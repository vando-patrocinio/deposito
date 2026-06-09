"""test_v8_4.py — V8.4 motor de coorte com pareamento."""
from __future__ import annotations
import os
import sys
import uuid
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CO = "test-v84-co"
COLLS = ["subscribers", "subscriber_invoices",
         "motor_ia_cohorts", "motor_ia_cohort_members",
         "motor_ia_causality", "wa_outbox", "wa_messages_sent"]


@pytest_asyncio.fixture
async def setup_db():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    import database as dm
    dm.db = db
    from services import (v8_4_cohort, v7_2_revenue,
                          homologation)
    v8_4_cohort.db = db
    v7_2_revenue.db = db
    homologation.db = db
    for col in COLLS:
        await db[col].delete_many({"company_id": CO})
    yield db, v8_4_cohort
    for col in COLLS:
        await db[col].delete_many({"company_id": CO})
    c.close()


def _id(p):
    return f"{p}-{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_pair_match_balances_by_strata(setup_db):
    db, m = setup_db
    cands = []
    # 10 da branch A (mesma strata) + 10 da branch B (outra)
    for i in range(10):
        cands.append({
            "subscriber_id": f"a-{i}", "branch": "A",
            "plan_price_band": 1, "invoice_amount_band": 1,
            "days_overdue_band": 1})
    for i in range(10):
        cands.append({
            "subscriber_id": f"b-{i}", "branch": "B",
            "plan_price_band": 2, "invoice_amount_band": 2,
            "days_overdue_band": 2})
    t, c = m.pair_match(cands, n_per_group=5, seed=42)
    assert len(t) == 5
    assert len(c) == 5
    # Strata balanceada: cada par treatment/control tem strata igual
    # entre eles
    ts = sorted([x["strata"] for x in t])
    cs = sorted([x["strata"] for x in c])
    assert ts == cs, f"strata desbalanceado: T={ts} C={cs}"


@pytest.mark.asyncio
async def test_create_cohort_v84_idempotent(setup_db):
    db, m = setup_db
    t = [{"subscriber_id": "t1", "phone": "5521998176526",
          "branch": "A", "plan_price": 100,
          "invoice_id": "inv1", "invoice_amount": 100,
          "days_overdue": 5}]
    c = [{"subscriber_id": "c1", "phone": "5521998176526",
          "branch": "A", "plan_price": 100,
          "invoice_id": "inv2", "invoice_amount": 100,
          "days_overdue": 5}]
    r1 = await m.create_cohort_v84(CO, "test-1", t, c)
    r2 = await m.create_cohort_v84(CO, "test-1", t, c)
    assert r1["id"] == r2["id"]
    n = await db.motor_ia_cohort_members.count_documents(
        {"cohort_id": r1["id"]})
    assert n == 2


@pytest.mark.asyncio
async def test_calculate_lift_with_significance(setup_db):
    db, m = setup_db
    # Cohort: 50 treatment (35 pagaram) vs 50 control (15 pagaram)
    cohort = await m.create_cohort_v84(
        CO, "stat-test",
        treatment=[{"subscriber_id": f"t-{i}",
                    "branch": "A", "plan_price": 100,
                    "invoice_id": f"inv-t-{i}",
                    "invoice_amount": 100,
                    "days_overdue": 5} for i in range(50)],
        control=[{"subscriber_id": f"c-{i}",
                  "branch": "A", "plan_price": 100,
                  "invoice_id": f"inv-c-{i}",
                  "invoice_amount": 100,
                  "days_overdue": 5} for i in range(50)])
    # 35/50 treatment paid; 15/50 control paid
    for i in range(35):
        await db.motor_ia_cohort_members.update_one(
            {"cohort_id": cohort["id"],
             "subscriber_id": f"t-{i}"},
            {"$set": {"paid_within_window": True,
                      "paid_amount_BRL": 100.0}})
    for i in range(15):
        await db.motor_ia_cohort_members.update_one(
            {"cohort_id": cohort["id"],
             "subscriber_id": f"c-{i}"},
            {"$set": {"paid_within_window": True,
                      "paid_amount_BRL": 100.0}})
    lift = await m.calculate_lift(cohort["id"])
    assert lift["treatment_rate"] == 0.7
    assert lift["control_rate"] == 0.3
    assert lift["lift_absolute"] == 0.4
    assert lift["lift_pct"] == 133.33
    assert lift["incremental_revenue_BRL"] == 2000.0  # 3500-1500
    # Z-test deve ser significativo (diff 0.4 com n=50 cada)
    assert lift["significant_95"] is True
    assert lift["p_value_two_sided"] < 0.05
    # Persistiu em motor_ia_causality
    saved = await db.motor_ia_causality.find_one(
        {"cohort_id": cohort["id"]})
    assert saved is not None
    assert saved["incremental_revenue_BRL"] == 2000.0


