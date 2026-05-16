"""Iter 98 — GESTAO_IA Modo Concorrente (SWOT)."""
import os

import httpx
import pytest
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
BASE = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://dual-combine-3.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE}/api"


async def _token():
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{API}/auth/login", json={
            "email": "admin@empresa.com", "password": "123456",
        })
    return r.json().get("access_token") or r.json().get("token")


@pytest.mark.asyncio
async def test_1_market_input_too_short_returns_400():
    token = await _token()
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{API}/gestao-ia/competitive-analysis",
                            json={"market_input": "curto"},
                            headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400
    assert "20 caracteres" in r.json()["detail"]


@pytest.mark.asyncio
async def test_2_unauthenticated_blocked():
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{API}/gestao-ia/competitive-analysis",
                            json={"market_input": "x" * 50})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_3_generates_swot_schema():
    token = await _token()
    payload = {"market_input": (
        "Concorrente Sumicity entrou no Centro com 500MB a R$79. "
        "Vivo Fibra expandindo em Vista Alegre com 1GB a R$99."
    )}
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(f"{API}/gestao-ia/competitive-analysis",
                            json=payload,
                            headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert "swot_analysis" in j
    swot = j["swot_analysis"]
    for k in ("resumo_estrategico", "swot", "concorrentes_identificados",
              "bairros_a_priorizar", "acoes_curto_prazo"):
        assert k in swot, f"missing {k}"
    for q in ("forcas", "fraquezas", "oportunidades", "ameacas"):
        assert q in swot["swot"]
        assert isinstance(swot["swot"][q], list)


@pytest.mark.asyncio
async def test_4_latest_after_generate():
    token = await _token()
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{API}/gestao-ia/competitive-analysis/latest",
                          headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    j = r.json()
    assert "swot_analysis" in j
    assert "market_input" in j
