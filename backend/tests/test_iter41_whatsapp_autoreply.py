"""Iteration 41 — WhatsApp Baileys Auto-Reply (Jerusa) + regressions.

Tests the new /auto-reply GET/PUT endpoints and the inbound auto-reply flow:
- OFF: inbound saves only inbound msg, no auto_reply field in response
- ON:  inbound returns auto_reply text, persists outbound row
- Groups (@g.us) skipped, from_me ignored
- Multi-turn session (session_id=wa-{phone})

After tests, auto-reply is left DISABLED.
"""
import os
import time
import pytest
import requests


def _load_base_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        url = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass
    assert url, "REACT_APP_BACKEND_URL not configured"
    return url.rstrip("/")


BASE_URL = _load_base_url()
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=20)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after(auth_headers):
    """Ensure auto-reply is DISABLED before and after the test module."""
    requests.put(f"{BASE_URL}/api/whatsapp-baileys/auto-reply",
                 headers=auth_headers, json={"enabled": False, "agent_name": "Jerusa"},
                 timeout=10)
    yield
    requests.put(f"{BASE_URL}/api/whatsapp-baileys/auto-reply",
                 headers=auth_headers, json={"enabled": False, "agent_name": "Jerusa"},
                 timeout=10)


def _list_messages(auth_headers, limit=50):
    r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/messages?limit={limit}",
                     headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text[:200]
    return r.json().get("items", [])


# ---------- Auto-reply settings endpoint ----------
class TestAutoReplySettings:
    def test_get_default_disabled(self, auth_headers):
        # Start in disabled state (cleanup fixture forces it)
        r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/auto-reply",
                         headers=auth_headers, timeout=10)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert "enabled" in body and "agent_name" in body
        assert body["enabled"] is False
        assert body["agent_name"] == "Jerusa"
        assert "updated_at" in body
        assert "updated_by" in body

    def test_put_enable_then_persists(self, auth_headers):
        r = requests.put(f"{BASE_URL}/api/whatsapp-baileys/auto-reply",
                         headers=auth_headers,
                         json={"enabled": True, "agent_name": "Jerusa"}, timeout=10)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body == {"ok": True, "enabled": True, "agent_name": "Jerusa"}

        # GET-verify
        r2 = requests.get(f"{BASE_URL}/api/whatsapp-baileys/auto-reply",
                          headers=auth_headers, timeout=10)
        assert r2.status_code == 200
        body2 = r2.json()
        assert body2["enabled"] is True
        assert body2["agent_name"] == "Jerusa"
        assert body2.get("updated_at")
        assert body2.get("updated_by")  # admin email

    def test_put_disable(self, auth_headers):
        r = requests.put(f"{BASE_URL}/api/whatsapp-baileys/auto-reply",
                         headers=auth_headers,
                         json={"enabled": False, "agent_name": "Jerusa"}, timeout=10)
        assert r.status_code == 200
        assert r.json()["enabled"] is False


