"""Iter 49 — Tests for:
1. Central IA — AI evaluations summary (NPS-like / CSAT / FCR / FRT / AHT)
2. Central IA — SLA alerts (high_idle_attendant / slow_frt_attendant) appended to alerts
3. Lousa — date-based filter (only show today's BR-day tickets)
4. Lousa — admin reagendar keeps ticket alive (status='pendente'),
   updates scheduled_time + rescheduled_at + reschedule_count.
"""

import os
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://dual-combine-3.preview.emergentagent.com",
).rstrip("/")

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"

# Use the seeded demo collaborator (DIOGO HENRIQUE — clock_in_enabled may vary)
COLLAB_ID = "col-30aafc3c"


def _today_br_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%d")


def _tomorrow_br_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=3) + timedelta(days=1)).strftime("%Y-%m-%d")


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# -------------------------------------------------------------------
# Feature #3 — AI evaluations summary
# -------------------------------------------------------------------
class TestAIEvaluationsSummary:
    def test_endpoint_returns_required_envelope(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/central-ia/dashboard/ai-evaluations?days=30",
            headers=admin_headers,
            timeout=15,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        # Top-level envelope
        for k in ("ai_only", "human", "trend_14d", "days", "generated_at"):
            assert k in d, f"missing key {k}"
        assert d["days"] == 30
        assert isinstance(d["trend_14d"], list)

    def test_ai_only_has_all_kpi_fields(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/central-ia/dashboard/ai-evaluations?days=30",
            headers=admin_headers,
            timeout=15,
        )
        assert r.status_code == 200
        ai = r.json()["ai_only"]
        for k in (
            "total", "avg_csat", "promoters", "neutrals", "detractors",
            "fcr_rate", "avg_frt_seconds", "avg_aht_seconds",
            "nps", "promoters_pct", "detractors_pct",
        ):
            assert k in ai, f"ai_only missing {k}"

    def test_human_block_has_same_shape(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/central-ia/dashboard/ai-evaluations?days=30",
            headers=admin_headers,
            timeout=15,
        )
        h = r.json()["human"]
        for k in (
            "total", "avg_csat", "promoters", "neutrals", "detractors",
            "fcr_rate", "avg_frt_seconds", "avg_aht_seconds",
            "nps", "promoters_pct", "detractors_pct",
        ):
            assert k in h, f"human missing {k}"

    def test_ai_only_known_values(self, admin_headers):
        """Per review: 9 ai-only evals; avg_csat ~4.5 (drifts ~+0.1 as worker
        re-evaluates older convs); nps ≈ -88.9.  We assert count exact and
        the other two within tolerance."""
        r = requests.get(
            f"{BASE_URL}/api/central-ia/dashboard/ai-evaluations?days=30",
            headers=admin_headers,
            timeout=15,
        )
        ai = r.json()["ai_only"]
        assert ai["total"] == 9, f"expected 9 ai-only evals, got {ai['total']}"
        assert 4.0 <= ai["avg_csat"] <= 5.0, f"avg_csat out of range: {ai['avg_csat']}"
        assert abs(ai["nps"] - (-88.9)) <= 1.0, f"nps drifted: {ai['nps']}"

    def test_nps_formula_consistency(self, admin_headers):
        """NPS == round(promoters_pct - detractors_pct, 1)."""
        r = requests.get(
            f"{BASE_URL}/api/central-ia/dashboard/ai-evaluations?days=30",
            headers=admin_headers,
            timeout=15,
        )
        for block in ("ai_only", "human"):
            d = r.json()[block]
            if d["total"] == 0:
                continue
            expected = round(d["promoters_pct"] - d["detractors_pct"], 1)
            assert abs(d["nps"] - expected) <= 0.1, f"{block} nps mismatch"

    def test_requires_auth(self):
        r = requests.get(
            f"{BASE_URL}/api/central-ia/dashboard/ai-evaluations?days=30",
            timeout=15,
        )
        assert r.status_code in (401, 403)


# -------------------------------------------------------------------
# Feature #1 — SLA alerts in /api/central-ia/alerts
# -------------------------------------------------------------------
class TestSLAAlerts:
    def test_alerts_endpoint_responds(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/central-ia/alerts",
            headers=admin_headers,
            timeout=15,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert "items" in d
        assert isinstance(d["items"], list)

    def test_alert_items_well_formed(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/central-ia/alerts",
            headers=admin_headers,
            timeout=15,
        )
        for it in r.json()["items"]:
            assert "kind" in it and "severity" in it and "title" in it

    def test_sla_alert_kinds_are_allowed(self, admin_headers):
        """SLA kinds must be 'high_idle_attendant' or 'slow_frt_attendant'
        with severity 'warning'. If none fire it's fine — no SLA breach
        in current seed data — but if any present, they must conform."""
        r = requests.get(
            f"{BASE_URL}/api/central-ia/alerts",
            headers=admin_headers,
            timeout=15,
        )
        sla = [it for it in r.json()["items"]
               if it["kind"] in ("high_idle_attendant", "slow_frt_attendant")]
        for it in sla:
            assert it["severity"] == "warning"
            assert it.get("user_id")


# -------------------------------------------------------------------
# Feature #2 — Lousa date filtering + reagendar
# -------------------------------------------------------------------
class TestLousaDateFilterAndReschedule:
    @pytest.fixture(scope="class")
    def today_ticket_id(self, admin_headers):
        """Create a ticket scheduled for TODAY (BR) for the test collaborator."""
        today = _today_br_iso()
        payload = {
            "client_name": "TEST_LOUSA Cliente Hoje",
            "address": "Rua Teste, 1",
            "neighborhood": "Centro",
            "phone": "21999999999",
            "type": "reparo",
            "priority": "horario",
            "scheduled_time": f"{today}T14:00:00+00:00",
            "assigned_collaborator_id": COLLAB_ID,
            "relato": "iter49 date filter test",
            "pppoe_user": "TEST",
            "test_history": [],
        }
        r = requests.post(
            f"{BASE_URL}/api/lousa/tickets",
            headers=admin_headers, json=payload, timeout=15,
        )
        assert r.status_code == 200, r.text
        tid = r.json()["id"]
        yield tid
        # cleanup
        requests.delete(f"{BASE_URL}/api/lousa/tickets/{tid}",
                        headers=admin_headers, timeout=15)

    @pytest.fixture(scope="class")
    def tomorrow_ticket_id(self, admin_headers):
        """Create a ticket scheduled for TOMORROW (BR)."""
        tomorrow = _tomorrow_br_iso()
        payload = {
            "client_name": "TEST_LOUSA Cliente Amanha",
            "address": "Rua Teste, 2",
            "neighborhood": "Centro",
            "phone": "21999999998",
            "type": "reparo",
            "priority": "horario",
            "scheduled_time": f"{tomorrow}T14:00:00+00:00",
            "assigned_collaborator_id": COLLAB_ID,
            "relato": "iter49 tomorrow ticket — should NOT appear today",
            "pppoe_user": "TEST",
            "test_history": [],
        }
        r = requests.post(
            f"{BASE_URL}/api/lousa/tickets",
            headers=admin_headers, json=payload, timeout=15,
        )
        assert r.status_code == 200, r.text
        tid = r.json()["id"]
        yield tid
        requests.delete(f"{BASE_URL}/api/lousa/tickets/{tid}",
                        headers=admin_headers, timeout=15)

    def test_today_ticket_appears_in_collaborator_lousa(self, today_ticket_id):
        r = requests.get(
            f"{BASE_URL}/api/lousa/by-collaborator/{COLLAB_ID}", timeout=15,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        if not d.get("lousa_unlocked", True) and d.get("needs_clock_in"):
            pytest.skip("Collaborator needs clock-in; cannot verify today filter")
        ids = [t["id"] for t in d.get("tickets", [])]
        assert today_ticket_id in ids, f"today ticket {today_ticket_id} missing"

    def test_tomorrow_ticket_filtered_out(self, tomorrow_ticket_id):
        r = requests.get(
            f"{BASE_URL}/api/lousa/by-collaborator/{COLLAB_ID}", timeout=15,
        )
        d = r.json()
        if not d.get("lousa_unlocked", True) and d.get("needs_clock_in"):
            pytest.skip("Collaborator needs clock-in; cannot verify date filter")
        ids = [t["id"] for t in d.get("tickets", [])]
        assert tomorrow_ticket_id not in ids, (
            f"tomorrow ticket {tomorrow_ticket_id} leaked into today's lousa"
        )

    def test_reagendar_keeps_pendente_and_moves_to_new_day(
        self, admin_headers, today_ticket_id
    ):
        tomorrow = _tomorrow_br_iso()
        # admin-close with reagendar + new_date+new_time
        payload = {
            "action": "reagendar",
            "new_date": tomorrow,
            "new_time": "10:00",
            "notes": "iter49 reschedule test",
        }
        r = requests.post(
            f"{BASE_URL}/api/lousa/tickets/{today_ticket_id}/admin-close",
            headers=admin_headers, json=payload, timeout=15,
        )
        assert r.status_code in (200, 204), r.text

        # Fetch ticket directly to verify status + fields
        r2 = requests.get(
            f"{BASE_URL}/api/lousa/tickets/{today_ticket_id}",
            headers=admin_headers, timeout=15,
        )
        assert r2.status_code == 200, r2.text
        t = r2.json()
        assert t["status"] == "pendente", f"expected pendente, got {t['status']}"
        assert t.get("rescheduled_at"), "rescheduled_at not set"
        assert (t.get("reschedule_count") or 0) >= 1
        assert tomorrow in str(t.get("scheduled_time", ""))

        # And: ticket should now be FILTERED OUT from today's lousa
        time.sleep(0.5)
        r3 = requests.get(
            f"{BASE_URL}/api/lousa/by-collaborator/{COLLAB_ID}", timeout=15,
        )
        d = r3.json()
        ids = [t["id"] for t in d.get("tickets", [])]
        assert today_ticket_id not in ids, (
            "after reagendar to tomorrow, ticket still in today's lousa"
        )

    def test_cancelar_marks_cancelada(self, admin_headers):
        """Sanity: cancelar still resolves to 'cancelada'."""
        today = _today_br_iso()
        r = requests.post(
            f"{BASE_URL}/api/lousa/tickets",
            headers=admin_headers,
            json={
                "client_name": "TEST_LOUSA Cancelar",
                "address": "Rua X, 9",
                "neighborhood": "Centro",
                "phone": "21988888888",
                "type": "reparo",
                "priority": "horario",
                "scheduled_time": f"{today}T15:00:00+00:00",
                "assigned_collaborator_id": COLLAB_ID,
                "relato": "iter49 cancel test",
                "pppoe_user": "TEST",
                "test_history": [],
            },
            timeout=15,
        )
        assert r.status_code == 200
        tid = r.json()["id"]
        try:
            r2 = requests.post(
                f"{BASE_URL}/api/lousa/tickets/{tid}/admin-close",
                headers=admin_headers,
                json={"action": "cancelar", "notes": "test cancel"},
                timeout=15,
            )
            assert r2.status_code in (200, 204), r2.text
            r3 = requests.get(
                f"{BASE_URL}/api/lousa/tickets/{tid}",
                headers=admin_headers, timeout=15,
            )
            assert r3.json()["status"] == "cancelada"
        finally:
            requests.delete(f"{BASE_URL}/api/lousa/tickets/{tid}",
                            headers=admin_headers, timeout=15)

    def test_encerrar_marks_encerrada(self, admin_headers):
        """Sanity: encerrar still resolves to 'encerrada'."""
        today = _today_br_iso()
        r = requests.post(
            f"{BASE_URL}/api/lousa/tickets",
            headers=admin_headers,
            json={
                "client_name": "TEST_LOUSA Encerrar",
                "address": "Rua Y, 10",
                "neighborhood": "Centro",
                "phone": "21977777777",
                "type": "reparo",
                "priority": "horario",
                "scheduled_time": f"{today}T16:00:00+00:00",
                "assigned_collaborator_id": COLLAB_ID,
                "relato": "iter49 encerrar test",
                "pppoe_user": "TEST",
                "test_history": [],
            },
            timeout=15,
        )
        assert r.status_code == 200
        tid = r.json()["id"]
        try:
            r2 = requests.post(
                f"{BASE_URL}/api/lousa/tickets/{tid}/admin-close",
                headers=admin_headers,
                json={"action": "encerrar", "notes": "test encerrar"},
                timeout=15,
            )
            assert r2.status_code in (200, 204), r2.text
            r3 = requests.get(
                f"{BASE_URL}/api/lousa/tickets/{tid}",
                headers=admin_headers, timeout=15,
            )
            assert r3.json()["status"] == "encerrada"
        finally:
            requests.delete(f"{BASE_URL}/api/lousa/tickets/{tid}",
                            headers=admin_headers, timeout=15)
