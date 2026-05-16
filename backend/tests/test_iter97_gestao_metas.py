"""Iter 97 — GESTÃO E METAS: pontos, medalha retirador, dashboard config,
geofence, GESTAO_IA, admin optimize-route."""
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


async def _token():
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{API}/auth/login", json={
            "email": "admin@empresa.com", "password": "123456",
        })
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.mark.asyncio
async def test_1_perf_returns_points_today():
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{API}/lousa/public/tech-performance/col-30aafc3c")
    assert r.status_code == 200
    j = r.json()
    assert "points_today" in j
    assert isinstance(j["points_today"], (int, float))


@pytest.mark.asyncio
async def test_2_retirador_medal_in_catalog():
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{API}/lousa/public/achievements/col-30aafc3c")
    assert r.status_code == 200
    j = r.json()
    ids = {m["id"] for m in j["medals"]}
    assert "retirador" in ids
    assert j["total_count"] >= 11


@pytest.mark.asyncio
async def test_3_dashboard_config_get_and_set():
    token = await _token()
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{API}/lousa/admin/dashboard-config",
                          headers=headers)
        assert r.status_code == 200
        original = r.json()
        # Toggle off
        r2 = await c.post(f"{API}/lousa/admin/dashboard-config",
                            json={"show_smart_route": False},
                            headers=headers)
        assert r2.status_code == 200
        assert r2.json()["show_smart_route"] is False
        # Reset
        r3 = await c.post(
            f"{API}/lousa/admin/dashboard-config",
            json={"show_smart_route": original.get("show_smart_route", True)},
            headers=headers,
        )
        assert r3.status_code == 200


@pytest.mark.asyncio
async def test_4_dashboard_config_public_endpoint():
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(
            f"{API}/lousa/public/dashboard-config/col-30aafc3c"
        )
    assert r.status_code == 200
    j = r.json()
    for k in ("show_performance", "show_achievements",
              "show_smart_route", "show_points", "enable_geofence_alerts"):
        assert k in j


@pytest.mark.asyncio
async def test_5_geofence_ping_no_open_ticket():
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            f"{API}/lousa/public/geofence-ping",
            json={"collaborator_id": "col-30aafc3c",
                  "lat": -22.9, "lng": -43.2},
        )
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["alert"] is False


@pytest.mark.asyncio
async def test_6_geofence_creates_alert_when_far_for_5min(db):
    """Cria chamado em_andamento atrás, ping fora da área, força elapsed."""
    cid = "col-30aafc3c"
    # Cria ticket em_andamento com endereço (-22.9, -43.2)
    tid = f"tkt-iter97-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    await db.tickets.insert_one({
        "id": tid, "company_id": "co-demo",
        "type": "reparo", "priority": "normal",
        "status": "em_andamento",
        "assigned_collaborator_id": cid,
        "created_at": now.isoformat(),
        "opened_at": now.isoformat(),
        "client_snapshot": {
            "name": "GeofenceClient", "address": "R. Origem 1",
            "neighborhood": "X", "phone": "",
            "latitude": -22.9, "longitude": -43.2,
        },
        "position": int(now.timestamp() * -1000),
    })
    try:
        # 1º ping: longe → cria outside_since
        async with httpx.AsyncClient(timeout=20) as c:
            r1 = await c.post(f"{API}/lousa/public/geofence-ping",
                                  json={"collaborator_id": cid,
                                          "lat": -22.97, "lng": -43.28})
        assert r1.status_code == 200
        # Simula passagem de tempo: força outside_since 6min atrás
        await db.tickets.update_one(
            {"id": tid},
            {"$set": {"geofence_state.outside_since":
                          (now - timedelta(minutes=6)).isoformat()}},
        )
        # 2º ping: longe + agora elapsed_min >= 5 → cria alert
        async with httpx.AsyncClient(timeout=20) as c:
            r2 = await c.post(f"{API}/lousa/public/geofence-ping",
                                  json={"collaborator_id": cid,
                                          "lat": -22.97, "lng": -43.28})
        assert r2.status_code == 200
        j = r2.json()
        assert j["alert"] is True
        assert "alert_id" in j
        # Verifica bolha criada com type=alerta_geofence
        alert = await db.tickets.find_one(
            {"id": j["alert_id"]}, {"_id": 0, "type": 1, "priority": 1,
                                       "assigned_collaborator_id": 1},
        )
        assert alert["type"] == "alerta_geofence"
        assert alert["priority"] == "urgente"
        assert alert["assigned_collaborator_id"] == cid
        # 3º ping ainda longe: NÃO duplica
        async with httpx.AsyncClient(timeout=20) as c:
            r3 = await c.post(f"{API}/lousa/public/geofence-ping",
                                  json={"collaborator_id": cid,
                                          "lat": -22.97, "lng": -43.28})
        j3 = r3.json()
        assert j3["alert"] is False
        # Cleanup do alert
        await db.tickets.delete_one({"id": j["alert_id"]})
    finally:
        await db.tickets.delete_one({"id": tid})


@pytest.mark.asyncio
async def test_7_admin_optimize_route_requires_last_position(db):
    """Sem last_position no técnico, retorna 400."""
    token = await _token()
    # Limpa last_position de um tech temporário
    cid = f"col-routetest-{uuid.uuid4().hex[:6]}"
    await db.collaborators.insert_one({
        "id": cid, "company_id": "co-demo", "name": "Route Test Tech",
        "active": True, "role": "técnico",
        "cpf": f"CPF{uuid.uuid4().hex[:9]}",
    })
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{API}/lousa/admin/optimize-route",
                                json={"collaborator_id": cid, "apply": False},
                                headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 400
        assert "GPS" in r.json()["detail"]
    finally:
        await db.collaborators.delete_one({"id": cid})


@pytest.mark.asyncio
async def test_8_gestao_ia_generate(db):
    """Smoke: GESTAO_IA gera relatório com schema correto."""
    token = await _token()
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{API}/gestao-ia/generate",
                            headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    j = r.json()
    for k in ("snapshot_current", "snapshot_previous", "kpi_deltas",
              "top_techs", "ai_analysis", "generated_at"):
        assert k in j
    ai = j["ai_analysis"]
    assert "resumo_executivo" in ai
    assert "kpis" in ai
    assert "acoes_recomendadas" in ai
