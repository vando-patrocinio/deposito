"""CTO 13/06/2026: Regression test for clock_in_enabled preservation.

Bug: PUT /collaborators/{id} sem o campo `clock_in_enabled` no payload estava
sobrescrevendo o valor para True (default do CollaboratorIn). Isso fazia o
toggle "Bate ponto: OFF" virar ON silenciosamente sempre que o gestor editava
nome/cargo do colaborador.

Fix: CollaboratorIn.clock_in_enabled = Optional[bool] = None + lógica de
preservação no PUT (lê prev_val do Mongo se data["clock_in_enabled"] is None).
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://dual-combine-3.preview.emergentagent.com",
).rstrip("/")
ADMIN = {"email": "admin@empresa.com", "password": "123456"}


@pytest.fixture(scope="module")
def admin_headers():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=20)
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token") or r.json().get("token")
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture()
def collab_off(admin_headers):
    """Cria colaborador com clock_in_enabled=False."""
    suffix = uuid.uuid4().hex[:6]
    payload = {
        "name": f"TEST_preserve_{suffix}",
        "cpf": f"888{suffix.zfill(8)[:8]}",
        "email": f"test_preserve_{suffix}@example.com",
        "phone": "11999990000",
        "role": "Colaborador de Campo",
        "cargo": "tecnico",
        "company": "Operação SP",
        "clock_in_enabled": False,
    }
    r = requests.post(
        f"{BASE_URL}/api/collaborators", json=payload,
        headers=admin_headers, timeout=20,
    )
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert r.json().get("clock_in_enabled") is False, (
        f"POST não respeitou clock_in_enabled=False: {r.json()}"
    )
    yield cid
    requests.delete(
        f"{BASE_URL}/api/collaborators/{cid}",
        headers=admin_headers, timeout=20,
    )


def test_put_without_clock_in_enabled_preserves_false(collab_off, admin_headers):
    """PUT sem o campo clock_in_enabled NÃO pode mudar False -> True."""
    # PUT só com nome diferente — SEM clock_in_enabled no payload
    body = {
        "name": "TEST_preserve_renamed",
        "cpf": "88899988866",
        "email": "test_preserve_renamed@example.com",
        "phone": "11888880000",
        "role": "Colaborador de Campo",
        "cargo": "tecnico",
        "company": "Operação SP",
        # ⚠️ clock_in_enabled OMITIDO — deve preservar False
    }
    r = requests.put(
        f"{BASE_URL}/api/collaborators/{collab_off}", json=body,
        headers=admin_headers, timeout=20,
    )
    assert r.status_code == 200, r.text

    # Confirma no GET que continua False
    r2 = requests.get(
        f"{BASE_URL}/api/collaborators/{collab_off}",
        headers=admin_headers, timeout=20,
    )
    assert r2.status_code == 200
    assert r2.json().get("clock_in_enabled") is False, (
        f"REGRESSION: PUT parcial sobrescreveu clock_in_enabled "
        f"de False para {r2.json().get('clock_in_enabled')}. "
        f"Resp: {r2.json()}"
    )


def test_put_explicit_true_still_works(collab_off, admin_headers):
    """PUT com clock_in_enabled=True explicito deve ligar (não regrediu o caminho normal)."""
    body = {
        "name": "TEST_preserve_on",
        "cpf": "88899988866",
        "email": "test_preserve_on@example.com",
        "phone": "11888880000",
        "role": "Colaborador de Campo",
        "cargo": "tecnico",
        "company": "Operação SP",
        "clock_in_enabled": True,
    }
    r = requests.put(
        f"{BASE_URL}/api/collaborators/{collab_off}", json=body,
        headers=admin_headers, timeout=20,
    )
    assert r.status_code == 200, r.text
    assert r.json().get("clock_in_enabled") is True


def test_put_explicit_false_still_works(admin_headers):
    """PUT com clock_in_enabled=False explicito (depois de ON) deve desligar."""
    suffix = uuid.uuid4().hex[:6]
    payload = {
        "name": f"TEST_offflow_{suffix}",
        "cpf": f"777{suffix.zfill(8)[:8]}",
        "email": f"test_offflow_{suffix}@example.com",
        "phone": "11999990000",
        "role": "Colaborador de Campo",
        "cargo": "tecnico",
        "company": "Operação SP",
        "clock_in_enabled": True,
    }
    r = requests.post(
        f"{BASE_URL}/api/collaborators", json=payload,
        headers=admin_headers, timeout=20,
    )
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    try:
        body = {**payload, "clock_in_enabled": False}
        r2 = requests.put(
            f"{BASE_URL}/api/collaborators/{cid}", json=body,
            headers=admin_headers, timeout=20,
        )
        assert r2.status_code == 200, r2.text
        assert r2.json().get("clock_in_enabled") is False
    finally:
        requests.delete(
            f"{BASE_URL}/api/collaborators/{cid}",
            headers=admin_headers, timeout=20,
        )


def test_create_with_associado_defaults_to_false(admin_headers):
    """POST sem clock_in_enabled + cargo=associado → deve ficar False (regra cargo)."""
    suffix = uuid.uuid4().hex[:6]
    payload = {
        "name": f"TEST_assoc_{suffix}",
        "cpf": f"666{suffix.zfill(8)[:8]}",
        "email": f"test_assoc_{suffix}@example.com",
        "phone": "11999990000",
        "role": "Colaborador de Campo",
        "cargo": "associado",
        "company": "Operação SP",
        # SEM clock_in_enabled
    }
    r = requests.post(
        f"{BASE_URL}/api/collaborators", json=payload,
        headers=admin_headers, timeout=20,
    )
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    try:
        # Associado não bate ponto por regra de cargo
        assert r.json().get("clock_in_enabled") is False, (
            f"associado defaultou para {r.json().get('clock_in_enabled')}"
        )
    finally:
        requests.delete(
            f"{BASE_URL}/api/collaborators/{cid}",
            headers=admin_headers, timeout=20,
        )


def test_create_with_tecnico_defaults_to_true(admin_headers):
    """POST sem clock_in_enabled + cargo=tecnico → deve ficar True (CLT)."""
    suffix = uuid.uuid4().hex[:6]
    payload = {
        "name": f"TEST_tec_{suffix}",
        "cpf": f"555{suffix.zfill(8)[:8]}",
        "email": f"test_tec_{suffix}@example.com",
        "phone": "11999990000",
        "role": "Colaborador de Campo",
        "cargo": "tecnico",
        "company": "Operação SP",
        # SEM clock_in_enabled
    }
    r = requests.post(
        f"{BASE_URL}/api/collaborators", json=payload,
        headers=admin_headers, timeout=20,
    )
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    try:
        assert r.json().get("clock_in_enabled") is True, (
            f"tecnico defaultou para {r.json().get('clock_in_enabled')}"
        )
    finally:
        requests.delete(
            f"{BASE_URL}/api/collaborators/{cid}",
            headers=admin_headers, timeout=20,
        )
