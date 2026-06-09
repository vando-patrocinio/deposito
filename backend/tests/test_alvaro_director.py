"""Testes FASE 7 — Álvaro Diretor de Operações."""
from __future__ import annotations
import asyncio, os, sys
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CO = "test-alv-pytest"


def _run(coro):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import importlib
        import database as dm
        dm.db = db
        from services import alvaro_director as alv
        importlib.reload(alv)
        for col in ("tickets", "subscribers", "subscriber_invoices",
                     "appointments", "sales_leads", "companies",
                     "motor_ia_daily_briefings"):
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro(db, alv)
        finally:
            for col in ("tickets", "subscribers", "subscriber_invoices",
                         "appointments", "sales_leads", "companies",
                         "motor_ia_daily_briefings"):
                await db[col].delete_many({"company_id": CO})
            c.close()
    return asyncio.run(_wrap())


def test_technician_ranking_scores():
    async def go(db, alv):
        # tech-good: 10 fechados / 10 total = 100%
        for i in range(10):
            await db.tickets.insert_one({
                "company_id": CO, "id": f"t-g-{i}",
                "assigned_to": "tech-good", "status": "encerrada"})
        # tech-bad: 2 fechados / 10 total = 20%
        for i in range(10):
            await db.tickets.insert_one({
                "company_id": CO, "id": f"t-b-{i}",
                "assigned_to": "tech-bad",
                "status": "encerrada" if i < 2 else "aberta"})
        r = await alv.technician_ranking(CO)
        assert len(r) == 2
        # tech-good é o topo
        assert r[0]["collaborator_id"] == "tech-good"
        assert r[0]["score"] > r[1]["score"]
    _run(go)


def test_bottlenecks_detects_sla_breach():
    async def go(db, alv):
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        await db.tickets.insert_one({
            "company_id": CO, "id": "tk-sla", "status": "aberta",
            "opened_at": old, "assigned_to": "x"})
        b = await alv.bottlenecks(CO)
        types = [x["type"] for x in b]
        assert "SLA_BREACH_RISK" in types
    _run(go)


def test_waste_detection_rework():
    async def go(db, alv):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        for i in range(3):
            await db.tickets.insert_one({
                "company_id": CO, "id": f"rt-{i}",
                "client_id": "client-rework",
                "created_at": now, "status": "aberta"})
        w = await alv.waste_detection(CO)
        assert w["clients_with_rework"] >= 1
    _run(go)


def test_daily_briefing_persists():
    async def go(db, alv):
        r = await alv.daily_briefing(CO, kind="07h")
        assert r["kind"] == "07h"
        assert "metrics" in r
        # persistido em motor_ia_daily_briefings
        cnt = await db.motor_ia_daily_briefings.count_documents(
            {"company_id": CO})
        assert cnt == 1
    _run(go)


def test_director_summary_aggregates_all():
    async def go(db, alv):
        r = await alv.director_summary(CO)
        for k in ("headline", "top_technicians", "region_ranking",
                  "bottlenecks", "waste", "recommendations"):
            assert k in r
    _run(go)
