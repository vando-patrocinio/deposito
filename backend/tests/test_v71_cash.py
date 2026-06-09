"""Testes V7.1 OPERAÇÃO CAIXA."""
from __future__ import annotations
import asyncio, os, sys, importlib
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CO = "test-v71-cash"
COLLS = [
    "subscribers", "subscriber_invoices", "motor_ia_actions",
    "motor_ia_decisions", "motor_ia_events", "motor_ia_outcomes",
    "motor_ia_autonomous_cycles", "wa_messages", "tickets",
]


def _run(coro):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import database as dm; dm.db = db
        from services import cash_operation
        from services import transport_check, financial_foundation
        from services import real_revenue, blockers_audit
        from services import smartolt_predictive
        for m in (transport_check, financial_foundation,
                   blockers_audit, smartolt_predictive,
                   real_revenue, cash_operation):
            importlib.reload(m)
        for col in COLLS:
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro(db, cash_operation)
        finally:
            for col in COLLS:
                await db[col].delete_many({"company_id": CO})
            c.close()
    return asyncio.run(_wrap())


def test_kpi_money_generated_returns_four_periods():
    async def go(db, cash):
        r = await cash.kpi_money_generated(CO)
        for p in ("today", "7d", "30d", "12m"):
            assert p in r
            assert "estimated" in r[p]
            assert "confirmed" in r[p]
            assert "received" in r[p]
    _run(go)


def test_war_room_returns_5_revenue_states():
    async def go(db, cash):
        r = await cash.war_room(CO)
        for k in ("revenue_at_risk_BRL", "revenue_recoverable_BRL",
                  "revenue_estimated_30d", "revenue_confirmed_30d",
                  "revenue_received_30d", "revenue_lost_7d_BRL",
                  "headline"):
            assert k in r
    _run(go)


def test_go_live_status_returns_blocked_when_no_wa():
    async def go(db, cash):
        r = await cash.go_live_status(CO)
        assert r["state"] in ("VERDE", "BLOQUEADO")
        # Sem WA configurado → BLOQUEADO
        assert r["state"] == "BLOQUEADO"
        assert len(r["blockers"]) >= 3
    _run(go)


def test_action_to_cash_funnel_has_all_stages():
    async def go(db, cash):
        r = await cash.action_to_cash(CO, days=30)
        stages = ["created", "sent", "delivered", "read", "replied",
                   "negotiated", "paid", "received"]
        for s in stages:
            assert s in r["funnel"]
    _run(go)


def test_top_money_actions_returns_priority_list():
    async def go(db, cash):
        r = await cash.top_money_actions(CO, top_n=10)
        assert "items" in r
        assert "total_BRL" in r
        # ordenado por ROI desc
        for i in range(len(r["items"]) - 1):
            assert r["items"][i]["roi_BRL"] \
                >= r["items"][i + 1]["roi_BRL"]
    _run(go)


def test_attribution_by_action_kind():
    async def go(db, cash):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        # 1 ciclo com outcome real positivo
        await db.motor_ia_decisions.insert_one({
            "company_id": CO, "decision_id": "d-attr",
            "created_at": now,
            "action_kind": "operacao_tese_tier_c",
            "expected_BRL": 100})
        await db.motor_ia_actions.insert_one({
            "company_id": CO, "action_id": "a-attr",
            "decision_id": "d-attr", "created_at": now,
            "status": "executed", "payload": {}})
        await db.motor_ia_outcomes.insert_one({
            "company_id": CO, "outcome_id": "o-attr",
            "action_id": "a-attr", "decision_id": "d-attr",
            "observed_at": now, "actual_BRL": 75})
        r = await cash.revenue_attribution_by(CO, "action_kind", 30)
        # Procura action_kind operacao_tese_tier_c
        found = [x for x in r["items"]
                 if x["key"] == "operacao_tese_tier_c"]
        assert len(found) == 1
        assert found[0]["actual_BRL"] == 75.0
    _run(go)
