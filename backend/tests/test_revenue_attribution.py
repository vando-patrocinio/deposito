"""Testes da Fase 1 da Constituição V3.0 — RevenueOps IA.

Usa o padrão de _run() criando event loop fresh por teste,
para contornar conflito conhecido AsyncIOMotorClient + pytest-asyncio.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


CO = "test-revops-pytest"


def _run(coro_factory):
    """Roda coroutine em loop fresco para evitar conflito motor + pytest."""
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        # Re-import service para que ele use o motor atual
        import importlib
        import database as database_mod
        database_mod.db = db
        from services import revenue_attribution
        importlib.reload(revenue_attribution)
        # Cleanup
        await db.motor_ia_revenue_attribution.delete_many(
            {"company_id": CO})
        try:
            res = await coro_factory(db, revenue_attribution)
        finally:
            await db.motor_ia_revenue_attribution.delete_many(
                {"company_id": CO})
            client.close()
        return res
    return asyncio.run(_wrap())


def test_attribute_basic():
    async def go(db, mod):
        doc = await mod.attribute(
            company_id=CO, kind="recovered", amount_BRL=150.00,
            template="amigavel_5_15d", channel="whatsapp_baileys",
        )
        assert doc["amount_BRL"] == 150.00
        assert doc["kind"] == "recovered"
        s = await mod.summary(CO)
        assert s["recovered"]["total_BRL"] == 150.00
        assert s["recovered"]["count"] == 1
        assert s["_total_BRL"] == 150.00
    _run(go)


def test_attribute_idempotent_by_action_id():
    async def go(db, mod):
        await mod.attribute(company_id=CO, kind="recovered",
                                  amount_BRL=100, action_id="act-test-1")
        # 2ª chamada com mesmo action_id+kind → não duplica
        await mod.attribute(company_id=CO, kind="recovered",
                                  amount_BRL=999, action_id="act-test-1")
        s = await mod.summary(CO)
        assert s["recovered"]["count"] == 1
        assert s["recovered"]["total_BRL"] == 100.00
    _run(go)


def test_attribute_invalid_kind():
    async def go(db, mod):
        with pytest.raises(ValueError):
            await mod.attribute(company_id=CO, kind="invalid_xyz",
                                      amount_BRL=10)
    _run(go)


def test_attribute_zero_amount():
    async def go(db, mod):
        with pytest.raises(ValueError):
            await mod.attribute(company_id=CO, kind="recovered",
                                      amount_BRL=0)
    _run(go)


def test_summary_filters_by_period():
    async def go(db, mod):
        now = datetime.now(timezone.utc)
        await mod.attribute(company_id=CO, kind="recovered", amount_BRL=200)
        s = await mod.summary(CO, since=now - timedelta(days=1),
                                    until=now + timedelta(hours=1))
        assert s["recovered"]["total_BRL"] == 200.00
    _run(go)


def test_by_template_aggregation():
    async def go(db, mod):
        await mod.attribute(company_id=CO, kind="recovered", amount_BRL=100,
                                  template="A", action_id="a1")
        await mod.attribute(company_id=CO, kind="recovered", amount_BRL=300,
                                  template="A", action_id="a2")
        await mod.attribute(company_id=CO, kind="recovered", amount_BRL=50,
                                  template="B", action_id="b1")
        rows = await mod.by_template(CO)
        assert len(rows) == 2
        assert rows[0]["template"] == "A"
        assert rows[0]["total_BRL"] == 400.00
        assert rows[0]["count"] == 2
    _run(go)


def test_multi_kind_summary():
    async def go(db, mod):
        await mod.attribute(company_id=CO, kind="recovered", amount_BRL=500)
        await mod.attribute(company_id=CO, kind="generated", amount_BRL=300)
        await mod.attribute(company_id=CO, kind="churn_prevented",
                                  amount_BRL=200)
        await mod.attribute(company_id=CO, kind="cost_saved",
                                  amount_BRL=100)
        s = await mod.summary(CO)
        assert s["recovered"]["total_BRL"] == 500
        assert s["generated"]["total_BRL"] == 300
        assert s["churn_prevented"]["total_BRL"] == 200
        assert s["cost_saved"]["total_BRL"] == 100
        assert s["_total_BRL"] == 1100
        assert s["_total_count"] == 4
    _run(go)


def test_tenant_isolation():
    async def go(db, mod):
        await mod.attribute(company_id=CO, kind="recovered", amount_BRL=999)
        await mod.attribute(company_id="other-tenant", kind="recovered",
                                  amount_BRL=1)
        s_co = await mod.summary(CO)
        s_other = await mod.summary("other-tenant")
        assert s_co["recovered"]["total_BRL"] == 999
        assert s_other["recovered"]["total_BRL"] == 1
        await db.motor_ia_revenue_attribution.delete_many(
            {"company_id": "other-tenant"})
    _run(go)