# ---------- Inbound webhook behavior ----------
class TestInboundAutoReply:
    PHONE_OFF = "5521900002222"
    PHONE_ON = "5521900001111"
    PHONE_MULTI = "5521900003333"
    GROUP_JID = "120363111222333444@g.us"

    def _disable(self, auth_headers):
        requests.put(f"{BASE_URL}/api/whatsapp-baileys/auto-reply",
                     headers=auth_headers,
                     json={"enabled": False, "agent_name": "Jerusa"}, timeout=10)

    def _enable(self, auth_headers):
        requests.put(f"{BASE_URL}/api/whatsapp-baileys/auto-reply",
                     headers=auth_headers,
                     json={"enabled": True, "agent_name": "Jerusa"}, timeout=10)

    def test_inbound_with_autoreply_off(self, auth_headers):
        self._disable(auth_headers)
        payload = {
            "phone": self.PHONE_OFF,
            "jid": f"{self.PHONE_OFF}@s.whatsapp.net",
            "from_me": False,
            "text": "Olá teste off",
            "message_id": "TEST_AR_OFF1",
        }
        r = requests.post(f"{BASE_URL}/api/whatsapp-baileys/inbound",
                          json=payload, timeout=15)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body.get("ok") is True
        # subscriber_id may be null OR a string — both acceptable
        assert "subscriber_id" in body
        # No auto_reply field should be present
        assert "auto_reply" not in body, f"auto_reply leaked when OFF: {body}"

        # Verify only inbound row exists for this message_id
        time.sleep(0.5)
        msgs = _list_messages(auth_headers, limit=200)
        matched = [m for m in msgs if m.get("message_id") == "TEST_AR_OFF1"]
        assert len(matched) >= 1, "inbound msg not persisted"
        assert all(m.get("direction") == "inbound" for m in matched)
        # No outbound message for this phone right after this inbound
        outbounds = [m for m in msgs
                     if m.get("phone") == self.PHONE_OFF
                     and m.get("direction") == "outbound"
                     and m.get("auto_reply") is True]
        # There shouldn't be any auto_reply outbound for OFF phone right now.
        # (Could pre-exist from earlier runs, but with unique phone — safe.)
        assert outbounds == [], f"unexpected auto outbounds when OFF: {outbounds[:2]}"

    def test_inbound_with_autoreply_on(self, auth_headers):
        self._enable(auth_headers)
        payload = {
            "phone": self.PHONE_ON,
            "jid": f"{self.PHONE_ON}@s.whatsapp.net",
            "from_me": False,
            "text": "Olá, qual o preço dos planos?",
            "message_id": "TEST_AR1",
        }
        r = requests.post(f"{BASE_URL}/api/whatsapp-baileys/inbound",
                          json=payload, timeout=60)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body.get("ok") is True
        assert "auto_reply" in body, f"no auto_reply in response: {body}"
        assert isinstance(body["auto_reply"], str) and len(body["auto_reply"]) > 0

        # Persistence — wait briefly for the outbound insert
        time.sleep(1.5)
        msgs = _list_messages(auth_headers, limit=200)
        inbound = [m for m in msgs if m.get("message_id") == "TEST_AR1"
                   and m.get("direction") == "inbound"]
        outbound = [m for m in msgs if m.get("phone") == self.PHONE_ON
                    and m.get("direction") == "outbound"
                    and m.get("auto_reply") is True]
        assert len(inbound) >= 1, "inbound row missing"
        assert len(outbound) >= 1, f"outbound auto_reply row missing for {self.PHONE_ON}"
        # Outbound carries session_id and agent info
        out = outbound[0]
        assert out.get("session_id") == f"wa-{self.PHONE_ON}"
        assert out.get("agent_name") == "Jerusa"
        assert out.get("text") and len(out["text"]) > 0

    def test_group_jid_is_skipped(self, auth_headers):
        self._enable(auth_headers)
        payload = {
            "phone": "5521900004444",
            "jid": self.GROUP_JID,
            "from_me": False,
            "text": "mensagem em grupo, não responder",
            "message_id": "TEST_AR_GROUP",
        }
        r = requests.post(f"{BASE_URL}/api/whatsapp-baileys/inbound",
                          json=payload, timeout=20)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body.get("ok") is True
        assert "auto_reply" not in body, f"group should not auto-reply: {body}"

    def test_from_me_is_ignored(self, auth_headers):
        self._enable(auth_headers)
        payload = {
            "phone": "5521900005555",
            "jid": "5521900005555@s.whatsapp.net",
            "from_me": True,
            "text": "minha própria mensagem",
            "message_id": "TEST_AR_FROMME",
        }
        r = requests.post(f"{BASE_URL}/api/whatsapp-baileys/inbound",
                          json=payload, timeout=10)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body == {"ok": True, "ignored": "from_me"}

    def test_multi_turn_session(self, auth_headers):
        self._enable(auth_headers)
        # Turn 1
        p1 = {
            "phone": self.PHONE_MULTI,
            "jid": f"{self.PHONE_MULTI}@s.whatsapp.net",
            "from_me": False,
            "text": "Oi, meu nome é Carlos.",
            "message_id": "TEST_AR_MULTI1",
        }
        r1 = requests.post(f"{BASE_URL}/api/whatsapp-baileys/inbound",
                           json=p1, timeout=60)
        assert r1.status_code == 200, r1.text[:200]
        b1 = r1.json()
        assert b1.get("auto_reply"), f"turn1 missing reply: {b1}"

        # Turn 2 — same phone -> same session_id
        p2 = {
            "phone": self.PHONE_MULTI,
            "jid": f"{self.PHONE_MULTI}@s.whatsapp.net",
            "from_me": False,
            "text": "Qual é o preço do plano básico?",
            "message_id": "TEST_AR_MULTI2",
        }
        r2 = requests.post(f"{BASE_URL}/api/whatsapp-baileys/inbound",
                           json=p2, timeout=60)
        assert r2.status_code == 200, r2.text[:200]
        b2 = r2.json()
        assert b2.get("auto_reply"), f"turn2 missing reply: {b2}"

        # Both outbound rows persist with same session_id
        time.sleep(1.5)
        msgs = _list_messages(auth_headers, limit=200)
        outs = [m for m in msgs
                if m.get("phone") == self.PHONE_MULTI
                and m.get("direction") == "outbound"
                and m.get("auto_reply") is True]
        assert len(outs) >= 2, f"expected >=2 auto outbounds, got {len(outs)}"
        for o in outs:
            assert o.get("session_id") == f"wa-{self.PHONE_MULTI}"


# ---------- Regressions ----------
class TestRegression:
    def test_qr_endpoint(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/qr",
                         headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert "qr" in body and "status" in body

    def test_voice_session_start(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/voice/sessions/start",
                          headers=auth_headers,
                          json={"caller": "5521999990001"}, timeout=20)
        assert r.status_code in (200, 201), f"{r.status_code}: {r.text[:200]}"
        body = r.json()
        assert body.get("session_id") or body.get("id"), body

    def test_textgen(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/aihub/agents/text-gen",
                          headers=auth_headers,
                          json={"field": "company_info", "mode": "gerar",
                                "current_text": "", "context": "Provedor ISP"},
                          timeout=60)
        assert r.status_code in (200, 201), f"{r.status_code}: {r.text[:200]}"
        body = r.json()
        assert body.get("text") and len(body["text"]) > 20, body

    def test_schedule_lousa_ticket(self, auth_headers):
        # Smoke check that lousa schedule-ticket tool exists.
        r = requests.post(f"{BASE_URL}/api/aihub/tools/schedule-lousa-ticket",
                          headers=auth_headers,
                          json={"subscriber_id": "sub-doesnotexist",
                                "kind": "preventiva",
                                "scheduled_for": "2026-02-15T10:00:00",
                                "note": "regressão iter41"},
                          timeout=20)
        # 200 (ok) / 404 (sub not found) / 400 (validation) — all acceptable, just shouldn't 500
        assert r.status_code in (200, 201, 400, 404, 422), f"{r.status_code}: {r.text[:200]}"
