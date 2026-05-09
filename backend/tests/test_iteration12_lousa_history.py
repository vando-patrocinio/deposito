"""Iter12 — Histórico da Lousa
Tests for GET /api/lousa/history with day/month/year/range granularities,
collaborator/status/type filters, summary KPIs, and auth requirement.
"""
import os
import pytest
import requests
from datetime import datetime, timezone

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


# ----- Auth fixtures -----
@pytest.fixture(scope="module")
def gestor_token():
    r = requests.post(f"{API}/auth/login", json={"email": "gestor@empresa.com", "password": "123456"}, timeout=20)
    assert r.status_code == 200, f"login gestor failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def gestor_headers(gestor_token):
    return {"Authorization": f"Bearer {gestor_token}", "Content-Type": "application/json"}


# ----- granularity=day -----
class TestHistoryDay:
    def test_day_today_returns_200_and_shape(self, gestor_headers):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        r = requests.get(f"{API}/lousa/history", params={"granularity": "day", "date": today}, headers=gestor_headers, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        # Top-level shape
        for k in ("granularity", "label", "from_iso", "to_iso", "items", "summary"):
            assert k in d, f"missing key {k}"
        assert d["granularity"] == "day"
        assert d["label"] == today
        assert d["from_iso"].startswith(today)
        # to_iso agora usa intervalo SEMI-ABERTO (próximo dia 00:00) — consistente com month/year
        from datetime import datetime as _dt, timedelta as _td
        next_day = (_dt.fromisoformat(today) + _td(days=1)).strftime("%Y-%m-%d")
        assert d["to_iso"].startswith(next_day)
        assert isinstance(d["items"], list)
        assert isinstance(d["summary"], dict)

    def test_day_item_fields(self, gestor_headers):
        # use month granularity to grab some items, validate item field structure
        m = datetime.now(timezone.utc).strftime("%Y-%m")
        r = requests.get(f"{API}/lousa/history", params={"granularity": "month", "month": m}, headers=gestor_headers, timeout=30)
        assert r.status_code == 200
        items = r.json()["items"]
        if not items:
            pytest.skip("no items in current month — skipping field validation")
        it = items[0]
        for k in (
            "id", "client_name", "address", "neighborhood", "type", "priority",
            "status", "scheduled_time", "created_at", "opened_at", "closed_at",
            "duration_minutes", "admin_action", "admin_notes",
            "collaborator_id", "collaborator_name",
        ):
            assert k in it, f"item missing key {k}"

    def test_summary_fields(self, gestor_headers):
        m = datetime.now(timezone.utc).strftime("%Y-%m")
        r = requests.get(f"{API}/lousa/history", params={"granularity": "month", "month": m}, headers=gestor_headers, timeout=30)
        assert r.status_code == 200
        s = r.json()["summary"]
        for k in (
            "total", "finalizada", "encerrada", "cancelada", "reagendada",
            "pendente", "aberta", "by_type", "by_collaborator",
            "total_duration_minutes", "durations_count", "avg_duration_minutes",
            "top_collaborator",
        ):
            assert k in s, f"summary missing key {k}"
        assert isinstance(s["by_type"], dict)
        assert isinstance(s["by_collaborator"], dict)
        # top_collaborator either None or {id, name, count}
        if s["top_collaborator"] is not None:
            for k in ("id", "name", "count"):
                assert k in s["top_collaborator"]


# ----- granularity=month -----
class TestHistoryMonth:
    def test_month_covers_full_month(self, gestor_headers):
        r = requests.get(f"{API}/lousa/history", params={"granularity": "month", "month": "2026-01"}, headers=gestor_headers, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["from_iso"] == "2026-01-01T00:00:00"
        assert d["to_iso"] == "2026-02-01T00:00:00"
        assert d["label"] == "2026-01"

    def test_month_december_rollover(self, gestor_headers):
        r = requests.get(f"{API}/lousa/history", params={"granularity": "month", "month": "2025-12"}, headers=gestor_headers, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["from_iso"] == "2025-12-01T00:00:00"
        assert d["to_iso"] == "2026-01-01T00:00:00"


# ----- granularity=year -----
class TestHistoryYear:
    def test_year_covers_full_year(self, gestor_headers):
        r = requests.get(f"{API}/lousa/history", params={"granularity": "year", "year": "2026"}, headers=gestor_headers, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["from_iso"] == "2026-01-01T00:00:00"
        assert d["to_iso"] == "2027-01-01T00:00:00"
        assert d["label"] == "2026"


# ----- granularity=range -----
class TestHistoryRange:
    def test_range_missing_params_returns_400(self, gestor_headers):
        # missing date_to
        r = requests.get(f"{API}/lousa/history", params={"granularity": "range", "date_from": "2026-01-01"}, headers=gestor_headers, timeout=30)
        assert r.status_code == 400, r.text

    def test_range_missing_both_returns_400(self, gestor_headers):
        r = requests.get(f"{API}/lousa/history", params={"granularity": "range"}, headers=gestor_headers, timeout=30)
        assert r.status_code == 400

    def test_range_with_both_works(self, gestor_headers):
        r = requests.get(f"{API}/lousa/history", params={
            "granularity": "range", "date_from": "2026-01-01", "date_to": "2026-01-31"
        }, headers=gestor_headers, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["granularity"] == "range"
        assert d["from_iso"].startswith("2026-01-01")
        # to_iso agora é SEMI-ABERTO: 2026-02-01 (1 dia após 2026-01-31)
        assert d["to_iso"].startswith("2026-02-01")
        assert "→" in d["label"]


# ----- filters -----
class TestHistoryFilters:
    def test_status_filter_limits_results(self, gestor_headers):
        m = datetime.now(timezone.utc).strftime("%Y-%m")
        r = requests.get(f"{API}/lousa/history", params={"granularity": "month", "month": m, "status": "cancelada"}, headers=gestor_headers, timeout=30)
        assert r.status_code == 200
        items = r.json()["items"]
        for it in items:
            assert it["status"] == "cancelada"

    def test_type_filter_alias(self, gestor_headers):
        m = datetime.now(timezone.utc).strftime("%Y-%m")
        # 'type' is the public param (alias to type_filter internally)
        r = requests.get(f"{API}/lousa/history", params={"granularity": "month", "month": m, "type": "reparo"}, headers=gestor_headers, timeout=30)
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert it["type"] == "reparo"

    def test_collaborator_filter(self, gestor_headers):
        m = datetime.now(timezone.utc).strftime("%Y-%m")
        # find a collaborator with items first
        full = requests.get(f"{API}/lousa/history", params={"granularity": "month", "month": m}, headers=gestor_headers, timeout=30).json()
        cid = None
        for it in full["items"]:
            if it.get("collaborator_id"):
                cid = it["collaborator_id"]
                break
        if not cid:
            pytest.skip("no collaborator-assigned items to filter on")
        r = requests.get(f"{API}/lousa/history", params={"granularity": "month", "month": m, "collaborator_id": cid}, headers=gestor_headers, timeout=30)
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert it["collaborator_id"] == cid


# ----- auth -----
class TestHistoryAuth:
    def test_no_auth_returns_401_or_403(self):
        r = requests.get(f"{API}/lousa/history", params={"granularity": "day"}, timeout=30)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"

    def test_bad_token_rejected(self):
        r = requests.get(f"{API}/lousa/history",
                         params={"granularity": "day"},
                         headers={"Authorization": "Bearer fake-token"},
                         timeout=30)
        assert r.status_code in (401, 403)
