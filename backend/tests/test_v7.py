"""test_v7.py — Constituição V7.0 — Execução Real."""
from __future__ import annotations
import asyncio, importlib, os, sys, uuid
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
CO = "test-v7-co"
COLLS = ["tickets", "smart_installs", "smart_repairs",
         "smart_withdrawals", "motor_ia_outcomes",
         "motor_ia_actions", "motor_ia_events",
         "motor_ia_autonomous_cycles", "motor_ia_decisions",
         "motor_ia_failure_risk_scores", "motor_ia_learnings",
         "subscribers", "smartolt_onus", "payments_received",
         "wa_outbox", "wa_messages_sent"]


def _run(coro):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        os.environ["HOMOLOG_MODE"] = "true"
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import database as dm
        dm.db = db
        from services import execution_v7 as v7
        from services import company_v6 as v6
        from services import homologation as homo
        from services import autonomous_engine as eng
        for m in (homo, eng, v6, v7):
            importlib.reload(m)
        for col in COLLS:
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro(db, v7)
        finally:
            for col in COLLS:
                await db[col].delete_many({"company_id": CO})
            c.close()
    return asyncio.new_event_loop().run_until_complete(_wrap())


def _id(p):
    return f"{p}-{uuid.uuid4().hex[:8]}"


def test_classify_ticket_regex_install_repair_withdraw():
    from services import execution_v7 as v7
    assert v7.classify_ticket(
        {"subject": "nova instalação cliente"}) == "INSTALL"
    assert v7.classify_ticket(
        {"category": "retirada"}) == "WITHDRAW"
    assert v7.classify_ticket(
        {"subject": "sem sinal, LOS"}) == "REPAIR"
    assert v7.classify_ticket({"subject": "outro"}) is None


def test_backfill_populates_category():
    async def t(db, v7):
        await db.tickets.insert_many([
            {"id": _id("tk"), "company_id": CO,
             "subject": "instalação nova", "category": None,
             "opened_at": datetime.now(timezone.utc).isoformat()},
            {"id": _id("tk"), "company_id": CO,
             "subject": "sem sinal LOS", "category": "",
             "opened_at": datetime.now(timezone.utc).isoformat()},
        ])
        out = await v7.backfill_tickets(CO, window_days=30)
        assert out["classified"]["INSTALL"] == 1
        assert out["classified"]["REPAIR"] == 1
        # Verificar persistência
        n = await db.tickets.count_documents({
            "company_id": CO, "category": "INSTALL"})
        assert n == 1
    _run(t)


def test_predict_install_returns_resources():
    async def t(db, v7):
        sid = _id("sub")
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO,
            "smartolt_onu_zone": "CTO-A", "plan_price": 80,
            "status": "active"})
        out = await v7.predict_install_resources(CO, sid)
        p = out["predicted"]
        assert p["splitter_recommended"] in ("1x8", "1x16")
        assert p["cable_meters_estimate"] > 0
        assert p["tech_minutes_estimate"] in (90, 120)
        assert "ONT" in p["materials"]
        assert 0 <= p["confidence"] <= 1
    _run(t)


def test_predict_repair_los_recomenda_tecnico():
    async def t(db, v7):
        cid = _id("c")
        tk_id = _id("tk")
        await db.subscribers.insert_one({
            "id": cid, "company_id": CO,
            "smartolt_onu_status": "LOS"})
        await db.tickets.insert_one({
            "id": tk_id, "company_id": CO, "client_id": cid,
            "subject": "sem sinal",
            "opened_at": datetime.now(timezone.utc).isoformat()})
        r = await v7.predict_repair_outcome(CO, tk_id)
        assert r["should_send_tech"] is True
        assert r["recommended_action"] == "DESPACHAR_TECNICO"
        assert r["p_remote_resolution"] < 0.5
    _run(t)


def test_payment_received_matches_outcome_and_closes_cycle():
    async def t(db, v7):
        sid = "sub-pay"
        oid = _id("out")
        await db.motor_ia_outcomes.insert_one({
            "id": oid, "company_id": CO,
            "subscriber_id": sid, "action_id": "act-pay",
            "environment": "production",
            "status": "executed",
            "expected_BRL": 100.0, "actual_BRL": 0,
            "observed_at": datetime.now(timezone.utc).isoformat()})
        await db.motor_ia_actions.insert_one({
            "id": "act-pay", "company_id": CO,
            "expected_BRL": 100, "actual_BRL": 0,
            "status": "executed"})
        out = await v7.payment_received(
            CO, client_id=sid, amount_BRL=95.0,
            provider="pix", payment_ref="E2E-XYZ")
        assert out["matched_outcome_id"] == oid
        assert out["amount_BRL"] == 95.0
        oc = await db.motor_ia_outcomes.find_one({"id": oid})
        assert oc["status"] == "revenue_received"
        assert oc["actual_BRL"] == 95.0
        # Receipt persistido
        r = await db.payments_received.find_one(
            {"id": out["receipt_id"]})
        assert r is not None
    _run(t)


def test_operacao_tese_batch_uses_homolog_redirection():
    async def t(db, v7):
        # 2 outcomes pendentes
        for _ in range(2):
            oid = _id("out")
            await db.motor_ia_outcomes.insert_one({
                "id": oid, "company_id": CO,
                "subscriber_id": _id("sub"),
                "environment": "production",
                "status": "executed", "expected_BRL": 75,
                "actual_BRL": 0,
                "observed_at": datetime.now(timezone.utc).isoformat()})
        out = await v7.operacao_tese_run_batch(CO, batch_size=10)
        assert out["candidates_found"] == 2
        assert out["messages_sent"] == 2
        # Modo homolog → todas redirecionadas
        assert out["all_redirected_to_test_phone"] is True
    _run(t)


def test_proof_of_value_returns_nine_kpis():
    async def t(db, v7):
        # Cenário mínimo: 1 outcome recebido
        oid = _id("out")
        await db.motor_ia_outcomes.insert_one({
            "id": oid, "company_id": CO,
            "subscriber_id": "sub-x", "environment": "production",
            "status": "revenue_received",
            "expected_BRL": 100, "actual_BRL": 95,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "observed_at": datetime.now(timezone.utc).isoformat()})
        # 1 install FTC
        await db.smart_installs.insert_one({
            "id": _id("sfi"), "company_id": CO,
            "first_time_complete": True,
            "created_at": datetime.now(timezone.utc).isoformat()})
        # 1 repair com truck avoided
        await db.smart_repairs.insert_one({
            "id": _id("sfr"), "company_id": CO,
            "truck_roll_avoided": True,
            "created_at": datetime.now(timezone.utc).isoformat()})
        out = await v7.proof_of_value(CO, window_days=30)
        k = out["kpis"]
        for fld in ("receita_recuperada_BRL", "receita_protegida_BRL",
                    "truck_rolls_evitados", "first_time_fix_pct",
                    "recuperacao_ativos_pct",
                    "eficiencia_tecnica_ciclos_pct", "roi_da_ia_BRL"):
            assert fld in k
        assert k["receita_recuperada_BRL"] == 95.0
        assert k["truck_rolls_evitados"] == 1
        assert k["first_time_fix_pct"] == 100.0
        # Definição de sucesso V7
        s = out["success_definition_v7"]
        assert s["gera_receita_real"] is True
        assert s["reduz_truck_roll_real"] is True
        assert "success_score" in out
    _run(t)
