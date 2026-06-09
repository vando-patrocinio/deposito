"""iter219b — Leo (Secretária IA) conectado ao Presidente IA.

Testa:
 1. secretaria_tools expõe 5 novas tools em TOOLS_SPEC_EXTRA + TOOL_FUNCS_EXTRA
 2. Cada tool nova retorna o shape esperado
 3. manager_assistant._is_manager_phone reconhece presidente_briefing_phone e notify_phone
 4. SYSTEM_PROMPT da Secretária IA cita "Presidente IA" e "Leo"
 5. e2e ask() responde sobre saúde, riscos, oportunidades e churn usando as novas tools
 6. usage_log em secretaria_log é registrado
 7. Regression: tools antigas (whatsapp_activity_summary, revenue_summary, list_olts) continuam ok

Executa direto sobre os módulos do backend (sem HTTP) + um teste via REST para
PUT /api/presidente-ia/briefing/settings.
"""
from __future__ import annotations

import os
import sys
import asyncio
import pytest
import requests

# Garante que `/app/backend` está no path
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
CID = "co-demo"
TEST_PHONE = "5511999998888"

# ============================================================
# Imports do backend (após sys.path ajustado)
# ============================================================
from services import secretaria_tools as st  # noqa: E402
from services import secretaria_ia as sia  # noqa: E402
from services import manager_assistant as ma  # noqa: E402
from database import db  # noqa: E402


# ============================================================
# Helpers
# ============================================================
def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ============================================================
# 1) Estrutura: TOOLS_SPEC_EXTRA e TOOL_FUNCS_EXTRA
# ============================================================
NEW_TOOLS = ["corporate_health", "top_risks", "top_opportunities",
             "clients_at_risk", "presidente_scan"]


def test_new_tools_in_spec_extra():
    names = [(t.get("function") or {}).get("name") for t in st.TOOLS_SPEC_EXTRA]
    for n in NEW_TOOLS:
        assert n in names, f"tool '{n}' não está em TOOLS_SPEC_EXTRA"


def test_new_tools_in_func_extra():
    for n in NEW_TOOLS:
        assert n in st.TOOL_FUNCS_EXTRA, f"tool '{n}' não está em TOOL_FUNCS_EXTRA"
        assert callable(st.TOOL_FUNCS_EXTRA[n])


def test_new_tools_visible_in_secretaria_tools_spec():
    """secretaria_ia.TOOLS_SPEC já deve incluir as novas tools via extend."""
    names = [(t.get("function") or {}).get("name") for t in sia.TOOLS_SPEC]
    for n in NEW_TOOLS:
        assert n in names, f"tool '{n}' não está em TOOLS_SPEC final do secretaria_ia"


# ============================================================
# 2) Shape de cada tool nova
# ============================================================
def test_corporate_health_shape():
    res = _run(st._tool_corporate_health(CID, {}))
    assert isinstance(res, dict)
    assert "score" in res
    assert "status" in res
    assert "components" in res
    assert isinstance(res["components"], (dict, list))


def test_top_risks_shape():
    res = _run(st._tool_top_risks(CID, {"limit": 5}))
    assert isinstance(res, dict)
    assert "total" in res
    assert "criticos" in res
    assert "altos" in res
    assert "medios" in res
    assert "top" in res
    assert isinstance(res["top"], list)


def test_top_opportunities_shape():
    res = _run(st._tool_top_opportunities(CID, {"limit": 5}))
    assert isinstance(res, dict)
    assert "total" in res
    assert "receita_potencial_brl" in res
    assert "top" in res
    assert isinstance(res["top"], list)


def test_clients_at_risk_shape():
    res = _run(st._tool_clients_at_risk(CID, {"limit": 5}))
    assert isinstance(res, dict)
    assert "total" in res
    assert "items" in res
    assert isinstance(res["items"], list)


def test_presidente_scan_shape():
    res = _run(st._tool_presidente_scan(CID, {}))
    assert isinstance(res, dict)
    assert "ok" in res
    assert "elapsed_ms" in res
    assert "health_score" in res
    # campos adicionais presentes
    for k in ("health_status", "risks_total", "opportunities_total"):
        assert k in res


