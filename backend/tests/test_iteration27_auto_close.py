"""E2E pytest: ciclo completo Lousa→Estoque com auto-baixa (iter 27).

Valida que ao finalizar a bolha (PublicFinalizeIn com completion_data),
a OS de estoque é auto-fechada e materiais são baixados do técnico.
"""
import uuid
import pytest


@pytest.fixture(scope="module")
def admin_token(base_url, api):
    r = api.post(f"{base_url}/api/auth/login",
                 json={"email": "admin@empresa.com", "password": "123456"})
    assert r.status_code == 200, r.text
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def technician_id(base_url, api, headers):
    r = api.get(f"{base_url}/api/stok/technicians", headers=headers)
    return r.json()[0]["id"]


def _setup_stock(base_url, api, headers, technician_id):
    """Cadastra ONT no técnico + insumos suficientes pra fechar OS de instalação."""
    mac = f"AA:BB:CC:{uuid.uuid4().hex[:2].upper()}:{uuid.uuid4().hex[:2].upper()}:{uuid.uuid4().hex[:2].upper()}"
    api.post(f"{base_url}/api/stok/onts/bulk", headers=headers,
             json={"model": "ZTE Auto-Close Test", "macs": [mac]})
    api.post(f"{base_url}/api/stok/onts/transfer-to-tech", headers=headers,
             json={"mac": mac, "technician_id": technician_id})
    # Compra e transfere insumos generosamente
    api.post(f"{base_url}/api/stok/consumables/purchase", headers=headers,
             json={"consumable_id": "drop", "pack_qty": 1})
    api.post(f"{base_url}/api/stok/consumables/transfer", headers=headers,
             json={"consumable_id": "drop", "quantity": 200, "technician_id": technician_id})
    for cons in ("conector_fast", "esticador", "conector_rede"):
        # Compra 100 unidades (pack_qty=1 pra estes) e transfere 25 pro técnico
        api.post(f"{base_url}/api/stok/consumables/purchase", headers=headers,
                 json={"consumable_id": cons, "pack_qty": 100})
        api.post(f"{base_url}/api/stok/consumables/transfer", headers=headers,
                 json={"consumable_id": cons, "quantity": 25, "technician_id": technician_id})
    return mac


def _stock_qty(base_url, api, headers, technician_id, consumable_id):
    r = api.get(f"{base_url}/api/stok/stock", headers=headers)
    return r.json().get(technician_id, {}).get(consumable_id, 0)


