"""Testes da FASE 6.5 — Knowledge Graph (XAI)."""
from __future__ import annotations
import asyncio, os, sys
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CO = "test-kg-pytest"


def _run(coro_factory):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import importlib
        import database as database_mod
        database_mod.db = db
        from services import knowledge_graph as kg
        importlib.reload(kg)
        for col in ("subscribers", "subscriber_invoices", "tickets",
                     "smartolt_onus", "motor_ia_subscriber_scores",
                     "subscriber_access_points"):
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro_factory(db, kg)
        finally:
            for col in ("subscribers", "subscriber_invoices", "tickets",
                         "smartolt_onus", "motor_ia_subscriber_scores",
                         "subscriber_access_points"):
                await db[col].delete_many({"company_id": CO})
            c.close()
    return asyncio.run(_wrap())


def test_explain_returns_xai_structure():
    async def go(db, kg):
        await db.subscribers.insert_one({
            "id": "s-kg-1", "company_id": CO, "status": "ATIVO",
            "smartolt_onu_status": "LOS"})
        r = await kg.why_client_cancelled(CO, "s-kg-1")
        for k in ("cause", "effect", "impact", "recommended_action",
                  "factors", "evidence", "confidence"):
            assert k in r
        assert r["confidence"] > 0
        # Tem ONU ruim → "ONU sem sinal" deve estar nos fatores
        names = [f["name"] for f in r["factors"]]
        assert any("ONU" in n for n in names)
    _run(go)


def test_explain_cto_degrades():
    async def go(db, kg):
        for i, status in enumerate(["Offline", "Offline", "Online"]):
            await db.smartolt_onus.insert_one({
                "id": f"o-kg-{i}", "company_id": CO,
                "unique_external_id": f"UEX-{i}",
                "sn": f"SKG{i}", "zone_name": "CTO-KG",
                "status": status, "olt_name": "OLT1",
                "board": "1", "port": "1"})
        r = await kg.why_cto_degrades(CO, "CTO-KG")
        # 2 de 3 ruim → fator "alta taxa de offlines"
        assert r["confidence"] > 0
        assert "tickets" in str(r["evidence"]).lower()
    _run(go)


def test_dispatcher_invalid_key():
    async def go(db, kg):
        r = await kg.explain("invalid", company_id=CO, entity_id="x")
        assert "error" in r
    _run(go)


def test_what_causes_problems_aggregate():
    async def go(db, kg):
        await db.smartolt_onus.insert_one({
            "id": "o-wc", "company_id": CO,
            "unique_external_id": "UEX-WC",
            "sn": "SWC", "zone_name": "CTO-WC",
            "status": "LOS", "olt_name": "O", "board": "1", "port": "1"})
        await db.motor_ia_subscriber_scores.insert_one({
            "subscriber_id": "s-wc", "company_id": CO,
            "churn_score": 85, "buy_score": 50, "upgrade_score": 50,
            "retention_score": 50, "referral_score": 50,
            "collection_score": 50, "next_best_action": "NO_ACTION",
            "confidence": 0.5})
        await db.subscribers.insert_one({
            "id": "s-wc", "company_id": CO, "status": "ATIVO"})
        r = await kg.what_causes_problems(CO)
        assert "summary" in r
        assert r["top_offenders"]["cto"] is not None
        assert r["top_offenders"]["cliente_em_risco"] is not None
    _run(go)
