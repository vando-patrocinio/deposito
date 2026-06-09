"""iter219c — Leo (Secretária IA) com superpoderes de execução com confirmação.

Cobre:
 1. SYSTEM_PROMPT contém regras de confirmação ("Confirma?", "só chame a tool...sim/confirmo")
 2. secretaria_tools expõe 5 novas exec_* tools em TOOLS_SPEC_EXTRA + TOOL_FUNCS_EXTRA
 3. Cada exec_* delega para services.agent_tools.execute_tool_call
 4. ask() persiste/carrega histórico em db.secretaria_conversation_state (último 6)
 5. e2e turno 1: "pause a promo X" => Leo responde "Confirma?" SEM chamar exec_*
 6. e2e turno 2 SIM: "sim, pode pausar" => Leo chama exec_pause_promo, promo vira active=False
 7. e2e turno 2 NÃO: "não, espera" => nenhuma exec chamada
 8. FIFO: 6+ turnos mantém só últimas 6 mensagens
 9. Regression: as 5 tools NÃO destrutivas (corporate_health, top_risks, top_opportunities,
    clients_at_risk, presidente_scan) continuam funcionando
10. Regression iter218: GET /api/presidente-ia/dashboard e /conselho 200
"""
from __future__ import annotations

import os
import sys
import asyncio
import pytest
import requests

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
CID = "co-demo"
WHO_TURN = "+5511999900001"
WHO_NO = "+5511999900002"
WHO_FIFO = "+5511999900003"

from services import secretaria_tools as st  # noqa: E402
from services import secretaria_ia as sia  # noqa: E402
from database import db  # noqa: E402


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ============================================================
# 1) SYSTEM_PROMPT contém regras de confirmação
# ============================================================
def test_system_prompt_confirmation_rules():
    sp = sia.SYSTEM_PROMPT
    assert "Confirma?" in sp, "SYSTEM_PROMPT não menciona 'Confirma?'"
    # checa palavras "sim" e "confirmo" + descreve gate
    assert "sim" in sp.lower() and "confirmo" in sp.lower()
    # menciona AÇÕES DESTRUTIVAS / exec_*
    assert "exec_pause_promo" in sp
    assert ("destrut" in sp.lower() or "destrutiv" in sp.lower())


# ============================================================
# 2) Specs e funcs das 5 novas exec_* tools
# ============================================================
EXEC_TOOLS = [
    "exec_pause_promo",
    "exec_escalate_dunning",
    "exec_assign_technician",
    "exec_flag_dunning",
    "exec_create_inspection_ticket",
]


def test_exec_tools_in_spec_extra():
    names = [(t.get("function") or {}).get("name") for t in st.TOOLS_SPEC_EXTRA]
    for n in EXEC_TOOLS:
        assert n in names, f"{n} ausente em TOOLS_SPEC_EXTRA"


def test_exec_tools_in_func_extra():
    for n in EXEC_TOOLS:
        assert n in st.TOOL_FUNCS_EXTRA, f"{n} ausente em TOOL_FUNCS_EXTRA"
        assert callable(st.TOOL_FUNCS_EXTRA[n])


def test_exec_tools_visible_in_final_TOOLS_SPEC():
    names = [(t.get("function") or {}).get("name") for t in sia.TOOLS_SPEC]
    for n in EXEC_TOOLS:
        assert n in names, f"{n} ausente em sia.TOOLS_SPEC final"


# ============================================================
# 3) exec_* delega para services.agent_tools.execute_tool_call
# ============================================================
def test_exec_pause_promo_delegates(monkeypatch):
    """Mocka execute_tool_call e verifica payload."""
    captured = {}

    async def fake_exec(company_id, payload):
        captured["company_id"] = company_id
        captured["payload"] = payload
        return {"status": "ok", "result": {"paused": True},
                "error": None, "action_id": "act-test"}

    import services.agent_tools as at
    monkeypatch.setattr(at, "execute_tool_call", fake_exec)

    res = _run(st._tool_exec_pause_promo(
        CID, {"promotion_id": "pr-test", "reason": "teste"}))
    assert res["status"] == "ok"
    assert res["tool"] == "pause_promo_inactive"
    assert res["action_id"] == "act-test"
    assert captured["company_id"] == CID
    assert captured["payload"]["tool"] == "pause_promo_inactive"
    assert captured["payload"]["args"]["promotion_id"] == "pr-test"