@pytest.mark.asyncio
async def test_attribution_window_marks_paid(setup_db):
    db, m = setup_db
    now = datetime.now(timezone.utc)
    await db.subscribers.insert_one({
        "id": "sub-attr", "company_id": CO,
        "external_code": "ATLAZ-A1",
        "phone": "5521998176526"})
    inv_id = _id("inv")
    await db.subscriber_invoices.insert_one({
        "id": inv_id, "company_id": CO,
        "subscriber_external_id": "A1", "status": "paid",
        "amount_paid": 100.0,
        "paid_date": (now + timedelta(days=2)).strftime(
            "%Y-%m-%d %H:%M:%S")})
    cohort = await m.create_cohort_v84(
        CO, "attr-test",
        treatment=[{"subscriber_id": "sub-attr",
                    "external_code": "ATLAZ-A1",
                    "phone": "5521998176526",
                    "branch": "A", "plan_price": 100,
                    "invoice_id": inv_id,
                    "invoice_amount": 100,
                    "days_overdue": 5}],
        control=[])
    attr = await m.attribution_window(cohort["id"])
    assert attr["members_marked_paid"] == 1
    mem = await db.motor_ia_cohort_members.find_one(
        {"subscriber_id": "sub-attr"})
    assert mem["paid_within_window"] is True
    assert mem["paid_amount_BRL"] == 100.0


@pytest.mark.asyncio
async def test_dispatch_passes_through_homologation(setup_db):
    """Dispatch envia treatment via gateway → todas redirecionadas
    para TEST_PHONE (HOMOLOG_MODE=true). Membros recebem wa_message_id.
    """
    db, m = setup_db
    cohort = await m.create_cohort_v84(
        CO, "dispatch-test",
        treatment=[{"subscriber_id": "sub-disp",
                    "external_code": "X", "phone": "11999998888",
                    "branch": "A", "plan_price": 100,
                    "invoice_id": "i1", "invoice_amount": 100,
                    "days_overdue": 5}],
        control=[])
    r = await m.dispatch_treatment_group(
        cohort["id"], template="V8.4 unit test dispatch")
    assert r["sent"] == 1
    mem = await db.motor_ia_cohort_members.find_one(
        {"subscriber_id": "sub-disp"})
    # Bloqueado pela homolog + redirecionado para TEST_PHONE
    assert mem["wa_blocked"] is True
    assert mem["wa_to_effective"] == "5521998176526"
    assert mem["wa_message_id"] is not None  # sidecar real
    assert mem["status"] == "dispatched"
    # Auditoria
    bad = await db.wa_messages_sent.count_documents({
        "company_id": CO,
        "to_effective": {"$ne": "5521998176526"}})
    assert bad == 0


@pytest.mark.asyncio
async def test_zero_lift_when_no_diff(setup_db):
    db, m = setup_db
    cohort = await m.create_cohort_v84(
        CO, "zero-lift",
        treatment=[{"subscriber_id": "t1", "branch": "A",
                    "plan_price": 100, "invoice_id": "i1",
                    "invoice_amount": 100, "days_overdue": 5}],
        control=[{"subscriber_id": "c1", "branch": "A",
                  "plan_price": 100, "invoice_id": "i2",
                  "invoice_amount": 100, "days_overdue": 5}])
    lift = await m.calculate_lift(cohort["id"])
    assert lift["lift_absolute"] == 0.0
    assert lift["significant_95"] is False
