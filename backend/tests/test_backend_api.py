import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _test_secrets import TEST_ADMIN_PASSWORD, TEST_AUDITOR_PASSWORD  # noqa: E402
"""End-to-end backend tests for Ponto do Colaborador app.

Covers: health, collaborators CRUD, geofences, clock-records with face validation,
timesheets, settings, scheduler, admin auth.
"""
import time
import uuid
import pytest


# ---------- Health ----------
class TestHealth:
    def test_root_health(self, api, base_url):
        r = api.get(f"{base_url}/api/")
        assert r.status_code == 200
        data = r.json()
        assert data.get("ok") is True
        assert data.get("service")


# ---------- Admin auth ----------
class TestAdminAuth:
    def test_admin_login_success(self, api, base_url):
        r = api.post(f"{base_url}/api/auth/admin-login", json={"password": TEST_ADMIN_PASSWORD})
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_admin_login_wrong_password(self, api, base_url):
        r = api.post(f"{base_url}/api/auth/admin-login", json={"password": "wrong"})
        assert r.status_code == 401


# ---------- Settings ----------
class TestSettings:
    def test_get_settings_initial(self, api, base_url):
        r = api.get(f"{base_url}/api/settings")
        assert r.status_code == 200
        data = r.json()
        assert "resend_api_key_set" in data
        assert data.get("emergent_key_available") is True
        # Initially key is empty -> not set
        assert data.get("resend_api_key_set") is False

    def test_update_settings_set_resend_key(self, api, base_url):
        r = api.put(f"{base_url}/api/settings", json={"resend_api_key": "re_TESTE123"})
        assert r.status_code == 200
        # confirm via GET
        r2 = api.get(f"{base_url}/api/settings")
        assert r2.status_code == 200
        d = r2.json()
        assert d.get("resend_api_key_set") is True
        # masked
        assert d.get("resend_api_key", "").endswith("...")

    def test_update_settings_clear_via_empty_string(self, api, base_url):
        # Backend filters None values; empty string check the documented behavior
        r = api.put(f"{base_url}/api/settings", json={"resend_api_key": ""})
        assert r.status_code == 200
        # After empty string update, behaviour: empty string is not None, so saved
        r2 = api.get(f"{base_url}/api/settings")
        d = r2.json()
        # Document the actual outcome - empty string treated as falsy by bool()
        assert d.get("resend_api_key_set") is False


# ---------- Collaborators ----------
@pytest.fixture(scope="module")
def created_collab(api, base_url):
    cpf = f"TEST{uuid.uuid4().hex[:9]}"
    payload = {
        "name": "TEST_Maria Silva",
        "cpf": cpf,
        "email": f"test_{uuid.uuid4().hex[:6]}@example.com",
        "phone": "+55 11 98888-1234",
        "role": "Colaborador de Campo",
        "company": "Operação SP",
        "schedule": {
            "entrada": "08:00",
            "inicio_intervalo": "12:00",
            "fim_intervalo": "13:00",
            "saida": "17:00",
        },
    }
    r = api.post(f"{base_url}/api/collaborators", json=payload)
    assert r.status_code == 200, r.text
    coll = r.json()
    yield coll
    # teardown
    api.delete(f"{base_url}/api/collaborators/{coll['id']}")


class TestCollaborators:
    def test_list_has_seed(self, api, base_url):
        r = api.get(f"{base_url}/api/collaborators")
        assert r.status_code == 200
        items = r.json()
        ids = [c.get("id") for c in items]
        assert "col-demo-001" in ids
        seed = next(c for c in items if c["id"] == "col-demo-001")
        assert seed["name"] == "Carlos Almeida"

    def test_create_collaborator(self, created_collab):
        assert created_collab["id"].startswith("col-")
        assert created_collab["name"] == "TEST_Maria Silva"
        assert "schedule" in created_collab

    def test_get_collaborator(self, api, base_url, created_collab):
        r = api.get(f"{base_url}/api/collaborators/{created_collab['id']}")
        assert r.status_code == 200
        assert r.json()["cpf"] == created_collab["cpf"]

    def test_create_duplicate_cpf(self, api, base_url, created_collab):
        payload = {
            "name": "TEST_Dup",
            "cpf": created_collab["cpf"],
            "email": f"dup_{uuid.uuid4().hex[:6]}@example.com",
            "phone": "+55 11 98888-9999",
        }
        r = api.post(f"{base_url}/api/collaborators", json=payload)
        assert r.status_code == 400

    def test_update_collaborator(self, api, base_url, created_collab):
        new_payload = {
            "name": "TEST_Maria Silva Updated",
            "cpf": created_collab["cpf"],
            "email": created_collab["email"],
            "phone": "+55 11 97777-1111",
            "role": "Gestor",
            "company": "Operação SP",
            "schedule": created_collab["schedule"],
        }
        r = api.put(f"{base_url}/api/collaborators/{created_collab['id']}", json=new_payload)
        assert r.status_code == 200
        assert r.json()["name"] == "TEST_Maria Silva Updated"
        assert r.json()["role"] == "Gestor"


# ---------- Geocoding & Geofences ----------
class TestGeocoding:
    def test_geocode_endpoint(self, api, base_url):
        r = api.get(f"{base_url}/api/geocode", params={"address": "Av. Paulista, 1000, São Paulo, SP"})
        # Nominatim sometimes flaky; allow 200 or 400
        assert r.status_code in (200, 400)
        if r.status_code == 200:
            d = r.json()
            assert "lat" in d and "lng" in d
            assert -25 < d["lat"] < -20  # São Paulo region