# ============================================================
# 4) Persistência do histórico em db.secretaria_conversation_state
# ============================================================
def test_history_persisted_and_capped_to_6():
    async def go():
        # limpa
        await db.secretaria_conversation_state.delete_one(
            {"company_id": CID, "who": WHO_FIFO})

        # Mock chat para evitar custos de LLM — força resposta sem tools
        async def fake_chat(cid, messages):
            return {"message": {"content": f"resp-{len(messages)}"}}

        import services.secretaria_ia as siamod
        original = siamod._chat_with_tools
        siamod._chat_with_tools = fake_chat
        try:
            for i in range(5):
                await sia.ask(CID, f"pergunta {i}", channel="whatsapp",
                              who=WHO_FIFO)
        finally:
            siamod._chat_with_tools = original

        doc = await db.secretaria_conversation_state.find_one(
            {"company_id": CID, "who": WHO_FIFO}, {"_id": 0})
        assert doc is not None, "secretaria_conversation_state não foi gravado"
        assert "messages" in doc
        assert "updated_at" in doc
        # FIFO: máximo 6 (3 turnos de user+assistant)
        assert len(doc["messages"]) <= 6, \
            f"histórico não capped em 6: len={len(doc['messages'])}"
        # Última deve ser assistant da pergunta 4
        assert doc["messages"][-1]["role"] == "assistant"
        # cleanup
        await db.secretaria_conversation_state.delete_one(
            {"company_id": CID, "who": WHO_FIFO})

    _run(go())


# ============================================================
# 5+6+7) e2e Turno 1 (proposta) + Turno 2 (SIM) + Turno 2 (NÃO)
# ============================================================
@pytest.fixture(scope="module")
def promo_id():
    async def go():
        p = await db.parcerias_promotions.find_one(
            {"company_id": CID, "active": True}, {"_id": 0, "id": 1})
        if not p:
            pytest.skip("nenhuma promo ativa em parcerias_promotions")
        return p["id"]
    return _run(go())


@pytest.mark.timeout(90)
def test_e2e_turno1_proposta_e_turno2_sim(promo_id):
    """Turno 1: pede pausa — Leo deve propor 'Confirma?'.
    Turno 2: 'sim' — Leo executa exec_pause_promo, promo vira active=False.
    Reverte no finally.
    """
    async def go():
        await db.secretaria_conversation_state.delete_one(
            {"company_id": CID, "who": WHO_TURN})
        try:
            # Turno 1 — proposta
            t1 = await sia.ask(
                CID,
                f"Leo, pause a promo {promo_id}",
                channel="whatsapp", who=WHO_TURN)
            ans1 = (t1.get("answer") or "").lower()
            tools1 = [t["name"] for t in t1.get("tools_used", [])]
            print("\n[t1] answer:", t1.get("answer"))
            print("[t1] tools:", tools1)
            assert "confirma" in ans1, \
                f"turno1: Leo não pediu confirmação. ans={t1.get('answer')}"
            assert "exec_pause_promo" not in tools1, \
                f"turno1: Leo executou sem confirmar! tools={tools1}"

            # Turno 2 — SIM
            t2 = await sia.ask(
                CID, "sim, pode pausar",
                channel="whatsapp", who=WHO_TURN)
            tools2 = [t["name"] for t in t2.get("tools_used", [])]
            print("\n[t2-sim] answer:", t2.get("answer"))
            print("[t2-sim] tools:", tools2)
            assert "exec_pause_promo" in tools2, \
                f"turno2 SIM: exec_pause_promo NÃO chamada. tools={tools2}"

            # Verifica no banco
            promo_after = await db.parcerias_promotions.find_one(
                {"company_id": CID, "id": promo_id},
                {"_id": 0, "active": 1})
            assert promo_after is not None
            assert promo_after.get("active") is False, \
                f"promo NÃO foi pausada. active={promo_after.get('active')}"

            # Verifica que exec_pause_promo recebeu o promotion_id correto
            pause_call = next(
                (t for t in t2.get("tools_used") if t["name"] == "exec_pause_promo"),
                None)
            assert pause_call is not None
            assert pause_call["args"].get("promotion_id") == promo_id, \
                f"promotion_id incorreto: {pause_call['args']}"
        finally:
            # Restaura promo
            await db.parcerias_promotions.update_one(
                {"company_id": CID, "id": promo_id},
                {"$set": {"active": True}})
            await db.secretaria_conversation_state.delete_one(
                {"company_id": CID, "who": WHO_TURN})

    _run(go())


