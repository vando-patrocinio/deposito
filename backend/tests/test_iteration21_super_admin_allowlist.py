"""Iteration 21 — SUPER_ADMIN_EMAILS allowlist tests.

Cobre:
- POST /api/auth/google-login: auto-cria, reativa, super_admin flag, 404, 403, 422, 401
- POST /api/collaborator-auth/process-session: auto-cria, bypass device, 409 normal, 404 normal
- GET  /api/collaborator-auth/me com sessão criada via super-admin
- Regressão: /api/auth/login (vando@example.com) e /api/users (auditor)

Estratégia:
- httpx.AsyncClient é monkey-patchado para simular respostas do Emergent OAuth
  (o serviço externo NÃO pode ser chamado em CI).
- Usamos FastAPI TestClient apontando para o app real (server.app) com Mongo real.
- Cleanup pré e pós: remove user/collaborator com email = vando.patrocinio@gmail.com.
"""
from __future__ import annotations

import os
import sys
import uuid
from typing import Optional

import pytest
import requests
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

# Use sync pymongo for test cleanup to avoid event-loop binding issues with motor.
_sync_client = MongoClient(os.environ["MONGO_URL"])
sdb = _sync_client[os.environ["DB_NAME"]]

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://selfie-attendance-7.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

SUPER_ADMIN_EMAIL = "vando.patrocinio@gmail.com"
NON_SUPER_EMAIL = "no.such.user.iter21@example.com"


# ---------------------------------------------------------------------------
# httpx mock infrastructure
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, json_data: Optional[dict] = None):
        self.status_code = status_code
        self._json = json_data or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("GET", "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data")
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=req,
                response=httpx.Response(self.status_code, request=req),
            )


class _FakeAsyncClient:
    """Replacement for httpx.AsyncClient that returns a configurable response.

    Configure via _FakeAsyncClient.set_response(status, payload).
    """

    _status: int = 200
    _payload: dict = {"email": SUPER_ADMIN_EMAIL, "name": "Vando Patrocinio", "picture": ""}

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, **kw):
        return _FakeResponse(self._status, dict(self._payload))

    @classmethod
    def set_response(cls, status: int, payload: Optional[dict] = None):
        cls._status = status
        cls._payload = payload if payload is not None else {}


@pytest.fixture(autouse=True)
def _patch_httpx(monkeypatch):
    """Patch httpx.AsyncClient globally so both routes/users.py (lazy import) and
    routes/collab_auth.py (top-level import) get the fake client."""
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    # collab_auth imported httpx at module load → re-patch attribute
    import routes.collab_auth as ca
    monkeypatch.setattr(ca.httpx, "AsyncClient", _FakeAsyncClient)
    yield


# ---------------------------------------------------------------------------
# DB cleanup helpers
# ---------------------------------------------------------------------------


def _run(coro):
    raise RuntimeError("not used")


def _cleanup():
    sdb.users.delete_many({"email": SUPER_ADMIN_EMAIL})
    sdb.users.delete_many({"google_email": SUPER_ADMIN_EMAIL})
    cids = [c["id"] for c in sdb.collaborators.find(
        {"$or": [{"email": SUPER_ADMIN_EMAIL}, {"google_email": SUPER_ADMIN_EMAIL}]},
        {"_id": 0, "id": 1},
    )]
    if cids:
        sdb.collaborator_sessions.delete_many({"collaborator_id": {"$in": cids}})
    sdb.collaborators.delete_many(
        {"$or": [{"email": SUPER_ADMIN_EMAIL}, {"google_email": SUPER_ADMIN_EMAIL}]}
    )


@pytest.fixture(autouse=True)
def _clean_super_admin():
    _cleanup()
    yield
    _cleanup()


@pytest.fixture(scope="module")
def client():
    # Ensure SUPER_ADMIN_EMAILS env var is set for this test process
    os.environ.setdefault("SUPER_ADMIN_EMAILS", SUPER_ADMIN_EMAIL)
    with TestClient(server.app) as c:
        yield c


# ---------------------------------------------------------------------------
# /api/auth/google-login (sistema)
# ---------------------------------------------------------------------------


