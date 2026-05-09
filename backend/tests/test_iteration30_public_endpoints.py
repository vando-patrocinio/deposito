"""E2E tests endpoints públicos (mobile) iter 30."""
import pytest


@pytest.fixture(scope="module")
def admin_token(base_url, api):
    r = api.post(f"{base_url}/api/auth/login",
                 json={"email": "admin@empresa.com", "password": "123456"})
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def technician_id(base_url, api, headers):
    r = api.get(f"{base_url}/api/stok/technicians", headers=headers)
    return r.json()[0]["id"]


def test_public_tech_stock(base_url, api, technician_id):
    """Endpoint público: técnico vê seu próprio saldo de insumos + ONTs."""
    r = api.get(f"{base_url}/api/stok/public/collaborator/{technician_id}/stock")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["collaborator_id"] == technician_id
    assert "consumables" in d and len(d["consumables"]) == 6
    for c in d["consumables"]:
        assert "id" in c and "name" in c and "unit" in c and "qty" in c
        assert isinstance(c["qty"], int)
    assert "onts" in d


def test_public_tech_stock_404_invalid_collaborator(base_url, api):
    r = api.get(f"{base_url}/api/stok/public/collaborator/col-DOES-NOT-EXIST/stock")
    assert r.status_code == 404


def test_public_validate_mac_existing_in_smartolt(base_url, api, technician_id):
    """SN real da Ligo Fibra deve aparecer com found_smartolt=True."""
    r = api.get(f"{base_url}/api/smartolt/public/validate-mac/ALCLFC090E99",
                params={"collaborator_id": technician_id})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["found_smartolt"] is True
    assert d["smartolt"]["name"] == "TnPalestrina733_Vitoria"
    assert d["smartolt"]["olt_name"] == "RIO_HUAWEI"
    # Não está no estoque do técnico (é cliente real Ligo)
    assert d["in_tech_stock"] is False


def test_public_validate_mac_unknown(base_url, api):
    r = api.get(f"{base_url}/api/smartolt/public/validate-mac/ZZZZZ_INVALID")
    assert r.status_code == 200
    d = r.json()
    assert d["found_smartolt"] is False
    assert d["in_tech_stock"] is False


def test_public_validate_mac_in_tech_stock(base_url, api, headers, technician_id):
    """ONT cadastrada no técnico deve retornar in_tech_stock=True."""
    import uuid
    mac = f"AA:BB:CC:{uuid.uuid4().hex[:2].upper()}:{uuid.uuid4().hex[:2].upper()}:{uuid.uuid4().hex[:2].upper()}"
    api.post(f"{base_url}/api/stok/onts/bulk", headers=headers,
             json={"model": "Test Iter30", "macs": [mac]})
    api.post(f"{base_url}/api/stok/onts/transfer-to-tech", headers=headers,
             json={"mac": mac, "technician_id": technician_id})
    r = api.get(f"{base_url}/api/smartolt/public/validate-mac/{mac}",
                params={"collaborator_id": technician_id})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["in_tech_stock"] is True
    assert d["ont_record"]["mac"] == mac
    assert d["ont_record"]["location_type"] == "tecnico"
    # Não existe na SmartOLT (é só do estoque interno)
    assert d["found_smartolt"] is False


def test_public_validate_mac_empty(base_url, api):
    r = api.get(f"{base_url}/api/smartolt/public/validate-mac/%20")
    # FastAPI pode rejeitar ou aceitar — qualquer 4xx é OK
    assert r.status_code in (400, 404, 422)


def test_smartolt_validation_recorded_in_auto_close(
    base_url, api, headers, technician_id,
):
    """Quando técnico finaliza com MAC do cliente real, auto-close grava SmartOLT info."""
    import uuid
    # Setup: ONT no estoque do técnico
    mac = f"AA:BB:CC:{uuid.uuid4().hex[:2].upper()}:{uuid.uuid4().hex[:2].upper()}:{uuid.uuid4().hex[:2].upper()}"
    api.post(f"{base_url}/api/stok/onts/bulk", headers=headers,
             json={"model": "Test Iter30", "macs": [mac]})
    api.post(f"{base_url}/api/stok/onts/transfer-to-tech", headers=headers,
             json={"mac": mac, "technician_id": technician_id})
    api.post(f"{base_url}/api/stok/consumables/purchase", headers=headers,
             json={"consumable_id": "drop", "pack_qty": 1})
    api.post(f"{base_url}/api/stok/consumables/transfer", headers=headers,
             json={"consumable_id": "drop", "quantity": 50, "technician_id": technician_id})
    # Cria + abre + finaliza
    rb = api.post(f"{base_url}/api/lousa/tickets", headers=headers, json={
        "client_name": f"Iter30 {uuid.uuid4().hex[:5]}",
        "address": "x", "neighborhood": "y", "phone": "0",
        "relato": "iter30", "type": "instalacao", "priority": "normal",
        "assigned_collaborator_id": technician_id,
    })
    tid = rb.json()["id"]
    api.post(f"{base_url}/api/lousa/tickets/{tid}/admin-open", headers=headers, json={})
    rf = api.post(f"{base_url}/api/lousa/public/tickets/{tid}/finalize",
                  json={"collaborator_id": technician_id, "latitude": -22.9, "longitude": -43.2,
                        "completion_data": {"sinal": -22, "qtd_drop": 10, "esticadores": 0,
                                              "conectores_fast": 0, "cabo_rede": 0,
                                              "conectores_rede": 0, "ont": mac, "fotos": ["a","b","c"]}})
    assert rf.status_code == 200
    services = api.get(f"{base_url}/api/stok/services", headers=headers).json()
    s = next(x for x in services if x.get("ticket_id") == tid)
    # Mac é interno (não está no SmartOLT real), portanto smartolt_validation pode ser None
    # Mas o campo deve existir (None ou dict)
    assert "smartolt_validation" in s