@pytest.mark.timeout(90)
def test_e2e_turno2_nao_cancela(promo_id):
    """Turno 1: pede pausa. Turno 2: 'não'. NÃO deve executar nada."""
    async def go():
        await db.secretaria_conversation_state.delete_one(
            {"company_id": CID, "who": WHO_NO})
        try:
            t1 = await sia.ask(
                CID, f"Leo, pause a promo {promo_id}",
                channel="whatsapp", who=WHO_NO)
            ans1 = (t1.get("answer") or "").lower()
            assert "confirma" in ans1, \
                f"turno1(no): sem 'confirma'. {t1.get('answer')}"

            t2 = await sia.ask(
                CID, "não, espera",
                channel="whatsapp", who=WHO_NO)
            tools2 = [t["name"] for t in t2.get("tools_used", [])]
            print("\n[t2-nao] answer:", t2.get("answer"))
            print("[t2-nao] tools:", tools2)
            assert "exec_pause_promo" not in tools2, \
                f"turno2 NÃO: Leo executou mesmo após 'não'. tools={tools2}"
            for n in EXEC_TOOLS:
                assert n not in tools2, f"exec {n} chamada após 'não'"

            # Promo continua ativa
            promo_after = await db.parcerias_promotions.find_one(
                {"company_id": CID, "id": promo_id},
                {"_id": 0, "active": 1})
            assert promo_after.get("active") is True, \
                "promo não deveria ter sido alterada"
        finally:
            await db.parcerias_promotions.update_one(
                {"company_id": CID, "id": promo_id},
                {"$set": {"active": True}})
            await db.secretaria_conversation_state.delete_one(
                {"company_id": CID, "who": WHO_NO})

    _run(go())


# ============================================================
# 8) Regression: 5 tools NÃO destrutivas continuam funcionando
# ============================================================
def test_regression_corporate_health():
    res = _run(st._tool_corporate_health(CID, {}))
    assert isinstance(res, dict)
    assert "score" in res and "status" in res


def test_regression_top_risks():
    res = _run(st._tool_top_risks(CID, {"limit": 3}))
    assert "total" in res and "top" in res


def test_regression_top_opportunities():
    res = _run(st._tool_top_opportunities(CID, {"limit": 3}))
    assert "total" in res and "receita_potencial_brl" in res


def test_regression_clients_at_risk():
    res = _run(st._tool_clients_at_risk(CID, {"limit": 3}))
    assert "total" in res and "items" in res


def test_regression_presidente_scan():
    res = _run(st._tool_presidente_scan(CID, {}))
    assert "ok" in res and "health_score" in res


# ============================================================
# 9) Regression iter218: REST endpoints
# ============================================================
@pytest.fixture(scope="module")
def admin_token():
    if not BASE_URL:
        pytest.skip("REACT_APP_BACKEND_URL não configurado")
    r = requests.post(f"{BASE_URL}/api/auth/login",
                     json={"email": "admin@empresa.com",
                           "password": "123456"}, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"login admin falhou: {r.status_code}")
    return r.json().get("access_token")


def test_regression_presidente_dashboard(admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    r = requests.get(f"{BASE_URL}/api/presidente-ia/dashboard",
                     headers=h, timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    body = r.json()
    assert isinstance(body, dict)
    # shape esperado
    assert "health" in body or "score" in body or "ok" in body


def test_regression_presidente_conselho(admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    r = requests.get(f"{BASE_URL}/api/presidente-ia/conselho",
                     headers=h, timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