@pytest.fixture(scope="module")
def created_geofence(api, base_url, created_collab):
    payload = {
        "name": "TEST_Loja Paulista",
        "type": "Loja",
        "address": "Av. Paulista, 1000, São Paulo, SP",
        "radius": 15.0,
    }
    r = api.post(f"{base_url}/api/collaborators/{created_collab['id']}/geofences", json=payload)
    if r.status_code != 200:
        pytest.skip(f"geocoding failed: {r.status_code} {r.text}")
    yield r.json()


class TestGeofences:
    def test_create_geofence(self, created_geofence):
        assert created_geofence["id"].startswith("geo-")
        assert created_geofence["radius"] == 15.0
        assert "lat" in created_geofence and "lng" in created_geofence

    def test_list_geofences(self, api, base_url, created_collab, created_geofence):
        r = api.get(f"{base_url}/api/collaborators/{created_collab['id']}/geofences")
        assert r.status_code == 200
        ids = [g["id"] for g in r.json()]
        assert created_geofence["id"] in ids

    def test_delete_geofence_deactivates(self, api, base_url, created_collab):
        # create a separate fence to delete
        r = api.post(
            f"{base_url}/api/collaborators/{created_collab['id']}/geofences",
            json={"name": "TEST_DeleteMe", "type": "Base", "address": "Praça da Sé, São Paulo", "radius": 15.0},
        )
        if r.status_code != 200:
            pytest.skip("geocoding flaky")
        gid = r.json()["id"]
        rd = api.delete(f"{base_url}/api/geofences/{gid}")
        assert rd.status_code == 200
        # confirm not listed in active
        rl = api.get(f"{base_url}/api/collaborators/{created_collab['id']}/geofences")
        assert gid not in [g["id"] for g in rl.json()]


# ---------- Today endpoint ----------
class TestToday:
    def test_today_initial(self, api, base_url, created_collab):
        r = api.get(f"{base_url}/api/collaborators/{created_collab['id']}/today")
        assert r.status_code == 200
        d = r.json()
        assert "date" in d
        assert d["next_expected"] == "Entrada"
        assert isinstance(d["records"], list)


# ---------- Clock records (face validation via real GPT-4o) ----------
@pytest.fixture(scope="module")
def clock_record_blocked(api, base_url, created_collab, landscape_image_b64):
    """Submit a real (non-face) JPEG; expect blocked with face_detected=false."""
    payload = {
        "collaborator_id": created_collab["id"],
        "type": "Entrada",
        "selfie_base64": landscape_image_b64,
        "lat": -23.5613,
        "lng": -46.6562,
    }
    r = api.post(f"{base_url}/api/clock-records", json=payload, timeout=120)
    assert r.status_code == 200, r.text
    return r.json()


class TestClockRecords:
    def test_create_record_blocked_no_face(self, clock_record_blocked):
        rec = clock_record_blocked
        assert rec["status"] == "Bloqueado"
        assert "Não conseguimos validar seu rosto" in rec["public_block_message"]
        assert rec["internal_block_reason"]
        assert rec["face_validation"].get("face_detected") is False

    def test_list_records_filter_by_collaborator(self, api, base_url, created_collab, clock_record_blocked):
        r = api.get(f"{base_url}/api/clock-records", params={"collaborator_id": created_collab["id"]})
        assert r.status_code == 200
        ids = [x["id"] for x in r.json()]
        assert clock_record_blocked["id"] in ids

    def test_list_records_filter_by_status(self, api, base_url, clock_record_blocked):
        r = api.get(f"{base_url}/api/clock-records", params={"status": "Bloqueado"})
        assert r.status_code == 200
        statuses = {x["status"] for x in r.json()}
        assert statuses == {"Bloqueado"} or "Bloqueado" in statuses

    def test_get_record_by_id(self, api, base_url, clock_record_blocked):
        r = api.get(f"{base_url}/api/clock-records/{clock_record_blocked['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == clock_record_blocked["id"]

    def test_approve_record(self, api, base_url, clock_record_blocked):
        r = api.post(f"{base_url}/api/clock-records/{clock_record_blocked['id']}/approve")
        assert r.status_code == 200
        assert r.json()["status"] == "Válido"

    def test_reject_record(self, api, base_url, clock_record_blocked):
        r = api.post(f"{base_url}/api/clock-records/{clock_record_blocked['id']}/reject")
        assert r.status_code == 200
        assert r.json()["status"] == "Recusado"


# ---------- Timesheet ----------
class TestTimesheet:
    def test_timesheet_structure(self, api, base_url, created_collab):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        r = api.get(f"{base_url}/api/timesheets/{created_collab['id']}/{now.year}/{now.month}")
        assert r.status_code == 200
        d = r.json()
        assert "days" in d
        assert "total_worked_min" in d
        assert "total_balance_min" in d
        assert d["collaborator"]["id"] == created_collab["id"]


# ---------- Email send & scheduler ----------
class TestEmailScheduler:
    def test_send_timesheet_no_key(self, api, base_url, created_collab):
        # Ensure key is cleared first
        api.put(f"{base_url}/api/settings", json={"resend_api_key": ""})
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        r = api.post(f"{base_url}/api/timesheets/send/{created_collab['id']}", params={"year": now.year, "month": now.month})
        assert r.status_code == 200
        d = r.json()
        assert d.get("sent") is False
        assert "Resend" in d.get("reason", "") or "key" in d.get("reason", "").lower()

    def test_run_monthly_now(self, api, base_url):
        r = api.post(f"{base_url}/api/scheduler/run-monthly-now")
        assert r.status_code == 200
        assert r.json().get("ok") is True
