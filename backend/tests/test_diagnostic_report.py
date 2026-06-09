"""Tests for GET /api/conselho-ia/diagnostic-report (16-section diag report)."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
    "https://dual-combine-3.preview.emergentagent.com"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                       json={"email": "admin@empresa.com",
                             "password": "123456"}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json().get("access_token") or r.json().get("token")


def _hdr(t): return {"Authorization": f"Bearer {t}"}


def test_requires_auth():
    r = requests.get(f"{BASE_URL}/api/conselho-ia/diagnostic-report",
                      timeout=20)
    assert r.status_code in (401, 403)


def test_returns_16_sections_and_meta(token):
    t0 = time.time()
    r = requests.get(f"{BASE_URL}/api/conselho-ia/diagnostic-report?days=30",
                      headers=_hdr(token), timeout=30)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    data = r.json()
    # Meta
    assert data.get("period_days") == 30
    assert isinstance(data.get("elapsed_ms"), int)
    assert data["elapsed_ms"] < 10000
    assert elapsed < 12
    # 16 sections
    sections = data.get("sections", {})
    expected_keys = [
        "01_executive_summary", "02_module_map", "03_ai_engine",
        "04_database", "05_operations", "06_network", "07_gps_fleet",
        "08_security", "09_financials", "10_kpis", "11_automations",
        "12_integrations", "13_roadmap", "14_ai_auto_analysis",
        "15_executive_review", "16_anomalies",
    ]
    assert sorted(sections.keys()) == sorted(expected_keys)
    for k in expected_keys:
        assert "title" in sections[k]
        assert "data" in sections[k]


def test_days_parameter_reflected(token):
    r = requests.get(f"{BASE_URL}/api/conselho-ia/diagnostic-report?days=7",
                      headers=_hdr(token), timeout=30)
    assert r.status_code == 200
    j = r.json()
    assert j["period_days"] == 7
    assert j["sections"]["01_executive_summary"]["data"]["periodo_dias"] == 7


def test_section_shapes(token):
    r = requests.get(f"{BASE_URL}/api/conselho-ia/diagnostic-report?days=30",
                      headers=_hdr(token), timeout=30)
    assert r.status_code == 200
    s = r.json()["sections"]
    d01 = s["01_executive_summary"]["data"]
    for k in ("total_clientes", "mrr_brl", "churn_pct",
              "inadimplencia_pct", "ticket_medio_brl"):
        assert k in d01
    assert isinstance(s["02_module_map"]["data"]["modulos"], list)
    assert "top_20_volume" in s["04_database"]["data"]
    integ = s["12_integrations"]["data"]["integracoes"]
    assert isinstance(integ, list) and len(integ) > 0
    assert all("nome" in i and "ativo" in i and "evidencia" in i
               for i in integ)
    d15 = s["15_executive_review"]["data"]
    assert "estado_geral" in d15 and "riscos" in d15 \
        and "pontos_fortes" in d15
    d16 = s["16_anomalies"]["data"]
    assert "subscribers_sem_plano" in d16 \
        and "emails_duplicados" in d16
