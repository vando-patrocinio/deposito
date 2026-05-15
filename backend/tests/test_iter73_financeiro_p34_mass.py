"""Iter 73 — Tests for Financeiro Phase 3 (Bills+Cashflow), Phase 4 (Atlaz Financeiro),
and Mass Messaging (campaigns + CSV upload + preview + start/pause).
"""
from __future__ import annotations

import io
import os
import time

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


@pytest.fixture(scope="module")
def admin():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("token") or data.get("access_token")
    if tok:
        s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="module")
def cash_account(admin):
    """Cria/garante uma conta caixa para os testes."""
    payload = {"name": "TEST_CashAcct_Iter73", "opening_balance": 1000.0,
               "type": "checking", "active": True}
    r = admin.post(f"{BASE_URL}/api/financeiro/cash-accounts", json=payload, timeout=10)
    assert r.status_code in (200, 201), f"create cash account: {r.status_code} {r.text}"
    return r.json()


# ===========================================================================
# Financeiro Fase 3 — Bills (Contas a Pagar)
# ===========================================================================
class TestBills:
    bill_id = None

    def test_create_bill_pending(self, admin):
        # due_date no futuro -> pending
        payload = {"description": "TEST_Bill_Iter73 Internet",
                   "amount": 250.55,
                   "due_date": "2099-01-15"}
        r = admin.post(f"{BASE_URL}/api/financeiro/bills", json=payload, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "pending"
        assert body["amount"] == 250.55
        assert body["description"] == "TEST_Bill_Iter73 Internet"
        assert body.get("paid_at") is None
        TestBills.bill_id = body["id"]

    def test_create_bill_overdue(self, admin):
        payload = {"description": "TEST_Bill_Overdue",
                   "amount": 99.9, "due_date": "2000-01-01"}
        r = admin.post(f"{BASE_URL}/api/financeiro/bills", json=payload, timeout=10)
        assert r.status_code == 200
        assert r.json()["status"] == "overdue"

    def test_list_filter_status(self, admin):
        r = admin.get(f"{BASE_URL}/api/financeiro/bills?status=pending", timeout=10)
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list)
        assert all(b["status"] == "pending" for b in items)

    def test_update_bill(self, admin):
        bid = TestBills.bill_id
        r = admin.put(f"{BASE_URL}/api/financeiro/bills/{bid}",
                      json={"notes": "updated note iter73"}, timeout=10)
        assert r.status_code == 200
        assert r.json()["notes"] == "updated note iter73"

    def test_pay_bill_creates_movement_and_updates_balance(self, admin, cash_account):
        bid = TestBills.bill_id
        cash_id = cash_account["id"]
        # get balance before
        r0 = admin.get(f"{BASE_URL}/api/financeiro/cash-accounts", timeout=10)
        assert r0.status_code == 200
        balance_before = next(a["current_balance"] for a in r0.json() if a["id"] == cash_id)

        r = admin.post(f"{BASE_URL}/api/financeiro/bills/{bid}/pay",
                       json={"cash_account_id": cash_id}, timeout=10)
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["ok"] is True
        assert out["movement"]["type"] == "expense"
        assert out["movement"]["amount"] == 250.55

        # bill agora 'paid'
        r2 = admin.get(f"{BASE_URL}/api/financeiro/bills?status=paid", timeout=10)
        assert any(b["id"] == bid and b.get("paid_at") for b in r2.json())

        # saldo decrementado
        r3 = admin.get(f"{BASE_URL}/api/financeiro/cash-accounts", timeout=10)
        balance_after = next(a["current_balance"] for a in r3.json() if a["id"] == cash_id)
        assert round(balance_before - balance_after, 2) == 250.55

    def test_pay_bill_already_paid_returns_400(self, admin, cash_account):
        bid = TestBills.bill_id
        r = admin.post(f"{BASE_URL}/api/financeiro/bills/{bid}/pay",
                       json={"cash_account_id": cash_account["id"]}, timeout=10)
        assert r.status_code == 400

    def test_delete_paid_bill_reverses_balance(self, admin, cash_account):
        bid = TestBills.bill_id
        cash_id = cash_account["id"]
        r0 = admin.get(f"{BASE_URL}/api/financeiro/cash-accounts", timeout=10)
        b_before = next(a["current_balance"] for a in r0.json() if a["id"] == cash_id)
        r = admin.delete(f"{BASE_URL}/api/financeiro/bills/{bid}", timeout=10)
        assert r.status_code == 200
        r1 = admin.get(f"{BASE_URL}/api/financeiro/cash-accounts", timeout=10)
        b_after = next(a["current_balance"] for a in r1.json() if a["id"] == cash_id)
        assert round(b_after - b_before, 2) == 250.55  # estorno


