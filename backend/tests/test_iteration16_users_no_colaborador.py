import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _test_secrets import TEST_ADMIN_PASSWORD, TEST_AUDITOR_PASSWORD  # noqa: E402
"""
Iteration 16 — Conceptual separation between Cadastro (employees) and Users (system access).
Backend validations:
  - POST /api/users with role='colaborador' must return 400 with pt-BR message about Cadastro.
  - POST /api/users with role='gestor' or 'auditor' works normally.
  - PUT /api/users/{uid} with role='colaborador' must return 400.
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

AUDITOR_EMAIL = "vando@example.com"
AUDITOR_PASS = "123456"
GESTOR_EMAIL = "admin@example.com"
GESTOR_PASS = TEST_ADMIN_PASSWORD


@pytest.fixture(scope="module")
def auditor_token():
    r = requests.post(f"{API}/auth/login", json={"email": AUDITOR_EMAIL, "password": AUDITOR_PASS}, timeout=15)
    if r.status_code != 200:
        pytest.skip(f"Auditor login failed: {r.status_code} {r.text}")
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auditor_session(auditor_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {auditor_token}", "Content-Type": "application/json"})
    return s


def _unique_email(prefix="TEST_iter16"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


# Bloqueio de criação de role=colaborador via /api/users
class TestCreateUserBlocksColaborador:
    def test_post_users_role_colaborador_returns_400(self, auditor_session):
        payload = {"email": _unique_email(), "name": "TEST Colaborador", "role": "colaborador", "password": "abc123"}
        r = auditor_session.post(f"{API}/users", json=payload, timeout=15)
        assert r.status_code == 400, f"Esperava 400, recebeu {r.status_code}: {r.text}"
        detail = (r.json().get("detail") or "").lower()
        assert "cadastro" in detail, f"Mensagem deve mencionar 'Cadastro'. Recebido: {detail}"
        # pt-BR
        assert any(w in detail for w in ["colaborador", "ponto", "gestor", "auditor"]), \
            f"Mensagem deve estar em pt-BR. Recebido: {detail}"

    def test_post_users_role_gestor_succeeds(self, auditor_session):
        email = _unique_email()
        payload = {"email": email, "name": "TEST Gestor 16", "role": "gestor", "password": "abc123"}
        r = auditor_session.post(f"{API}/users", json=payload, timeout=15)
        assert r.status_code == 200, f"Esperava 200, recebeu {r.status_code}: {r.text}"
        data = r.json()
        assert data["role"] == "gestor"
        assert data["email"] == email.lower()
        uid = data["id"]
        # GET to verify persistence
        lst = auditor_session.get(f"{API}/users", timeout=15).json()
        assert any(u["id"] == uid for u in lst)
        # cleanup
        auditor_session.delete(f"{API}/users/{uid}", timeout=15)

    def test_post_users_role_auditor_succeeds(self, auditor_session):
        email = _unique_email()
        payload = {"email": email, "name": "TEST Auditor 16", "role": "auditor", "password": "abc123"}
        r = auditor_session.post(f"{API}/users", json=payload, timeout=15)
        assert r.status_code == 200, f"Esperava 200, recebeu {r.status_code}: {r.text}"
        data = r.json()
        assert data["role"] == "auditor"
        uid = data["id"]
        auditor_session.delete(f"{API}/users/{uid}", timeout=15)


# Bloqueio de update para role=colaborador
class TestUpdateUserBlocksColaborador:
    def test_put_users_role_colaborador_returns_400(self, auditor_session):
        # Cria um gestor primeiro
        email = _unique_email("TEST_iter16_upd")
        cr = auditor_session.post(f"{API}/users", json={"email": email, "name": "TEST Upd", "role": "gestor", "password": "abc123"}, timeout=15)
        assert cr.status_code == 200, cr.text
        uid = cr.json()["id"]
        try:
            r = auditor_session.put(f"{API}/users/{uid}", json={"role": "colaborador"}, timeout=15)
            assert r.status_code == 400, f"Esperava 400, recebeu {r.status_code}: {r.text}"
            detail = (r.json().get("detail") or "").lower()
            assert "cadastro" in detail, f"Mensagem deve mencionar 'Cadastro'. Recebido: {detail}"
        finally:
            auditor_session.delete(f"{API}/users/{uid}", timeout=15)

    def test_put_users_role_auditor_succeeds(self, auditor_session):
        email = _unique_email("TEST_iter16_upd_ok")
        cr = auditor_session.post(f"{API}/users", json={"email": email, "name": "TEST UpdOk", "role": "gestor", "password": "abc123"}, timeout=15)
        assert cr.status_code == 200
        uid = cr.json()["id"]
        try:
            r = auditor_session.put(f"{API}/users/{uid}", json={"role": "auditor"}, timeout=15)
            assert r.status_code == 200, r.text
            assert r.json()["role"] == "auditor"
        finally:
            auditor_session.delete(f"{API}/users/{uid}", timeout=15)


# Regressão: gestor continua bloqueado de criar usuários (require_role auditor)
class TestGestorCannotCreateUsers:
    def test_gestor_post_users_returns_403(self):
        r = requests.post(f"{API}/auth/login", json={"email": GESTOR_EMAIL, "password": GESTOR_PASS}, timeout=15)
        if r.status_code != 200:
            pytest.skip("Gestor login indisponível")
        tok = r.json()["access_token"]
        s = requests.Session()
        s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
        rr = s.post(f"{API}/users", json={"email": _unique_email(), "name": "x", "role": "gestor", "password": "abc123"}, timeout=15)
        assert rr.status_code == 403, f"Gestor deveria receber 403; recebeu {rr.status_code}: {rr.text}"
