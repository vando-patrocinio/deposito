"""Iteração 4 — Grade fixa de horários da lousa + configurações por slot.

Settings novos: lousa_grid_start_hour, lousa_grid_end_hour,
lousa_grid_slot_minutes, lousa_grid_max_per_slot.

GET /api/lousa/grid agora retorna 'slots' (lista fixa) e 'unscheduled'.
POST /api/lousa/tickets/{id}/transfer aceita 'new_grid_slot' (sem
new_collaborator_id mantém o mesmo técnico).
"""
import os
import uuid

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@empresa.com", "password": "123456"}
GESTOR = {"email": "gestor@empresa.com", "password": "123456"}


# ----------------------- fixtures -----------------------
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json=ADMIN, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def gestor_token():
    r = requests.post(f"{API}/auth/login", json=GESTOR, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def gestor_h(gestor_token):
    return {"Authorization": f"Bearer {gestor_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def collaborator_id(admin_h):
    """Cria colaborador isolado para os testes de slot."""
    payload = {
        "name": f"TEST_I4_{uuid.uuid4().hex[:6]}",
        "cpf": f"{uuid.uuid4().int % 10**11:011d}",
        "email": f"test_i4_{uuid.uuid4().hex[:6]}@example.com",
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
def reset_settings(admin_h):
    """Garante settings padrão (8-18, 60min, 2/slot) ao final."""
    yield
    requests.put(
        f"{API}/settings",
        json={
            "lousa_grid_start_hour": 8,
            "lousa_grid_end_hour": 18,
            "lousa_grid_slot_minutes": 60,
            "lousa_grid_max_per_slot": 2,
        },
        headers=admin_h,
        timeout=20,
    )


def _create_ticket(admin_h, cid, scheduled_time=None, priority="normal", name=None):
    payload = {
        "client_name": name or f"TEST_I4_CLI_{uuid.uuid4().hex[:5]}",
        "address": "Rua dos Testes, 100, São Paulo",
        "neighborhood": "Centro",
        "phone": "11999999999",
        "relato": "teste iter4",
        "type": "reparo",
        "priority": priority,
        "scheduled_time": scheduled_time,
        "assigned_collaborator_id": cid,
    }
    r = requests.post(f"{API}/lousa/tickets", json=payload, headers=admin_h, timeout=30)
    assert r.status_code in (200, 201), r.text
    return r.json()


# ----------------------- 1. Settings PUT --------------------------
class TestSettingsLousaGrid:
    def test_put_lousa_grid_settings(self, admin_h):
        r = requests.put(
            f"{API}/settings",
            json={
                "lousa_grid_start_hour": 8,
                "lousa_grid_end_hour": 18,
                "lousa_grid_slot_minutes": 60,
                "lousa_grid_max_per_slot": 2,
            },
            headers=admin_h,
            timeout=20,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["lousa_grid_start_hour"] == 8
        assert d["lousa_grid_end_hour"] == 18
        assert d["lousa_grid_slot_minutes"] == 60
        assert d["lousa_grid_max_per_slot"] == 2

    def test_get_settings_persists_grid(self, admin_h):
        r = requests.get(f"{API}/settings", headers=admin_h, timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d["lousa_grid_start_hour"] == 8
        assert d["lousa_grid_end_hour"] == 18
        assert d["lousa_grid_slot_minutes"] == 60
        assert d["lousa_grid_max_per_slot"] == 2


# ----------------------- 2. GET /api/lousa/grid format ------------
class TestGridFormat:
    def test_grid_returns_fixed_slots_block(self, admin_h, gestor_h):
        # garante settings
        requests.put(
            f"{API}/settings",
            json={
                "lousa_grid_start_hour": 8,
                "lousa_grid_end_hour": 18,
                "lousa_grid_slot_minutes": 60,
                "lousa_grid_max_per_slot": 2,
            },
            headers=admin_h,
            timeout=20,
        )
        r = requests.get(f"{API}/lousa/grid", headers=gestor_h, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "grid" in body, body
        g = body["grid"]
        assert g["start_hour"] == 8
        assert g["end_hour"] == 18
        assert g["slot_minutes"] == 60
        assert g["max_per_slot"] == 2
        assert isinstance(g["slots"], list)
        # 8..17 = 10 slots
        assert g["slots"] == [
            "08:00", "09:00", "10:00", "11:00", "12:00",
            "13:00", "14:00", "15:00", "16:00", "17:00",
        ]

    def test_each_column_has_slots_and_unscheduled(self, admin_h, gestor_h, collaborator_id):
        # garante existência de coluna do colaborador
        _create_ticket(admin_h, collaborator_id)
        r = requests.get(f"{API}/lousa/grid", headers=gestor_h, timeout=30)
        body = r.json()
        col = next((c for c in body["columns"] if c["collaborator"]["id"] == collaborator_id), None)
        assert col is not None
        assert "slots" in col and isinstance(col["slots"], list)
        assert "unscheduled" in col and isinstance(col["unscheduled"], list)
        # cada slot tem 'slot', 'tickets', 'full'
        assert all({"slot", "tickets", "full"} <= set(s.keys()) for s in col["slots"])
        assert len(col["slots"]) == len(body["grid"]["slots"])


# ----------------------- 3. Slot assignment ----------------------
class TestSlotAssignment:
    def test_horario_0930_falls_in_0900(self, admin_h, gestor_h, collaborator_id):
        t = _create_ticket(
            admin_h, collaborator_id,
            scheduled_time="2026-05-09T09:30:00",
            priority="horario",
        )
        r = requests.get(f"{API}/lousa/grid", headers=gestor_h, timeout=30)
        col = next(c for c in r.json()["columns"] if c["collaborator"]["id"] == collaborator_id)
        slot_0900 = next(s for s in col["slots"] if s["slot"] == "09:00")
        ids = [x["id"] for x in slot_0900["tickets"]]
        assert t["id"] in ids, f"ticket esperado no slot 09:00, slots={col['slots']}"

    def test_normal_without_scheduled_falls_in_unscheduled(self, admin_h, gestor_h, collaborator_id):
        t = _create_ticket(admin_h, collaborator_id)  # priority=normal, sem scheduled
        r = requests.get(f"{API}/lousa/grid", headers=gestor_h, timeout=30)
        col = next(c for c in r.json()["columns"] if c["collaborator"]["id"] == collaborator_id)
        ids = [x["id"] for x in col["unscheduled"]]
        assert t["id"] in ids


# ----------------------- 4. Transfer com new_grid_slot ------------
class TestTransferGridSlot:
    def test_transfer_only_grid_slot_keeps_collaborator(self, admin_h, gestor_h, collaborator_id):
        t = _create_ticket(admin_h, collaborator_id)
        r = requests.post(
            f"{API}/lousa/tickets/{t['id']}/transfer",
            json={"new_grid_slot": "10:00"},
            headers=gestor_h,
            timeout=20,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["grid_slot"] == "10:00"
        assert d["assigned_collaborator_id"] == collaborator_id

        # Verifica via GET grid: ticket aparece em 10:00
        g = requests.get(f"{API}/lousa/grid", headers=gestor_h, timeout=30).json()
        col = next(c for c in g["columns"] if c["collaborator"]["id"] == collaborator_id)
        slot_1000 = next(s for s in col["slots"] if s["slot"] == "10:00")
        assert t["id"] in [x["id"] for x in slot_1000["tickets"]]

    def test_transfer_with_collaborator_and_slot(self, admin_h, gestor_h, collaborator_id):
        # cria 2º colaborador destino
        payload = {
            "name": f"TEST_I4_DEST_{uuid.uuid4().hex[:5]}",
            "cpf": f"{uuid.uuid4().int % 10**11:011d}",
            "email": f"dest_i4_{uuid.uuid4().hex[:6]}@example.com",
            "phone": "11999999999",
            "is_test_mode": True,
        }
        r = requests.post(f"{API}/collaborators", json=payload, headers=admin_h, timeout=20)
        dest_cid = r.json()["id"]
        try:
            t = _create_ticket(admin_h, collaborator_id)
            r2 = requests.post(
                f"{API}/lousa/tickets/{t['id']}/transfer",
                json={"new_collaborator_id": dest_cid, "new_grid_slot": "11:00"},
                headers=gestor_h,
                timeout=20,
            )
            assert r2.status_code == 200, r2.text
            d = r2.json()
            assert d["assigned_collaborator_id"] == dest_cid
            assert d["grid_slot"] == "11:00"
        finally:
            requests.delete(f"{API}/collaborators/{dest_cid}", headers=admin_h, timeout=20)

    def test_slot_full_returns_409(self, admin_h, gestor_h, collaborator_id):
        # Reset settings p/ max_per_slot=2
        requests.put(
            f"{API}/settings",
            json={"lousa_grid_max_per_slot": 2},
            headers=admin_h, timeout=20,
        )
        # Cria 3 tickets normais
        t1 = _create_ticket(admin_h, collaborator_id)
        t2 = _create_ticket(admin_h, collaborator_id)
        t3 = _create_ticket(admin_h, collaborator_id)
        slot = "14:00"
        # mover 2 para o slot deve OK
        r1 = requests.post(
            f"{API}/lousa/tickets/{t1['id']}/transfer",
            json={"new_grid_slot": slot}, headers=gestor_h, timeout=20,
        )
        assert r1.status_code == 200, r1.text
        r2 = requests.post(
            f"{API}/lousa/tickets/{t2['id']}/transfer",
            json={"new_grid_slot": slot}, headers=gestor_h, timeout=20,
        )
        assert r2.status_code == 200, r2.text
        # 3º deve dar 409
        r3 = requests.post(
            f"{API}/lousa/tickets/{t3['id']}/transfer",
            json={"new_grid_slot": slot}, headers=gestor_h, timeout=20,
        )
        assert r3.status_code == 409, r3.text
        msg = r3.json().get("detail", "")
        assert "cheio" in msg.lower() or "2/2" in msg, msg

    def test_sem_horario_no_capacity_limit(self, admin_h, gestor_h, collaborator_id):
        # Cria 5 tickets, todos para sem_horario — não deve dar 409
        ids = [_create_ticket(admin_h, collaborator_id)["id"] for _ in range(3)]
        for tid in ids:
            r = requests.post(
                f"{API}/lousa/tickets/{tid}/transfer",
                json={"new_grid_slot": "sem_horario"},
                headers=gestor_h, timeout=20,
            )
            assert r.status_code == 200, f"sem_horario não deve ter limite, status={r.status_code} body={r.text}"


# ----------------------- 5. slot_minutes=30 ----------------------
class TestSlotMinutes30:
    def test_30min_slots_returns_20_slots(self, admin_h, gestor_h):
        r = requests.put(
            f"{API}/settings",
            json={
                "lousa_grid_start_hour": 8,
                "lousa_grid_end_hour": 18,
                "lousa_grid_slot_minutes": 30,
                "lousa_grid_max_per_slot": 2,
            },
            headers=admin_h, timeout=20,
        )
        assert r.status_code == 200
        body = requests.get(f"{API}/lousa/grid", headers=gestor_h, timeout=30).json()
        slots = body["grid"]["slots"]
        assert len(slots) == 20, f"esperado 20 slots, got {len(slots)}: {slots}"
        assert slots[0] == "08:00"
        assert slots[1] == "08:30"
        assert slots[-1] == "17:30"
        # restore
        requests.put(
            f"{API}/settings",
            json={"lousa_grid_slot_minutes": 60},
            headers=admin_h, timeout=20,
        )


# ----------------------- 6. Regression --------------------------
class TestRegression:
    def test_lousa_logs_endpoint(self, gestor_h):
        r = requests.get(f"{API}/lousa/logs?limit=10", headers=gestor_h, timeout=20)
        assert r.status_code == 200
        assert "items" in r.json()

    def test_admin_close_still_works(self, admin_h, gestor_h, collaborator_id):
        t = _create_ticket(admin_h, collaborator_id)
        r = requests.post(
            f"{API}/lousa/tickets/{t['id']}/admin-close",
            json={"action": "encerrar", "notes": "regression iter4"},
            headers=gestor_h, timeout=20,
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "encerrada"

    def test_lousa_all_works(self, gestor_h):
        r = requests.get(f"{API}/lousa/all", headers=gestor_h, timeout=20)
        assert r.status_code == 200
        assert "tickets" in r.json()
