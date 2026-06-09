"""Testes FASE 11 — Financial Foundation (V5.0)."""
from __future__ import annotations
import asyncio, os, sys
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CO = "test-fin-pytest"


def _run(coro):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import database as dm
        dm.db = db
        import importlib
        from services import financial_foundation as fin
        importlib.reload(fin)
        for col in ("subscribers", "subscriber_invoices",
                     "motor_ia_subscriber_scores",
                     "motor_ia_revenue_attribution"):
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro(db, fin)
        finally:
            for col in ("subscribers", "subscriber_invoices",
                         "motor_ia_subscriber_scores",
                         "motor_ia_revenue_attribution"):
                await db[col].delete_many({"company_id": CO})
            c.close()
    return asyncio.run(_wrap())


def test_mrr_sums_active_subscriber_plan_prices():
    async def go(db, fin):
        for i, price in enumerate([99.9, 149.9, 79.9]):
            await db.subscribers.insert_one({
                "id": f"s-{i}", "company_id": CO, "status": "ATIVO",
                "plan_price": price})
        # cancelado deve ser ignorado
        await db.subscribers.insert_one({
            "id": "s-cancel", "company_id": CO, "status": "INATIVO",
            "plan_price": 999})
        r = await fin.mrr(CO)
        assert r["active_subscribers"] == 3
        assert abs(r["mrr_BRL"] - 329.7) < 0.1
    _run(go)


def test_arr_equals_mrr_times_12():
    async def go(db, fin):
        await db.subscribers.insert_one({
            "id": "s-1", "company_id": CO, "status": "ATIVO",
            "plan_price": 100})
        r = await fin.arr(CO)
        assert r["arr_BRL"] == 1200.0
    _run(go)


def test_revenue_at_risk_from_isabella_and_onu():
    async def go(db, fin):
        await db.subscribers.insert_many([
            {"id": "high-churn", "company_id": CO, "status": "ATIVO",
             "plan_price": 99.9, "smartolt_onu_status": "Online"},
            {"id": "onu-bad", "company_id": CO, "status": "ATIVO",
             "plan_price": 149.9, "smartolt_onu_status": "Offline"},
            {"id": "safe", "company_id": CO, "status": "ATIVO",
             "plan_price": 200, "smartolt_onu_status": "Online"},
        ])
        await db.motor_ia_subscriber_scores.insert_one({
            "company_id": CO, "subscriber_id": "high-churn",
            "churn_score": 0.85})
        r = await fin.revenue_at_risk(CO)
        assert r["subscribers_at_risk"] == 2
        assert abs(r["monthly_BRL_at_risk"] - (99.9 + 149.9)) < 0.1
        assert r["sources"]["isabella_churn_high"] == 1
        assert r["sources"]["onu_degraded"] == 1
    _run(go)


def test_overdue_summary():
    async def go(db, fin):
        for i in range(3):
            await db.subscriber_invoices.insert_one({
                "id": f"inv-{i}", "company_id": CO, "amount": 100,
                "status": "overdue"})
        r = await fin.overdue_summary(CO)
        assert r["overdue_count"] == 3
        assert r["overdue_BRL"] == 300.0
    _run(go)


def test_summary_returns_executive_payload():
    async def go(db, fin):
        await db.subscribers.insert_one({
            "id": "s-1", "company_id": CO, "status": "ATIVO",
            "plan_price": 100})
        r = await fin.summary(CO)
        for k in ("headline", "mrr", "arr", "ltv", "revenue_at_risk",
                  "churn_cost_90d", "overdue", "collected_mtd",
                  "revenue_protected_BRL", "executive_actions"):
            assert k in r
        assert r["mrr"]["mrr_BRL"] == 100.0
    _run(go)
