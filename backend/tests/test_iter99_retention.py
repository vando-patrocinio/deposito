"""Iter 99 — Modo Cliente Cancelando (Playbook de Retenção)."""
import os

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


async def _token():
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{API}/auth/login", json={
            "email": "admin@empresa.com", "password": "123456",
        })
    return r.json().get("access_token") or r.json().get("token")


@pytest.mark.asyncio
async def test_1_get_default_config():
    token = await _token()
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{API}/gestao-ia/retention/config",
                          headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    j = r.json()
    for k in ("enabled", "trigger_risk", "discount_pct",
              "visit_window_hours", "auto_send_whatsapp",
              "create_urgent_ticket", "message_template"):
        assert k in j


@pytest.mark.asyncio
async def test_2_update_config_and_validations(db):
    token = await _token()
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=15) as c:
        # Valid update
        r = await c.post(f"{API}/gestao-ia/retention/config",
                            json={"discount_pct": 30, "trigger_risk": "alto"},
                            headers=headers)
        assert r.status_code == 200
        assert r.json()["discount_pct"] == 30
        assert r.json()["trigger_risk"] == "alto"
        # Invalid trigger_risk
        r2 = await c.post(f"{API}/gestao-ia/retention/config",
                              json={"trigger_risk": "extremo"},
                              headers=headers)
        assert r2.status_code == 400
        # Invalid discount
        r3 = await c.post(f"{API}/gestao-ia/retention/config",
                              json={"discount_pct": 150},
                              headers=headers)
        assert r3.status_code == 400
        # Invalid visit_window
        r4 = await c.post(f"{API}/gestao-ia/retention/config",
                              json={"visit_window_hours": 200},
                              headers=headers)
        assert r4.status_code == 400
    # Cleanup
    await db.retention_playbook.delete_many({"company_id": "co-demo"})


@pytest.mark.asyncio
async def test_3_trigger_creates_mural_and_ticket(db):
    token = await _token()
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{API}/gestao-ia/retention/trigger",
                            json={"phone": "5521988887777",
                                    "customer_name": "Pytest Cliente",
                                    "risk_reason": "test"},
                            headers=headers)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is True
        rid = j["retention_id"]
        tid = j["ticket_id"]
        # Idempotência: segundo trigger não duplica
        r2 = await c.post(f"{API}/gestao-ia/retention/trigger",
                              json={"phone": "5521988887777",
                                      "customer_name": "Pytest Cliente"},
                              headers=headers)
        assert r2.status_code == 200
        assert r2.json()["ok"] is False  # já existe
        # Mural lista
        r3 = await c.get(f"{API}/gestao-ia/retention/mural",
                            headers=headers)
        assert r3.status_code == 200
        items = r3.json()["items"]
        assert any(i["id"] == rid for i in items)
        # Update status
        r4 = await c.patch(f"{API}/gestao-ia/retention/mural/{rid}",
                              json={"status": "won"},
                              headers=headers)
        assert r4.status_code == 200
        assert r4.json()["status"] == "won"
        # Após "won", uma nova trigger DEVE conseguir abrir (status mudou)
        r5 = await c.post(f"{API}/gestao-ia/retention/trigger",
                              json={"phone": "5521988887777",
                                      "customer_name": "Pytest Cliente"},
                              headers=headers)
        assert r5.status_code == 200
        new_rid = r5.json().get("retention_id")
        assert new_rid and new_rid != rid

    # Cleanup
    await db.retention_mural.delete_many({"customer_name": "Pytest Cliente"})
    await db.tickets.delete_one({"id": tid})
    await db.tickets.delete_many({"type": "retencao"})


@pytest.mark.asyncio
async def test_4_invalid_status_rejected(db):
    token = await _token()
    headers = {"Authorization": f"Bearer {token}"}
    # Cria entry via trigger primeiro
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{API}/gestao-ia/retention/trigger",
                            json={"phone": "5511999991122",
                                    "customer_name": "T2"},
                            headers=headers)
        rid = r.json()["retention_id"]
        try:
            r2 = await c.patch(f"{API}/gestao-ia/retention/mural/{rid}",
                                  json={"status": "magico"},
                                  headers=headers)
            assert r2.status_code == 400
        finally:
            await db.retention_mural.delete_many(
                {"customer_name": "T2"},
            )
            await db.tickets.delete_many({"type": "retencao"})


@pytest.mark.asyncio
async def test_5_disabled_playbook_blocks_trigger(db):
    token = await _token()
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=15) as c:
        await c.post(f"{API}/gestao-ia/retention/config",
                       json={"enabled": False}, headers=headers)
        try:
            r = await c.post(f"{API}/gestao-ia/retention/trigger",
                                json={"phone": "5511000000000",
                                        "customer_name": "Should fail"},
                                headers=headers)
            assert r.status_code == 200
            j = r.json()
            assert j["ok"] is False
            assert "desativado" in j["reason"].lower()
        finally:
            await c.post(f"{API}/gestao-ia/retention/config",
                          json={"enabled": True}, headers=headers)
            await db.retention_playbook.delete_many({"company_id": "co-demo"})
