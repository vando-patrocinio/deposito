"""tests/test_iter151_fleet_tracking_full.py

Comprehensive end-to-end test of Fleet Tracking Phase 1 MVP against the LIVE
preview backend (REACT_APP_BACKEND_URL).

Covers:
  - Ingest auth (token required, valid token + unknown IMEI returns reason)
  - Vehicle CRUD + IMEI duplicate (409)
  - Ingest with real IMEI -> live + history + stats
  - Geofence circle (entry/exit events) and speed events
  - Commands enqueue + gateway pull + ack
  - Tenants CRUD
  - Reports summary
  - TK103 parser standalone
"""
import os
import sys
import uuid
import time

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL",
                           "https://dual-combine-3.preview.emergentagent.com"
                           ).rstrip("/")
INGEST_TOKEN = "J7CxsgoQGixWQvKm8P16BrmDawn40jPwUeieRkW054g"

# Track created resources for cleanup
_created_vehicles: list = []
_created_geofences: list = []
_created_tenants: list = []


# ───────────────────────── fixtures ─────────────────────────
@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(session):
    r = session.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "admin@empresa.com",
                            "password": "123456"})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module", autouse=True)
def cleanup(session, admin_token):
    yield
    h = {"Authorization": f"Bearer {admin_token}"}
    for vid in _created_vehicles:
        session.delete(f"{BASE_URL}/api/fleet-tracking/vehicles/{vid}",
                        headers=h)
    for gid in _created_geofences:
        session.delete(f"{BASE_URL}/api/fleet-tracking/geofences/{gid}",
                        headers=h)
    for tid in _created_tenants:
        session.delete(f"{BASE_URL}/api/fleet-tracking/tenants/{tid}",
                        headers=h)


