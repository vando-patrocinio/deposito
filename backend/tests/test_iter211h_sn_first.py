"""iter211h — SN obrigatório como chave primária para ONTs.

Valida:
- Cadastro bulk via `items: [{sn, mac?}]` (preferido).
- Cadastro bulk legado via `macs: [str]` (cada string tratada como SN).
- Rejeita cadastro sem nenhum SN.
- Rejeita SN duplicado.
- Endpoint de rastreabilidade encontra ONT por SN.
"""
import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://dual-combine-3.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, pw):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _hdr(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@empresa.com", "123456")


@pytest.fixture(scope="module")
def unique_sn():
    return f"ITER211HSN{uuid.uuid4().hex[:8].upper()}"


def test_bulk_rejects_without_sn(admin_tok):
    """Sem SN nem MAC → 400."""
    r = requests.post(f"{API}/stok/onts/bulk",
                       json={"model": "Test Model"},
                       headers=_hdr(admin_tok), timeout=20)
    assert r.status_code == 400, r.text
    assert "SN" in r.json().get("detail", "")


def test_bulk_accepts_items_format(admin_tok, unique_sn):
    """Formato preferido: items=[{sn, mac?}]."""
    r = requests.post(
        f"{API}/stok/onts/bulk",
        json={"model": "ZTE F670L",
                "items": [{"sn": unique_sn},
                            {"sn": f"{unique_sn}B",
                              "mac": "48:F1:AB:2C:4E:99"}]},
        headers=_hdr(admin_tok), timeout=20,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inserted"] == 2
    assert unique_sn in body["sns"]
    assert f"{unique_sn}B" in body["sns"]


def test_bulk_legacy_macs_treats_as_sn(admin_tok):
    """Formato legado: macs=[str] — cada string tratada como SN."""
    sn = f"LEGACY{uuid.uuid4().hex[:8].upper()}"
    r = requests.post(
        f"{API}/stok/onts/bulk",
        json={"model": "Huawei HG", "macs": [sn]},
        headers=_hdr(admin_tok), timeout=20,
    )
    assert r.status_code == 200, r.text
    assert sn in r.json()["sns"]


def test_bulk_rejects_duplicate_sn(admin_tok, unique_sn):
    """SN já cadastrado → 400."""
    r = requests.post(
        f"{API}/stok/onts/bulk",
        json={"model": "X", "items": [{"sn": unique_sn}]},
        headers=_hdr(admin_tok), timeout=20,
    )
    assert r.status_code == 400, r.text
    assert "já cadastrado" in r.json()["detail"]


def test_traceability_finds_by_sn(admin_tok, unique_sn):
    """GET /onts/traceability/{sn} encontra a ONT cadastrada acima."""
    r = requests.get(f"{API}/stok/onts/traceability/{unique_sn}",
                      headers=_hdr(admin_tok), timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ont"]["sn"] == unique_sn
    assert body["found_by"] == "sn"
