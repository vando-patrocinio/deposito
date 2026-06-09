"""test_v8_3.py — V8.3 infraestrutura de causalidade."""
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

CO = "test-v83-co"
COLLS = ["subscribers", "subscriber_invoices",
         "motor_ia_actions", "motor_ia_cohorts",
         "motor_ia_cohort_members"]


@pytest_asyncio.fixture
async def setup_db():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    import database as dm
    dm.db = db
    from services import v8_3_causality, v7_2_revenue
    v8_3_causality.db = db
    v7_2_revenue.db = db
    for col in COLLS:
        await db[col].delete_many({"company_id": CO})
    yield db, v8_3_causality
    for col in COLLS:
        await db[col].delete_many({"company_id": CO})
    c.close()


def _id(p):
    return f"{p}-{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_cohort_creation_idempotent(setup_db):
    db, m = setup_db
    c1 = await m.create_cohort(CO, "test-1",
                                ["sub-A", "sub-B"],
                                ["sub-C", "sub-D"])
    c2 = await m.create_cohort(CO, "test-1",
                                ["sub-A", "sub-B"],
                                ["sub-C", "sub-D"])
    # Mesmo cohort_id (idempotência)
    assert c1["id"] == c2["id"]
    # 4 membros
    n = await db.motor_ia_cohort_members.count_documents(
        {"cohort_id": c1["id"]})
    assert n == 4


@pytest.mark.asyncio
async def test_attribution_window_marks_paid(setup_db):
    db, m = setup_db
    now = datetime.now(timezone.utc)
    await db.subscribers.insert_one({
        "id": "sub-attr", "company_id": CO,
        "external_code": "ATLAZ-999"})
    await db.subscriber_invoices.insert_one({
        "id": _id("inv"), "company_id": CO,
        "subscriber_external_id": "999",
        "status": "paid",
        "amount_paid": 100.0,
        "paid_date": (now + timedelta(days=3)).strftime(
            "%Y-%m-%d %H:%M:%S")})
    cohort = await m.create_cohort(
        CO, "win-test", ["sub-attr"], [])
    attr = await m.compute_attribution(
        cohort["id"], window_days=14)
    assert attr["members_marked_paid"] == 1
    mem = await db.motor_ia_cohort_members.find_one(
        {"subscriber_id": "sub-attr"})
    assert mem["paid_within_window"] is True
    assert mem["paid_amount_BRL"] == 100.0


@pytest.mark.asyncio
async def test_lift_calculation_correct(setup_db):
    db, m = setup_db
    # Setup manual: 5 treatment, 5 control
    cohort = await m.create_cohort(
        CO, "lift-test",
        [f"t-{i}" for i in range(5)],
        [f"c-{i}" for i in range(5)])
    # Marca 3/5 treatment como paid, 1/5 control
    for i in range(3):
        await db.motor_ia_cohort_members.update_one(
            {"cohort_id": cohort["id"],
             "subscriber_id": f"t-{i}"},
            {"$set": {"paid_within_window": True,
                      "paid_amount_BRL": 100.0}})
    await db.motor_ia_cohort_members.update_one(
        {"cohort_id": cohort["id"],
         "subscriber_id": "c-0"},
        {"$set": {"paid_within_window": True,
                  "paid_amount_BRL": 100.0}})
    lift = await m.compute_lift(cohort["id"])
    # 3/5 = 0.6 vs 1/5 = 0.2 ⇒ lift_abs=0.4
    assert lift["treatment"]["payment_rate"] == 0.6
    assert lift["control"]["payment_rate"] == 0.2
    assert lift["lift_absolute"] == 0.4
    assert lift["lift_pct"] == 200.0  # (0.6-0.2)/0.2 * 100
    assert lift["incremental_revenue_BRL_estimate"] == 200.0
    assert lift["confidence_simple"] in ("high",
                                          "medium", "low")


@pytest.mark.asyncio
async def test_lift_zero_when_no_diff(setup_db):
    db, m = setup_db
    cohort = await m.create_cohort(
        CO, "zero-lift",
        ["t-1", "t-2"], ["c-1", "c-2"])
    lift = await m.compute_lift(cohort["id"])
    assert lift["lift_absolute"] == 0.0
    assert lift["confidence_simple"] == "none"


