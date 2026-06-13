"""Regression suite — Indique e Ganhe / Customer flow.

CTO 13/06/2026 — este teste existe pra travar a recorrência do bug
"Não autenticado" no fluxo público do cliente. Esse bug apareceu
2 vezes no mesmo mês porque o middleware RBAC bloqueava endpoints
que deveriam ser públicos.

Sintoma esperado se o middleware regredir:
    HTTP 401 "Não autenticado" em /api/customer/login

Esses testes batem direto na app sem rolar autenticação corporativa.
"""
from __future__ import annotations

import pytest
import httpx
import os

API_URL = os.environ.get(
    "TEST_API_URL",
    "http://localhost:8001",
)


@pytest.mark.asyncio
async def test_customer_login_endpoint_is_public():
    """`/api/customer/login` DEVE responder sem JWT corporativo.

    Se voltar 401 "Não autenticado" significa que o middleware está
    bloqueando antes do handler — regressão do bug do CTO 13/06.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{API_URL}/api/customer/login",
            json={"cpf": "11111111111"},  # CPF inválido → handler deve dar 400
        )
        # ANY response que NÃO seja 401 "Não autenticado" passa o teste
        # (400 = CPF inválido / 404 = não encontrado / 200 = OK).
        # 401 = middleware bloqueou ANTES do handler = REGRESSÃO.
        assert r.status_code != 401, (
            f"REGRESSÃO! /api/customer/login retornou 401 — middleware "
            f"está bloqueando antes do handler. Resposta: {r.text[:200]}"
        )


@pytest.mark.asyncio
async def test_customer_login_validates_invalid_cpf():
    """CPF placeholder (11 dígitos repetidos) deve dar 400 do handler."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{API_URL}/api/customer/login",
            json={"cpf": "11111111111"},
        )
        assert r.status_code == 400
        assert "CPF" in r.text


@pytest.mark.asyncio
async def test_referrals_public_mural_no_auth():
    """`/api/referrals/public/mural` deve responder sem JWT (KPIs anônimos)."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{API_URL}/api/referrals/public/mural")
        assert r.status_code == 200, (
            f"/api/referrals/public/mural deveria ser público; "
            f"got {r.status_code}: {r.text[:200]}"
        )


@pytest.mark.asyncio
async def test_referrals_landing_info_no_auth():
    """`/api/r/{code}/info` é público (landing compartilhada)."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Código inválido → 404 do handler é OK (não 401 do middleware)
        r = await client.get(f"{API_URL}/api/r/INVALIDXYZ/info")
        assert r.status_code != 401, (
            f"REGRESSÃO! /api/r/{{code}}/info bloqueado pelo middleware. "
            f"Resposta: {r.text[:200]}"
        )


@pytest.mark.asyncio
async def test_customer_me_requires_token():
    """`/api/customer/me` DEVE exigir token (mas via handler, não middleware).

    Sem token: 401 do handler `_require_customer` ("Token ausente").
    Com token corporativo errado: 401 do handler ("Token inválido").
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Sem header Authorization
        r = await client.get(f"{API_URL}/api/customer/me")
        assert r.status_code == 401
        # Mensagem deve ser do handler, NÃO do middleware genérico
        assert "Token ausente" in r.text or "Token" in r.text


@pytest.mark.asyncio
async def test_customer_full_flow_when_subscriber_exists():
    """Fluxo E2E completo: login → me → stats → leaderboard → milestone.

    Skipa se não houver subscriber com CPF cadastrado no DB.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Tenta com CPF "famoso" 00000000191 (Receita Federal). Provavelmente 404.
        r = await client.post(
            f"{API_URL}/api/customer/login",
            json={"cpf": "00000000191"},
        )
        if r.status_code == 404:
            pytest.skip("Nenhum subscriber com este CPF no DB de teste.")
        assert r.status_code == 200
        body = r.json()
        token = body["token"]
        assert token

        # /me
        r = await client.get(
            f"{API_URL}/api/customer/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200

        # /stats
        r = await client.get(
            f"{API_URL}/api/customer/stats",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200

        # /leaderboard
        r = await client.get(
            f"{API_URL}/api/customer/leaderboard",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200

        # /milestone-cards
        r = await client.get(
            f"{API_URL}/api/customer/milestone-cards",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
