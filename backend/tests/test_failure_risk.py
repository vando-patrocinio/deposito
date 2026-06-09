"""
test_failure_risk.py — Sprint 2 (Constituição V5.0)

Cobre:
  - Composição do failure_risk_score (6 sinais + região)
  - Classificação BAIXO/MEDIO/ALTO/CRITICO
  - Emissão do evento FAILURE_RISK_HIGH quando score > 80
  - Ciclo autônomo completo (driver dispara run_cycle do
    autonomous_engine que persiste Decision V5 + Action + Outcome +
    Learning + cycle row)
  - Métricas Fase H (preventive_ratio, prevented_churn_BRL,
    prevented_revenue_loss_BRL)

Pattern `_run()` para isolar event loop como demais testes async.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CO = "test-frs-v5"
COLLS = [
    "subscribers", "smartolt_onus", "tickets",
    "client_equipment_history",
    "motor_ia_events", "motor_ia_analysis",
    "motor_ia_decisions", "motor_ia_actions",
    "motor_ia_outcomes", "motor_ia_learnings",
    "motor_ia_decision_quality", "motor_ia_autonomous_cycles",
    "motor_ia_recurrence_scores", "motor_ia_failure_risk_scores",
    "motor_ia_subscriber_scores",
]


def _run(coro):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import database as dm
        dm.db = db
        from services import failure_risk as fr
        from services import alvaro_v5 as av5
        from services import autonomous_engine as eng
        from services import smartolt_twin as twin
        from services import transport_check as txc
        importlib.reload(twin)
        importlib.reload(txc)
        importlib.reload(av5)
        importlib.reload(fr)
        importlib.reload(eng)
        for col in COLLS:
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro(db, fr, eng)
        finally:
            for col in COLLS:
                await db[col].delete_many({"company_id": CO})
            c.close()
    return asyncio.new_event_loop().run_until_complete(_wrap())


def _id(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:10]}"


def test_classify_boundaries():
    from services import failure_risk as fr
    assert fr._classify(0) == "BAIXO"
    assert fr._classify(30) == "BAIXO"
    assert fr._classify(31) == "MEDIO"
    assert fr._classify(60) == "MEDIO"
    assert fr._classify(61) == "ALTO"
    assert fr._classify(80) == "ALTO"
    assert fr._classify(81) == "CRITICO"
    assert fr._classify(100) == "CRITICO"


def test_compute_failure_risk_healthy_subscriber_is_baixo():
    async def t(db, fr, eng):
        sid = _id("sub")
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO, "status": "active",
            "smartolt_onu_status": "Online",
            "plan_price": 100,
        })
        r = await fr.compute_failure_risk(
            sid, company_id=CO, persist=False)
        assert r["score"] < 30
        assert r["classification"] == "BAIXO"
        assert r["should_open_preventive_os"] is False
        # Evidência presente (Regra de Ouro)
        types = [e["type"] for e in r["evidence"]]
        for must in ("onu_status", "tickets_30d",
                     "recurrence_score", "cto_health_score",
                     "churn_score"):
            assert must in types
    _run(t)


def test_compute_failure_risk_los_with_churn_is_critico_and_emits_event():
    async def t(db, fr, eng):
        sid = _id("sub")
        sn = _id("sn")
        # ONU em LOS + sinal degradado + CTO ruim
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO, "status": "active",
            "smartolt_onu_status": "LOS",
            "smartolt_onu_sn": sn,
            "smartolt_onu_zone": "CTO-PROBLEMA",
            "plan_price": 150,
        })
        await db.smartolt_onus.insert_one({
            "company_id": CO, "sn": sn, "status": "LOS",
            "signal_1310": -30,
            "olt_name": "OLT-X", "board": 1, "port": 1,
            "zone_name": "CTO-PROBLEMA",
        })
        # Churn score alto
        await db.motor_ia_subscriber_scores.insert_one({
            "subscriber_id": sid, "company_id": CO,
            "churn_score": 0.9,
        })
        # Tickets recentes
        base = datetime.now(timezone.utc)
        await db.tickets.insert_many([{
            "id": _id("tk"), "company_id": CO, "client_id": sid,
            "opened_at": (base - timedelta(days=i + 1)).isoformat(),
            "status": "open", "subject": "queda",
        } for i in range(5)])

        r = await fr.compute_failure_risk(
            sid, company_id=CO, persist=True)
        assert r["score"] > 80, (
            f"esperado >80 (CRITICO), obtido {r['score']}")
        assert r["classification"] == "CRITICO"
        assert r["should_open_preventive_os"] is True
        assert r["expected_revenue_at_risk_BRL"] > 0

        # Evento FAILURE_RISK_HIGH deve ter sido emitido
        ev = await db.motor_ia_events.find_one({
            "subscriber_id": sid,
            "event_type": "FAILURE_RISK_HIGH",
        })
        assert ev is not None
        assert ev["consumed"] is False
        assert ev["payload"]["failure_risk_score"] == r["score"]
    _run(t)


def test_drive_from_failure_risk_creates_preventive_cycle_and_ticket():
    async def t(db, fr, eng):
        sid = _id("sub")
        sn = _id("sn")
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO, "status": "active",
            "smartolt_onu_status": "LOS",
            "smartolt_onu_sn": sn,
            "smartolt_onu_zone": "CTO-DRIVE",
            "plan_price": 200,
        })
        await db.smartolt_onus.insert_one({
            "company_id": CO, "sn": sn, "status": "LOS",
            "signal_1310": -30, "olt_name": "OLT-Y",
            "board": 1, "port": 1, "zone_name": "CTO-DRIVE",
        })
        await db.motor_ia_subscriber_scores.insert_one({
            "subscriber_id": sid, "company_id": CO, "churn_score": 0.9,
        })
        # Tickets recentes para garantir score > 80
        base = datetime.now(timezone.utc)
        await db.tickets.insert_many([{
            "id": _id("tk"), "company_id": CO, "client_id": sid,
            "opened_at": (base - timedelta(days=i + 1)).isoformat(),
            "status": "open", "subject": "queda",
        } for i in range(5)])

        out = await fr.drive_from_failure_risk(CO, limit=10)
        assert out["processed"] == 1
        assert out["preventive_cycles_triggered"] == 1, (
            f"esperado 1 ciclo, raw={out}")
        assert len(out["cycle_ids"]) == 1
        cyc_id = out["cycle_ids"][0]

        # Ciclo deve estar completo
        cyc = await db.motor_ia_autonomous_cycles.find_one(
            {"cycle_id": cyc_id})
        assert cyc is not None
        assert cyc["status"] == "complete"
        assert cyc.get("decision_id")
        assert cyc.get("action_id")
        assert cyc.get("outcome_id")
        assert cyc.get("learning_id")

        # Decision deve estar populada com cause/effect/impact V5-like
        dec = await db.motor_ia_decisions.find_one(
            {"decision_id": cyc["decision_id"]})
        assert dec is not None
        assert dec["cause"]
        assert dec["effect"]
        assert dec["impact"]
        assert dec["recommended_action"]
        assert isinstance(dec["evidence"], list) and dec["evidence"]
        assert dec["action_kind"] == "preventive_ticket"

        # Action: ticket preventivo criado real (não bloqueado por WA)
        act = await db.motor_ia_actions.find_one(
            {"action_id": cyc["action_id"]})
        assert act is not None
        assert act["status"] == "executed"
        assert act["kind"] == "preventive_ticket"
        ticket_id = (act.get("result") or {}).get("ticket_id")
        assert ticket_id
        tk = await db.tickets.find_one({"id": ticket_id})
        assert tk is not None
        assert tk["origin"] == "autonomous_engine"
        assert tk["priority"] == "ALTA"
    _run(t)


def test_failure_risk_does_not_trigger_when_score_below_80():
    async def t(db, fr, eng):
        sid = _id("sub")
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO, "status": "active",
            "smartolt_onu_status": "Online",
            "plan_price": 100,
        })
        # Apenas 1 ticket recente — score baixo
        base = datetime.now(timezone.utc)
        await db.tickets.insert_one({
            "id": _id("tk"), "company_id": CO, "client_id": sid,
            "opened_at": (base - timedelta(days=1)).isoformat(),
            "status": "open", "subject": "lentidão",
        })
        out = await fr.drive_from_failure_risk(CO, limit=10)
        assert out["preventive_cycles_triggered"] == 0
    _run(t)


def test_phase_h_metrics_computes_ratio_and_prevented_revenue():
    async def t(db, fr, eng):
        # Cenário: 1 ciclo preventivo + 1 corretivo
        sid_pre = _id("sub")
        sid_cor = _id("sub")
        sn = _id("sn")
        for sid, status, zone in (
                (sid_pre, "LOS", "CTO-A"),
                (sid_cor, "Offline", "CTO-B")):
            await db.subscribers.insert_one({
                "id": sid, "company_id": CO, "status": "active",
                "smartolt_onu_status": status,
                "smartolt_onu_zone": zone,
                "plan_price": 100,
            })
        await db.smartolt_onus.insert_one({
            "company_id": CO, "sn": sn, "status": "LOS",
            "signal_1310": -30, "zone_name": "CTO-A",
            "olt_name": "OLT-Z", "board": 1, "port": 1,
        })
        await db.subscribers.update_one(
            {"id": sid_pre}, {"$set": {"smartolt_onu_sn": sn}})
        await db.motor_ia_subscriber_scores.insert_one({
            "subscriber_id": sid_pre, "company_id": CO,
            "churn_score": 0.9,
        })
        # Tickets recentes para o sid_pre alcançar > 80
        base = datetime.now(timezone.utc)
        await db.tickets.insert_many([{
            "id": _id("tk"), "company_id": CO, "client_id": sid_pre,
            "opened_at": (base - timedelta(days=i + 1)).isoformat(),
            "status": "open", "subject": "queda",
        } for i in range(5)])

        # Dispara um ciclo preventivo via FAILURE_RISK_HIGH
        await fr.drive_from_failure_risk(CO, limit=10)
        # E um ciclo corretivo via ONU_DEGRADED
        await eng.run_cycle({
            "event_type": "ONU_DEGRADED",
            "company_id": CO,
            "subscriber_id": sid_cor,
            "payload": {"onu_status": "Offline"},
        })

        m = await fr.phase_h_metrics(CO, window_days=30)
        assert m["preventive_count"] >= 1
        assert m["corrective_count"] >= 1
        assert 0.0 < m["preventive_ratio"] < 1.0
        assert m["prevented_churn_BRL"] > 0
        assert "generated_at" in m
    _run(t)
