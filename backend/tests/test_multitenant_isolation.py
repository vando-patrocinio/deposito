"""test_multitenant_isolation.py — FASE 1 da OPERAÇÃO MATURIDADE COMERCIAL.

Garante que NENHUM endpoint do Presidente IA / Cash / Operator vaza
dados entre tenants. Cria temporariamente um tenant `co-iso-test`
com 1 entry no executive_ledger e verifica que admin@co-demo NÃO vê.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

import pytest  # noqa
import httpx  # noqa
from motor.motor_asyncio import AsyncIOMotorClient  # noqa


API_URL = os.environ.get(
    "API_URL", "https://dual-combine-3.preview.emergentagent.com")
DB_NAME = os.environ["DB_NAME"]
MONGO_URL = os.environ["MONGO_URL"]


async def _setup_isolation():
    c = AsyncIOMotorClient(MONGO_URL)
    db = c[DB_NAME]
    cid = "co-iso-test"
    await db.companies.update_one(
        {"id": cid},
        {"$set": {"id": cid, "name": "Iso Test"}}, upsert=True)
    await db.executive_ledger.update_one(
        {"action_id": "iso-test-action-1"},
        {"$set": {
            "action_id": "iso-test-action-1",
            "company_id": cid,
            "executed_at":
                datetime.now(timezone.utc).isoformat(),
            "categoria": "DISPARO_COBRANCA",
            "modulo": "Cobrança",
            "responsavel": "iso-test-bot",
            "valor_previsto_brl": 99999.0,
            "valor_confirmado_brl": 88888.0,
            "status": "CONFIRMED"}}, upsert=True)
    c.close()


async def _cleanup_isolation():
    c = AsyncIOMotorClient(MONGO_URL)
    db = c[DB_NAME]
    await db.executive_ledger.delete_many(
        {"company_id": "co-iso-test"})
    await db.companies.delete_one({"id": "co-iso-test"})
    c.close()


async def _login(client) -> str:
    r = await client.post(f"{API_URL}/api/auth/login",
                              json={"email": "admin@empresa.com",
                                     "password": "123456"})
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_cash_endpoints_no_cross_tenant_leak():
    """Admin de co-demo NÃO deve ver os R$88.888 do co-iso-test."""
    await _setup_isolation()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            token = await _login(client)
            headers = {"Authorization": f"Bearer {token}"}

            r = await client.get(f"{API_URL}/api/presidente-ia/cash",
                                       headers=headers)
            assert r.status_code == 200, r.text
            d = r.json()
            # admin é de co-demo. Não pode aparecer 88888 no caixa
            assert d["caixa_gerado_30d_brl"] != 88888.0
            assert d["company_id"] == "co-demo"

            # ia-ranking não pode listar iso-test-bot
            r = await client.get(
                f"{API_URL}/api/presidente-ia/cash/ia-ranking",
                headers=headers)
            assert r.status_code == 200
            ias = [it["ia"] for it in r.json()["items"]]
            assert "iso-test-bot" not in ias, (
                f"VAZAMENTO: iso-test-bot apareceu em {ias}")

            # module-ranking não pode somar R$88888
            r = await client.get(
                f"{API_URL}/api/presidente-ia/cash/module-ranking",
                headers=headers)
            modulos = r.json()["items"]
            cobranca = next((m for m in modulos
                                if m["modulo"] == "Cobrança"), None)
            if cobranca:
                assert cobranca["confirmado_brl"] < 88888.0, (
                    f"VAZAMENTO Cobrança={cobranca}")
    finally:
        await _cleanup_isolation()


@pytest.mark.asyncio
async def test_governador_no_cross_tenant_leak():
    """Governador e brain devem retornar apenas dados de co-demo."""
    await _setup_isolation()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            token = await _login(client)
            headers = {"Authorization": f"Bearer {token}"}
            for ep in (
                "governador/saude",
                "governador/relatorio-diario",
                "governador/sistema-nervoso",
                "brain/autopilot/top10",
                "self/audit",
                "self/readiness",
                "evolution/backlog",
                "operator/morning-briefing",
                "lucro",
                "company-value",
                "top-opportunities",
                "top-wastes",
            ):
                r = await client.get(
                    f"{API_URL}/api/presidente-ia/{ep}",
                    headers=headers)
                assert r.status_code == 200, f"{ep} {r.status_code}"
                # toda resposta deve estar amarrada em co-demo
                body = r.text
                assert "co-iso-test" not in body, (
                    f"VAZAMENTO em {ep}: {body[:200]}")
                assert "iso-test-bot" not in body
                assert "iso-test-action-1" not in body
    finally:
        await _cleanup_isolation()


@pytest.mark.asyncio
async def test_cross_tenant_ranking_inclui_ambos():
    """Cross-tenant ranking (admin endpoint) deve listar ambos."""
    await _setup_isolation()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            token = await _login(client)
            headers = {"Authorization": f"Bearer {token}"}
            r = await client.get(
                f"{API_URL}/api/presidente-ia/cash/cross-tenant-ranking",
                headers=headers)
            assert r.status_code == 200
            ids = [t["company_id"] for t in r.json()["tenants"]]
            assert "co-iso-test" in ids
            assert "co-demo" in ids
            iso = next(t for t in r.json()["tenants"]
                          if t["company_id"] == "co-iso-test")
            assert iso["caixa_confirmado_brl"] == 88888.0
    finally:
        await _cleanup_isolation()


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
