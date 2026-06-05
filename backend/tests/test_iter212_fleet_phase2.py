"""iter212 Phase 2 — Fleet portal white-label + TTL orphan + portal users CRUD.

Cobre:
- Admin endpoints: POST/GET/DELETE /api/fleet-tracking/tenants/{tid}/portal-users
- Portal auth: POST /api/fleet-portal/auth/login + GET /api/fleet-portal/me
- Isolation: portal só vê veículos com fleet_tenant_id == seu
- TTL: fleet_orphan_positions tem received_at_dt (BSON Date) + index TTL 30d
"""
import os
import uuid
import asyncio
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
INGEST_TOKEN = "J7CxsgoQGixWQvKm8P16BrmDawn40jPwUeieRkW054g"

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def tenant(admin_h):
    name = f"TEST_iter212_{uuid.uuid4().hex[:6]}"
    r = requests.post(f"{BASE_URL}/api/fleet-tracking/tenants", headers=admin_h,
                      json={"name": name, "contact_email": "t@t.com", "monthly_fee": 99.0}, timeout=15)
    assert r.status_code == 200, r.text
    t = r.json()
    yield t
    requests.delete(f"{BASE_URL}/api/fleet-tracking/tenants/{t['id']}", headers=admin_h, timeout=10)


@pytest.fixture(scope="module")
def created_vehicles(admin_h, tenant):
    """Cria dois veículos: 1 dentro do tenant, 1 frota própria (fleet_tenant_id=null)."""
    veh_ids = []
    placa1 = f"TST{uuid.uuid4().hex[:4].upper()}"
    imei1 = "8800000" + uuid.uuid4().hex[:6]
    r1 = requests.post(f"{BASE_URL}/api/fleet-tracking/vehicles", headers=admin_h,
                       json={"placa": placa1, "imei": imei1, "fleet_tenant_id": tenant["id"],
                             "modelo": "Tenant-Car"}, timeout=15)
    assert r1.status_code == 200, r1.text
    veh_ids.append(r1.json()["id"])

    placa2 = f"OWN{uuid.uuid4().hex[:4].upper()}"
    imei2 = "8800001" + uuid.uuid4().hex[:6]
    r2 = requests.post(f"{BASE_URL}/api/fleet-tracking/vehicles", headers=admin_h,
                       json={"placa": placa2, "imei": imei2, "modelo": "Own-Car"}, timeout=15)
    assert r2.status_code == 200, r2.text
    veh_ids.append(r2.json()["id"])

    yield {"tenant_vid": veh_ids[0], "own_vid": veh_ids[1],
           "tenant_imei": imei1, "own_imei": imei2}

    for vid in veh_ids:
        requests.delete(f"{BASE_URL}/api/fleet-tracking/vehicles/{vid}", headers=admin_h, timeout=10)


