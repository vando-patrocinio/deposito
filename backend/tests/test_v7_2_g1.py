"""test_v7_2_g1.py — V7.2 G1 FIX
Cobre os 4 bugs cumulativos do revenue_realization=0:
 1) outcome usa `outcome_id` em vez de `id`
 2) outcome sem subscriber_id (resolver via action/decision)
 3) external_code prefixado ATLAZ- vs subscriber_external_id cru
 4) revenue_realization deve refletir invoices paid (truth source)
"""
from __future__ import annotations
import asyncio
import importlib
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CO = "test-v72-g1-co"
COLLS = [
    "subscribers", "subscriber_invoices",
    "motor_ia_outcomes", "motor_ia_actions",
    "motor_ia_decisions", "motor_ia_learnings",
]


def _run(coro):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import database as dm
        dm.db = db
        from services import v7_2_revenue
        importlib.reload(v7_2_revenue)
        for col in COLLS:
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro(db, v7_2_revenue)
        finally:
            for col in COLLS:
                await db[col].delete_many({"company_id": CO})
            c.close()
    return asyncio.new_event_loop().run_until_complete(_wrap())


def _id(p):
    return f"{p}-{uuid.uuid4().hex[:8]}"


# ───────── BUG #3: external_code prefixado ─────────
def test_external_code_with_atlaz_prefix_matches():
    """invoice tem '1813301' cru; subscriber tem 'ATLAZ-1813301'."""
    async def t(db, mod):
        sid = _id("sub")
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO,
            "external_code": "ATLAZ-1813301"})
        await db.subscriber_invoices.insert_one({
            "id": _id("inv"), "company_id": CO,
            "subscriber_external_id": "1813301",
            "status": "paid", "amount_paid": 100.0})
        # Outcome com subscriber_id direto
        oid = _id("out")
        await db.motor_ia_outcomes.insert_one({
            "outcome_id": oid, "company_id": CO,
            "subscriber_id": sid,
            "expected_BRL": 100.0, "actual_BRL": 0,
            "observed_at": datetime.now(timezone.utc).isoformat()})
        out = await mod.backfill_action_to_cash_v72(
            CO, dry_run=False)
        assert out["outcomes_marked_received"] == 1, out
        assert out["total_recovered_BRL"] == 100.0
        oc = await db.motor_ia_outcomes.find_one({"outcome_id": oid})
        assert oc["status"] == "revenue_received"
        assert oc["actual_BRL"] == 100.0
    _run(t)


# ───────── BUG #1 + BUG #2: outcome com outcome_id e SEM subscriber_id ─────────
def test_outcome_with_outcome_id_and_resolved_via_action():
    """Outcome sem subscriber_id → resolve via action.subscriber_id."""
    async def t(db, mod):
        sid = _id("sub")
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO, "external_code": "EXT-A"})
        await db.subscriber_invoices.insert_one({
            "id": _id("inv"), "company_id": CO,
            "subscriber_external_id": "EXT-A",
            "status": "paid", "amount_paid": 50.0})
        # Action carrega o subscriber_id
        aid = "act-resolve-x"
        await db.motor_ia_actions.insert_one({
            "id": aid, "action_id": aid, "company_id": CO,
            "subscriber_id": sid, "expected_BRL": 50.0,
            "actual_BRL": 0, "status": "executed"})
        # Outcome SEM subscriber_id mas com action_id apontando p/ act
        # E usa `outcome_id` em vez de `id` (caso real do co-demo)
        oid = "out-resolve-x"
        await db.motor_ia_outcomes.insert_one({
            "outcome_id": oid, "action_id": aid,
            "company_id": CO,
            "expected_BRL": 50.0, "actual_BRL": 0,
            "observed_at": datetime.now(timezone.utc).isoformat()})
        out = await mod.backfill_action_to_cash_v72(
            CO, dry_run=False)
        assert out["outcomes_marked_received"] == 1, out
        oc = await db.motor_ia_outcomes.find_one({"outcome_id": oid})
        assert oc["status"] == "revenue_received"
        assert oc["actual_BRL"] == 50.0
        # Action marcada também
        act = await db.motor_ia_actions.find_one({"id": aid})
        assert act["status"] == "revenue_confirmed"
    _run(t)


