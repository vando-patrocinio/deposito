"""test_v6.py — Constituição V6.0 (P1+P2+P3+P4)."""
from __future__ import annotations
import asyncio, importlib, os, sys, uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CO = "test-v6-co"
COLLS = ["tickets", "smart_installs", "smart_repairs",
         "smart_withdrawals", "motor_ia_outcomes",
         "motor_ia_actions", "motor_ia_learnings",
         "motor_ia_events", "motor_ia_failure_risk_scores",
         "motor_ia_autonomous_cycles",
         "autonomous_company_scores",
         "smartolt_onus", "subscribers",
         "fin_cash_movements"]


def _run(coro):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import database as dm
        dm.db = db
        from services import company_v6 as v6
        from services import observability_twin as twin
        from services import failure_risk as fr
        from services import ops_v51
        for m in (twin, fr, ops_v51, v6):
            importlib.reload(m)
        for col in COLLS:
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro(db, v6)
        finally:
            for col in COLLS:
                await db[col].delete_many({"company_id": CO})
            c.close()
    return asyncio.new_event_loop().run_until_complete(_wrap())


def _id(p):
    return f"{p}-{uuid.uuid4().hex[:8]}"


def test_classify_kind_from_ticket():
    from services import company_v6 as v6
    assert v6._classify_kind_from_ticket(
        {"category": "instalacao"}) == "install"
    assert v6._classify_kind_from_ticket(
        {"category": "retirada"}) == "withdraw"
    assert v6._classify_kind_from_ticket(
        {"subject": "reparo de cabo"}) == "repair"
    assert v6._classify_kind_from_ticket(
        {"category": "outro"}) is None


def test_sync_smart_field_ops_classifies_tickets():
    async def t(db, v6):
        for cat, subj in (("instalação", "nova"),
                          ("retirada", "withdraw"),
                          ("manutenção", "reparo"),
                          ("outro", "qq")):
            await db.tickets.insert_one({
                "id": _id("tk"), "company_id": CO,
                "client_id": _id("c"), "category": cat,
                "subject": subj, "status": "open",
                "opened_at": datetime.now(timezone.utc).isoformat()})
        out = await v6.sync_smart_field_ops(CO, window_days=30)
        assert out["synced"]["install"] == 1
        assert out["synced"]["withdraw"] == 1
        assert out["synced"]["repair"] == 1
        assert out["synced"]["unclassified"] == 1
        # Tabelas smart_* populadas
        assert await db.smart_installs.count_documents(
            {"company_id": CO}) == 1
        assert await db.smart_repairs.count_documents(
            {"company_id": CO}) == 1
        assert await db.smart_withdrawals.count_documents(
            {"company_id": CO}) == 1
    _run(t)


def test_smart_field_kpis_calcula_corretamente():
    async def t(db, v6):
        # 2 installs (1 reopened = quality 0, 1 closed = quality 100)
        await db.tickets.insert_many([
            {"id": _id("tk"), "company_id": CO,
             "client_id": _id("c"), "category": "instalação",
             "subject": "i1", "status": "closed",
             "reopened": False,
             "opened_at": datetime.now(timezone.utc).isoformat()},
            {"id": _id("tk"), "company_id": CO,
             "client_id": _id("c"), "category": "instalação",
             "subject": "i2", "status": "closed",
             "reopened": True,
             "opened_at": datetime.now(timezone.utc).isoformat()},
            # 1 reparo remoto + 1 truck-roll
            {"id": _id("tk"), "company_id": CO,
             "client_id": _id("c"), "category": "reparo",
             "subject": "r1", "status": "closed",
             "resolution_kind": "remote",
             "opened_at": datetime.now(timezone.utc).isoformat()},
            # 1 retirada com asset_recovered=True
            {"id": _id("tk"), "company_id": CO,
             "client_id": _id("c"), "category": "retirada",
             "subject": "w1", "status": "closed",
             "asset_recovered": True,
             "opened_at": datetime.now(timezone.utc).isoformat()},
        ])
        await v6.sync_smart_field_ops(CO, window_days=30)
        k = await v6.smart_field_ops_kpis(CO, window_days=30)
        assert k["installs"]["total"] == 2
        assert k["installs"]["first_time_complete"] == 1
        assert k["installs"]["quality_score_pct"] == 50.0
        assert k["repairs"]["truck_roll_avoidance_pct"] == 100.0
        assert k["withdrawals"]["asset_recovery_score_pct"] == 100.0
    _run(t)


