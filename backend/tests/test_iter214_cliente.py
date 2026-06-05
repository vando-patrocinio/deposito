"""Iter 214 — Backend smoke for /api/customer/* (Indique e Ganhe Cliente app)."""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
VALID_CPF = "45907863463"
INVALID_CPF = "11111111111"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def login_data(session):
    r = session.post(f"{BASE_URL}/api/customer/login", json={"cpf": VALID_CPF}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    d = r.json()
    assert "token" in d and "subscriber" in d
    assert d["subscriber"].get("referral_code")
    return d


@pytest.fixture(scope="module")
def auth_headers(login_data):
    return {"Authorization": f"Bearer {login_data['token']}", "Content-Type": "application/json"}


# Login tests
class TestLogin:
    def test_login_valid_cpf(self, session):
        r = session.post(f"{BASE_URL}/api/customer/login", json={"cpf": VALID_CPF}, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert isinstance(d.get("token"), str) and len(d["token"]) > 0
        sub = d.get("subscriber") or {}
        assert sub.get("referral_code")
        # Maria José Silva
        assert "Maria" in (sub.get("name") or "")

    def test_login_invalid_cpf(self, session):
        r = session.post(f"{BASE_URL}/api/customer/login", json={"cpf": INVALID_CPF}, timeout=30)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"

    def test_login_masked_cpf_works(self, session):
        r = session.post(f"{BASE_URL}/api/customer/login", json={"cpf": "459.078.634-63"}, timeout=30)
        assert r.status_code == 200


# Authenticated endpoints
class TestCustomerEndpoints:
    def test_me(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/customer/me", headers=auth_headers, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d.get("referral_code")
        assert "Maria" in (d.get("name") or "")

    def test_stats(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/customer/stats", headers=auth_headers, timeout=30)
        assert r.status_code == 200
        d = r.json()
        for k in ("total_indicated", "installed", "available_brl", "earned_total_brl"):
            assert k in d, f"missing field {k} in stats"

    def test_referrals(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/customer/referrals", headers=auth_headers, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d
        assert isinstance(d["items"], list)

    def test_leaderboard(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/customer/leaderboard", headers=auth_headers, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "leaderboard" in d

    def test_pix_save(self, session, auth_headers):
        r = session.put(f"{BASE_URL}/api/customer/pix-key", headers=auth_headers,
                        json={"pix_key": VALID_CPF, "pix_key_type": "cpf"}, timeout=30)
        assert r.status_code == 200, f"pix save failed: {r.status_code} {r.text}"

    def test_referral_landing_regression(self, session, login_data):
        code = login_data["subscriber"]["referral_code"]
        # public landing page - just verify backend resolves referral code via public api
        # The frontend route /r/<code> serves React; backend has /api/referrals/landing/<code> typically
        # We test the frontend HTML is served (200 from root path with the code)
        r = requests.get(f"{BASE_URL}/r/{code}", timeout=30, allow_redirects=True)
        assert r.status_code == 200

    def test_unauthorized_me(self, session):
        r = session.get(f"{BASE_URL}/api/customer/me", timeout=30)
        assert r.status_code in (401, 403)
