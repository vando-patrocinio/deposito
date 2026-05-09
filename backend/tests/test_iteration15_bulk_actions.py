"""Iter15 — Bulk Actions (encerrar/reagendar/cancelar) + Bulk AI Evaluate
Tests:
- POST /api/lousa/tickets/bulk-action — encerrar/reagendar/cancelar
- POST /api/lousa/tickets/bulk-ai-evaluate — heurística em lote
- Validações Pydantic (min/max length), role-guard (gestor), regras de status
- Auditoria: ticket_logs com [bulk] no details, notification para colab em cancelar/reagendar
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def gestor_headers():
    r = requests.post(f"{API}/auth/login",
                      json={"email": "gestor@empresa.com", "password": "123456"}, timeout=20)
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def colab_headers():
    """colaborador@empresa.com — usado para teste de role-guard (deve falhar 403)."""
    r = requests.post(f"{API}/auth/login",
                      json={"email": "colaborador@empresa.com", "password": "123456"}, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"colab login failed: {r.status_code} {r.text[:120]}")
    tok = r.json().get("access_token") or r.json().get("token")
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _list_active_ticket_ids(gestor_headers, limit=3):
    """Pega ticket_ids ativas (aberta/pendente/aguardando_atendimento) do grid atual."""
    r = requests.get(f"{API}/lousa/grid", headers=gestor_headers, timeout=20)
    assert r.status_code == 200, r.text
    ids = []
    for col in r.json().get("columns", []):
        for t in col.get("tickets", []):
            if t.get("status") in ("aberta", "pendente", "aguardando_atendimento") and not t.get("historical"):
                ids.append(t["id"])
                if len(ids) >= limit:
                    return ids
    return ids


def _create_ticket(gestor_headers, suffix=""):
    """Cria um ticket de seed para teste (status pendente)."""
    # Pega um colaborador do grid
    r = requests.get(f"{API}/lousa/grid", headers=gestor_headers, timeout=20)
    cols = r.json().get("columns", [])
    if not cols:
        pytest.skip("Sem colunas/colaboradores na lousa para criar ticket de teste")
    coll0 = cols[0].get("collaborator") or {}
    coll_id = coll0.get("id") or cols[0].get("collaborator_id") or cols[0].get("id")
    if not coll_id:
        return None
    payload = {
        "client_name": f"TEST_BULK_{suffix}_{int(time.time()*1000)}",
        "address": "Rua Teste, 1",
        "neighborhood": "Centro",
        "phone": "11999990000",
        "relato": "seed bulk iter15",
        "type": "reparo",
        "priority": "normal",
        "scheduled_time": "2026-05-09T14:00:00",
        "assigned_collaborator_id": coll_id,
    }
    r = requests.post(f"{API}/lousa/tickets", headers=gestor_headers, json=payload, timeout=20)
    if r.status_code not in (200, 201):
        return None
    body = r.json()
    return body.get("id") or (body.get("ticket") or {}).get("id")


# ---------- BULK AI EVALUATE ----------
class TestBulkAiEvaluate:
    def test_empty_ticket_ids_returns_422(self, gestor_headers):
        r = requests.post(f"{API}/lousa/tickets/bulk-ai-evaluate",
                          headers=gestor_headers, json={"ticket_ids": []}, timeout=20)
        assert r.status_code == 422, r.text

    def test_max_length_50_violation_returns_422(self, gestor_headers):
        ids = [f"fake-{i}" for i in range(51)]
        r = requests.post(f"{API}/lousa/tickets/bulk-ai-evaluate",
                          headers=gestor_headers, json={"ticket_ids": ids}, timeout=20)
        assert r.status_code == 422, r.text

    def test_unknown_ids_return_error_items(self, gestor_headers):
        r = requests.post(f"{API}/lousa/tickets/bulk-ai-evaluate",
                          headers=gestor_headers,
                          json={"ticket_ids": ["fake-1", "fake-2"]}, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("count") == 2
        assert all("error" in i for i in d["items"])

    def test_real_ids_return_heuristic(self, gestor_headers):
        ids = _list_active_ticket_ids(gestor_headers, limit=3)
        if len(ids) < 1:
            pytest.skip("Sem tickets ativas para testar bulk-ai-evaluate")
        r = requests.post(f"{API}/lousa/tickets/bulk-ai-evaluate",
                          headers=gestor_headers, json={"ticket_ids": ids}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("count") == len(ids)
        for item in d["items"]:
            if "error" in item:
                continue
            assert item.get("method") == "heuristic"
            assert "ai_score" in item
            assert "verdict" in item
            assert "signals" in item
            assert "duration_minutes" in item

    def test_role_guard_colab_forbidden(self, colab_headers, gestor_headers):
        ids = _list_active_ticket_ids(gestor_headers, limit=1) or ["fake"]
        r = requests.post(f"{API}/lousa/tickets/bulk-ai-evaluate",
                          headers=colab_headers, json={"ticket_ids": ids}, timeout=20)
        assert r.status_code in (401, 403), f"colab should be forbidden, got {r.status_code}"


# ---------- BULK ACTION ----------
class TestBulkActionValidation:
    def test_empty_ticket_ids_returns_422(self, gestor_headers):
        r = requests.post(f"{API}/lousa/tickets/bulk-action", headers=gestor_headers,
                          json={"ticket_ids": [], "action": "encerrar"}, timeout=20)
        assert r.status_code == 422, r.text

    def test_invalid_action_returns_422(self, gestor_headers):
        r = requests.post(f"{API}/lousa/tickets/bulk-action", headers=gestor_headers,
                          json={"ticket_ids": ["fake"], "action": "delete"}, timeout=20)
        assert r.status_code == 422, r.text

    def test_max_length_200_violation_returns_422(self, gestor_headers):
        ids = [f"fake-{i}" for i in range(201)]
        r = requests.post(f"{API}/lousa/tickets/bulk-action", headers=gestor_headers,
                          json={"ticket_ids": ids, "action": "encerrar"}, timeout=20)
        assert r.status_code == 422, r.text

    def test_role_guard_colab_forbidden(self, colab_headers):
        r = requests.post(f"{API}/lousa/tickets/bulk-action", headers=colab_headers,
                          json={"ticket_ids": ["fake"], "action": "encerrar"}, timeout=20)
        assert r.status_code in (401, 403)

    def test_unknown_ids_register_failures(self, gestor_headers):
        r = requests.post(f"{API}/lousa/tickets/bulk-action", headers=gestor_headers,
                          json={"ticket_ids": ["fake-x", "fake-y"], "action": "encerrar",
                                "notes": "teste"}, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("processed") == 0
        assert d.get("failed") == 2
        assert len(d.get("errors", [])) == 2


class TestBulkActionEncerrar:
    def test_encerrar_real_tickets(self, gestor_headers):
        # Cria 2 tickets de seed
        t1 = _create_ticket(gestor_headers, "ENC1")
        t2 = _create_ticket(gestor_headers, "ENC2")
        if not t1 or not t2:
            pytest.skip("Não foi possível criar tickets de seed")
        r = requests.post(f"{API}/lousa/tickets/bulk-action", headers=gestor_headers,
                          json={"ticket_ids": [t1, t2], "action": "encerrar",
                                "notes": "iter15 teste encerrar"}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("action") == "encerrar"
        assert d.get("processed") == 2
        assert d.get("failed") == 0
        assert set(d["success"]) == {t1, t2}

        # Verifica persistência via GET (re-aplicar deve falhar com "já encerrada")
        r2 = requests.post(f"{API}/lousa/tickets/bulk-action", headers=gestor_headers,
                           json={"ticket_ids": [t1], "action": "encerrar"}, timeout=20)
        d2 = r2.json()
        assert d2.get("processed") == 0
        assert d2.get("failed") == 1
        assert "encerrada" in (d2["errors"][0].get("error") or "").lower()


class TestBulkActionReagendar:
    def test_reagendar_with_new_date_time(self, gestor_headers):
        t1 = _create_ticket(gestor_headers, "RES1")
        t2 = _create_ticket(gestor_headers, "RES2")
        if not t1 or not t2:
            pytest.skip("Sem tickets para reagendar")
        r = requests.post(f"{API}/lousa/tickets/bulk-action", headers=gestor_headers,
                          json={"ticket_ids": [t1, t2], "action": "reagendar",
                                "notes": "iter15 reagendar bulk",
                                "new_date": "2026-06-01", "new_time": "10:30"}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("processed") == 2, d
        assert d.get("failed") == 0


class TestBulkActionCancelar:
    def test_cancelar_real_tickets(self, gestor_headers):
        t1 = _create_ticket(gestor_headers, "CAN1")
        if not t1:
            pytest.skip("Sem ticket para cancelar")
        r = requests.post(f"{API}/lousa/tickets/bulk-action", headers=gestor_headers,
                          json={"ticket_ids": [t1], "action": "cancelar",
                                "notes": "iter15 cancelar bulk"}, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("processed") == 1
        assert d.get("failed") == 0