class TestGoogleLoginSuperAdmin:
    def test_super_admin_auto_creates_as_auditor(self, client):
        _FakeAsyncClient.set_response(200, {"email": SUPER_ADMIN_EMAIL, "name": "Vando", "picture": ""})
        r = client.post("/api/auth/google-login", json={"session_id": "fake-sid"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["super_admin"] is True
        assert body["user"]["email"] == SUPER_ADMIN_EMAIL
        assert body["user"]["role"] == "auditor"
        assert body["user"]["active"] is True
        assert "access_token" in body and len(body["access_token"]) > 20
        # persisted?
        u = sdb.users.find_one({"email": SUPER_ADMIN_EMAIL})
        assert u is not None
        assert u.get("role") == "auditor"
        assert u.get("auto_created") is True

    def test_super_admin_reactivates_disabled_user(self, client):
        # Pre-create disabled user
        uid = f"usr-{uuid.uuid4().hex[:10]}"
        sdb.users.insert_one({
            "id": uid, "email": SUPER_ADMIN_EMAIL, "name": "Vando", "role": "auditor",
            "password_hash": "$2b$12$abcdefghijklmnopqrstuv", "active": False,
        })
        _FakeAsyncClient.set_response(200, {"email": SUPER_ADMIN_EMAIL, "name": "Vando", "picture": ""})
        r = client.post("/api/auth/google-login", json={"session_id": "fake-sid"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["super_admin"] is True
        assert body["user"]["active"] is True
        u = sdb.users.find_one({"id": uid})
        assert u["active"] is True

    def test_super_admin_existing_active_user_returns_super_admin_true(self, client):
        uid = f"usr-{uuid.uuid4().hex[:10]}"
        sdb.users.insert_one({
            "id": uid, "email": SUPER_ADMIN_EMAIL, "name": "Vando", "role": "auditor",
            "password_hash": "$2b$12$abcdefghijklmnopqrstuv", "active": True,
        })
        _FakeAsyncClient.set_response(200, {"email": SUPER_ADMIN_EMAIL, "name": "Vando", "picture": "http://x/y.png"})
        r = client.post("/api/auth/google-login", json={"session_id": "fake-sid"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["super_admin"] is True
        assert body["user"]["id"] == uid
        assert body["user"]["google_picture"] == "http://x/y.png"

    def test_non_super_admin_unknown_email_returns_404(self, client):
        _FakeAsyncClient.set_response(200, {"email": NON_SUPER_EMAIL, "name": "Ghost", "picture": ""})
        r = client.post("/api/auth/google-login", json={"session_id": "fake-sid"})
        assert r.status_code == 404, r.text
        assert NON_SUPER_EMAIL in r.json().get("detail", "")

    def test_non_super_admin_disabled_user_returns_403(self, client):
        email = "disabled.iter21@example.com"
        sdb.users.delete_many({"email": email})
        uid = f"usr-{uuid.uuid4().hex[:10]}"
        sdb.users.insert_one({
            "id": uid, "email": email, "name": "X", "role": "gestor",
            "password_hash": "$2b$12$abcdefghijklmnopqrstuv", "active": False,
        })
        _FakeAsyncClient.set_response(200, {"email": email, "name": "X", "picture": ""})
        r = client.post("/api/auth/google-login", json={"session_id": "fake-sid"})
        sdb.users.delete_one({"id": uid})
        assert r.status_code == 403, r.text

    def test_missing_session_id_returns_422(self, client):
        # body missing session_id field → pydantic 422
        r = client.post("/api/auth/google-login", json={})
        assert r.status_code == 422, r.text

    def test_invalid_session_id_returns_401(self, client):
        # Emergent returned 404 → route raises 401
        _FakeAsyncClient.set_response(404, {})
        r = client.post("/api/auth/google-login", json={"session_id": "invalid"})
        assert r.status_code == 401, r.text

    def test_response_includes_super_admin_field_for_non_super(self, client):
        # active non-super existing user: super_admin must be False
        email = "regular.iter21@example.com"
        sdb.users.delete_many({"email": email})
        uid = f"usr-{uuid.uuid4().hex[:10]}"
        sdb.users.insert_one({
            "id": uid, "email": email, "name": "Reg", "role": "gestor",
            "password_hash": "$2b$12$abcdefghijklmnopqrstuv", "active": True,
        })
        _FakeAsyncClient.set_response(200, {"email": email, "name": "Reg", "picture": ""})
        r = client.post("/api/auth/google-login", json={"session_id": "fake-sid"})
        sdb.users.delete_one({"id": uid})
        assert r.status_code == 200
        body = r.json()
        assert body["super_admin"] is False


# ---------------------------------------------------------------------------
# /api/collaborator-auth/process-session
# ---------------------------------------------------------------------------


class TestCollabProcessSessionSuperAdmin:
    def test_super_admin_no_collab_auto_creates(self, client):
        _FakeAsyncClient.set_response(200, {"email": SUPER_ADMIN_EMAIL, "name": "Vando", "picture": ""})
        r = client.post("/api/collaborator-auth/process-session",
                        json={"session_id": "sid", "device_id": "device-A"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["google_email"] == SUPER_ADMIN_EMAIL
        assert body["collaborator"]["device_id"] == "device-A"
        assert body["collaborator"].get("auto_created_super_admin") is True
        c = sdb.collaborators.find_one({"email": SUPER_ADMIN_EMAIL})
        assert c is not None

    def test_super_admin_changes_device_without_409(self, client):
        # 1st bind: device-A (auto-create)
        _FakeAsyncClient.set_response(200, {"email": SUPER_ADMIN_EMAIL, "name": "V", "picture": ""})
        r1 = client.post("/api/collaborator-auth/process-session",
                         json={"session_id": "sid1", "device_id": "device-A"})
        assert r1.status_code == 200
        # 2nd bind same email but different device — must NOT be 409
        r2 = client.post("/api/collaborator-auth/process-session",
                         json={"session_id": "sid2", "device_id": "device-B"})
        assert r2.status_code == 200, r2.text
        assert r2.json()["collaborator"]["device_id"] == "device-B"

    def test_non_super_admin_with_different_device_returns_409(self, client):
        # Create a regular collaborator bound to device-A
        email = "collab.iter21@example.com"
        sdb.collaborators.delete_many({"email": email})
        cid = f"col-it21-{uuid.uuid4().hex[:6]}"
        sdb.collaborators.insert_one({
            "id": cid, "name": "Col21", "cpf": f"X-{cid[-6:]}", "email": email,
            "device_id": "device-A",
            "schedule": {"entrada": "08:00", "inicio_intervalo": "12:00",
                         "fim_intervalo": "13:00", "saida": "17:00"},
        })
        _FakeAsyncClient.set_response(200, {"email": email, "name": "Col21", "picture": ""})
        r = client.post("/api/collaborator-auth/process-session",
                        json={"session_id": "sid", "device_id": "device-B"})
        sdb.collaborator_sessions.delete_many({"collaborator_id": cid})
        sdb.collaborators.delete_one({"id": cid})
        assert r.status_code == 409, r.text

    def test_non_super_admin_unknown_email_returns_404(self, client):
        _FakeAsyncClient.set_response(200, {"email": NON_SUPER_EMAIL, "name": "G", "picture": ""})
        r = client.post("/api/collaborator-auth/process-session",
                        json={"session_id": "sid", "device_id": "device-X"})
        assert r.status_code == 404, r.text

    def test_me_endpoint_with_super_admin_session(self, client):
        # Auto-create session via process-session
        _FakeAsyncClient.set_response(200, {"email": SUPER_ADMIN_EMAIL, "name": "V", "picture": ""})
        r = client.post("/api/collaborator-auth/process-session",
                        json={"session_id": "sid", "device_id": "dev-me"})
        assert r.status_code == 200
        token = r.json()["session_token"]
        # GET /me using Bearer
        r2 = client.get("/api/collaborator-auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 200, r2.text
        body = r2.json()
        assert body["google_email"] == SUPER_ADMIN_EMAIL
        assert body["device_id"] == "dev-me"
        assert body["collaborator"]["email"] == SUPER_ADMIN_EMAIL


# ---------------------------------------------------------------------------
# Regressão (via URL pública — sem mocks)
# ---------------------------------------------------------------------------


class TestRegression:
    def test_legacy_login_vando_still_works(self):
        r = requests.post(f"{API}/auth/login",
                          json={"email": "vando@example.com", "password": "123456"},
                          timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "access_token" in body
        assert body["user"]["email"] == "vando@example.com"
        assert body["user"]["role"] == "auditor"

    def test_users_list_with_auditor_token(self):
        r = requests.post(f"{API}/auth/login",
                          json={"email": "vando@example.com", "password": "123456"},
                          timeout=15)
        assert r.status_code == 200
        token = r.json()["access_token"]
        r2 = requests.get(f"{API}/users", headers={"Authorization": f"Bearer {token}"}, timeout=15)
        assert r2.status_code == 200, r2.text
        users = r2.json()
        assert isinstance(users, list)
        assert any(u.get("email") == "vando@example.com" for u in users)
