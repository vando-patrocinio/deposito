"""
iter97 — Backend tests for active reconciliation:
POST /api/financeiro/bank-import/reconcile-payments
POST /api/financeiro/bank-import/reconcile-confirm

Tests cover:
1. Seed → run with auto_mark=true → invoice becomes paid + movement reconciled.
2. Idempotency: second run excludes already-reconciled movements.
3. CPF resolution via subscriber.external_code when invoice has no document.
4. Manual reconcile-confirm path.
5. Endpoint returns expected stats / orphans structure.
"""
import os
import uuid
from datetime import datetime, timedelta

import pytest
import requests

def _load_base_url():
    v = os.environ.get("REACT_APP_BACKEND_URL", "")
    if not v:
        try:
            with open("/app/frontend/.env") as fh:
                for line in fh:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        v = line.split("=", 1)[1].strip()
                        break
        except FileNotFoundError:
            pass
    return v.rstrip("/")


BASE_URL = _load_base_url()
DEMO_CID = "co-demo"

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
               timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    body = r.json()
    token = body.get("token") or body.get("access_token")
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


# ---------- direct mongo helpers (insert seed) ----------
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

def _load_env_var(name):
    v = os.environ.get(name, "")
    if not v:
        for path in ("/app/backend/.env", "/app/frontend/.env"):
            try:
                with open(path) as fh:
                    for line in fh:
                        if line.startswith(name + "="):
                            v = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
                if v:
                    break
            except FileNotFoundError:
                pass
    return v


MONGO_URL = _load_env_var("MONGO_URL") or "mongodb://localhost:27017"
DB_NAME = _load_env_var("DB_NAME") or "test_database"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _pick_real_subscriber():
    cli = AsyncIOMotorClient(MONGO_URL)
    try:
        db = cli[DB_NAME]
        s = await db.subscribers.find_one(
            {"company_id": DEMO_CID,
             "document": {"$nin": [None, ""]}},
            {"_id": 0, "id": 1, "external_code": 1,
             "document": 1, "name": 1},
        )
        return s
    finally:
        cli.close()


async def _insert_seed(doc_digits, amount, mov_date, due_date,
                       invoice_external=None, with_doc_in_invoice=True,
                       sub_external_code=None, name="TEST_RECON"):
    cli = AsyncIOMotorClient(MONGO_URL)
    try:
        db = cli[DB_NAME]
        mov_id = f"TEST_mov_{uuid.uuid4().hex[:8]}"
        inv_id = f"TEST_inv_{uuid.uuid4().hex[:8]}"
        mov = {
            "id": mov_id, "company_id": DEMO_CID, "type": "income",
            "source": "bank_import_sicoob", "amount": amount,
            "date": mov_date,
            "description": f"PIX RECEBIDO {name} CPF {doc_digits}",
            "created_at": datetime.utcnow().isoformat(),
        }
        inv = {
            "id": inv_id, "company_id": DEMO_CID, "status": "open",
            "amount": amount, "due_date": due_date,
            "subscriber_name": name,
            "external_id": invoice_external or f"EXT-{uuid.uuid4().hex[:6]}",
            "description": "TEST reconcile",
        }
        if with_doc_in_invoice:
            inv["subscriber_document"] = doc_digits
        if sub_external_code:
            inv["subscriber_external_id"] = sub_external_code
        await db.fin_cash_movements.insert_one(mov)
        await db.subscriber_invoices.insert_one(inv)
        return mov_id, inv_id
    finally:
        cli.close()


async def _cleanup(mov_id, inv_id):
    cli = AsyncIOMotorClient(MONGO_URL)
    try:
        db = cli[DB_NAME]
        if mov_id:
            await db.fin_cash_movements.delete_one(
                {"id": mov_id, "company_id": DEMO_CID})
        if inv_id:
            await db.subscriber_invoices.delete_one(
                {"id": inv_id, "company_id": DEMO_CID})
    finally:
        cli.close()


