"""Testes FASE 10 — Autonomous Engine (V5.0)."""
from __future__ import annotations
import asyncio, os, sys
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CO = "test-auto-pytest"

COLLS_TO_CLEAN = [
    "subscribers", "subscriber_invoices", "motor_ia_subscriber_scores",
    "motor_ia_events", "motor_ia_analysis", "motor_ia_decisions",
    "motor_ia_actions", "motor_ia_outcomes", "motor_ia_learnings",
    "motor_ia_decision_quality", "motor_ia_autonomous_cycles",
    "motor_ia_autonomy_score", "motor_ia_tuning_log",
    "tickets",
]


def _run(coro):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import database as dm
        dm.db = db
        import importlib
        from services import autonomous_engine as eng
        from services import auto_tuning
        from services import transport_check
        from services import wa_dispatcher
        from services import reconcile_worker
        importlib.reload(transport_check)
        importlib.reload(wa_dispatcher)
        importlib.reload(reconcile_worker)
        importlib.reload(eng)
        importlib.reload(auto_tuning)
        for col in COLLS_TO_CLEAN:
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro(db, eng, auto_tuning)
        finally:
            for col in COLLS_TO_CLEAN:
                await db[col].delete_many({"company_id": CO})
            c.close()
    return asyncio.run(_wrap())


def test_full_cycle_event_to_learning_with_overdue():
    """Critério de aceite: 1 ciclo COMPLETO auditável."""
    async def go(db, eng, _):
        # Setup: subscriber com plano + 2 invoices overdue
        await db.subscribers.insert_one({
            "id": "sub-1", "company_id": CO, "document": "12345678900",
            "status": "ATIVO", "plan_price": 99.90})
        await db.subscriber_invoices.insert_many([
            {"company_id": CO, "subscriber_document": "12345678900",
             "amount": 99.90, "status": "overdue"},
            {"company_id": CO, "subscriber_document": "12345678900",
             "amount": 99.90, "status": "overdue"},
        ])
        # Roda 1 ciclo
        r = await eng.run_cycle({
            "event_type": "OVERDUE_DETECTED",
            "company_id": CO, "subscriber_id": "sub-1",
            "payload": {"overdue_count": 2}})
        # validações
        assert r["status"] == "complete"
        for k in ("analysis", "decision", "action",
                  "outcome", "learning"):
            assert k in r
        # decision tem XAI obrigatório (V5.0)
        d = r["decision"]
        for k in ("cause", "effect", "impact", "recommended_action",
                  "evidence", "confidence", "expected_BRL"):
            assert k in d
        assert d["expected_BRL"] > 0
        assert d["action_kind"] == "operacao_tese_tier_c"
        # persistência: cycle salvo
        cy = await db.motor_ia_autonomous_cycles.find_one(
            {"cycle_id": r["cycle_id"]})
        assert cy and cy["status"] == "complete"
        assert cy.get("human_intervention") is False
        # decision_quality persistido
        dq = await db.motor_ia_decision_quality.find_one(
            {"decision_id": d["decision_id"]})
        assert dq and dq["learned"] is True
    _run(go)


def test_cycle_with_high_churn_drives_retention_action():
    async def go(db, eng, _):
        await db.subscribers.insert_one({
            "id": "sub-churn", "company_id": CO,
            "status": "ATIVO", "plan_price": 199.0})
        await db.motor_ia_subscriber_scores.insert_one({
            "company_id": CO, "subscriber_id": "sub-churn",
            "churn_score": 0.92, "upgrade_score": 0.1,
            "buy_score": 0.1})
        r = await eng.run_cycle({
            "event_type": "ISABELLA_HIGH_CHURN", "company_id": CO,
            "subscriber_id": "sub-churn"})
        assert r["decision"]["action_kind"] == "retention_campaign"
        assert r["decision"]["expected_BRL"] > 0
    _run(go)


