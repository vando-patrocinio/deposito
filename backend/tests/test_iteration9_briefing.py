"""Iteration 9 — Backend tests for GET /api/lousa/briefing.

Coverage:
- 401 sem auth
- gestor: use_ai=false retorna summary_data com chaves esperadas e narrative=null + method='data-only'
- gestor: use_ai=true retorna narrative string OU cai em data-only se LLM falhar (timeout 30s)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
ADMIN = {"email": "admin@empresa.com", "password": "123456"}
GESTOR = {"email": "gestor@empresa.com", "password": "123456"}


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login {creds['email']} failed: {r.status_code} {r.text}"
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.fixture(scope="module")
def gestor_headers():
    try:
        tok = _login(GESTOR)
    except AssertionError:
        # fallback to admin (super-role)
        tok = _login(ADMIN)
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_headers():
    tok = _login(ADMIN)
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ------------------------ Auth ------------------------
class TestBriefingAuth:
    def test_no_auth_returns_401(self):
        r = requests.get(f"{BASE_URL}/api/lousa/briefing", timeout=15)
        assert r.status_code in (401, 403), r.text


# ------------------------ data-only ------------------------
class TestBriefingDataOnly:
    def test_use_ai_false_returns_summary_data(self, gestor_headers):
        r = requests.get(
            f"{BASE_URL}/api/lousa/briefing?use_ai=false",
            headers=gestor_headers,
            timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("narrative") is None
        assert body.get("method") == "data-only"

        sd = body.get("summary_data")
        assert isinstance(sd, dict)
        # required keys
        for k in [
            "date", "total_today", "finalized_count", "still_open_count",
            "canceled_count", "avg_duration_minutes", "top3_services",
        ]:
            assert k in sd, f"missing key {k} in summary_data: {sd.keys()}"

        # types
        assert isinstance(sd["total_today"], int)
        assert isinstance(sd["finalized_count"], int)
        assert isinstance(sd["still_open_count"], int)
        assert isinstance(sd["canceled_count"], int)
        assert isinstance(sd["top3_services"], list)
        # date is YYYY-MM-DD
        assert isinstance(sd["date"], str) and len(sd["date"]) >= 10

    def test_admin_role_can_access(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/lousa/briefing?use_ai=false",
            headers=admin_headers,
            timeout=20,
        )
        # admin é super-role e deve passar require_role('gestor')
        assert r.status_code == 200, r.text


# ------------------------ LLM narrative ------------------------
class TestBriefingLLM:
    def test_use_ai_true_returns_narrative_or_falls_back(self, gestor_headers):
        r = requests.get(
            f"{BASE_URL}/api/lousa/briefing?use_ai=true",
            headers=gestor_headers,
            timeout=45,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # narrative pode ser string OU None (fallback aceito)
        narrative = body.get("narrative")
        method = body.get("method")
        assert method in ("llm", "data-only")
        if method == "llm":
            assert isinstance(narrative, str) and len(narrative) > 10
        else:
            assert narrative is None
        assert isinstance(body.get("summary_data"), dict)