def test_mark_revenue_received_fecha_outcome_e_persiste_learning():
    async def t(db, v6):
        oid = _id("out")
        await db.motor_ia_outcomes.insert_one({
            "id": oid, "company_id": CO,
            "subscriber_id": "sub-x", "action_id": "act-x",
            "environment": "production",
            "status": "executed",
            "expected_BRL": 100.0, "actual_BRL": 0.0,
            "observed_at": datetime.now(timezone.utc).isoformat()})
        await db.motor_ia_actions.insert_one({
            "id": "act-x", "company_id": CO,
            "status": "executed", "expected_BRL": 100, "actual_BRL": 0})
        out = await v6.mark_revenue_received(
            CO, oid, 95.50, source="manual_test", payment_ref="PIX-X")
        assert out["actual_BRL"] == 95.50
        assert out["status"] == "revenue_received"
        # Outcome atualizado
        oc = await db.motor_ia_outcomes.find_one({"id": oid})
        assert oc["actual_BRL"] == 95.50
        assert oc["status"] == "revenue_received"
        # Action atualizada
        act = await db.motor_ia_actions.find_one({"id": "act-x"})
        assert act["status"] == "revenue_confirmed"
        # Learning gravado
        lrn = await db.motor_ia_learnings.find_one(
            {"company_id": CO, "outcome_id": oid,
             "kind": "revenue_confirmation"})
        assert lrn is not None
        assert lrn["actual_BRL"] == 95.50
        assert lrn["delta_BRL"] == -4.5
    _run(t)


def test_mark_revenue_rejects_homolog_outcome():
    async def t(db, v6):
        oid = _id("out")
        await db.motor_ia_outcomes.insert_one({
            "id": oid, "company_id": CO,
            "environment": "homolog",
            "expected_BRL": 100, "actual_BRL": 0,
            "observed_at": datetime.now(timezone.utc).isoformat()})
        r = await v6.mark_revenue_received(CO, oid, 100)
        assert "error" in r
        assert r["error"] == "homolog_outcome_cannot_be_marked_real"
    _run(t)


def test_reconcile_with_cash_matches_outcome_to_movement():
    async def t(db, v6):
        sid = "sub-recon"
        oid = _id("out")
        await db.motor_ia_outcomes.insert_one({
            "id": oid, "company_id": CO,
            "subscriber_id": sid, "action_id": "act-r",
            "environment": "production",
            "status": "executed",
            "expected_BRL": 75.0, "actual_BRL": 0,
            "observed_at": datetime.now(timezone.utc).isoformat()})
        await db.motor_ia_actions.insert_one({
            "id": "act-r", "company_id": CO,
            "status": "executed", "expected_BRL": 75})
        await db.fin_cash_movements.insert_one({
            "id": "mov-1", "company_id": CO,
            "type": "income", "client_id": sid,
            "amount": 75.0,
            "created_at": datetime.now(timezone.utc).isoformat()})
        out = await v6.reconcile_with_cash(CO, window_days=30)
        assert out["matched_outcomes"] >= 1
        assert out["total_received_BRL"] == 75.0
        oc = await db.motor_ia_outcomes.find_one({"id": oid})
        assert oc["status"] == "revenue_received"
        assert oc["revenue_source"] == "auto_reconcile_cash"
    _run(t)


def test_autonomous_company_score_compoe_e_explica():
    async def t(db, v6):
        s = await v6.autonomous_company_score(CO, window_days=30)
        assert 0 <= s["score"] <= 100
        for k in ("infrastructure_health", "failure_risk_inverse",
                  "preventive_ratio_pct", "technician_avg",
                  "revenue_realization_pct", "smart_field_quality"):
            assert k in s["components"]
        # Soma de pesos = 100
        assert sum(s["weights"].values()) == 100
        # 6 perguntas respondidas (Regra de Ouro)
        ans = s["answers_six_questions"]
        for q in ("aumenta_receita", "reduz_churn", "reduz_truck_roll",
                  "melhora_campo", "melhora_rede",
                  "ajuda_presidente_decidir"):
            assert q in ans
        # Persiste para evolução diária
        ev = await db.autonomous_company_scores.find_one(
            {"company_id": CO, "date": s["date"]})
        assert ev is not None
        # Explicação textual
        assert s["explanation"]["narrative"]
    _run(t)


def test_digital_twin_summary_has_four_quadrants():
    async def t(db, v6):
        out = await v6.digital_twin_summary(CO, window_days=30)
        q = out["quadrants"]
        assert set(q.keys()) == {"network", "infrastructure",
                                  "field", "financial"}
        for name, card in q.items():
            for must in ("problem", "cause", "impact", "action",
                         "confidence", "evidence", "score"):
                assert must in card, f"{name} sem {must}"
        assert 0 <= out["overall_score"] <= 100
    _run(t)
