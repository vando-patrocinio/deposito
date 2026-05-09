"""E2E pytest for /api/stok integration (iter 25).

Cobre: login admin → catálogo/dashboard → cadastro de ONT bulk →
transfer p/ técnico → criar OS → fechar OS com baixa de insumos →
histórico → retorno ONT à empresa.
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
    assert r.status_code == 200
    techs = r.json()
    assert techs, "Pelo menos 1 técnico deve existir"
    return techs[0]["id"]


def _unique_mac(prefix="AA"):
    return f"{prefix}:" + ":".join(uuid.uuid4().hex[:2].upper() for _ in range(5))


def test_catalog(base_url, api, headers):
    r = api.get(f"{base_url}/api/stok/catalog", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert "consumables" in data
    ids = {c["id"] for c in data["consumables"]}
    assert {"drop", "cabo_rede", "conector_fast", "conector_fibra", "esticador", "conector_rede"} <= ids


def test_dashboard(base_url, api, headers):
    r = api.get(f"{base_url}/api/stok/dashboard", headers=headers)
    assert r.status_code == 200
    d = r.json()
    for k in ("company_onts", "total_onts", "active_services_count",
              "technicians_count", "tech_rows", "empresa_stock"):
        assert k in d


def test_onts_bulk_and_transfer(base_url, api, headers, technician_id):
    mac = _unique_mac("BB")
    r = api.post(f"{base_url}/api/stok/onts/bulk", headers=headers,
                 json={"model": "Test ZTE H198A", "macs": [mac]})
    assert r.status_code == 200, r.text
    assert r.json()["inserted"] == 1

    # Bulk dup → 400
    r2 = api.post(f"{base_url}/api/stok/onts/bulk", headers=headers,
                  json={"model": "Test", "macs": [mac]})
    assert r2.status_code == 400

    # Transfer p/ técnico
    r3 = api.post(f"{base_url}/api/stok/onts/transfer-to-tech", headers=headers,
                  json={"mac": mac, "technician_id": technician_id})
    assert r3.status_code == 200, r3.text

    # Devolução à empresa
    r4 = api.post(f"{base_url}/api/stok/onts/{mac}/return-to-company", headers=headers)
    assert r4.status_code == 200, r4.text


def test_consumables_purchase_and_transfer(base_url, api, headers, technician_id):
    # Compra: 1 caixa drop = 1000m
    r = api.post(f"{base_url}/api/stok/consumables/purchase", headers=headers,
                 json={"consumable_id": "drop", "pack_qty": 1})
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 1000

    # Transferir 50m p/ técnico
    r2 = api.post(f"{base_url}/api/stok/consumables/transfer", headers=headers,
                  json={"consumable_id": "drop", "quantity": 50,
                        "technician_id": technician_id})
    assert r2.status_code == 200, r2.text


def test_service_create_and_close_full_flow(base_url, api, headers, technician_id):
    # Setup: cria ONT no estoque empresa, transfere para técnico, e
    # garante saldo de drop no técnico.
    mac = _unique_mac("CC")
    api.post(f"{base_url}/api/stok/onts/bulk", headers=headers,
             json={"model": "ZTE Test", "macs": [mac]})
    api.post(f"{base_url}/api/stok/onts/transfer-to-tech", headers=headers,
             json={"mac": mac, "technician_id": technician_id})
    api.post(f"{base_url}/api/stok/consumables/purchase", headers=headers,
             json={"consumable_id": "drop", "pack_qty": 1})
    api.post(f"{base_url}/api/stok/consumables/transfer", headers=headers,
             json={"consumable_id": "drop", "quantity": 100,
                   "technician_id": technician_id})

    # Cria OS de instalação
    cid = f"client-{uuid.uuid4().hex[:6]}"
    r = api.post(f"{base_url}/api/stok/services", headers=headers,
                 json={"type": "instalacao", "client_id": cid,
                       "client_name": "Cliente Teste 25",
                       "technician_id": technician_id})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    # Fecha OS: instala ONT + baixa 30m de drop
    r2 = api.post(f"{base_url}/api/stok/services/{sid}/close", headers=headers,
                  json={"ont_mac": mac, "tag": "instalacao",
                        "used_items": [{"consumable_id": "drop", "quantity": 30}]})
    assert r2.status_code == 200, r2.text

    # Conferir histórico
    r3 = api.get(f"{base_url}/api/stok/history", headers=headers,
                 params={"q": sid})
    assert r3.status_code == 200
    descs = [h["description"] for h in r3.json()]
    assert any("instalada" in d for d in descs), descs


def test_close_without_active_service_returns_404(base_url, api, headers):
    r = api.post(f"{base_url}/api/stok/services/OS-NONEXIST/close", headers=headers,
                 json={"used_items": []})
    assert r.status_code == 404


def test_unauthorized_without_token(base_url, api):
    r = api.get(f"{base_url}/api/stok/dashboard")
    assert r.status_code in (401, 403)


def test_bridge_lousa_open_creates_service(base_url, api, headers, technician_id):
    """Quando técnico abre uma bolha via /lousa/public/tickets/{id}/open,
    auto_open_service_for_ticket cria OS de estoque automaticamente."""
    import time
    # 1) cria ticket via admin endpoint (bypass GPS)
    payload_t = {
        "type": "instalacao",
        "client_name": "Bridge Test Cliente",
        "address": "Rua X, 1",
        "neighborhood": "Centro",
        "phone": "21999999999",
        "relato": "Teste bridge",
        "assigned_collaborator_id": technician_id,
        "scheduled_time": time.strftime("%Y-%m-%dT08:00:00"),
        "priority": "normal",
    }
    r = api.post(f"{base_url}/api/lousa/tickets", headers=headers, json=payload_t)
    assert r.status_code == 200, r.text
    tid = r.json()["id"]

    # 2) admin-open: gestor abre em nome do colaborador (dispara bridge)
    r2 = api.post(f"{base_url}/api/lousa/tickets/{tid}/admin-open",
                  headers=headers, json={})
    assert r2.status_code == 200, r2.text

    # 3) Verifica que OS foi criada no estoque
    r4 = api.get(f"{base_url}/api/stok/services", headers=headers)
    assert r4.status_code == 200
    services = r4.json()
    bridged = [s for s in services if s.get("ticket_id") == tid]
    assert bridged, f"OS de estoque não foi criada para ticket {tid}"
    assert bridged[0]["auto_opened"] is True
    assert bridged[0]["status"] == "ativo"
    assert bridged[0]["type"] == "instalacao"

    # 4) Cancela o ticket via admin → OS deve ficar cancelado
    rc = api.post(f"{base_url}/api/lousa/tickets/{tid}/admin-close",
                  headers=headers,
                  json={"action": "cancelar", "notes": "Teste cancelar"})
    assert rc.status_code == 200, rc.text
    r5 = api.get(f"{base_url}/api/stok/services", headers=headers)
    bridged_after = [s for s in r5.json() if s.get("ticket_id") == tid]
    assert bridged_after[0]["status"] == "cancelado", bridged_after[0]
