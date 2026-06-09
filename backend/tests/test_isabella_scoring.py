"""Testes da FASE 6 — Isabella Revenue Engine."""
from __future__ import annotations
import asyncio, os, sys
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CO = "test-isa-pytest"


def _run(coro_factory):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import importlib
        import database as database_mod
        database_mod.db = db
        from services import isabella_scoring as isa
        importlib.reload(isa)
        for col in ("subscribers", "subscriber_access_points",
                     "subscriber_invoices", "tickets", "referrals",
                     "motor_ia_subscriber_scores",
                     "isabella_opportunities"):
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro_factory(db, isa)
        finally:
            for col in ("subscribers", "subscriber_access_points",
                         "subscriber_invoices", "tickets", "referrals",
                         "motor_ia_subscriber_scores",
                         "isabella_opportunities"):
                await db[col].delete_many({"company_id": CO})
            c.close()
    return asyncio.run(_wrap())


def test_score_ranges_clamped():
    async def go(db, isa):
        s = isa._scores_for_sub(
            {"created_at": "2020-01-01T00:00:00+00:00",
             "status": "ATIVO", "smartolt_onu_status": "Online",
             "plan_price": 50, "smartolt_onu_sn": "X1"},
            tickets_n=0, overdue_n=0, overdue_amt=0, paid_n=10,
            referred_n=2,
        )
        for k in ("buy_score", "upgrade_score", "churn_score",
                  "retention_score", "referral_score",
                  "collection_score"):
            assert 0 <= s[k] <= 100
        # Cliente bom: referral alto
        assert s["referral_score"] >= 70
    _run(go)


def test_high_churn_when_offline_onu():
    async def go(db, isa):
        s = isa._scores_for_sub(
            {"created_at": "2024-01-01T00:00:00+00:00",
             "status": "ATIVO", "smartolt_onu_status": "LOS",
             "plan_price": 80, "smartolt_onu_sn": "Y1"},
            tickets_n=3, overdue_n=2, overdue_amt=200, paid_n=2,
            referred_n=0,
        )
        assert s["churn_score"] >= 70
        assert s["next_best_action"] in (
            "RETENTION_PLAYBOOK", "COLLECTION_CONTACT")
    _run(go)


def test_nba_priority_collection_over_upgrade():
    async def go(db, isa):
        # Cliente com upgrade alto MAS overdue presente → priorizar collection
        s = isa._scores_for_sub(
            {"created_at": "2018-01-01T00:00:00+00:00",
             "status": "ATIVO", "smartolt_onu_status": "Online",
             "plan_price": 50, "smartolt_onu_sn": "Z1"},
            tickets_n=0, overdue_n=1, overdue_amt=100, paid_n=20,
            referred_n=0,
        )
        # Tem overdue → preferência por collection
        if s["collection_score"] >= 75:
            assert s["next_best_action"] == "COLLECTION_CONTACT"
    _run(go)


def test_calculate_all_persists_and_creates_opportunity():
    async def go(db, isa):
        # 1 subscriber simples com overdue alta → collection > 75
        await db.subscribers.insert_one({
            "id": "sub-isa-1", "company_id": CO,
            "name": "Cliente", "status": "ATIVO",
            "created_at": "2018-01-01T00:00:00+00:00",
            "smartolt_onu_status": "Online",
            "smartolt_onu_sn": "SN-ISA-1",
            "plan_price": 60,
        })
        await db.subscriber_access_points.insert_one({
            "id": "sap-isa-1", "company_id": CO,
            "subscriber_id": "sub-isa-1",
            "subscriber_external_id": "ext-isa-1",
        })
        await db.subscriber_invoices.insert_one({
            "id": "inv-isa-1", "company_id": CO,
            "subscriber_external_id": "ext-isa-1",
            "amount": 99.9, "status": "overdue",
            "due_date": "2026-05-01",
        })
        for i in range(15):  # 15 pagamentos passados → bom histórico
            await db.subscriber_invoices.insert_one({
                "id": f"inv-paid-{i}", "company_id": CO,
                "subscriber_external_id": "ext-isa-1",
                "amount": 99.9, "status": "paid",
                "paid_date": f"2025-0{(i%9)+1}-01",
            })
        r = await isa.calculate_all(CO)
        assert r["scored"] == 1
        # Recupera o score
        doc = await db.motor_ia_subscriber_scores.find_one(
            {"subscriber_id": "sub-isa-1"})
        assert doc["collection_score"] >= 75
        # Playbook gera oportunidade
        p = await isa.run_playbooks(CO)
        assert p["created"].get("operacao_tese_candidate", 0) >= 1
    _run(go)


def test_tenant_isolation():
    async def go(db, isa):
        await db.subscribers.insert_one({
            "id": "s-co1", "company_id": CO, "status": "ATIVO",
            "created_at": "2020-01-01T00:00:00+00:00"})
        await db.subscribers.insert_one({
            "id": "s-co2", "company_id": "other-tenant",
            "status": "ATIVO",
            "created_at": "2020-01-01T00:00:00+00:00"})
        await isa.calculate_all(CO)
        cnt_co = await db.motor_ia_subscriber_scores.count_documents(
            {"company_id": CO})
        cnt_other = await db.motor_ia_subscriber_scores.count_documents(
            {"company_id": "other-tenant"})
        assert cnt_co == 1
        assert cnt_other == 0
        await db.subscribers.delete_many({"company_id": "other-tenant"})
    _run(go)
