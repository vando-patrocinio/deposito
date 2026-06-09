"""test_v7_1.py — V7.1 G1 Action→Cash via invoices."""
from __future__ import annotations
import asyncio, importlib, os, sys, uuid
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
CO = "test-v71-co"
COLLS = ["subscribers", "subscriber_invoices",
         "motor_ia_outcomes", "motor_ia_actions",
         "motor_ia_learnings"]


def _run(coro):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import database as dm; dm.db = db
        from services import v7_1_backfill, company_v6
        importlib.reload(company_v6); importlib.reload(v7_1_backfill)
        for col in COLLS:
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro(db, v7_1_backfill)
        finally:
            for col in COLLS:
                await db[col].delete_many({"company_id": CO})
            c.close()
    return asyncio.new_event_loop().run_until_complete(_wrap())


def _id(p): return f"{p}-{uuid.uuid4().hex[:8]}"


def test_dry_run_doesnt_change_outcomes():
    async def t(db, bf):
        ext = "EXT-123"
        sid = _id("sub")
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO, "external_code": ext})
        await db.subscriber_invoices.insert_one({
            "id": _id("inv"), "company_id": CO,
            "subscriber_external_id": ext, "status": "paid",
            "amount_paid": 100.0, "amount": 100.0})
        oid = _id("out")
        await db.motor_ia_outcomes.insert_one({
            "id": oid, "company_id": CO, "subscriber_id": sid,
            "environment": "production", "status": "executed",
            "expected_BRL": 100.0, "actual_BRL": 0,
            "observed_at": datetime.now(timezone.utc).isoformat()})
        out = await bf.backfill_action_to_cash(CO, dry_run=True)
        assert out["outcomes_marked_received"] == 1
        assert out["total_recovered_BRL"] == 100.0
        # NÃO marcou de fato
        oc = await db.motor_ia_outcomes.find_one({"id": oid})
        assert oc["actual_BRL"] == 0
        assert oc["status"] == "executed"
    _run(t)


def test_real_run_marks_outcome_received():
    async def t(db, bf):
        ext = "EXT-R"
        sid = _id("sub")
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO, "external_code": ext})
        inv_id = _id("inv")
        await db.subscriber_invoices.insert_one({
            "id": inv_id, "company_id": CO,
            "subscriber_external_id": ext, "status": "paid",
            "amount_paid": 99.5, "amount": 100.0})
        oid = _id("out")
        await db.motor_ia_outcomes.insert_one({
            "id": oid, "company_id": CO, "subscriber_id": sid,
            "action_id": "act-1",
            "environment": "production", "status": "executed",
            "expected_BRL": 100.0, "actual_BRL": 0,
            "observed_at": datetime.now(timezone.utc).isoformat()})
        await db.motor_ia_actions.insert_one({
            "id": "act-1", "company_id": CO,
            "expected_BRL": 100, "status": "executed"})
        out = await bf.backfill_action_to_cash(CO, dry_run=False)
        assert out["outcomes_marked_received"] == 1
        assert out["total_recovered_BRL"] == 99.5
        oc = await db.motor_ia_outcomes.find_one({"id": oid})
        assert oc["status"] == "revenue_received"
        assert oc["actual_BRL"] == 99.5
        assert oc["revenue_source"] == "invoice_backfill_v7_1"
        assert oc["payment_ref"] == inv_id
        # Learning gravado
        lrn = await db.motor_ia_learnings.find_one(
            {"company_id": CO, "outcome_id": oid,
             "kind": "revenue_confirmation"})
        assert lrn is not None
    _run(t)


def test_homolog_outcomes_are_ignored():
    async def t(db, bf):
        ext = "EXT-H"
        sid = _id("sub")
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO, "external_code": ext})
        await db.subscriber_invoices.insert_one({
            "id": _id("inv"), "company_id": CO,
            "subscriber_external_id": ext, "status": "paid",
            "amount_paid": 100.0})
        await db.motor_ia_outcomes.insert_one({
            "id": _id("out"), "company_id": CO,
            "subscriber_id": sid,
            "environment": "homolog",  # PROIBIDO
            "status": "executed",
            "expected_BRL": 100.0, "actual_BRL": 0,
            "observed_at": datetime.now(timezone.utc).isoformat()})
        out = await bf.backfill_action_to_cash(CO, dry_run=False)
        assert out["outcomes_marked_received"] == 0
        assert out["skipped_no_outcome_match"] == 1
    _run(t)


def test_amount_mismatch_outside_tolerance_skips():
    async def t(db, bf):
        ext = "EXT-MM"
        sid = _id("sub")
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO, "external_code": ext})
        await db.subscriber_invoices.insert_one({
            "id": _id("inv"), "company_id": CO,
            "subscriber_external_id": ext, "status": "paid",
            "amount_paid": 10.0})  # 10 vs expected 100 = 10%
        await db.motor_ia_outcomes.insert_one({
            "id": _id("out"), "company_id": CO,
            "subscriber_id": sid, "environment": "production",
            "status": "executed",
            "expected_BRL": 100.0, "actual_BRL": 0,
            "observed_at": datetime.now(timezone.utc).isoformat()})
        out = await bf.backfill_action_to_cash(CO, dry_run=False)
        assert out["outcomes_marked_received"] == 0
        assert out["skipped_no_outcome_match"] == 1
    _run(t)
