"""
test_iter222_audit_trail.py — Sprint 3 / Audit Trail + Governança.

Cobre:
  1. Admin acessa GET /api/audit-log
  2. Auditor acessa GET /api/audit-log
  3. Colaborador é bloqueado (403)
  4. Eventos DELETE viram entradas em audit_log
  5. Mascaramento de email/IP em listagem
  6. Endpoint /api/presidente-ia/security/alerts roda detectores
  7. Endpoint /api/presidente-ia/security/insight retorna resumo
  8. Detector de mass-export gera alerta após N exports
  9. RBAC bloqueado gera categoria=rbac_blocked

Setup: criamos usuários reais em DB via pymongo SÍNCRONO (evita
conflito de event loop com motor + TestClient).

Roda:
    cd /app && pytest backend/tests/test_iter222_audit_trail.py -v
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("ALLOW_MOCK_MODULES", "true")
    from server import app as fastapi_app
    return fastapi_app


@pytest.fixture(scope="module")
def client(app):
    # `with TestClient(app)` mantém o lifespan vivo durante TODOS os
    # testes do módulo. Cada módulo de teste roda em um loop próprio;
    # se você invocar este módulo + outro que também usa TestClient,
    # rode separadamente (pytest backend/tests/test_iter222_*.py) para
    # evitar conflito do motor client global.
    _reset_motor_client()
    with TestClient(app) as c:
        yield c


def _reset_motor_client():
    """Reinicializa o `mongo_client` global em database.py para o loop
    atual. Necessário quando rodamos múltiplos módulos de teste no
    mesmo pytest-run e cada um abre/encerra um lifespan distinto."""
    try:
        import database as _dbmod
        from motor.motor_asyncio import AsyncIOMotorClient
        # NÃO chamamos .close() — pode falhar com loop fechado.
        # Apenas substituímos a referência; o old client é GC-ado.
        _dbmod.mongo_client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        _dbmod.db = _dbmod.mongo_client[os.environ["DB_NAME"]]
    except Exception:
        pass


@pytest.fixture(scope="module")
def sync_db():
    """PyMongo síncrono — evita conflito de loop em testes."""
    cli = MongoClient(os.environ["MONGO_URL"])
    name = os.environ.get("DB_NAME") or "test_db"
    return cli[name]


@pytest.fixture(scope="module")
def users(sync_db):
    from auth import create_access_token, hash_password
    suffix = uuid.uuid4().hex[:6]
    now_iso = datetime.now(timezone.utc).isoformat()

    def _make(role, suff_role, is_super=False):
        uid = f"tst-{suff_role}-{suffix}"
        return {
            "id": uid,
            "email": f"{uid}@test.local",
            "name": f"Test {role}",
            "role": role,
            "active": True,
            "company_id": "tst-audit-co",
            "is_super_admin": is_super,
            "password_hash": hash_password("test123"),
            "created_at": now_iso,
            "updated_at": now_iso,
        }

    admin = _make("administrador", "adm", is_super=True)
    auditor = _make("auditor", "aud")
    colab = _make("colaborador", "col")
    ids = [admin["id"], auditor["id"], colab["id"]]

    sync_db.users.delete_many({"id": {"$in": ids}})
    sync_db.users.insert_many([admin, auditor, colab])

    tokens = {
        "admin": create_access_token(
            user_id=admin["id"], email=admin["email"],
            role=admin["role"], company_id=admin["company_id"],
            is_super_admin=True),
        "auditor": create_access_token(
            user_id=auditor["id"], email=auditor["email"],
            role=auditor["role"], company_id=auditor["company_id"]),
        "colab": create_access_token(
            user_id=colab["id"], email=colab["email"],
            role=colab["role"], company_id=colab["company_id"]),
    }
    yield {"users": {"admin": admin, "auditor": auditor,
                       "colab": colab}, "tokens": tokens}
    sync_db.users.delete_many({"id": {"$in": ids}})


def _h(tokens, kind):
    return {"Authorization": f"Bearer {tokens[kind]}"}


# ─────────────────── 1. Admin acessa ───────────────────
def test_admin_can_access_audit_log(client, users):
    r = client.get("/api/audit-log?limit=5",
                       headers=_h(users["tokens"], "admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and "total" in body


# ─────────────────── 2. Auditor acessa ───────────────────
def test_auditor_can_access_audit_log(client, users):
    r = client.get("/api/audit-log?limit=5",
                       headers=_h(users["tokens"], "auditor"))
    assert r.status_code == 200, r.text


# ─────────────────── 3. Colaborador bloqueado ───────────────────
def test_colaborador_blocked_from_audit_log(client, users):
    r = client.get("/api/audit-log?limit=5",
                       headers=_h(users["tokens"], "colab"))
    assert r.status_code == 403, r.text


# ─────────────────── 4. Stats funciona ───────────────────
def test_admin_can_access_audit_stats(client, users):
    r = client.get("/api/audit-log/stats",
                       headers=_h(users["tokens"], "admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "cards" in body and "top_users" in body
    for k in ("total", "deletes", "exports", "rbac_blocked",
                "impersonate"):
        assert k in body["cards"]


# ─────────────────── 5. DELETE gera audit_log ───────────────────
def test_delete_generates_audit_log_entry(client, users):
    h = _h(users["tokens"], "admin")
    rid = f"non-existent-{uuid.uuid4().hex[:6]}"
    client.delete(f"/api/pracas/{rid}", headers=h)

    r = client.get(
        f"/api/audit-log?endpoint=/api/pracas/{rid}&limit=5",
        headers=h)
    assert r.status_code == 200
    items = r.json().get("items", [])
    assert any(it.get("category") == "destructive"
                 for it in items), (
        f"Esperava audit destructive p/ DELETE /api/pracas/{rid}, "
        f"items={items}")


# ─────────────────── 6. RBAC bloqueado registra ───────────────────
def test_rbac_block_creates_audit_entry(client, users):
    uid_email = users["users"]["colab"]["email"]
    r = client.get("/api/admin/health",
                       headers=_h(users["tokens"], "colab"))
    assert r.status_code in (403, 404), r.text

    r = client.get(
        f"/api/audit-log?category=rbac_blocked"
        f"&user_email={uid_email}",
        headers=_h(users["tokens"], "admin"))
    assert r.status_code == 200
    items = r.json().get("items", [])
    # Como o email pode estar mascarado, basta filtrar por role + 403
    matched = [it for it in items
                 if it.get("user_role") == "colaborador"
                 and it.get("status") == 403]
    assert matched, (
        f"Esperava entrada rbac_blocked p/ {uid_email}, "
        f"received={r.json()}")
    assert matched[0]["status"] == 403


# ─────────────────── 7. Security insight ───────────────────
def test_security_insight_endpoint(client, users):
    r = client.get("/api/presidente-ia/security/insight",
                       headers=_h(users["tokens"], "admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "status" in body and "counts" in body
    for k in ("total", "deletes", "exports", "rbac_blocked"):
        assert k in body["counts"]


# ─────────────────── 8. Security alerts ───────────────────
def test_security_alerts_returns_structure(client, users):
    r = client.get("/api/presidente-ia/security/alerts",
                       headers=_h(users["tokens"], "admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "count" in body and "alerts" in body
    assert isinstance(body["alerts"], list)


# ─────────────────── 9. Mass export detector ───────────────────
def test_mass_export_alert_generated(client, users, sync_db):
    """Insere 6 events de export via pymongo, depois chama o endpoint
    /api/presidente-ia/security/alerts (que roda detect_mass_export
    no MESMO loop do TestClient — evita conflito motor)."""
    uid = f"tst-mass-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    docs = [{
        "id": f"aud-mass-{uid}-{i}",
        "user_id": uid, "user_email": f"{uid}@test.local",
        "user_role": "gestor", "company_id": "tst-audit-co",
        "category": "export", "criticality": "media",
        "method": "GET", "target": f"/api/pdf-reports/{i}",
        "action": f"GET /api/pdf-reports/{i}",
        "status": 200, "created_at": now,
        "data": {},
    } for i in range(6)]
    sync_db.audit_log.insert_many(docs)
    try:
        r = client.get("/api/presidente-ia/security/alerts",
                          headers=_h(users["tokens"], "admin"))
        assert r.status_code == 200, r.text
        alerts = r.json().get("alerts", [])
    finally:
        sync_db.audit_log.delete_many({"user_id": uid})

    matched = [a for a in alerts if a.get("scope") == uid]
    assert matched, (
        f"Esperava alerta mass_export p/ {uid}. "
        f"Recebido count={len(alerts)} alerts={alerts}")
    assert matched[0]["type"] == "mass_export"


# ─────────────────── 10. Mascaramento ───────────────────
def test_email_masked_in_listing(client, users, sync_db):
    eid = f"aud-mask-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": eid,
        "user_id": "tst-mask", "user_email": "supersecret@empresa.com",
        "user_role": "gestor", "company_id": "tst-audit-co",
        "category": "destructive", "criticality": "alta",
        "method": "DELETE", "target": "/api/x-mask-test",
        "action": "DELETE /api/x-mask-test", "status": 200,
        "ip": "192.168.1.50",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data": {},
    }
    sync_db.audit_log.insert_one(doc)
    try:
        h = _h(users["tokens"], "auditor")
        r = client.get(
            "/api/audit-log?endpoint=/api/x-mask-test&limit=5",
            headers=h)
        assert r.status_code == 200
        items = r.json().get("items", [])
        ours = [it for it in items if it.get("id") == eid]
        assert ours, f"Não achou item inserido: {items}"
        assert "*" in ours[0]["user_email"]
        assert ours[0]["ip"] == "192.168.*.*"
        # Detalhe: sem mascaramento
        r2 = client.get(f"/api/audit-log/{eid}", headers=h)
        assert r2.status_code == 200
        d = r2.json()
        assert d["user_email"] == "supersecret@empresa.com"
        assert d["ip"] == "192.168.1.50"
    finally:
        sync_db.audit_log.delete_one({"id": eid})

