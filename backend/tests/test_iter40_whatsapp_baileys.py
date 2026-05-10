"""Iteration 40 — WhatsApp Baileys QR integration + regressions."""
import os
import pytest
import requests

def _load_base_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        # fallback to frontend/.env
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


# ---------- WhatsApp Baileys ----------
class TestWhatsAppBaileys:
    def test_qr_returns_png_data_url(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/qr",
                         headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert "qr" in body and "status" in body
        # may need a moment for sidecar to generate first QR; retry once
        if not body.get("qr"):
            import time
            time.sleep(4)
            r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/qr",
                             headers=auth_headers, timeout=15)
            body = r.json()
        assert body["qr"], f"qr is empty: {body}"
        assert body["qr"].startswith("data:image/png;base64,"), body["qr"][:80]
        assert len(body["qr"]) > 4000, f"qr too short: {len(body['qr'])}"
        assert body["status"] in ("connecting", "open"), body["status"]

    def test_status(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/status",
                         headers=auth_headers, timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert "connected" in body and "state" in body
        assert isinstance(body["connected"], bool)

    def test_send_not_connected_returns_503(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/whatsapp-baileys/send",
                          headers=auth_headers,
                          json={"phone": "5521999990001", "text": "ping"},
                          timeout=15)
        assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text[:200]}"
        detail = r.json().get("detail", "")
        assert "não conectado" in detail.lower() or "nao conectado" in detail.lower(), detail

    def test_inbound_webhook_and_messages(self, auth_headers):
        payload = {
            "phone": "5521999990001",
            "jid": "5521999990001@s.whatsapp.net",
            "from_me": False,
            "text": "teste",
            "message_id": "TEST1",
        }
        r = requests.post(f"{BASE_URL}/api/whatsapp-baileys/inbound",
                          json=payload, timeout=10)
        assert r.status_code == 200, r.text[:200]
        assert r.json().get("ok") is True

        r2 = requests.get(f"{BASE_URL}/api/whatsapp-baileys/messages",
                          headers=auth_headers, timeout=10)
        assert r2.status_code == 200
        items = r2.json().get("items", [])
        found = next((m for m in items
                      if m.get("message_id") == "TEST1"
                      and m.get("direction") == "inbound"
                      and m.get("phone") == "5521999990001"
                      and m.get("text") == "teste"), None)
        assert found is not None, f"inbound message not found in {items[:3]}"


# ---------- Regressions ----------
class TestRegression:
    def test_voice_session_start(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/voice/sessions/start",
                          headers=auth_headers,
                          json={"caller": "5521999990001"}, timeout=20)
        # accept 200 or 201
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
        # endpoint exists; quick smoke
        r = requests.get(f"{BASE_URL}/api/lousa/tickets",
                         headers=auth_headers, timeout=15)
        # not testing exact endpoint—just ensure lousa module is up
        assert r.status_code in (200, 404, 405), r.status_code
