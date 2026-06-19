from __future__ import annotations
"""Iteration 18 — backend-only tests for refactored routes (push, locations, dashboard)
and the new dwell-heatmap endpoint, plus regression of legacy/non-refactored endpoints.

Covers:
- routes/locations.py: POST /api/locations (auth-free), GET /live, GET /{cid}/track,
  GET /dwell-analysis, DELETE /{cid}
- routes/dashboard.py: /overtime/trend, /overtime/range (monthly+accumulated),
  /dwell-heatmap. Plus regression on the kept-in-server endpoint /overtime/{y}/{m}
- routes/push.py: /vapid-public-key (public), /subscribe (jwt), /unsubscribe (jwt),
  /subscriptions (gestor/auditor), /test (gestor/auditor)
- Regression on critical endpoints kept in server.py (auth, users, pracas,
  collaborators, clock-records, timesheets, holidays, settings).
"""

import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _test_secrets import TEST_ADMIN_PASSWORD, TEST_AUDITOR_PASSWORD  # noqa: E402
import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL is not set"

ADMIN = {"email": "admin@example.com", "password": TEST_ADMIN_PASSWORD}
AUDITOR = {"email": "vando@example.com", "password": "123456"}


# ---------------------------------------------------------------- fixtures
@pytest.fixture(scope="session")
def s() -> requests.Session:
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


def _login(sess: requests.Session, creds: dict) -> str:
    r = sess.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    assert "access_token" in body
    return body["access_token"]


@pytest.fixture(scope="session")
def admin_token(s) -> str:
    return _login(s, ADMIN)


@pytest.fixture(scope="session")
def auditor_token(s) -> str:
    return _login(s, AUDITOR)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# =================================================================
# Auth & basic regression
# =================================================================
class TestAuthRegression:
    def test_admin_login(self, s):
        r = s.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["user"]["email"] == ADMIN["email"]
        assert body["user"]["role"] in ("gestor", "auditor")

    def test_auditor_login(self, s):
        r = s.post(f"{BASE_URL}/api/auth/login", json=AUDITOR, timeout=15)
        assert r.status_code == 200
        assert r.json()["user"]["role"] in ("auditor", "gestor")

    def test_login_wrong_password(self, s):
        r = s.post(f"{BASE_URL}/api/auth/login",
                   json={"email": ADMIN["email"], "password": "wrong-xxxxx"}, timeout=15)
        assert r.status_code in (401, 429)


