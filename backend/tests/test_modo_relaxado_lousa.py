"""CTO 13/06/2026 — Regression tests for "Modo Relaxado" UX.

User feedback:
- Img1 (Insumos): aceitar valores negativos no estoque.
- Img2 (Foto): respeitar a opção de foto desligada em Configuração.
- Img3 (Validações): Modo Relaxado deve passar OS sem atrito.

Esses testes garantem que com `cto_photo_required=false`,
`mac_validation_required=false` e estoque insuficiente, a OS de
instalação ainda fecha 200 (sem trava no backend).
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


@pytest.fixture(autouse=True)
def cleanup_open_tickets_col_demo():
    """Antes de cada teste, garante col-demo-001 sem ticket aberto +
    apaga lixo dos testes anteriores."""
    from pymongo import MongoClient
    cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = cli[os.environ.get("DB_NAME", "test_database")]
    db.tickets.delete_many({
        "assigned_collaborator_id": "col-demo-001",
        "client_snapshot.name": {"$regex": "^TEST_"},
    })
    db.tickets.update_many(
        {"assigned_collaborator_id": "col-demo-001", "status": "aberta"},
        {"$set": {"status": "pendente", "opened_at": None}},
    )
    cli.close()
    yield


@pytest.fixture(scope="module")
def collab_headers():
    """Login como colaborador Carlos (col-demo-001) pra usar endpoints
    /lousa/public/* que respeitam role colaborador."""
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "colaborador@empresa.com", "password": "123456"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token") or r.json().get("token")
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_headers():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=20)
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token") or r.json().get("token")
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def relaxed_mode(admin_headers):
    """Coloca a empresa em Modo Relaxado (todos os toggles OFF) e
    restaura no teardown."""
    # snapshot estado anterior
    prev = requests.get(
        f"{BASE_URL}/api/settings/os-validation-toggles",
        headers=admin_headers, timeout=20,
    ).json()
    # aplica Modo Relaxado: todos OFF
    payload = {k: False for k in [
        "ipv6_test_required", "cto_photo_required", "cto_port_required",
        "mac_validation_required", "sn_smartolt_or_photo_required",
    ]}
    r = requests.put(
        f"{BASE_URL}/api/settings/os-validation-toggles", json=payload,
        headers=admin_headers, timeout=20,
    )
    assert r.status_code == 200, r.text
    yield r.json()
    # teardown — restaura
    requests.put(
        f"{BASE_URL}/api/settings/os-validation-toggles", json=prev,
        headers=admin_headers, timeout=20,
    )


def test_settings_endpoint_accepts_all_off(relaxed_mode):
    """Modo Relaxado aplicado deve devolver todas as travas OFF."""
    assert relaxed_mode.get("cto_photo_required") is False
    assert relaxed_mode.get("mac_validation_required") is False
    assert relaxed_mode.get("cto_port_required") is False
    assert relaxed_mode.get("ipv6_test_required") is False


def test_installation_close_without_photos_passes_in_relaxed(
    relaxed_mode, admin_headers, collab_headers,
):
    """Instalação SEM foto + SEM cto_id deve fechar 200 em Modo Relaxado.
    Antes, o handler tinha hardcoded `if instalacao and len(fotos)<1: 400`.
    Agora respeita o toggle cto_photo_required."""
    # Cria ticket de instalação atribuído a col-demo-001
    payload = {
        "client_name": "TEST_relaxado_install",
        "address": "Rua Relaxado 1, SP",
        "neighborhood": "Centro",
        "phone": "11999990000",
        "relato": "Teste Modo Relaxado",
        "type": "instalacao",
        "priority": "normal",
        "assigned_collaborator_id": "col-demo-001",
    }
    r = requests.post(
        f"{BASE_URL}/api/lousa/tickets", json=payload,
        headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    try:
        # Abre via endpoint público (col-demo-001 é o assigned)
        r_open = requests.post(
            f"{BASE_URL}/api/lousa/public/tickets/{tid}/open",
            json={"collaborator_id": "col-demo-001"},
            headers=collab_headers, timeout=20,
        )
        assert r_open.status_code == 200, r_open.text

        # Finaliza: instalação SEM fotos, SEM cto_id, SEM equipamento
        # — todos os toggles OFF, deve passar
        finalize_body = {
            "collaborator_id": "col-demo-001",
            "outcome": "sucesso",
            "latitude": -23.55, "longitude": -46.63,
            "completion_data": {
                "sinal": -22,
                "ont": "TESTONT001",  # ainda obrigatório (regra ortogonal)
                "qtd_drop": 999999,  # estoque negativo proposital
                "esticadores": 999999,
                "conectores_fast": 999999,
                "cabo_rede": 0,
                "conectores_rede": 0,
                "fotos": [],  # SEM FOTOS
                # SEM cto_id, SEM cto_port_number
            },
        }
        r_close = requests.post(
            f"{BASE_URL}/api/lousa/public/tickets/{tid}/finalize",
            json=finalize_body, headers=collab_headers, timeout=30,
        )
        # Aceita: 200 (fechado mesmo sem fotos/cto em Modo Relaxado).
        # Bug original: 400 com "exige pelo menos 1 foto" ou "CTO_PORT_REQUIRED".
        assert r_close.status_code == 200, (
            f"Modo Relaxado falhou pra fechar OS sem foto/cto: "
            f"{r_close.status_code} {r_close.text[:300]}"
        )
    finally:
        requests.delete(
            f"{BASE_URL}/api/lousa/tickets/{tid}",
            headers=admin_headers, timeout=20,
        )


def test_rigorous_mode_still_blocks_without_photo(admin_headers, collab_headers):
    """Modo Rigoroso (cto_photo_required=True) ainda deve bloquear OS de
    instalação sem foto — não quebramos a trava quando ela está LIGADA."""
    # Liga apenas cto_photo_required + cto_port_required
    requests.put(
        f"{BASE_URL}/api/settings/os-validation-toggles",
        json={"cto_photo_required": True, "mac_validation_required": True,
              "cto_port_required": True},
        headers=admin_headers, timeout=20,
    )
    try:
        payload = {
            "client_name": "TEST_rigoroso_install",
            "address": "Rua Rigoroso 1, SP",
            "neighborhood": "Centro",
            "phone": "11999990001",
            "relato": "Teste Modo Rigoroso",
            "type": "instalacao",
            "priority": "normal",
            "assigned_collaborator_id": "col-demo-001",
        }
        r = requests.post(
            f"{BASE_URL}/api/lousa/tickets", json=payload,
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        tid = r.json()["id"]
        try:
            r_open = requests.post(
                f"{BASE_URL}/api/lousa/public/tickets/{tid}/open",
                json={"collaborator_id": "col-demo-001"},
                headers=collab_headers, timeout=20,
            )
            assert r_open.status_code == 200, r_open.text

            finalize_body = {
                "collaborator_id": "col-demo-001",
                "outcome": "sucesso",
                "latitude": -23.55, "longitude": -46.63,
                "completion_data": {
                    "sinal": -22, "ont": "TESTONT002",
                    "qtd_drop": 0, "esticadores": 0,
                    "conectores_fast": 0, "cabo_rede": 0,
                    "conectores_rede": 0, "fotos": [],
                },
            }
            r_close = requests.post(
                f"{BASE_URL}/api/lousa/public/tickets/{tid}/finalize",
                json=finalize_body, headers=collab_headers, timeout=30,
            )
            # Espera 400 com mensagem de foto/cto obrigatória
            assert r_close.status_code in (400, 422), (
                f"Modo Rigoroso DEVERIA bloquear OS sem foto, mas voltou "
                f"{r_close.status_code}: {r_close.text[:300]}"
            )
        finally:
            requests.delete(
                f"{BASE_URL}/api/lousa/tickets/{tid}",
                headers=admin_headers, timeout=20,
            )
    finally:
        # Restaura Modo Relaxado pra não deixar resíduo
        requests.put(
            f"{BASE_URL}/api/settings/os-validation-toggles",
            json={k: False for k in [
                "ipv6_test_required", "cto_photo_required",
                "cto_port_required", "mac_validation_required",
                "sn_smartolt_or_photo_required",
            ]},
            headers=admin_headers, timeout=20,
        )
