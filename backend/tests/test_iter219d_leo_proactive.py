"""iter219d — Leo Proativo: testes do detector + envio + cooldown +
seeding de conversation_state + endpoint REST + regression iter219c/iter218.

Cobre:
 1. services.leo_proactive.try_proactive_notifications retorna {ok:False, reason:'phone não configurado'} sem phone
 2. _detect_zero_redemption_promos retorna a promo seed (>3 dias, zero resgates)
 3. e2e mock: ao rodar leo proativo com _send mockado, conversation_state é populado
    com proposta + motor_ia_proactive_notifications gravado + 2a execução pulada por cooldown
 4. presidente_ia.proactive_scan() retorna campo 'leo_proactive'
 5. POST /api/presidente-ia/leo/proactive (REST) retorna shape esperado
 6. e2e iter219c continuation: após proposta seedada via leo proativo, "sim" do gestor
    dispara exec_pause_promo
 7. Regression iter218: GET /api/presidente-ia/dashboard 200
 8. Regression iter219c: ask() ainda persiste history (≤6 msgs FIFO) e exec_* visiveis
"""
from __future__ import annotations

import os
import sys
import asyncio
import pytest
import requests

BACKEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
CID = "co-demo"
TEST_PHONE = "5511999900001"
WHO_FIFO = "+5511999900099"

from services import leo_proactive as lp  # noqa: E402
from services import presidente_ia as pia  # noqa: E402
from services import secretaria_ia as sia  # noqa: E402
from database import db  # noqa: E402


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


async def _cleanup_state():
    """Limpa cooldowns + conversation_state do telefone de teste."""
    await db.motor_ia_proactive_notifications.delete_many(
        {"company_id": CID})
    await db.secretaria_conversation_state.delete_one(
        {"company_id": CID, "who": TEST_PHONE})


async def _set_briefing_phone(phone: str):
    """Configura presidente_briefing_phone."""
    await db.conselho_ia_settings.update_one(
        {"company_id": CID},
        {"$set": {"company_id": CID,
                  "presidente_briefing_phone": phone}},
        upsert=True)


async def _unset_briefing_phone():
    await db.conselho_ia_settings.update_one(
        {"company_id": CID},
        {"$unset": {"presidente_briefing_phone": "",
                    "notify_phone": ""}})


# ============================================================
# 1) phone não configurado → ok:False
# ============================================================
def test_returns_not_configured_without_phone():
    async def go():
        # snapshot original
        cfg_before = await db.conselho_ia_settings.find_one(
            {"company_id": CID}, {"_id": 0}) or {}
        try:
            await _unset_briefing_phone()
            res = await lp.try_proactive_notifications(CID)
            assert res["ok"] is False
            assert "phone" in (res.get("reason") or "").lower()
            assert res["sent"] == 0
        finally:
            # restaura
            if cfg_before.get("presidente_briefing_phone"):
                await _set_briefing_phone(
                    cfg_before["presidente_briefing_phone"])
    _run(go())


# ============================================================
# 2) detector zero_redemption_promos pega promo seed
# ============================================================
def test_detector_zero_redemption_promos_finds_seed():
    async def go():
        msgs = await lp._detect_zero_redemption_promos(CID)
        # Deve ter pelo menos 1 candidato (promo seed pr-f0f9158f606b)
        assert isinstance(msgs, list)
        assert len(msgs) >= 1, \
            f"detector vazio — esperado >=1 promo zerada. msgs={msgs}"
        for key, kind, text in msgs:
            assert key.startswith("promo:")
            assert kind == "pause_promo"
            assert "Confirma?" in text
            assert "sim" in text.lower()
    _run(go())