def test_finalize_auto_closes_service_and_decrements_stock(
    base_url, api, headers, technician_id,
):
    mac = _setup_stock(base_url, api, headers, technician_id)
    drop_before = _stock_qty(base_url, api, headers, technician_id, "drop")
    fast_before = _stock_qty(base_url, api, headers, technician_id, "conector_fast")

    # Cria bolha de instalação
    rb = api.post(f"{base_url}/api/lousa/tickets", headers=headers, json={
        "client_name": f"AutoClose {uuid.uuid4().hex[:5]}",
        "address": "Rua AC 1", "neighborhood": "Test", "phone": "21000",
        "relato": "iter27 auto-baixa", "type": "instalacao", "priority": "normal",
        "assigned_collaborator_id": technician_id,
    })
    assert rb.status_code == 200, rb.text
    tid = rb.json()["id"]

    # admin-open dispara auto_open_service_for_ticket → cria OS ativa
    ro = api.post(f"{base_url}/api/lousa/tickets/{tid}/admin-open", headers=headers, json={})
    assert ro.status_code == 200, ro.text

    services = api.get(f"{base_url}/api/stok/services", headers=headers).json()
    bridged = [s for s in services if s.get("ticket_id") == tid]
    assert bridged and bridged[0]["status"] == "ativo"

    # Finalize via public endpoint COM completion_data preenchido
    rf = api.post(
        f"{base_url}/api/lousa/public/tickets/{tid}/finalize",
        json={
            "collaborator_id": technician_id,
            "latitude": -22.9, "longitude": -43.2,
            "completion_data": {
                "sinal": -19.5, "qtd_drop": 30,
                "esticadores": 2, "conectores_fast": 4,
                "cabo_rede": 0, "conectores_rede": 1,
                "ont": mac,
                "fotos": ["data:image/jpeg;base64,xxx", "img2", "img3"],
            },
        },
    )
    assert rf.status_code == 200, rf.text

    # OS deve estar fechada com auto_closed=true
    services = api.get(f"{base_url}/api/stok/services", headers=headers).json()
    bridged = [s for s in services if s.get("ticket_id") == tid]
    assert bridged, "OS sumiu"
    s = bridged[0]
    assert s["status"] == "fechado", f"esperado fechado, veio {s['status']}: {s.get('error_reason')}"
    assert s.get("auto_closed") is True
    assert s.get("auto_closed_ont_mac") == mac
    used = {ui["consumable_id"]: ui["quantity"] for ui in s.get("auto_closed_used_items") or []}
    assert used.get("drop") == 30
    assert used.get("esticador") == 2
    assert used.get("conector_fast") == 4
    assert used.get("conector_rede") == 1

    # Estoque do técnico decrementado
    drop_after = _stock_qty(base_url, api, headers, technician_id, "drop")
    fast_after = _stock_qty(base_url, api, headers, technician_id, "conector_fast")
    assert drop_after == drop_before - 30, f"drop {drop_before}→{drop_after}"
    assert fast_after == fast_before - 4, f"fast {fast_before}→{fast_after}"

    # ONT migrou para o cliente
    onts = api.get(f"{base_url}/api/stok/onts", headers=headers).json()
    target = next((o for o in onts if o["mac"] == mac), None)
    assert target and target["location_type"] == "cliente"
    assert target["status"] == "instalada"

    # Histórico tem entrada `auto_finalize_lousa`
    hist = api.get(f"{base_url}/api/stok/history", headers=headers,
                   params={"tag": "auto_finalize_lousa", "limit": 50}).json()
    assert any(s["id"] in h.get("description", "") for h in hist), \
        f"sem histórico auto_finalize_lousa para {s['id']}"


def test_finalize_with_insufficient_stock_marks_error(
    base_url, api, headers, technician_id,
):
    """Se faltar saldo, OS vira `erro_estoque` mas finalize NÃO derruba."""
    # Cria ticket de instalação SEM cadastrar ONT/insumos pro técnico
    rb = api.post(f"{base_url}/api/lousa/tickets", headers=headers, json={
        "client_name": f"NoStock {uuid.uuid4().hex[:5]}",
        "address": "Rua NS 1", "neighborhood": "Test", "phone": "21000",
        "relato": "sem saldo", "type": "instalacao", "priority": "normal",
        "assigned_collaborator_id": technician_id,
    })
    tid = rb.json()["id"]
    api.post(f"{base_url}/api/lousa/tickets/{tid}/admin-open", headers=headers, json={})

    # Finaliza com saldo grande de drop (provavelmente mais que o técnico tem)
    rf = api.post(
        f"{base_url}/api/lousa/public/tickets/{tid}/finalize",
        json={
            "collaborator_id": technician_id,
            "latitude": -22.9, "longitude": -43.2,
            "completion_data": {
                "sinal": -20, "qtd_drop": 999999,
                "esticadores": 0, "conectores_fast": 0,
                "cabo_rede": 0, "conectores_rede": 0,
                "ont": "ZZ:ZZ:ZZ:ZZ:ZZ:ZZ",  # MAC inexistente
                "fotos": ["a", "b", "c"],
            },
        },
    )
    # finalize na Lousa SEMPRE retorna 200 (auto-close é best-effort)
    assert rf.status_code == 200

    services = api.get(f"{base_url}/api/stok/services", headers=headers).json()
    bridged = [s for s in services if s.get("ticket_id") == tid]
    s = bridged[0]
    assert s["status"] == "erro_estoque", f"esperado erro_estoque, veio {s['status']}"
    assert s.get("error_reason"), "deveria ter error_reason"
    assert s.get("ticket_finalized") is True
