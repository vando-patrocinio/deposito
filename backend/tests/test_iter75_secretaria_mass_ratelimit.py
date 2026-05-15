"""Iter 75 — Tests for slowapi @limiter.limit on:

(1) /api/secretaria/ask                    — limit 30/min (DEV 300)
(2) /api/mass-messaging/campaigns POST     — limit 10/min (DEV 100)
(3) /api/mass-messaging/campaigns/{id}/start — limit 5/min (DEV 50)
(4) /api/whatsapp-twilio/webhook POST      — limit 120/min (DEV 1200)
(5) /api/whatsapp-meta/webhook POST        — limit 120/min (DEV 1200)
(6) /api/secretaria/webhook/chatgpt        — limit 120/min
(7) /api/secretaria/ask/{token}            — limit 120/min

Key bug being verified: removal of `from __future__ import annotations`
from secretaria.py and mass_messaging.py prevents 422 errors caused by
slowapi + Pydantic Body interaction.
"""
import os
import uuid

import pytest
import requests


def _base_url() -> str:
    url = os.environ.get("REACT_APP_BACKEND_URL", "").strip()
    if not url:
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        url = line.split("=", 1)[1].strip()
                        break
        except FileNotFoundError:
            pass
    return url.rstrip("/")


BASE_URL = _base_url()
assert BASE_URL, "REACT_APP_BACKEND_URL not set"

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASSWORD = "123456"


# ---------------------------- fixtures ----------------------------
@pytest.fixture(scope="module")
def auth_headers():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    tok = r.json()["access_token"]
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _xff(prefix="10.77"):
    """Synthetic X-Forwarded-For unique per test."""
    return (
        f"{prefix}."
        f"{uuid.uuid4().int % 254}."
        f"{(uuid.uuid4().int >> 8) % 254}"
    )


# ============== (1) /api/secretaria/ask — main bug fix ==============
class TestSecretariaAsk:
    """Primary bug: slowapi + `from __future__ import annotations` caused 422.
    These tests must return 200, not 422."""

    def test_ask_valid_payload_returns_200(self, auth_headers):
        r = requests.post(
            f"{BASE_URL}/api/secretaria/ask",
            headers={**auth_headers, "X-Forwarded-For": _xff()},
            json={"question": "quantos clientes ativos?",
                  "channel": "internal"},
            timeout=60,
        )
        assert r.status_code == 200, (
            f"Expected 200 (slowapi+__future__ bug regression): "
            f"got {r.status_code}: {r.text[:300]}"
        )
        data = r.json()
        assert "answer" in data, f"missing 'answer' field: {data}"
        assert isinstance(data["answer"], str)
        assert len(data["answer"]) > 0

    def test_ask_minimal_payload_returns_200(self, auth_headers):
        """Even without channel field — should not 422."""
        r = requests.post(
            f"{BASE_URL}/api/secretaria/ask",
            headers={**auth_headers, "X-Forwarded-For": _xff()},
            json={"question": "ping"},
            timeout=60,
        )
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:300]}"

    def test_ask_missing_question_returns_422(self, auth_headers):
        """422 should still happen for actually invalid payloads."""
        r = requests.post(
            f"{BASE_URL}/api/secretaria/ask",
            headers={**auth_headers, "X-Forwarded-For": _xff()},
            json={"channel": "internal"},
            timeout=15,
        )
        assert r.status_code == 422

    def test_ask_unauthorized(self):
        r = requests.post(
            f"{BASE_URL}/api/secretaria/ask",
            headers={"Content-Type": "application/json"},
            json={"question": "ping"},
            timeout=15,
        )
        assert r.status_code in (401, 403)

    def test_ask_10_calls_below_dev_limit(self, auth_headers):
        """DEV limit = 300/min — 10 sequential calls should all succeed.
        Uses same XFF so we test the actual per-IP limit."""
        xff = _xff(prefix="10.71")
        statuses = []
        for _ in range(10):
            r = requests.post(
                f"{BASE_URL}/api/secretaria/ask",
                headers={**auth_headers, "X-Forwarded-For": xff},
                json={"question": "ping", "channel": "internal"},
                timeout=60,
            )
            statuses.append(r.status_code)
            if r.status_code == 429:
                break
        # ALL should be 200 in DEV (limit=300)
        success = sum(1 for s in statuses if s == 200)
        assert success == 10, (
            f"expected 10×200 (DEV limit=300), got statuses={statuses}"
        )


