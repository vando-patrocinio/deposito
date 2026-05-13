"""Tests for WhatsApp Baileys AI health + silent-failure persistence (iteration 56)."""
import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback to reading frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL"):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

WA_INBOUND_TOKEN = None
with open("/app/backend/.env") as f:
    for line in f:
        if line.startswith("WA_INBOUND_TOKEN"):
            WA_INBOUND_TOKEN = line.split("=", 1)[1].strip()
            break


@pytest.fixture(scope="module")
def access_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "admin@empresa.com", "password": "123456"},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token")
    assert tok, f"no access_token in response: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def auth_headers(access_token):
    return {"Authorization": f"Bearer {access_token}"}


# ---------------- ai-health endpoint ----------------
class TestAiHealthEndpoint:
    def test_ai_health_returns_valid_shape(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/ai-health", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        # Required keys
        for k in [
            "status", "auto_reply_enabled", "agent_name", "agent_active",
            "motor_ia_configured", "motor_ia_model", "sidecar_status",
            "stats_24h", "last_ok", "last_fail", "reasons",
        ]:
            assert k in data, f"missing key '{k}' in ai-health response: {data}"

        assert data["status"] in ("healthy", "degraded", "down"), data["status"]
        assert isinstance(data["auto_reply_enabled"], bool)
        assert isinstance(data["reasons"], list)

        stats = data["stats_24h"]
        for sk in ("sent", "failed", "failed_1h"):
            assert sk in stats, f"stats_24h missing '{sk}'"
            assert isinstance(stats[sk], int)

        # Each reason has code/severity/message
        for reason in data["reasons"]:
            assert "code" in reason and "severity" in reason and "message" in reason, reason

        # In current state: auto_reply off + no Jerusa → status should be 'down'
        if not data["auto_reply_enabled"]:
            codes = [r["code"] for r in data["reasons"]]
            assert "auto_reply_off" in codes, f"expected auto_reply_off in reasons {codes}"


# ---------------- silent-failure persistence ----------------
class TestSilentFailurePersistence:
    @pytest.fixture
    def phone(self):
        # unique phone so the conversation is fresh-ish
        return f"55119{int(time.time()) % 100000000:08d}"

    def test_inbound_persists_failed_outbound(self, auth_headers, phone):
        assert WA_INBOUND_TOKEN, "WA_INBOUND_TOKEN missing"
        msg_id = f"TEST_{uuid.uuid4().hex[:12]}"
        payload = {
            "phone": phone,
            "jid": f"{phone}@s.whatsapp.net",
            "text": "Oi, preciso de ajuda (TESTE iter56)",
            "push_name": "TEST Iter56",
            "message_id": msg_id,
            "timestamp": int(time.time()),
        }
        r = requests.post(
            f"{BASE_URL}/api/whatsapp-baileys/inbound",
            json=payload,
            headers={"X-WA-Token": WA_INBOUND_TOKEN},
            timeout=20,
        )
        assert r.status_code == 200, f"inbound failed {r.status_code}: {r.text}"

        # Give backend a moment for the auto-reply attempt to persist
        time.sleep(2)

        m = requests.get(
            f"{BASE_URL}/api/whatsapp-baileys/conversations/{phone}/messages?limit=10",
            headers=auth_headers,
            timeout=15,
        )
        assert m.status_code == 200, m.text
        body = m.json()
        msgs = body if isinstance(body, list) else body.get("messages") or body.get("items") or []
        assert len(msgs) >= 2, f"expected >=2 messages (inbound + failed-outbound), got {len(msgs)}: {body}"

        # Find an outbound entry with delivery_status starting with 'failed_'
        outbound_failed = [
            mm for mm in msgs
            if (mm.get("auto_reply") is True or mm.get("direction") == "out")
            and str(mm.get("delivery_status", "")).startswith("failed_")
        ]
        assert outbound_failed, f"no failed_* outbound message persisted. msgs={msgs}"

        sample = outbound_failed[0]
        # Expected status in current state (auto_reply off)
        assert sample["delivery_status"] in (
            "failed_disabled", "failed_no_agent", "failed_llm_error",
            "failed_motor_ia_unavailable", "failed_empty_reply", "failed_sidecar",
        ), sample["delivery_status"]
        assert sample.get("delivery_error"), f"delivery_error empty: {sample}"


# ---------------- toggle auto-reply ----------------
class TestAutoReplyToggle:
    def test_put_auto_reply_enabled_then_health_then_revert(self, auth_headers):
        # Capture original state
        h0 = requests.get(f"{BASE_URL}/api/whatsapp-baileys/ai-health", headers=auth_headers, timeout=15).json()
        original_enabled = bool(h0.get("auto_reply_enabled"))

        try:
            r = requests.put(
                f"{BASE_URL}/api/whatsapp-baileys/auto-reply",
                json={"enabled": True, "agent_name": "Jerusa"},
                headers=auth_headers,
                timeout=15,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body.get("ok") is True, body

            h = requests.get(f"{BASE_URL}/api/whatsapp-baileys/ai-health", headers=auth_headers, timeout=15)
            assert h.status_code == 200
            data = h.json()
            assert data["auto_reply_enabled"] is True, data
        finally:
            # Revert to original state (default expected: False)
            requests.put(
                f"{BASE_URL}/api/whatsapp-baileys/auto-reply",
                json={"enabled": original_enabled},
                headers=auth_headers,
                timeout=15,
            )
