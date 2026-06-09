"""test_v8_2.py — V8.2 primeiro R$ atribuído ao motor IA.

Usa pytest-asyncio com event loop session-scoped para evitar
"attached to a different loop" do motor client.
"""
from __future__ import annotations
import os
import sys
import uuid
import pytest
import pytest_asyncio
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CO = "test-v82-co"
COLLS = ["tickets", "subscribers", "subscriber_invoices",
         "motor_ia_events", "motor_ia_decisions",
         "motor_ia_actions", "motor_ia_outcomes",
         "motor_ia_learnings", "wa_outbox", "wa_messages_sent"]


@pytest_asyncio.fixture
async def setup_db():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    import database as dm
    dm.db = db
    from services import v8_2_first_cash, homologation, v7_2_revenue
    # Garante db atualizado em todos os módulos
    v8_2_first_cash.db = db
    homologation.db = db
    v7_2_revenue.db = db
    for col in COLLS:
        await db[col].delete_many({"company_id": CO})
    yield db, v8_2_first_cash
    for col in COLLS:
        await db[col].delete_many({"company_id": CO})
    c.close()


def _id(p):
    return f"{p}-{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_full_cycle_closes_with_real_cash(setup_db):
    db, m = setup_db
    sid = _id("sub")
    inv_id = _id("inv")
    await db.subscribers.insert_one({
        "id": sid, "company_id": CO,
        "external_code": "ATLAZ-9999"})
    await db.subscriber_invoices.insert_one({
        "id": inv_id, "company_id": CO,
        "subscriber_external_id": "9999",
        "status": "paid", "amount_paid": 99.90,
        "due_date": "2026-05-01"})
    r = await m.execute_first_cash_cycle(
        CO, sid, inv_id, expected_BRL=100.0,
        real_phone_redacted="11999999999")
    assert "error" not in r, r
    c = r["ciclo_completo"]
    assert c["1_evento"]["event_type"] == "INVOICE_OVERDUE"
    assert c["2_decisao"]["expected_BRL"] == 100.0
    assert c["3_acao"]["wa_blocked"] is True
    assert c["3_acao"]["redirected_to"] == "5521998176526"
    assert c["4_outcome"]["status"] == "revenue_received"
    assert c["4_outcome"]["actual_BRL"] == 99.90
    assert c["4_outcome"]["revenue_source"] == (
        "v8_2_first_cash_cycle")
    assert c["5_learning"]["kind"] == "revenue_confirmation"
    assert abs(c["5_learning"]["delta_BRL"] - (-0.10)) < 0.001
    assert r["action_actual_BRL"] == 99.90
    assert r["action_final_status"] == "revenue_confirmed"


@pytest.mark.asyncio
async def test_invoice_not_paid_rejects(setup_db):
    db, m = setup_db
    sid = _id("sub")
    inv_id = _id("inv")
    await db.subscribers.insert_one({
        "id": sid, "company_id": CO,
        "external_code": "ATLAZ-X"})
    await db.subscriber_invoices.insert_one({
        "id": inv_id, "company_id": CO,
        "subscriber_external_id": "X",
        "status": "open", "amount": 50.0})
    r = await m.execute_first_cash_cycle(
        CO, sid, inv_id, expected_BRL=50.0)
    assert r.get("error") == "invoice_not_paid_or_not_found"


@pytest.mark.asyncio
async def test_no_real_wa_sent(setup_db):
    db, m = setup_db
    sid = _id("sub")
    inv_id = _id("inv")
    await db.subscribers.insert_one({
        "id": sid, "company_id": CO,
        "external_code": "ATLAZ-Z"})
    await db.subscriber_invoices.insert_one({
        "id": inv_id, "company_id": CO,
        "subscriber_external_id": "Z",
        "status": "paid", "amount_paid": 30.0})
    await m.execute_first_cash_cycle(
        CO, sid, inv_id, expected_BRL=30.0,
        real_phone_redacted="11888888888")
    bad = await db.wa_messages_sent.count_documents({
        "company_id": CO,
        "to_effective": {"$ne": "5521998176526"}})
    assert bad == 0
    ev = await db.motor_ia_events.count_documents({
        "company_id": CO,
        "event_type": "HOMOLOGATION_BLOCKED_REAL_PHONE"})
    assert ev >= 1
