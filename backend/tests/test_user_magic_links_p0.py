"""
P0 CTO Vando — Magic Links per user + collaborator_id unique link.

Cobre:
  * GET    /api/users/{uid}/magic-link          (auditor)
  * POST   /api/users/{uid}/magic-link/rotate   (auditor)
  * POST   /api/auth/magic-login                (PUBLIC)
  * POST   /api/users                           (collaborator_id unique)
  * PUT    /api/users/{uid}                     (collaborator_id unique)
"""
import os
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


# ──────────────────────── fixtures ────────────────────────
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=20)
    assert r.status_code == 200, f"login admin: {r.status_code} {r.text}"
    body = r.json()
    tok = body.get("access_token") or body.get("token")
    assert tok, f"no token in admin login: {body}"
    return tok


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def some_user_id(admin_headers):
    """Pega um user gestor/auditor qualquer com role != admin (ideal: Mayara)."""
    r = requests.get(f"{BASE_URL}/api/users", headers=admin_headers, timeout=20)
    assert r.status_code == 200, f"GET /users: {r.status_code} {r.text}"
    users = r.json() if isinstance(r.json(), list) else r.json().get("items") or r.json().get("users") or []
    # Prefer Mayara
    target = next((u for u in users if u.get("email") == "msaldanhavargasmiranda@gmail.com"), None)
    if not target:
        target = next((u for u in users if u.get("role") in ("gestor", "auditor")), None)
    assert target, "Nenhum user gestor/auditor encontrado"
    return target["id"]


# ───────────────── GET magic-link ─────────────────
class TestMagicLinkGet:
    def test_get_returns_active_and_reserve(self, admin_headers, some_user_id):
        r = requests.get(f"{BASE_URL}/api/users/{some_user_id}/magic-link",
                         headers=admin_headers, timeout=20)
        assert r.status_code == 200, f"GET magic-link: {r.status_code} {r.text}"
        data = r.json()
        assert data["user_id"] == some_user_id
        assert data.get("user_email")
        assert data.get("active") and data["active"].get("token"), "active token missing"
        assert data.get("reserve") and data["reserve"].get("token"), "reserve token missing"
        assert data["active"]["token"] != data["reserve"]["token"], "active==reserve!"
        assert data["active"]["status"] == "active"
        assert data["reserve"]["status"] == "reserve"
        # generations
        assert isinstance(data["active"]["generation"], int)
        assert isinstance(data["reserve"]["generation"], int)
        # _id never leaks
        assert "_id" not in data["active"]
        assert "_id" not in data["reserve"]

    def test_get_requires_auth(self, some_user_id):
        r = requests.get(f"{BASE_URL}/api/users/{some_user_id}/magic-link", timeout=20)
        assert r.status_code in (401, 403), f"esperava 401/403, veio {r.status_code}"


# ───────────────── ROTATE + magic-login ─────────────────
class TestMagicLinkRotateAndLogin:
    def test_rotate_revokes_active_promotes_reserve_new_reserve(self, admin_headers, some_user_id):
        # 1. captura ativo + reserva atuais
        r0 = requests.get(f"{BASE_URL}/api/users/{some_user_id}/magic-link",
                          headers=admin_headers, timeout=20)
        assert r0.status_code == 200
        prev = r0.json()
        prev_active_tok = prev["active"]["token"]
        prev_reserve_tok = prev["reserve"]["token"]
        prev_active_gen = prev["active"]["generation"]
        prev_reserve_gen = prev["reserve"]["generation"]

        # 2. rotate
        r1 = requests.post(f"{BASE_URL}/api/users/{some_user_id}/magic-link/rotate",
                           headers=admin_headers, json={"reason": "pytest"}, timeout=20)
        assert r1.status_code == 200, f"rotate: {r1.status_code} {r1.text}"
        rot = r1.json()
        assert rot.get("ok") is True
        assert rot.get("rotated_at")
        new_active = rot["active"]
        new_reserve = rot["reserve"]
        assert new_active["token"] == prev_reserve_tok, "ex-reserva deveria virar ativo"
        assert new_reserve["token"] != prev_active_tok and new_reserve["token"] != prev_reserve_tok, "novo reserva tem que ser inédito"
        assert new_active["status"] == "active"
        assert new_reserve["status"] == "reserve"
        assert new_reserve["generation"] > prev_reserve_gen, "geração do reserva tem que avançar"
        # store for next tests
        pytest._mlk = {
            "old_active": prev_active_tok,
            "new_active": new_active["token"],
            "new_reserve": new_reserve["token"],
        }

    def test_magic_login_with_old_active_returns_401(self):
        old = pytest._mlk["old_active"]
        r = requests.post(f"{BASE_URL}/api/auth/magic-login", json={"token": old}, timeout=20)
        assert r.status_code == 401, f"esperava 401 (revogado), veio {r.status_code} {r.text}"

    def test_magic_login_with_reserve_returns_401(self):
        res = pytest._mlk["new_reserve"]
        r = requests.post(f"{BASE_URL}/api/auth/magic-login", json={"token": res}, timeout=20)
        assert r.status_code == 401, f"reserva NÃO deve logar, veio {r.status_code} {r.text}"

    def test_magic_login_with_new_active_returns_jwt(self):
        tok = pytest._mlk["new_active"]
        r = requests.post(f"{BASE_URL}/api/auth/magic-login", json={"token": tok}, timeout=20)
        assert r.status_code == 200, f"esperava 200, veio {r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True
        assert body.get("access_token") and isinstance(body["access_token"], str)
        assert body.get("user") and body["user"].get("email")
        assert "password_hash" not in body["user"]
        # JWT é utilizável
        me = requests.get(f"{BASE_URL}/api/auth/me",
                         headers={"Authorization": f"Bearer {body['access_token']}"}, timeout=20)
        assert me.status_code == 200, f"/api/me com magic JWT: {me.status_code} {me.text}"

    def test_magic_login_invalid_token_401(self):
        r = requests.post(f"{BASE_URL}/api/auth/magic-login",
                          json={"token": "INVALID_" + uuid.uuid4().hex}, timeout=20)
        assert r.status_code == 401, f"esperava 401, veio {r.status_code}"

    def test_magic_login_short_token_400(self):
        r = requests.post(f"{BASE_URL}/api/auth/magic-login", json={"token": "abc"}, timeout=20)
        assert r.status_code == 400