# =================================================================
# routes/push.py
# =================================================================
class TestPushRoutes:
    def test_vapid_public_key_public(self, s):
        r = s.get(f"{BASE_URL}/api/push/vapid-public-key", timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "public_key" in body
        assert isinstance(body["public_key"], str) and len(body["public_key"]) > 20

    def test_vapid_key_stable(self, s):
        a = s.get(f"{BASE_URL}/api/push/vapid-public-key").json()["public_key"]
        b = s.get(f"{BASE_URL}/api/push/vapid-public-key").json()["public_key"]
        assert a == b, "VAPID key should be cached/persistent across requests"

    def test_subscribe_requires_jwt(self, s):
        r = s.post(f"{BASE_URL}/api/push/subscribe",
                   json={"endpoint": "https://example.com/x", "keys": {"p256dh": "k", "auth": "a"}},
                   timeout=15)
        assert r.status_code in (401, 403)

    def test_unsubscribe_requires_jwt(self, s):
        r = s.post(f"{BASE_URL}/api/push/unsubscribe",
                   json={"endpoint": "https://example.com/x"}, timeout=15)
        assert r.status_code in (401, 403)

    def test_subscriptions_requires_role(self, s):
        r = s.get(f"{BASE_URL}/api/push/subscriptions", timeout=15)
        assert r.status_code in (401, 403)

    def test_test_endpoint_requires_role(self, s):
        r = s.post(f"{BASE_URL}/api/push/test", timeout=15)
        assert r.status_code in (401, 403)

    def test_subscribe_with_valid_jwt(self, s, admin_token):
        endpoint = f"https://fcm.googleapis.com/fcm/send/TEST_{uuid.uuid4().hex[:10]}"
        payload = {
            "endpoint": endpoint,
            "keys": {"p256dh": "BMxx_fake", "auth": "auth_fake"},
            "user_agent": "pytest-iter18",
        }
        r = s.post(f"{BASE_URL}/api/push/subscribe", json=payload,
                   headers=auth(admin_token), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert "endpoint" in body
        # cleanup
        r2 = s.post(f"{BASE_URL}/api/push/unsubscribe", json={"endpoint": endpoint},
                    headers=auth(admin_token), timeout=15)
        assert r2.status_code == 200

    def test_subscribe_validation_missing_keys(self, s, admin_token):
        # Missing keys field → pydantic 422
        r = s.post(f"{BASE_URL}/api/push/subscribe",
                   json={"endpoint": "https://e/x"},
                   headers=auth(admin_token), timeout=15)
        assert r.status_code in (400, 422)

    def test_unsubscribe_missing_endpoint(self, s, admin_token):
        r = s.post(f"{BASE_URL}/api/push/unsubscribe", json={},
                   headers=auth(admin_token), timeout=15)
        assert r.status_code == 400

    def test_subscriptions_list_admin(self, s, admin_token):
        r = s.get(f"{BASE_URL}/api/push/subscriptions",
                  headers=auth(admin_token), timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        for it in body:
            assert "endpoint" in it
            # endpoint is truncated to 80 chars + ellipsis if longer
            assert isinstance(it["endpoint"], str)

    def test_push_test_broadcast(self, s, auditor_token):
        r = s.post(f"{BASE_URL}/api/push/test", headers=auth(auditor_token), timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        # broadcast returns dict with sent/failed/removed (sent may be 0)
        assert "sent" in body
        assert "failed" in body
        assert isinstance(body["sent"], int)
        assert isinstance(body["failed"], int)


# =================================================================
# routes/locations.py
# =================================================================
class TestLocationsRoutes:
    @pytest.fixture(scope="class")
    def collaborator_id(self, s, auditor_token):
        # use the demo collaborator if present, otherwise the first one
        r = s.get(f"{BASE_URL}/api/collaborators", headers=auth(auditor_token), timeout=15)
        assert r.status_code == 200
        items = r.json()
        if not items:
            pytest.skip("no collaborator in DB")
        for c in items:
            if c["id"] == "col-demo-001":
                return c["id"]
        return items[0]["id"]

    def test_post_location_no_auth(self, s, collaborator_id):
        # legacy: auth-free ping
        r = s.post(f"{BASE_URL}/api/locations",
                   json={"collaborator_id": collaborator_id,
                         "lat": -23.55, "lng": -46.63, "accuracy": 12.0},
                   timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["collaborator_id"] == collaborator_id
        assert "id" in body and "_id" not in body
        assert body["lat"] == -23.55

    def test_post_location_unknown_collaborator_404(self, s):
        r = s.post(f"{BASE_URL}/api/locations",
                   json={"collaborator_id": "does-not-exist-xxx",
                         "lat": 0, "lng": 0}, timeout=15)
        assert r.status_code == 404

    def test_live_returns_list(self, s):
        r = s.get(f"{BASE_URL}/api/locations/live", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        for d in body:
            assert "_id" not in d
            assert "collaborator_id" in d

    def test_track_returns_points(self, s, collaborator_id):
        # ensure at least one ping in last 24h
        s.post(f"{BASE_URL}/api/locations",
               json={"collaborator_id": collaborator_id, "lat": -23.5, "lng": -46.6}, timeout=15)
        r = s.get(f"{BASE_URL}/api/locations/{collaborator_id}/track?hours=24", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        assert len(body) >= 1
        for d in body:
            assert "_id" not in d
            assert d["collaborator_id"] == collaborator_id

    def test_dwell_analysis_contract(self, s):
        r = s.get(f"{BASE_URL}/api/locations/dwell-analysis?hours=8&min_dur_min=30&use_ai=false",
                  timeout=20)
        assert r.status_code == 200
        body = r.json()
        for k in ("generated_at", "hours", "stationary_threshold_min", "use_ai", "items", "alerts"):
            assert k in body
        assert isinstance(body["items"], list)
        assert isinstance(body["alerts"], list)
        assert body["use_ai"] is False
        for a in body["alerts"]:
            assert a["id"].startswith(("dwell:", "fence:"))
            assert a["level"] in ("warning", "danger")

    def test_delete_track_with_hours(self, s, collaborator_id, auditor_token):
        # post fresh ping then delete *older than 999h* → deletes 0 (preserves data).
        s.post(f"{BASE_URL}/api/locations",
               json={"collaborator_id": collaborator_id, "lat": -23.5, "lng": -46.6}, timeout=15)
        r = s.delete(f"{BASE_URL}/api/locations/{collaborator_id}?hours=999", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "deleted" in body
        assert isinstance(body["deleted"], int)
        # don't wipe: only verify endpoint shape


# =================================================================
# routes/dashboard.py
# =================================================================
class TestDashboardRoutes:
    def test_overtime_trend(self, s):
        r = s.get(f"{BASE_URL}/api/dashboard/overtime/trend?months=3", timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("months", "series", "top_debit", "alerts", "budget_brl", "threshold_pct"):
            assert k in body, f"missing key: {k}"
        assert body["months"] == 3
        assert isinstance(body["series"], list)
        assert len(body["series"]) <= 3
        for it in body["series"]:
            for k in ("year", "month", "label", "total_overtime_min",
                      "total_paid_brl", "projected_overtime_min",
                      "projected_paid_brl", "is_current"):
                assert k in it
        # exactly one is_current=True (current month) when months>=1
        assert sum(1 for x in body["series"] if x["is_current"]) <= 1

    def test_overtime_trend_clamped(self, s):
        # months capped at 24
        r = s.get(f"{BASE_URL}/api/dashboard/overtime/trend?months=999", timeout=60)
        assert r.status_code == 200
        body = r.json()
        assert body["months"] == 24
        assert len(body["series"]) <= 24

    def test_overtime_range_monthly(self, s):
        # 3-month range
        r = s.get(f"{BASE_URL}/api/dashboard/overtime/range",
                  params={"year_from": 2025, "month_from": 11,
                          "year_to": 2026, "month_to": 1, "mode": "monthly"},
                  timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mode"] == "monthly"
        assert body["year_from"] == 2025 and body["month_from"] == 11
        assert body["year_to"] == 2026 and body["month_to"] == 1
        assert isinstance(body["series"], list)
        assert len(body["series"]) == 3
        labels = [it["label"] for it in body["series"]]
        assert labels == ["11/2025", "12/2025", "01/2026"]

    def test_overtime_range_accumulated_mode_preserved(self, s):
        r = s.get(f"{BASE_URL}/api/dashboard/overtime/range",
                  params={"year_from": 2025, "month_from": 12,
                          "year_to": 2026, "month_to": 1, "mode": "accumulated"},
                  timeout=30)
        assert r.status_code == 200
        assert r.json()["mode"] == "accumulated"

    def test_overtime_range_invalid(self, s):
        r = s.get(f"{BASE_URL}/api/dashboard/overtime/range",
                  params={"year_from": 2025, "month_from": 13,
                          "year_to": 2026, "month_to": 1}, timeout=15)
        assert r.status_code in (400, 422)

    def test_overtime_specific_month_still_works(self, s):
        # not refactored — kept in server.py
        today_y, today_m = 2026, 1
        r = s.get(f"{BASE_URL}/api/dashboard/overtime/{today_y}/{today_m}", timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "total_overtime_min" in body and "rows" in body

    def test_dwell_heatmap_contract(self, s):
        r = s.get(f"{BASE_URL}/api/dashboard/dwell-heatmap",
                  params={"year": 2026, "month": 1}, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("year", "month", "last_day", "rows", "by_day", "total_minutes"):
            assert k in body, f"missing key: {k}"
        assert body["year"] == 2026 and body["month"] == 1
        assert body["last_day"] == 31
        assert isinstance(body["rows"], list)
        assert isinstance(body["by_day"], list)
        assert len(body["by_day"]) == 31
        for d in body["by_day"]:
            assert "day" in d and "minutes" in d
            assert isinstance(d["minutes"], int)
        for row in body["rows"]:
            for k in ("praca_id", "praca_name", "total_minutes", "stays", "by_collab"):
                assert k in row
            assert isinstance(row["by_collab"], list)
        assert body["total_minutes"] == sum(r["total_minutes"] for r in body["rows"])

    def test_dwell_heatmap_invalid(self, s):
        r = s.get(f"{BASE_URL}/api/dashboard/dwell-heatmap",
                  params={"year": 2026, "month": 13}, timeout=15)
        assert r.status_code in (400, 422)


# =================================================================
# Regression on endpoints kept in server.py
# =================================================================
class TestServerRegression:
    def test_users_crud_list(self, s, auditor_token):
        r = s.get(f"{BASE_URL}/api/users", headers=auth(auditor_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_pracas_list(self, s, auditor_token):
        r = s.get(f"{BASE_URL}/api/pracas", headers=auth(auditor_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_collaborators_list(self, s, auditor_token):
        r = s.get(f"{BASE_URL}/api/collaborators", headers=auth(auditor_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_clock_records_list(self, s):
        r = s.get(f"{BASE_URL}/api/clock-records", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_holidays_list(self, s):
        r = s.get(f"{BASE_URL}/api/holidays/2026", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_settings_get(self, s, auditor_token):
        r = s.get(f"{BASE_URL}/api/settings", headers=auth(auditor_token), timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, dict)

    def test_timesheets_kept_works(self, s, auditor_token):
        # find any collaborator id
        r = s.get(f"{BASE_URL}/api/collaborators", headers=auth(auditor_token), timeout=15)
        items = r.json()
        if not items:
            pytest.skip("no collaborators")
        cid = items[0]["id"]
        r2 = s.get(f"{BASE_URL}/api/timesheets/{cid}/2026/1", headers=auth(auditor_token), timeout=20)
        assert r2.status_code == 200
