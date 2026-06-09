"""
test_iter226_warroom.py — Sprint 7 / Sistema Nervoso Foundation.
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
def users(sync_db):
    from auth import create_access_token, hash_password
    suffix = uuid.uuid4().hex[:6]
    now = datetime.now(timezone.utc).isoformat()
    admin = {
        "id": f"tst-adm-{suffix}",
        "email": f"tst-adm-{suffix}@test.local",
        "name": "T", "role": "administrador", "active": True,
        "company_id": "tst-wr", "is_super_admin": True,
        "password_hash": hash_password("x"),
        "created_at": now, "updated_at": now,
    }
    colab = {**admin,
        "id": f"tst-col-{suffix}",
        "email": f"tst-col-{suffix}@test.local",
        "role": "colaborador", "is_super_admin": False}
    ids = [admin["id"], colab["id"]]
    sync_db.users.delete_many({"id": {"$in": ids}})
    sync_db.users.insert_many([admin, colab])
    tokens = {
        "admin": create_access_token(
            user_id=admin["id"], email=admin["email"],
            role="administrador", company_id=admin["company_id"],
            is_super_admin=True),
        "colab": create_access_token(
            user_id=colab["id"], email=colab["email"],
            role="colaborador", company_id=colab["company_id"]),
    }
    yield {"tokens": tokens}
    sync_db.users.delete_many({"id": {"$in": ids}})


def _h(tokens, kind):
    return {"Authorization": f"Bearer {tokens[kind]}"}


def test_warroom_admin(client, users):
    r = client.get("/api/presidente-ia/warroom",
                       headers=_h(users["tokens"], "admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "executive" in body
    assert "data_quality" in body
    assert "critical_alerts" in body
    assert "overall_score" in body["executive"]
    assert "scores" in body["executive"]
    for k in ("dados", "operacional", "comercial",
                "financeiro", "seguranca"):
        assert k in body["executive"]["scores"]


def test_warroom_blocked_colab(client, users):
    r = client.get("/api/presidente-ia/warroom",
                       headers=_h(users["tokens"], "colab"))
    assert r.status_code == 403


def test_data_quality_endpoint(client, users):
    r = client.get("/api/presidente-ia/data-quality",
                       headers=_h(users["tokens"], "admin"))
    assert r.status_code == 200
    b = r.json()
    assert "score" in b and "issues" in b and "status" in b
    assert isinstance(b["issues"], list)
    assert 0 <= b["score"] <= 100


def test_executive_health_endpoint(client, users):
    r = client.get("/api/presidente-ia/executive-health",
                       headers=_h(users["tokens"], "admin"))
    assert r.status_code == 200
    b = r.json()
    assert "overall_score" in b and "scores" in b


def test_scheduler_run_now(client, users):
    r = client.post("/api/presidente-ia/scheduler/run-now",
                        headers=_h(users["tokens"], "admin"))
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_emit_event_writes_to_bus(client, users, sync_db):
    """Emite evento e confirma gravação em motor_ia_events."""
    import asyncio
    from services.event_bus import emit_event, EventType
    eid = asyncio.run(emit_event(
        EventType.CLIENT_OFFLINE,
        company_id="tst-wr", source="test",
        severity="alta", payload={"client_id": "x"}))
    assert eid["id"].startswith("evt-")
    # confirma via pymongo
    found = sync_db.motor_ia_events.find_one({"id": eid["id"]})
    assert found is not None
    assert found["event_type"] == "CLIENT_OFFLINE"
    assert found["severity"] == "alta"
    sync_db.motor_ia_events.delete_one({"id": eid["id"]})
