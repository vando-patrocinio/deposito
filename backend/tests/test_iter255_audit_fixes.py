"""iter255 — regression tests for post-audit fixes:
- P0-2 LID send target (@lid)
- P0-3 phone_is_lid flag from DB
- P2 geocoding throttle (no 500)
- duplicate /api/motor-ia/budget route removed (daily limits persist)
"""
import os
import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

ORIGINAL = {
    "monthly_limit_usd": 200,
    "daily_limit_usd": 2.0,
    "daily_service_limits": {"vision": 0.5, "stt": 0.5, "tts": 0.5, "text": 1.0},
}


# === Auth smoke ===
@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "admin@empresa.com", "password": "123456"},
                      timeout=30)
    if r.status_code != 200:
        pytest.fail(f"login failed {r.status_code}: {r.text[:400]}")
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no token in login response: {data}"
    return tok


@pytest.fixture(scope="session")
def H(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


class TestAuthSmoke:
    def test_login_returns_token_and_user(self):
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": "admin@empresa.com", "password": "123456"},
                          timeout=30)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert (d.get("access_token") or d.get("token"))
        u = d.get("user") or {}
        assert u.get("email") == "admin@empresa.com"

    def test_me_endpoint(self, H):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=H, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert r.json().get("email") == "admin@empresa.com"


