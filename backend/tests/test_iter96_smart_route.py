"""Iter 96 — Smart Route (otimização TSP greedy)."""
import os
import uuid
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")

BASE = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://dual-combine-3.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE}/api"


@pytest_asyncio.fixture
async def db():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    yield cli[os.environ["DB_NAME"]]
    cli.close()


@pytest.mark.asyncio
async def test_1_few_candidates_returns_not_ok():
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            f"{API}/lousa/public/optimize-route",
            json={"collaborator_id": "col-no-exists",
                  "current_lat": -22.9, "current_lng": -43.2},
        )
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is False
    assert "reorden" in j["reason"].lower()


@pytest.mark.asyncio
async def test_2_nearest_neighbor_order(db):
    """Cria 3 tickets com lat/lng conhecidos, valida ordem otimizada."""
    cid = "col-30aafc3c"
    today = (datetime.now(timezone.utc).replace(hour=12)).isoformat()
    points = [
        # Próximo do origem (-22.9, -43.2)
        {"name": "Perto", "lat": -22.905, "lng": -43.205,
          "expected_order": 0},
        # Médio
        {"name": "Médio", "lat": -22.95, "lng": -43.25,
          "expected_order": 1},
        # Longe
        {"name": "Longe", "lat": -23.0, "lng": -43.3,
          "expected_order": 2},
    ]
    created_ids = []
    docs = []
    for p in points:
        tid = f"tkt-iter96-{uuid.uuid4().hex[:8]}"
        created_ids.append(tid)
        docs.append({
            "id": tid, "company_id": "co-demo",
            "type": "reparo", "priority": "normal",
            "status": "pendente",
            "assigned_collaborator_id": cid,
            "scheduled_time": None,
            "opened_at": None,
            "created_at": today,
            "position": 1700000000 + len(docs),
            "client_snapshot": {
                "name": p["name"], "address": "Rua X",
                "neighborhood": "Centro",
                "latitude": p["lat"], "longitude": p["lng"],
            },
        })
    await db.tickets.insert_many(docs)
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(
                f"{API}/lousa/public/optimize-route",
                json={"collaborator_id": cid,
                      "current_lat": -22.9, "current_lng": -43.2,
                      "apply": False},
            )
        assert r.status_code == 200
        j = r.json()
        assert j["ok"] is True
        # Filtra só nossos tickets
        ids_in_order = [c["id"] for c in j["optimized"]
                          if c["id"] in created_ids]
        # Perto deve vir primeiro
        idx_perto = ids_in_order.index(created_ids[0])
        idx_longe = ids_in_order.index(created_ids[2])
        assert idx_perto < idx_longe
        assert j["total_km"] > 0
        assert j["stops"] >= 3
        # NÃO foi aplicado
        assert j["applied"] is False
    finally:
        await db.tickets.delete_many({"id": {"$regex": "^tkt-iter96-"}})


@pytest.mark.asyncio
async def test_3_apply_persists_new_order(db):
    cid = "col-30aafc3c"
    today = datetime.now(timezone.utc).isoformat()
    a = f"tkt-iter96-{uuid.uuid4().hex[:8]}"
    b = f"tkt-iter96-{uuid.uuid4().hex[:8]}"
    base_position = 1700000000
    docs = [
        {"id": a, "company_id": "co-demo", "type": "reparo",
          "priority": "normal", "status": "pendente",
          "assigned_collaborator_id": cid, "created_at": today,
          "position": base_position + 1,
          "client_snapshot": {"name": "Longe", "address": "X",
                                "latitude": -23.0, "longitude": -43.3,
                                "neighborhood": ""}},
        {"id": b, "company_id": "co-demo", "type": "reparo",
          "priority": "normal", "status": "pendente",
          "assigned_collaborator_id": cid, "created_at": today,
          "position": base_position,
          "client_snapshot": {"name": "Perto", "address": "Y",
                                "latitude": -22.905, "longitude": -43.205,
                                "neighborhood": ""}},
    ]
    await db.tickets.insert_many(docs)
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(
                f"{API}/lousa/public/optimize-route",
                json={"collaborator_id": cid,
                      "current_lat": -22.9, "current_lng": -43.2,
                      "apply": True},
            )
        assert r.status_code == 200
        j = r.json()
        assert j["applied"] is True
        # Re-check positions in DB — "Perto" deve ter position menor
        a_doc = await db.tickets.find_one({"id": a}, {"_id": 0, "position": 1})
        b_doc = await db.tickets.find_one({"id": b}, {"_id": 0, "position": 1})
        assert b_doc["position"] < a_doc["position"], "Perto deve vir antes"
    finally:
        await db.tickets.delete_many({"id": {"$regex": "^tkt-iter96-"}})
