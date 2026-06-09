"""
test_iter225_backend_health.py — Sprint 6 / SRE health panel.
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
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def users(sync_db):
    from auth import create_access_token, hash_password
    suffix = uuid.uuid4().hex[:6]
    now_iso = datetime.now(timezone.utc).isoformat()
    admin = {
        "id": f"tst-adm-{suffix}",
        "email": f"tst-adm-{suffix}@test.local",
        "name": "T", "role": "administrador", "active": True,
        "company_id": "tst-h-co", "is_super_admin": True,
        "password_hash": hash_password("x"),
        "created_at": now_iso, "updated_at": now_iso,
    }
    auditor = {**admin,
        "id": f"tst-aud-{suffix}",
        "email": f"tst-aud-{suffix}@test.local",
        "role": "auditor", "is_super_admin": False}
    colab = {**admin,
        "id": f"tst-col-{suffix}",
        "email": f"tst-col-{suffix}@test.local",
        "role": "colaborador", "is_super_admin": False}
    ids = [admin["id"], auditor["id"], colab["id"]]
    sync_db.users.delete_many({"id": {"$in": ids}})
    sync_db.users.insert_many([admin, auditor, colab])
    tokens = {
        "admin": create_access_token(
            user_id=admin["id"], email=admin["email"],
            role="administrador", company_id=admin["company_id"],
            is_super_admin=True),
        "auditor": create_access_token(
            user_id=auditor["id"], email=auditor["email"],
            role="auditor", company_id=auditor["company_id"]),
        "colab": create_access_token(
            user_id=colab["id"], email=colab["email"],
            role="colaborador", company_id=colab["company_id"]),
    }
    yield {"tokens": tokens}
    sync_db.users.delete_many({"id": {"$in": ids}})


def _h(tokens, kind):
    return {"Authorization": f"Bearer {tokens[kind]}"}


def test_deep_health_admin(client, users):
    # gera alguma latência primeiro
    client.get("/api/health-panel/deep",
                   headers=_h(users["tokens"], "admin"))
    r = client.get("/api/health-panel/deep",
                       headers=_h(users["tokens"], "admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "status" in body
    assert "latency" in body
    assert "services" in body
    assert isinstance(body["services"], list)
    assert "top_slowest" in body["latency"]


def test_deep_health_auditor(client, users):
    r = client.get("/api/health-panel/deep",
                       headers=_h(users["tokens"], "auditor"))
    assert r.status_code == 200


def test_deep_health_blocked_colab(client, users):
    r = client.get("/api/health-panel/deep",
                       headers=_h(users["tokens"], "colab"))
    assert r.status_code == 403


def test_services_endpoint(client, users):
    r = client.get("/api/health-panel/services",
                       headers=_h(users["tokens"], "admin"))
    assert r.status_code == 200
    body = r.json()
    names = [s["name"] for s in body["services"]]
    assert "MongoDB" in names
    # MongoDB precisa estar OK no ambiente de teste
    mongo = [s for s in body["services"] if s["name"] == "MongoDB"][0]
    assert mongo["ok"] is True


def test_latency_records_via_middleware(client, users):
    # faz algumas chamadas para popular o ring
    for _ in range(3):
        client.get("/api/audit-log?limit=5",
                       headers=_h(users["tokens"], "admin"))
    r = client.get("/api/health-panel/latency?window_seconds=3600",
                       headers=_h(users["tokens"], "admin"))
    assert r.status_code == 200
    body = r.json()
    assert body["total_requests"] >= 3
    # confirma que pelo menos uma rota foi registrada
    assert len(body.get("top_slowest", [])) >= 1


def test_index_hints_endpoint(client, users):
    r = client.get("/api/health-panel/indexes",
                       headers=_h(users["tokens"], "admin"))
    assert r.status_code == 200
    body = r.json()
    assert "hints" in body
    assert isinstance(body["hints"], list)
