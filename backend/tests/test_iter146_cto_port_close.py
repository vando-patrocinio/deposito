"""Iter146 — Lógica de porta de CTO ao fechar OS.

Cobre:
- GET /api/stok/services/{sid}/client-cto-port (current_port + free_ports_same_cto)
- POST /api/stok/services/{sid}/close — retirada → libera porta automaticamente
- POST close — manutencao + port_swap=true → ocupa nova + libera antiga
- POST close — port_swap=true sem new_port_number → 400
- POST close — new_port_number == current → 400
- POST close — porta destino ocupada por OUTRO cliente → 409
- POST close — manutencao + cliente já tem porta + port_swap=false → não altera
- POST close — instalacao + cliente SEM porta + cto_id/cto_port_number → ocupa
- Regressão: payload antigo sem novos campos não quebra
"""
import os
import uuid
import asyncio
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME", "ponto")

CID = "co-demo"
TECH_ID = "col-30aafc3c"  # Diogo


def _login():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                       json={"email": "gestor@empresa.com", "password": "123456"},
                       timeout=15)
    assert r.status_code == 200, f"Login falhou: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def headers():
    return _login()


@pytest.fixture(scope="module")
def loop():
    l = asyncio.new_event_loop()
    yield l
    l.close()


@pytest.fixture(scope="module")
def mdb(loop):
    cli = AsyncIOMotorClient(MONGO_URL)
    return cli[DB_NAME]


@pytest.fixture
def ctx(headers, loop, mdb):
    """Cria CTO com porta ocupada pelo cliente test + 3 portas livres + service."""
    client_id = f"TEST_cli_{uuid.uuid4().hex[:8]}"
    client_name = "TEST Cliente Porta"
    cto_id = f"TEST_cto_{uuid.uuid4().hex[:8]}"
    cto_name = "TEST CTO-A"
    other_client = f"TEST_other_{uuid.uuid4().hex[:6]}"

    async def setup():
        await mdb.ctos.insert_one({
            "id": cto_id, "company_id": CID, "name": cto_name, "vlan": 100,
            "ports": [
                {"number": 1, "status": "free"},
                {"number": 2, "status": "free"},
                {"number": 3, "status": "used",
                 "client_subscriber_id": other_client,
                 "client_name": "TEST Outro"},
                {"number": 5, "status": "used",
                 "client_subscriber_id": client_id,
                 "client_name": client_name,
                 "client_pppoe": "pppoe_x"},
                {"number": 7, "status": "free"},
            ],
        })

    loop.run_until_complete(setup())

    # Cria OS via API (tipo manutencao não existe na enum atual; usa 'reparo')
    def mk_service(stype):
        r = requests.post(f"{BASE_URL}/api/stok/services", headers=headers,
                           json={"type": stype, "client_id": client_id,
                                  "client_name": client_name,
                                  "technician_id": TECH_ID}, timeout=15)
        assert r.status_code == 200, f"create svc {stype}: {r.status_code} {r.text}"
        return r.json()["id"]

    state = {"client_id": client_id, "cto_id": cto_id, "other_client": other_client,
             "mk_service": mk_service}
    yield state

    async def teardown():
        await mdb.ctos.delete_one({"id": cto_id})
        await mdb.stok_services.delete_many({"client_id": client_id})
    loop.run_until_complete(teardown())


# 1) GET client-cto-port: cliente COM porta
def test_get_client_cto_port_with_port(headers, ctx):
    sid = ctx["mk_service"]("reparo")
    r = requests.get(f"{BASE_URL}/api/stok/services/{sid}/client-cto-port",
                       headers=headers, timeout=10)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["current_port"] is not None
    assert d["current_port"]["cto_id"] == ctx["cto_id"]
    assert d["current_port"]["port_number"] == 5
    free_nums = sorted(p["number"] for p in d["free_ports_same_cto"])
    assert free_nums == [1, 2, 7]


# 2) GET client-cto-port: cliente SEM porta
def test_get_client_cto_port_no_port(headers, mdb, loop):
    cid_test = f"TEST_nop_{uuid.uuid4().hex[:6]}"
    r = requests.post(f"{BASE_URL}/api/stok/services", headers=headers,
                       json={"type": "instalacao", "client_id": cid_test,
                              "client_name": "TEST Sem Porta",
                              "technician_id": TECH_ID}, timeout=15)
    assert r.status_code == 200
    sid = r.json()["id"]
    rr = requests.get(f"{BASE_URL}/api/stok/services/{sid}/client-cto-port",
                       headers=headers, timeout=10)
    assert rr.status_code == 200
    d = rr.json()
    assert d["current_port"] is None
    assert d["free_ports_same_cto"] == []
    loop.run_until_complete(mdb.stok_services.delete_one({"id": sid}))


