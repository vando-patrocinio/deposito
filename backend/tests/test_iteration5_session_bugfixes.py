"""Session bugfixes on top of iteration 5:
- Field(ge=1, le=86400) on settings.time_sync_max_drift_seconds (422 on invalid)
- Drift validation skip ONLY for admin token (not is_test_mode)
- PATCH /api/lousa/tickets/{id} clears grid_slot when scheduled_time changes
"""
import os
import time
import uuid
import requests
import pytest

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, r.text
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@empresa.com', '123456')}"}


@pytest.fixture(scope="module")
def gestor_headers():
    return {"Authorization": f"Bearer {_login('gestor@empresa.com', '123456')}"}


@pytest.fixture(scope="module", autouse=True)
def restore_settings(admin_headers):
    # Save current settings so we restore after tests
    r = requests.get(f"{API}/settings", headers=admin_headers, timeout=20)
    assert r.status_code == 200, r.text
    original = r.json()
    yield
    body = {
        "time_sync_enabled": False,
        "time_sync_max_drift_seconds": int(original.get("time_sync_max_drift_seconds", 60) or 60),
    }
    requests.put(f"{API}/settings", headers=admin_headers, json=body, timeout=20)


# ---------- (a) Field(ge=1, le=86400) ----------
class TestTimeSyncMaxDriftValidation:
    def test_zero_rejected_422(self, admin_headers):
        r = requests.put(f"{API}/settings", headers=admin_headers,
                         json={"time_sync_max_drift_seconds": 0}, timeout=20)
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"

    def test_negative_rejected_422(self, admin_headers):
        r = requests.put(f"{API}/settings", headers=admin_headers,
                         json={"time_sync_max_drift_seconds": -10}, timeout=20)
        assert r.status_code == 422, r.text

    def test_too_large_rejected_422(self, admin_headers):
        r = requests.put(f"{API}/settings", headers=admin_headers,
                         json={"time_sync_max_drift_seconds": 100000}, timeout=20)
        assert r.status_code == 422, r.text

    def test_valid_accepted(self, admin_headers):
        r = requests.put(f"{API}/settings", headers=admin_headers,
                         json={"time_sync_max_drift_seconds": 30}, timeout=20)
        assert r.status_code == 200, r.text


# ---------- (b) drift skip ONLY for admin/auditor token ----------
class TestDriftSkipOnlyForAdmin:
    @pytest.fixture(scope="class")
    def test_collab(self, gestor_headers):
        # Create a collaborator with is_test_mode=true
        cpf = f"999{uuid.uuid4().int % 10**8:08d}"
        body = {
            "name": f"TEST_I5SBF_{uuid.uuid4().hex[:6]}",
            "cpf": cpf,
            "email": f"test_i5sbf_{uuid.uuid4().hex[:6]}@example.com",
            "phone": "11900000000",
            "is_test_mode": True,
        }
        r = requests.post(f"{API}/collaborators", headers=gestor_headers, json=body, timeout=20)
        assert r.status_code == 200, r.text
        cid = r.json()["id"]
        yield cid
        requests.delete(f"{API}/collaborators/{cid}", headers=gestor_headers, timeout=20)

    @pytest.fixture(autouse=True)
    def _enable_sync(self, admin_headers):
        # enable time sync with small drift threshold
        r = requests.put(f"{API}/settings", headers=admin_headers,
                         json={"time_sync_enabled": True,
                               "time_sync_max_drift_seconds": 30}, timeout=20)
        assert r.status_code == 200, r.text
        yield
        requests.put(f"{API}/settings", headers=admin_headers,
                     json={"time_sync_enabled": False}, timeout=20)

    def test_collab_test_mode_no_admin_token_blocked_412(self, test_collab):
        """is_test_mode collaborator without admin Bearer => drift validated => 412."""
        bad_client_ms = int(time.time() * 1000) - 3600 * 1000  # 1h atrás
        body = {
            "collaborator_id": test_collab,
            "type": "Entrada",
            "selfie_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgAAIAAAUAAen63NgAAAAASUVORK5CYII=",
            "lat": -23.5505, "lng": -46.6333,
            "client_time_ms": bad_client_ms,
        }
        # NO Authorization header
        r = requests.post(f"{API}/clock-records", json=body, timeout=30)
        assert r.status_code == 412, f"expected 412, got {r.status_code}: {r.text}"
        assert "dessincronizado" in r.text.lower() or "sincroniz" in r.text.lower()

    def test_admin_token_skips_drift(self, test_collab, admin_headers):
        """Same dessync, but with admin Bearer token => drift validation skipped."""
        bad_client_ms = int(time.time() * 1000) - 3600 * 1000
        body = {
            "collaborator_id": test_collab,
            "type": "Entrada",
            "selfie_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgAAIAAAUAAen63NgAAAAASUVORK5CYII=",
            "lat": -23.5505, "lng": -46.6333,
            "client_time_ms": bad_client_ms,
        }
        r = requests.post(f"{API}/clock-records", headers=admin_headers, json=body, timeout=30)
        # Should NOT be 412; admin test mode bypasses face/geo too -> 200
        assert r.status_code != 412, f"admin token should bypass drift: {r.text}"
        assert r.status_code == 200, r.text


