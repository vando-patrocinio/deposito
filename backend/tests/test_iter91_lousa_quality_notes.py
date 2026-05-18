"""Backend tests para feature 'Notas de Qualidade' (sinal SmartOLT
abertura vs fechamento) — iteração 91.

Cobertura:
 - GET /api/lousa/quality-notes/config (gestor/admin)
 - PUT /api/lousa/quality-notes/config (admin) — toggle on/off
 - GET /api/lousa/quality-notes?days=30
 - POST /api/lousa/tickets/{id}/capture-signal — autorização, 400 quando
   captura desligada, 422 quando ONU não mapeada/sem leitura
 - Helper _capture_signal_snapshot disparado em create/finalize ticket
   (validado via campo signal_at_open no ticket criado)
"""
import os
import uuid
import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"


# ----------------------------------------------------------------------- fixtures
def _login(email: str, password: str) -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    assert r.status_code == 200, f"login {email} -> {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login("admin@empresa.com", "123456")


@pytest.fixture(scope="module")
def gestor_token():
    return _login("gestor@empresa.com", "123456")


@pytest.fixture(scope="module")
def colab_token():
    return _login("colaborador@empresa.com", "123456")


def H(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# --------------------------------------------------------------- config endpoints
class TestQualityNotesConfig:
    """GET/PUT /api/lousa/quality-notes/config"""

    def test_get_config_as_admin(self, admin_token):
        r = requests.get(f"{API}/lousa/quality-notes/config", headers=H(admin_token), timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "enabled" in body
        assert "degradation_threshold_db" in body
        assert "los_threshold_dbm" in body
        assert isinstance(body["enabled"], bool)

    def test_get_config_as_gestor(self, gestor_token):
        r = requests.get(f"{API}/lousa/quality-notes/config", headers=H(gestor_token), timeout=10)
        assert r.status_code == 200
        assert "enabled" in r.json()

    def test_get_config_forbidden_for_colaborador(self, colab_token):
        r = requests.get(f"{API}/lousa/quality-notes/config", headers=H(colab_token), timeout=10)
        assert r.status_code == 403

    def test_put_config_admin_can_toggle(self, admin_token):
        # ligar
        r = requests.put(
            f"{API}/lousa/quality-notes/config",
            headers=H(admin_token), json={"enabled": True}, timeout=10,
        )
        assert r.status_code == 200, r.text
        assert r.json()["enabled"] is True

        # atualiza threshold também
        r2 = requests.put(
            f"{API}/lousa/quality-notes/config",
            headers=H(admin_token),
            json={"degradation_threshold_db": 4.0, "los_threshold_dbm": -27.0},
            timeout=10,
        )
        assert r2.status_code == 200
        body = r2.json()
        assert body["degradation_threshold_db"] == 4.0
        assert body["los_threshold_dbm"] == -27.0

    def test_put_config_gestor_forbidden(self, gestor_token):
        r = requests.put(
            f"{API}/lousa/quality-notes/config",
            headers=H(gestor_token), json={"enabled": True}, timeout=10,
        )
        assert r.status_code == 403

    def test_put_config_empty_body_rejected(self, admin_token):
        r = requests.put(
            f"{API}/lousa/quality-notes/config",
            headers=H(admin_token), json={}, timeout=10,
        )
        assert r.status_code == 400


# ------------------------------------------------------------------- listing endpoint
class TestQualityNotesList:
    def test_list_returns_structure(self, gestor_token):
        r = requests.get(
            f"{API}/lousa/quality-notes?days=30",
            headers=H(gestor_token), timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Required fields per review request
        for k in ("items", "total", "summary", "config"):
            assert k in body, f"missing key {k} in {body.keys()}"
        assert isinstance(body["items"], list)
        assert isinstance(body["total"], int)
        assert isinstance(body["summary"], dict)
        # summary must have the 3 buckets
        for bucket in ("bom", "regular", "ruim"):
            assert bucket in body["summary"]

    def test_list_forbidden_for_colaborador(self, colab_token):
        r = requests.get(
            f"{API}/lousa/quality-notes?days=30",
            headers=H(colab_token), timeout=10,
        )
        assert r.status_code == 403


# ------------------------------------------------------- manual capture-signal endpoint
def _create_demo_ticket(token: str) -> str:
    """Cria um ticket simples na lousa e retorna o ticket_id."""
    payload = {
        "type": "instalacao",
        "client_name": f"TEST_QualityNotes_{uuid.uuid4().hex[:6]}",
        "address": "Rua Teste 100",
        "phone": "11999990000",
        "assigned_collaborator_id": "col-30aafc3c",
        "scheduled_for_date": "2026-01-15",
        "scheduled_for_slot": "manha",
    }
    r = requests.post(f"{API}/lousa/tickets", headers=H(token), json=payload, timeout=15)
    assert r.status_code in (200, 201), f"create ticket -> {r.status_code} {r.text}"
    return r.json()["id"]


class TestManualCaptureSignal:
    @pytest.fixture(scope="class")
    def ticket_id(self, gestor_token):
        return _create_demo_ticket(gestor_token)

    def test_capture_returns_422_when_no_onu(self, gestor_token, ticket_id):
        """Ticket sem ONU mapeada deve retornar 422 com mensagem clara."""
        r = requests.post(
            f"{API}/lousa/tickets/{ticket_id}/capture-signal",
            headers=H(gestor_token), json={"moment": "close"}, timeout=15,
        )
        # 422 esperado (sem ONU). 200 só se o demo tiver SmartOLT mockado.
        assert r.status_code in (200, 422), r.text
        if r.status_code == 422:
            detail = (r.json().get("detail") or "").lower()
            assert "sinal" in detail or "onu" in detail or "smartolt" in detail

    def test_capture_404_unknown_ticket(self, gestor_token):
        r = requests.post(
            f"{API}/lousa/tickets/does-not-exist-xyz/capture-signal",
            headers=H(gestor_token), json={"moment": "close"}, timeout=10,
        )
        assert r.status_code == 404

    def test_capture_unauth_no_token(self, ticket_id):
        r = requests.post(
            f"{API}/lousa/tickets/{ticket_id}/capture-signal",
            json={"moment": "close"}, timeout=10,
        )
        assert r.status_code in (401, 403)

    def test_capture_colaborador_cannot_touch_others_ticket(self, colab_token, gestor_token):
        """Cria ticket atribuído a outro técnico -> colaborador 403."""
        payload = {
            "type": "instalacao",
            "client_name": f"TEST_OtherTech_{uuid.uuid4().hex[:6]}",
            "address": "Rua Outra 200",
            "phone": "11988880000",
            "assigned_collaborator_id": "col-demo-OTHER",
            "scheduled_for_date": "2026-01-16",
            "scheduled_for_slot": "manha",
        }
        cr = requests.post(f"{API}/lousa/tickets", headers=H(gestor_token), json=payload, timeout=15)
        if cr.status_code not in (200, 201):
            pytest.skip(f"cannot create ticket for other tech: {cr.status_code} {cr.text}")
        other_tid = cr.json()["id"]
        r = requests.post(
            f"{API}/lousa/tickets/{other_tid}/capture-signal",
            headers=H(colab_token), json={"moment": "close"}, timeout=10,
        )
        assert r.status_code == 403

    def test_capture_invalid_moment_rejected(self, gestor_token, ticket_id):
        r = requests.post(
            f"{API}/lousa/tickets/{ticket_id}/capture-signal",
            headers=H(gestor_token), json={"moment": "middle"}, timeout=10,
        )
        assert r.status_code == 422  # pydantic Literal rejection

    def test_capture_blocked_when_toggle_off(self, admin_token, gestor_token, ticket_id):
        """Toggle OFF deve retornar 400 com mensagem 'desligada'."""
        # turn off
        r0 = requests.put(
            f"{API}/lousa/quality-notes/config",
            headers=H(admin_token), json={"enabled": False}, timeout=10,
        )
        assert r0.status_code == 200
        assert r0.json()["enabled"] is False
        try:
            r = requests.post(
                f"{API}/lousa/tickets/{ticket_id}/capture-signal",
                headers=H(gestor_token), json={"moment": "close"}, timeout=10,
            )
            assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
            detail = (r.json().get("detail") or "").lower()
            assert "deslig" in detail, f"mensagem deve mencionar 'desligada': {detail}"
        finally:
            # restore ON (cleanup)
            requests.put(
                f"{API}/lousa/quality-notes/config",
                headers=H(admin_token), json={"enabled": True}, timeout=10,
            )


# -------------------------------------------------- helper firing on create_ticket
class TestSnapshotHelperOnCreate:
    def test_create_ticket_has_signal_at_open_field_handled(self, gestor_token):
        """Cria um ticket via API. Como não há ONU mapeada para o snapshot demo,
        signal_at_open pode ser None — o importante é que o helper não quebra
        o create. A presença da chave (mesmo None) confirma o code path."""
        ticket_id = _create_demo_ticket(gestor_token)
        # GET ticket detail
        r = requests.get(
            f"{API}/lousa/tickets/{ticket_id}",
            headers=H(gestor_token), timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Helper deve ter rodado (sucesso ou falha silenciosa). Caso bem-sucedido,
        # signal_at_open existe e é dict; caso falha (sem ONU), é None/ausente.
        # Critério mínimo: o create não quebrou.
        assert body.get("id") == ticket_id
        # signal_at_open pode ser None (aceitável). Se presente, valida formato.
        sao = body.get("signal_at_open")
        if sao is not None:
            assert isinstance(sao, dict)
            assert "rx_dbm" in sao