# ============== (2) /api/mass-messaging/campaigns POST ==============
class TestMassCampaignCreate:
    def test_create_campaign_valid_returns_200(self, auth_headers):
        payload = {
            "name": f"TEST_iter75_camp_{uuid.uuid4().hex[:6]}",
            "channel": "meta_cloud",
            "mode": "free",
            "text": "Olá {{1}}, tudo bem?",
            "throttle_per_min": 60,
        }
        r = requests.post(
            f"{BASE_URL}/api/mass-messaging/campaigns",
            headers={**auth_headers, "X-Forwarded-For": _xff()},
            json=payload,
            timeout=20,
        )
        assert r.status_code == 200, (
            f"Expected 200 (slowapi+__future__ bug regression): "
            f"got {r.status_code}: {r.text[:300]}"
        )
        data = r.json()
        assert "id" in data
        assert data["name"] == payload["name"]
        assert data["channel"] == "meta_cloud"
        assert data["status"] == "draft"
        assert data["total_recipients"] == 0
        # cleanup
        cid = data["id"]
        requests.delete(
            f"{BASE_URL}/api/mass-messaging/campaigns/{cid}",
            headers=auth_headers, timeout=10,
        )

    def test_5_calls_below_dev_limit(self, auth_headers):
        """DEV limit = 100/min — 5 calls should all succeed."""
        xff = _xff(prefix="10.72")
        ids = []
        for i in range(5):
            r = requests.post(
                f"{BASE_URL}/api/mass-messaging/campaigns",
                headers={**auth_headers, "X-Forwarded-For": xff},
                json={
                    "name": f"TEST_iter75_burst_{i}_{uuid.uuid4().hex[:4]}",
                    "channel": "meta_cloud",
                    "mode": "free",
                    "text": "hi",
                },
                timeout=15,
            )
            assert r.status_code == 200, (
                f"call #{i}: status={r.status_code} body={r.text[:200]}"
            )
            ids.append(r.json()["id"])
        # cleanup
        for cid in ids:
            requests.delete(
                f"{BASE_URL}/api/mass-messaging/campaigns/{cid}",
                headers=auth_headers, timeout=10,
            )


# ============== (3) /api/mass-messaging/campaigns/{id}/start ==============
class TestMassCampaignStart:
    def test_start_with_zero_recipients_returns_400(self, auth_headers):
        # Create campaign first (no upload → 0 recipients)
        cr = requests.post(
            f"{BASE_URL}/api/mass-messaging/campaigns",
            headers={**auth_headers, "X-Forwarded-For": _xff()},
            json={
                "name": f"TEST_iter75_start_{uuid.uuid4().hex[:5]}",
                "channel": "meta_cloud",
                "mode": "free",
                "text": "hi",
            },
            timeout=15,
        )
        assert cr.status_code == 200
        cid = cr.json()["id"]

        # Start without uploading any recipients → expect 400
        sr = requests.post(
            f"{BASE_URL}/api/mass-messaging/campaigns/{cid}/start",
            headers={**auth_headers, "X-Forwarded-For": _xff()},
            json={"force_now": True},
            timeout=15,
        )
        # cleanup before asserting
        requests.delete(
            f"{BASE_URL}/api/mass-messaging/campaigns/{cid}",
            headers=auth_headers, timeout=10,
        )
        assert sr.status_code == 400, (
            f"expected 400 for 0 recipients; got {sr.status_code}: "
            f"{sr.text[:200]}"
        )
        body = sr.json()
        assert "detail" in body
        assert "upload" in body["detail"].lower() or "antes" in body["detail"].lower()

    def test_start_default_payload_does_not_422(self, auth_headers):
        """The Body(default_factory=...) interaction with slowapi must
        not cause 422 when client sends empty body."""
        cr = requests.post(
            f"{BASE_URL}/api/mass-messaging/campaigns",
            headers={**auth_headers, "X-Forwarded-For": _xff()},
            json={
                "name": f"TEST_iter75_emptybody_{uuid.uuid4().hex[:5]}",
                "channel": "meta_cloud",
                "mode": "free",
                "text": "hi",
            },
            timeout=15,
        )
        assert cr.status_code == 200
        cid = cr.json()["id"]

        sr = requests.post(
            f"{BASE_URL}/api/mass-messaging/campaigns/{cid}/start",
            headers={**auth_headers, "X-Forwarded-For": _xff()},
            timeout=15,
        )
        requests.delete(
            f"{BASE_URL}/api/mass-messaging/campaigns/{cid}",
            headers=auth_headers, timeout=10,
        )
        # Should be 400 (zero recipients), NOT 422
        assert sr.status_code == 400, (
            f"expected 400 with empty body; got {sr.status_code}: "
            f"{sr.text[:200]}"
        )


