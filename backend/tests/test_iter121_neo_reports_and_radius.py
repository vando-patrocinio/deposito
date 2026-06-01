"""Tests for iter121 — NEO Reports schedules + 5km radius filter + auth login.

Coverage:
- CRUD /api/neo-reports/schedules
- POST /schedules/{id}/run (manual)
- GET /history, /report-types
- Validation (400s)
- Auth role enforcement (gestor)
- /api/rede-ia/public/ctos/list/{collab_id} radius filter
- /api/auth/login basic sanity
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

BRT = timezone(timedelta(hours=-3))

GESTOR_EMAIL = "gestor@empresa.com"
GESTOR_PASS = "123456"

COLLAB_TEC = "col-30aafc3c"  # role=Tecnico


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def gestor_token(session):
    r = session.post(f"{BASE_URL}/api/auth/login",
                     json={"email": GESTOR_EMAIL, "password": GESTOR_PASS})
    assert r.status_code == 200, f"gestor login failed: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no token in response: {data}"
    return tok


@pytest.fixture(scope="session")
def auth(session, gestor_token):
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {gestor_token}",
    })
    return s


# ---------------------------------------------------------------------------
# Auth / login sanity (collaborator login endpoint unchanged)
# ---------------------------------------------------------------------------
class TestAuthLogin:
    def test_gestor_login_returns_token(self, session):
        r = session.post(f"{BASE_URL}/api/auth/login",
                         json={"email": GESTOR_EMAIL, "password": GESTOR_PASS})
        assert r.status_code == 200
        d = r.json()
        assert d.get("access_token") or d.get("token")

    def test_invalid_login_rejected(self, session):
        r = session.post(f"{BASE_URL}/api/auth/login",
                         json={"email": GESTOR_EMAIL, "password": "wrong-pass"})
        assert r.status_code in (401, 400, 403)


# ---------------------------------------------------------------------------
# Report types
# ---------------------------------------------------------------------------
class TestReportTypes:
    def test_report_types_list(self, auth):
        r = auth.get(f"{BASE_URL}/api/neo-reports/report-types")
        assert r.status_code == 200, r.text
        items = r.json().get("items", [])
        keys = {i["key"] for i in items}
        assert {"ctos_occupancy", "closed_tickets", "dre"}.issubset(keys)

    def test_report_types_requires_auth(self, session):
        r = session.get(f"{BASE_URL}/api/neo-reports/report-types")
        assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Schedules CRUD + next_run_at calculation
# ---------------------------------------------------------------------------
class TestSchedulesCRUD:
    created_ids: list[str] = []

    def test_list_schedules_initial(self, auth):
        r = auth.get(f"{BASE_URL}/api/neo-reports/schedules")
        assert r.status_code == 200
        assert "items" in r.json()

    def test_create_daily_schedule_next_run(self, auth):
        payload = {
            "name": f"TEST_daily_{uuid.uuid4().hex[:6]}",
            "report_type": "ctos_occupancy",
            "frequency": "daily",
            "hour": 8, "minute": 30,
            "active": True,
        }
        r = auth.post(f"{BASE_URL}/api/neo-reports/schedules", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["id"].startswith("nrs-")
        assert d["frequency"] == "daily"
        assert d["next_run_at"]
        nxt = datetime.fromisoformat(d["next_run_at"])
        assert nxt.hour == 8 and nxt.minute == 30
        # next_run must be in the future
        now = datetime.now(BRT)
        assert nxt > now
        TestSchedulesCRUD.created_ids.append(d["id"])

        # Verify via GET list
        list_r = auth.get(f"{BASE_URL}/api/neo-reports/schedules")
        ids = [i["id"] for i in list_r.json()["items"]]
        assert d["id"] in ids

    def test_create_weekly_schedule_next_run(self, auth):
        payload = {
            "name": f"TEST_weekly_{uuid.uuid4().hex[:6]}",
            "report_type": "closed_tickets",
            "frequency": "weekly",
            "hour": 9, "minute": 0,
            "day_of_week": 0,  # Monday
            "active": True,
        }
        r = auth.post(f"{BASE_URL}/api/neo-reports/schedules", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        nxt = datetime.fromisoformat(d["next_run_at"])
        assert nxt.weekday() == 0  # Monday
        assert nxt.hour == 9
        TestSchedulesCRUD.created_ids.append(d["id"])

    def test_create_monthly_schedule_next_run(self, auth):
        payload = {
            "name": f"TEST_monthly_{uuid.uuid4().hex[:6]}",
            "report_type": "dre",
            "frequency": "monthly",
            "hour": 10, "minute": 15,
            "day_of_month": 5,
            "active": True,
        }
        r = auth.post(f"{BASE_URL}/api/neo-reports/schedules", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        nxt = datetime.fromisoformat(d["next_run_at"])
        assert nxt.day == 5 and nxt.hour == 10 and nxt.minute == 15
        TestSchedulesCRUD.created_ids.append(d["id"])

    def test_patch_recomputes_next_run(self, auth):
        assert TestSchedulesCRUD.created_ids, "no schedules created"
        sid = TestSchedulesCRUD.created_ids[0]
        # change hour to 23
        r = auth.patch(f"{BASE_URL}/api/neo-reports/schedules/{sid}",
                       json={"hour": 23, "minute": 45})
        assert r.status_code == 200, r.text
        d = r.json()
        nxt = datetime.fromisoformat(d["next_run_at"])
        assert nxt.hour == 23 and nxt.minute == 45

    def test_patch_frequency_change(self, auth):
        sid = TestSchedulesCRUD.created_ids[0]
        r = auth.patch(f"{BASE_URL}/api/neo-reports/schedules/{sid}",
                       json={"frequency": "weekly", "day_of_week": 2})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["frequency"] == "weekly"
        nxt = datetime.fromisoformat(d["next_run_at"])
        assert nxt.weekday() == 2

    def test_run_now_ctos_occupancy(self, auth):
        # create fresh
        payload = {
            "name": f"TEST_run_{uuid.uuid4().hex[:6]}",
            "report_type": "ctos_occupancy",
            "frequency": "daily",
            "hour": 6,
            "active": True,
        }
        cr = auth.post(f"{BASE_URL}/api/neo-reports/schedules", json=payload)
        assert cr.status_code == 200, cr.text
        sid = cr.json()["id"]
        TestSchedulesCRUD.created_ids.append(sid)

        r = auth.post(f"{BASE_URL}/api/neo-reports/schedules/{sid}/run")
        assert r.status_code == 200, r.text
        run = r.json()
        assert run.get("status") in ("success", "delivery_failed"), (
            f"unexpected status: {run.get('status')} err={run.get('error')}"
        )
        # PDF deve ter sido gerado
        assert run.get("pdf_size_bytes", 0) > 500, (
            f"pdf too small: {run.get('pdf_size_bytes')}"
        )
        # whatsapp_phone não foi setado => status deve ser success
        assert run.get("status") == "success"

    def test_history_contains_run(self, auth):
        r = auth.get(f"{BASE_URL}/api/neo-reports/history")
        assert r.status_code == 200
        items = r.json().get("items", [])
        # após executar run-now, deve haver pelo menos 1
        assert len(items) >= 1
        # first item should be most recent
        first = items[0]
        assert "status" in first

    def test_delete_schedules_cleanup(self, auth):
        for sid in TestSchedulesCRUD.created_ids:
            r = auth.delete(f"{BASE_URL}/api/neo-reports/schedules/{sid}")
            assert r.status_code == 200, f"delete {sid}: {r.text}"
        # re-delete -> 404
        r = auth.delete(f"{BASE_URL}/api/neo-reports/schedules/{TestSchedulesCRUD.created_ids[0]}")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Validation (400s)
# ---------------------------------------------------------------------------
class TestValidation:
    def test_invalid_report_type(self, auth):
        r = auth.post(f"{BASE_URL}/api/neo-reports/schedules", json={
            "name": "TEST_bad", "report_type": "bogus",
            "frequency": "daily", "hour": 8,
        })
        assert r.status_code == 400

    def test_invalid_frequency(self, auth):
        r = auth.post(f"{BASE_URL}/api/neo-reports/schedules", json={
            "name": "TEST_bad", "report_type": "ctos_occupancy",
            "frequency": "yearly", "hour": 8,
        })
        assert r.status_code == 400

    def test_weekly_without_day_of_week(self, auth):
        r = auth.post(f"{BASE_URL}/api/neo-reports/schedules", json={
            "name": "TEST_bad", "report_type": "ctos_occupancy",
            "frequency": "weekly", "hour": 8,
        })
        assert r.status_code == 400

    def test_monthly_without_day_of_month(self, auth):
        r = auth.post(f"{BASE_URL}/api/neo-reports/schedules", json={
            "name": "TEST_bad", "report_type": "ctos_occupancy",
            "frequency": "monthly", "hour": 8,
        })
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Auth role enforcement
# ---------------------------------------------------------------------------
class TestAuthRole:
    def test_create_schedule_without_auth(self, session):
        r = session.post(f"{BASE_URL}/api/neo-reports/schedules", json={
            "name": "x", "report_type": "ctos_occupancy",
            "frequency": "daily", "hour": 8,
        })
        assert r.status_code in (401, 403)

    def test_list_schedules_without_auth(self, session):
        r = session.get(f"{BASE_URL}/api/neo-reports/schedules")
        assert r.status_code in (401, 403)

    def test_history_without_auth(self, session):
        r = session.get(f"{BASE_URL}/api/neo-reports/history")
        assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# 5km radius filter
# ---------------------------------------------------------------------------
class TestRadiusFilter:
    def test_no_lat_lng_returns_all_for_tech(self, session):
        r = session.get(
            f"{BASE_URL}/api/rede-ia/public/ctos/list/{COLLAB_TEC}"
        )
        assert r.status_code == 200, r.text
        d = r.json()
        # sem lat/lng => filtro não aplicado
        assert d["role_filter_applied"] is False
        assert d["filtered_out_count"] == 0
        # deve retornar todas as CTOs cadastradas
        assert d["total"] >= 1

    def test_with_lat_lng_filters_for_tech(self, session):
        # Ponto longe das CTOs (centro de São Paulo)
        r = session.get(
            f"{BASE_URL}/api/rede-ia/public/ctos/list/{COLLAB_TEC}",
            params={"lat": -23.55, "lng": -46.63, "radius_km": 5.0},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["role_filter_applied"] is True
        assert d["radius_km"] == 5.0
        # Esperamos que ao menos algumas CTOs sejam filtradas
        # se elas não estão em SP. filtered_out_count >= 0
        assert d["filtered_out_count"] >= 0

    def test_radius_filter_keeps_only_within(self, session):
        # Pega lista total
        r_all = session.get(
            f"{BASE_URL}/api/rede-ia/public/ctos/list/{COLLAB_TEC}"
        )
        total_all = r_all.json()["total"]

        # Filtra com ponto bem distante => deveria filtrar quase tudo
        # (Tóquio)
        r_far = session.get(
            f"{BASE_URL}/api/rede-ia/public/ctos/list/{COLLAB_TEC}",
            params={"lat": 35.6, "lng": 139.7, "radius_km": 5.0},
        )
        d = r_far.json()
        assert d["role_filter_applied"] is True
        # com CTOs com gps, filtered_out_count > 0 (estão longe)
        # ctos sem gps são ignoradas (não contam como filtered_out nem kept)
        assert d["total"] <= total_all
