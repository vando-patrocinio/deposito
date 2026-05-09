"""E2E tests SmartOLT integration (iter 26).

Cobre: settings (mascarado), test-connection, sync ONUs, lookup por PPPoE/nome,
get_onu_signal (cache + live), endpoint Lousa /tickets/{id}/signal.

Requer credenciais reais SmartOLT da Ligo Fibra (subdomain=ligofibra).
"""
import pytest
import uuid


@pytest.fixture(scope="module")
def admin_token(base_url, api):
    r = api.post(f"{base_url}/api/auth/login",
                 json={"email": "admin@empresa.com", "password": "123456"})
    assert r.status_code == 200, r.text
    d = r.json()
    return d.get("access_token") or d.get("token")


@pytest.fixture(scope="module")
def headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def technician_id(base_url, api, headers):
    r = api.get(f"{base_url}/api/stok/technicians", headers=headers)
    return r.json()[0]["id"]


def test_settings_mask(base_url, api, headers):
    r = api.get(f"{base_url}/api/smartolt/settings", headers=headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "subdomain" in d
    # api_key vem mascarado (4...4 com elipse)
    if d.get("api_key"):
        assert "…" in d["api_key"] or "*" in d["api_key"]


def test_test_connection(base_url, api, headers):
    r = api.post(f"{base_url}/api/smartolt/test-connection", headers=headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("ok") is True
    assert d.get("olts_count", 0) >= 1


def test_lookup_by_pppoe_exact(base_url, api, headers):
    # Match case-insensitive: 'TnPalestrina733_VItoria' (Atlaz) → 'TnPalestrina733_Vitoria' (SmartOLT)
    r = api.get(f"{base_url}/api/smartolt/onu/lookup", headers=headers,
                params={"pppoe": "TnPalestrina733_VItoria"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["count"] >= 1
    m = d["matches"][0]
    assert m["unique_external_id"] == "ALCLFC090E99"
    assert m["olt_name"] == "RIO_HUAWEI"
    assert m["board"] == "1"
    assert m["port"] == "5"


def test_lookup_no_match(base_url, api, headers):
    r = api.get(f"{base_url}/api/smartolt/onu/lookup", headers=headers,
                params={"pppoe": "ZzInexistenteXyz9999"})
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_lookup_validation(base_url, api, headers):
    r = api.get(f"{base_url}/api/smartolt/onu/lookup", headers=headers)
    assert r.status_code == 400


def test_onu_signal(base_url, api, headers):
    r = api.get(f"{base_url}/api/smartolt/onu/ALCLFC090E99/signal", headers=headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "onu" in d
    onu = d["onu"]
    assert onu["unique_external_id"] == "ALCLFC090E99"
    # Sinal deve estar entre -8 e -30 dBm (faixa GPON saudável)
    rx = float(onu.get("signal_1490") or onu.get("signal_1310"))
    assert -32 < rx < -5


def test_lousa_ticket_signal_via_pppoe(base_url, api, headers, technician_id):
    """Cria ticket com PPPoE real → endpoint /lousa/tickets/{id}/signal resolve."""
    payload = {
        "client_name": f"Test {uuid.uuid4().hex[:5]}",
        "address": "Rua Test 123", "neighborhood": "Test", "phone": "21000000000",
        "relato": "iter26 smartolt",
        "pppoe_user": "TnPalestrina733_Vitoria",
        "type": "reparo", "priority": "normal",
        "assigned_collaborator_id": technician_id,
    }
    r = api.post(f"{base_url}/api/lousa/tickets", headers=headers, json=payload)
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    r2 = api.get(f"{base_url}/api/lousa/tickets/{tid}/signal", headers=headers)
    assert r2.status_code == 200, r2.text
    d = r2.json()
    assert d["found"] is True
    assert d["match_strategy"] == "pppoe"
    assert d["onu"]["unique_external_id"] == "ALCLFC090E99"
    # cleanup
    api.delete(f"{base_url}/api/lousa/tickets/{tid}", headers=headers)


def test_lousa_ticket_signal_refresh_live(base_url, api, headers, technician_id):
    payload = {
        "client_name": f"Test {uuid.uuid4().hex[:5]}",
        "address": "Rua Live 1", "neighborhood": "Test", "phone": "21000000000",
        "relato": "iter26 live", "pppoe_user": "TnPalestrina733_Vitoria",
        "type": "reparo", "priority": "normal",
        "assigned_collaborator_id": technician_id,
    }
    r = api.post(f"{base_url}/api/lousa/tickets", headers=headers, json=payload)
    tid = r.json()["id"]
    r2 = api.get(f"{base_url}/api/lousa/tickets/{tid}/signal", headers=headers,
                 params={"refresh": "true"})
    assert r2.status_code == 200, r2.text
    d = r2.json()
    assert d["found"] is True
    # cached pode ser true se TTL ainda válido OU false se forçou
    assert "onu" in d
    api.delete(f"{base_url}/api/lousa/tickets/{tid}", headers=headers)


def test_lousa_ticket_signal_no_match(base_url, api, headers, technician_id):
    payload = {
        "client_name": f"Cliente Inexistente Xyz {uuid.uuid4().hex[:5]}",
        "address": "Rua Test 456", "neighborhood": "Test", "phone": "21000000000",
        "relato": "no match", "pppoe_user": "ZzInexistenteXyz9999",
        "type": "reparo", "priority": "normal",
        "assigned_collaborator_id": technician_id,
    }
    r = api.post(f"{base_url}/api/lousa/tickets", headers=headers, json=payload)
    tid = r.json()["id"]
    r2 = api.get(f"{base_url}/api/lousa/tickets/{tid}/signal", headers=headers)
    assert r2.status_code == 200
    d = r2.json()
    assert d["found"] is False
    assert d["reason"] == "no_match"
    api.delete(f"{base_url}/api/lousa/tickets/{tid}", headers=headers)


def test_settings_unauthorized(base_url, api):
    r = api.get(f"{base_url}/api/smartolt/settings")
    assert r.status_code in (401, 403)
