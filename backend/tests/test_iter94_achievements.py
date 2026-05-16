"""Iter 94 — Conquistas/medalhas persistentes."""
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


@pytest_asyncio.fixture
async def db():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    yield cli[os.environ["DB_NAME"]]
    cli.close()


@pytest.mark.asyncio
async def test_1_unknown_collab_returns_404():
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{API}/lousa/public/achievements/col-xyz-nao-existe")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_2_shape_with_real_collab():
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{API}/lousa/public/achievements/col-30aafc3c")
    assert r.status_code == 200
    j = r.json()
    assert "medals" in j
    assert "earned_count" in j
    assert "total_count" in j
    assert j["total_count"] >= 10
    assert isinstance(j["medals"], list)
    medal_ids = {m["id"] for m in j["medals"]}
    # IDs do catálogo presentes
    for required in ("primeira_nota", "dezena", "centena",
                      "instalador_10", "streak_7", "veloz", "sinal_ouro"):
        assert required in medal_ids


@pytest.mark.asyncio
async def test_3_seed_unlocks_multiple_medals(db):
    cid = f"col-ach-{uuid.uuid4().hex[:6]}"
    await db.collaborators.insert_one({
        "id": cid, "company_id": "co-demo", "name": "Veloz Tech",
        "active": True, "role": "técnico",
        "cpf": f"CPF{uuid.uuid4().hex[:9]}",
    })
    # Seed 12 instalacoes finalizadas (dispara primeira_nota, dezena, instalador_10)
    now = datetime.now(timezone.utc)
    docs = []
    for i in range(12):
        opened = now - timedelta(days=i, hours=2)
        closed = opened + timedelta(minutes=20)  # veloz < 30min
        docs.append({
            "id": f"tkt-iter94-{uuid.uuid4().hex[:8]}",
            "company_id": "co-demo", "type": "instalacao",
            "status": "finalizada", "outcome": "sucesso",
            "assigned_collaborator_id": cid,
            "opened_at": opened.isoformat(),
            "closed_at": closed.isoformat(),
            "client_snapshot": {},
            "completion_data": {"sinal": -21.0, "qtd_drop": 50},
        })
    await db.tickets.insert_many(docs)
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{API}/lousa/public/achievements/{cid}")
        assert r.status_code == 200
        j = r.json()
        earned_ids = {m["id"] for m in j["medals"] if m["earned"]}
        assert "primeira_nota" in earned_ids
        assert "dezena" in earned_ids
        assert "instalador_10" in earned_ids
        # 12 < 100 → centena bloqueada
        assert "centena" not in earned_ids
        # sinal_ouro precisa de 50+ — não desbloqueia com 12
        assert "sinal_ouro" not in earned_ids
        assert j["stats"]["total_closed"] == 12
        assert j["stats"]["instalacoes"] == 12
        assert j["stats"]["avg_minutes"] == 20
    finally:
        await db.tickets.delete_many({"id": {"$regex": "^tkt-iter94-"}})
        await db.collaborators.delete_one({"id": cid})


@pytest.mark.asyncio
async def test_4_streak_calculation(db):
    cid = f"col-streak-{uuid.uuid4().hex[:6]}"
    await db.collaborators.insert_one({
        "id": cid, "company_id": "co-demo", "name": "Streak Tech",
        "active": True, "role": "técnico",
        "cpf": f"CPF{uuid.uuid4().hex[:9]}",
    })
    # 8 dias consecutivos com 1 nota cada
    now = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0,
                                                microsecond=0)
    docs = []
    for d in range(8):
        when = now - timedelta(days=d)
        opened = when - timedelta(minutes=30)
        docs.append({
            "id": f"tkt-iter94s-{uuid.uuid4().hex[:8]}",
            "company_id": "co-demo", "type": "suporte",
            "status": "finalizada", "outcome": "sucesso",
            "assigned_collaborator_id": cid,
            "opened_at": opened.isoformat(),
            "closed_at": when.isoformat(),
            "client_snapshot": {},
            "completion_data": {"qtd_drop": 5},
        })
    await db.tickets.insert_many(docs)
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{API}/lousa/public/achievements/{cid}")
        assert r.status_code == 200
        j = r.json()
        assert j["stats"]["max_streak"] == 8
        earned = {m["id"] for m in j["medals"] if m["earned"]}
        assert "streak_7" in earned
        assert "streak_30" not in earned
    finally:
        await db.tickets.delete_many({"id": {"$regex": "^tkt-iter94s-"}})
        await db.collaborators.delete_one({"id": cid})
