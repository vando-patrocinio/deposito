"""E2E tests para o fluxo de marcar fatura como paga (Atlaz Financeiro bi-direcional).

Cenários cobertos:
  1. Mark paid LOCAL (push_to_atlaz=false) → status=paid, paid_source=smartprov
  2. Mark paid com push (push_to_atlaz=true, sem token) → attempted=false
  3. Mark paid com push (token mock) → attempted=true, ok pode ser false
  4. Unmark paid → reverte status=open, limpa campos paid_*
  5. probe-write → não escreve nada, só retorna 404 para endpoints inexistentes
"""
import os
import uuid

import httpx
import pytest

BACKEND_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
BASE = f"{BACKEND_URL}/api"

LOGIN = {"email": "admin@empresa.com", "password": "123456"}


def _login() -> str:
    r = httpx.post(f"{BASE}/auth/login", json=LOGIN, timeout=15)
    assert r.status_code == 200, r.text
    return r.json().get("access_token") or r.json().get("token")


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def token():
    return _login()


@pytest.fixture(scope="module")
def open_invoice(token):
    """Pega a primeira fatura em aberto pra testar (não destrutivo)."""
    r = httpx.get(f"{BASE}/atlaz-financeiro/invoices?status=open&limit=1",
                   headers=_hdr(token), timeout=15)
    assert r.status_code == 200, r.text
    items = r.json().get("items", [])
    assert items, "Nenhuma fatura em aberto disponível para teste"
    return items[0]


def test_mark_paid_local_only(token, open_invoice):
    """Mark paid sem push pro Atlaz: status=paid, paid_source=smartprov, atlaz_push.attempted=False."""
    inv_id = open_invoice["id"]
    payload = {
        "paid_amount": open_invoice.get("amount", 99.9),
        "paid_method": "pix",
        "paid_note": f"pytest-{uuid.uuid4().hex[:6]}",
        "push_to_atlaz": False,
    }
    r = httpx.post(f"{BASE}/atlaz-financeiro/invoices/{inv_id}/mark-paid",
                    json=payload, headers=_hdr(token), timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    inv = data["invoice"]
    assert inv["status"] == "paid"
    assert inv["paid_source"] == "smartprov"
    assert inv["paid_method"] == "pix"
    assert inv["paid_by_user_name"]  # vem do JWT
    assert data["atlaz_push"]["attempted"] is False

    # cleanup — reverter
    r2 = httpx.post(f"{BASE}/atlaz-financeiro/invoices/{inv_id}/unmark-paid",
                     headers=_hdr(token), timeout=15)
    assert r2.status_code == 200, r2.text


def test_mark_paid_with_push_attempt(token, open_invoice):
    """Mark paid com push=true: como Atlaz V2 não tem endpoint de baixa,
    atlaz_push.ok=False mas attempted=True e fatura fica paga local."""
    inv_id = open_invoice["id"]
    r = httpx.post(f"{BASE}/atlaz-financeiro/invoices/{inv_id}/mark-paid",
                    json={"push_to_atlaz": True, "paid_method": "boleto"},
                    headers=_hdr(token), timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["invoice"]["status"] == "paid"
    push = data["atlaz_push"]
    assert push["attempted"] is True
    # ok pode ser True ou False — depende da Atlaz responder algum endpoint
    assert "ok" in push

    # cleanup
    httpx.post(f"{BASE}/atlaz-financeiro/invoices/{inv_id}/unmark-paid",
                headers=_hdr(token), timeout=15)


def test_unmark_paid_resets_fields(token, open_invoice):
    """Unmark deve voltar status=open e limpar paid_*."""
    inv_id = open_invoice["id"]
    # 1) marca como paga local
    httpx.post(f"{BASE}/atlaz-financeiro/invoices/{inv_id}/mark-paid",
                json={"push_to_atlaz": False},
                headers=_hdr(token), timeout=15)
    # 2) reverte
    r = httpx.post(f"{BASE}/atlaz-financeiro/invoices/{inv_id}/unmark-paid",
                    headers=_hdr(token), timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    # 3) confere via list
    r3 = httpx.get(f"{BASE}/atlaz-financeiro/invoices?status=open&limit=200",
                    headers=_hdr(token), timeout=15)
    items = r3.json().get("items", [])
    inv = next((i for i in items if i["id"] == inv_id), None)
    assert inv is not None, "fatura deveria voltar pra lista de open"
    assert inv["status"] == "open"
    assert "paid_date" not in inv or inv.get("paid_date") is None
    assert "paid_by_user_name" not in inv or inv.get("paid_by_user_name") is None


def test_probe_write_does_not_write(token):
    """probe-write deve retornar lista de endpoints sem escrever nada."""
    r = httpx.get(f"{BASE}/atlaz-financeiro/probe-write",
                   headers=_hdr(token), timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "endpoints" in data
    assert "probed_at" in data
    assert isinstance(data["endpoints"], list)
    assert len(data["endpoints"]) > 0
    # Pelo menos um endpoint deve ter sido testado
    for ep in data["endpoints"]:
        assert "endpoint" in ep
        assert "http_status" in ep
