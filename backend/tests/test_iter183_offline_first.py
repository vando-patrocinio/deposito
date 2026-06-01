"""iter183 — Offline-First backend coverage.

Validates the public CTO creation endpoint used by the technician PWA outbox.
Also verifies the listing endpoint used to seed the technician home.
"""
import os
import time
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
COLLAB = "col-30aafc3c"


@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ------------------- listing endpoint used in PWA -------------------
def test_public_list_ctos_returns_items(http):
    r = http.get(f"{BASE_URL}/api/rede-ia/public/ctos/list/{COLLAB}", timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    assert isinstance(items, list)
    assert len(items) > 0


# ------------------- create endpoint — invalid payloads -------------------
def test_public_create_cto_invalid_sigla(http):
    payload = {
        "sigla": "ZZ_NOT_EXIST",
        "capacity": 8,
        "network_type": "balanceada",
        "element_type": "cto",
        "gps_lat": -3.71,
        "gps_lon": -38.54,
        "endereco": "Rua TESTE_OFFLINE",
        "rua": "Rua TESTE_OFFLINE",
        "numero": "100",
        "bairro": "Brás",
        "cidade": "São Paulo",
        "estado": "SP",
        "vlan": 301,
        "suggested_name": "CTO_301_99001",
        "cto_number": 99001,
    }
    r = http.post(f"{BASE_URL}/api/rede-ia/public/ctos/{COLLAB}", json=payload, timeout=15)
    assert r.status_code == 400
    assert "não cadastrado" in r.text.lower() or "nao cadastrado" in r.text.lower() or "ZZ" in r.text.upper()


def test_public_create_cto_invalid_collab(http):
    payload = {
        "sigla": "BRA",
        "capacity": 8,
        "network_type": "balanceada",
        "element_type": "cto",
        "gps_lat": -3.71,
        "gps_lon": -38.54,
        "endereco": "Rua TESTE_OFFLINE",
        "rua": "Rua TESTE_OFFLINE",
        "numero": "100",
        "bairro": "Brás",
        "cidade": "São Paulo",
        "estado": "SP",
        "vlan": 301,
        "suggested_name": "CTO_301_99002",
        "cto_number": 99002,
    }
    r = http.post(f"{BASE_URL}/api/rede-ia/public/ctos/col-does-not-exist", json=payload, timeout=15)
    assert r.status_code == 404


def test_public_create_cto_invalid_capacity(http):
    payload = {
        "sigla": "BRA",
        "capacity": 7,  # invalid (only 4/8/16)
        "network_type": "balanceada",
        "element_type": "cto",
        "gps_lat": -3.71,
        "gps_lon": -38.54,
        "endereco": "Rua TESTE_OFFLINE",
        "rua": "Rua TESTE_OFFLINE",
        "numero": "100",
        "bairro": "Brás",
        "cidade": "São Paulo",
        "estado": "SP",
        "vlan": 301,
        "suggested_name": "CTO_301_99003",
        "cto_number": 99003,
    }
    r = http.post(f"{BASE_URL}/api/rede-ia/public/ctos/{COLLAB}", json=payload, timeout=15)
    assert r.status_code == 400
    assert "capacidade" in r.text.lower() or "4, 8" in r.text


# ------------------- create endpoint — happy path + persistence -------------------
def test_public_create_cto_happy_path_and_persistence(http):
    # Use a high random number to avoid 409 collisions
    num = 90000 + (int(time.time()) % 9999)
    payload = {
        "sigla": "BRA",
        "capacity": 8,
        "network_type": "balanceada",
        "element_type": "cto",
        "gps_lat": -3.7100,
        "gps_lon": -38.5400,
        "endereco": "Rua TESTE_OFFLINE 100",
        "rua": "Rua TESTE_OFFLINE",
        "numero": "100",
        "bairro": "Brás",
        "cidade": "São Paulo",
        "estado": "SP",
        "vlan": 301,
        "suggested_name": f"CTO_301_{num:05d}",
        "cto_number": num,
        "name": f"TESTE_OFFLINE_{uuid.uuid4().hex[:6]}",
    }
    r = http.post(f"{BASE_URL}/api/rede-ia/public/ctos/{COLLAB}", json=payload, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("id"), f"No id in response: {data}"
    cto_id = data["id"]

    # Verify it appears in the list endpoint
    r2 = http.get(f"{BASE_URL}/api/rede-ia/public/ctos/list/{COLLAB}", timeout=15)
    assert r2.status_code == 200
    items = r2.json().get("items", []) if isinstance(r2.json(), dict) else r2.json()
    ids = [i.get("id") for i in items]
    assert cto_id in ids, f"Created CTO {cto_id} not found in list"

    # Cleanup
    try:
        import asyncio
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        from motor.motor_asyncio import AsyncIOMotorClient
        async def _cleanup():
            cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
            d = cli[os.environ["DB_NAME"]]
            await d.ctos.delete_one({"id": cto_id})
            await d.cto_ports.delete_many({"cto_id": cto_id})
        asyncio.run(_cleanup())
    except Exception as e:
        print(f"cleanup warning: {e}")
