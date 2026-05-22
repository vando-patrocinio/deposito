"""Tests for GET /api/whatsapp-baileys/viability-heatmap.

Coverage:
- 200 + estrutura correta para role gestor (admin@empresa.com)
- range days=7 / 30 / 90 retornam window_days correto
- districts vem ordenado desc por leads
- 403/401 sem token
- demo data (6 leads em Recreio/Jacarepagua/Olaria) presente
"""
from __future__ import annotations

import os
import pytest
import requests

BACKEND = (os.environ.get("REACT_APP_BACKEND_URL")
           or "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
EP = f"{BACKEND}/api/whatsapp-baileys/viability-heatmap"


@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BACKEND}/api/auth/login",
        json={"email": "admin@empresa.com", "password": "123456"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token")
    assert tok
    return tok


@pytest.fixture
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_heatmap_default_30d(auth_headers):
    r = requests.get(EP, headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["window_days"] == 30
    assert "total_pending" in data
    assert "districts" in data and isinstance(data["districts"], list)
    assert "districts_count" in data
    # Demo data: at least 3 districts and 6 leads
    assert data["total_pending"] >= 6
    assert data["districts_count"] >= 3


def test_heatmap_districts_shape(auth_headers):
    r = requests.get(f"{EP}?days=30", headers=auth_headers, timeout=20)
    data = r.json()
    for d in data["districts"]:
        assert "district" in d and isinstance(d["district"], str)
        assert "leads" in d and isinstance(d["leads"], int)
        assert "unique_phones" in d and isinstance(d["unique_phones"], int)
        assert "last_at" in d
    # Verifica que está ordenado desc por leads
    leads = [d["leads"] for d in data["districts"]]
    assert leads == sorted(leads, reverse=True)


def test_heatmap_demo_districts_present(auth_headers):
    r = requests.get(f"{EP}?days=30", headers=auth_headers, timeout=20)
    data = r.json()
    names = {d["district"].lower() for d in data["districts"]}
    assert "recreio" in names
    assert "jacarepagua" in names
    assert "olaria" in names
    # Recreio deve ser top com 3 leads
    top = data["districts"][0]
    assert top["district"].lower() == "recreio"
    assert top["leads"] >= 3


@pytest.mark.parametrize("days", [7, 30, 90])
def test_heatmap_range(auth_headers, days):
    r = requests.get(f"{EP}?days={days}", headers=auth_headers, timeout=20)
    assert r.status_code == 200
    assert r.json()["window_days"] == days


def test_heatmap_requires_auth():
    r = requests.get(EP, timeout=15)
    assert r.status_code in (401, 403)


def test_heatmap_days_clamped(auth_headers):
    # days extremo deve ser clamped (1..365)
    r = requests.get(f"{EP}?days=9999", headers=auth_headers, timeout=20)
    assert r.status_code == 200
    assert r.json()["window_days"] == 365
    # days=0 é falsy no Python (int(0) or 30 → 30) — fica no default
    r2 = requests.get(f"{EP}?days=0", headers=auth_headers, timeout=20)
    assert r2.status_code == 200
    assert r2.json()["window_days"] == 30