# 3) Close retirada → libera porta automaticamente
def test_close_retirada_libera_porta(headers, ctx, loop, mdb):
    sid = ctx["mk_service"]("retirada")
    # Para retirada precisa de ont_mac, mas vamos mockar: insere ONT no cliente
    mac = f"AA:BB:CC:{uuid.uuid4().hex[:6].upper()}"
    loop.run_until_complete(mdb.stok_onts.insert_one({
        "company_id": CID, "mac": mac, "model": "TEST",
        "location_type": "cliente", "location_id": ctx["client_id"],
        "status": "instalada",
    }))
    r = requests.post(f"{BASE_URL}/api/stok/services/{sid}/close",
                       headers=headers,
                       json={"ont_mac": mac, "used_items": [], "tag": "retirada"},
                       timeout=20)
    assert r.status_code == 200, r.text
    # Verifica porta liberada
    cto = loop.run_until_complete(mdb.ctos.find_one({"id": ctx["cto_id"]}, {"_id": 0}))
    p5 = next(p for p in cto["ports"] if p["number"] == 5)
    assert p5["status"] == "free"
    assert p5.get("client_subscriber_id") is None
    assert p5.get("release_reason") == "retirada"
    assert p5.get("released_by_email")
    loop.run_until_complete(mdb.stok_onts.delete_one({"mac": mac}))


# 4) Close manutencao/reparo + port_swap → ocupa nova, libera antiga
def test_close_port_swap(headers, ctx, loop, mdb):
    sid = ctx["mk_service"]("reparo")
    # 'reparo' não cai no ramo CTO (ver _handle_cto_port_on_close).
    # Vamos forçar usando type='troca' (que cai no branch).
    loop.run_until_complete(mdb.stok_services.update_one(
        {"id": sid}, {"$set": {"type": "troca"}}))
    # Mas troca exige ont_mac... insere ONT no técnico
    mac = f"DD:EE:FF:{uuid.uuid4().hex[:6].upper()}"
    loop.run_until_complete(mdb.stok_onts.insert_one({
        "company_id": CID, "mac": mac, "model": "TEST",
        "location_type": "tecnico", "location_id": TECH_ID,
        "status": "com_tecnico",
    }))
    r = requests.post(f"{BASE_URL}/api/stok/services/{sid}/close",
                       headers=headers,
                       json={"ont_mac": mac, "used_items": [], "tag": "troca",
                              "port_swap": True, "new_port_number": 1},
                       timeout=20)
    assert r.status_code == 200, r.text
    cto = loop.run_until_complete(mdb.ctos.find_one({"id": ctx["cto_id"]}, {"_id": 0}))
    p1 = next(p for p in cto["ports"] if p["number"] == 1)
    p5 = next(p for p in cto["ports"] if p["number"] == 5)
    assert p1["status"] == "used"
    assert p1["client_subscriber_id"] == ctx["client_id"]
    assert p5["status"] == "free"
    assert p5.get("release_reason") == "port_swap"
    loop.run_until_complete(mdb.stok_onts.delete_one({"mac": mac}))


# 5) port_swap=true sem new_port_number → 400
def test_port_swap_missing_new_port(headers, ctx, loop, mdb):
    sid = ctx["mk_service"]("reparo")
    loop.run_until_complete(mdb.stok_services.update_one(
        {"id": sid}, {"$set": {"type": "troca"}}))
    mac = f"11:22:33:{uuid.uuid4().hex[:6].upper()}"
    loop.run_until_complete(mdb.stok_onts.insert_one({
        "company_id": CID, "mac": mac, "model": "T",
        "location_type": "tecnico", "location_id": TECH_ID, "status": "com_tecnico",
    }))
    r = requests.post(f"{BASE_URL}/api/stok/services/{sid}/close",
                       headers=headers,
                       json={"ont_mac": mac, "used_items": [], "tag": "troca",
                              "port_swap": True}, timeout=20)
    assert r.status_code == 400
    loop.run_until_complete(mdb.stok_onts.delete_one({"mac": mac}))


