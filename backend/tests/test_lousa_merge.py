"""Backend tests for Smart1 (lousa de bolhas) + Smart2 (selfie ponto) merge.

Coverage:
- /api/auth/login JWT for admin/gestor/colaborador
- /api/lousa/by-collaborator/{cid} (public)
- /api/lousa/me (colaborador token)
- /api/lousa/all (gestor token)
- /api/lousa/public/tickets/{id}/open BEFORE Entrada → 412
- /api/lousa/tickets create (gestor)
- /api/lousa/tickets/{id}/admin-close (gestor)
- /api/notifications + /api/notifications/{nid}/read
- Regression smart2: /api/saas/me, /api/collaborators, /api/auth/me
- Administrador role acesso aos endpoints do gestor
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
COL_DEMO = "col-demo-001"


# -------------------- Fixtures --------------------
@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(session, email, password):
    r = session.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login {email} failed: {r.status_code} {r.text}"
    data = r.json()
    assert data.get("ok") is True
    assert "access_token" in data
    assert "user" in data
    return data


@pytest.fixture(scope="module")
def admin_token(session):
    return _login(session, "admin@empresa.com", "123456")["access_token"]


@pytest.fixture(scope="module")
def gestor_token(session):
    return _login(session, "gestor@empresa.com", "123456")["access_token"]


@pytest.fixture(scope="module")
def colab_token(session):
    return _login(session, "colaborador@empresa.com", "123456")["access_token"]


def _h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# -------------------- Auth --------------------
class TestAuth:
    def test_login_admin(self, session):
        d = _login(session, "admin@empresa.com", "123456")
        assert d["user"]["role"] == "administrador"
        assert d["user"]["email"] == "admin@empresa.com"

    def test_login_gestor(self, session):
        d = _login(session, "gestor@empresa.com", "123456")
        assert d["user"]["role"] == "gestor"

    def test_login_colaborador(self, session):
        d = _login(session, "colaborador@empresa.com", "123456")
        assert d["user"]["role"] == "colaborador"
        assert d["user"].get("collaborator_id") == COL_DEMO, "Colaborador deve estar vinculado a col-demo-001"

    def test_login_wrong_password(self, session):
        r = session.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@empresa.com", "password": "wrong"})
        assert r.status_code == 401

    def test_auth_me(self, session, gestor_token):
        r = session.get(f"{BASE_URL}/api/auth/me", headers=_h(gestor_token))
        assert r.status_code == 200
        u = r.json()
        assert u["email"] == "gestor@empresa.com"
        assert u["role"] == "gestor"


# -------------------- Lousa READ (public + auth) --------------------
class TestLousaRead:
    def test_lousa_by_collaborator_public(self, session):
        r = session.get(f"{BASE_URL}/api/lousa/by-collaborator/{COL_DEMO}")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "tickets" in data and "clock_state" in data and "lousa_unlocked" in data
        # 5 bolhas seed (somente ativas; resolvidas só aparecem se houver fechadas <24h)
        active = [t for t in data["tickets"] if t["status"] in ("pendente", "aberta", "aguardando_atendimento")]
        assert len(active) >= 5, f"Esperava >=5 bolhas ativas, achei {len(active)}"
        assert data["clock_state"]["has_entrada"] is False
        assert data["lousa_unlocked"] is False

    def test_lousa_by_collaborator_not_found(self, session):
        r = session.get(f"{BASE_URL}/api/lousa/by-collaborator/inexistente-xyz")
        assert r.status_code == 404

    def test_lousa_me_colaborador(self, session, colab_token):
        r = session.get(f"{BASE_URL}/api/lousa/me", headers=_h(colab_token))
        assert r.status_code == 200, r.text
        data = r.json()
        assert "tickets" in data
        # Todas as bolhas devem ser do col-demo-001
        for t in data["tickets"]:
            assert t["assigned_collaborator_id"] == COL_DEMO

    def test_lousa_me_gestor_forbidden(self, session, gestor_token):
        r = session.get(f"{BASE_URL}/api/lousa/me", headers=_h(gestor_token))
        assert r.status_code == 403

    def test_lousa_all_gestor(self, session, gestor_token):
        r = session.get(f"{BASE_URL}/api/lousa/all", headers=_h(gestor_token))
        assert r.status_code == 200, r.text
        data = r.json()
        assert "tickets" in data
        assert len(data["tickets"]) >= 5

    def test_lousa_all_admin_super_role(self, session, admin_token):
        """Administrador deve ter acesso aos endpoints do gestor (super-role)."""
        r = session.get(f"{BASE_URL}/api/lousa/all", headers=_h(admin_token))
        assert r.status_code == 200, r.text
        assert len(r.json()["tickets"]) >= 5

    def test_lousa_all_colaborador_forbidden(self, session, colab_token):
        r = session.get(f"{BASE_URL}/api/lousa/all", headers=_h(colab_token))
        assert r.status_code == 403


# -------------------- Lousa state machine --------------------
class TestLousaStateMachine:
    def test_public_open_blocked_before_entrada(self, session):
        """Sem bater Entrada → 412 'Bata o ponto de Entrada antes'."""
        # Pega 1 ticket pendente do colaborador demo
        r = session.get(f"{BASE_URL}/api/lousa/by-collaborator/{COL_DEMO}")
        tickets = [t for t in r.json()["tickets"] if t["status"] == "pendente"]
        assert tickets, "Nenhuma bolha pendente para testar"
        tid = tickets[0]["id"]
        r2 = session.post(
            f"{BASE_URL}/api/lousa/public/tickets/{tid}/open",
            json={"collaborator_id": COL_DEMO},
        )
        assert r2.status_code == 412, f"Esperava 412, recebi {r2.status_code}: {r2.text}"
        detail = r2.json().get("detail", "")
        assert "Entrada" in detail


# -------------------- Lousa CRUD (gestor) --------------------
class TestLousaCRUD:
    created_id: str | None = None

    def test_create_ticket_as_gestor(self, session, gestor_token):
        payload = {
            "client_name": f"TEST_Cliente_{uuid.uuid4().hex[:6]}",
            "address": "Rua Teste, 100, São Paulo",
            "neighborhood": "Centro",
            "phone": "+5511900000000",
            "relato": "Teste automatizado merge smart1+smart2",
            "type": "reparo",
            "priority": "normal",
            "assigned_collaborator_id": COL_DEMO,
        }
        r = session.post(f"{BASE_URL}/api/lousa/tickets", json=payload, headers=_h(gestor_token))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "pendente"
        assert data["assigned_collaborator_id"] == COL_DEMO
        assert data["client_snapshot"]["name"].startswith("TEST_")
        assert "id" in data and data["id"].startswith("tkt-")
        TestLousaCRUD.created_id = data["id"]

    def test_create_ticket_as_colaborador_forbidden(self, session, colab_token):
        payload = {
            "client_name": "TEST_NoAccess",
            "address": "x", "assigned_collaborator_id": COL_DEMO,
        }
        r = session.post(f"{BASE_URL}/api/lousa/tickets", json=payload, headers=_h(colab_token))
        assert r.status_code == 403

    def test_admin_close_ticket(self, session, gestor_token):
        assert TestLousaCRUD.created_id, "Ticket não foi criado"
        r = session.post(
            f"{BASE_URL}/api/lousa/tickets/{TestLousaCRUD.created_id}/admin-close",
            json={"action": "encerrar", "notes": "Encerrada por teste automatizado"},
            headers=_h(gestor_token),
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "encerrada"
        assert data["admin_action"] == "encerrar"
        assert data["closed_at"] is not None

    def test_admin_close_already_closed(self, session, gestor_token):
        r = session.post(
            f"{BASE_URL}/api/lousa/tickets/{TestLousaCRUD.created_id}/admin-close",
            json={"action": "encerrar"},
            headers=_h(gestor_token),
        )
        assert r.status_code == 400

    def test_admin_creates_ticket_super_role(self, session, admin_token):
        """Administrador (super-role) também consegue criar."""
        payload = {
            "client_name": f"TEST_Admin_{uuid.uuid4().hex[:6]}",
            "address": "Rua Admin, 1",
            "assigned_collaborator_id": COL_DEMO,
        }
        r = session.post(f"{BASE_URL}/api/lousa/tickets", json=payload, headers=_h(admin_token))
        assert r.status_code == 200, r.text
        # cleanup
        tid = r.json()["id"]
        session.delete(f"{BASE_URL}/api/lousa/tickets/{tid}", headers=_h(admin_token))

    def test_cleanup_created(self, session, gestor_token):
        if TestLousaCRUD.created_id:
            r = session.delete(
                f"{BASE_URL}/api/lousa/tickets/{TestLousaCRUD.created_id}",
                headers=_h(gestor_token),
            )
            assert r.status_code in (200, 204)


# -------------------- Notifications --------------------
class TestNotifications:
    def test_list_as_gestor(self, session, gestor_token):
        r = session.get(f"{BASE_URL}/api/notifications", headers=_h(gestor_token))
        assert r.status_code == 200, r.text
        data = r.json()
        assert "items" in data and "unread_count" in data
        assert isinstance(data["items"], list)
        assert isinstance(data["unread_count"], int)

    def test_list_as_admin_super_role(self, session, admin_token):
        r = session.get(f"{BASE_URL}/api/notifications", headers=_h(admin_token))
        assert r.status_code == 200

    def test_list_as_colab_forbidden(self, session, colab_token):
        r = session.get(f"{BASE_URL}/api/notifications", headers=_h(colab_token))
        assert r.status_code == 403

    def test_mark_read(self, session, gestor_token):
        # Cria uma notificação fake invocando notify-backoffice via colaborador?
        # Mais simples: lista e se houver alguma, marca como lida; senão skip.
        r = session.get(f"{BASE_URL}/api/notifications", headers=_h(gestor_token))
        items = r.json()["items"]
        if not items:
            pytest.skip("Sem notificações para marcar como lida")
        nid = items[0]["id"]
        r2 = session.post(f"{BASE_URL}/api/notifications/{nid}/read", headers=_h(gestor_token))
        assert r2.status_code == 200
        assert r2.json().get("ok") is True

    def test_read_all(self, session, gestor_token):
        r = session.post(f"{BASE_URL}/api/notifications/read-all", headers=_h(gestor_token))
        assert r.status_code == 200


# -------------------- Smart2 regression --------------------
class TestSmart2Regression:
    def test_saas_me(self, session, gestor_token):
        r = session.get(f"{BASE_URL}/api/saas/me", headers=_h(gestor_token))
        assert r.status_code == 200, r.text
        data = r.json()
        # Deve ter algum identificador de empresa/plano
        assert isinstance(data, dict)

    def test_collaborators_list(self, session, gestor_token):
        r = session.get(f"{BASE_URL}/api/collaborators", headers=_h(gestor_token))
        assert r.status_code == 200, r.text
        data = r.json()
        # Pode ser lista ou dict {items: [...]}
        if isinstance(data, list):
            assert any(c.get("id") == COL_DEMO for c in data)
        elif isinstance(data, dict) and "items" in data:
            assert any(c.get("id") == COL_DEMO for c in data["items"])

    def test_auth_me_colab(self, session, colab_token):
        r = session.get(f"{BASE_URL}/api/auth/me", headers=_h(colab_token))
        assert r.status_code == 200
        u = r.json()
        assert u["role"] == "colaborador"
        assert u.get("collaborator_id") == COL_DEMO
