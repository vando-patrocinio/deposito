"""Iter 95 — Modo Boss: chamados urgentes."""
import os
import uuid

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


async def _login():
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{API}/auth/login", json={
            "email": "admin@empresa.com", "password": "123456",
        })
    assert r.status_code == 200
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.mark.asyncio
async def test_1_create_urgent_ticket_succeeds(db):
    token = await _login()
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            f"{API}/lousa/tickets",
            json={
                "client_name": f"BossClient-{uuid.uuid4().hex[:6]}",
                "address": "R. Boss Test 1", "neighborhood": "TestCentro",
                "phone": "5521988887777", "relato": "boss test",
                "type": "reparo", "priority": "urgente",
                "assigned_collaborator_id": "col-30aafc3c",
                "scheduled_time": None,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["priority"] == "urgente"
    tid = j["id"]
    # Cleanup
    await db.tickets.delete_one({"id": tid})
    await db.aihub_wa_messages.delete_many({"ticket_id": tid})


@pytest.mark.asyncio
async def test_2_invalid_priority_rejected():
    token = await _login()
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            f"{API}/lousa/tickets",
            json={
                "client_name": "X", "address": "R. X",
                "neighborhood": "Y", "phone": "5521000000000",
                "relato": "x", "type": "reparo",
                "priority": "super_urgente_inexistente",
                "assigned_collaborator_id": "col-30aafc3c",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_3_urgent_ranks_above_horario(db):
    """Cria urgente + horario para mesmo tech, valida que urgente vem antes."""
    token = await _login()
    headers = {"Authorization": f"Bearer {token}"}
    payloads = [
        {
            "client_name": f"BossA-{uuid.uuid4().hex[:6]}",
            "address": "R. A", "neighborhood": "TX",
            "phone": "5521900000001", "relato": "horario",
            "type": "reparo", "priority": "horario",
            "assigned_collaborator_id": "col-30aafc3c",
            "scheduled_time": None,
        },
        {
            "client_name": f"BossB-{uuid.uuid4().hex[:6]}",
            "address": "R. B", "neighborhood": "TX",
            "phone": "5521900000002", "relato": "urgente",
            "type": "reparo", "priority": "urgente",
            "assigned_collaborator_id": "col-30aafc3c",
            "scheduled_time": None,
        },
    ]
    created_ids = []
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            for p in payloads:
                r = await c.post(f"{API}/lousa/tickets", json=p,
                                    headers=headers)
                assert r.status_code == 200, r.text
                created_ids.append(r.json()["id"])
            # Lista por collab
            r2 = await c.get(
                f"{API}/lousa/by-collaborator/col-30aafc3c",
                headers=headers,
            )
            assert r2.status_code == 200
            tickets = r2.json().get("tickets") or []
            # Urgente deve aparecer ANTES de horario na lista (não-finalizada)
            seen_urgente = False
            for t in tickets:
                if t["id"] not in created_ids:
                    continue
                if t["priority"] == "urgente":
                    seen_urgente = True
                elif t["priority"] == "horario":
                    assert seen_urgente, "urgente deve vir antes de horario"
    finally:
        for tid in created_ids:
            await db.tickets.delete_one({"id": tid})
            await db.aihub_wa_messages.delete_many({"ticket_id": tid})
