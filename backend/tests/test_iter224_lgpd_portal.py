"""
test_iter224_lgpd_portal.py — Sprint 5 / LGPD Portal (PDF).
"""
from __future__ import annotations

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


def _reset_motor_client():
    try:
        import database as _dbmod
        from motor.motor_asyncio import AsyncIOMotorClient
        _dbmod.mongo_client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        _dbmod.db = _dbmod.mongo_client[os.environ["DB_NAME"]]
    except Exception:
        pass


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("ALLOW_MOCK_MODULES", "true")
    from server import app as fastapi_app
    return fastapi_app


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
    admin = {
        "id": f"tst-adm-{suffix}",
        "email": f"tst-adm-{suffix}@test.local",
        "name": "T", "role": "administrador", "active": True,
        "company_id": "tst-pdf-co", "is_super_admin": True,
        "password_hash": hash_password("x"),
        "created_at": now_iso, "updated_at": now_iso,
    }
    auditor = {**admin,
        "id": f"tst-aud-{suffix}",
        "email": f"tst-aud-{suffix}@test.local",
        "role": "auditor", "is_super_admin": False,
    }
    ids = [admin["id"], auditor["id"]]
    sync_db.users.delete_many({"id": {"$in": ids}})
    sync_db.users.insert_many([admin, auditor])
    tokens = {
        "admin": create_access_token(
            user_id=admin["id"], email=admin["email"],
            role="administrador", company_id=admin["company_id"],
            is_super_admin=True),
        "auditor": create_access_token(
            user_id=auditor["id"], email=auditor["email"],
            role="auditor", company_id=auditor["company_id"]),
    }
    yield {"users": {"admin": admin, "auditor": auditor},
              "tokens": tokens}
    sync_db.users.delete_many({"id": {"$in": ids}})


def _h(tokens, kind):
    return {"Authorization": f"Bearer {tokens[kind]}"}


# ─────────────────── 1. PDF download ───────────────────
def test_lgpd_pdf_download_admin(client, users, sync_db):
    """Cria 3 eventos com subject_id e baixa o dossiê."""
    subj = f"sub-pdf-{uuid.uuid4().hex[:8]}"
    docs = [{
        "id": f"aud-pdf-{subj}-{i}",
        "user_id": "actor", "user_email": "actor@test.local",
        "user_role": "atendimento", "company_id": "tst-pdf-co",
        "category": "config_change", "criticality": "alta",
        "method": "PUT", "target": f"/api/subscribers/{subj}",
        "endpoint": f"/api/subscribers/{subj}",
        "action": f"PUT /api/subscribers/{subj}",
        "status": 200,
        "data": {"subject_id": subj},
        "created_at": datetime.now(timezone.utc).isoformat(),
    } for i in range(3)]
    sync_db.audit_log.insert_many(docs)
    try:
        r = client.get(
            f"/api/audit-log/lgpd/subject-report.pdf?subject_id={subj}",
            headers=_h(users["tokens"], "admin"))
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert "X-LGPD-Dossie-Id" in r.headers
        assert "X-LGPD-Checksum" in r.headers
        assert len(r.headers["X-LGPD-Checksum"]) == 64
        # PDF tem magic bytes %PDF-
        assert r.content[:5] == b"%PDF-"
        assert len(r.content) > 1500
    finally:
        sync_db.audit_log.delete_many(
            {"id": {"$regex": f"^aud-pdf-{subj}"}})


# ─────────────────── 2. PDF para auditor (também ok) ───────────
def test_lgpd_pdf_download_auditor(client, users):
    r = client.get(
        "/api/audit-log/lgpd/subject-report.pdf?subject_id=any",
        headers=_h(users["tokens"], "auditor"))
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"


# ─────────────────── 3. Colab bloqueado ───────────────────
def test_lgpd_pdf_blocked_for_colab(client, sync_db):
    from auth import create_access_token, hash_password
    uid = f"tst-col-{uuid.uuid4().hex[:6]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    sync_db.users.insert_one({
        "id": uid, "email": f"{uid}@test.local", "name": "T",
        "role": "colaborador", "active": True,
        "company_id": "tst-pdf-co", "is_super_admin": False,
        "password_hash": hash_password("x"),
        "created_at": now_iso, "updated_at": now_iso,
    })
    tok = create_access_token(
        user_id=uid, email=f"{uid}@test.local",
        role="colaborador", company_id="tst-pdf-co")
    try:
        r = client.get(
            "/api/audit-log/lgpd/subject-report.pdf?subject_id=x",
            headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 403
    finally:
        sync_db.users.delete_one({"id": uid})


# ─────────────────── 4. PDF audita sua própria emissão ─────────
def test_pdf_generation_logs_to_audit(client, users, sync_db):
    subj = f"sub-audita-{uuid.uuid4().hex[:6]}"
    r = client.get(
        f"/api/audit-log/lgpd/subject-report.pdf?subject_id={subj}",
        headers=_h(users["tokens"], "admin"))
    assert r.status_code == 200
    dossie_id = r.headers.get("X-LGPD-Dossie-Id")
    # verifica que existe entrada no audit_log
    entry = sync_db.audit_log.find_one(
        {"action": {"$regex": dossie_id}})
    assert entry is not None
    assert entry["category"] == "export"
    assert entry["data"]["dossie_id"] == dossie_id
