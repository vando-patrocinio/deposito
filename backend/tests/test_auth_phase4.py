import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _test_secrets import TEST_ADMIN_PASSWORD, TEST_AUDITOR_PASSWORD  # noqa: E402
"""Phase 4 Auth tests: login, /auth/me, users CRUD, role gating, lockout, legacy."""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://selfie-attendance-7.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASS = TEST_ADMIN_PASSWORD
AUDITOR_EMAIL = "auditor@example.com"
AUDITOR_PASS = TEST_AUDITOR_PASSWORD


def _login(email, pw):
    return requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)


@pytest.fixture(scope="module")
def admin_token():
    r = _login(ADMIN_EMAIL, ADMIN_PASS)
    assert r.status_code == 200, f"login admin falhou: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auditor_token():
    r = _login(AUDITOR_EMAIL, AUDITOR_PASS)
    assert r.status_code == 200, f"login auditor falhou: {r.status_code} {r.text}"
    return r.json()["access_token"]


def hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


# --- Login ---
class TestLogin:
    def test_login_admin(self):
        r = _login(ADMIN_EMAIL, ADMIN_PASS)
        assert r.status_code == 200
        d = r.json()
        assert "access_token" in d and len(d["access_token"]) > 20
        assert d["user"]["role"] == "gestor"
        assert d["user"]["email"] == ADMIN_EMAIL

    def test_login_auditor(self):
        r = _login(AUDITOR_EMAIL, AUDITOR_PASS)
        assert r.status_code == 200
        d = r.json()
        assert d["user"]["role"] == "auditor"

    def test_login_invalid(self):
        r = _login(ADMIN_EMAIL, "senhaerrada-xyz")
        assert r.status_code == 401

    def test_login_unknown_email(self):
        r = _login(f"nao-existe-{uuid.uuid4().hex[:6]}@x.com", "whatever")
        assert r.status_code == 401


# --- /auth/me ---
class TestAuthMe:
    def test_me_no_auth(self):
        r = requests.get(f"{API}/auth/me", timeout=10)
        assert r.status_code == 401

    def test_me_with_token(self, admin_token):
        r = requests.get(f"{API}/auth/me", headers=hdr(admin_token), timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert d["email"] == ADMIN_EMAIL
        assert d["role"] == "gestor"
        assert "password_hash" not in d


# --- Users CRUD + role gating ---
class TestUsersCrud:
    created_uid = None
    created_email = f"test_{uuid.uuid4().hex[:8]}@example.com"

    def test_list_users_as_gestor(self, admin_token):
        r = requests.get(f"{API}/users", headers=hdr(admin_token), timeout=10)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_user(self, admin_token):
        payload = {
            "email": TestUsersCrud.created_email,
            "password": "test123456",
            "name": "TEST User",
            "role": "colaborador",
        }
        r = requests.post(f"{API}/users", json=payload, headers=hdr(admin_token), timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["email"] == payload["email"]
        assert d["role"] == "colaborador"
        assert "password_hash" not in d
        TestUsersCrud.created_uid = d["id"]

    def test_list_as_colaborador_returns_403(self):
        # login with newly created colaborador
        r = _login(TestUsersCrud.created_email, "test123456")
        assert r.status_code == 200
        colab_tok = r.json()["access_token"]
        r2 = requests.get(f"{API}/users", headers=hdr(colab_tok), timeout=10)
        assert r2.status_code == 403

    def test_update_user(self, admin_token):
        uid = TestUsersCrud.created_uid
        assert uid
        r = requests.put(
            f"{API}/users/{uid}",
            json={"name": "TEST Updated", "role": "gestor", "active": True},
            headers=hdr(admin_token), timeout=10,
        )
        assert r.status_code == 200
        assert r.json()["name"] == "TEST Updated"
        assert r.json()["role"] == "gestor"

    def test_set_password_admin(self, admin_token):
        uid = TestUsersCrud.created_uid
        new_pw = "nova-senha-123"
        r = requests.post(
            f"{API}/users/set-password",
            json={"user_id": uid, "new_password": new_pw},
            headers=hdr(admin_token), timeout=10,
        )
        assert r.status_code == 200
        # verify login with new password
        r2 = _login(TestUsersCrud.created_email, new_pw)
        assert r2.status_code == 200

    def test_cannot_delete_self(self, admin_token):
        # find admin id
        r = requests.get(f"{API}/auth/me", headers=hdr(admin_token), timeout=10)
        my_id = r.json()["id"]
        rd = requests.delete(f"{API}/users/{my_id}", headers=hdr(admin_token), timeout=10)
        assert rd.status_code == 400

    def test_delete_created_user(self, admin_token):
        uid = TestUsersCrud.created_uid
        r = requests.delete(f"{API}/users/{uid}", headers=hdr(admin_token), timeout=10)
        assert r.status_code == 200


# --- change-my-password ---
class TestChangeMyPassword:
    def test_wrong_current_password(self, auditor_token):
        r = requests.post(
            f"{API}/auth/change-my-password",
            json={"current_password": "errada-xxx", "new_password": "newpass12"},
            headers=hdr(auditor_token), timeout=10,
        )
        assert r.status_code == 401

    def test_correct_then_revert(self):
        # login auditor fresh
        r = _login(AUDITOR_EMAIL, AUDITOR_PASS)
        assert r.status_code == 200
        tok = r.json()["access_token"]
        tmp_pw = "tmp-pass-123"
        r2 = requests.post(
            f"{API}/auth/change-my-password",
            json={"current_password": AUDITOR_PASS, "new_password": tmp_pw},
            headers=hdr(tok), timeout=10,
        )
        assert r2.status_code == 200
        # login with new
        r3 = _login(AUDITOR_EMAIL, tmp_pw)
        assert r3.status_code == 200
        # revert
        tok2 = r3.json()["access_token"]
        r4 = requests.post(
            f"{API}/auth/change-my-password",
            json={"current_password": tmp_pw, "new_password": AUDITOR_PASS},
            headers=hdr(tok2), timeout=10,
        )
        assert r4.status_code == 200


# --- Legacy admin-login ---
class TestLegacyAdminLogin:
    def test_admin_login_ok(self):
        r = requests.post(f"{API}/auth/admin-login", json={"password": ADMIN_PASS}, timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert d["role"] == "gestor"
        assert "access_token" in d

    def test_admin_login_wrong(self):
        r = requests.post(f"{API}/auth/admin-login", json={"password": "wrong-xxx"}, timeout=10)
        assert r.status_code == 401


# --- Brute force lockout ---
class TestLockout:
    def test_lockout_after_5_fails(self):
        # use a unique email to avoid locking real accounts
        target = f"lockout_{uuid.uuid4().hex[:8]}@test.com"
        # 5 failed attempts
        for i in range(5):
            r = requests.post(f"{API}/auth/login", json={"email": target, "password": "wrong"}, timeout=10)
            assert r.status_code == 401
        # 6th should be 429
        r6 = requests.post(f"{API}/auth/login", json={"email": target, "password": "wrong"}, timeout=10)
        assert r6.status_code == 429, f"expected 429 got {r6.status_code} {r6.text}"
