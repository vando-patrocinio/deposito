"""Iter78 — Test P0 fixes:
1. GET /api/smartolt/onu/{external_id}/actions endpoint
2. ALVARO IA: _is_automatic_message filter
3. ALVARO IA: _build_conversation_text skips auto_reply
4. ALVARO IA: run_daily_analysis skips pure-bot conversations
"""
import os
import sys
import asyncio
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback for tests not relying on HTTP
    BASE_URL = "http://localhost:8001"

# Make backend importable for unit tests on alvaro_ai
sys.path.insert(0, "/app/backend")


# ─────────────────────────── Fixtures ───────────────────────────
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "admin@empresa.com", "password": "123456"},
        timeout=15,
    )
    if r.status_code != 200:
        pytest.skip(f"Login failed: {r.status_code} {r.text[:200]}")
    data = r.json()
    tok = data.get("token") or data.get("access_token")
    assert tok, f"no token in response: {data}"
    return tok


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# ─────────── 1. GET /api/smartolt/onu/{external_id}/actions ───────────
class TestSmartoltOnuActions:
    def test_actions_endpoint_unknown_external_id(self, admin_headers):
        """Endpoint must return 200 with {count:0, items:[]} for fake external_id."""
        r = requests.get(
            f"{BASE_URL}/api/smartolt/onu/FAKE_EXT_ID_TEST_78/actions",
            headers=admin_headers,
            timeout=15,
        )
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:300]}"
        data = r.json()
        assert "count" in data, f"missing 'count' in: {data}"
        assert "items" in data, f"missing 'items' in: {data}"
        assert isinstance(data["items"], list)
        assert data["count"] == len(data["items"])
        # For a fake external_id no records exist
        assert data["count"] == 0
        assert data["items"] == []

    def test_actions_endpoint_limit_param(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/smartolt/onu/FAKE_EXT_ID_TEST_78/actions?limit=5",
            headers=admin_headers,
            timeout=15,
        )
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data.get("items"), list)

    def test_actions_endpoint_requires_auth(self):
        r = requests.get(
            f"{BASE_URL}/api/smartolt/onu/SOMEID/actions", timeout=10,
        )
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"


# ─────────── 2. ALVARO IA — _is_automatic_message ───────────
class TestAlvaroIsAutomaticMessage:
    def test_auto_reply_true_is_automatic(self):
        from services.alvaro_ai import _is_automatic_message
        assert _is_automatic_message({"auto_reply": True}) is True

    def test_auto_reply_false_is_not_automatic(self):
        from services.alvaro_ai import _is_automatic_message
        assert _is_automatic_message({"auto_reply": False, "direction": "outbound"}) is False

    def test_actor_ai_is_automatic(self):
        from services.alvaro_ai import _is_automatic_message
        assert _is_automatic_message({"actor": "ai"}) is True
        assert _is_automatic_message({"actor": "bot"}) is True
        assert _is_automatic_message({"actor": "system"}) is True
        assert _is_automatic_message({"actor": "auto"}) is True

    def test_actor_human_not_automatic(self):
        from services.alvaro_ai import _is_automatic_message
        assert _is_automatic_message({"actor": "human"}) is False
        assert _is_automatic_message({}) is False


# ─────────── 3. ALVARO IA — _build_conversation_text filter ───────────
class TestAlvaroBuildConversation:
    def test_filters_auto_reply_messages(self):
        from services.alvaro_ai import _build_conversation_text
        msgs = [
            {"direction": "inbound", "text": "minha internet caiu",
             "created_at": "2026-01-01T10:00:00"},
            {"direction": "outbound", "text": "RESPOSTA_BOT_AUTOMATICA",
             "auto_reply": True, "created_at": "2026-01-01T10:00:05"},
            {"direction": "outbound", "text": "Vou verificar pra você",
             "created_at": "2026-01-01T10:05:00"},
        ]
        out = _build_conversation_text(msgs)
        assert "minha internet caiu" in out
        assert "Vou verificar pra você" in out
        assert "RESPOSTA_BOT_AUTOMATICA" not in out, \
            f"auto_reply leaked: {out}"

    def test_filters_actor_ai_messages(self):
        from services.alvaro_ai import _build_conversation_text
        msgs = [
            {"direction": "inbound", "text": "ola", "created_at": "2026-01-01T10:00:00"},
            {"direction": "outbound", "actor": "ai", "text": "RESPOSTA_IA",
             "created_at": "2026-01-01T10:00:01"},
        ]
        out = _build_conversation_text(msgs)
        assert "ola" in out
        assert "RESPOSTA_IA" not in out

    def test_speaker_labels(self):
        from services.alvaro_ai import _build_conversation_text
        msgs = [
            {"direction": "inbound", "text": "oi", "created_at": "2026-01-01T10:00:00"},
            {"direction": "outbound", "text": "olá", "created_at": "2026-01-01T10:01:00"},
        ]
        out = _build_conversation_text(msgs)
        assert "CLIENTE:" in out
        assert "ATENDIMENTO:" in out


# ─────────── 4. ALVARO IA — run_daily_analysis skip pure-bot ───────────
class TestAlvaroRunDailyAnalysisSkipBot:
    """Validate the skip logic for pure-bot conversations.

    We can't easily call run_daily_analysis end-to-end in tests because it
    invokes the LLM. Instead we test the documented skip condition directly:
    human_outbound == 0 AND inbound_cnt < 2  -> skip.
    """

    def test_skip_condition_pure_bot(self):
        from services.alvaro_ai import _is_automatic_message
        # 1 inbound + only auto_reply outbound -> should be skipped
        msgs = [
            {"direction": "inbound", "text": "oi"},
            {"direction": "outbound", "text": "menu bot", "auto_reply": True},
        ]
        human_ob = sum(1 for m in msgs
                       if m.get("direction") == "outbound" and not _is_automatic_message(m))
        ib = sum(1 for m in msgs if m.get("direction") == "inbound")
        # SKIP condition: human_ob==0 AND ib<2
        assert human_ob == 0
        assert ib < 2
        assert (human_ob == 0 and ib < 2) is True, "should be skipped"

    def test_not_skip_when_human_replied(self):
        from services.alvaro_ai import _is_automatic_message
        msgs = [
            {"direction": "inbound", "text": "internet caiu"},
            {"direction": "outbound", "text": "vou ver", "auto_reply": False},
        ]
        human_ob = sum(1 for m in msgs
                       if m.get("direction") == "outbound" and not _is_automatic_message(m))
        ib = sum(1 for m in msgs if m.get("direction") == "inbound")
        assert human_ob >= 1
        assert (human_ob == 0 and ib < 2) is False

    def test_not_skip_when_2plus_inbound(self):
        msgs = [
            {"direction": "inbound", "text": "oi"},
            {"direction": "inbound", "text": "alguém aí?"},
            {"direction": "outbound", "text": "menu bot", "auto_reply": True},
        ]
        from services.alvaro_ai import _is_automatic_message
        human_ob = sum(1 for m in msgs
                       if m.get("direction") == "outbound" and not _is_automatic_message(m))
        ib = sum(1 for m in msgs if m.get("direction") == "inbound")
        assert ib >= 2
        assert (human_ob == 0 and ib < 2) is False