# ===========================================================================
# Financeiro Fase 3 — Movements + Cashflow
# ===========================================================================
class TestMovements:
    mov_id = None

    def test_create_income_increments_balance(self, admin, cash_account):
        cash_id = cash_account["id"]
        r0 = admin.get(f"{BASE_URL}/api/financeiro/cash-accounts", timeout=10)
        before = next(a["current_balance"] for a in r0.json() if a["id"] == cash_id)
        payload = {"type": "income", "date": "2026-01-10",
                   "amount": 500.0, "cash_account_id": cash_id,
                   "description": "TEST_Income_Iter73"}
        r = admin.post(f"{BASE_URL}/api/financeiro/movements", json=payload, timeout=10)
        assert r.status_code == 200, r.text
        TestMovements.mov_id = r.json()["id"]
        r1 = admin.get(f"{BASE_URL}/api/financeiro/cash-accounts", timeout=10)
        after = next(a["current_balance"] for a in r1.json() if a["id"] == cash_id)
        assert round(after - before, 2) == 500.0

    def test_delete_movement_reverses(self, admin, cash_account):
        cash_id = cash_account["id"]
        r0 = admin.get(f"{BASE_URL}/api/financeiro/cash-accounts", timeout=10)
        before = next(a["current_balance"] for a in r0.json() if a["id"] == cash_id)
        r = admin.delete(f"{BASE_URL}/api/financeiro/movements/{TestMovements.mov_id}",
                         timeout=10)
        assert r.status_code == 200
        r1 = admin.get(f"{BASE_URL}/api/financeiro/cash-accounts", timeout=10)
        after = next(a["current_balance"] for a in r1.json() if a["id"] == cash_id)
        assert round(before - after, 2) == 500.0

    def test_cashflow_default_30d(self, admin):
        r = admin.get(f"{BASE_URL}/api/financeiro/cashflow", timeout=10)
        assert r.status_code == 200
        d = r.json()
        for k in ("series", "totals", "current_balance", "group_by",
                  "from_date", "to_date"):
            assert k in d
        assert d["group_by"] == "day"
        assert {"income", "expense", "net"} <= set(d["totals"].keys())