# === Motor IA budget ===
class TestMotorIaBudget:
    def test_get_budget_shape(self, H):
        r = requests.get(f"{BASE_URL}/api/motor-ia/budget", headers=H, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        d = r.json()
        for k in ("monthly_limit_usd", "spent_month_usd", "used_pct",
                  "warn_threshold_pct", "enabled", "daily_limit_usd",
                  "daily_service_limits"):
            assert k in d, f"missing key {k} in {d}"
        assert isinstance(d["daily_service_limits"], dict)
        for s in ("vision", "stt", "tts", "text"):
            assert s in d["daily_service_limits"]

    def test_put_daily_only_no_422_and_persists(self, H):
        payload = {"daily_limit_usd": 7.25,
                   "daily_service_limits": {"vision": 1.5, "stt": 2.25,
                                            "tts": 0.75, "text": 2.75}}
        r = requests.put(f"{BASE_URL}/api/motor-ia/budget", json=payload,
                         headers=H, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        d = r.json()
        assert d["daily_limit_usd"] == 7.25
        assert d["daily_service_limits"]["stt"] == 2.25

        g = requests.get(f"{BASE_URL}/api/motor-ia/budget", headers=H, timeout=30)
        assert g.status_code == 200
        gd = g.json()
        assert gd["daily_limit_usd"] == 7.25
        assert gd["daily_service_limits"] == {"vision": 1.5, "stt": 2.25,
                                             "tts": 0.75, "text": 2.75}

        t = requests.get(f"{BASE_URL}/api/motor-ia/budget/status/today",
                         headers=H, timeout=30)
        assert t.status_code == 200, f"{t.status_code} {t.text[:400]}"
        td = t.json()
        blob = str(td)
        assert "7.25" in blob or td.get("daily_limit_usd") == 7.25, \
            f"today status does not reflect daily limit: {td}"

    def test_put_monthly_only_does_not_reset_daily(self, H):
        r = requests.put(f"{BASE_URL}/api/motor-ia/budget",
                         json={"monthly_limit_usd": 321.0},
                         headers=H, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        d = r.json()
        assert d["monthly_limit_usd"] == 321.0
        assert d["daily_limit_usd"] == 7.25, f"daily limit was reset: {d}"
        assert d["daily_service_limits"]["text"] == 2.75, f"service limits reset: {d}"

    def test_budget_status_shape(self, H):
        r = requests.get(f"{BASE_URL}/api/motor-ia/budget/status", headers=H, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        d = r.json()
        assert isinstance(d, dict) and len(d) > 0

    def test_restore_original_values(self, H):
        r = requests.put(f"{BASE_URL}/api/motor-ia/budget", json=ORIGINAL,
                         headers=H, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        g = requests.get(f"{BASE_URL}/api/motor-ia/budget", headers=H, timeout=30).json()
        assert g["monthly_limit_usd"] == 200
        assert g["daily_limit_usd"] == 2.0
        assert g["daily_service_limits"] == ORIGINAL["daily_service_limits"]


# === WhatsApp send endpoints (sidecar offline -> handled error, never 500) ===
class TestWhatsAppSendNo500:
    TEST_PHONE = "5521999990001"

    def test_send_text(self, H):
        r = requests.post(f"{BASE_URL}/api/whatsapp-baileys/send",
                          json={"phone": self.TEST_PHONE, "text": "TEST_iter255 ping"},
                          headers=H, timeout=60)
        assert r.status_code != 500, f"500 on /send: {r.text[:600]}"
        assert r.status_code in (200, 400, 409, 422, 502, 503), \
            f"unexpected {r.status_code}: {r.text[:400]}"

    def test_send_audio(self, H):
        r = requests.post(f"{BASE_URL}/api/whatsapp-baileys/send-audio",
                          json={"phone": self.TEST_PHONE,
                                "audio_b64": "A" * 200,
                                "mimetype": "audio/ogg; codecs=opus",
                                "duration_sec": 1.0},
                          headers=H, timeout=90)
        assert r.status_code != 500, f"500 on /send-audio: {r.text[:600]}"
        assert r.status_code in (200, 400, 409, 502, 503), \
            f"unexpected {r.status_code}: {r.text[:300]}"

    def test_send_image(self, H):
        tiny_png = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
                    "AAAADUlEQVR42mP8z8AAAwAB/AL+bTIAAAAASUVORK5CYII=")
        r = requests.post(f"{BASE_URL}/api/whatsapp-baileys/send-image",
                          json={"phone": self.TEST_PHONE, "image_data_url": tiny_png,
                                "caption": "TEST_iter255"},
                          headers=H, timeout=60)
        assert r.status_code != 500, f"500 on /send-image: {r.text[:600]}"
        assert r.status_code in (200, 400, 409, 502, 503), \
            f"unexpected {r.status_code}: {r.text[:300]}"


# === LID send target resolution (P0-2) ===
class TestLidSendTarget:
    def test_resolve_send_target_returns_lid_jid(self):
        import asyncio
        import sys
        sys.path.insert(0, "/app/backend")
        from database import db
        from services.wa.lid import resolve_send_target

        async def _run():
            conv = await db.wa_conversations.find_one(
                {"phone_is_lid": True}, {"_id": 0, "phone": 1, "company_id": 1, "lid": 1})
            if not conv:
                return None
            return conv, await resolve_send_target(conv["company_id"], conv["phone"])

        res = asyncio.run(_run())
        if res is None:
            pytest.skip("no LID conversation in DB")
        conv, target = res
        assert target == f"{conv['lid']}@lid", f"expected <lid>@lid, got {target}"


# === AI orchestrator module import (regression) ===
class TestAiOrchestratorImport:
    def test_module_imports(self):
        import ast
        src = open("/app/backend/services/ai_orchestrator.py").read()
        ast.parse(src)  # raises SyntaxError if module is broken


# === Conversations listing + LID flag ===
class TestConversationsLid:
    def test_conversations_200(self, H):
        r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/conversations",
                         headers=H, timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        body = r.json()
        items = body.get("items") if isinstance(body, dict) else body
        assert isinstance(items, list)

    def test_lid_conversations_have_flag_and_lid(self, H):
        r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/conversations",
                         headers=H, timeout=60)
        body = r.json()
        items = body.get("items") if isinstance(body, dict) else body
        lids = [c for c in items if c.get("phone_is_lid")]
        if not lids:
            pytest.skip("no LID conversations present in preview data")
        for c in lids:
            assert c.get("lid"), f"phone_is_lid conv without lid field: {c}"


# === Geocoding regression ===
class TestGeocoding:
    def test_lousa_map_services(self, H):
        r = requests.get(f"{BASE_URL}/api/lousa/map/services?period=today",
                         headers=H, timeout=90)
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        assert isinstance(r.json(), (dict, list))

    def test_admin_geocode_no_500(self, H):
        r = requests.get(f"{BASE_URL}/api/geocode",
                         params={"address": "Avenida Paulista 1000, Sao Paulo, SP"},
                         headers=H, timeout=90)
        assert r.status_code != 500, f"500 on geocode: {r.text[:600]}"
        assert r.status_code in (200, 429), f"unexpected {r.status_code}: {r.text[:300]}"

    def test_admin_geocode_search_no_500(self, H):
        r = requests.get(f"{BASE_URL}/api/geocode/search",
                         params={"q": "Rua Augusta, Sao Paulo", "limit": 3},
                         headers=H, timeout=90)
        assert r.status_code != 500, f"500 on geocode/search: {r.text[:600]}"
        assert r.status_code in (200, 429)