# ============================================================
# 3) e2e mock _send → conversation_state + cooldown
# ============================================================
@pytest.mark.timeout(60)
def test_e2e_mock_send_seeds_state_and_cooldown(monkeypatch):
    async def go():
        await _cleanup_state()
        await _set_briefing_phone(TEST_PHONE)
        try:
            sent_calls = []

            async def fake_send(phone, text):
                sent_calls.append({"phone": phone, "text": text})
                return {"ok": True}

            monkeypatch.setattr(lp, "_send", fake_send)

            # 1a execução
            r1 = await lp.try_proactive_notifications(CID)
            assert r1["ok"] is True, f"r1: {r1}"
            assert r1["phone"] == TEST_PHONE
            assert r1["sent"] >= 1, \
                f"esperado pelo menos 1 envio. r1={r1}"
            assert r1["skipped_cooldown"] == 0
            assert isinstance(r1["details"], list)
            # Pelo menos 1 detalhe ok:True
            ok_details = [d for d in r1["details"] if d.get("ok")]
            assert len(ok_details) >= 1
            assert len(sent_calls) == r1["sent"]

            # verifica conversation_state populado com proposta
            state = await db.secretaria_conversation_state.find_one(
                {"company_id": CID, "who": TEST_PHONE},
                {"_id": 0})
            assert state is not None, \
                "conversation_state NÃO foi gravado"
            msgs = state.get("messages") or []
            assert len(msgs) >= 1
            # último(s) devem ser do assistant (Leo)
            last_assistants = [m for m in msgs
                               if m["role"] == "assistant"]
            assert len(last_assistants) >= 1
            assert "Confirma?" in last_assistants[-1]["content"]

            # verifica registro em motor_ia_proactive_notifications
            recs = await db.motor_ia_proactive_notifications.find(
                {"company_id": CID}, {"_id": 0}).to_list(10)
            assert len(recs) >= 1
            for r in recs:
                assert r.get("kind")
                assert r.get("key")
                assert r.get("sent_at")
                assert r.get("text")

            # 2a execução — deve pular por cooldown
            sent_before = len(sent_calls)
            r2 = await lp.try_proactive_notifications(CID)
            assert r2["ok"] is True
            assert r2["sent"] == 0, \
                f"2a exec deveria pular tudo. r2={r2}"
            assert r2["skipped_cooldown"] >= 1
            # _send não pode ser chamado novamente
            assert len(sent_calls) == sent_before
        finally:
            await _cleanup_state()

    _run(go())


# ============================================================
# 4) presidente_ia.proactive_scan() retorna campo leo_proactive
# ============================================================
@pytest.mark.timeout(60)
def test_proactive_scan_returns_leo_proactive_field(monkeypatch):
    async def go():
        await _cleanup_state()
        # sem phone → leo proativo retorna ok:False mas o campo deve existir
        await _unset_briefing_phone()
        try:
            res = await pia.proactive_scan(CID)
            assert isinstance(res, dict)
            assert res.get("ok") is True
            # shape original ainda existe
            for k in ("health", "risks", "opportunities",
                      "predictions", "correlations"):
                assert k in res, f"campo {k} sumiu do proactive_scan"
            # novo campo iter219d
            assert "leo_proactive" in res, \
                "campo leo_proactive ausente"
            assert isinstance(res["leo_proactive"], dict)
            # sem phone, sent=0
            assert res["leo_proactive"].get("sent") == 0
        finally:
            await _cleanup_state()

    _run(go())


# ============================================================
# 5) Endpoint REST POST /api/presidente-ia/leo/proactive
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


