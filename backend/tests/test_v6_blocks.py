"""Testes V6.0 Bloco 2 (Blockers) + Bloco 8 (Predictive)."""
from __future__ import annotations
import asyncio, os, sys, importlib
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CO = "test-v6-blocks"
COLLS = [
    "subscribers", "subscriber_invoices", "motor_ia_actions",
    "motor_ia_decisions", "motor_ia_events", "tickets",
    "wa_baileys_sessions", "motor_ia_knowledge_graph",
]


def _run(coro):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import database as dm; dm.db = db
        from services import blockers_audit, smartolt_predictive
        from services import transport_check, multitenant_audit
        for m in (transport_check, multitenant_audit,
                   blockers_audit, smartolt_predictive):
            importlib.reload(m)
        for col in COLLS:
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro(db, blockers_audit, smartolt_predictive)
        finally:
            for col in COLLS:
                await db[col].delete_many({"company_id": CO})
            c.close()
    return asyncio.run(_wrap())


# ===== Bloco 2 — Blockers ===== #
def test_blockers_audit_detects_wa_credentials_missing():
    async def go(db, blk, _p):
        r = await blk.full_audit(CO)
        # WA não configurado → credentials blockers presentes
        cred = [b for b in r["blockers"] if b["kind"] == "credential"]
        assert len(cred) >= 3
        kinds = [b["blocker"] for b in cred]
        assert "WA_SIDECAR_TOKEN" in kinds
        assert "BAILEYS_SIDECAR_URL" in kinds
        assert "PRESIDENTE_IA_GESTOR_PHONE" in kinds
    _run(go)


def test_blockers_audit_reports_data_quality_issues():
    async def go(db, blk, _p):
        # Subscriber ATIVO sem phone
        await db.subscribers.insert_one({
            "id": "s1", "company_id": CO, "status": "ATIVO",
            "plan_price": 100})  # sem phone
        r = await blk.full_audit(CO)
        dq = [b for b in r["blockers"] if b["kind"] == "data_quality"]
        assert any(b["blocker"] == "active_subscribers_without_phone"
                    for b in dq)
    _run(go)


def test_blockers_audit_returns_headline():
    async def go(db, blk, _p):
        r = await blk.full_audit(CO)
        assert "headline" in r and "bloqueador" in r["headline"]
        assert "summary" in r
        assert r["summary"]["p0_count"] >= 1
    _run(go)


# ===== Bloco 8 — Predictive ===== #
def test_predict_cto_failures_identifies_critical_zones():
    async def go(db, _b, pred):
        # CTO crítica: 6 ONUs, 5 offline
        for i in range(5):
            await db.subscribers.insert_one({
                "id": f"off-{i}", "company_id": CO, "status": "ATIVO",
                "smartolt_onu_zone": "CTO-CRITICAL",
                "smartolt_onu_status": "Offline", "plan_price": 99})
        await db.subscribers.insert_one({
            "id": "on-1", "company_id": CO, "status": "ATIVO",
            "smartolt_onu_zone": "CTO-CRITICAL",
            "smartolt_onu_status": "Online", "plan_price": 99})
        rows = await pred.predict_cto_failures(CO)
        zones = [r["zone"] for r in rows]
        assert "CTO-CRITICAL" in zones
        crit = [r for r in rows if r["zone"] == "CTO-CRITICAL"][0]
        assert crit["severity"] in ("ALTO", "CRITICO")
        assert crit["impact_BRL_monthly"] > 0
        # XAI obrigatório
        for k in ("cause", "effect", "impact", "recommended_action",
                  "evidence", "confidence"):
            assert k in crit
    _run(go)


def test_predict_signal_churn_returns_at_risk_subscribers():
    async def go(db, _b, pred):
        for i in range(3):
            await db.subscribers.insert_one({
                "id": f"sig-{i}", "company_id": CO, "status": "ATIVO",
                "smartolt_onu_status": "LOS", "plan_price": 150})
        rows = await pred.predict_signal_churn(CO)
        assert len(rows) >= 3
        for r in rows:
            for k in ("cause", "effect", "impact",
                       "recommended_action", "evidence", "confidence"):
                assert k in r
            assert r["impact_BRL_monthly"] > 0
    _run(go)


def test_auto_create_preventive_tickets_creates_real_tickets():
    async def go(db, _b, pred):
        # Cria CTO crítica
        for i in range(5):
            await db.subscribers.insert_one({
                "id": f"cto-{i}", "company_id": CO, "status": "ATIVO",
                "smartolt_onu_zone": "CTO-AUTO",
                "smartolt_onu_status": "Offline", "plan_price": 100})
        await db.subscribers.insert_one({
            "id": "cto-ok", "company_id": CO, "status": "ATIVO",
            "smartolt_onu_zone": "CTO-AUTO",
            "smartolt_onu_status": "Online", "plan_price": 100})
        r = await pred.auto_create_preventive_tickets(
            CO, max_tickets=5)
        assert r["created"] >= 1
        # ticket existe no banco
        tk = await db.tickets.find_one({
            "company_id": CO, "origin": "smartolt_predictive"})
        assert tk is not None
    _run(go)


def test_predictive_summary_has_headline_and_kpis():
    async def go(db, _b, pred):
        r = await pred.predictive_summary(CO)
        assert "headline" in r
        assert "summary" in r
        assert "total_monthly_risk_BRL" in r
        for k in ("ctos_at_risk", "recurrent_onus",
                   "signal_churn_risks"):
            assert k in r
    _run(go)
