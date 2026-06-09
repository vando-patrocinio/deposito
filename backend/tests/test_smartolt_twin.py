"""Testes da FASE 4 — SmartOLT Digital Twin."""
from __future__ import annotations
import asyncio, os, sys
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CO = "test-twin-pytest"


def _run(coro_factory):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import importlib
        import database as database_mod
        database_mod.db = db
        from services import smartolt_twin
        importlib.reload(smartolt_twin)
        # cleanup
        for col in ("smartolt_onus", "subscribers", "tickets",
                     "subscriber_invoices", "cto_ports"):
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro_factory(db, smartolt_twin)
        finally:
            for col in ("smartolt_onus", "subscribers", "tickets",
                         "subscriber_invoices", "cto_ports"):
                await db[col].delete_many({"company_id": CO})
            c.close()
    return asyncio.run(_wrap())


def test_score_levels_classification():
    async def go(db, twin):
        assert twin._level(100) == "EXCELENTE"
        assert twin._level(94) == "SAUDAVEL"
        assert twin._level(85) == "ATENCAO"
        assert twin._level(75) == "CRITICO"
        assert twin._level(50) == "INCIDENTE"
    _run(go)


def test_onu_score_signal_brackets():
    async def go(db, twin):
        assert twin._onu_score({"status": "Online",
                                  "signal_1310": "-20"}) == 100
        assert twin._onu_score({"status": "Online",
                                  "signal_1310": "-24"}) == 90
        assert twin._onu_score({"status": "Online",
                                  "signal_1310": "-28"}) == 55
        assert twin._onu_score({"status": "LOS"}) == 0
        assert twin._onu_score({"status": "Power fail"}) == 0
    _run(go)


def test_cto_health_aggregation():
    async def go(db, twin):
        # 3 ONUs em "CTO-A": 2 Online (-20), 1 LOS
        for i, (status, sig) in enumerate([
            ("Online", "-20"), ("Online", "-22"), ("LOS", "-99"),
        ]):
            await db.smartolt_onus.insert_one({
                "id": f"o-{i}", "company_id": CO,
                "name": f"onu{i}", "sn": f"S{i}", "unique_external_id": f"UEI-A-{i}",
                "zone_name": "CTO-A",
                "status": status, "signal_1310": sig,
                "olt_name": "OLT1", "board": "1", "port": "1",
            })
        ctos = await twin.cto_health(CO)
        assert len(ctos) == 1
        assert ctos[0]["cto"] == "CTO-A"
        assert ctos[0]["total_onus"] == 3
        assert ctos[0]["offline"] == 1
        # média (100+100+0)/3 ≈ 66.7
        assert 60 < ctos[0]["score"] < 75
    _run(go)


def test_pon_health_counts():
    async def go(db, twin):
        for i, status in enumerate(["Online", "Online", "LOS", "Offline"]):
            await db.smartolt_onus.insert_one({
                "id": f"o2-{i}", "company_id": CO,
                "sn": f"S2{i}", "unique_external_id": f"UEI-B-{i}",
                "olt_name": "OLT1", "board": "1", "port": "5",
                "status": status,
            })
        pons = await twin.pon_health(CO)
        assert len(pons) == 1
        p = pons[0]
        assert p["total"] == 4
        assert p["online"] == 2
        assert p["los"] == 1
        assert p["offline"] == 1
    _run(go)


def test_predictions_structure():
    async def go(db, twin):
        # 1 ONU LOS em "CTO-B" → CTO degradada
        await db.smartolt_onus.insert_one({
            "id": "o-pr-1", "company_id": CO, "sn": "SPR1",
            "zone_name": "CTO-B", "status": "LOS",
            "olt_name": "OLT1", "board": "1", "port": "1",
        })
        pred = await twin.predictions(CO)
        for k in ("CTO_DEGRADED", "CTO_CRITICAL", "VLAN_SATURATED",
                   "MASS_OFFLINE", "CHURN_BY_SIGNAL"):
            assert k in pred
        assert pred["CTO_DEGRADED"]["predicted_count"] >= 1
    _run(go)


def test_what_to_worry_responds_all_questions():
    async def go(db, twin):
        await db.smartolt_onus.insert_one({
            "id": "o-w-1", "company_id": CO, "sn": "SW1",
            "zone_name": "CTO-W", "status": "LOS",
            "olt_name": "OLT1", "board": "1", "port": "1",
        })
        r = await twin.what_to_worry(CO)
        for k in ("qual_cto_preocupa", "bairro_degradando",
                  "onde_havera_saturacao", "risco_operacional",
                  "onde_investir_primeiro",
                  "predicted_next_problem_30d"):
            assert k in r and r[k] is not None
    _run(go)
