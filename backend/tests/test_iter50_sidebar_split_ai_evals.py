"""Iteration 50 regression tests:
- Lousa date filter (scheduled_for/scheduled_time only shows today's tickets in /lousa/me)
- Central IA endpoints (KPIs, ai-evaluations summary, alerts with SLA)
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
                      timeout=20)
    assert r.status_code == 200, f"Login falhou: {r.status_code} {r.text}"
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def H(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# -------------------- Central IA endpoints --------------------
class TestCentralIA:
    def test_dashboard_kpis(self, H):
        r = requests.get(f"{BASE_URL}/api/central-ia/dashboard/kpis?days=7",
                         headers=H, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("days", "total_conversations", "sentiment"):
            assert k in body

    def test_dashboard_summary(self, H):
        r = requests.get(f"{BASE_URL}/api/central-ia/dashboard/summary",
                         headers=H, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("evaluated_24h", "alerts_24h", "csat_avg_24h"):
            assert k in body

    def test_ai_evaluations_summary(self, H):
        # New endpoint used by AiEvaluationsCard
        r = requests.get(f"{BASE_URL}/api/central-ia/dashboard/ai-evaluations?days=30",
                         headers=H, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "ai_only" in body and "human" in body and "trend_14d" in body
        for blk in (body["ai_only"], body["human"]):
            for k in ("total", "avg_csat", "promoters", "neutrals", "detractors",
                     "fcr_rate", "avg_frt_seconds", "avg_aht_seconds"):
                assert k in blk, f"Falta '{k}' em ai-evaluations block"

    def test_attendants_ranking(self, H):
        r = requests.get(f"{BASE_URL}/api/central-ia/dashboard/attendants?days=7",
                         headers=H, timeout=20)
        assert r.status_code == 200, r.text
        assert "items" in r.json()

    def test_productivity(self, H):
        r = requests.get(f"{BASE_URL}/api/central-ia/dashboard/productivity?days=7",
                         headers=H, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "items" in body and "team" in body

    def test_intents(self, H):
        r = requests.get(f"{BASE_URL}/api/central-ia/dashboard/intents?days=7",
                         headers=H, timeout=20)
        assert r.status_code == 200, r.text

    def test_alerts_includes_sla_keys(self, H):
        # /alerts compounds SLA-style alerts derived from productivity
        r = requests.get(f"{BASE_URL}/api/central-ia/alerts",
                         headers=H, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "items" in body
        # not asserting that SLA alerts exist (depends on data) - just shape
        for it in body["items"][:5]:
            assert "kind" in it and "severity" in it


# -------------------- Lousa date filter --------------------
class TestLousaDateRule:
    def _today_br(self):
        return (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%d")

    def _yesterday_br(self):
        return (datetime.now(timezone.utc) - timedelta(hours=3, days=1)).strftime("%Y-%m-%d")

    @pytest.fixture(scope="class")
    def collab_id(self, H):
        r = requests.get(f"{BASE_URL}/api/collaborators", headers=H, timeout=20)
        if r.status_code != 200:
            pytest.skip("Sem endpoint /collaborators")
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        if not items:
            pytest.skip("Sem colaboradores cadastrados")
        return items[0]["id"]

    def test_grid_today_baseline(self, H):
        r = requests.get(f"{BASE_URL}/api/lousa/grid", headers=H, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "columns" in body and isinstance(body["columns"], list)

    def test_create_ticket_yesterday_not_in_today(self, H, collab_id):
        # Create a ticket scheduled for yesterday
        sched_y = f"{self._yesterday_br()}T09:00:00"
        payload = {
            "client_name": f"TEST_YDAY_{uuid.uuid4().hex[:6]}",
            "address": "Rua Teste 100",
            "neighborhood": "Centro",
            "phone": "11999998888",
            "relato": "teste filtro data",
            "type": "reparo",
            "priority": "normal",
            "scheduled_time": sched_y,
            "assigned_collaborator_id": collab_id,
        }
        r = requests.post(f"{BASE_URL}/api/lousa/tickets", json=payload,
                          headers=H, timeout=20)
        assert r.status_code in (200, 201), r.text
        t_yday = r.json()
        t_yday_id = t_yday["id"]

        # Create one for today as control
        sched_t = f"{self._today_br()}T10:00:00"
        payload2 = {**payload,
                    "client_name": f"TEST_TODAY_{uuid.uuid4().hex[:6]}",
                    "scheduled_time": sched_t}
        r2 = requests.post(f"{BASE_URL}/api/lousa/tickets", json=payload2,
                           headers=H, timeout=20)
        assert r2.status_code in (200, 201), r2.text
        t_today_id = r2.json()["id"]

        # Use public collab endpoint that applies date rule
        r3 = requests.get(f"{BASE_URL}/api/lousa/by-collaborator/{collab_id}",
                          timeout=20)
        # Endpoint exists but may require clock-in (returns tickets=[] + needs_clock_in=true)
        assert r3.status_code == 200, r3.text
        body = r3.json()
        tickets = body.get("tickets") or []
        ids = [t["id"] for t in tickets]
        # The yesterday ticket must NOT appear in collaborator's today view
        assert t_yday_id not in ids, \
            f"Ticket de ontem ({t_yday_id}) apareceu na lousa de hoje: {ids}"
        # Cleanup
        for tid in (t_yday_id, t_today_id):
            requests.delete(f"{BASE_URL}/api/lousa/tickets/{tid}",
                            headers=H, timeout=10)