# ============================================================
# 3) _is_manager_phone reconhece presidente_briefing_phone/notify_phone
# ============================================================
def test_is_manager_phone_presidente_briefing_phone():
    async def go():
        # Salva valor antigo
        old = await db.conselho_ia_settings.find_one(
            {"company_id": CID}, {"_id": 0}) or {}
        try:
            await db.conselho_ia_settings.update_one(
                {"company_id": CID},
                {"$set": {"company_id": CID,
                          "presidente_briefing_phone": TEST_PHONE,
                          "notify_phone": ""}},
                upsert=True)
            ok = await ma._is_manager_phone(CID, TEST_PHONE)
            assert ok is True, "presidente_briefing_phone NÃO foi reconhecido"

            # Outro número não deve bater
            ko = await ma._is_manager_phone(CID, "5500000000000")
            assert ko is False

            # Também testa notify_phone
            await db.conselho_ia_settings.update_one(
                {"company_id": CID},
                {"$set": {"presidente_briefing_phone": "",
                          "notify_phone": TEST_PHONE}})
            ok2 = await ma._is_manager_phone(CID, TEST_PHONE)
            assert ok2 is True, "notify_phone NÃO foi reconhecido"
        finally:
            # Restaura
            await db.conselho_ia_settings.update_one(
                {"company_id": CID},
                {"$set": {"presidente_briefing_phone":
                              old.get("presidente_briefing_phone") or "",
                          "notify_phone":
                              old.get("notify_phone") or ""}})
    _run(go())


# ============================================================
# 4) SYSTEM_PROMPT
# ============================================================
def test_system_prompt_mentions_presidente_and_leo():
    sp = sia.SYSTEM_PROMPT
    assert "Presidente IA" in sp, "SYSTEM_PROMPT não menciona 'Presidente IA'"
    assert "Leo" in sp, "SYSTEM_PROMPT não menciona 'Leo'"


# ============================================================
# 5) e2e ask() — pipeline real com LLM + tool-use
# ============================================================
# Estes testes consomem o Motor IA. Podem demorar até ~30s cada.
@pytest.fixture(scope="module")
def setup_phone():
    async def go():
        old = await db.conselho_ia_settings.find_one(
            {"company_id": CID}, {"_id": 0}) or {}
        await db.conselho_ia_settings.update_one(
            {"company_id": CID},
            {"$set": {"company_id": CID,
                      "presidente_briefing_phone": TEST_PHONE,
                      "presidente_briefing_enabled": True}},
            upsert=True)
        return old
    old = _run(go())
    yield
    async def restore():
        await db.conselho_ia_settings.update_one(
            {"company_id": CID},
            {"$set": {"presidente_briefing_phone":
                          old.get("presidente_briefing_phone") or "",
                      "presidente_briefing_enabled":
                          bool(old.get("presidente_briefing_enabled"))}})
    _run(restore())


@pytest.mark.timeout(60)
def test_ask_saude_da_empresa(setup_phone):
    res = _run(sia.ask(CID, "oi Leo, como está a saúde da empresa?",
                        channel="whatsapp", who=TEST_PHONE))
    ans = (res.get("answer") or "").lower()
    print("\n[saude] answer:", res.get("answer"))
    print("[saude] tools:", [t["name"] for t in res.get("tools_used", [])])
    tools_called = [t["name"] for t in res.get("tools_used", [])]
    # Deve ter usado corporate_health OU presidente_scan
    assert any(t in tools_called for t in ("corporate_health",
                                              "presidente_scan")), \
        f"Nenhuma tool de saúde corporativa chamada. Tools: {tools_called}"
    # Resposta deve mencionar score ou status
    assert any(w in ans for w in ("85", "saudavel", "saudável", "score",
                                       "status", "atenção", "atencao",
                                       "alerta", "critic")), \
        f"Resposta não menciona saúde: {res.get('answer')}"


@pytest.mark.timeout(60)
def test_ask_riscos_hoje(setup_phone):
    res = _run(sia.ask(CID, "quais riscos hoje?",
                        channel="whatsapp", who=TEST_PHONE))
    ans = (res.get("answer") or "").lower()
    print("\n[riscos] answer:", res.get("answer"))
    print("[riscos] tools:", [t["name"] for t in res.get("tools_used", [])])
    tools_called = [t["name"] for t in res.get("tools_used", [])]
    assert "top_risks" in tools_called or "presidente_scan" in tools_called, \
        f"top_risks não chamada. Tools: {tools_called}"
    # aceita menção a tickets, operação, risco ou ao número 620
    assert any(w in ans for w in ("620", "ticket", "opera", "risc", "crít",
                                       "alto", "médio", "medio")), \
        f"Resposta não menciona risco. {res.get('answer')}"


