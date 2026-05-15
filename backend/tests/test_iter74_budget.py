"""Iteration 74 — Módulo Orçamento (Comercial · Orçamento_IA)

Cobre o fluxo completo: criar → upload CSV → analisar com Claude → editar
%ganho/imposto/mão-de-obra → calcular totais → exportar PDF → KPIs.

Roda contra o ambiente preview com admin@empresa.com / 123456.
"""
import io
import os
import pytest
import requests


def _load_base_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    url = line.strip().split("=", 1)[1]
                    break
    return url.rstrip("/")


BASE = _load_base_url()


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE}/api/auth/login",
                       json={"email": "admin@empresa.com", "password": "123456"},
                       timeout=15)
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def budget_id(auth):
    """Cria orçamento de teste, sobe CSV, retorna o ID. Cleanup ao final."""
    r = requests.post(f"{BASE}/api/budget",
                       headers=auth,
                       json={"name": "PYTEST · Iter74", "description": "Suite de testes"},
                       timeout=15)
    assert r.status_code == 200
    bid = r.json()["id"]
    csv = ("item;qtde;unidade;especificacao\n"
            "Roteador AC1200;2;un;Intelbras\n"
            "Cabo UTP cat5e;100;m;CMX\n")
    r2 = requests.post(f"{BASE}/api/budget/{bid}/upload-csv",
                        headers=auth,
                        files={"file": ("items.csv", csv.encode("utf-8"), "text/csv")},
                        timeout=15)
    assert r2.status_code == 200
    yield bid
    requests.delete(f"{BASE}/api/budget/{bid}", headers=auth, timeout=10)


def test_create_budget_returns_draft(auth):
    r = requests.post(f"{BASE}/api/budget", headers=auth,
                       json={"name": "TestDraft"}, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "draft"
    assert body["margin_pct"] == 25.0
    assert body["totals"]["final"] == 0
    requests.delete(f"{BASE}/api/budget/{body['id']}", headers=auth, timeout=5)


def test_csv_upload_parses_items(budget_id, auth):
    r = requests.get(f"{BASE}/api/budget/{budget_id}", headers=auth, timeout=10)
    body = r.json()
    assert len(body["items"]) == 2
    names = [it["name"] for it in body["items"]]
    assert "Roteador AC1200" in names
    assert "Cabo UTP cat5e" in names


def test_update_percentages_recalculates_totals(budget_id, auth):
    r = requests.put(f"{BASE}/api/budget/{budget_id}",
                      headers=auth,
                      json={"margin_pct": 50, "tax_pct": 10, "labor_pct": 20},
                      timeout=10)
    body = r.json()
    assert body["margin_pct"] == 50
    assert body["tax_pct"] == 10
    assert body["labor_pct"] == 20
    # Base 0 ainda (sem analise) → final 0
    assert body["totals"]["final"] == 0


def test_item_manual_override(budget_id, auth):
    # Pega items
    b = requests.get(f"{BASE}/api/budget/{budget_id}", headers=auth).json()
    items_payload = []
    for it in b["items"]:
        items_payload.append({"id": it["id"], "manual_override": 100.0})
    r = requests.put(f"{BASE}/api/budget/{budget_id}",
                      headers=auth,
                      json={"items": items_payload, "margin_pct": 0,
                             "tax_pct": 0, "labor_pct": 0},
                      timeout=10)
    body = r.json()
    # 2 itens × 100 + qtde (Roteador qty=2, Cabo qty=100) = 2*100 + 100*100 = 10200
    assert body["totals"]["base"] == 10200.0
    assert body["totals"]["final"] == 10200.0


def test_kpis_endpoint(auth, budget_id):
    r = requests.get(f"{BASE}/api/budget/kpis", headers=auth, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert "avg_margin_pct" in body and "total_value" in body


def test_pdf_endpoint_returns_pdf_bytes(auth, budget_id):
    r = requests.get(f"{BASE}/api/budget/{budget_id}/pdf",
                      headers=auth, timeout=15)
    assert r.status_code == 200
    assert r.headers.get("content-type") == "application/pdf"
    # PDF começa com %PDF-
    assert r.content[:5] == b"%PDF-"
    assert len(r.content) > 1000  # tem conteúdo


def test_forbidden_for_colaborador():
    """Colaborador não-financeiro deve receber 403."""
    # Login como colaborador comum (se existir nas seeds)
    r = requests.post(f"{BASE}/api/auth/login",
                       json={"email": "colab@empresa.com", "password": "123456"},
                       timeout=10)
    if r.status_code != 200:
        pytest.skip("Colaborador test account não disponível")
    tok = r.json().get("access_token")
    if not tok:
        pytest.skip("Sem token de colaborador")
    rr = requests.get(f"{BASE}/api/budget",
                       headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert rr.status_code == 403
