import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _test_secrets import TEST_ADMIN_PASSWORD, TEST_AUDITOR_PASSWORD  # noqa: E402
"""Iteration 9: Tests for /dashboard/overtime/trend, vando login, PUT /users with email/password."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://selfie-attendance-7.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    return r


# ---------- AUTH / SEED USER vando ----------

def test_vando_login_returns_token_and_role_auditor():
    r = _login("vando@example.com", "123456")
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "access_token" in data and isinstance(data["access_token"], str)
    assert data["user"]["role"] == "auditor"
    assert data["user"]["name"] == "vando"
    assert data["user"]["email"] == "vando@example.com"


def test_admin_login_baseline():
    r = _login("admin@example.com", TEST_ADMIN_PASSWORD)
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "gestor"


@pytest.fixture(scope="module")
def admin_token():
    r = _login("admin@example.com", TEST_ADMIN_PASSWORD)
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# ---------- DASHBOARD TREND ----------

class TestDashboardTrend:
    def test_trend_default_6m(self):
        r = requests.get(f"{API}/dashboard/overtime/trend?months=6", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["months"] == 6
        assert isinstance(d["series"], list) and len(d["series"]) == 6
        for s in d["series"]:
            assert "label" in s
            assert "total_overtime_min" in s
            assert "total_paid_brl" in s
            assert "projected_overtime_min" in s
            assert "projected_paid_brl" in s
            assert "is_current" in s
        assert "top_debit" in d and isinstance(d["top_debit"], list)

    def test_trend_3m(self):
        r = requests.get(f"{API}/dashboard/overtime/trend?months=3", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["months"] == 3
        assert len(d["series"]) == 3

    def test_trend_12m(self):
        r = requests.get(f"{API}/dashboard/overtime/trend?months=12", timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert d["months"] == 12
        assert len(d["series"]) == 12

    def test_current_month_has_projection(self):
        r = requests.get(f"{API}/dashboard/overtime/trend?months=6", timeout=30)
        d = r.json()
        cur = [s for s in d["series"] if s["is_current"]]
        assert len(cur) == 1, "Deve existir exatamente um mês corrente"
        c = cur[0]
        # projected >= realized
        assert c["projected_overtime_min"] >= c["total_overtime_min"]
        assert c["projected_paid_brl"] >= c["total_paid_brl"]

    def test_top_debit_structure(self):
        r = requests.get(f"{API}/dashboard/overtime/trend?months=6", timeout=30)
        d = r.json()
        for row in d["top_debit"]:
            assert "collaborator_id" in row
            assert "name" in row
            assert "balance_min" in row
            assert row["balance_min"] < 0


# ---------- PUT /users/{uid} email + password ----------

class TestUpdateUser:
    @pytest.fixture
    def created_user(self, auth_headers):
        # cria via /users
        unique = uuid.uuid4().hex[:8]
        payload = {
            "email": f"TEST_user_{unique}@example.com",
            "password": "secret123",
            "name": "TEST User",
            "role": "colaborador",
        }
        r = requests.post(f"{API}/users", headers=auth_headers, json=payload, timeout=20)
        assert r.status_code in (200, 201), r.text
        u = r.json()
        yield u
        # cleanup
        requests.delete(f"{API}/users/{u['id']}", headers=auth_headers, timeout=20)

    def test_update_name_role_only_regression(self, auth_headers, created_user):
        uid = created_user["id"]
        r = requests.put(f"{API}/users/{uid}", headers=auth_headers,
                         json={"name": "Renamed", "role": "gestor"}, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == "Renamed"
        assert d["role"] == "gestor"

    def test_update_email_valid(self, auth_headers, created_user):
        uid = created_user["id"]
        new_email = f"TEST_renamed_{uuid.uuid4().hex[:6]}@example.com"
        r = requests.put(f"{API}/users/{uid}", headers=auth_headers,
                         json={"email": new_email}, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["email"] == new_email.lower()

    def test_update_email_invalid_returns_400(self, auth_headers, created_user):
        uid = created_user["id"]
        r = requests.put(f"{API}/users/{uid}", headers=auth_headers,
                         json={"email": "not-an-email"}, timeout=20)
        assert r.status_code == 400

    def test_update_email_duplicate_returns_400(self, auth_headers, created_user):
        uid = created_user["id"]
        r = requests.put(f"{API}/users/{uid}", headers=auth_headers,
                         json={"email": "admin@example.com"}, timeout=20)
        assert r.status_code == 400

    def test_update_password_too_short_returns_400(self, auth_headers, created_user):
        uid = created_user["id"]
        r = requests.put(f"{API}/users/{uid}", headers=auth_headers,
                         json={"password": "abc"}, timeout=20)
        assert r.status_code == 400

    def test_update_password_login_with_new(self, auth_headers, created_user):
        uid = created_user["id"]
        email = created_user["email"]
        new_pw = "newpass456"
        r = requests.put(f"{API}/users/{uid}", headers=auth_headers,
                         json={"password": new_pw}, timeout=20)
        assert r.status_code == 200, r.text
        # login com nova senha
        r2 = _login(email, new_pw)
        assert r2.status_code == 200, f"login w/ new pw failed: {r2.text}"
        # login com senha antiga deve falhar
        r3 = _login(email, "secret123")
        assert r3.status_code in (401, 429)

    def test_update_no_password_keeps_old(self, auth_headers, created_user):
        uid = created_user["id"]
        email = created_user["email"]
        # update só do nome
        r = requests.put(f"{API}/users/{uid}", headers=auth_headers,
                         json={"name": "Still Same Pw"}, timeout=20)
        assert r.status_code == 200
        # senha antiga ainda funciona
        r2 = _login(email, "secret123")
        assert r2.status_code == 200, f"old pw should still work: {r2.text}"
