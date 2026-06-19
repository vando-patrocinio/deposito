import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _test_secrets import TEST_ADMIN_PASSWORD, TEST_AUDITOR_PASSWORD  # noqa: E402
"""Iteration 11 — Tests for Praças CRUD + praca_id on collaborators + holidays_extra in timesheet."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://selfie-attendance-7.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


# ----- auth helpers -----
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": "admin@example.com", "password": TEST_ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ----- Praças CRUD -----
class TestPracasCrud:
    def test_list_pracas_public(self):
        r = requests.get(f"{API}/pracas")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_praca_requires_auth(self):
        r = requests.post(f"{API}/pracas", json={
            "name": "TEST_noauth", "city": "X", "state": "RJ", "holidays_extra": []
        })
        assert r.status_code in (401, 403)

    def test_create_update_delete_praca(self, admin_headers):
        # CREATE
        payload = {
            "name": "TEST_Praca_Iter11",
            "city": "Niterói",
            "state": "rj",
            "holidays_extra": [
                {"date": "2026-04-10", "name": "Aniversário Teste", "scope": "municipal"}
            ],
        }
        r = requests.post(f"{API}/pracas", json=payload, headers=admin_headers)
        assert r.status_code == 200, r.text
        created = r.json()
        assert created["name"] == "TEST_Praca_Iter11"
        assert created["city"] == "Niterói"
        assert created["state"] == "RJ"  # upper
        assert len(created["holidays_extra"]) == 1
        assert created["holidays_extra"][0]["scope"] == "municipal"
        pid = created["id"]

        # verify in list
        r = requests.get(f"{API}/pracas")
        ids = [p["id"] for p in r.json()]
        assert pid in ids

        # UPDATE
        payload2 = {
            "name": "TEST_Praca_Iter11_Upd",
            "city": "São Gonçalo",
            "state": "RJ",
            "holidays_extra": [
                {"date": "2026-04-10", "name": "Aniv Upd", "scope": "municipal"},
                {"date": "2026-05-20", "name": "Dia Estadual", "scope": "estadual"},
            ],
        }
        r = requests.put(f"{API}/pracas/{pid}", json=payload2, headers=admin_headers)
        assert r.status_code == 200, r.text
        upd = r.json()
        assert upd["name"] == "TEST_Praca_Iter11_Upd"
        assert len(upd["holidays_extra"]) == 2

        # DELETE when not used → OK
        r = requests.delete(f"{API}/pracas/{pid}", headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        # verify gone
        r = requests.get(f"{API}/pracas")
        ids = [p["id"] for p in r.json()]
        assert pid not in ids

    def test_delete_praca_in_use_returns_400(self, admin_headers):
        # create praça
        r = requests.post(f"{API}/pracas", json={
            "name": "TEST_Praca_InUse",
            "city": "Rio",
            "state": "RJ",
            "holidays_extra": [],
        }, headers=admin_headers)
        assert r.status_code == 200
        pid = r.json()["id"]

        # attach to Carlos (col-demo-001)
        original = requests.get(f"{API}/collaborators").json()
        carlos = next((c for c in original if c["id"] == "col-demo-001"), None)
        assert carlos is not None
        original_praca_id = carlos.get("praca_id")

        body = {k: v for k, v in carlos.items() if k not in ("id", "avatar_data_url", "reference_face", "created_at", "updated_at")}
        body["praca_id"] = pid
        r = requests.put(
            f"{API}/collaborators/col-demo-001",
            json=body,
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("praca_id") == pid

        # delete → 400
        r = requests.delete(f"{API}/pracas/{pid}", headers=admin_headers)
        assert r.status_code == 400
        assert "uso" in r.text.lower() or "colabora" in r.text.lower()

        # restore Carlos to original praca
        body["praca_id"] = original_praca_id
        requests.put(
            f"{API}/collaborators/col-demo-001",
            json=body,
            headers=admin_headers,
        )

        # cleanup praça
        requests.delete(f"{API}/pracas/{pid}", headers=admin_headers)


# ----- Timesheet integration with holidays_extra -----
class TestTimesheetHolidaysExtra:
    def test_holiday_municipal_appears_in_timesheet(self, admin_headers):
        # Create a test praça with a holiday in April 2026
        r = requests.post(f"{API}/pracas", json={
            "name": "TEST_Praca_HolInt",
            "city": "Cachoeiras",
            "state": "RJ",
            "holidays_extra": [
                {"date": "2026-04-10", "name": "Aniv Cidade Teste", "scope": "municipal"}
            ],
        }, headers=admin_headers)
        assert r.status_code == 200
        pid = r.json()["id"]

        # save original carlos praca
        carlos = next(c for c in requests.get(f"{API}/collaborators").json() if c["id"] == "col-demo-001")
        original_praca_id = carlos.get("praca_id")
        body = {k: v for k, v in carlos.items() if k not in ("id", "avatar_data_url", "reference_face", "created_at", "updated_at")}

        try:
            # attach Carlos to new praça
            body["praca_id"] = pid
            r = requests.put(
                f"{API}/collaborators/col-demo-001",
                json=body,
                headers=admin_headers,
            )
            assert r.status_code == 200, r.text

            # fetch timesheet April 2026
            r = requests.get(f"{API}/timesheets/col-demo-001/2026/4")
            assert r.status_code == 200, r.text
            data = r.json()
            days = data.get("days", [])
            april_10 = next((d for d in days if d["date"] == "2026-04-10"), None)
            assert april_10 is not None
            assert april_10.get("is_holiday") is True
            hol = april_10.get("holiday") or {}
            assert hol.get("scope") == "municipal"
            assert "Aniv" in (hol.get("name") or "")
        finally:
            # restore
            body["praca_id"] = original_praca_id
            requests.put(
                f"{API}/collaborators/col-demo-001",
                json=body,
                headers=admin_headers,
            )
            requests.delete(f"{API}/pracas/{pid}", headers=admin_headers)
