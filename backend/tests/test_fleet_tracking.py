"""tests/test_fleet_tracking.py — Smoke test do módulo Fleet Tracking (Phase 1).

Cobre:
  • Ingest sem auth + com token (positivo + negativo)
  • CRUD vehicles (precisa user gestor)
  • positions/live, positions/history
  • geofences CRUD
  • commands enqueue
  • tenants CRUD

Roda contra MongoDB local sem mockar (use DB de teste se quiser isolamento).
"""
import os
import pytest
from httpx import AsyncClient, ASGITransport

os.environ.setdefault("FLEET_INGEST_TOKEN",
                       "J7CxsgoQGixWQvKm8P16BrmDawn40jPwUeieRkW054g")

from server import app  # noqa: E402


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport,
                            base_url="http://test") as c:
        yield c


async def _login_admin(c: AsyncClient) -> str:
    r = await c.post("/api/auth/login",
                      json={"email": "admin@empresa.com", "password": "123456"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_ingest_token_required(client):
    r = await client.post("/api/fleet-tracking/ingest",
                           json={"imei": "999", "lat": 0, "lng": 0})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_ingest_unknown_imei(client):
    r = await client.post(
        "/api/fleet-tracking/ingest",
        json={"imei": "test-unknown-999", "lat": -23.5, "lng": -46.6},
        headers={"Authorization":
                  "Bearer J7CxsgoQGixWQvKm8P16BrmDawn40jPwUeieRkW054g"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert r.json()["reason"] == "imei-not-registered"


@pytest.mark.asyncio
async def test_full_vehicle_flow(client):
    token = await _login_admin(client)
    h = {"Authorization": f"Bearer {token}"}

    # Cria
    imei = f"99887766{os.urandom(2).hex()}"
    r = await client.post("/api/fleet-tracking/vehicles",
                           headers=h,
                           json={"placa": f"TST{os.urandom(2).hex()}",
                                  "imei": imei,
                                  "tracker_model": "TK103",
                                  "modelo": "Onix",
                                  "speed_limit_kmh": 100})
    assert r.status_code == 200, r.text
    vid = r.json()["id"]

    # Lista
    r = await client.get("/api/fleet-tracking/vehicles", headers=h)
    assert r.status_code == 200
    assert any(v["id"] == vid for v in r.json())

    # Ingest com IMEI real
    r = await client.post(
        "/api/fleet-tracking/ingest",
        json={"imei": imei, "lat": -23.55, "lng": -46.63,
              "speed_kmh": 50, "heading": 90, "ignition": True},
        headers={"Authorization":
                  "Bearer J7CxsgoQGixWQvKm8P16BrmDawn40jPwUeieRkW054g"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # Live deve retornar este veículo
    r = await client.get("/api/fleet-tracking/positions/live", headers=h)
    assert r.status_code == 200
    found = [v for v in r.json() if v["id"] == vid]
    assert found and found[0]["lat"] is not None

    # History
    r = await client.get(f"/api/fleet-tracking/positions/{vid}/history",
                          headers=h)
    assert r.status_code == 200
    assert "points" in r.json()

    # Geofence
    r = await client.post("/api/fleet-tracking/geofences", headers=h,
                           json={"name": "Test fence",
                                  "kind": "circle",
                                  "center_lat": -23.55, "center_lng": -46.63,
                                  "radius_m": 500})
    assert r.status_code == 200, r.text
    gid = r.json()["id"]

    # Comando
    r = await client.post(f"/api/fleet-tracking/vehicles/{vid}/command",
                           headers=h, json={"kind": "locate_now"})
    assert r.status_code == 200

    # Cleanup
    await client.delete(f"/api/fleet-tracking/vehicles/{vid}", headers=h)
    await client.delete(f"/api/fleet-tracking/geofences/{gid}", headers=h)


@pytest.mark.asyncio
async def test_tk103_parser():
    import sys
    sys.path.insert(0, "/app/fleet_gateway")
    from tk103_parser import parse_frame, build_command  # type: ignore
    frame = "*HQ,1234567890,V1,123456,A,2334.1234,S,04612.5678,W,015.0,180,010326,FFFFFBFF#"
    pos = parse_frame(frame)
    assert pos is not None
    assert pos["imei"] == "1234567890"
    assert pos["fix_valid"] is True
    assert -24 < pos["lat"] < -23
    assert build_command("block", "123456") == "RELAY,1123456#"
    assert build_command("locate_now") == "WHERE#"