def test_outcome_resolved_via_decision_when_action_missing():
    """Quando não há action mas decision tem subscriber_id."""
    async def t(db, mod):
        sid = _id("sub")
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO, "external_code": "EXT-D"})
        await db.subscriber_invoices.insert_one({
            "id": _id("inv"), "company_id": CO,
            "subscriber_external_id": "EXT-D",
            "status": "paid", "amount_paid": 30.0})
        did = "dec-resolve-y"
        await db.motor_ia_decisions.insert_one({
            "id": did, "decision_id": did, "company_id": CO,
            "subscriber_id": sid, "expected_BRL": 30.0})
        await db.motor_ia_outcomes.insert_one({
            "outcome_id": "out-resolve-y", "decision_id": did,
            "company_id": CO,
            "expected_BRL": 30.0, "actual_BRL": 0,
            "observed_at": datetime.now(timezone.utc).isoformat()})
        out = await mod.backfill_action_to_cash_v72(
            CO, dry_run=False)
        assert out["outcomes_marked_received"] == 1, out
    _run(t)


# ───────── BUG #4: revenue_realization truth-source ─────────
def test_revenue_truth_reads_invoices_directly():
    """Mesmo SEM outcomes pagos, revenue_total_BRL deve refletir
    invoices paid (fonte de verdade da empresa)."""
    async def t(db, mod):
        sid = _id("sub")
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO, "external_code": "EXT-T"})
        # 3 invoices paid + 1 open
        for i in range(3):
            await db.subscriber_invoices.insert_one({
                "id": _id("inv"), "company_id": CO,
                "subscriber_external_id": "EXT-T",
                "status": "paid", "amount_paid": 100.0,
                "paid_date": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S")})
        await db.subscriber_invoices.insert_one({
            "id": _id("inv"), "company_id": CO,
            "subscriber_external_id": "EXT-T",
            "status": "open", "amount": 100.0})
        truth = await mod.revenue_realization_truth(
            CO, window_days=30)
        assert truth["revenue_total_BRL"] == 300.0, truth
        assert truth["invoices_paid_count"] == 3
        assert truth["invoices_total_count"] == 4
        assert truth["corporate_realization_pct"] == 75.0
        # Receita orgânica = 100% pois 0 outcomes
        assert truth["revenue_organic_BRL"] == 300.0
        assert truth["ia_attribution_pct"] == 0
    _run(t)


def test_revenue_truth_attributes_ia_when_outcomes_received():
    """Quando outcomes estão revenue_received, ia_attribution_pct
    reflete o split corretamente."""
    async def t(db, mod):
        sid = _id("sub")
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO, "external_code": "EXT-Z"})
        # 2 invoices pagas = 200 BRL total empresa
        for _ in range(2):
            await db.subscriber_invoices.insert_one({
                "id": _id("inv"), "company_id": CO,
                "subscriber_external_id": "EXT-Z",
                "status": "paid", "amount_paid": 100.0,
                "paid_date": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S")})
        # 1 outcome já marcado como received = 100 BRL atribuído
        await db.motor_ia_outcomes.insert_one({
            "outcome_id": _id("out"), "company_id": CO,
            "subscriber_id": sid,
            "expected_BRL": 100.0, "actual_BRL": 100.0,
            "status": "revenue_received",
            "observed_at": datetime.now(timezone.utc).isoformat()})
        truth = await mod.revenue_realization_truth(
            CO, window_days=30)
        assert truth["revenue_total_BRL"] == 200.0
        assert truth["revenue_attributed_to_ai_BRL"] == 100.0
        assert truth["revenue_organic_BRL"] == 100.0
        assert truth["ia_attribution_pct"] == 50.0
    _run(t)


# ───────── Garantia: homolog continua proibido ─────────
def test_homolog_outcomes_never_marked():
    async def t(db, mod):
        sid = _id("sub")
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO, "external_code": "EXT-H"})
        await db.subscriber_invoices.insert_one({
            "id": _id("inv"), "company_id": CO,
            "subscriber_external_id": "EXT-H",
            "status": "paid", "amount_paid": 100.0})
        await db.motor_ia_outcomes.insert_one({
            "outcome_id": _id("out"), "company_id": CO,
            "subscriber_id": sid,
            "environment": "homolog",  # PROIBIDO
            "expected_BRL": 100.0, "actual_BRL": 0,
            "observed_at": datetime.now(timezone.utc).isoformat()})
        out = await mod.backfill_action_to_cash_v72(
            CO, dry_run=False)
        assert out["outcomes_marked_received"] == 0, out
    _run(t)


