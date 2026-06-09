"""
test_iter223_lgpd_chain.py — Sprint 4 / LGPD hardening.

Cobre:
  1. insert_audit_event grava prev_hash + hash
  2. Cadeia consecutiva é consistente (verify_chain ok)
  3. Adulteração de evento é detectada (status=tampering_detected)
  4. subject_report retorna eventos do titular
  5. GET /api/audit-log/lgpd/subject-report (admin/auditor)
  6. GET /api/audit-log/lgpd/verify-chain
  7. GET /api/audit-log/retention-policy (admin/auditor)
  8. PUT /api/audit-log/retention-policy (admin)
  9. PUT /api/audit-log/retention-policy bloqueado p/ auditor
 10. POST /api/audit-log/retention-policy/apply (admin)

Setup: usuários reais em DB via pymongo síncrono.

Roda:
    cd /app && pytest backend/tests/test_iter223_lgpd_chain.py -v
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


def _reset_motor_client():
    try:
        import database as _dbmod
        from motor.motor_asyncio import AsyncIOMotorClient
        _dbmod.mongo_client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        _dbmod.db = _dbmod.mongo_client[os.environ["DB_NAME"]]
    except Exception:
        pass


@pytest.fixture(scope="module")
def client(app):
    _reset_motor_client()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def sync_db():
    cli = MongoClient(os.environ["MONGO_URL"])
    return cli[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def users(sync_db):
    from auth import create_access_token, hash_password
    suffix = uuid.uuid4().hex[:6]
    now_iso = datetime.now(timezone.utc).isoformat()

    def _make(role, suff_role, is_super=False):
        uid = f"tst-{suff_role}-{suffix}"
        return {
            "id": uid, "email": f"{uid}@test.local",
            "name": f"Test {role}", "role": role, "active": True,
            "company_id": "tst-lgpd-co", "is_super_admin": is_super,
            "password_hash": hash_password("test123"),
            "created_at": now_iso, "updated_at": now_iso,
        }

    admin = _make("administrador", "adm", is_super=True)
    auditor = _make("auditor", "aud")
    ids = [admin["id"], auditor["id"]]
    sync_db.users.delete_many({"id": {"$in": ids}})
    sync_db.users.insert_many([admin, auditor])

    tokens = {
        "admin": create_access_token(
            user_id=admin["id"], email=admin["email"],
            role=admin["role"], company_id=admin["company_id"],
            is_super_admin=True),
        "auditor": create_access_token(
            user_id=auditor["id"], email=auditor["email"],
            role=auditor["role"], company_id=auditor["company_id"]),
    }
    yield {"users": {"admin": admin, "auditor": auditor},
              "tokens": tokens}
    sync_db.users.delete_many({"id": {"$in": ids}})


def _h(tokens, kind):
    return {"Authorization": f"Bearer {tokens[kind]}"}


# ─────────────────── 1. Hash determinístico ───────────────────
def test_compute_hash_is_deterministic():
    from services.lgpd_chain import compute_hash
    doc = {
        "id": "aud-x", "category": "export", "action": "GET /api/x",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    h1 = compute_hash(doc, "abc")
    h2 = compute_hash(doc, "abc")
    h3 = compute_hash(doc, "def")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64  # sha256 hex


# ─────────────────── 2. Verify chain detecta adulteração ───────
def test_verify_chain_detects_tampering(client, users, sync_db):
    """Insere 3 eventos via API (DELETE → middleware grava com chain),
    depois adultera o registro do meio e roda verify-chain."""
    # gera 3 DELETEs auditáveis
    h = _h(users["tokens"], "admin")
    paths = [f"/api/pracas/lgpd-{uuid.uuid4().hex[:5]}" for _ in range(3)]
    for p in paths:
        client.delete(p, headers=h)
    # 1) confirma que existem na DB com hash
    chained = list(sync_db.audit_log.find(
        {"target": {"$in": paths}}).sort("created_at", 1))
    assert len(chained) >= 3
    for ev in chained:
        assert ev.get("hash"), f"Evento sem hash: {ev}"
        assert "prev_hash" in ev

    # 2) verifica que cadeia atual é íntegra
    r = client.get("/api/audit-log/lgpd/verify-chain?limit=10000",
                       headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok", body

    # 3) adultera (muda action) — sem refazer hash
    victim = chained[1]
    sync_db.audit_log.update_one(
        {"id": victim["id"]},
        {"$set": {"action": "ADULTERADO"}})
    # 4) verify deve detectar
    r = client.get("/api/audit-log/lgpd/verify-chain?limit=10000",
                       headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "tampering_detected"
    assert body["broken_count"] >= 1


# ─────────────────── 3. Subject report ───────────────────
def test_subject_report_endpoint(client, users, sync_db):
    """Cria 4 events com subject_id e verifica que o report acha."""
    subj = f"sub-{uuid.uuid4().hex[:8]}"
    docs = []
    for i in range(4):
        docs.append({
            "id": f"aud-sr-{subj}-{i}",
            "user_id": "outro-user",
            "user_email": "outro@test.local",
            "user_role": "atendimento",
            "company_id": "tst-lgpd-co",
            "category": "config_change",
            "criticality": "alta",
            "method": "PUT",
            "target": f"/api/subscribers/{subj}",
            "endpoint": f"/api/subscribers/{subj}",
            "action": f"PUT /api/subscribers/{subj}",
            "status": 200,
            "data": {"subject_id": subj},
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    sync_db.audit_log.insert_many(docs)
    try:
        r = client.get(
            f"/api/audit-log/lgpd/subject-report?subject_id={subj}",
            headers=_h(users["tokens"], "auditor"))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["subject_id"] == subj
        assert body["total_events"] >= 4
        cats = body["by_category"]
        assert cats.get("config_change", 0) >= 4
        assert "events" in body and isinstance(body["events"], list)
        assert "lgpd_basis" in body
    finally:
        sync_db.audit_log.delete_many({"id": {"$regex": f"^aud-sr-{subj}"}})


# ─────────────────── 4. Retention policy GET ───────────────────
def test_retention_policy_get(client, users):
    r = client.get("/api/audit-log/retention-policy",
                       headers=_h(users["tokens"], "auditor"))
    assert r.status_code == 200, r.text
    p = r.json()["policy"]
    assert "destructive" in p and "_default" in p


# ─────────────────── 5. Retention policy PUT admin ─────────────
def test_retention_policy_put_admin(client, users):
    new_policy = {"destructive": 365, "ai_rate_limited": 7}
    r = client.put("/api/audit-log/retention-policy",
                       json=new_policy,
                       headers=_h(users["tokens"], "admin"))
    assert r.status_code == 200, r.text
    p = r.json()["policy"]
    assert p["destructive"] == 365
    assert p["ai_rate_limited"] == 7


# ─────────────────── 6. PUT bloqueado p/ auditor ───────────────
def test_retention_policy_put_blocked_for_auditor(client, users):
    r = client.put("/api/audit-log/retention-policy",
                       json={"destructive": 100},
                       headers=_h(users["tokens"], "auditor"))
    assert r.status_code == 403, r.text


# ─────────────────── 7. Apply retention ───────────────────
def test_apply_retention_admin(client, users):
    r = client.post("/api/audit-log/retention-policy/apply",
                        headers=_h(users["tokens"], "admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "deleted" in body
    assert isinstance(body["deleted"], dict)


# ─────────────────── 8. RBAC: colab bloqueado em subject-report ─
def test_lgpd_subject_report_blocked_for_colab(client, users, sync_db):
    """Cria colaborador real e checa 403."""
    from auth import create_access_token, hash_password
    uid = f"tst-col-{uuid.uuid4().hex[:6]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    sync_db.users.insert_one({
        "id": uid, "email": f"{uid}@test.local", "name": "T",
        "role": "colaborador", "active": True,
        "company_id": "tst-lgpd-co", "is_super_admin": False,
        "password_hash": hash_password("x"),
        "created_at": now_iso, "updated_at": now_iso,
    })
    tok = create_access_token(
        user_id=uid, email=f"{uid}@test.local",
        role="colaborador", company_id="tst-lgpd-co")
    try:
        r = client.get(
            "/api/audit-log/lgpd/subject-report?subject_id=x",
            headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 403, r.text
    finally:
        sync_db.users.delete_one({"id": uid})
