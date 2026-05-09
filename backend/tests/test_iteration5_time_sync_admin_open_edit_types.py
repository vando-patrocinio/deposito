"""Iteração 5 — Time sync server, admin open/edit bolhas, novos tipos (prioridade/preventiva/venda).

Cobre:
- GET /api/server-time (público)
- PUT /api/settings com time_sync_enabled / time_sync_max_drift_seconds
- POST /api/clock-records com client_time_ms (drift validation)
- POST /api/lousa/tickets com novos tipos (prioridade/preventiva/venda)
- POST /api/lousa/tickets/{id}/admin-open
- PATCH /api/lousa/tickets/{id}
- GET /api/lousa/grid SLA por tipo (preventiva, venda, prioridade)
- Regression: /api/lousa/all, /api/lousa/by-collaborator, transfer, admin-close
"""
import os
import time
import uuid

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@empresa.com", "password": "123456"}
GESTOR = {"email": "gestor@empresa.com", "password": "123456"}

TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="


# ----------------------- fixtures -----------------------
@pytest.fixture(scope="module")
def admin_h():
    r = requests.post(f"{API}/auth/login", json=ADMIN, timeout=20)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def gestor_h():
    r = requests.post(f"{API}/auth/login", json=GESTOR, timeout=20)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def collaborator_id(admin_h):
    """Cria colaborador isolado em test_mode (bypass cerca/face)."""
    payload = {
        "name": f"TEST_I5_{uuid.uuid4().hex[:6]}",
        "cpf": f"{uuid.uuid4().int % 10**11:011d}",
        "email": f"test_i5_{uuid.uuid4().hex[:6]}@example.com",
        "phone": "11999999999",
        "city": "São Paulo",
        "is_test_mode": True,
    }
    r = requests.post(f"{API}/collaborators", json=payload, headers=admin_h, timeout=20)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    yield cid
    requests.delete(f"{API}/collaborators/{cid}", headers=admin_h, timeout=20)


@pytest.fixture(scope="module", autouse=True)
def reset_settings_after(admin_h):
    """Garante settings padrão ao final (time_sync_enabled=false, SLAs default)."""
    yield
    requests.put(
        f"{API}/settings",
        json={
            "time_sync_enabled": False,
            "time_sync_max_drift_seconds": 60,
            "sla_reparo_minutes": 60,
            "sla_instalacao_minutes": 120,
            "sla_retirada_minutes": 30,
            "sla_prioridade_minutes": 45,
            "sla_preventiva_minutes": 90,
            "sla_venda_minutes": 60,
        },
        headers=admin_h,
        timeout=20,
    )


def _create_ticket(headers, cid, ttype="reparo", priority="normal"):
    body = {
        "client_name": f"TEST_I5_CLI_{uuid.uuid4().hex[:5]}",
        "address": "Av Paulista 1000, São Paulo",
        "neighborhood": "Bela Vista",
        "phone": "11988887777",
        "relato": "Teste iter5",
        "type": ttype,
        "priority": priority,
        "assigned_collaborator_id": cid,
    }
    r = requests.post(f"{API}/lousa/tickets", json=body, headers=headers, timeout=30)
    return r


def _delete_ticket(headers, tid):
    requests.delete(f"{API}/lousa/tickets/{tid}", headers=headers, timeout=20)


