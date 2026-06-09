"""test_v7_2_2.py — V7.2.2 G2/G3 backfill puro de qualidade."""
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
CO = "test-v722-co"
COLLS = ["tickets", "client_equipment_history",
         "ai_preventive_suggestions", "appointments"]


def _run(coro):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import database as dm
        dm.db = db
        from services import v7_2_2_data_quality
        importlib.reload(v7_2_2_data_quality)
        for col in COLLS:
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro(db, v7_2_2_data_quality)
        finally:
            for col in COLLS:
                await db[col].delete_many({"company_id": CO})
            c.close()
    return asyncio.new_event_loop().run_until_complete(_wrap())


def _id(p):
    return f"{p}-{uuid.uuid4().hex[:8]}"


# ───────── G3 (category) ─────────
def test_category_from_type_reparo_normalizes_to_REPAIR():
    async def t(db, m):
        await db.tickets.insert_one({
            "id": _id("tkt"), "company_id": CO, "type": "reparo"})
        out = await m.backfill_quality(CO, dry_run=False)
        assert out["G3_category"]["fixed_n"] == 1
        assert out["G3_category"]["distribution_in_fixed"][
            "REPAIR"] == 1
        tk = await db.tickets.find_one({"company_id": CO})
        assert tk["category"] == "REPAIR"
        assert tk["source_backfill_category"] == "tickets.type"
    _run(t)


def test_category_from_type_instalacao_to_INSTALL():
    async def t(db, m):
        await db.tickets.insert_one({
            "id": _id("tkt"), "company_id": CO,
            "type": "instalacao"})
        out = await m.backfill_quality(CO, dry_run=False)
        assert out["G3_category"]["distribution_in_fixed"][
            "INSTALL"] == 1
        tk = await db.tickets.find_one({"company_id": CO})
        assert tk["category"] == "INSTALL"
    _run(t)


def test_category_from_type_retirada_to_WITHDRAW():
    async def t(db, m):
        await db.tickets.insert_one({
            "id": _id("tkt"), "company_id": CO,
            "type": "retirada"})
        out = await m.backfill_quality(CO, dry_run=False)
        assert out["G3_category"]["distribution_in_fixed"][
            "WITHDRAW"] == 1
    _run(t)


def test_category_via_ai_triage_fallback():
    """type ausente → ai_triage.type usado."""
    async def t(db, m):
        await db.tickets.insert_one({
            "id": _id("tkt"), "company_id": CO,
            "type": None,
            "ai_triage": {"type": "Manutenção"}})
        out = await m.backfill_quality(CO, dry_run=False)
        assert out["G3_category"]["fixed_n"] == 1
        tk = await db.tickets.find_one({"company_id": CO})
        assert tk["category"] == "REPAIR"
        assert tk["source_backfill_category"] == "heuristic_blob"
    _run(t)


def test_category_already_valid_not_overwritten():
    async def t(db, m):
        await db.tickets.insert_one({
            "id": _id("tkt"), "company_id": CO,
            "type": "reparo", "category": "INSTALL"})
        await m.backfill_quality(CO, dry_run=False)
        tk = await db.tickets.find_one({"company_id": CO})
        # INSTALL preservado, NÃO sobrescrito por REPAIR
        assert tk["category"] == "INSTALL"
        assert "source_backfill_category" not in tk
    _run(t)


# ───────── G2 (assigned_to) ─────────
def test_assigned_from_collaborator_id():
    async def t(db, m):
        await db.tickets.insert_one({
            "id": _id("tkt"), "company_id": CO,
            "assigned_collaborator_id": "col-abc",
            "type": "reparo"})
        out = await m.backfill_quality(CO, dry_run=False)
        assert out["G2_assigned_to"]["fixed_n"] == 1
        tk = await db.tickets.find_one({"company_id": CO})
        assert tk["assigned_to"] == "col-abc"
        assert tk["source_backfill_assigned_to"] == (
            "tickets.assigned_collaborator_id")
    _run(t)


def test_assigned_from_equipment_history():
    async def t(db, m):
        tid = _id("tkt")
        await db.tickets.insert_one({
            "id": tid, "company_id": CO,
            "assigned_collaborator_id": None,
            "type": "instalacao"})
        await db.client_equipment_history.insert_one({
            "id": _id("ceh"), "company_id": CO,
            "ticket_id": tid, "captured_by": "col-tech-eq"})
        out = await m.backfill_quality(CO, dry_run=False)
        tk = await db.tickets.find_one({"id": tid})
        assert tk["assigned_to"] == "col-tech-eq"
        assert tk["source_backfill_assigned_to"] == (
            "client_equipment_history.captured_by")
    _run(t)


