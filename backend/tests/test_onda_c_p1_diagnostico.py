"""Onda C P1 — Watchtower Diagnostico + Audit script (READ-ONLY)."""
import os
import subprocess
import time
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PWD = "123456"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PWD}, timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ── Diagnostico endpoint ───────────────────────────────────────────────────

def test_diagnostico_requires_auth():
    r = requests.get(f"{BASE_URL}/api/watchtower/estoque/diagnostico", timeout=15)
    assert r.status_code in (401, 403), f"expected 401/403 unauth, got {r.status_code}"


def test_diagnostico_full_payload(auth_headers):
    r = requests.get(f"{BASE_URL}/api/watchtower/estoque/diagnostico?window_hours=24",
                     headers=auth_headers, timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    d = r.json()
    for k in ("company_id", "generated_at", "window_hours", "phases",
              "latency", "late_close", "reconcile", "swap_pending", "recent_errors"):
        assert k in d, f"missing key {k}"
    assert d["window_hours"] == 24
    assert isinstance(d["phases"], list) and len(d["phases"]) == 6
    for p in d["phases"]:
        for k in ("phase", "label", "ok", "error", "not_ok", "total", "success_rate_pct"):
            assert k in p, f"phase missing {k}: {p}"
    for k in ("p50_ms", "p95_ms", "samples", "completed_pct"):
        assert k in d["latency"]
    for k in ("runs_7d", "total_closed_ok_7d", "total_closed_failed_7d", "last_run"):
        assert k in d["late_close"]
    for k in ("runs_7d", "total_orphan_marked_7d", "last_run"):
        assert k in d["reconcile"]
    for k in ("total_pending", "top_techs", "last_events"):
        assert k in d["swap_pending"]
    assert isinstance(d["recent_errors"], list)
    assert len(d["recent_errors"]) <= 20


def test_diagnostico_window_bounds(auth_headers):
    # ok range
    r = requests.get(f"{BASE_URL}/api/watchtower/estoque/diagnostico?window_hours=1",
                     headers=auth_headers, timeout=20)
    assert r.status_code == 200
    r = requests.get(f"{BASE_URL}/api/watchtower/estoque/diagnostico?window_hours=168",
                     headers=auth_headers, timeout=20)
    assert r.status_code == 200
    # invalid
    r = requests.get(f"{BASE_URL}/api/watchtower/estoque/diagnostico?window_hours=0",
                     headers=auth_headers, timeout=20)
    assert r.status_code in (400, 422)
    r = requests.get(f"{BASE_URL}/api/watchtower/estoque/diagnostico?window_hours=999",
                     headers=auth_headers, timeout=20)
    assert r.status_code in (400, 422)


def test_diagnostico_is_readonly(auth_headers):
    """Two consecutive calls produce stable payload structure (smoke read-only)."""
    r1 = requests.get(f"{BASE_URL}/api/watchtower/estoque/diagnostico",
                      headers=auth_headers, timeout=30).json()
    time.sleep(0.5)
    r2 = requests.get(f"{BASE_URL}/api/watchtower/estoque/diagnostico",
                      headers=auth_headers, timeout=30).json()
    assert set(r1.keys()) == set(r2.keys())
    assert len(r1["phases"]) == len(r2["phases"]) == 6


def test_watchtower_summary_regression(auth_headers):
    r = requests.get(f"{BASE_URL}/api/watchtower/estoque/summary",
                     headers=auth_headers, timeout=30)
    assert r.status_code == 200, f"regression: {r.status_code} {r.text[:200]}"


# ── Audit script ───────────────────────────────────────────────────────────

def test_audit_script_print_only():
    """--print-only does not write a file."""
    out_path = Path("/app/memory/PRAÇA_TECNICO_AUDIT.md")
    pre_mtime = out_path.stat().st_mtime if out_path.exists() else None
    res = subprocess.run(
        ["python3", "/app/backend/scripts/audit_praca_tecnico.py",
         "--company-id", "co-demo", "--print-only"],
        capture_output=True, text=True, timeout=120,
    )
    assert res.returncode == 0, f"stderr: {res.stderr[:400]}"
    assert "AUDITORIA PRAÇA x TÉCNICO" in res.stdout
    assert "Sumário Global" in res.stdout
    post_mtime = out_path.stat().st_mtime if out_path.exists() else None
    assert pre_mtime == post_mtime, "print-only must NOT write file"


def test_audit_script_writes_file():
    """Default mode writes to /app/memory/PRAÇA_TECNICO_AUDIT.md with all sections."""
    res = subprocess.run(
        ["python3", "/app/backend/scripts/audit_praca_tecnico.py",
         "--company-id", "co-demo"],
        capture_output=True, text=True, timeout=120,
    )
    assert res.returncode == 0, f"stderr: {res.stderr[:400]}"
    p = Path("/app/memory/PRAÇA_TECNICO_AUDIT.md")
    assert p.exists()
    md = p.read_text(encoding="utf-8")
    assert "AUDITORIA PRAÇA x TÉCNICO" in md
    assert "Sumário Global" in md
    assert "Totais de inconsistências" in md
    assert "co-demo" in md