async def _read_invoice(inv_id):
    cli = AsyncIOMotorClient(MONGO_URL)
    try:
        db = cli[DB_NAME]
        return await db.subscriber_invoices.find_one(
            {"id": inv_id, "company_id": DEMO_CID}, {"_id": 0})
    finally:
        cli.close()


async def _read_movement(mov_id):
    cli = AsyncIOMotorClient(MONGO_URL)
    try:
        db = cli[DB_NAME]
        return await db.fin_cash_movements.find_one(
            {"id": mov_id, "company_id": DEMO_CID}, {"_id": 0})
    finally:
        cli.close()


# ---------- helpers ----------
def _period_around(d):
    dt = datetime.strptime(d, "%Y-%m-%d")
    return ((dt - timedelta(days=5)).strftime("%Y-%m-%d"),
            (dt + timedelta(days=5)).strftime("%Y-%m-%d"))


# ---------- tests ----------
class TestReconcilePayments:

    def test_endpoint_reachable_empty_period(self, session):
        """Smoke: /reconcile-payments responds with stats structure."""
        # period in the far past — no movements expected
        r = session.post(
            f"{BASE_URL}/api/financeiro/bank-import/reconcile-payments"
            f"?from_date=2020-01-01&to_date=2020-01-31&auto_mark=false",
            timeout=60,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("auto_marked", "pending", "pix_orphans",
                  "invoices_orphans", "stats"):
            assert k in body, f"missing key {k}"
        st = body["stats"]
        for k in ("bank_movements_in_period", "open_invoices_considered",
                  "auto_marked_count", "pending_count",
                  "pix_orphans_count", "invoices_orphans_count"):
            assert k in st

    def test_auto_mark_match_score_100(self, session):
        """Seed PIX+invoice with exact CPF+amount+same day → auto_marked=1,
        invoice flips to paid, movement gets reconciled_invoice_id."""
        sub = _run(_pick_real_subscriber())
        if not sub:
            pytest.skip("no real subscriber w/ document on co-demo")
        doc = sub["document"]
        digits = "".join(ch for ch in str(doc) if ch.isdigit())
        amount = round(99.0 + (datetime.utcnow().microsecond % 100) / 100, 2)
        mov_date = "2026-01-10"
        due_date = "2026-01-10"
        mov_id, inv_id = _run(_insert_seed(
            digits, amount, mov_date, due_date))
        try:
            f, t = _period_around(mov_date)
            r = session.post(
                f"{BASE_URL}/api/financeiro/bank-import/reconcile-payments"
                f"?from_date={f}&to_date={t}&auto_mark=true",
                timeout=60,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            matched_movs = [m["movement"]["id"]
                            for m in body["auto_marked"]]
            assert mov_id in matched_movs, (
                f"expected mov {mov_id} in auto_marked. "
                f"stats={body['stats']}")
            picked = next(m for m in body["auto_marked"]
                          if m["movement"]["id"] == mov_id)
            assert picked["score"] == 100
            assert picked["invoice"]["id"] == inv_id

            inv = _run(_read_invoice(inv_id))
            assert inv["status"] == "paid"
            assert inv.get("paid_method") == "auto_reconciliation"
            assert inv.get("reconciled_movement_id") == mov_id

            mov = _run(_read_movement(mov_id))
            assert mov.get("reconciled_invoice_id") == inv_id
        finally:
            _run(_cleanup(mov_id, inv_id))

    def test_idempotent_second_run_skips_reconciled(self, session):
        """Run reconcile twice → 2nd run movement should be excluded."""
        sub = _run(_pick_real_subscriber())
        if not sub:
            pytest.skip("no real subscriber")
        digits = "".join(ch for ch in str(sub["document"]) if ch.isdigit())
        amount = round(50.0 + (datetime.utcnow().microsecond % 100) / 100, 2)
        mov_date = "2026-01-12"
        mov_id, inv_id = _run(_insert_seed(
            digits, amount, mov_date, mov_date))
        try:
            f, t = _period_around(mov_date)
            url = (f"{BASE_URL}/api/financeiro/bank-import/"
                   f"reconcile-payments?from_date={f}&to_date={t}"
                   f"&auto_mark=true")
            r1 = session.post(url, timeout=60).json()
            ids1 = [m["movement"]["id"] for m in r1["auto_marked"]]
            assert mov_id in ids1
            r2 = session.post(url, timeout=60).json()
            ids2 = [m["movement"]["id"] for m in r2["auto_marked"]]
            ids2 += [m["movement"]["id"] for m in r2["pending"]]
            orph = [o["id"] for o in r2["pix_orphans"]]
            assert mov_id not in ids2, "mov re-matched on 2nd run"
            assert mov_id not in orph, "mov leaked into orphans"
        finally:
            _run(_cleanup(mov_id, inv_id))

    def test_resolves_doc_via_subscriber_external_code(self, session):
        """Invoice without subscriber_document but with subscriber_external_id
        pointing to a subscriber with document → should still match."""
        sub = _run(_pick_real_subscriber())
        if not sub:
            pytest.skip("no real subscriber")
        if not sub.get("external_code"):
            pytest.skip("subscriber has no external_code")
        digits = "".join(ch for ch in str(sub["document"]) if ch.isdigit())
        ext = sub["external_code"].replace("ATLAZ-", "")
        amount = round(77.0 + (datetime.utcnow().microsecond % 100) / 100, 2)
        mov_date = "2026-01-14"
        mov_id, inv_id = _run(_insert_seed(
            digits, amount, mov_date, mov_date,
            with_doc_in_invoice=False, sub_external_code=ext))
        try:
            f, t = _period_around(mov_date)
            r = session.post(
                f"{BASE_URL}/api/financeiro/bank-import/reconcile-payments"
                f"?from_date={f}&to_date={t}&auto_mark=true",
                timeout=60,
            ).json()
            matched = [m["movement"]["id"] for m in r["auto_marked"]]
            assert mov_id in matched, (
                f"failed external_code lookup. stats={r['stats']}")
        finally:
            _run(_cleanup(mov_id, inv_id))

    def test_reconcile_confirm_manual_match(self, session):
        """auto_mark=false → pending; then reconcile-confirm marks paid."""
        sub = _run(_pick_real_subscriber())
        if not sub:
            pytest.skip("no real subscriber")
        digits = "".join(ch for ch in str(sub["document"]) if ch.isdigit())
        amount = round(33.0 + (datetime.utcnow().microsecond % 100) / 100, 2)
        mov_date = "2026-01-16"
        mov_id, inv_id = _run(_insert_seed(
            digits, amount, mov_date, mov_date))
        try:
            f, t = _period_around(mov_date)
            r = session.post(
                f"{BASE_URL}/api/financeiro/bank-import/reconcile-payments"
                f"?from_date={f}&to_date={t}&auto_mark=false",
                timeout=60,
            ).json()
            pending_ids = [m["movement"]["id"] for m in r["pending"]]
            auto_ids = [m["movement"]["id"] for m in r["auto_marked"]]
            assert mov_id in pending_ids or mov_id in auto_ids
            # confirm always works whether it was pending or auto_marked
            cr = session.post(
                f"{BASE_URL}/api/financeiro/bank-import/reconcile-confirm",
                json={"matches": [{"movement_id": mov_id,
                                   "invoice_id": inv_id}]},
                timeout=30,
            )
            assert cr.status_code == 200, cr.text
            body = cr.json()
            assert body.get("ok") is True
            assert body.get("approved") >= 1

            inv = _run(_read_invoice(inv_id))
            assert inv["status"] == "paid"
            mov = _run(_read_movement(mov_id))
            assert mov.get("reconciled_invoice_id") == inv_id
        finally:
            _run(_cleanup(mov_id, inv_id))

    def test_orphans_capped(self, session):
        """When no matches exist, ensure orphan arrays are capped 200/300."""
        r = session.post(
            f"{BASE_URL}/api/financeiro/bank-import/reconcile-payments"
            f"?from_date=2025-01-01&to_date=2026-12-31&auto_mark=false",
            timeout=90,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["pix_orphans"]) <= 200
        assert len(body["invoices_orphans"]) <= 300
