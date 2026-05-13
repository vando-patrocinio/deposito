"""Iteration 61 — WhatsApp Twilio channel structural tests.

Covers:
- Auth (admin login)
- GET/PUT /api/whatsapp-twilio/config with masked creds
- GET /api/whatsapp-twilio/status (fake creds → error/unreachable)
- POST /api/whatsapp-twilio/send (fake creds → 502 expected)
- POST /api/whatsapp-twilio/webhook (form-data simulation)
- GET /api/whatsapp-twilio/messages (verify inbound persistence)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not set"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                       json={"email": "admin@empresa.com", "password": "123456"},
                       timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    tk = data.get("access_token") or data.get("token")
    assert tk, f"no token in login response: {data}"
    return tk


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Config CRUD
# ---------------------------------------------------------------------------
class TestTwilioConfig:
    def test_get_config_initial(self, auth_headers):
        # NOTE: cannot guarantee no creds exist; assert shape always
        r = requests.get(f"{BASE_URL}/api/whatsapp-twilio/config",
                          headers=auth_headers, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "configured" in body
        assert "enabled" in body
        assert isinstance(body["configured"], bool)

    def test_put_config_with_fake_creds(self, auth_headers):
        payload = {
            "account_sid": "AC_fake_sid_test_12345678",
            "auth_token": "fake_token_abcdef123456",
            "from_number": "+5521998176526",
            "enabled": False,
            "sandbox": True,
        }
        r = requests.put(f"{BASE_URL}/api/whatsapp-twilio/config",
                          json=payload, headers=auth_headers, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("configured") is True
        assert body.get("from_number") == "+5521998176526"
        wh = body.get("webhook_url", "")
        assert "/api/whatsapp-twilio/webhook" in wh
        assert "tenant=" in wh

    def test_get_config_after_put_returns_masked(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/whatsapp-twilio/config",
                          headers=auth_headers, timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body.get("configured") is True
        sid = body.get("account_sid") or ""
        # masked: starts with first 4 + asterisks + last 4
        assert "*" in sid, f"account_sid not masked: {sid}"
        assert sid.startswith("AC_f"), f"prefix not preserved: {sid}"
        assert sid.endswith("5678"), f"suffix not preserved: {sid}"
        assert body.get("from_number") == "+5521998176526"

    def test_status_with_fake_creds(self, auth_headers):
        # Need to flip enabled=True to actually hit Twilio API
        payload = {
            "account_sid": "AC_fake_sid_test_12345678",
            "auth_token": "fake_token_abcdef123456",
            "from_number": "+5521998176526",
            "enabled": True,
            "sandbox": True,
        }
        requests.put(f"{BASE_URL}/api/whatsapp-twilio/config",
                      json=payload, headers=auth_headers, timeout=10)
        r = requests.get(f"{BASE_URL}/api/whatsapp-twilio/status",
                          headers=auth_headers, timeout=15)
        assert r.status_code == 200
        body = r.json()
        # With fake creds Twilio will return 401 → status='error'; or unreachable
        assert body.get("status") in ("error", "unreachable", "disabled"), body


# ---------------------------------------------------------------------------
# Webhook + messages persistence
# ---------------------------------------------------------------------------
class TestTwilioWebhook:
    def test_webhook_simulated_inbound(self):
        # Webhook is public (Twilio calls it). Pass tenant via query.
        data = {
            "From": "whatsapp:+5511988887777",
            "To": "whatsapp:+5521998176526",
            "Body": "oi twilio iter61",
            "ProfileName": "Cliente Twilio Iter61",
            "MessageSid": "SMfakeIter61",
            "NumMedia": "0",
        }
        r = requests.post(
            f"{BASE_URL}/api/whatsapp-twilio/webhook?tenant=co-demo",
            data=data, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True

    def test_messages_list_includes_inbound(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/whatsapp-twilio/messages?limit=20",
                          headers=auth_headers, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        items = body.get("items") or []
        # Find the most recent inbound with our text
        found = [m for m in items
                  if m.get("channel") == "twilio"
                  and m.get("direction") == "inbound"
                  and "oi twilio iter61" in (m.get("text") or "")]
        assert found, f"inbound message not persisted: {items[:3]}"
        assert found[0].get("phone") == "5511988887777"


# ---------------------------------------------------------------------------
# Send with fake creds → expect Twilio 401
# ---------------------------------------------------------------------------
class TestTwilioSend:
    def test_send_with_fake_creds_fails(self, auth_headers):
        # Ensure enabled
        payload = {
            "account_sid": "AC_fake_sid_test_12345678",
            "auth_token": "fake_token_abcdef123456",
            "from_number": "+5521998176526",
            "enabled": True,
            "sandbox": True,
        }
        requests.put(f"{BASE_URL}/api/whatsapp-twilio/config",
                      json=payload, headers=auth_headers, timeout=10)
        r = requests.post(
            f"{BASE_URL}/api/whatsapp-twilio/send",
            json={"phone": "+5521977770000", "text": "teste iter61"},
            headers=auth_headers, timeout=20,
        )
        # Endpoint raises HTTPException(502) on failure
        assert r.status_code in (502, 401, 400), f"unexpected: {r.status_code} {r.text}"
