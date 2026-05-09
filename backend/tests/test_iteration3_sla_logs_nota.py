"""Iteration 3 backend tests:
- Settings: novos campos sla_*, sla_warning_pct, sla_blink_when_overdue, nota_fence_radius_m
- /api/lousa/grid: groups por slot de horário + sla por bolha
- Logs de auditoria (criada/aberta/finalizada/encerrar/transferida) em /api/lousa/logs
- SLA overdue/warning/n/a (manipula opened_at via mongo direto)
- Praça especial 'NOTA' → cerca dinâmica baseada na bolha aberta/pendente do colab
- Regression iter1/iter2: login, /api/lousa/all, /api/lousa/me, /api/notifications
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

# Load REACT_APP_BACKEND_URL from frontend/.env
if not os.environ.get("REACT_APP_BACKEND_URL"):
    try:
        with open("/app/frontend/.env") as _f:
            for _ln in _f:
                if _ln.startswith("REACT_APP_BACKEND_URL="):
                    os.environ["REACT_APP_BACKEND_URL"] = _ln.split("=", 1)[1].strip()
                    break
    except Exception:
        pass

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@empresa.com", "password": "123456"}
GESTOR = {"email": "gestor@empresa.com", "password": "123456"}
COLAB = {"email": "colaborador@empresa.com", "password": "123456"}
DEMO_CID = "col-demo-001"
DEMO_COMPANY_ID = "co-demo"

TINY_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


@pytest.fixture(scope="module")
def mongo_db():
    cli = MongoClient(MONGO_URL)
    yield cli[DB_NAME]
    cli.close()


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


def _login(s, creds):
    r = s.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login {creds['email']} -> {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token(s):
    return _login(s, ADMIN)


@pytest.fixture(scope="module")
def gestor_token(s):
    return _login(s, GESTOR)


@pytest.fixture(scope="module")
def colab_token(s):
    return _login(s, COLAB)


@pytest.fixture(scope="module")
def gestor_h(gestor_token):
    return {"Authorization": f"Bearer {gestor_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# ---------------------- Regression: logins ----------------------
def test_regression_login_admin(admin_token):
    assert admin_token

def test_regression_login_gestor(gestor_token):
    assert gestor_token


# ---------------------- 1. Settings - novos campos ----------------------
def test_settings_has_new_sla_fields(s, gestor_h):
    r = s.get(f"{API}/settings", headers=gestor_h, timeout=10)
    assert r.status_code == 200, r.text
    d = r.json()
    # default values
    assert d.get("sla_reparo_minutes") == 60
    assert d.get("sla_instalacao_minutes") == 120
    assert d.get("sla_retirada_minutes") == 30
    assert d.get("sla_warning_pct") == 80
    assert d.get("sla_blink_when_overdue") is True
    assert d.get("nota_fence_radius_m") == 80


def test_settings_put_updates_new_fields(s, admin_h):
    payload = {
        "sla_reparo_minutes": 45,
        "sla_instalacao_minutes": 100,
        "sla_retirada_minutes": 25,
        "sla_warning_pct": 75,
        "sla_blink_when_overdue": False,
        "nota_fence_radius_m": 120,
    }
    r = s.put(f"{API}/settings", headers=admin_h, json=payload, timeout=10)
    assert r.status_code == 200, r.text

    r2 = s.get(f"{API}/settings", headers=admin_h, timeout=10)
    d = r2.json()
    assert d["sla_reparo_minutes"] == 45
    assert d["sla_instalacao_minutes"] == 100
    assert d["sla_retirada_minutes"] == 25
    assert d["sla_warning_pct"] == 75
    assert d["sla_blink_when_overdue"] is False
    assert d["nota_fence_radius_m"] == 120

    # restore defaults for next tests
    restore = {
        "sla_reparo_minutes": 60, "sla_instalacao_minutes": 120,
        "sla_retirada_minutes": 30, "sla_warning_pct": 80,
        "sla_blink_when_overdue": True, "nota_fence_radius_m": 80,
    }
    s.put(f"{API}/settings", headers=admin_h, json=restore, timeout=10)


# ---------------------- 2. Setup: collab + tickets ----------------------
@pytest.fixture(scope="module")
def collab_a(s, gestor_h):
    suf = uuid.uuid4().hex[:6]
    r = s.post(f"{API}/collaborators", headers=gestor_h, json={
        "name": f"TEST_I3_A {suf}", "cpf": f"311.{suf[:3]}.{suf[3:6]}-31",
        "email": f"TEST_i3a_{suf}@example.com", "phone": "+5511311110000",
        "is_test_mode": True,
    }, timeout=15).json()
    yield r
    try:
        s.delete(f"{API}/collaborators/{r['id']}", headers=gestor_h, timeout=10)
    except Exception:
        pass


@pytest.fixture(scope="module")
def collab_b(s, gestor_h):
    suf = uuid.uuid4().hex[:6]
    r = s.post(f"{API}/collaborators", headers=gestor_h, json={
        "name": f"TEST_I3_B {suf}", "cpf": f"322.{suf[:3]}.{suf[3:6]}-32",
        "email": f"TEST_i3b_{suf}@example.com", "phone": "+5511322220000",
        "is_test_mode": True,
    }, timeout=15).json()
    yield r
    try:
        s.delete(f"{API}/collaborators/{r['id']}", headers=gestor_h, timeout=10)
    except Exception:
        pass


def _create_ticket(s, gestor_h, cid, *, type_="reparo", priority="normal",
                   scheduled_time=None, client_name=None):
    body = {
        "client_name": client_name or f"TEST_CLI_{uuid.uuid4().hex[:6]}",
        "address": "Av. Paulista 1000, São Paulo",
        "neighborhood": "Bela Vista", "phone": "+551130001111",
        "relato": "teste i3",
        "type": type_, "priority": priority,
        "assigned_collaborator_id": cid,
    }
    if scheduled_time:
        body["scheduled_time"] = scheduled_time
    r = s.post(f"{API}/lousa/tickets", headers=gestor_h, json=body, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------- 3. Grid: groups + sla ----------------------
def test_grid_returns_groups_and_sla(s, gestor_h, collab_a):
    cid = collab_a["id"]
    # Cria 1 ticket com horário 09:00 e 1 sem horário
    tk_h = _create_ticket(s, gestor_h, cid, type_="reparo", priority="horario",
                          scheduled_time="2026-05-09T09:00:00")
    tk_n = _create_ticket(s, gestor_h, cid, type_="reparo", priority="normal")

    r = s.get(f"{API}/lousa/grid", headers=gestor_h, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "sla_blink_when_overdue" in body
    assert "sla_warning_pct" in body
    assert "sla_map" in body
    cols = [c for c in body["columns"] if c["collaborator"]["id"] == cid]
    assert cols, "coluna do colab não encontrada no grid"
    col = cols[0]
    assert "groups" in col and isinstance(col["groups"], list)
    # Cada ticket tem sla
    for t in col["tickets"]:
        assert "sla" in t and "sla_minutes" in t["sla"] and "status" in t["sla"]
        assert "time_slot" in t

    slots = {g["slot"]: g for g in col["groups"]}
    # Slot manha_09 deve existir e ter label correto
    assert "manha_09" in slots, f"slots={list(slots.keys())}"
    assert "Manhã" in slots["manha_09"]["label"]
    assert "09" in slots["manha_09"]["label"]
    assert any(t["id"] == tk_h["id"] for t in slots["manha_09"]["tickets"])

    # Slot sem_horario com label "📋 Sem horário marcado"
    assert "sem_horario" in slots
    assert "Sem horário" in slots["sem_horario"]["label"]
    assert any(t["id"] == tk_n["id"] for t in slots["sem_horario"]["tickets"])

    # cleanup tickets
    s.delete(f"{API}/lousa/tickets/{tk_h['id']}", headers=gestor_h, timeout=10)
    s.delete(f"{API}/lousa/tickets/{tk_n['id']}", headers=gestor_h, timeout=10)


# ---------------------- 4. SLA: overdue / warning / n/a ----------------------
def test_sla_pending_uses_queue_mode_when_no_schedule(s, gestor_h, collab_a):
    """Bolha 'pendente' sem scheduled_time → SLA mode='queue', status='ok' (recém-criada).

    Regra: pendentes/aguardando agora também rodam SLA usando created_at + grace period
    (default 60min). Assim o gestor vê bolhas paradas demais piscando, igual às em execução.
    """
    cid = collab_a["id"]
    tk = _create_ticket(s, gestor_h, cid, type_="reparo", priority="normal")
    try:
        r = s.get(f"{API}/lousa/grid", headers=gestor_h, timeout=15)
        cols = [c for c in r.json()["columns"] if c["collaborator"]["id"] == cid]
        t = next(t for t in cols[0]["tickets"] if t["id"] == tk["id"])
        assert t["sla"]["status"] == "ok"
        assert t["sla"]["mode"] == "queue"
        # elapsed_minutes deve ser número (não None) já que agora há referência
        assert t["sla"]["elapsed_minutes"] is not None
    finally:
        s.delete(f"{API}/lousa/tickets/{tk['id']}", headers=gestor_h, timeout=10)


def test_sla_status_overdue_when_opened_long_ago(s, gestor_h, mongo_db, collab_a):
    """opened_at há 200min com sla=60 → status='overdue', pct>=100."""
    cid = collab_a["id"]
    tk = _create_ticket(s, gestor_h, cid, type_="reparo", priority="normal")
    try:
        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=200)).isoformat()
        mongo_db.tickets.update_one(
            {"id": tk["id"]},
            {"$set": {"status": "aberta", "opened_at": old_ts}},
        )
        r = s.get(f"{API}/lousa/grid", headers=gestor_h, timeout=15)
        cols = [c for c in r.json()["columns"] if c["collaborator"]["id"] == cid]
        t = next(t for t in cols[0]["tickets"] if t["id"] == tk["id"])
        assert t["sla"]["status"] == "overdue", f"sla={t['sla']}"
        assert t["sla"]["pct"] >= 100
        assert t["sla"]["elapsed_minutes"] >= 100
    finally:
        s.delete(f"{API}/lousa/tickets/{tk['id']}", headers=gestor_h, timeout=10)


def test_sla_status_warning_when_above_pct(s, gestor_h, mongo_db, collab_a):
    """opened_at há 50min com sla=60 (warning_pct=80% → 48min) → status='warning'."""
    cid = collab_a["id"]
    tk = _create_ticket(s, gestor_h, cid, type_="reparo", priority="normal")
    try:
        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=50)).isoformat()
        mongo_db.tickets.update_one(
            {"id": tk["id"]},
            {"$set": {"status": "aberta", "opened_at": old_ts}},
        )
        r = s.get(f"{API}/lousa/grid", headers=gestor_h, timeout=15)
        cols = [c for c in r.json()["columns"] if c["collaborator"]["id"] == cid]
        t = next(t for t in cols[0]["tickets"] if t["id"] == tk["id"])
        assert t["sla"]["status"] == "warning", f"sla={t['sla']}"
        assert 80 <= t["sla"]["pct"] < 100
    finally:
        s.delete(f"{API}/lousa/tickets/{tk['id']}", headers=gestor_h, timeout=10)


# ---------------------- 5. Logs de auditoria ----------------------
def test_log_action_criada(s, gestor_h, collab_a):
    cid = collab_a["id"]
    tk = _create_ticket(s, gestor_h, cid, type_="reparo", priority="normal",
                        client_name=f"TEST_LOG_{uuid.uuid4().hex[:5]}")
    try:
        r = s.get(f"{API}/lousa/logs?ticket_id={tk['id']}", headers=gestor_h, timeout=10)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        actions = [it["action"] for it in items]
        assert "criada" in actions, f"actions={actions}"
        criada = next(it for it in items if it["action"] == "criada")
        assert criada["ticket_id"] == tk["id"]
        assert criada["actor_role"] in ("gestor", "administrador")
        assert "at" in criada
    finally:
        s.delete(f"{API}/lousa/tickets/{tk['id']}", headers=gestor_h, timeout=10)


def test_log_action_aberta_via_public(s, gestor_h, collab_a):
    """POST /lousa/public/tickets/{id}/open requer Entrada hoje. collab_a é is_test_mode."""
    cid = collab_a["id"]
    # bate Entrada
    bare = requests.Session()
    bare.headers.update({"Content-Type": "application/json"})
    bare.post(f"{API}/clock-records", json={
        "collaborator_id": cid, "type": "Entrada",
        "selfie_base64": f"data:image/png;base64,{TINY_PNG}",
        "lat": 0.0, "lng": 0.0,
    }, timeout=60)
    tk = _create_ticket(s, gestor_h, cid, type_="reparo", priority="normal")
    try:
        r = bare.post(f"{API}/lousa/public/tickets/{tk['id']}/open",
                      json={"collaborator_id": cid}, timeout=20)
        assert r.status_code == 200, r.text
        logs = s.get(f"{API}/lousa/logs?ticket_id={tk['id']}", headers=gestor_h, timeout=10).json()["items"]
        actions = [it["action"] for it in logs]
        assert "aberta" in actions, f"actions={actions}"
        ab = next(it for it in logs if it["action"] == "aberta")
        assert ab["actor_role"] == "colaborador"
    finally:
        s.delete(f"{API}/lousa/tickets/{tk['id']}", headers=gestor_h, timeout=10)


def test_log_action_finalizada(s, gestor_h, collab_a):
    cid = collab_a["id"]
    bare = requests.Session()
    bare.headers.update({"Content-Type": "application/json"})
    bare.post(f"{API}/clock-records", json={
        "collaborator_id": cid, "type": "Entrada",
        "selfie_base64": f"data:image/png;base64,{TINY_PNG}",
        "lat": 0.0, "lng": 0.0,
    }, timeout=60)
    tk = _create_ticket(s, gestor_h, cid, type_="reparo", priority="normal")
    try:
        r = bare.post(f"{API}/lousa/public/tickets/{tk['id']}/open",
                      json={"collaborator_id": cid}, timeout=20)
        assert r.status_code == 200, r.text
        fin_payload = {
            "collaborator_id": cid,
            "completion_data": {
                "sinal": -25.0, "qtd_drop": 0, "esticadores": 0,
                "conectores_fast": 0, "cabo_rede": 0.0, "conectores_rede": 0,
                "fotos": [], "observacoes": "ok",
            },
            "latitude": 0.0, "longitude": 0.0, "outcome": "sucesso",
        }
        r = bare.post(f"{API}/lousa/public/tickets/{tk['id']}/finalize",
                      json=fin_payload, timeout=20)
        assert r.status_code == 200, r.text
        logs = s.get(f"{API}/lousa/logs?ticket_id={tk['id']}", headers=gestor_h, timeout=10).json()["items"]
        actions = [it["action"] for it in logs]
        assert "finalizada" in actions
    finally:
        s.delete(f"{API}/lousa/tickets/{tk['id']}", headers=gestor_h, timeout=10)


def test_log_action_encerrar(s, gestor_h, collab_a):
    cid = collab_a["id"]
    tk = _create_ticket(s, gestor_h, cid, type_="reparo", priority="normal")
    try:
        r = s.post(f"{API}/lousa/tickets/{tk['id']}/admin-close",
                   headers=gestor_h, json={"action": "encerrar", "notes": "bug"},
                   timeout=15)
        assert r.status_code == 200, r.text
        logs = s.get(f"{API}/lousa/logs?ticket_id={tk['id']}", headers=gestor_h, timeout=10).json()["items"]
        actions = [it["action"] for it in logs]
        assert "encerrar" in actions, f"actions={actions}"
    finally:
        s.delete(f"{API}/lousa/tickets/{tk['id']}", headers=gestor_h, timeout=10)


def test_log_action_transferida_with_origin_destination(s, gestor_h, collab_a, collab_b):
    cid_a = collab_a["id"]
    cid_b = collab_b["id"]
    tk = _create_ticket(s, gestor_h, cid_a, type_="reparo", priority="normal")
    try:
        r = s.post(f"{API}/lousa/tickets/{tk['id']}/transfer",
                   headers=gestor_h, json={"new_collaborator_id": cid_b}, timeout=15)
        assert r.status_code == 200, r.text
        logs = s.get(f"{API}/lousa/logs?ticket_id={tk['id']}", headers=gestor_h, timeout=10).json()["items"]
        tr = [it for it in logs if it["action"] == "transferida"]
        assert tr, f"actions={[i['action'] for i in logs]}"
        details = tr[0].get("details") or ""
        assert "→" in details or "->" in details or "Para" in details, f"details={details}"
    finally:
        s.delete(f"{API}/lousa/tickets/{tk['id']}", headers=gestor_h, timeout=10)


def test_logs_endpoint_sorted_desc(s, gestor_h):
    r = s.get(f"{API}/lousa/logs?limit=20", headers=gestor_h, timeout=10)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    if len(items) >= 2:
        assert items[0]["at"] >= items[1]["at"], "logs não estão em ordem desc por 'at'"


# ---------------------- 6. Praça NOTA ----------------------
def test_collaborator_accepts_praca_id_NOTA(s, gestor_h, collab_a):
    cid = collab_a["id"]
    cur = s.get(f"{API}/collaborators/{cid}", timeout=10).json()
    upd = {
        "name": cur["name"], "cpf": cur["cpf"], "email": cur["email"],
        "phone": cur["phone"], "is_test_mode": True,
        "praca_id": "NOTA",
    }
    r = s.put(f"{API}/collaborators/{cid}", headers=gestor_h, json=upd, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("praca_id") == "NOTA", f"praca_id não persistiu: {body}"


def test_clock_record_NOTA_dynamic_fence_inside(s, gestor_h, admin_h, mongo_db):
    """Colab praca_id=NOTA + is_test_mode (para passar face IA com tiny PNG),
    com bolha aberta com lat/lng setados → audit deve mencionar cerca dinâmica NOTA.
    Nota: is_test_mode bypassa cerca de qualquer modo, mas a cerca dinâmica NOTA é
    computada e logada no audit antes do bypass — comprovando o fluxo."""
    suf = uuid.uuid4().hex[:6]
    cr = s.post(f"{API}/collaborators", headers=gestor_h, json={
        "name": f"TEST_NOTA {suf}", "cpf": f"333.{suf[:3]}.{suf[3:6]}-33",
        "email": f"TEST_nota_{suf}@example.com", "phone": "+5511333330000",
        "is_test_mode": True, "praca_id": "NOTA",
    }, timeout=15)
    assert cr.status_code == 200, cr.text
    cid = cr.json()["id"]
    mongo_db.collaborators.update_one({"id": cid}, {"$set": {"praca_id": "NOTA"}})

    tk = _create_ticket(s, gestor_h, cid, type_="reparo", priority="normal")
    target_lat, target_lng = -23.5, -46.6
    mongo_db.tickets.update_one(
        {"id": tk["id"]},
        {"$set": {
            "status": "aberta",
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "client_snapshot.latitude": target_lat,
            "client_snapshot.longitude": target_lng,
        }},
    )
    s.put(f"{API}/settings", headers=admin_h, json={"nota_fence_radius_m": 80}, timeout=10)

    try:
        bare = requests.Session()
        bare.headers.update({"Content-Type": "application/json"})
        r = bare.post(f"{API}/clock-records", json={
            "collaborator_id": cid, "type": "Entrada",
            "selfie_base64": f"data:image/png;base64,{TINY_PNG}",
            "lat": target_lat, "lng": target_lng,
        }, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "Válido", f"esperava Válido, got {body['status']} ({body.get('internal_reason')})"
        # audit deve mencionar NOTA / cerca dinâmica
        audit_str = str(body.get("audit") or "")
        assert ("praca=NOTA" in audit_str) or ("cerca dinâmica" in audit_str), \
            f"audit não menciona NOTA: {audit_str[:400]}"
    finally:
        s.delete(f"{API}/lousa/tickets/{tk['id']}", headers=gestor_h, timeout=10)
        s.delete(f"{API}/collaborators/{cid}", headers=gestor_h, timeout=10)


def test_clock_record_NOTA_blocked_when_no_open_ticket(s, gestor_h, mongo_db):
    """Colab NOTA sem bolha aberta nem pendente com lat/lng → Bloqueado."""
    suf = uuid.uuid4().hex[:6]
    cr = s.post(f"{API}/collaborators", headers=gestor_h, json={
        "name": f"TEST_NOTA2 {suf}", "cpf": f"444.{suf[:3]}.{suf[3:6]}-44",
        "email": f"TEST_nota2_{suf}@example.com", "phone": "+5511444440000",
        "is_test_mode": False, "praca_id": "NOTA",
    }, timeout=15)
    assert cr.status_code == 200, cr.text
    cid = cr.json()["id"]
    mongo_db.collaborators.update_one({"id": cid}, {"$set": {"praca_id": "NOTA"}})
    # Garantir que NÃO há tickets para ele com lat/lng
    mongo_db.tickets.delete_many({"assigned_collaborator_id": cid})

    try:
        bare = requests.Session()
        bare.headers.update({"Content-Type": "application/json"})
        r = bare.post(f"{API}/clock-records", json={
            "collaborator_id": cid, "type": "Entrada",
            "selfie_base64": f"data:image/png;base64,{TINY_PNG}",
            "lat": -23.5, "lng": -46.6,
        }, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "Bloqueado", f"esperava Bloqueado, got {body['status']}"
    finally:
        s.delete(f"{API}/collaborators/{cid}", headers=gestor_h, timeout=10)


# ---------------------- 7. Regression iter1/iter2 ----------------------
def test_regression_lousa_all(s, gestor_h):
    r = s.get(f"{API}/lousa/all", headers=gestor_h, timeout=15)
    assert r.status_code == 200
    assert "tickets" in r.json()


def test_regression_notifications(s, gestor_h):
    r = s.get(f"{API}/notifications", headers=gestor_h, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and "unread_count" in body


def test_regression_lousa_me_for_colab(s, colab_token):
    r = s.get(f"{API}/lousa/me",
              headers={"Authorization": f"Bearer {colab_token}"}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "tickets" in body
    assert "clock_state" in body
