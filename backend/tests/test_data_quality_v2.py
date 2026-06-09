"""Testes da FASE 2 da Constituição V3.0 — Data Quality.

Usa o padrão _run() com event loop fresh por teste (motor + pytest).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


CO = "test-dq-pytest"


def _run(coro_factory):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        import importlib
        import database as database_mod
        database_mod.db = db
        from services import data_quality_v2 as dq_mod
        importlib.reload(dq_mod)
        # cleanup
        for col in ("subscribers", "subscriber_phones",
                     "subscriber_invoices", "smartolt_onus",
                     "subscriber_access_points",
                     "subscriber_addresses", "atlaz_clients_cache"):
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro_factory(db, dq_mod)
        finally:
            for col in ("subscribers", "subscriber_phones",
                         "subscriber_invoices", "smartolt_onus",
                         "subscriber_access_points",
                         "subscriber_addresses", "atlaz_clients_cache",
                         "data_quality_snapshots"):
                await db[col].delete_many({"company_id": CO})
            client.close()
    return asyncio.run(_wrap())


def _seed_basic(db):
    """Cria 10 subscribers, com phone/whatsapp/onu para todos."""
    async def go():
        for i in range(10):
            sid = f"sub-dq-{i}"
            await db.subscribers.insert_one({
                "id": sid, "company_id": CO,
                "name": f"Cliente {i}",
                "document": f"1234567{i:04d}",
                "phone": f"5511990000{i:03d}",
                "whatsapp": f"5511990000{i:03d}",
                "status": "ATIVO",
                "pppoe_user": f"pppoe_{i}",
                "smartolt_onu_sn": f"SN{i:04d}",
                "current_vlan_olt": "OLT1",
            })
            await db.subscriber_invoices.insert_one({
                "id": f"inv-dq-{i}", "company_id": CO,
                "subscriber_external_id": f"ext-{i}",
                "amount": 100.0, "due_date": "2026-05-01",
                "status": "open",
            })
            await db.smartolt_onus.insert_one({
                "id": f"onu-dq-{i}", "company_id": CO,
                "unique_external_id": f"UNIQ-DQ-{i}",
                "sn": f"SN{i:04d}", "status": "Online",
                "signal_1310": "-22.0",
            })
            await db.subscriber_phones.insert_one({
                "id": f"ph-dq-{i}", "company_id": CO,
                "subscriber_id": sid,
                "normalized_number": f"5511990000{i:03d}",
                "is_whatsapp": True,
            })
    return go


def test_score_clientes_full_dataset():
    async def go(db, dq):
        await _seed_basic(db)()
        r = await dq.score_clientes(CO)
        assert r["total"] == 10
        assert r["score"] == 100.0  # todos com doc+phone+wa
    _run(go)


def test_score_rede_full_dataset():
    async def go(db, dq):
        await _seed_basic(db)()
        r = await dq.score_rede(CO)
        # ok: pppoe + smartolt_onu_sn presentes → 100%
        assert r["score"] == 100.0
    _run(go)


def test_score_financeiro_full_dataset():
    async def go(db, dq):
        await _seed_basic(db)()
        r = await dq.score_financeiro(CO)
        assert r["score"] == 100.0
    _run(go)


def test_score_smartolt_full_dataset():
    async def go(db, dq):
        await _seed_basic(db)()
        r = await dq.score_smartolt(CO)
        assert r["score"] == 100.0
    _run(go)


def test_full_report_levels_match_overall():
    async def go(db, dq):
        await _seed_basic(db)()
        r = await dq.full_report(CO)
        assert "overall_score" in r
        assert r["overall_level"] in [
            "SAUDAVEL", "AMARELO", "VERMELHO", "INCIDENTE_EXECUTIVO"]
        assert "answers" in r
        for k in ("qualidade_hoje", "principal_gap",
                  "impacto_financeiro", "corrigir_primeiro"):
            assert k in r["answers"]
    _run(go)


def test_revenue_impact_locked_when_no_phone():
    async def go(db, dq):
        # Cliente overdue SEM phone/whatsapp → represado
        await db.subscribers.insert_one({
            "id": "sub-locked", "company_id": CO,
            "name": "Sem telefone", "document": "00000000000",
            "status": "ATIVO",
            "pppoe_user": "pppoe_x", "smartolt_onu_sn": "SN-X",
        })
        await db.subscriber_invoices.insert_one({
            "id": "inv-locked", "company_id": CO,
            "subscriber_external_id": "ext-locked",
            "amount": 250.0, "due_date": "2026-05-01",
            "status": "overdue",
        })
        await db.subscriber_access_points.insert_one({
            "id": "sap-locked", "company_id": CO,
            "subscriber_id": "sub-locked",
            "subscriber_external_id": "ext-locked",
            "pppoe_user": "pppoe_x", "status": "Ativo",
        })
        r = await dq.revenue_impact(CO)
        assert r["locked_BRL"] >= 250.0
        assert "sem_telefone_whatsapp" in r["reasons"]
    _run(go)


def test_score_levels():
    async def go(db, dq):
        from services.data_quality_v2 import _level
        assert _level(95) == "SAUDAVEL"
        assert _level(94.9) == "AMARELO"
        assert _level(89) == "VERMELHO"
        assert _level(79) == "INCIDENTE_EXECUTIVO"
    _run(go)


def test_tenant_isolation():
    async def go(db, dq):
        await _seed_basic(db)()
        r_co = await dq.score_clientes(CO)
        r_other = await dq.score_clientes("other-co")
        assert r_co["total"] == 10
        assert r_other["total"] == 0
    _run(go)
