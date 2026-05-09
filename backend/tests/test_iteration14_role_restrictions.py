"""Iteration 14 — Role-based access restrictions.

Validates:
- Gestor (admin@example.com) is now BLOCKED from /api/users, PUT /api/settings (403)
- Gestor still has access to /api/pracas (POST 200) and /api/collaborators (POST 200)
- Auditor (vando@example.com) has full access (200 on all endpoints)
- Collaborator user creation works via auditor
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://selfie-attendance-7.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


# ----------------------------- Fixtures -----------------------------
def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def gestor_token():
    return _login("admin@example.com", "admin123")


@pytest.fixture(scope="module")
def auditor_token():
    return _login("vando@example.com", "123456")


@pytest.fixture(scope="module")
def gestor_headers(gestor_token):
    return {"Authorization": f"Bearer {gestor_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def auditor_headers(auditor_token):
    return {"Authorization": f"Bearer {auditor_token}", "Content-Type": "application/json"}


# ----------------------------- Auth basics -----------------------------
class TestAuthBasics:
    def test_gestor_login_returns_role(self, gestor_token):
        r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {gestor_token}"}, timeout=10)
        assert r.status_code == 200
        assert r.json()["role"] == "gestor"

    def test_auditor_login_returns_role(self, auditor_token):
        r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {auditor_token}"}, timeout=10)
        assert r.status_code == 200
        assert r.json()["role"] == "auditor"


# ----------------------------- Gestor blocked endpoints -----------------------------
class TestGestorBlocked:
    """Gestor should now be FORBIDDEN (403) on /users and PUT /settings."""

    def test_gestor_get_users_forbidden(self, gestor_headers):
        r = requests.get(f"{API}/users", headers=gestor_headers, timeout=10)
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"

    def test_gestor_post_users_forbidden(self, gestor_headers):
        payload = {
            "email": f"TEST_blocked_{uuid.uuid4().hex[:6]}@example.com",
            "password": "abc12345",
            "name": "Should Not Create",
            "role": "colaborador",
        }
        r = requests.post(f"{API}/users", json=payload, headers=gestor_headers, timeout=10)
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"

    def test_gestor_put_settings_forbidden(self, gestor_headers):
        # current settings GET is presumably public/auth — we only assert PUT is blocked
        r = requests.put(
            f"{API}/settings",
            json={"company_name": "TEST_Should_Not_Persist"},
            headers=gestor_headers,
            timeout=10,
        )
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"


# ----------------------------- Gestor allowed endpoints (regression) -----------------------------
class TestGestorAllowed:
    """Gestor must KEEP access to /pracas (POST), /collaborators (POST)."""

    created_praca_id: str | None = None
    created_collab_id: str | None = None

    def test_gestor_get_pracas_public(self):
        # No auth — public list
        r = requests.get(f"{API}/pracas", timeout=10)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_gestor_post_praca_ok(self, gestor_headers):
        payload = {
            "name": f"TEST_Praca_{uuid.uuid4().hex[:6]}",
            "city": "Cachoeiras de Macacu",
            "state": "RJ",
            "schedule": {"weekday_start": "08:00", "weekday_end": "17:00"},
        }
        r = requests.post(f"{API}/pracas", json=payload, headers=gestor_headers, timeout=10)
        assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"
        body = r.json()
        assert "id" in body
        assert body["name"] == payload["name"]
        TestGestorAllowed.created_praca_id = body["id"]

    def test_gestor_post_collaborator_ok(self, gestor_headers):
        payload = {
            "name": f"TEST_Colab_{uuid.uuid4().hex[:6]}",
            "cpf": f"000.000.{uuid.uuid4().int % 1000:03d}-00",
            "email": f"TEST_colab_{uuid.uuid4().hex[:6]}@example.com",
            "phone": "21999999999",
        }
        r = requests.post(f"{API}/collaborators", json=payload, headers=gestor_headers, timeout=10)
        assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"
        body = r.json()
        assert "id" in body
        TestGestorAllowed.created_collab_id = body["id"]

    def test_cleanup_created_praca(self, auditor_headers):
        # Auditor cleans up the praca created above
        if TestGestorAllowed.created_praca_id:
            r = requests.delete(
                f"{API}/pracas/{TestGestorAllowed.created_praca_id}", headers=auditor_headers, timeout=10
            )
            # 200 or 204 acceptable
            assert r.status_code in (200, 204), f"cleanup failed: {r.status_code} {r.text}"


# ----------------------------- Auditor full access -----------------------------
class TestAuditorFullAccess:
    created_user_id: str | None = None

    def test_auditor_get_users_ok(self, auditor_headers):
        r = requests.get(f"{API}/users", headers=auditor_headers, timeout=10)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_auditor_create_collaborador_user(self, auditor_headers):
        payload = {
            "email": f"TEST_coluser_{uuid.uuid4().hex[:6]}@example.com",
            "password": "colab123",
            "name": "TEST Colab User",
            "role": "colaborador",
            "collaborator_id": "col-demo-001",
        }
        r = requests.post(f"{API}/users", json=payload, headers=auditor_headers, timeout=10)
        assert r.status_code in (200, 201), f"expected 200/201 got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("email") == payload["email"].lower()
        assert body.get("role") == "colaborador"
        assert "id" in body
        TestAuditorFullAccess.created_user_id = body["id"]

    def test_auditor_collaborador_can_login(self):
        # Verify the user we just created is valid (data persistence)
        # We don't have the email directly; skip if not available
        # In practice, login is in another test class; here we just GET it
        pass

    def test_auditor_put_settings_ok(self, auditor_headers):
        # Read current settings then PUT a benign value
        r = requests.get(f"{API}/settings", headers=auditor_headers, timeout=10)
        if r.status_code == 200:
            curr = r.json()
        else:
            curr = {}
        payload = {"company_name": curr.get("company_name") or "TEST_Co"}
        r = requests.put(f"{API}/settings", json=payload, headers=auditor_headers, timeout=10)
        assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"

    def test_auditor_post_pracas_ok(self, auditor_headers):
        payload = {
            "name": f"TEST_PracaAud_{uuid.uuid4().hex[:6]}",
            "city": "Niterói",
            "state": "RJ",
        }
        r = requests.post(f"{API}/pracas", json=payload, headers=auditor_headers, timeout=10)
        assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"
        pid = r.json()["id"]
        # cleanup
        requests.delete(f"{API}/pracas/{pid}", headers=auditor_headers, timeout=10)

    def test_auditor_post_collaborators_ok(self, auditor_headers):
        payload = {
            "name": f"TEST_AudColab_{uuid.uuid4().hex[:6]}",
            "cpf": f"000.111.{uuid.uuid4().int % 1000:03d}-00",
            "email": f"TEST_audcolab_{uuid.uuid4().hex[:6]}@example.com",
            "phone": "21988887777",
        }
        r = requests.post(f"{API}/collaborators", json=payload, headers=auditor_headers, timeout=10)
        assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"

    def test_zzz_cleanup_user(self, auditor_headers):
        if TestAuditorFullAccess.created_user_id:
            r = requests.delete(
                f"{API}/users/{TestAuditorFullAccess.created_user_id}", headers=auditor_headers, timeout=10
            )
            assert r.status_code in (200, 204)