# ───────────────────────── INGEST AUTH ─────────────────────────
class TestIngestAuth:
    def test_ingest_no_token_401(self, session):
        r = session.post(f"{BASE_URL}/api/fleet-tracking/ingest",
                          json={"imei": "TEST_999", "lat": 0, "lng": 0})
        assert r.status_code == 401

    def test_ingest_bad_token_401(self, session):
        r = session.post(f"{BASE_URL}/api/fleet-tracking/ingest",
                          json={"imei": "TEST_999", "lat": 0, "lng": 0},
                          headers={"Authorization": "Bearer WRONG"})
        assert r.status_code == 401

    def test_ingest_unknown_imei(self, session):
        r = session.post(
            f"{BASE_URL}/api/fleet-tracking/ingest",
            json={"imei": "TEST_orphan_" + uuid.uuid4().hex[:6],
                  "lat": -23.5, "lng": -46.6},
            headers={"Authorization": f"Bearer {INGEST_TOKEN}"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False
        assert data["reason"] == "imei-not-registered"


# ───────────────────────── Vehicle CRUD ─────────────────────────
class TestVehicleCRUD:
    placa = f"TST{uuid.uuid4().hex[:4].upper()}"
    imei = "TEST" + uuid.uuid4().hex[:11]
    vid = None

    def test_create_vehicle(self, session, auth_headers):
        r = session.post(
            f"{BASE_URL}/api/fleet-tracking/vehicles",
            headers=auth_headers,
            json={"placa": self.placa, "imei": self.imei,
                  "tracker_model": "TK103", "tracker_password": "123456",
                  "modelo": "Onix", "speed_limit_kmh": 80})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["placa"] == self.placa
        assert data["imei"] == self.imei
        assert "id" in data
        TestVehicleCRUD.vid = data["id"]
        _created_vehicles.append(data["id"])

    def test_create_vehicle_duplicate_imei_409(self, session, auth_headers):
        r = session.post(
            f"{BASE_URL}/api/fleet-tracking/vehicles",
            headers=auth_headers,
            json={"placa": "DUP" + uuid.uuid4().hex[:3].upper(),
                  "imei": self.imei, "tracker_model": "TK103"})
        assert r.status_code == 409

    def test_list_vehicles_contains_created(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/fleet-tracking/vehicles",
                         headers=auth_headers)
        assert r.status_code == 200
        ids = [v["id"] for v in r.json()]
        assert TestVehicleCRUD.vid in ids

    def test_update_vehicle(self, session, auth_headers):
        r = session.put(
            f"{BASE_URL}/api/fleet-tracking/vehicles/{TestVehicleCRUD.vid}",
            headers=auth_headers,
            json={"placa": self.placa, "imei": self.imei,
                  "tracker_model": "TK103", "modelo": "Updated",
                  "speed_limit_kmh": 100})
        assert r.status_code == 200
        # Verify persistence
        r2 = session.get(f"{BASE_URL}/api/fleet-tracking/vehicles",
                          headers=auth_headers)
        veh = next(v for v in r2.json() if v["id"] == TestVehicleCRUD.vid)
        assert veh["modelo"] == "Updated"
        assert veh["speed_limit_kmh"] == 100


# ───────────────────────── Live + History ─────────────────────────
class TestPositions:
    def test_ingest_and_live(self, session, auth_headers):
        imei = TestVehicleCRUD.imei
        # Send 3 positions
        for i, (lat, lng, sp) in enumerate(
                [(-23.550, -46.630, 30),
                 (-23.551, -46.631, 45),
                 (-23.552, -46.632, 60)]):
            r = session.post(
                f"{BASE_URL}/api/fleet-tracking/ingest",
                json={"imei": imei, "lat": lat, "lng": lng,
                      "speed_kmh": sp, "heading": 90, "ignition": True,
                      "fix_valid": True},
                headers={"Authorization": f"Bearer {INGEST_TOKEN}"})
            assert r.status_code == 200
            assert r.json()["ok"] is True

        # Live
        r = session.get(f"{BASE_URL}/api/fleet-tracking/positions/live",
                         headers=auth_headers)
        assert r.status_code == 200
        found = [v for v in r.json() if v["id"] == TestVehicleCRUD.vid]
        assert found, "vehicle missing from live"
        v = found[0]
        assert v["lat"] is not None and v["lng"] is not None
        assert v["online"] is True

    def test_history_with_stats(self, session, auth_headers):
        r = session.get(
            f"{BASE_URL}/api/fleet-tracking/positions/"
            f"{TestVehicleCRUD.vid}/history",
            headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "points" in data
        assert "stats" in data
        s = data["stats"]
        assert "total_km" in s
        assert "moving_minutes" in s
        assert "stops" in s
        assert len(data["points"]) >= 3


# ───────────────────────── Geofences + speed events ─────────────────────────
class TestGeofencesAndEvents:
    gid = None

    def test_create_geofence_circle(self, session, auth_headers):
        r = session.post(
            f"{BASE_URL}/api/fleet-tracking/geofences",
            headers=auth_headers,
            json={"name": "TEST_fence_" + uuid.uuid4().hex[:4],
                  "kind": "circle", "center_lat": -23.550,
                  "center_lng": -46.630, "radius_m": 300,
                  "alert_on": "both",
                  "vehicle_ids": [TestVehicleCRUD.vid]})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["kind"] == "circle"
        assert data["radius_m"] == 300
        TestGeofencesAndEvents.gid = data["id"]
        _created_geofences.append(data["id"])

    def test_create_geofence_polygon_validation(self, session, auth_headers):
        # invalid: polygon needs >=3 points
        r = session.post(
            f"{BASE_URL}/api/fleet-tracking/geofences",
            headers=auth_headers,
            json={"name": "TEST_poly_bad", "kind": "polygon",
                  "polygon": [[-23.5, -46.6]]})
        assert r.status_code == 400

    def test_create_geofence_polygon_ok(self, session, auth_headers):
        r = session.post(
            f"{BASE_URL}/api/fleet-tracking/geofences",
            headers=auth_headers,
            json={"name": "TEST_poly_" + uuid.uuid4().hex[:4],
                  "kind": "polygon",
                  "polygon": [[-23.55, -46.63], [-23.55, -46.62],
                              [-23.54, -46.62], [-23.54, -46.63]]})
        assert r.status_code == 200
        _created_geofences.append(r.json()["id"])

    def test_geofence_exit_event_generated(self, session, auth_headers):
        imei = TestVehicleCRUD.imei
        # First position inside (will set initial inside state)
        session.post(
            f"{BASE_URL}/api/fleet-tracking/ingest",
            json={"imei": imei, "lat": -23.550, "lng": -46.630,
                  "speed_kmh": 10},
            headers={"Authorization": f"Bearer {INGEST_TOKEN}"})
        # Now go far OUTSIDE the 300m radius
        session.post(
            f"{BASE_URL}/api/fleet-tracking/ingest",
            json={"imei": imei, "lat": -23.600, "lng": -46.700,
                  "speed_kmh": 50},
            headers={"Authorization": f"Bearer {INGEST_TOKEN}"})
        time.sleep(0.5)
        r = session.get(
            f"{BASE_URL}/api/fleet-tracking/events",
            params={"vehicle_id": TestVehicleCRUD.vid},
            headers=auth_headers)
        assert r.status_code == 200
        kinds = [e["kind"] for e in r.json()]
        assert "geofence_exit" in kinds, f"events kinds = {kinds}"

    def test_speed_event_generated(self, session, auth_headers):
        imei = TestVehicleCRUD.imei
        # vehicle limit is 100 after update; send 150
        session.post(
            f"{BASE_URL}/api/fleet-tracking/ingest",
            json={"imei": imei, "lat": -23.560, "lng": -46.640,
                  "speed_kmh": 150},
            headers={"Authorization": f"Bearer {INGEST_TOKEN}"})
        time.sleep(0.4)
        r = session.get(
            f"{BASE_URL}/api/fleet-tracking/events",
            params={"vehicle_id": TestVehicleCRUD.vid, "kind": "speed"},
            headers=auth_headers)
        assert r.status_code == 200
        assert any(e["kind"] == "speed" for e in r.json())


# ───────────────────────── Commands ─────────────────────────
class TestCommands:
    cmd_id = None

    def test_create_command(self, session, auth_headers):
        r = session.post(
            f"{BASE_URL}/api/fleet-tracking/vehicles/"
            f"{TestVehicleCRUD.vid}/command",
            headers=auth_headers, json={"kind": "block"})
        assert r.status_code == 200
        data = r.json()
        assert data["kind"] == "block"
        assert data["status"] == "pending"
        TestCommands.cmd_id = data["id"]

    def test_gateway_pull_pending(self, session):
        r = session.get(
            f"{BASE_URL}/api/fleet-tracking/commands/{TestVehicleCRUD.imei}",
            headers={"Authorization": f"Bearer {INGEST_TOKEN}"})
        assert r.status_code == 200
        ids = [c["id"] for c in r.json()]
        assert TestCommands.cmd_id in ids

    def test_gateway_ack(self, session):
        r = session.post(
            f"{BASE_URL}/api/fleet-tracking/commands/"
            f"{TestCommands.cmd_id}/ack",
            json={"ok": True, "msg": "executed"},
            headers={"Authorization": f"Bearer {INGEST_TOKEN}"})
        assert r.status_code == 200
        # After ack should not be in pending list
        r2 = session.get(
            f"{BASE_URL}/api/fleet-tracking/commands/{TestVehicleCRUD.imei}",
            headers={"Authorization": f"Bearer {INGEST_TOKEN}"})
        ids = [c["id"] for c in r2.json()]
        assert TestCommands.cmd_id not in ids


# ───────────────────────── Tenants white-label ─────────────────────────
class TestTenants:
    tid = None

    def test_create_tenant(self, session, auth_headers):
        r = session.post(
            f"{BASE_URL}/api/fleet-tracking/tenants",
            headers=auth_headers,
            json={"name": "TEST_Tenant_" + uuid.uuid4().hex[:4],
                  "contact_email": "x@y.com", "monthly_fee": 99.0})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["monthly_fee"] == 99.0
        TestTenants.tid = data["id"]
        _created_tenants.append(data["id"])

    def test_list_tenants(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/fleet-tracking/tenants",
                         headers=auth_headers)
        assert r.status_code == 200
        assert any(t["id"] == TestTenants.tid for t in r.json())


# ───────────────────────── Reports ─────────────────────────
class TestReports:
    def test_summary_includes_vehicle(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/fleet-tracking/reports/summary",
                         params={"days": 7}, headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["days"] == 7
        assert "rows" in data
        row = next((x for x in data["rows"]
                     if x["vehicle_id"] == TestVehicleCRUD.vid), None)
        assert row is not None
        assert "km" in row and "moving_hours" in row and "stops" in row


# ───────────────────────── TK103 Parser standalone ─────────────────────────
class TestTK103Parser:
    def test_parse_frame(self):
        sys.path.insert(0, "/app/fleet_gateway")
        from tk103_parser import parse_frame, build_command  # type: ignore
        frame = ("*HQ,1234567890,V1,123456,A,2334.1234,S,04612.5678,W,"
                 "015.0,180,010326,FFFFFBFF#")
        pos = parse_frame(frame)
        assert pos is not None
        assert pos["imei"] == "1234567890"
        assert pos["fix_valid"] is True
        assert -24 < pos["lat"] < -23
        assert -47 < pos["lng"] < -46
        assert pos["speed_kmh"] == 15.0
        assert build_command("block", "123456") == "RELAY,1123456#"
        assert build_command("unblock", "123456") == "RELAY,0123456#"
        assert build_command("locate_now") == "WHERE#"

    def test_parse_invalid(self):
        sys.path.insert(0, "/app/fleet_gateway")
        from tk103_parser import parse_frame  # type: ignore
        assert parse_frame("garbage") is None
        assert parse_frame("") is None
