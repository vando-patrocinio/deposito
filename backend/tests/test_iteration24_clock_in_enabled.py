"""Iter 24: clock_in_enabled toggle on Collaborator + lousa public endpoints."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
ADMIN = {"email": "admin@empresa.com", "password": "123456"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=20)
    assert r.status_code == 200, r.text
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def test_collab(admin_headers):
    suffix = uuid.uuid4().hex[:6]
    payload = {
        "name": f"TEST_iter24_{suffix}",
        "cpf": f"999{suffix.zfill(8)[:8]}",
        "email": f"test_iter24_{suffix}@example.com",
        "phone": "11999990000",
        "role": "Colaborador de Campo",
        "company": "Operação SP",
        "clock_in_enabled": True,
    }
    r = requests.post(f"{BASE_URL}/api/collaborators", json=payload, headers=admin_headers, timeout=20)
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    yield cid
    requests.delete(f"{BASE_URL}/api/collaborators/{cid}", headers=admin_headers, timeout=20)


# 1. POST /collaborators persists clock_in_enabled (default true)
def test_create_collaborator_default_clock_in_enabled(test_collab, admin_headers):
    r = requests.get(f"{BASE_URL}/api/collaborators/{test_collab}", headers=admin_headers, timeout=20)
    assert r.status_code == 200
    assert r.json().get("clock_in_enabled") is True


# 2. PUT collaborator updates clock_in_enabled to False
def test_put_set_clock_in_enabled_false(test_collab, admin_headers):
    body = {
        "name": "TEST_iter24_updated",
        "cpf": "99988877766",
        "email": "test_iter24_upd@example.com",
        "phone": "11888880000",
        "role": "Colaborador de Campo",
        "company": "Operação SP",
        "clock_in_enabled": False,
    }
    r = requests.put(f"{BASE_URL}/api/collaborators/{test_collab}", json=body, headers=admin_headers, timeout=20)
    assert r.status_code == 200, r.text
    assert r.json().get("clock_in_enabled") is False
    # GET verify persistence
    r2 = requests.get(f"{BASE_URL}/api/collaborators/{test_collab}", headers=admin_headers, timeout=20)
    assert r2.json().get("clock_in_enabled") is False


# 3. /lousa/by-collaborator returns lousa_unlocked=true and needs_clock_in=false when disabled
def test_lousa_unlocked_when_clock_disabled(test_collab):
    r = requests.get(f"{BASE_URL}/api/lousa/by-collaborator/{test_collab}", timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("clock_in_enabled") is False
    assert data.get("lousa_unlocked") is True
    assert data.get("needs_clock_in") is False
    assert "tickets" in data


# 4. Toggle back to true: needs_clock_in becomes true (no entrada record)
def test_lousa_locked_when_clock_enabled_no_entrada(test_collab, admin_headers):
    body = {
        "name": "TEST_iter24_re_enabled",
        "cpf": "99988877766",
        "email": "test_iter24_upd@example.com",
        "phone": "11888880000",
        "role": "Colaborador de Campo",
        "company": "Operação SP",
        "clock_in_enabled": True,
    }
    r = requests.put(f"{BASE_URL}/api/collaborators/{test_collab}", json=body, headers=admin_headers, timeout=20)
    assert r.status_code == 200
    r2 = requests.get(f"{BASE_URL}/api/lousa/by-collaborator/{test_collab}", timeout=20)
    assert r2.status_code == 200
    data = r2.json()
    assert data.get("clock_in_enabled") is True
    assert data.get("needs_clock_in") is True
    assert data.get("lousa_unlocked") is False


# 5. public_open_ticket: when clock_in_enabled=False, opens without 412 validation
def test_public_open_ticket_skips_clock_check_when_disabled(test_collab, admin_headers):
    # set clock_in_enabled=false again
    body = {
        "name": "TEST_iter24_open",
        "cpf": "99988877766",
        "email": "test_iter24_upd@example.com",
        "phone": "11888880000",
        "role": "Colaborador de Campo",
        "company": "Operação SP",
        "clock_in_enabled": False,
    }
    requests.put(f"{BASE_URL}/api/collaborators/{test_collab}", json=body, headers=admin_headers, timeout=20)

    # create a ticket assigned to him
    tk = {
        "client_name": "TEST_iter24_client",
        "address": "Rua Teste 123, São Paulo",
        "neighborhood": "Centro",
        "phone": "11999998888",
        "relato": "Teste iter24",
        "type": "reparo",
        "priority": "normal",
        "assigned_collaborator_id": test_collab,
    }
    r_tk = requests.post(f"{BASE_URL}/api/lousa/tickets", json=tk, headers=admin_headers, timeout=30)
    assert r_tk.status_code == 200, r_tk.text
    tid = r_tk.json()["id"]
    try:
        # public open without entrada — should succeed (NOT 412)
        r_open = requests.post(
            f"{BASE_URL}/api/lousa/public/tickets/{tid}/open",
            json={"collaborator_id": test_collab}, timeout=20,
        )
        assert r_open.status_code == 200, f"expected 200 got {r_open.status_code}: {r_open.text}"
        assert r_open.json().get("status") == "aberta"
    finally:
        requests.delete(f"{BASE_URL}/api/lousa/tickets/{tid}", headers=admin_headers, timeout=20)


# 6. Regression: GET /clock-records with collaborator_id+date_from+date_to still works
def test_clock_records_filter_works(test_collab):
    r = requests.get(
        f"{BASE_URL}/api/clock-records",
        params={"collaborator_id": test_collab, "date_from": "2025-01-01", "date_to": "2030-12-31"},
        timeout=20,
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)
