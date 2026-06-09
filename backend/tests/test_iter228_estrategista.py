"""
test_iter228_estrategista.py — Sprint 9 / Estrategista IA.
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
    os.environ.setdefault("DISABLE_EXEC_SCHEDULER", "1")
    from server import app as fa
    return fa


@pytest.fixture(scope="module")
def client(app):
    _reset_motor_client()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def sync_db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_token(sync_db):
    from auth import create_access_token, hash_password
    suffix = uuid.uuid4().hex[:6]
    now = datetime.now(timezone.utc).isoformat()
    user = {
        "id": f"tst-est-{suffix}",
        "email": f"tst-est-{suffix}@test.local",
        "name": "T", "role": "administrador", "active": True,
        "company_id": "tst-est", "is_super_admin": True,
        "password_hash": hash_password("x"),
        "created_at": now, "updated_at": now,
    }
    sync_db.users.delete_one({"id": user["id"]})
    sync_db.users.insert_one(user)
    tok = create_access_token(
        user_id=user["id"], email=user["email"],
        role="administrador", company_id=user["company_id"],
        is_super_admin=True)
    yield tok
    sync_db.users.delete_one({"id": user["id"]})


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def test_strategist_daily_report(client, admin_token):
    r = client.get(
        "/api/presidente-ia/strategist/report?period=daily&force=true",
        headers=_h(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["period"] == "daily"
    assert "text" in body and len(body["text"]) > 50
    assert "context" in body
    assert "metrics" in body["context"]
    # tem ID e foi gravado
    assert body["id"].startswith("rpt-")


def test_strategist_weekly_cached(client, admin_token):
    """Segunda chamada deve vir do cache."""
    r1 = client.get(
        "/api/presidente-ia/strategist/report?period=weekly&force=true",
        headers=_h(admin_token))
    assert r1.status_code == 200
    r2 = client.get(
        "/api/presidente-ia/strategist/report?period=weekly",
        headers=_h(admin_token))
    assert r2.status_code == 200
    assert r2.json().get("cached") is True


def test_strategist_invalid_period(client, admin_token):
    r = client.get(
        "/api/presidente-ia/strategist/report?period=annual",
        headers=_h(admin_token))
    assert r.status_code == 400


def test_strategist_history(client, admin_token):
    r = client.get(
        "/api/presidente-ia/strategist/reports/history?limit=5",
        headers=_h(admin_token))
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert isinstance(body["items"], list)


def test_strategist_blocked_for_colab(client, sync_db):
    from auth import create_access_token, hash_password
    uid = f"tst-col-{uuid.uuid4().hex[:6]}"
    sync_db.users.insert_one({
        "id": uid, "email": f"{uid}@t.l", "name": "x",
        "role": "colaborador", "active": True,
        "company_id": "tst-est", "is_super_admin": False,
        "password_hash": hash_password("x"),
        "created_at": "2026-01-01", "updated_at": "2026-01-01",
    })
    tok = create_access_token(
        user_id=uid, email=f"{uid}@t.l", role="colaborador",
        company_id="tst-est")
    try:
        r = client.get(
            "/api/presidente-ia/strategist/report",
            headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 403
    finally:
        sync_db.users.delete_one({"id": uid})
