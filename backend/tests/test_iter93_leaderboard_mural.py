"""Iter 93 — Mural público de ranking de técnicos."""
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
async def test_1_leaderboard_returns_shape():
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{API}/lousa/public/leaderboard?company_id=co-demo")
    assert r.status_code == 200
    j = r.json()
    for k in ("company_id", "generated_at", "total_techs", "leaderboard"):
        assert k in j
    assert isinstance(j["leaderboard"], list)


@pytest.mark.asyncio
async def test_2_no_auth_required():
    """Endpoint público — sem Authorization header funciona."""
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{API}/lousa/public/leaderboard")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_3_ranking_with_seeded_data(db):
    """Cria 3 técnicos, 2/4/1 fechadas — valida ordenação."""
    cids = [f"col-mural-{i}-{uuid.uuid4().hex[:6]}" for i in range(3)]
    counts = [2, 4, 1]
    expected_order = [cids[1], cids[0], cids[2]]  # 4 > 2 > 1
    now = datetime.now(timezone.utc)

    cols = [
        {"id": cids[0], "company_id": "co-demo", "name": "Alpha Tech",
          "active": True, "role": "técnico", "cpf": f"CPF{uuid.uuid4().hex[:9]}"},
        {"id": cids[1], "company_id": "co-demo", "name": "Bravo Líder",
          "active": True, "role": "técnico", "cpf": f"CPF{uuid.uuid4().hex[:9]}"},
        {"id": cids[2], "company_id": "co-demo", "name": "Charlie Junior",
          "active": True, "role": "técnico", "cpf": f"CPF{uuid.uuid4().hex[:9]}"},
    ]
    await db.collaborators.insert_many(cols)

    tickets = []
    for idx, cid in enumerate(cids):
        for j in range(counts[idx]):
            opened = now - timedelta(hours=2, minutes=j * 4)
            closed = opened + timedelta(minutes=20)
            tickets.append({
                "id": f"tkt-iter93-{uuid.uuid4().hex[:8]}",
                "company_id": "co-demo", "type": "suporte",
                "status": "finalizada", "outcome": "sucesso",
                "assigned_collaborator_id": cid,
                "opened_at": opened.isoformat(),
                "closed_at": closed.isoformat(),
                "client_snapshot": {},
                "completion_data": {"qtd_drop": 5},
            })
    await db.tickets.insert_many(tickets)

    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(
                f"{API}/lousa/public/leaderboard?company_id=co-demo&limit=3"
            )
        assert r.status_code == 200
        j = r.json()
        lb = j["leaderboard"]
        # Filtrar somente nossos técnicos (pode haver outros)
        ours = [row for row in lb if row["collaborator_id"] in cids]
        assert len(ours) == 3
        # ordenação por closed_today desc
        ranks_by_cid = {row["collaborator_id"]: row["rank"] for row in lb}
        assert ranks_by_cid[expected_order[0]] < ranks_by_cid[expected_order[1]]
        assert ranks_by_cid[expected_order[1]] < ranks_by_cid[expected_order[2]]
        # Líder com 4 fechadas + 100% deve receber badge
        leader = next(r for r in lb if r["collaborator_id"] == cids[1])
        assert leader["closed_today"] == 4
        assert leader["success_rate"] == 100
        assert leader["name"] == "Bravo Líder"
        assert leader["badge"]  # algum badge motivacional
    finally:
        await db.tickets.delete_many({"id": {"$regex": "^tkt-iter93-"}})
        await db.collaborators.delete_many({"id": {"$in": cids}})


@pytest.mark.asyncio
async def test_4_limit_param_caps_results():
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(
            f"{API}/lousa/public/leaderboard?company_id=co-demo&limit=2"
        )
    assert r.status_code == 200
    j = r.json()
    assert len(j["leaderboard"]) <= 2
