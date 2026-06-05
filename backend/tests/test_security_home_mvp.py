"""
Backend tests for SecurityHome MVP (Verisure-style alarm monitoring).
Covers admin CRUD (sites/tenants/sensors), arm/disarm, Contact ID ingest,
portal login & operations, tenant isolation, alarm ack.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
    "https://dual-combine-3.preview.emergentagent.com"

# Read ingest token from backend env directly (file is local to container)
def _read_env(key):
    try:
        with open("/app/backend/.env") as f:
            for line in f:
                if line.startswith(f"{key}="):
                    return line.strip().split("=", 1)[1]
    except Exception:
        return ""
    return ""

INGEST_TOKEN = _read_env("SECURITY_INGEST_TOKEN")

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASSWORD = "123456"
PORTAL_EMAIL = "cliente@casa.com"
PORTAL_PASSWORD = "123456"


# ────────────────────── fixtures ──────────────────────
@pytest.fixture(scope="module")
def admin_token():
    """Login as admin@empresa.com on main app."""
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=15)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    data = r.json()
    token = data.get("access_token") or data.get("token")
    assert token, f"No token in response: {data}"
    return token


@pytest.fixture(scope="module")
def admin_session(admin_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {admin_token}",
                      "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def portal_session():
    r = requests.post(f"{BASE_URL}/api/security-portal/auth/login",
                      json={"email": PORTAL_EMAIL, "password": PORTAL_PASSWORD},
                      timeout=15)
    assert r.status_code == 200, f"Portal login failed: {r.status_code} {r.text}"
    data = r.json()
    token = data.get("access_token")
    assert token
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}",
                      "Content-Type": "application/json"})
    s._login_data = data
    return s


# ────────────────────── Portal login ──────────────────────
class TestPortalAuth:
    def test_portal_login_success(self, portal_session):
        data = portal_session._login_data
        assert data.get("token_type") == "bearer"
        assert data["user"]["email"] == PORTAL_EMAIL
        # Verify token has security_portal type
        import jwt as _jwt
        payload = _jwt.decode(data["access_token"], options={"verify_signature": False})
        assert payload.get("type") == "security_portal"

    def test_portal_login_wrong_password(self):
        r = requests.post(f"{BASE_URL}/api/security-portal/auth/login",
                          json={"email": PORTAL_EMAIL, "password": "wrong"},
                          timeout=15)
        assert r.status_code == 401

    def test_portal_login_nonexistent_user(self):
        """cliente@teste.com exists in fleet portal but NOT security portal."""
        r = requests.post(f"{BASE_URL}/api/security-portal/auth/login",
                          json={"email": "cliente@teste.com",
                                "password": "123456"},
                          timeout=15)
        assert r.status_code == 401


# ────────────────────── Admin: sites ──────────────────────
class TestAdminSites:
    def test_list_sites(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/security-home/sites")
        assert r.status_code == 200
        sites = r.json()
        assert isinstance(sites, list)
        # Should have at least the seed test site
        assert any("Casa Principal" in (s.get("name") or "") for s in sites), \
            f"Seed site missing: {sites}"

    def test_create_update_delete_site(self, admin_session):
        # Create
        panel_id = f"99{int(time.time()) % 100}"
        payload = {
            "name": "TEST_SiteMVP",
            "address": "Rua Teste",
            "panel_id": panel_id,
            "panel_model": "Intelbras AMT 8000",
        }
        r = admin_session.post(f"{BASE_URL}/api/security-home/sites",
                               json=payload)
        assert r.status_code == 200, r.text
        site = r.json()
        assert site["name"] == "TEST_SiteMVP"
        assert site["panel_id"] == panel_id
        assert site["arm_state"] == "disarmed"
        sid = site["id"]

        # Update
        u = admin_session.put(f"{BASE_URL}/api/security-home/sites/{sid}",
                              json={**payload, "name": "TEST_SiteMVP_v2"})
        assert u.status_code == 200

        # Verify via list
        r2 = admin_session.get(f"{BASE_URL}/api/security-home/sites")
        assert any(s.get("id") == sid and s.get("name") == "TEST_SiteMVP_v2"
                   for s in r2.json())

        # Delete
        d = admin_session.delete(f"{BASE_URL}/api/security-home/sites/{sid}")
        assert d.status_code == 200


# ────────────────────── Admin: tenants ──────────────────────
class TestAdminTenants:
    def test_list_and_create_tenant(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/security-home/tenants")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

        c = admin_session.post(f"{BASE_URL}/api/security-home/tenants",
                               json={"name": "TEST_TenantSec",
                                     "monthly_fee": 99.9})
        assert c.status_code == 200
        t = c.json()
        assert t["name"] == "TEST_TenantSec"
        assert t["id"].startswith("st-")


# ────────────────────── Admin: sensors ──────────────────────
class TestSensorsAndArming:
    @pytest.fixture(scope="class")
    def seed_site_id(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/security-home/sites")
        for s in r.json():
            if "Casa Principal" in (s.get("name") or ""):
                return s["id"]
        pytest.skip("Seed site not found")

    def test_list_sensors(self, admin_session, seed_site_id):
        r = admin_session.get(
            f"{BASE_URL}/api/security-home/sites/{seed_site_id}/sensors")
        assert r.status_code == 200
        sensors = r.json()
        assert isinstance(sensors, list)
        assert len(sensors) >= 1, "Expected seed sensors"

    def test_create_and_delete_sensor(self, admin_session, seed_site_id):
        payload = {"label": "TEST_Sensor", "kind": "magnetic",
                   "contact_zone": 50, "plant_x": 0.3, "plant_y": 0.4}
        c = admin_session.post(
            f"{BASE_URL}/api/security-home/sites/{seed_site_id}/sensors",
            json=payload)
        assert c.status_code == 200
        sensor = c.json()
        assert sensor["label"] == "TEST_Sensor"
        sensor_id = sensor["id"]

        d = admin_session.delete(
            f"{BASE_URL}/api/security-home/sensors/{sensor_id}")
        assert d.status_code == 200

    def test_admin_arm_disarm_persists(self, admin_session, seed_site_id):
        # Arm away
        r = admin_session.post(
            f"{BASE_URL}/api/security-home/sites/{seed_site_id}/arm?mode=away")
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "armed_away"

        # Verify persisted
        sites = admin_session.get(
            f"{BASE_URL}/api/security-home/sites").json()
        site = next(s for s in sites if s["id"] == seed_site_id)
        assert site["arm_state"] == "armed_away"

        # Disarm
        d = admin_session.post(
            f"{BASE_URL}/api/security-home/sites/{seed_site_id}/disarm")
        assert d.status_code == 200
        assert d.json()["state"] == "disarmed"


# ────────────────────── Contact ID ingest ──────────────────────
class TestContactIdIngest:
    @pytest.fixture(scope="class")
    def panel_id(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/security-home/sites")
        for s in r.json():
            if "Casa Principal" in (s.get("name") or ""):
                return s["panel_id"]
        pytest.skip("Seed site not found")

    def test_ingest_no_token_rejected(self, panel_id):
        if not INGEST_TOKEN:
            pytest.skip("No ingest token configured — bypass active")
        r = requests.post(f"{BASE_URL}/api/security-home/ingest",
                          json={"panel_id": panel_id, "event_code": 130,
                                "zone": 1, "qualifier": 1},
                          timeout=15)
        assert r.status_code == 401

    def test_ingest_wrong_token_rejected(self, panel_id):
        if not INGEST_TOKEN:
            pytest.skip("No ingest token configured")
        r = requests.post(f"{BASE_URL}/api/security-home/ingest",
                          headers={"Authorization": "Bearer WRONG"},
                          json={"panel_id": panel_id, "event_code": 130,
                                "zone": 1, "qualifier": 1},
                          timeout=15)
        assert r.status_code == 401

    def test_ingest_burglary_creates_alarm_and_triggers_sensor(
            self, admin_session, panel_id):
        r = requests.post(
            f"{BASE_URL}/api/security-home/ingest",
            headers={"Authorization": f"Bearer {INGEST_TOKEN}"},
            json={"panel_id": panel_id, "event_code": 130,
                  "zone": 1, "qualifier": 1, "partition": 1},
            timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert "alarm_id" in body

        # Alarm appears in list
        time.sleep(0.5)
        alarms = admin_session.get(
            f"{BASE_URL}/api/security-home/alarms?acked=false").json()
        assert any(a["id"] == body["alarm_id"] for a in alarms)
        new_alarm = next(a for a in alarms if a["id"] == body["alarm_id"])
        assert new_alarm["event_code"] == 130
        assert new_alarm["kind"] == "burglary"

        # Sensor zone 1 must be triggered
        sites = admin_session.get(
            f"{BASE_URL}/api/security-home/sites").json()
        seed = next(s for s in sites if s["panel_id"] == panel_id)
        sensors = admin_session.get(
            f"{BASE_URL}/api/security-home/sites/{seed['id']}/sensors").json()
        z1 = next((s for s in sensors if s.get("contact_zone") == 1), None)
        assert z1 is not None
        assert z1["state"] == "triggered", f"sensor state={z1.get('state')}"

        # Ack the alarm
        ack = admin_session.post(
            f"{BASE_URL}/api/security-home/alarms/{body['alarm_id']}"
            f"/ack?resolution=verificado")
        assert ack.status_code == 200

    def test_ingest_disarm_updates_arm_state(self, admin_session, panel_id):
        r = requests.post(
            f"{BASE_URL}/api/security-home/ingest",
            headers={"Authorization": f"Bearer {INGEST_TOKEN}"},
            json={"panel_id": panel_id, "event_code": 402,
                  "zone": 0, "qualifier": 1},
            timeout=15)
        assert r.status_code == 200
        # Site arm_state == disarmed
        sites = admin_session.get(
            f"{BASE_URL}/api/security-home/sites").json()
        seed = next(s for s in sites if s["panel_id"] == panel_id)
        assert seed["arm_state"] == "disarmed"


# ────────────────────── Portal endpoints ──────────────────────
class TestPortalOperations:
    def test_portal_me(self, portal_session):
        r = portal_session.get(f"{BASE_URL}/api/security-portal/me")
        assert r.status_code == 200
        data = r.json()
        assert data["user"]["email"] == PORTAL_EMAIL
        assert data.get("tenant") is not None

    def test_portal_sites(self, portal_session):
        r = portal_session.get(f"{BASE_URL}/api/security-portal/sites")
        assert r.status_code == 200
        sites = r.json()
        assert isinstance(sites, list) and len(sites) >= 1
        assert any("Casa Principal" in (s.get("name") or "") for s in sites)

    def test_portal_sensors_arm_disarm_panic(self, portal_session):
        sites = portal_session.get(
            f"{BASE_URL}/api/security-portal/sites").json()
        sid = sites[0]["id"]

        # Sensors
        s = portal_session.get(
            f"{BASE_URL}/api/security-portal/sites/{sid}/sensors")
        assert s.status_code == 200
        assert isinstance(s.json(), list)

        # Arm away
        a = portal_session.post(
            f"{BASE_URL}/api/security-portal/sites/{sid}/arm?mode=away")
        assert a.status_code == 200
        assert a.json()["state"] == "armed_away"

        # Disarm
        d = portal_session.post(
            f"{BASE_URL}/api/security-portal/sites/{sid}/disarm")
        assert d.status_code == 200
        assert d.json()["state"] == "disarmed"

        # Panic
        p = portal_session.post(
            f"{BASE_URL}/api/security-portal/sites/{sid}/panic")
        assert p.status_code == 200
        alarm_id = p.json()["alarm_id"]

        # Verify alarm origin=portal in list
        time.sleep(0.5)
        alarms = portal_session.get(
            f"{BASE_URL}/api/security-portal/alarms").json()
        alm = next((a for a in alarms if a["id"] == alarm_id), None)
        assert alm is not None
        assert alm.get("origin") == "portal"
        assert alm["severity"] == "critical"

    def test_portal_no_token_unauthorized(self):
        r = requests.get(f"{BASE_URL}/api/security-portal/sites", timeout=15)
        assert r.status_code == 401


# ────────────────────── Portal user CRUD ──────────────────────
class TestPortalUserMgmt:
    def test_list_create_delete_portal_user(self, admin_session):
        # Find seed tenant
        tenants = admin_session.get(
            f"{BASE_URL}/api/security-home/tenants").json()
        seed_tenant = next((t for t in tenants
                            if "Residencial" in (t.get("name") or "")),
                           tenants[0] if tenants else None)
        if not seed_tenant:
            pytest.skip("No tenant available")
        tid = seed_tenant["id"]

        # List existing
        r = admin_session.get(
            f"{BASE_URL}/api/security-home/tenants/{tid}/portal-users")
        assert r.status_code == 200

        # Create
        email = f"test_{int(time.time())}@casa.com"
        c = admin_session.post(
            f"{BASE_URL}/api/security-home/tenants/{tid}/portal-users",
            json={"email": email, "password": "abc123", "name": "TEST User"})
        assert c.status_code == 200, c.text
        uid = c.json()["id"]
        assert uid.startswith("spu-")

        # New user can login
        login = requests.post(
            f"{BASE_URL}/api/security-portal/auth/login",
            json={"email": email, "password": "abc123"}, timeout=15)
        assert login.status_code == 200

        # Delete
        d = admin_session.delete(
            f"{BASE_URL}/api/security-home/portal-users/{uid}")
        assert d.status_code == 200