# ── Admin endpoints: portal users CRUD ────────────────────────────────────
class TestPortalUsersAdmin:
    def test_create_portal_user(self, admin_h, tenant):
        email = f"portal_{uuid.uuid4().hex[:6]}@t.com"
        r = requests.post(f"{BASE_URL}/api/fleet-tracking/tenants/{tenant['id']}/portal-users",
                          headers=admin_h, json={"email": email, "password": "p@ss1234", "name": "Tester"},
                          timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["email"] == email
        assert d["name"] == "Tester"
        assert "id" in d
        pytest.portal_uid = d["id"]
        pytest.portal_email = email

    def test_duplicate_email_returns_409(self, admin_h, tenant):
        r = requests.post(f"{BASE_URL}/api/fleet-tracking/tenants/{tenant['id']}/portal-users",
                          headers=admin_h,
                          json={"email": pytest.portal_email, "password": "x", "name": "Dup"}, timeout=15)
        assert r.status_code == 409, r.text

    def test_list_portal_users(self, admin_h, tenant):
        r = requests.get(f"{BASE_URL}/api/fleet-tracking/tenants/{tenant['id']}/portal-users",
                         headers=admin_h, timeout=15)
        assert r.status_code == 200
        emails = [u["email"] for u in r.json()]
        assert pytest.portal_email in emails
        # password_hash should never appear in listing
        for u in r.json():
            assert "password_hash" not in u


# ── Portal auth: login + me ──────────────────────────────────────────────
class TestPortalAuth:
    def test_login_invalid_email_401(self):
        r = requests.post(f"{BASE_URL}/api/fleet-portal/auth/login",
                          json={"email": "noexists@x.com", "password": "x"}, timeout=15)
        assert r.status_code == 401

    def test_login_invalid_password_401(self):
        r = requests.post(f"{BASE_URL}/api/fleet-portal/auth/login",
                          json={"email": pytest.portal_email, "password": "wrong"}, timeout=15)
        assert r.status_code == 401

    def test_login_success(self, tenant):
        r = requests.post(f"{BASE_URL}/api/fleet-portal/auth/login",
                          json={"email": pytest.portal_email, "password": "p@ss1234"}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "access_token" in d
        assert d["user"]["email"] == pytest.portal_email
        assert d["tenant"]["id"] == tenant["id"]
        pytest.portal_token = d["access_token"]

    def test_me_without_token_401(self):
        r = requests.get(f"{BASE_URL}/api/fleet-portal/me", timeout=15)
        assert r.status_code == 401

    def test_me_with_normal_app_token_403(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/fleet-portal/me",
                         headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
        assert r.status_code == 403, r.text

    def test_me_with_portal_token_ok(self, tenant):
        r = requests.get(f"{BASE_URL}/api/fleet-portal/me",
                         headers={"Authorization": f"Bearer {pytest.portal_token}"}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["user"]["email"] == pytest.portal_email
        assert d["tenant"]["id"] == tenant["id"]


# ── Portal isolation: só vê veículos do tenant ────────────────────────────
class TestPortalIsolation:
    def test_vehicles_only_tenant(self, created_vehicles):
        r = requests.get(f"{BASE_URL}/api/fleet-portal/vehicles",
                         headers={"Authorization": f"Bearer {pytest.portal_token}"}, timeout=15)
        assert r.status_code == 200, r.text
        vids = [v["id"] for v in r.json()]
        assert created_vehicles["tenant_vid"] in vids, "tenant veículo deve aparecer"
        assert created_vehicles["own_vid"] not in vids, "veículo frota própria NÃO deve aparecer"

    def test_positions_live_only_tenant(self, created_vehicles):
        r = requests.get(f"{BASE_URL}/api/fleet-portal/positions/live",
                         headers={"Authorization": f"Bearer {pytest.portal_token}"}, timeout=15)
        assert r.status_code == 200
        vids = [v["id"] for v in r.json()]
        assert created_vehicles["own_vid"] not in vids

    def test_history_other_vehicle_404(self, created_vehicles):
        r = requests.get(f"{BASE_URL}/api/fleet-portal/positions/{created_vehicles['own_vid']}/history",
                         headers={"Authorization": f"Bearer {pytest.portal_token}"}, timeout=15)
        assert r.status_code == 404, r.text

    def test_events_isolated(self):
        r = requests.get(f"{BASE_URL}/api/fleet-portal/events",
                         headers={"Authorization": f"Bearer {pytest.portal_token}"}, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ── Geofence map editor: create circle + polygon ─────────────────────────
class TestGeofenceCreate:
    def test_create_circle(self, admin_h):
        r = requests.post(f"{BASE_URL}/api/fleet-tracking/geofences", headers=admin_h,
                          json={"name": "TEST_circle_iter212", "kind": "circle",
                                "center_lat": -23.55, "center_lng": -46.63,
                                "radius_m": 250, "alert_on": "both"}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["kind"] == "circle"
        assert d["radius_m"] == 250
        pytest.gf_circle = d["id"]

    def test_create_polygon_needs_3(self, admin_h):
        # 2 pontos -> 400
        r = requests.post(f"{BASE_URL}/api/fleet-tracking/geofences", headers=admin_h,
                          json={"name": "TEST_bad_poly", "kind": "polygon",
                                "polygon": [[-23.5, -46.6], [-23.51, -46.61]]}, timeout=15)
        assert r.status_code == 400

    def test_create_polygon_ok(self, admin_h):
        r = requests.post(f"{BASE_URL}/api/fleet-tracking/geofences", headers=admin_h,
                          json={"name": "TEST_poly_iter212", "kind": "polygon",
                                "polygon": [[-23.5, -46.6], [-23.51, -46.61], [-23.52, -46.59]],
                                "alert_on": "entry"}, timeout=15)
        assert r.status_code == 200, r.text
        pytest.gf_poly = r.json()["id"]

    def test_cleanup_geofences(self, admin_h):
        for gid in [getattr(pytest, "gf_circle", None), getattr(pytest, "gf_poly", None)]:
            if gid:
                requests.delete(f"{BASE_URL}/api/fleet-tracking/geofences/{gid}", headers=admin_h)


# ── TTL index + orphan position ───────────────────────────────────────────
class TestTTLOrphan:
    def test_ingest_orphan_writes_dt(self):
        unknown_imei = f"UNK{uuid.uuid4().hex[:10]}"
        r = requests.post(f"{BASE_URL}/api/fleet-tracking/ingest",
                          headers={"Authorization": f"Bearer {INGEST_TOKEN}",
                                   "Content-Type": "application/json"},
                          json={"imei": unknown_imei, "lat": -23.5, "lng": -46.6,
                                "speed_kmh": 0}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is False
        pytest.unknown_imei = unknown_imei

    def test_orphan_doc_dt_is_bson_date(self):
        async def _check():
            cli = AsyncIOMotorClient(MONGO_URL)
            try:
                d = cli[DB_NAME]
                doc = await d.fleet_orphan_positions.find_one(
                    {"imei": pytest.unknown_imei}, {"_id": 0})
                assert doc is not None, "orphan doc não foi gravado"
                from datetime import datetime as _dt
                assert isinstance(doc.get("received_at_dt"), _dt), \
                    f"received_at_dt deve ser datetime BSON, got {type(doc.get('received_at_dt'))}"
                # listIndexes deve ter TTL
                idxs = await d.fleet_orphan_positions.index_information()
                ttl_ok = any(
                    info.get("expireAfterSeconds") == 2592000
                    and any(k[0] == "received_at_dt" for k in info.get("key", []))
                    for info in idxs.values()
                )
                assert ttl_ok, f"TTL index não encontrado. indexes={idxs}"
            finally:
                cli.close()
        asyncio.get_event_loop().run_until_complete(_check())


# ── Cleanup portal user no fim ────────────────────────────────────────────
def test_zz_cleanup_portal_user(admin_h):
    uid = getattr(pytest, "portal_uid", None)
    if uid:
        r = requests.delete(f"{BASE_URL}/api/fleet-tracking/portal-users/{uid}",
                            headers=admin_h, timeout=10)
        assert r.status_code in (200, 404)
