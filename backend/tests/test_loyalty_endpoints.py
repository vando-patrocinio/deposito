"""Testes leves dos endpoints de Fidelidade (iter215).

Garante que os 3 endpoints respondem com o shape esperado. Funciona como
"smoke test" pré-deploy: roda em < 5s e detecta regressão estrutural.

Rodar:
    cd /app/backend && pytest tests/test_loyalty_endpoints.py -v
"""
from __future__ import annotations

import os
import pytest
import httpx


API_URL = os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001"
ADMIN_EMAIL = os.environ.get("E2E_ADMIN_EMAIL", "admin@empresa.com")
ADMIN_PWD = os.environ.get("E2E_ADMIN_PASSWORD", "123456")


@pytest.fixture(scope="module")
def token():
    """Login admin e devolve JWT pra outros testes."""
    with httpx.Client(base_url=API_URL, timeout=30) as cli:
        r = cli.post("/api/auth/login",
                     json={"email": ADMIN_EMAIL, "password": ADMIN_PWD})
        r.raise_for_status()
        data = r.json()
        tok = data.get("access_token") or data.get("token")
        assert tok, f"Login não retornou token: {data}"
        return tok


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# /api/customer/loyalty-stats
# ---------------------------------------------------------------------------
def test_loyalty_stats_shape(auth_headers):
    with httpx.Client(base_url=API_URL, timeout=30) as cli:
        r = cli.get("/api/customer/loyalty-stats", headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        # Campos obrigatórios
        for k in ("buckets", "total_active", "vip_count", "vip_pct",
                  "oldest_years"):
            assert k in d, f"Campo '{k}' ausente: {list(d.keys())}"
        # Buckets devem conter as 5 faixas canônicas
        for b in ("<1ano", "1-3 anos", "3-5 anos", "5-10 anos", "10+ anos"):
            assert b in d["buckets"], f"Bucket '{b}' faltando"
        # Tipos
        assert isinstance(d["total_active"], int)
        assert isinstance(d["vip_count"], int)
        assert d["vip_count"] <= d["total_active"]


# ---------------------------------------------------------------------------
# /api/customer/loyalty-ranking
# ---------------------------------------------------------------------------
def test_loyalty_ranking_basic(auth_headers):
    with httpx.Client(base_url=API_URL, timeout=30) as cli:
        r = cli.get("/api/customer/loyalty-ranking",
                    params={"limit": 5},
                    headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("items", "count", "vip_count", "returned_count"):
            assert k in d
        assert len(d["items"]) <= 5
        # Cada item precisa de campos chave
        for it in d["items"]:
            for k in ("rank", "id", "name", "tenure_years", "is_vip",
                      "plan_name", "filial", "returned"):
                assert k in it, f"Campo '{k}' ausente no item: {list(it.keys())}"
            assert isinstance(it["tenure_years"], (int, float))
            assert it["tenure_years"] >= 0
        # Ranking ordenado: tenure desc
        tenures = [it["tenure_years"] for it in d["items"]]
        assert tenures == sorted(tenures, reverse=True), \
            f"Ranking fora de ordem: {tenures}"


def test_loyalty_ranking_skips_0800(auth_headers):
    """Planos com '0800' no nome NÃO podem aparecer no ranking."""
    with httpx.Client(base_url=API_URL, timeout=30) as cli:
        r = cli.get("/api/customer/loyalty-ranking",
                    params={"limit": 500},
                    headers=auth_headers)
        assert r.status_code == 200
        d = r.json()
        for it in d["items"]:
            assert "0800" not in (it.get("plan_name") or "").upper(), \
                f"Plano 0800 não filtrado: {it.get('plan_name')}"


# ---------------------------------------------------------------------------
# /api/customer/plan-migration-opportunities
# ---------------------------------------------------------------------------
def test_plan_migration_shape(auth_headers):
    with httpx.Client(base_url=API_URL, timeout=60) as cli:
        r = cli.get("/api/customer/plan-migration-opportunities",
                    params={"limit": 5, "min_savings_mbps": 30},
                    headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("items", "count", "vip_count", "total_savings_mbps"):
            assert k in d
        for it in d["items"]:
            # Tem que ter speed atual < best speed
            assert it["current_speed_mbps"] < it["best_speed_mbps"]
            assert it["delta_mbps"] >= 30
            assert it["price_brl"] > 0


# ---------------------------------------------------------------------------
# /api/customer/deactivated-list
# ---------------------------------------------------------------------------
def test_deactivated_list_shape(auth_headers):
    with httpx.Client(base_url=API_URL, timeout=30) as cli:
        r = cli.get("/api/customer/deactivated-list",
                    params={"limit": 10},
                    headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("items", "count", "by_praca"):
            assert k in d
        assert isinstance(d["by_praca"], list)


def test_churn_kpis_shape(auth_headers):
    with httpx.Client(base_url=API_URL, timeout=30) as cli:
        r = cli.get("/api/customer/churn-kpis", headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("total_deactivated", "total_active", "churn_rate_pct",
                  "avg_tenure_months_before_cancel", "median_tenure_months",
                  "avg_tenure_years", "buckets", "by_praca", "top_reasons"):
            assert k in d, f"Campo '{k}' ausente: {list(d.keys())}"
        # Buckets canônicos
        for b in ("<6 meses", "6m-1ano", "1-2 anos", "2-5 anos", "5+ anos"):
            assert b in d["buckets"], f"Bucket '{b}' faltando"
        assert isinstance(d["churn_rate_pct"], (int, float))
        assert 0 <= d["churn_rate_pct"] <= 100


# ---------------------------------------------------------------------------
# Auth — sem token deve dar 401
# ---------------------------------------------------------------------------
def test_endpoints_require_auth():
    with httpx.Client(base_url=API_URL, timeout=10) as cli:
        for path in ("/api/customer/loyalty-stats",
                     "/api/customer/loyalty-ranking",
                     "/api/customer/plan-migration-opportunities",
                     "/api/customer/deactivated-list",
                     "/api/customer/churn-kpis"):
            r = cli.get(path)
            assert r.status_code in (401, 403), \
                f"{path} aceitou sem auth: {r.status_code}"
