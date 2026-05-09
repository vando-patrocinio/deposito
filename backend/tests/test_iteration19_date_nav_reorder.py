"""Iteration 19 — Inline Date Navigator (admin) + Public mobile reorder."""
import os
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")

ADMIN_CRED = {"email": "admin@empresa.com", "password": "123456"}
COL_ID = "col-demo-001"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN_CRED, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---- GRID: date navigator behaviour --------------------------------------
class TestGridDateNavigator:
    def test_grid_default_no_historical_flag(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/lousa/grid", headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("historical") in (False, None)
        # tickets in active mode should NOT have historical=True
        for col in data.get("columns", []):
            for t in col.get("tickets", []):
                assert t.get("historical") is not True

    def test_grid_with_date_range_returns_historical_flags(self, admin_headers):
        # use a past date range guaranteed not today
        params = {"date_from": "2024-01-01", "date_to": "2024-01-31"}
        r = requests.get(f"{BASE_URL}/api/lousa/grid", headers=admin_headers,
                         params=params, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("historical") is True
        assert data.get("date_from") == params["date_from"]
        assert data.get("date_to") == params["date_to"]
        # All returned tickets in historical mode must have locked=True and historical=True
        for col in data.get("columns", []):
            for t in col.get("tickets", []):
                assert t.get("locked") is True, f"ticket {t.get('id')} not locked in historical"
                assert t.get("historical") is True, f"ticket {t.get('id')} no historical flag"

    def test_grid_with_only_date_from(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/lousa/grid",
                         headers=admin_headers,
                         params={"date_from": "2024-06-01"}, timeout=20)
        assert r.status_code == 200
        assert r.json().get("historical") is True


# ---- PUBLIC REORDER -------------------------------------------------------
@pytest.fixture(scope="module")
def seed_normal_tickets(admin_headers):
    """Ensure colaborador has at least 3 normal tickets to reorder."""
    # check current normal active tickets
    r = requests.get(f"{BASE_URL}/api/lousa/by-collaborator/{COL_ID}", timeout=15)
    assert r.status_code == 200
    data = r.json()
    tickets = [t for t in data.get("tickets", []) if t.get("priority") == "normal"]

    created_ids = []
    needed = max(0, 3 - len(tickets))
    for i in range(needed):
        payload = {
            "client_name": f"TEST_REORDER_{uuid.uuid4().hex[:6]}",
            "address": "Rua Demo, 100",
            "neighborhood": "Centro",
            "phone": "11999999999",
            "relato": "Teste reorder",
            "type": "reparo",
            "priority": "normal",
            "assigned_collaborator_id": COL_ID,
        }
        rc = requests.post(f"{BASE_URL}/api/lousa/tickets", headers=admin_headers,
                           json=payload, timeout=15)
        assert rc.status_code in (200, 201), rc.text
        created_ids.append(rc.json()["id"])

    # Re-fetch
    r = requests.get(f"{BASE_URL}/api/lousa/by-collaborator/{COL_ID}", timeout=15)
    data = r.json()
    yield data.get("tickets", [])

    # cleanup
    for tid in created_ids:
        requests.delete(f"{BASE_URL}/api/lousa/tickets/{tid}", headers=admin_headers, timeout=10)


class TestPublicReorder:
    def test_reorder_404_for_unknown_collaborator(self):
        r = requests.post(f"{BASE_URL}/api/lousa/public/reorder",
                          json={"collaborator_id": "col-does-not-exist", "items": []},
                          timeout=10)
        assert r.status_code == 404

    def test_reorder_400_for_ticket_not_belonging(self, seed_normal_tickets):
        r = requests.post(f"{BASE_URL}/api/lousa/public/reorder",
                          json={"collaborator_id": COL_ID,
                                "items": [{"id": "tkt-doesnotexist123", "position": 0}]},
                          timeout=10)
        assert r.status_code == 400, r.text

    def test_reorder_normal_tickets_swap_positions(self, seed_normal_tickets):
        normals = [t for t in seed_normal_tickets if t.get("priority") == "normal"]
        if len(normals) < 2:
            pytest.skip("Need at least 2 normal tickets")
        a, b = normals[0], normals[1]
        # swap
        items = [
            {"id": a["id"], "position": b["position"]},
            {"id": b["id"], "position": a["position"]},
        ]
        r = requests.post(f"{BASE_URL}/api/lousa/public/reorder",
                          json={"collaborator_id": COL_ID, "items": items}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        # idempotent - call same again
        r2 = requests.post(f"{BASE_URL}/api/lousa/public/reorder",
                           json={"collaborator_id": COL_ID, "items": items}, timeout=15)
        assert r2.status_code == 200
        assert r2.json().get("ok") is True

    def test_reorder_locked_priority_rejected(self, admin_headers, seed_normal_tickets):
        # Create a 'horario' priority ticket
        payload = {
            "client_name": f"TEST_LOCK_{uuid.uuid4().hex[:6]}",
            "address": "Rua Lock, 1",
            "neighborhood": "Centro",
            "phone": "11900000000",
            "relato": "lock",
            "type": "reparo",
            "priority": "horario",
            "scheduled_time": "2030-01-01T10:00:00",
            "assigned_collaborator_id": COL_ID,
        }
        rc = requests.post(f"{BASE_URL}/api/lousa/tickets",
                           headers=admin_headers, json=payload, timeout=15)
        assert rc.status_code in (200, 201), rc.text
        locked_id = rc.json()["id"]
        try:
            # Attempt to move the locked one (position=99 is definitely different)
            r = requests.post(f"{BASE_URL}/api/lousa/public/reorder",
                              json={"collaborator_id": COL_ID,
                                    "items": [{"id": locked_id, "position": 99}]},
                              timeout=10)
            assert r.status_code == 400, r.text
        finally:
            requests.delete(f"{BASE_URL}/api/lousa/tickets/{locked_id}",
                            headers=admin_headers, timeout=10)


# ---- REGRESSION ----------------------------------------------------------
class TestRegression:
    def test_grid(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/lousa/grid", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert "columns" in r.json()

    def test_by_collaborator(self):
        r = requests.get(f"{BASE_URL}/api/lousa/by-collaborator/{COL_ID}", timeout=15)
        assert r.status_code == 200
        assert "tickets" in r.json()

    def test_ai_rankings(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/lousa/ai-rankings", headers=admin_headers, timeout=20)
        assert r.status_code == 200

    def test_briefing(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/lousa/briefing", headers=admin_headers, timeout=30)
        assert r.status_code in (200, 503)  # may fail if LLM disabled

    def test_atlaz_settings(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_bulk_action_endpoint_exists(self, admin_headers):
        # call with empty payload - should return 400 or 422 (not 404/500)
        r = requests.post(f"{BASE_URL}/api/lousa/tickets/bulk-action",
                          headers=admin_headers, json={}, timeout=10)
        assert r.status_code in (400, 422), f"unexpected {r.status_code}: {r.text}"
