"""Iter14 — Lousa Grid Histórico + Mirror Mobile + serverTime
Tests:
- GET /api/lousa/grid (sem params) → historical=false, comportamento padrão
- GET /api/lousa/grid?date_from&date_to (dia/semana/mês/ano) → historical=true, locked=true
- GET /api/lousa/by-collaborator/{cid} (PÚBLICO) → mirror exato (só ativas)
- GET /api/server-time → para serverNow singleton
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def gestor_headers():
    r = requests.post(f"{API}/auth/login", json={"email": "gestor@empresa.com", "password": "123456"}, timeout=20)
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- /api/lousa/grid sem params ----------
class TestLousaGridDefault:
    def test_no_params_returns_historical_false(self, gestor_headers):
        r = requests.get(f"{API}/lousa/grid", headers=gestor_headers, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("historical") is False
        assert d.get("date_from") is None
        assert d.get("date_to") is None
        assert isinstance(d.get("columns"), list)

    def test_no_params_tickets_not_locked(self, gestor_headers):
        r = requests.get(f"{API}/lousa/grid", headers=gestor_headers, timeout=30)
        assert r.status_code == 200
        for col in r.json().get("columns", []):
            for t in col.get("tickets", []):
                # active mode should not flag historical/locked-by-history
                assert t.get("historical") in (False, None), f"ticket {t.get('id')} marked historical in default mode"


# ---------- /api/lousa/grid histórico ----------
class TestLousaGridHistorical:
    def test_day_range_returns_historical_true(self, gestor_headers):
        params = {"date_from": "2026-05-09", "date_to": "2026-05-09"}
        r = requests.get(f"{API}/lousa/grid", params=params, headers=gestor_headers, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("historical") is True
        assert d.get("date_from") == "2026-05-09"
        assert d.get("date_to") == "2026-05-09"
        assert isinstance(d.get("columns"), list)

    def test_day_range_tickets_locked_and_historical(self, gestor_headers):
        params = {"date_from": "2026-05-09", "date_to": "2026-05-09"}
        r = requests.get(f"{API}/lousa/grid", params=params, headers=gestor_headers, timeout=30)
        assert r.status_code == 200
        all_tickets = []
        for col in r.json().get("columns", []):
            all_tickets += col.get("tickets", [])
        assert len(all_tickets) > 0, "historical day should return at least 1 ticket"
        for t in all_tickets:
            assert t.get("locked") is True, f"ticket {t.get('id')} not locked in historical"
            assert t.get("historical") is True, f"ticket {t.get('id')} not historical-flagged"

    def test_week_range(self, gestor_headers):
        params = {"date_from": "2026-05-04", "date_to": "2026-05-10"}
        r = requests.get(f"{API}/lousa/grid", params=params, headers=gestor_headers, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d.get("historical") is True
        assert d.get("date_from") == "2026-05-04"
        assert d.get("date_to") == "2026-05-10"
        all_tickets = sum((c.get("tickets", []) for c in d.get("columns", [])), [])
        # week should be >= day count
        assert len(all_tickets) >= 1

    def test_month_range(self, gestor_headers):
        params = {"date_from": "2026-05-01", "date_to": "2026-05-31"}
        r = requests.get(f"{API}/lousa/grid", params=params, headers=gestor_headers, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d.get("historical") is True

    def test_no_auth_returns_401_or_403(self):
        r = requests.get(f"{API}/lousa/grid", timeout=30)
        assert r.status_code in (401, 403)


# ---------- /api/lousa/by-collaborator (PUBLIC mirror) ----------
class TestLousaByCollaboratorMirror:
    CID = "col-demo-001"

    def test_endpoint_is_public_no_auth(self):
        r = requests.get(f"{API}/lousa/by-collaborator/{self.CID}", timeout=30)
        assert r.status_code == 200, r.text

    def test_response_shape(self):
        r = requests.get(f"{API}/lousa/by-collaborator/{self.CID}", timeout=30)
        assert r.status_code == 200
        d = r.json()
        for k in ("tickets", "recent_resolved", "needs_clock_in", "last_closed_at", "minutes_since_last_close"):
            assert k in d, f"missing key {k}"
        assert isinstance(d["tickets"], list)
        assert isinstance(d["recent_resolved"], list)

    def test_tickets_only_active_status(self):
        """Mirror exato: tickets[] não pode conter finalizada/encerrada/cancelada."""
        r = requests.get(f"{API}/lousa/by-collaborator/{self.CID}", timeout=30)
        assert r.status_code == 200
        d = r.json()
        forbidden = {"finalizada", "encerrada", "cancelada"}
        for t in d.get("tickets", []):
            st = t.get("status")
            assert st not in forbidden, f"ticket {t.get('id')} has resolved status '{st}' in tickets[] — should be in recent_resolved"

    def test_recent_resolved_separate_array(self):
        """recent_resolved deve existir como array separado."""
        r = requests.get(f"{API}/lousa/by-collaborator/{self.CID}", timeout=30)
        d = r.json()
        # se há resolvidos recentes, devem estar aqui (não em tickets)
        assert isinstance(d["recent_resolved"], list)


# ---------- /api/server-time (para serverNow singleton) ----------
class TestServerTime:
    def test_server_time_endpoint_works(self):
        r = requests.get(f"{API}/server-time", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("iso", "epoch_ms", "epoch_s"):
            assert k in d, f"missing key {k}"
        assert isinstance(d["epoch_ms"], int)
        assert d["epoch_ms"] > 1_700_000_000_000  # sanity (post-2023)
