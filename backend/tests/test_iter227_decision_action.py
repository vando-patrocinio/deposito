"""
test_iter227_decision_action.py — Sprint 8 / Decision + Action Engine.
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
        "company_id": "tst-d8", "is_super_admin": True,
        "password_hash": hash_password("x"),
        "created_at": now, "updated_at": now,
    }
    sync_db.users.delete_one({"id": admin["id"]})
    sync_db.users.insert_one(admin)
    tok = create_access_token(
        user_id=admin["id"], email=admin["email"],
        role="administrador", company_id=admin["company_id"],
        is_super_admin=True)
    yield {"token": tok, "user": admin}
    sync_db.users.delete_one({"id": admin["id"]})


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _seed_events(sync_db, suffix, *events):
    docs = []
    for ev in events:
        docs.append({
            "id": f"evt-test-{suffix}-{uuid.uuid4().hex[:6]}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "company_id": "tst-d8",
            "user_id": ev.get("user_id"),
            "source": "test",
            "event_type": ev["event_type"],
            "severity": ev.get("severity", "media"),
            "payload": ev.get("payload", {}),
            "consumed": False,
        })
    sync_db.motor_ia_events.insert_many(docs)
    return [d["id"] for d in docs]


def test_rule_collective_outage(client, users, sync_db):
    suffix = uuid.uuid4().hex[:6]
    # 6 CLIENT_OFFLINE no mesmo CTO
    cto = f"CTO-test-{suffix}"
    ids = _seed_events(sync_db, suffix, *[
        {"event_type": "CLIENT_OFFLINE",
         "payload": {"cto_id": cto, "client_id": f"c{i}"}}
        for i in range(6)
    ])
    try:
        r = client.post("/api/presidente-ia/decision-cycle/run",
                            headers=_h(users["token"]))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["decision_cycle"]["events_processed"] >= 6
        assert body["decision_cycle"]["decisions_created"] >= 1
        # verifica decisão
        dec = sync_db.motor_ia_decisions.find_one(
            {"action_type": "open_incident",
             "action_payload.cto_id": cto})
        assert dec is not None
        assert dec["executed"] is True
        # verifica incidente
        inc = sync_db.incidents.find_one(
            {"cto_id": cto, "linked_decision_id": dec["id"]})
        assert inc is not None
        assert inc["affected_count"] == 6
    finally:
        sync_db.motor_ia_events.delete_many({"id": {"$in": ids}})
        sync_db.motor_ia_decisions.delete_many(
            {"action_payload.cto_id": cto})
        sync_db.incidents.delete_many({"cto_id": cto})


def test_rule_churn_risk(client, users, sync_db):
    suffix = uuid.uuid4().hex[:6]
    sub = f"sub-{suffix}"
    ids = _seed_events(sync_db, suffix, {
        "event_type": "CLIENT_CHURN_RISK",
        "payload": {"subscriber_id": sub, "reason": "2 tickets abertos"},
    })
    try:
        r = client.post("/api/presidente-ia/decision-cycle/run",
                            headers=_h(users["token"]))
        assert r.status_code == 200
        dec = sync_db.motor_ia_decisions.find_one(
            {"action_type": "create_retention_opportunity",
             "action_payload.subscriber_id": sub})
        assert dec is not None
        # oportunidade criada
        opp = sync_db.loyalty_opportunities.find_one(
            {"subscriber_id": sub,
             "linked_decision_id": dec["id"]})
        assert opp is not None
        assert opp["status"] == "pending"
    finally:
        sync_db.motor_ia_events.delete_many({"id": {"$in": ids}})
        sync_db.motor_ia_decisions.delete_many(
            {"action_payload.subscriber_id": sub})
        sync_db.loyalty_opportunities.delete_many(
            {"subscriber_id": sub})


def test_rule_rbac_abuse_notifies(client, users, sync_db):
    suffix = uuid.uuid4().hex[:6]
    uid = f"user-{suffix}"
    ids = _seed_events(sync_db, suffix, *[
        {"event_type": "RBAC_DENIED",
         "user_id": uid,
         "payload": {"path": "/api/admin"}}
        for _ in range(3)
    ])
    try:
        r = client.post("/api/presidente-ia/decision-cycle/run",
                            headers=_h(users["token"]))
        assert r.status_code == 200
        dec = sync_db.motor_ia_decisions.find_one(
            {"action_type": "notify_manager",
             "action_payload.user_id": uid})
        assert dec is not None
        notif = sync_db.presidente_ia_notifications.find_one(
            {"linked_decision_id": dec["id"]})
        assert notif is not None
        # DRY_RUN ativo por default
        assert notif["dry_run"] is True
    finally:
        sync_db.motor_ia_events.delete_many({"id": {"$in": ids}})
        sync_db.motor_ia_decisions.delete_many(
            {"action_payload.user_id": uid})
        sync_db.presidente_ia_notifications.delete_many(
            {"linked_decision_id": {
                "$regex": f"^dec-"}})


def test_outcomes_recorded(client, users, sync_db):
    """Toda execução grava motor_ia_outcomes (feedback loop)."""
    suffix = uuid.uuid4().hex[:6]
    sub = f"sub-fin-{suffix}"
    ids = _seed_events(sync_db, suffix, {
        "event_type": "PAYMENT_OVERDUE",
        "payload": {"subscriber_id": sub},
    })
    try:
        r = client.post("/api/presidente-ia/decision-cycle/run",
                            headers=_h(users["token"]))
        assert r.status_code == 200
        dec = sync_db.motor_ia_decisions.find_one(
            {"action_type": "escalate_dunning",
             "action_payload.subscriber_id": sub})
        assert dec is not None
        outcome = sync_db.motor_ia_outcomes.find_one(
            {"decision_id": dec["id"]})
        assert outcome is not None
        assert outcome["ok"] is True
    finally:
        sync_db.motor_ia_events.delete_many({"id": {"$in": ids}})


def test_decisions_endpoint(client, users):
    r = client.get("/api/presidente-ia/decisions?limit=10",
                       headers=_h(users["token"]))
    assert r.status_code == 200
    b = r.json()
    assert "items" in b and ("total" in b or "count" in b)


def test_actions_endpoint(client, users):
    r = client.get("/api/presidente-ia/actions?limit=10",
                       headers=_h(users["token"]))
    assert r.status_code == 200
    b = r.json()
    assert "items" in b and ("total" in b or "count" in b)
