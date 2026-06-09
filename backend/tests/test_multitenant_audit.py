"""Testes FASE 8 — Multi-tenant blindagem."""
from __future__ import annotations
import asyncio, os, sys
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CO_A = "test-mt-A"
CO_B = "test-mt-B"
ALL = [CO_A, CO_B]


def _run(coro):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import database as dm
        dm.db = db
        import importlib
        from services import multitenant_audit as mt
        importlib.reload(mt)
        for col in ("subscribers", "tickets", "motor_ia_events",
                     "motor_ia_actions"):
            await db[col].delete_many({"company_id": {"$in": ALL}})
            await db[col].delete_many({"_test_mt": True})
        try:
            return await coro(db, mt)
        finally:
            for col in ("subscribers", "tickets", "motor_ia_events",
                         "motor_ia_actions"):
                await db[col].delete_many({"company_id": {"$in": ALL}})
                await db[col].delete_many({"_test_mt": True})
            c.close()
    return asyncio.run(_wrap())


def test_audit_orphans_detects_missing_company_id():
    async def go(db, mt):
        await db.motor_ia_events.insert_one(
            {"_test_mt": True, "event_type": "x"})  # sem company_id
        await db.motor_ia_events.insert_one(
            {"_test_mt": True, "company_id": "", "event_type": "y"})
        await db.motor_ia_events.insert_one(
            {"_test_mt": True, "company_id": CO_A, "event_type": "z"})
        r = await mt.audit_orphans()
        # detectar pelo menos 2 órfãos em motor_ia_events
        ev = [d for d in r["details"] if d["collection"] == "motor_ia_events"]
        assert ev and ev[0]["orphan"] >= 2
    _run(go)


def test_leak_risk_detects_cross_tenant_reference():
    async def go(db, mt):
        await db.subscribers.insert_one(
            {"id": "sub-leak", "company_id": CO_B,
             "name": "Cross tenant sub"})
        await db.tickets.insert_one(
            {"id": "tk-leak", "company_id": CO_A,
             "client_id": "sub-leak", "status": "aberta"})
        r = await mt.leak_risk_scan()
        assert r["cross_tenant_refs"] >= 1
        assert r["status"] == "VAZAMENTO"
    _run(go)


def test_full_audit_aggregates_all():
    async def go(db, mt):
        r = await mt.full_audit()
        for k in ("headline", "orphans", "tenants", "leak_risk"):
            assert k in r
    _run(go)


def test_tenants_distribution_lists_companies():
    async def go(db, mt):
        for i in range(3):
            await db.subscribers.insert_one(
                {"id": f"s-a-{i}", "company_id": CO_A})
        for i in range(2):
            await db.subscribers.insert_one(
                {"id": f"s-b-{i}", "company_id": CO_B})
        r = await mt.tenants_distribution()
        ids = {x["company_id"] for x in r["items"]}
        assert CO_A in ids and CO_B in ids
    _run(go)
