"""test_v7_3.py — V7.3 G4 backfill_opened_at (idempotente)."""
from __future__ import annotations
import asyncio
import importlib
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
CO = "test-v73-co"
COLLS = ["tickets", "client_equipment_history"]


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


def test_source_A_created_at_used_first():
    async def t(db, m):
        ts = datetime.now(timezone.utc).isoformat()
        await db.tickets.insert_one({
            "id": _id("tkt"), "company_id": CO,
            "created_at": ts})
        out = await m.backfill_opened_at(CO, dry_run=False)
        assert out["fixed_n"] == 1
        assert out["sources_used"] == {"tickets.created_at": 1}
        tk = await db.tickets.find_one({"company_id": CO})
        assert tk["opened_at"] == ts
        assert tk["opened_at_source"] == "tickets.created_at"
    _run(t)


def test_source_B_equipment_history_when_no_created_at():
    async def t(db, m):
        tid = _id("tkt")
        ts = datetime.now(timezone.utc).isoformat()
        await db.tickets.insert_one({
            "id": tid, "company_id": CO})  # sem created_at
        await db.client_equipment_history.insert_one({
            "id": _id("ceh"), "company_id": CO,
            "ticket_id": tid, "captured_at": ts})
        out = await m.backfill_opened_at(CO, dry_run=False)
        assert out["fixed_n"] == 1
        tk = await db.tickets.find_one({"id": tid})
        assert tk["opened_at"] == ts
        assert tk["opened_at_source"] == (
            "client_equipment_history.captured_at")
    _run(t)


def test_source_C_closed_at_minus_avg_when_no_others():
    """Sem created_at e sem CEH → usa closed_at - avg."""
    async def t(db, m):
        # Cria 2 tickets de referência com opened+closed (1h)
        now = datetime.now(timezone.utc)
        for _ in range(2):
            await db.tickets.insert_one({
                "id": _id("ref"), "company_id": CO,
                "opened_at": (now - timedelta(hours=2)).isoformat(),
                "closed_at": (now - timedelta(hours=1)).isoformat()})
        # Ticket alvo: só closed_at
        await db.tickets.insert_one({
            "id": _id("tgt"), "company_id": CO,
            "closed_at": now.isoformat()})
        out = await m.backfill_opened_at(CO, dry_run=False)
        # Os de referência já têm opened_at; só o target é fixado
        assert out["fixed_n"] == 1
        assert "closed_at_minus_avg_duration" in out["sources_used"]
        # avg ~ 1h, então opened_at ≈ closed_at - 1h
        assert abs(out["avg_duration_hours_used"] - 1.0) < 0.5
    _run(t)


def test_already_set_not_overwritten():
    async def t(db, m):
        existing = "2024-01-01T00:00:00+00:00"
        await db.tickets.insert_one({
            "id": _id("tkt"), "company_id": CO,
            "opened_at": existing,
            "created_at": "2025-01-01T00:00:00+00:00"})
        out = await m.backfill_opened_at(CO, dry_run=False)
        assert out["fixed_n"] == 0
        tk = await db.tickets.find_one({"company_id": CO})
        assert tk["opened_at"] == existing
        assert "opened_at_source" not in tk
    _run(t)


def test_dry_run_doesnt_change_db():
    async def t(db, m):
        await db.tickets.insert_one({
            "id": _id("tkt"), "company_id": CO,
            "created_at": "2026-01-01T00:00:00+00:00"})
        out = await m.backfill_opened_at(CO, dry_run=True)
        assert out["fixed_n"] == 1
        assert out["coverage_after_pct"] == 100.0
        tk = await db.tickets.find_one({"company_id": CO})
        assert tk.get("opened_at") in (None,)
        assert "opened_at_source" not in tk
    _run(t)


def test_idempotent_second_run_zero():
    async def t(db, m):
        await db.tickets.insert_one({
            "id": _id("tkt"), "company_id": CO,
            "created_at": "2026-01-01T00:00:00+00:00"})
        r1 = await m.backfill_opened_at(CO, dry_run=False)
        r2 = await m.backfill_opened_at(CO, dry_run=False)
        assert r1["fixed_n"] == 1
        assert r2["fixed_n"] == 0
        assert r2["coverage_after_pct"] == 100.0
    _run(t)


def test_coverage_metrics_correct():
    async def t(db, m):
        # 4 tickets: 1 já com opened_at, 3 sem (com created_at)
        await db.tickets.insert_one({
            "id": _id("a"), "company_id": CO,
            "opened_at": "2026-01-01T00:00:00+00:00",
            "created_at": "2026-01-01T00:00:00+00:00"})
        for _ in range(3):
            await db.tickets.insert_one({
                "id": _id("x"), "company_id": CO,
                "created_at": "2026-01-01T00:00:00+00:00"})
        out = await m.backfill_opened_at(CO, dry_run=False)
        assert out["tickets_total"] == 4
        assert out["coverage_before_n"] == 1
        assert out["coverage_before_pct"] == 25.0
        assert out["fixed_n"] == 3
        assert out["coverage_after_n"] == 4
        assert out["coverage_after_pct"] == 100.0
    _run(t)


def test_no_source_available_skipped():
    """Sem created_at, sem CEH, sem closed_at → não fixa."""
    async def t(db, m):
        await db.tickets.insert_one({
            "id": _id("tkt"), "company_id": CO})
        out = await m.backfill_opened_at(CO, dry_run=False)
        assert out["fixed_n"] == 0
    _run(t)
