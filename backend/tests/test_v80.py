"""Testes V8.0 — SmartProv Score + GO LIVE Master + Money Stream."""
from __future__ import annotations
import asyncio, os, sys, importlib
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CO = "test-v80"
COLLS = ["subscribers", "subscriber_invoices", "motor_ia_actions",
          "motor_ia_decisions", "motor_ia_events", "motor_ia_outcomes",
          "motor_ia_autonomous_cycles", "motor_ia_subscriber_scores",
          "motor_ia_experiments"]


def _run(coro):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import database as dm; dm.db = db
        from services import smartprov_score, golive_master
        from services import transport_check, cash_operation
        from services import financial_foundation, autonomous_engine
        from services import real_revenue, blockers_audit
        from services import smartolt_predictive
        for m in (transport_check, financial_foundation,
                   blockers_audit, smartolt_predictive,
                   real_revenue, autonomous_engine,
                   cash_operation, smartprov_score, golive_master):
            importlib.reload(m)
        for col in COLLS:
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro(db, smartprov_score, golive_master)
        finally:
            for col in COLLS:
                await db[col].delete_many({"company_id": CO})
            c.close()
    return asyncio.run(_wrap())


def test_smartprov_score_returns_five_components():
    async def go(db, score, _g):
        r = await score.compute(CO)
        for k in ("revenue", "retention", "automation",
                  "data_quality", "network"):
            assert k in r["components"]
        assert "score" in r and "classification" in r
        assert r["classification"] in ("CRITICO", "ATENCAO", "BOM",
                                          "EXCELENTE", "REFERENCIA")
        assert "bottleneck" in r
    _run(go)


def test_smartprov_score_classifies_correctly():
    async def go(db, score, _g):
        # ATIVOs com tudo preenchido + online → DQ e network 100%
        for i in range(10):
            await db.subscribers.insert_one({
                "id": f"s-good-{i}", "company_id": CO, "status": "ATIVO",
                "phone": f"+551199{i:04d}", "plan_price": 100,
                "smartolt_onu_zone": f"CTO-{i}",
                "smartolt_onu_status": "Online"})
        r = await score.compute(CO)
        assert r["components"]["data_quality"] == 100.0
        assert r["components"]["network"] == 100.0
    _run(go)


def test_golive_master_blocks_when_wa_missing():
    async def go(db, _s, glm):
        r = await glm.status(CO)
        assert r["state"] in ("VERDE", "VERMELHO")
        # Sem WA configurado → VERMELHO
        assert r["state"] == "VERMELHO"
        # 8 checks
        assert len(r["checks"]) == 8
        # WA_SIDECAR_TOKEN entre blockers
        assert "WA_SIDECAR_TOKEN" in r["blockers"]
        # MongoDB deve estar OK (estamos conectados)
        assert r["checks"]["MONGODB"] is True
    _run(go)


def test_smartprov_score_bottleneck_identifies_weakest():
    async def go(db, score, _g):
        # Cria só DQ ruim (subscriber sem phone)
        for i in range(5):
            await db.subscribers.insert_one({
                "id": f"s-bad-{i}", "company_id": CO, "status": "ATIVO",
                "plan_price": 100, "smartolt_onu_zone": f"X{i}",
                "smartolt_onu_status": "Online"})  # sem phone
        r = await score.compute(CO)
        # data_quality deve estar baixo
        assert r["components"]["data_quality"] < 100
    _run(go)