def test_cycle_with_onu_offline_creates_preventive_ticket():
    async def go(db, eng, _):
        await db.subscribers.insert_one({
            "id": "sub-onu", "company_id": CO, "status": "ATIVO",
            "plan_price": 89.0, "smartolt_onu_status": "Offline",
            "smartolt_onu_zone": "CTO-Z01"})
        r = await eng.run_cycle({
            "event_type": "ONU_DEGRADED", "company_id": CO,
            "subscriber_id": "sub-onu"})
        assert r["decision"]["action_kind"] == "preventive_ticket"
        assert r["action"]["status"] == "executed"
        # ticket real foi criado
        tk = (r["action"]["result"] or {}).get("ticket_id")
        ticket = await db.tickets.find_one({"id": tk})
        assert ticket
        assert ticket["origin"] == "autonomous_engine"
    _run(go)


def test_autonomy_score_classifies():
    async def go(db, eng, _):
        # Sem ciclos → score 0 (ASSISTIDO)
        s = await eng.compute_autonomy_score(CO, days=1)
        assert s["score"] == 0
        assert s["classification"] == "ASSISTIDO"
        # Roda 3 ciclos de ONU (todos executados)
        for i in range(3):
            await db.subscribers.insert_one({
                "id": f"x{i}", "company_id": CO, "status": "ATIVO",
                "plan_price": 100, "smartolt_onu_status": "Offline"})
            await eng.run_cycle({"event_type": "ONU_DEGRADED",
                                    "company_id": CO,
                                    "subscriber_id": f"x{i}"})
        s2 = await eng.compute_autonomy_score(CO, days=1)
        assert s2["score"] == 100.0
        assert s2["classification"] == "OPERACAO_AUTONOMA"
    _run(go)


def test_daily_briefing_answers_8_executive_questions():
    async def go(db, eng, _):
        # gera 1 ciclo com outcome
        await db.subscribers.insert_one({
            "id": "sub-q", "company_id": CO, "status": "ATIVO",
            "plan_price": 79.9, "smartolt_onu_status": "LOS"})
        await eng.run_cycle({"event_type": "ONU_DEGRADED",
                                "company_id": CO,
                                "subscriber_id": "sub-q"})
        b = await eng.daily_briefing(CO)
        assert "headline" in b
        q = b["questions"]
        for k in ("1_generated_today_BRL", "2_recovered_today_BRL",
                   "3_protected_today_BRL", "4_lost_today_BRL",
                   "5_learnings_today",
                   "6_planned_for_tomorrow_BRL",
                   "7_better_than_yesterday", "8_proof"):
            assert k in q
        # 8: prova com números
        proof = q["8_proof"]
        for k in ("today_BRL", "yesterday_BRL", "diff_BRL"):
            assert k in proof
    _run(go)


def test_drive_from_overdue_executes_bulk_cycles():
    async def go(db, eng, _):
        for i in range(3):
            await db.subscribers.insert_one({
                "id": f"o{i}", "company_id": CO, "status": "ATIVO",
                "plan_price": 100, "document": f"doc-{i}"})
            await db.subscriber_invoices.insert_one({
                "company_id": CO, "subscriber_document": f"doc-{i}",
                "amount": 100, "status": "overdue"})
        cycles = await eng.drive_from_overdue(CO, limit=10)
        assert len(cycles) == 3
        # todos completos
        for c in cycles:
            assert c["status"] == "complete"
    _run(go)


def test_auto_tuning_records_adjustments():
    async def go(db, eng, auto_tuning):
        # cria 2 ciclos com ROI baixo + 1 com ROI alto
        await db.motor_ia_autonomous_cycles.insert_many([
            {"company_id": CO, "started_at":
             "2026-06-08T00:00:00+00:00",
             "status": "complete", "action_kind": "retention_campaign",
             "expected_BRL": 1000, "actual_BRL": 100},
            {"company_id": CO, "started_at":
             "2026-06-08T01:00:00+00:00",
             "status": "complete", "action_kind": "retention_campaign",
             "expected_BRL": 1000, "actual_BRL": 1500},
        ])
        r = await auto_tuning.tune_thresholds(CO, window_days=30)
        assert "tunings" in r
        assert len(r["tunings"]) >= 1
    _run(go)