def test_endpoint_leo_proactive_without_phone(admin_token):
    """Sem phone configurado, endpoint retorna ok:False."""
    async def reset():
        await _cleanup_state()
        await _unset_briefing_phone()
    _run(reset())

    h = {"Authorization": f"Bearer {admin_token}"}
    r = requests.post(f"{BASE_URL}/api/presidente-ia/leo/proactive",
                      headers=h, timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    body = r.json()
    assert body.get("ok") is False
    assert body.get("sent") == 0
    assert "phone" in (body.get("reason") or "").lower()


def test_endpoint_leo_proactive_with_phone_shape(admin_token):
    """Com phone configurado, endpoint retorna shape completo
    (sent>=0, details list, total_candidates). Envio real falha sem
    sidecar pareado — esperamos details com ok:False ou sent=0."""
    async def setup():
        await _cleanup_state()
        await _set_briefing_phone(TEST_PHONE)
    _run(setup())

    try:
        h = {"Authorization": f"Bearer {admin_token}"}
        r = requests.post(
            f"{BASE_URL}/api/presidente-ia/leo/proactive",
            headers=h, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        body = r.json()
        assert body.get("ok") is True
        assert body.get("phone") == TEST_PHONE
        assert "sent" in body
        assert "skipped_cooldown" in body
        assert "details" in body and isinstance(body["details"], list)
        assert "total_candidates" in body
        assert body["total_candidates"] >= 0
    finally:
        _run(_cleanup_state())


# ============================================================
# 6) e2e continuation iter219c: após proposta seedada, "sim" → exec_pause_promo
# ============================================================
@pytest.mark.timeout(120)
def test_e2e_proposal_then_sim_executes_pause_promo(monkeypatch):
    """Seed conversation_state com proposta de pausar promo X,
    então gestor responde 'sim' via ask() — exec_pause_promo deve
    ser chamada pelo LLM."""
    async def go():
        # pegar promo ativa
        p = await db.parcerias_promotions.find_one(
            {"company_id": CID, "active": True},
            {"_id": 0, "id": 1, "title": 1})
        if not p:
            pytest.skip("nenhuma promo ativa disponível")
        promo_id = p["id"]

        await _cleanup_state()
        await _set_briefing_phone(TEST_PHONE)

        async def fake_send(phone, text):
            return {"ok": True}
        monkeypatch.setattr(lp, "_send", fake_send)

        try:
            # Seed: roda leo proativo (gera proposta para promo zerada)
            r1 = await lp.try_proactive_notifications(CID)
            assert r1["sent"] >= 1, f"seed falhou: {r1}"

            # Verifica que a proposta menciona algum promo_id na conv
            state = await db.secretaria_conversation_state.find_one(
                {"company_id": CID, "who": TEST_PHONE},
                {"_id": 0})
            assert state is not None
            assistant_msgs = [m for m in state["messages"]
                              if m["role"] == "assistant"]
            assert assistant_msgs
            proposal_text = assistant_msgs[-1]["content"]
            # extrai promo_id mencionada
            import re
            m = re.search(r"(pr-[a-f0-9]+)", proposal_text)
            assert m, f"proposta não tem promo_id: {proposal_text}"
            proposed_promo_id = m.group(1)

            # Gestor responde "sim"
            t2 = await sia.ask(CID, "sim, pode pausar",
                               channel="whatsapp", who=TEST_PHONE)
            tools2 = [t["name"] for t in t2.get("tools_used", [])]
            print("\n[t2-sim] answer:", t2.get("answer"))
            print("[t2-sim] tools:", tools2)
            assert "exec_pause_promo" in tools2, \
                ("Leo NÃO chamou exec_pause_promo após 'sim'. "
                 f"tools={tools2}, answer={t2.get('answer')}")

            # restaura promo
            promo_after = await db.parcerias_promotions.find_one(
                {"company_id": CID, "id": proposed_promo_id},
                {"_id": 0, "active": 1})
            if promo_after and promo_after.get("active") is False:
                await db.parcerias_promotions.update_one(
                    {"company_id": CID, "id": proposed_promo_id},
                    {"$set": {"active": True}})
        finally:
            # restaura promo principal se foi alterada
            await db.parcerias_promotions.update_one(
                {"company_id": CID, "id": promo_id},
                {"$set": {"active": True}})
            await _cleanup_state()

    _run(go())


# ============================================================
# 7) Regression iter218: GET /api/presidente-ia/dashboard
# ============================================================
def test_regression_dashboard(admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    r = requests.get(f"{BASE_URL}/api/presidente-ia/dashboard",
                     headers=h, timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    body = r.json()
    assert "health" in body
    assert "risks" in body


# ============================================================
# 8) Regression iter219c: history FIFO ≤ 6 + exec_* visiveis
# ============================================================
def test_regression_iter219c_exec_tools_still_visible():
    names = [(t.get("function") or {}).get("name")
             for t in sia.TOOLS_SPEC]
    for n in ("exec_pause_promo", "exec_escalate_dunning",
              "exec_assign_technician", "exec_flag_dunning",
              "exec_create_inspection_ticket"):
        assert n in names, f"{n} sumiu de sia.TOOLS_SPEC"


def test_regression_iter219c_history_fifo_capped_6():
    async def go():
        await db.secretaria_conversation_state.delete_one(
            {"company_id": CID, "who": WHO_FIFO})

        async def fake_chat(cid, messages):
            return {"message": {"content": f"resp-{len(messages)}"}}

        import services.secretaria_ia as siamod
        original = siamod._chat_with_tools
        siamod._chat_with_tools = fake_chat
        try:
            for i in range(5):
                await sia.ask(CID, f"pergunta {i}",
                              channel="whatsapp", who=WHO_FIFO)
        finally:
            siamod._chat_with_tools = original

        doc = await db.secretaria_conversation_state.find_one(
            {"company_id": CID, "who": WHO_FIFO}, {"_id": 0})
        assert doc is not None
        assert len(doc["messages"]) <= 6
        await db.secretaria_conversation_state.delete_one(
            {"company_id": CID, "who": WHO_FIFO})

    _run(go())