# ===========================================================================
# Atlaz Financeiro (Fase 4)
# ===========================================================================
class TestAtlazFinanceiro:
    def test_probe_returns_results(self, admin):
        r = admin.get(f"{BASE_URL}/api/atlaz-financeiro/probe", timeout=60)
        # 200 (token configurado) ou 400 (token ausente) — ambos aceitos
        assert r.status_code in (200, 400), r.text
        if r.status_code == 200:
            d = r.json()
            assert "endpoints" in d and isinstance(d["endpoints"], list)
            assert len(d["endpoints"]) == 5
            for ep in d["endpoints"]:
                assert {"endpoint", "http_status", "available"} <= set(ep.keys())

    def test_sync_now_tolerant(self, admin):
        r = admin.post(f"{BASE_URL}/api/atlaz-financeiro/sync-now", timeout=60)
        assert r.status_code in (200, 400), r.text
        if r.status_code == 200:
            d = r.json()
            for k in ("inserted", "updated", "errors"):
                assert k in d

    def test_invoices_fixed_schema(self, admin):
        r = admin.get(f"{BASE_URL}/api/atlaz-financeiro/invoices", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d and "total" in d
        assert isinstance(d["items"], list)

    def test_stats_fixed_schema(self, admin):
        r = admin.get(f"{BASE_URL}/api/atlaz-financeiro/stats", timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k in ("total_invoices", "by_status", "last_sync"):
            assert k in d


# ===========================================================================
# Mass Messaging
# ===========================================================================
class TestMassMessaging:
    camp_id = None

    def test_create_template_missing_template_name_400(self, admin):
        r = admin.post(f"{BASE_URL}/api/mass-messaging/campaigns",
                       json={"name": "TEST_camp_invalid_tpl",
                             "channel": "meta_cloud", "mode": "template"},
                       timeout=10)
        assert r.status_code == 400

    def test_create_free_missing_text_400(self, admin):
        r = admin.post(f"{BASE_URL}/api/mass-messaging/campaigns",
                       json={"name": "TEST_camp_invalid_free",
                             "channel": "meta_cloud", "mode": "free"},
                       timeout=10)
        assert r.status_code == 400

    def test_create_campaign_ok(self, admin):
        r = admin.post(f"{BASE_URL}/api/mass-messaging/campaigns",
                       json={"name": "TEST_Camp_Iter73",
                             "channel": "meta_cloud", "mode": "free",
                             "text": "Olá {{name}}, vencimento {{vencimento}}",
                             "throttle_per_min": 60},
                       timeout=10)
        assert r.status_code == 200, r.text
        c = r.json()
        assert c["status"] == "draft"
        assert c["total_recipients"] == 0
        TestMassMessaging.camp_id = c["id"]

    def test_start_without_recipients_400(self, admin):
        cid = TestMassMessaging.camp_id
        r = admin.post(f"{BASE_URL}/api/mass-messaging/campaigns/{cid}/start",
                       json={}, timeout=10)
        assert r.status_code == 400

    def test_upload_csv_normalizes_phones(self, admin):
        cid = TestMassMessaging.camp_id
        csv_content = (
            "phone,name,vencimento\n"
            "+5511999999999,Joao,12/12\n"
            "(11) 98888-7777,Maria,15/12\n"
            "abc-invalid,Bad,01/01\n"
            "21987654321,Carlos,20/12\n"
            "11955554444,Ana,22/12\n"
        )
        files = {"file": ("contacts.csv", io.BytesIO(csv_content.encode("utf-8")),
                          "text/csv")}
        # Need to remove Content-Type header for multipart
        s2 = requests.Session()
        for c in admin.cookies:
            s2.cookies.set(c.name, c.value)
        if "Authorization" in admin.headers:
            s2.headers["Authorization"] = admin.headers["Authorization"]
        r = s2.post(f"{BASE_URL}/api/mass-messaging/campaigns/{cid}/recipients/upload",
                    files=files, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["inserted"] == 4
        assert d["invalid"] == 1
        assert "phone" in [h.lower() for h in d["headers"]]

    def test_preview_renders_vars(self, admin):
        cid = TestMassMessaging.camp_id
        r = admin.get(f"{BASE_URL}/api/mass-messaging/campaigns/{cid}/preview",
                      timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert len(d["samples"]) <= 3
        assert len(d["samples"]) >= 1
        any_with_name = False
        for s in d["samples"]:
            # rendered_text deve substituir {{name}}
            assert "{{name}}" not in s["rendered_text"]
            if "Joao" in s["rendered_text"] or "Maria" in s["rendered_text"] \
               or "Carlos" in s["rendered_text"] or "Ana" in s["rendered_text"]:
                any_with_name = True
        assert any_with_name, f"samples: {d['samples']}"

    def test_start_campaign_running(self, admin):
        cid = TestMassMessaging.camp_id
        r = admin.post(f"{BASE_URL}/api/mass-messaging/campaigns/{cid}/start",
                       json={}, timeout=10)
        assert r.status_code == 200
        assert r.json()["status"] in ("running", "queued")

    def test_pause_resume_toggle(self, admin):
        cid = TestMassMessaging.camp_id
        r1 = admin.post(f"{BASE_URL}/api/mass-messaging/campaigns/{cid}/pause",
                        json={}, timeout=10)
        assert r1.status_code in (200, 400)  # may already be done
        r2 = admin.post(f"{BASE_URL}/api/mass-messaging/campaigns/{cid}/resume",
                        json={}, timeout=10)
        assert r2.status_code in (200, 400)

    def test_worker_marks_failed_after_30s(self, admin):
        """Worker deve rodar e marcar recipients como failed (Meta sem creds)."""
        cid = TestMassMessaging.camp_id
        # garante running
        admin.post(f"{BASE_URL}/api/mass-messaging/campaigns/{cid}/resume",
                   json={}, timeout=10)
        time.sleep(30)
        r = admin.get(f"{BASE_URL}/api/mass-messaging/campaigns/{cid}/recipients",
                      timeout=15)
        assert r.status_code == 200
        recs = r.json()
        # algum recipient deve ter saído da fila 'queued'
        non_queued = [r for r in recs if r["status"] != "queued"]
        assert len(non_queued) >= 1, f"Worker não processou nenhum recipient: {recs[:3]}"

    def test_cleanup_campaign(self, admin):
        cid = TestMassMessaging.camp_id
        if not cid:
            return
        admin.post(f"{BASE_URL}/api/mass-messaging/campaigns/{cid}/pause",
                   json={}, timeout=10)
        r = admin.delete(f"{BASE_URL}/api/mass-messaging/campaigns/{cid}", timeout=10)
        assert r.status_code in (200, 400, 404)


# ===========================================================================
# Cleanup
# ===========================================================================
def test_cleanup_cash_account(admin, cash_account):
    cid = cash_account["id"]
    r = admin.delete(f"{BASE_URL}/api/financeiro/cash-accounts/{cid}", timeout=10)
    assert r.status_code in (200, 204, 404)