# ───────────────── collaborator_id UNIQUE ─────────────────
class TestCollaboratorUnique:
    def test_create_user_with_taken_collaborator_returns_409(self, admin_headers):
        # Mayara está com col-227d942d (per task description) — reusar deve dar 409
        payload = {
            "email": f"TEST_dup_{uuid.uuid4().hex[:6]}@example.com",
            "name": "TEST dup col",
            "password": "Test1234!",
            "role": "gestor",
            "collaborator_id": "col-227d942d",
        }
        r = requests.post(f"{BASE_URL}/api/users", headers=admin_headers, json=payload, timeout=20)
        # se col-227d942d não existir mais → 404. Caso contrário esperamos 409.
        assert r.status_code in (409, 404), f"esperava 409/404, veio {r.status_code} {r.text}"
        if r.status_code == 409:
            assert "vinculado" in r.text.lower()

    def test_put_user_with_taken_collaborator_returns_409(self, admin_headers, some_user_id):
        # Pega outro user diferente do Mayara
        r = requests.get(f"{BASE_URL}/api/users", headers=admin_headers, timeout=20)
        users = r.json() if isinstance(r.json(), list) else r.json().get("items") or []
        mayara = next((u for u in users if u.get("email") == "msaldanhavargasmiranda@gmail.com"), None)
        if not mayara or not mayara.get("collaborator_id"):
            pytest.skip("Mayara sem collaborator_id setado — skip")
        target = next((u for u in users
                       if u.get("role") in ("gestor", "auditor")
                       and u.get("email") != "msaldanhavargasmiranda@gmail.com"
                       and u.get("email") != ADMIN_EMAIL
                       and not u.get("is_super_admin")), None)
        if not target:
            pytest.skip("sem outro user disponivel")
        r2 = requests.put(f"{BASE_URL}/api/users/{target['id']}",
                          headers=admin_headers,
                          json={"collaborator_id": mayara["collaborator_id"]}, timeout=20)
        assert r2.status_code == 409, f"esperava 409, veio {r2.status_code} {r2.text}"
        assert "vinculado" in r2.text.lower()

    def test_put_user_collaborator_null_ok(self, admin_headers):
        # Cria um novo user, depois zera o collaborator_id (deve dar 200)
        email = f"TEST_clr_{uuid.uuid4().hex[:6]}@example.com"
        cr = requests.post(f"{BASE_URL}/api/users", headers=admin_headers, json={
            "email": email, "name": "TEST clr", "password": "Test1234!", "role": "gestor"
        }, timeout=20)
        assert cr.status_code in (200, 201), f"create: {cr.status_code} {cr.text}"
        uid = cr.json()["id"]
        upd = requests.put(f"{BASE_URL}/api/users/{uid}",
                           headers=admin_headers,
                           json={"collaborator_id": None}, timeout=20)
        assert upd.status_code == 200, f"PUT null: {upd.status_code} {upd.text}"
        # cleanup
        requests.delete(f"{BASE_URL}/api/users/{uid}", headers=admin_headers, timeout=20)