@pytest.mark.timeout(60)
def test_ask_oportunidade_receita(setup_phone):
    res = _run(sia.ask(CID, "onde tem oportunidade de receita?",
                        channel="whatsapp", who=TEST_PHONE))
    ans = (res.get("answer") or "").lower()
    print("\n[oportu] answer:", res.get("answer"))
    print("[oportu] tools:", [t["name"] for t in res.get("tools_used", [])])
    tools_called = [t["name"] for t in res.get("tools_used", [])]
    assert "top_opportunities" in tools_called \
        or "presidente_scan" in tools_called, \
        f"top_opportunities não chamada. Tools: {tools_called}"
    assert any(w in ans for w in ("security", "6.83", "6.86", "6.8", "6836",
                                       "6866", "oportunid", "upsell",
                                       "cross", "receita", "r$")), \
        f"Resposta não menciona oportunidade. {res.get('answer')}"


@pytest.mark.timeout(60)
def test_ask_churn_clientes_em_risco(setup_phone):
    res = _run(sia.ask(CID, "quem está em risco de churn?",
                        channel="whatsapp", who=TEST_PHONE))
    ans = (res.get("answer") or "").lower()
    print("\n[churn] answer:", res.get("answer"))
    print("[churn] tools:", [t["name"] for t in res.get("tools_used", [])])
    # Deve responder sem exception. Aceita "nenhum" ou listagem.
    assert res.get("answer"), "ask() retornou vazio"
    # Tool clients_at_risk ou churn_summary aceita
    tools_called = [t["name"] for t in res.get("tools_used", [])]
    assert any(t in tools_called for t in
                ("clients_at_risk", "churn_summary",
                 "list_overdue_subscribers")), \
        f"Nenhuma tool de churn chamada. Tools: {tools_called}"


# ============================================================
# 6) usage_log em secretaria_log
# ============================================================
@pytest.mark.timeout(60)
def test_secretaria_log_persisted(setup_phone):
    async def go():
        marker = "TEST_ITER219_LOG_MARKER"
        await sia.ask(CID, marker, channel="whatsapp", who=TEST_PHONE)
        # Procura registro com a question contendo o marker
        doc = await db.secretaria_log.find_one(
            {"company_id": CID, "question": {"$regex": marker}},
            sort=[("created_at", -1)])
        assert doc is not None, "secretaria_log NÃO registrou a chamada"
        assert "answer" in doc
        assert "tools_used" in doc
        assert "iterations" in doc
        assert doc.get("channel") == "whatsapp"
    _run(go())


# ============================================================
# 7) Regression: tools antigas continuam funcionando
# ============================================================
def test_regression_whatsapp_activity_summary():
    res = _run(st._tool_whatsapp_activity_summary(CID, {}))
    assert isinstance(res, dict)
    assert "msgs_received" in res
    assert "msgs_sent" in res
    assert "open_conversations" in res


def test_regression_revenue_summary():
    res = _run(st._tool_revenue_summary(CID, {}))
    assert isinstance(res, dict)
    assert "active_subscribers" in res
    assert "mrr_brl" in res
    assert "top_plans" in res


def test_regression_list_olts():
    res = _run(st._tool_list_olts(CID, {}))
    assert isinstance(res, dict)
    assert "count" in res
    assert "olts" in res


def test_regression_smartolt_status():
    res = _run(sia._tool_smartolt_status(CID, {}))
    assert isinstance(res, dict)
    assert "olts" in res
    assert "onus_total" in res


# ============================================================
# 8) PUT /api/presidente-ia/briefing/settings via REST (auth)
# ============================================================
@pytest.fixture(scope="module")
def admin_token():
    if not BASE_URL:
        pytest.skip("REACT_APP_BACKEND_URL não configurado")
    r = requests.post(f"{BASE_URL}/api/auth/login",
                       json={"email": "admin@empresa.com",
                              "password": "123456"}, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"Login admin falhou: {r.status_code} {r.text[:200]}")
    return r.json().get("access_token")


def test_briefing_settings_put(admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    payload = {"enabled": True, "phone": TEST_PHONE}
    r = requests.put(f"{BASE_URL}/api/presidente-ia/briefing/settings",
                       json=payload, headers=h, timeout=15)
    assert r.status_code == 200, f"PUT settings falhou: {r.status_code} {r.text[:200]}"
    body = r.json()
    assert body.get("ok") is True
    assert body.get("phone") == TEST_PHONE
    assert body.get("enabled") is True

    # GET deve refletir
    r2 = requests.get(f"{BASE_URL}/api/presidente-ia/briefing/settings",
                        headers=h, timeout=15)
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2.get("phone") == TEST_PHONE
    assert body2.get("enabled") is True


def test_briefing_preview(admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    r = requests.get(f"{BASE_URL}/api/presidente-ia/briefing/preview",
                       headers=h, timeout=60)
    assert r.status_code == 200, f"preview falhou: {r.status_code} {r.text[:200]}"
    body = r.json()
    # Espera um texto/string ou dict com texto
    assert body is not None