# ============================================================
# 1. GET /api/server-time (público)
# ============================================================
class TestServerTime:
    def test_server_time_public_no_auth(self):
        r = requests.get(f"{API}/server-time", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        for key in ("iso", "epoch_ms", "epoch_s", "tz", "sync_enabled", "max_drift_seconds"):
            assert key in d, f"falta chave {key} em {d}"
        assert isinstance(d["epoch_ms"], int)
        assert isinstance(d["epoch_s"], int)
        assert isinstance(d["sync_enabled"], bool)
        assert isinstance(d["max_drift_seconds"], int)
        # epoch_ms ≈ tempo atual (tolerância 30s)
        now_ms = int(time.time() * 1000)
        assert abs(now_ms - d["epoch_ms"]) < 30_000


# ============================================================
# 2. PUT /api/settings com time_sync
# ============================================================
class TestSettingsTimeSync:
    def test_update_time_sync_settings(self, admin_h):
        r = requests.put(
            f"{API}/settings",
            json={"time_sync_enabled": True, "time_sync_max_drift_seconds": 30},
            headers=admin_h,
            timeout=20,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["time_sync_enabled"] is True
        assert d["time_sync_max_drift_seconds"] == 30

    def test_server_time_reflects_settings(self, admin_h):
        # Após habilitar, GET /server-time precisa devolver sync_enabled=True
        r = requests.get(f"{API}/server-time", timeout=15)
        d = r.json()
        assert d["sync_enabled"] is True
        assert d["max_drift_seconds"] == 30


# ============================================================
# 3-6. Validação drift no /api/clock-records
# ============================================================
class TestClockRecordsTimeSync:
    def _payload(self, cid, **kw):
        p = {
            "collaborator_id": cid,
            "type": "Entrada",
            "selfie_base64": f"data:image/png;base64,{TINY_PNG_B64}",
            "lat": -23.5505,
            "lng": -46.6333,
        }
        p.update(kw)
        return p

    def test_drift_too_old_blocks_412(self, collaborator_id, admin_h):
        # time_sync_enabled=True (já setado em TestSettingsTimeSync)
        old_ms = int(time.time() * 1000) - 3_600_000  # 1h atrás
        r = requests.post(
            f"{API}/clock-records",
            json=self._payload(collaborator_id, client_time_ms=old_ms),
            timeout=30,
        )
        assert r.status_code == 412, f"esperado 412, veio {r.status_code}: {r.text}"
        assert "dessincronizado" in r.text.lower() or "sincroniz" in r.text.lower()

    def test_no_client_time_ms_does_not_block(self, collaborator_id, admin_h):
        # SEM client_time_ms → backend ignora drift gracefully
        r = requests.post(
            f"{API}/clock-records",
            json=self._payload(collaborator_id),  # sem client_time_ms
            timeout=60,
        )
        # Deve passar pela validação de tempo (pode falhar/sucesso por outras razões, mas NÃO 412 dessync)
        assert r.status_code != 412 or "dessincron" not in r.text.lower(), (
            f"não deveria bloquear por drift quando ausente: {r.status_code} {r.text}"
        )

    def test_drift_within_limit_passes(self, collaborator_id):
        ok_ms = int(time.time() * 1000) - 5_000  # 5s atrás (dentro do 30s)
        r = requests.post(
            f"{API}/clock-records",
            json=self._payload(collaborator_id, type="Saída", client_time_ms=ok_ms,
                               force_close_open_tickets=True),
            timeout=60,
        )
        # Não deve ser 412 por dessincronização
        assert not (r.status_code == 412 and "dessincron" in r.text.lower()), r.text

    def test_drift_ignored_when_sync_disabled(self, collaborator_id, admin_h):
        # Desabilita time_sync
        rs = requests.put(
            f"{API}/settings",
            json={"time_sync_enabled": False},
            headers=admin_h,
            timeout=20,
        )
        assert rs.status_code == 200
        # Mesmo com client_time_ms muito antigo, deve passar pela validação de drift
        old_ms = int(time.time() * 1000) - 7_200_000
        r = requests.post(
            f"{API}/clock-records",
            json=self._payload(collaborator_id, type="Início intervalo", client_time_ms=old_ms),
            timeout=60,
        )
        # Pode falhar por outra razão, mas não por drift
        assert not (r.status_code == 412 and "dessincron" in r.text.lower()), (
            f"drift não deveria ser validado com time_sync desabilitado: {r.text}"
        )
        # Re-habilita para os próximos testes
        requests.put(f"{API}/settings", json={"time_sync_enabled": True}, headers=admin_h, timeout=20)


# ============================================================
# 7-8. POST /api/lousa/tickets com novos tipos
# ============================================================
class TestNewTicketTypes:
    @pytest.mark.parametrize("ttype", ["prioridade", "preventiva", "venda"])
    def test_create_with_new_types(self, gestor_h, collaborator_id, ttype):
        r = _create_ticket(gestor_h, collaborator_id, ttype=ttype)
        assert r.status_code in (200, 201), f"{ttype} -> {r.status_code} {r.text}"
        d = r.json()
        assert d["type"] == ttype
        _delete_ticket(gestor_h, d["id"])

    def test_create_invalid_type_returns_422(self, gestor_h, collaborator_id):
        body = {
            "client_name": "TEST_I5_INV",
            "address": "Av Paulista 1000",
            "type": "invalido",
            "assigned_collaborator_id": collaborator_id,
        }
        r = requests.post(f"{API}/lousa/tickets", json=body, headers=gestor_h, timeout=20)
        assert r.status_code == 422, f"esperado 422, veio {r.status_code}: {r.text}"


# ============================================================
# 9-10. POST /api/lousa/tickets/{id}/admin-open
# ============================================================
class TestAdminOpen:
    def test_admin_open_pending_ticket(self, gestor_h, collaborator_id):
        c = _create_ticket(gestor_h, collaborator_id, ttype="reparo")
        assert c.status_code in (200, 201), c.text
        tid = c.json()["id"]
        try:
            r = requests.post(f"{API}/lousa/tickets/{tid}/admin-open", headers=gestor_h, timeout=20)
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["status"] == "aberta"
            assert d["opened_at"] is not None
        finally:
            _delete_ticket(gestor_h, tid)

    def test_admin_open_already_open_returns_400(self, gestor_h, collaborator_id):
        c = _create_ticket(gestor_h, collaborator_id, ttype="reparo")
        tid = c.json()["id"]
        try:
            # 1ª abertura: ok
            r1 = requests.post(f"{API}/lousa/tickets/{tid}/admin-open", headers=gestor_h, timeout=20)
            assert r1.status_code == 200
            # 2ª abertura: deve dar 400
            r2 = requests.post(f"{API}/lousa/tickets/{tid}/admin-open", headers=gestor_h, timeout=20)
            assert r2.status_code == 400, f"esperado 400, veio {r2.status_code}: {r2.text}"
        finally:
            _delete_ticket(gestor_h, tid)


# ============================================================
# 11-13. PATCH /api/lousa/tickets/{id}
# ============================================================
class TestEditTicket:
    def test_patch_updates_client_snapshot_and_fields(self, gestor_h, collaborator_id):
        c = _create_ticket(gestor_h, collaborator_id, ttype="reparo", priority="normal")
        tid = c.json()["id"]
        try:
            patch = {
                "client_name": "NEW_NAME_I5",
                "address": "Rua Nova 50, SP",
                "type": "preventiva",
                "priority": "horario",
                "scheduled_time": "2030-01-01T10:30:00",
            }
            r = requests.patch(f"{API}/lousa/tickets/{tid}", json=patch, headers=gestor_h, timeout=20)
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["client_snapshot"]["name"] == "NEW_NAME_I5"
            assert d["client_snapshot"]["address"] == "Rua Nova 50, SP"
            assert d["type"] == "preventiva"
            assert d["priority"] == "horario"
            assert d["scheduled_time"] == "2030-01-01T10:30:00"
        finally:
            _delete_ticket(gestor_h, tid)

    def test_patch_finalized_ticket_returns_400(self, gestor_h, admin_h, collaborator_id):
        # cria + abre + admin-close (encerra)
        c = _create_ticket(gestor_h, collaborator_id, ttype="reparo")
        tid = c.json()["id"]
        try:
            requests.post(f"{API}/lousa/tickets/{tid}/admin-open", headers=gestor_h, timeout=20)
            close = requests.post(
                f"{API}/lousa/tickets/{tid}/admin-close",
                json={"action": "encerrar", "notes": "iter5 close"},
                headers=gestor_h, timeout=20,
            )
            assert close.status_code == 200, close.text
            # Tenta editar uma encerrada → 400
            r = requests.patch(
                f"{API}/lousa/tickets/{tid}",
                json={"client_name": "X"},
                headers=gestor_h, timeout=20,
            )
            assert r.status_code == 400, f"esperado 400, veio {r.status_code}: {r.text}"
        finally:
            _delete_ticket(gestor_h, tid)

    def test_patch_creates_editada_log(self, gestor_h, collaborator_id):
        c = _create_ticket(gestor_h, collaborator_id, ttype="reparo")
        tid = c.json()["id"]
        try:
            requests.patch(
                f"{API}/lousa/tickets/{tid}",
                json={"client_name": "EDIT_LOG_TEST", "type": "venda"},
                headers=gestor_h, timeout=20,
            )
            logs = requests.get(
                f"{API}/lousa/logs?ticket_id={tid}&limit=50", headers=gestor_h, timeout=20,
            )
            assert logs.status_code == 200, logs.text
            items = logs.json()["items"]
            edited = [i for i in items if i["action"] == "editada"]
            assert len(edited) >= 1, f"nenhum log 'editada' encontrado: {items}"
            details = edited[0].get("details") or ""
            assert ("client_snapshot" in details) or ("type" in details), (
                f"details deveria listar campos alterados: {details}"
            )
        finally:
            _delete_ticket(gestor_h, tid)


# ============================================================
# 14-16. SLA por tipo no /api/lousa/grid
# ============================================================
class TestGridSlaPerType:
    def test_grid_uses_default_sla_for_preventiva_and_venda(self, gestor_h, collaborator_id, admin_h):
        # Garantir defaults
        requests.put(
            f"{API}/settings",
            json={"sla_preventiva_minutes": 90, "sla_venda_minutes": 60, "sla_prioridade_minutes": 45},
            headers=admin_h, timeout=20,
        )
        c1 = _create_ticket(gestor_h, collaborator_id, ttype="preventiva")
        c2 = _create_ticket(gestor_h, collaborator_id, ttype="venda")
        t1, t2 = c1.json()["id"], c2.json()["id"]
        try:
            r = requests.get(f"{API}/lousa/grid", headers=gestor_h, timeout=30)
            assert r.status_code == 200, r.text
            d = r.json()
            sla_map = d["sla_map"]
            assert sla_map["preventiva"] == 90
            assert sla_map["venda"] == 60
            assert sla_map["prioridade"] == 45
            # Confirma que cada bolha embute sla.sla_minutes correto
            all_tickets = [t for col in d["columns"] for t in col["tickets"]]
            for t in all_tickets:
                if t["id"] == t1:
                    assert t["sla"]["sla_minutes"] == 90
                if t["id"] == t2:
                    assert t["sla"]["sla_minutes"] == 60
        finally:
            _delete_ticket(gestor_h, t1)
            _delete_ticket(gestor_h, t2)

    def test_grid_reflects_custom_sla_values(self, gestor_h, collaborator_id, admin_h):
        # Atualiza settings com valores customizados
        rs = requests.put(
            f"{API}/settings",
            json={"sla_preventiva_minutes": 180, "sla_venda_minutes": 45},
            headers=admin_h, timeout=20,
        )
        assert rs.status_code == 200
        s = rs.json()
        assert s["sla_preventiva_minutes"] == 180
        assert s["sla_venda_minutes"] == 45

        c1 = _create_ticket(gestor_h, collaborator_id, ttype="preventiva")
        c2 = _create_ticket(gestor_h, collaborator_id, ttype="venda")
        t1, t2 = c1.json()["id"], c2.json()["id"]
        try:
            r = requests.get(f"{API}/lousa/grid", headers=gestor_h, timeout=30)
            d = r.json()
            assert d["sla_map"]["preventiva"] == 180
            assert d["sla_map"]["venda"] == 45
            for t in [tk for col in d["columns"] for tk in col["tickets"]]:
                if t["id"] == t1:
                    assert t["sla"]["sla_minutes"] == 180
                if t["id"] == t2:
                    assert t["sla"]["sla_minutes"] == 45
        finally:
            _delete_ticket(gestor_h, t1)
            _delete_ticket(gestor_h, t2)
            # Restaura defaults
            requests.put(
                f"{API}/settings",
                json={"sla_preventiva_minutes": 90, "sla_venda_minutes": 60},
                headers=admin_h, timeout=20,
            )


# ============================================================
# Regression — endpoints existentes ainda funcionam
# ============================================================
class TestRegression:
    def test_lousa_all(self, gestor_h):
        r = requests.get(f"{API}/lousa/all", headers=gestor_h, timeout=20)
        assert r.status_code == 200, r.text
        assert "tickets" in r.json()

    def test_by_collaborator(self, collaborator_id):
        r = requests.get(f"{API}/lousa/by-collaborator/{collaborator_id}", timeout=20)
        assert r.status_code == 200, r.text
        assert "tickets" in r.json()
        assert "clock_state" in r.json()

    def test_transfer_still_works(self, gestor_h, collaborator_id, admin_h):
        c = _create_ticket(gestor_h, collaborator_id, ttype="reparo")
        tid = c.json()["id"]
        try:
            r = requests.post(
                f"{API}/lousa/tickets/{tid}/transfer",
                json={"new_grid_slot": "10:00"},
                headers=gestor_h, timeout=20,
            )
            assert r.status_code == 200, r.text
            assert r.json().get("grid_slot") == "10:00"
        finally:
            _delete_ticket(gestor_h, tid)

    def test_admin_close_still_works(self, gestor_h, collaborator_id):
        c = _create_ticket(gestor_h, collaborator_id, ttype="reparo")
        tid = c.json()["id"]
        try:
            requests.post(f"{API}/lousa/tickets/{tid}/admin-open", headers=gestor_h, timeout=20)
            r = requests.post(
                f"{API}/lousa/tickets/{tid}/admin-close",
                json={"action": "encerrar", "notes": "regression iter5"},
                headers=gestor_h, timeout=20,
            )
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "encerrada"
        finally:
            _delete_ticket(gestor_h, tid)
