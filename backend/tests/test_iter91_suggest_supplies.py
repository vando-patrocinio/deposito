"""Iter 91 — Sugestão de insumos baseada em mediana histórica."""
import asyncio
import os
import uuid
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")

BASE = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://dual-combine-3.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE}/api"


@pytest_asyncio.fixture
async def db():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    yield cli[os.environ["DB_NAME"]]
    cli.close()


@pytest.mark.asyncio
async def test_1_defaults_when_no_history():
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{API}/lousa/public/suggest-supplies",
            json={"type": "instalacao",
                  "neighborhood": "Bairro Inexistente XYZ",
                  "company_id": "co-demo"},
        )
    assert r.status_code == 200
    j = r.json()
    assert j["source"] == "defaults"
    assert j["qtd_drop"] == 80
    assert j["esticadores"] == 2
    assert "Sem histórico" in j["rationale"]


@pytest.mark.asyncio
async def test_2_defaults_zero_for_retirada():
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{API}/lousa/public/suggest-supplies",
            json={"type": "retirada", "company_id": "co-demo"},
        )
    assert r.status_code == 200
    j = r.json()
    # Retirada não consome FTTH; defaults zerados
    assert j["qtd_drop"] == 0
    assert j["cabo_rede"] == 0


@pytest.mark.asyncio
async def test_3_median_path_with_seeded_history(db):
    bairro = f"TestBairro-{uuid.uuid4().hex[:6]}"
    samples = [(80, 8), (90, 7), (70, 9), (85, 8)]
    docs = []
    for d, c_ in samples:
        docs.append({
            "id": f"tkt-iter91-{uuid.uuid4().hex[:8]}",
            "company_id": "co-demo",
            "type": "instalacao",
            "status": "finalizada",
            "closed_at": datetime.now(timezone.utc).isoformat(),
            "client_snapshot": {"neighborhood": bairro},
            "completion_data": {
                "qtd_drop": d, "esticadores": 2, "conectores_fast": 3,
                "cabo_rede": c_, "conectores_rede": 1,
            },
        })
    await db.tickets.insert_many(docs)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{API}/lousa/public/suggest-supplies",
                json={"type": "instalacao",
                      "neighborhood": bairro,
                      "company_id": "co-demo"},
            )
        assert r.status_code == 200
        j = r.json()
        assert j["sample_size"] == 4
        assert j["source"] == f"bairro:{bairro}"
        # Mediana de (70,80,85,90) = 82.5 → round 82 ou 83
        assert 80 <= j["qtd_drop"] <= 90
        assert j["cabo_rede"] in (7.5, 8.0)
        assert "mediana" in j["rationale"].lower()
    finally:
        await db.tickets.delete_many({"id": {"$regex": "^tkt-iter91-"}})


@pytest.mark.asyncio
async def test_4_falls_back_to_company_wide_when_bairro_empty(db):
    bairro_specific = f"VazioBairro-{uuid.uuid4().hex[:6]}"
    # Seed só empresa-wide, não no bairro
    docs = []
    for d in [100, 110, 90, 95]:
        docs.append({
            "id": f"tkt-iter91-{uuid.uuid4().hex[:8]}",
            "company_id": "co-demo",
            "type": "suporte",
            "status": "finalizada",
            "closed_at": datetime.now(timezone.utc).isoformat(),
            "client_snapshot": {"neighborhood": "Outro"},
            "completion_data": {
                "qtd_drop": d, "esticadores": 1, "conectores_fast": 1,
                "cabo_rede": 5, "conectores_rede": 1,
            },
        })
    await db.tickets.insert_many(docs)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{API}/lousa/public/suggest-supplies",
                json={"type": "suporte",
                      "neighborhood": bairro_specific,
                      "company_id": "co-demo"},
            )
        assert r.status_code == 200
        j = r.json()
        # Bairro específico tem 0 → cai para empresa-wide
        assert j["source"] == "empresa"
        assert j["sample_size"] >= 4
    finally:
        await db.tickets.delete_many({"id": {"$regex": "^tkt-iter91-"}})