# ============== (4) /api/whatsapp-twilio/webhook POST ==============
class TestWhatsappTwilioWebhook:
    """Twilio webhook accepts form-urlencoded; we just need to verify
    the limiter decorator is wired (i.e., 200 normal flow, not 500)."""

    def test_twilio_webhook_accepts_post(self):
        r = requests.post(
            f"{BASE_URL}/api/whatsapp-twilio/webhook",
            data={"From": "whatsapp:+5511999999999",
                  "To": "whatsapp:+15555555555",
                  "Body": "test"},
            headers={"X-Forwarded-For": _xff(prefix="10.74")},
            timeout=15,
        )
        # Twilio webhook is public — should not 401. Accept 2xx or 4xx (not 5xx).
        assert r.status_code < 500, (
            f"twilio webhook 5xx: {r.status_code} {r.text[:200]}"
        )


# ============== (5) /api/whatsapp-meta/webhook POST ==============
class TestWhatsappMetaWebhook:
    def test_meta_webhook_accepts_post(self):
        r = requests.post(
            f"{BASE_URL}/api/whatsapp-meta/webhook",
            json={"object": "whatsapp_business_account", "entry": []},
            headers={"X-Forwarded-For": _xff(prefix="10.75"),
                     "Content-Type": "application/json"},
            timeout=15,
        )
        # Meta webhook is public — should accept the POST without 5xx
        assert r.status_code < 500, (
            f"meta webhook 5xx: {r.status_code} {r.text[:200]}"
        )


# ============== Regression: existing endpoints still work ==============
class TestRegression:
    def test_financeiro_analytics_still_works(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/financeiro/analytics?range=30d&period=day",
            headers=auth_headers, timeout=15,
        )
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        for k in ("range", "period", "totals", "series", "buckets",
                  "income_metrics", "expense_metrics"):
            assert k in data, f"missing {k}"

    def test_secretaria_config_no_ratelimit(self, auth_headers):
        """GET /api/secretaria/config doesn't have a limiter — 20 calls."""
        ok = 0
        for _ in range(20):
            r = requests.get(
                f"{BASE_URL}/api/secretaria/config",
                headers=auth_headers, timeout=10,
            )
            if r.status_code == 200:
                ok += 1
        assert ok == 20, f"expected 20/20; got {ok}/20"

    def test_auth_login_ratelimit_still_works(self):
        """Iter74 verified — re-validate with synthetic XFF.
        DEV limit = 50/min (5*10). Make 55 attempts; expect 429 to appear."""
        synth = _xff(prefix="10.66")
        headers = {"X-Forwarded-For": synth,
                   "Content-Type": "application/json"}
        statuses = []
        for i in range(55):
            r = requests.post(
                f"{BASE_URL}/api/auth/login",
                json={"email": f"none_{i}_{uuid.uuid4().hex[:6]}@x.com",
                      "password": "wrong"},
                headers=headers, timeout=10,
            )
            statuses.append(r.status_code)
            if r.status_code == 429:
                break
        assert 429 in statuses, (
            f"expected 429 after 50 attempts; last10={statuses[-10:]}"
        )
        assert 401 in statuses