# ───────── Idempotência ─────────
def test_backfill_is_idempotent():
    async def t(db, mod):
        sid = _id("sub")
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO,
            "external_code": "ATLAZ-99"})
        await db.subscriber_invoices.insert_one({
            "id": _id("inv"), "company_id": CO,
            "subscriber_external_id": "99",
            "status": "paid", "amount_paid": 25.0})
        await db.motor_ia_outcomes.insert_one({
            "outcome_id": _id("out"), "company_id": CO,
            "subscriber_id": sid,
            "expected_BRL": 25.0, "actual_BRL": 0,
            "observed_at": datetime.now(timezone.utc).isoformat()})
        r1 = await mod.backfill_action_to_cash_v72(
            CO, dry_run=False)
        r2 = await mod.backfill_action_to_cash_v72(
            CO, dry_run=False)
        assert r1["outcomes_marked_received"] == 1
        # 2ª rodada: outcome já marcado → 0 novos matches
        assert r2["outcomes_marked_received"] == 0
    _run(t)


# ───────── Proteção: subscriber_id homolog- nunca atribui ─────────
def test_homolog_subscriber_id_is_never_attributed():
    """Outcomes cujo subscriber_id começa com 'homolog-' nunca
    devem receber receita real, mesmo sem campo environment."""
    async def t(db, mod):
        await db.subscribers.insert_one({
            "id": "homolog-sub-real-issue", "company_id": CO,
            "external_code": "ATLAZ-HSI"})
        await db.subscriber_invoices.insert_one({
            "id": _id("inv"), "company_id": CO,
            "subscriber_external_id": "HSI",
            "status": "paid", "amount_paid": 50.0})
        await db.motor_ia_outcomes.insert_one({
            "outcome_id": _id("out"), "company_id": CO,
            "subscriber_id": "homolog-sub-real-issue",
            # SEM environment — caso real do co-demo
            "expected_BRL": 50.0, "actual_BRL": 0,
            "observed_at": datetime.now(timezone.utc).isoformat()})
        out = await mod.backfill_action_to_cash_v72(
            CO, dry_run=False)
        assert out["outcomes_marked_received"] == 0, out
    _run(t)

def test_amount_outside_tolerance_skips():
    """invoice 5 vs expected 100 = 5% — fora da banda 50-200%."""
    async def t(db, mod):
        sid = _id("sub")
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO, "external_code": "EXT-T"})
        await db.subscriber_invoices.insert_one({
            "id": _id("inv"), "company_id": CO,
            "subscriber_external_id": "EXT-T",
            "status": "paid", "amount_paid": 5.0})
        await db.motor_ia_outcomes.insert_one({
            "outcome_id": _id("out"), "company_id": CO,
            "subscriber_id": sid,
            "expected_BRL": 100.0, "actual_BRL": 0,
            "observed_at": datetime.now(timezone.utc).isoformat()})
        out = await mod.backfill_action_to_cash_v72(
            CO, dry_run=False)
        assert out["outcomes_marked_received"] == 0
    _run(t)