@pytest.mark.asyncio
async def test_run_pilot_dry_run_full_cycle(setup_db):
    db, m = setup_db
    res = await m.run_pilot(
        company_id=CO,
        n_treatment=50, n_control=50,
        treatment_payment_rate=0.7,
        control_payment_rate=0.3,
        window_days=14,
        dry_run=True, cleanup=True)
    assert res["synthetic"] is True
    assert res["n_treatment"] == 50
    assert res["n_control"] == 50
    # Lift positivo esperado pela diferença das rates
    lift = res["lift_result"]
    assert lift["treatment"]["n"] == 50
    assert lift["control"]["n"] == 50
    # Treatment rate >> Control rate
    assert lift["treatment"]["payment_rate"] > (
        lift["control"]["payment_rate"])
    assert lift["lift_absolute"] > 0
    # Cleanup funcionou
    remaining = await db.subscribers.count_documents(
        {"company_id": CO})
    assert remaining == 0


@pytest.mark.asyncio
async def test_batch_revenue_validation_classifies_correctly(
        setup_db):
    db, m = setup_db
    # Setup: 1 subscriber, 1 invoice paid, 1 action prévia
    sid = "sub-batch"
    await db.subscribers.insert_one({
        "id": sid, "company_id": CO,
        "external_code": "ATLAZ-BB"})
    now = datetime.now(timezone.utc)
    # Action 5 dias antes
    await db.motor_ia_actions.insert_one({
        "id": _id("act"), "company_id": CO,
        "subscriber_id": sid, "kind": "operacao_tese_tier_a",
        "status": "executed",
        "executed_at": (now - timedelta(days=5)).isoformat(),
        "expected_BRL": 50.0})
    # Invoice paga hoje (dentro da janela 30d)
    await db.subscriber_invoices.insert_one({
        "id": _id("inv"), "company_id": CO,
        "subscriber_external_id": "BB", "status": "paid",
        "amount_paid": 50.0,
        "paid_date": now.strftime("%Y-%m-%d %H:%M:%S")})
    # Invoice paga sem action correspondente
    await db.subscriber_invoices.insert_one({
        "id": _id("inv"), "company_id": CO,
        "subscriber_external_id": "XX",  # subscriber não existe
        "status": "paid", "amount_paid": 30.0,
        "paid_date": now.strftime("%Y-%m-%d %H:%M:%S")})
    out = await m.batch_revenue_validation(CO)
    assert out["attributed"]["n"] == 1
    assert out["attributed"]["sum_BRL"] == 50.0
    assert (out["attributed"]["by_kind"][
        "operacao_tese_tier_a"]["n"]) == 1
    assert out["no_subscriber_match"] == 1  # XX não existe


@pytest.mark.asyncio
async def test_calibrate_expected_brl_advisory_only(setup_db):
    db, m = setup_db
    # Cria 3 actions tier_c com expected=0 + 1 com expected>0
    for _ in range(3):
        await db.motor_ia_actions.insert_one({
            "id": _id("act"), "company_id": CO,
            "kind": "operacao_tese_tier_c",
            "expected_BRL": 0,
            "subscriber_id": _id("sub")})
    await db.motor_ia_actions.insert_one({
        "id": _id("act"), "company_id": CO,
        "kind": "operacao_tese_tier_c",
        "expected_BRL": 80.0,
        "subscriber_id": _id("sub")})
    # 5 invoices paid p/ calc média
    for _ in range(5):
        await db.subscriber_invoices.insert_one({
            "id": _id("inv"), "company_id": CO,
            "subscriber_external_id": _id("x"),
            "status": "paid", "amount_paid": 100.0})
    out = await m.calibrate_expected_brl(CO)
    assert out["zero_expected_count"] == 3
    assert out["global_avg_paid_BRL"] == 100.0
    assert out["estimated_total_uplift_BRL"] == 300.0
    assert out["advisory_only"] is True
    # NÃO alterou produção (re-conta)
    still_zero = await db.motor_ia_actions.count_documents({
        "company_id": CO, "kind": "operacao_tese_tier_c",
        "expected_BRL": 0})
    assert still_zero == 3
