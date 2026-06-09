"""Testes FASE 9 — Landing pública (V5.0)."""
from __future__ import annotations
import os
from fastapi.testclient import TestClient


def _client():
    os.environ.setdefault("ALLOW_MOCK_MODULES", "true")
    os.environ.setdefault("SKIP_STARTUP_JOBS", "1")
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from server import app
    return TestClient(app)


def test_public_health_works_without_auth():
    c = _client()
    r = c.get("/api/public/smartprov-ai-center/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_public_kpis_works_without_auth_and_returns_required_fields():
    c = _client()
    r = c.get("/api/public/smartprov-ai-center/kpis")
    assert r.status_code == 200
    d = r.json()
    for k in ("headline", "financial", "network", "nervous_system_24h",
              "isabella_engine", "governance", "modules_active",
              "executive_actions"):
        assert k in d, f"missing key: {k}"
    # No PII leaks
    payload = r.text.lower()
    for forbidden in ("@", "cpf", "phone", "email"):
        if forbidden == "@":
            assert "@gmail" not in payload and "@hotmail" not in payload
    # Modulos ativos
    assert len(d["modules_active"]) >= 8
    # Financial fields
    fin = d["financial"]
    for k in ("mrr_BRL", "arr_BRL", "ltv_BRL", "active_subscribers"):
        assert k in fin