def test_assigned_from_ai_triage_suggested():
    async def t(db, m):
        await db.tickets.insert_one({
            "id": _id("tkt"), "company_id": CO,
            "assigned_collaborator_id": None,
            "ai_triage": {"suggested_collaborator_id": "col-sug"}})
        out = await m.backfill_quality(CO, dry_run=False)
        tk = await db.tickets.find_one({"company_id": CO})
        assert tk["assigned_to"] == "col-sug"
        assert tk["source_backfill_assigned_to"] == (
            "ai_triage.suggested_collaborator_id")
    _run(t)


def test_assigned_from_closed_by_col_prefix():
    async def t(db, m):
        await db.tickets.insert_one({
            "id": _id("tkt"), "company_id": CO,
            "assigned_collaborator_id": None,
            "closed_by": "col-closer"})
        out = await m.backfill_quality(CO, dry_run=False)
        tk = await db.tickets.find_one({"company_id": CO})
        assert tk["assigned_to"] == "col-closer"
    _run(t)


def test_assigned_skips_closed_by_user_prefix():
    """closed_by='usr-...' não deve virar assigned_to."""
    async def t(db, m):
        await db.tickets.insert_one({
            "id": _id("tkt"), "company_id": CO,
            "assigned_collaborator_id": None,
            "closed_by": "usr-not-a-tech"})
        await m.backfill_quality(CO, dry_run=False)
        tk = await db.tickets.find_one({"company_id": CO})
        # usr- não é técnico — não copia
        assert not tk.get("assigned_to")
    _run(t)


def test_assigned_already_set_not_overwritten():
    async def t(db, m):
        await db.tickets.insert_one({
            "id": _id("tkt"), "company_id": CO,
            "assigned_to": "col-EXISTING",
            "assigned_collaborator_id": "col-OTHER"})
        await m.backfill_quality(CO, dry_run=False)
        tk = await db.tickets.find_one({"company_id": CO})
        assert tk["assigned_to"] == "col-EXISTING"
    _run(t)


# ───────── Idempotência / Dry-Run ─────────
def test_dry_run_doesnt_change_db():
    async def t(db, m):
        await db.tickets.insert_one({
            "id": _id("tkt"), "company_id": CO,
            "type": "reparo",
            "assigned_collaborator_id": "col-x"})
        out = await m.backfill_quality(CO, dry_run=True)
        assert out["G2_assigned_to"]["fixed_n"] == 1
        assert out["G3_category"]["fixed_n"] == 1
        tk = await db.tickets.find_one({"company_id": CO})
        # DB inalterado
        assert "assigned_to" not in tk or tk.get(
            "assigned_to") is None
        assert tk.get("category") is None
    _run(t)


def test_idempotent_second_run_zero_changes():
    async def t(db, m):
        await db.tickets.insert_one({
            "id": _id("tkt"), "company_id": CO,
            "type": "reparo",
            "assigned_collaborator_id": "col-x"})
        r1 = await m.backfill_quality(CO, dry_run=False)
        r2 = await m.backfill_quality(CO, dry_run=False)
        assert r1["G2_assigned_to"]["fixed_n"] == 1
        assert r1["G3_category"]["fixed_n"] == 1
        assert r2["G2_assigned_to"]["fixed_n"] == 0
        assert r2["G3_category"]["fixed_n"] == 0
    _run(t)


def test_coverage_calculations_correct():
    async def t(db, m):
        # 4 tickets: 2 com type, 2 sem; 3 com colab, 1 sem
        for i, (typ, colab) in enumerate([
                ("reparo", "col-1"),
                ("instalacao", "col-2"),
                (None, "col-3"),
                (None, None)]):
            await db.tickets.insert_one({
                "id": _id(f"tkt{i}"), "company_id": CO,
                "type": typ,
                "assigned_collaborator_id": colab})
        out = await m.backfill_quality(CO, dry_run=False)
        assert out["tickets_total"] == 4
        assert out["G2_assigned_to"]["coverage_after_n"] == 3
        assert out["G2_assigned_to"]["coverage_after_pct"] == 75.0
        assert out["G3_category"]["coverage_after_n"] == 2
        assert out["G3_category"]["coverage_after_pct"] == 50.0
    _run(t)
