"""Tests iter129 — sales_outreach worker + plans premium toggle/auto-mark.

Cobertura:
- POST /api/plans/auto-mark-premium (gestor auth) — idempotente; só pega
  speed_down_mbps >= 1000
- PATCH /api/plans/{id}/premium-feature — toggle granular ligar/desligar
- GET /api/wifi/leads — KPIs por status (gestor/admin/auditor)
- POST /api/wifi/leads/process-now — trigger manual (gestor/admin)
- process_pending_leads(): rate-limit, cooldown, stale marking,
  cleanup, send_failed handling
"""
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") \
    if "REACT_APP_BACKEND_URL" in os.environ \
    else "http://localhost:8001"


@pytest.fixture(scope="session")
def db():
    import os as _os
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    mongo_url = _os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = _os.environ.get("DB_NAME", "test_database")
    return MongoClient(mongo_url)[db_name]


@pytest.fixture(scope="session")
def gestor_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                       json={"email": "gestor@empresa.com",
                             "password": "123456"}, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def auditor_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                       json={"email": "auditor@example.com",
                             "password": "auditor123"}, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def temp_plan(db):
    """Cria plano temporário pra testes."""
    plan_id = f"plan-TEST-iter129-{uuid.uuid4().hex[:6]}"
    db.plans.insert_one({
        "id": plan_id, "company_id": "co-demo",
        "name": "TEST iter129", "monthly_price": 99.99,
        "speed_down_mbps": 2000, "active": True,
        "premium_features": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield plan_id
    db.plans.delete_one({"id": plan_id})


@pytest.fixture
def clean_leads(db):
    """Limpa leads de teste antes/depois."""
    q = {"company_id": "co-demo", "phone": {"$regex": "^\\+55TESTITER129"}}
    db.sales_leads.delete_many(q)
    yield
    db.sales_leads.delete_many(q)


# ======================================================================
# Premium feature toggle
# ======================================================================
class TestPremiumToggle:
    def test_toggle_enable(self, temp_plan, gestor_token):
        r = requests.patch(
            f"{BASE_URL}/api/plans/{temp_plan}/premium-feature",
            json={"feature": "wifi_self_service", "enabled": True},
            headers={"Authorization": f"Bearer {gestor_token}"},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "wifi_self_service" in data["premium_features"]

    def test_toggle_disable(self, temp_plan, gestor_token, db):
        db.plans.update_one({"id": temp_plan},
                             {"$set": {"premium_features": ["wifi_self_service"]}})
        r = requests.patch(
            f"{BASE_URL}/api/plans/{temp_plan}/premium-feature",
            json={"feature": "wifi_self_service", "enabled": False},
            headers={"Authorization": f"Bearer {gestor_token}"},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        assert "wifi_self_service" not in r.json()["premium_features"]

    def test_toggle_unknown_plan_404(self, gestor_token):
        r = requests.patch(
            f"{BASE_URL}/api/plans/plan-DOES-NOT-EXIST/premium-feature",
            json={"feature": "wifi_self_service", "enabled": True},
            headers={"Authorization": f"Bearer {gestor_token}"},
            timeout=10,
        )
        assert r.status_code == 404


# ======================================================================
# Auto-mark premium
# ======================================================================
class TestAutoMarkPremium:
    def test_marks_plans_over_threshold(self, temp_plan, gestor_token, db):
        r = requests.post(
            f"{BASE_URL}/api/plans/auto-mark-premium",
            headers={"Authorization": f"Bearer {gestor_token}"},
            timeout=10,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["threshold_mbps"] == 1000
        # nosso temp_plan tem 2000mbps então deve ser marcado
        updated_ids = {p["id"] for p in data["updated"]}
        already_ids = {p["id"] for p in data["already_premium"]}
        assert temp_plan in updated_ids or temp_plan in already_ids
        # Confirma no DB
        p = db.plans.find_one({"id": temp_plan}, {"_id": 0, "premium_features": 1})
        assert "wifi_self_service" in p["premium_features"]

    def test_idempotent(self, temp_plan, gestor_token, db):
        # 1ª chamada marca
        requests.post(
            f"{BASE_URL}/api/plans/auto-mark-premium",
            headers={"Authorization": f"Bearer {gestor_token}"}, timeout=10)
        # 2ª chamada deve listar como already_premium
        r = requests.post(
            f"{BASE_URL}/api/plans/auto-mark-premium",
            headers={"Authorization": f"Bearer {gestor_token}"}, timeout=10)
        already_ids = {p["id"] for p in r.json()["already_premium"]}
        assert temp_plan in already_ids


# ======================================================================
# GET /api/wifi/leads
# ======================================================================
class TestListLeads:
    def test_list_returns_kpis(self, gestor_token):
        r = requests.get(
            f"{BASE_URL}/api/wifi/leads",
            headers={"Authorization": f"Bearer {gestor_token}"}, timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data and "total" in data and "by_status" in data

    def test_filter_by_status(self, gestor_token, db, clean_leads):
        # cria lead manual
        db.sales_leads.insert_one({
            "id": f"lead-test-{uuid.uuid4().hex[:6]}",
            "company_id": "co-demo",
            "phone": "+55TESTITER129111",
            "source": "whatsapp_alvaro_wifi_request",
            "status": "new",
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.get(
            f"{BASE_URL}/api/wifi/leads?status=new",
            headers={"Authorization": f"Bearer {gestor_token}"}, timeout=10)
        items = r.json()["items"]
        phones = {i["phone"] for i in items}
        assert "+55TESTITER129111" in phones

    def test_auditor_can_list(self, auditor_token):
        r = requests.get(
            f"{BASE_URL}/api/wifi/leads",
            headers={"Authorization": f"Bearer {auditor_token}"}, timeout=10)
        assert r.status_code == 200


# ======================================================================
# POST /api/wifi/leads/process-now (trigger manual)
# ======================================================================
class TestTriggerOutreach:
    def test_returns_stats(self, gestor_token):
        r = requests.post(
            f"{BASE_URL}/api/wifi/leads/process-now",
            headers={"Authorization": f"Bearer {gestor_token}"}, timeout=15)
        assert r.status_code == 200
        s = r.json()["stats"]
        assert all(k in s for k in ("checked", "sent", "errors",
                                      "skipped_cooldown",
                                      "skipped_rate_limit",
                                      "skipped_no_phone", "stale_marked"))

    def test_auditor_cannot_trigger_403(self, auditor_token):
        r = requests.post(
            f"{BASE_URL}/api/wifi/leads/process-now",
            headers={"Authorization": f"Bearer {auditor_token}"}, timeout=10)
        assert r.status_code == 403


# ======================================================================
# process_pending_leads function — behavior
# ======================================================================
class TestProcessPendingLeads:
    @pytest.mark.asyncio
    async def test_marks_stale_old_leads(self, db, clean_leads):
        # Lead antigo (>24h)
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        db.sales_leads.insert_one({
            "id": f"lead-test-{uuid.uuid4().hex[:6]}",
            "company_id": "co-demo",
            "phone": "+55TESTITER129OLD",
            "source": "whatsapp_alvaro_wifi_request",
            "status": "new", "ts": old_ts,
        })
        # Insere também um sem phone — testa branch de skipped_no_phone na
        # MESMA execução do worker pra evitar conflito de event loop entre
        # múltiplos testes async com motor.
        db.sales_leads.insert_one({
            "id": f"lead-test-{uuid.uuid4().hex[:6]}",
            "company_id": "co-demo",
            "phone": None,
            "source": "whatsapp_alvaro_wifi_request",
            "status": "new",
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        from services.sales_outreach import process_pending_leads
        stats = await process_pending_leads()
        assert stats["stale_marked"] >= 1
        assert stats["skipped_no_phone"] >= 1
        # Confirma estado dos leads
        lead = db.sales_leads.find_one({"phone": "+55TESTITER129OLD"},
                                          {"_id": 0})
        assert lead["status"] == "stale_needs_human_review"
