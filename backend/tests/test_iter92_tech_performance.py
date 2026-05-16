"""Iter 92 — Card de performance do técnico (gamificação suave)."""
import os
import uuid
from datetime import datetime, timezone, timedelta

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
CID = "col-30aafc3c"  # DIOGO HENRIQUE


@pytest_asyncio.fixture
async def db():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    yield cli[os.environ["DB_NAME"]]
    cli.close()


@pytest.mark.asyncio
async def test_1_unknown_collaborator_returns_404():
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{API}/lousa/public/tech-performance/col-inexistente-xyz")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_2_known_collab_returns_shape():
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{API}/lousa/public/tech-performance/{CID}")
    assert r.status_code == 200
    j = r.json()
    for k in ("closed_today", "success_rate", "avg_minutes",
              "rank", "total_techs", "streak", "badge"):
        assert k in j, f"missing key {k}"
    assert isinstance(j["closed_today"], int)
    assert isinstance(j["success_rate"], int)
    assert isinstance(j["badge"], str)
    # 0 <= success_rate <= 100
    assert 0 <= j["success_rate"] <= 100


@pytest.mark.asyncio
async def test_3_badge_logic_with_seed(db):
    """Seed 4 fechadas hoje (sucesso) e valida badge motivacional."""
    cid_test = f"col-perftest-{uuid.uuid4().hex[:6]}"
    await db.collaborators.insert_one({
        "id": cid_test, "company_id": "co-demo",
        "name": "Perf Test Tech", "active": True,
    })
    now = datetime.now(timezone.utc)
    docs = []
    for i in range(4):
        opened = now - timedelta(hours=2, minutes=i * 5)
        closed = opened + timedelta(minutes=30)
        docs.append({
            "id": f"tkt-iter92-{uuid.uuid4().hex[:8]}",
            "company_id": "co-demo",
            "type": "suporte",
            "status": "finalizada",
            "outcome": "sucesso",
            "assigned_collaborator_id": cid_test,
            "opened_at": opened.isoformat(),
            "closed_at": closed.isoformat(),
            "client_snapshot": {},
            "completion_data": {"qtd_drop": 10},
        })
    await db.tickets.insert_many(docs)
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{API}/lousa/public/tech-performance/{cid_test}")
        assert r.status_code == 200
        j = r.json()
        assert j["closed_today"] == 4
        assert j["success_rate"] == 100
        # 4 notas com sucesso 100% e closed >=3 → badge "100% sucesso"
        assert "100%" in j["badge"] or "Líder" in j["badge"] or "ritmo" in j["badge"]
        assert j["avg_minutes"] == 30
    finally:
        await db.tickets.delete_many({"id": {"$regex": "^tkt-iter92-"}})
        await db.collaborators.delete_one({"id": cid_test})


@pytest.mark.asyncio
async def test_4_zero_closed_motivational_badge(db):
    cid_test = f"col-perfzero-{uuid.uuid4().hex[:6]}"
    await db.collaborators.insert_one({
        "id": cid_test, "company_id": "co-demo",
        "name": "Zero Tech", "active": True,
    })
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{API}/lousa/public/tech-performance/{cid_test}")
        assert r.status_code == 200
        j = r.json()
        assert j["closed_today"] == 0
        assert j["badge"].lower().startswith("bora")
        assert j["rank"] is None
        assert j["streak"] == 0
    finally:
        await db.collaborators.delete_one({"id": cid_test})