# ---------- (c) PATCH clears grid_slot on scheduled_time change ----------
class TestPatchClearsGridSlot:
    @pytest.fixture(scope="class")
    def collab_id(self):
        # Use existing demo collaborator
        r = requests.get(f"{API}/collaborators", timeout=20)
        assert r.status_code == 200, r.text
        for c in r.json():
            if c.get("id", "").startswith("col-demo"):
                return c["id"]
        return r.json()[0]["id"]

    def test_patch_scheduled_time_clears_grid_slot(self, gestor_headers, collab_id):
        # 1. create ticket with scheduled_time at 09:00
        r = requests.post(f"{API}/lousa/tickets", headers=gestor_headers, json={
            "client_name": f"TEST_I5SBF_{uuid.uuid4().hex[:6]}",
            "address": "Rua A 1", "neighborhood": "X", "phone": "1199",
            "type": "reparo", "priority": "normal",
            "scheduled_time": "2026-01-15T09:30:00",
            "assigned_collaborator_id": collab_id,
        }, timeout=30)
        assert r.status_code == 200, r.text
        ticket_id = r.json()["id"]
        try:
            # 2. transfer set new_grid_slot = "09:00" -> persists grid_slot
            r2 = requests.post(f"{API}/lousa/tickets/{ticket_id}/transfer",
                               headers=gestor_headers,
                               json={"new_grid_slot": "09:00"}, timeout=20)
            assert r2.status_code == 200, r2.text
            assert r2.json().get("grid_slot") == "09:00"

            # 3. PATCH scheduled_time to 14:00 -> grid_slot must be cleared (None)
            r3 = requests.patch(f"{API}/lousa/tickets/{ticket_id}",
                                headers=gestor_headers,
                                json={"scheduled_time": "2026-01-15T14:30:00"}, timeout=20)
            assert r3.status_code == 200, r3.text
            assert r3.json().get("grid_slot") is None, f"grid_slot should be cleared: {r3.json()}"

            # 4. GET grid -> ticket should now be in 14:00 slot (recomputed)
            rg = requests.get(f"{API}/lousa/grid", headers=gestor_headers, timeout=20)
            assert rg.status_code == 200, rg.text
            found_slot = None
            for col in rg.json()["columns"]:
                for tk in col["tickets"]:
                    if tk["id"] == ticket_id:
                        found_slot = tk.get("grid_slot")
                        break
            assert found_slot == "14:00", f"Expected slot 14:00 after PATCH, got {found_slot}"
        finally:
            requests.delete(f"{API}/lousa/tickets/{ticket_id}", headers=gestor_headers, timeout=20)


# ---------- (d) _sla_minutes_for_type defaults for new types ----------
class TestSlaDefaultsNewTypes:
    @pytest.fixture(scope="class")
    def collab_id(self):
        r = requests.get(f"{API}/collaborators", timeout=20)
        for c in r.json():
            if c.get("id", "").startswith("col-demo"):
                return c["id"]
        return r.json()[0]["id"]

    @pytest.fixture(autouse=True)
    def _reset_sla_settings(self, admin_headers):
        # ensure no override present
        requests.put(f"{API}/settings", headers=admin_headers, json={
            "sla_prioridade_minutes": 45,
            "sla_preventiva_minutes": 90,
            "sla_venda_minutes": 60,
        }, timeout=20)
        yield

    @pytest.mark.parametrize("ttype,expected", [
        ("prioridade", 45), ("preventiva", 90), ("venda", 60),
    ])
    def test_sla_defaults_via_grid(self, gestor_headers, collab_id, ttype, expected):
        # create ticket of given type and admin-open to set status=aberta so SLA computed
        rc = requests.post(f"{API}/lousa/tickets", headers=gestor_headers, json={
            "client_name": f"TEST_I5SBF_{ttype}_{uuid.uuid4().hex[:6]}",
            "address": "Rua B 2", "neighborhood": "Y", "phone": "1199",
            "type": ttype, "priority": "normal",
            "assigned_collaborator_id": collab_id,
        }, timeout=30)
        assert rc.status_code == 200, rc.text
        tid = rc.json()["id"]
        try:
            ro = requests.post(f"{API}/lousa/tickets/{tid}/admin-open", headers=gestor_headers, timeout=20)
            assert ro.status_code == 200, ro.text

            rg = requests.get(f"{API}/lousa/grid", headers=gestor_headers, timeout=20)
            assert rg.status_code == 200, rg.text
            found_sla = None
            for col in rg.json()["columns"]:
                for tk in col["tickets"]:
                    if tk["id"] == tid:
                        found_sla = tk.get("sla", {}).get("sla_minutes")
                        break
            assert found_sla == expected, f"expected {expected}min for type={ttype}, got {found_sla}"
        finally:
            requests.delete(f"{API}/lousa/tickets/{tid}", headers=gestor_headers, timeout=20)


# ---------- (e) GET /api/server-time public ----------
class TestServerTime:
    def test_server_time_public(self):
        r = requests.get(f"{API}/server-time", timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("iso", "epoch_ms", "epoch_s", "tz", "sync_enabled", "max_drift_seconds"):
            assert k in d, f"missing key {k}"
        assert isinstance(d["epoch_ms"], int)