# 6) new_port == current → 400
def test_port_swap_same_port(headers, ctx, loop, mdb):
    sid = ctx["mk_service"]("reparo")
    loop.run_until_complete(mdb.stok_services.update_one(
        {"id": sid}, {"$set": {"type": "troca"}}))
    mac = f"22:33:44:{uuid.uuid4().hex[:6].upper()}"
    loop.run_until_complete(mdb.stok_onts.insert_one({
        "company_id": CID, "mac": mac, "model": "T",
        "location_type": "tecnico", "location_id": TECH_ID, "status": "com_tecnico",
    }))
    r = requests.post(f"{BASE_URL}/api/stok/services/{sid}/close",
                       headers=headers,
                       json={"ont_mac": mac, "used_items": [], "tag": "troca",
                              "port_swap": True, "new_port_number": 5}, timeout=20)
    assert r.status_code == 400
    loop.run_until_complete(mdb.stok_onts.delete_one({"mac": mac}))


# 7) Porta destino ocupada por OUTRO cliente → 409
def test_port_swap_occupied(headers, ctx, loop, mdb):
    sid = ctx["mk_service"]("reparo")
    loop.run_until_complete(mdb.stok_services.update_one(
        {"id": sid}, {"$set": {"type": "troca"}}))
    mac = f"33:44:55:{uuid.uuid4().hex[:6].upper()}"
    loop.run_until_complete(mdb.stok_onts.insert_one({
        "company_id": CID, "mac": mac, "model": "T",
        "location_type": "tecnico", "location_id": TECH_ID, "status": "com_tecnico",
    }))
    r = requests.post(f"{BASE_URL}/api/stok/services/{sid}/close",
                       headers=headers,
                       json={"ont_mac": mac, "used_items": [], "tag": "troca",
                              "port_swap": True, "new_port_number": 3},
                       timeout=20)
    assert r.status_code == 409
    loop.run_until_complete(mdb.stok_onts.delete_one({"mac": mac}))


# 8) Regressão: payload antigo (sem novos campos) — não quebra
def test_close_regression_legacy_payload(headers, ctx, loop, mdb):
    sid = ctx["mk_service"]("reparo")
    # reparo: não toca em CTO/MAC, só estoque (lista vazia ok)
    r = requests.post(f"{BASE_URL}/api/stok/services/{sid}/close",
                       headers=headers,
                       json={"ont_mac": None, "used_items": [], "tag": "reparo"},
                       timeout=20)
    assert r.status_code == 200, r.text
    cto = loop.run_until_complete(mdb.ctos.find_one({"id": ctx["cto_id"]}))
    p5 = next(p for p in cto["ports"] if p["number"] == 5)
    assert p5["status"] == "used"  # inalterada


# 9) instalacao + cliente SEM porta + cto_id/cto_port_number → ocupa
def test_close_install_occupies_port(headers, ctx, loop, mdb):
    cid_test = f"TEST_inst_{uuid.uuid4().hex[:6]}"
    r = requests.post(f"{BASE_URL}/api/stok/services", headers=headers,
                       json={"type": "instalacao", "client_id": cid_test,
                              "client_name": "TEST Install",
                              "technician_id": TECH_ID}, timeout=15)
    sid = r.json()["id"]
    mac = f"44:55:66:{uuid.uuid4().hex[:6].upper()}"
    loop.run_until_complete(mdb.stok_onts.insert_one({
        "company_id": CID, "mac": mac, "model": "T",
        "location_type": "tecnico", "location_id": TECH_ID, "status": "com_tecnico",
    }))
    rr = requests.post(f"{BASE_URL}/api/stok/services/{sid}/close",
                        headers=headers,
                        json={"ont_mac": mac, "used_items": [], "tag": "instalacao",
                               "cto_id": ctx["cto_id"], "cto_port_number": 7},
                        timeout=20)
    assert rr.status_code == 200, rr.text
    cto = loop.run_until_complete(mdb.ctos.find_one({"id": ctx["cto_id"]}))
    p7 = next(p for p in cto["ports"] if p["number"] == 7)
    assert p7["status"] == "used"
    assert p7["client_subscriber_id"] == cid_test
    loop.run_until_complete(mdb.stok_onts.delete_one({"mac": mac}))
    loop.run_until_complete(mdb.stok_services.delete_one({"id": sid}))
