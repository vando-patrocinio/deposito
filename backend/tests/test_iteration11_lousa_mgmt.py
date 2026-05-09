"""Iter11 — Management KPIs/Insights, Reschedule modal payload, mobile drop on cancel."""
import os
import uuid
import requests
import pytest
from pathlib import Path


def _load_backend_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if url:
        return url.rstrip("/")
    env_path = Path("/app/frontend/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not set")


BASE_URL = _load_backend_url()
API = f"{BASE_URL}/api"

GESTOR = {"email": "gestor@empresa.com", "password": "123456"}
ADMIN = {"email": "admin@empresa.com", "password": "123456"}
DEMO_CID = "col-demo-001"


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def gestor_token():
    r = requests.post(f"{API}/auth/login", json=GESTOR, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json=ADMIN, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _create_pending_ticket(tok, label="iter11_test"):
    payload = {
        "client_name": f"TEST_{label}_{uuid.uuid4().hex[:6]}",
        "address": "Rua Teste 123",
        "neighborhood": "Centro",
        "phone": "11999999999",
        "relato": "Teste automatizado",
        "type": "instalacao",
        "priority": "normal",
        "assigned_collaborator_id": DEMO_CID,
    }
    r = requests.post(f"{API}/lousa/tickets", json=payload, headers=_h(tok), timeout=30)
    assert r.status_code in (200, 201), f"Create failed: {r.status_code} {r.text}"
    return r.json()


# ---------- 1. management-kpis shape ----------
def test_management_kpis_shape(gestor_token):
    r = requests.get(f"{API}/lousa/management-kpis?days=30", headers=_h(gestor_token), timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    # by_action keys
    assert "by_action" in data
    by_action = data["by_action"]
    for key in ["trabalhadas_pela_gestao", "encerradas", "reagendadas",
                "canceladas", "editadas", "transferidas"]:
        assert key in by_action, f"by_action missing {key}: {by_action}"
        assert isinstance(by_action[key], int)
    # top-level fields
    for key in ["total_management_actions", "by_actor", "top_cancel_reasons",
                "top_reschedule_reasons", "cancel_by_type", "reschedule_by_type",
                "current_status_counts", "avg_minutes_to_decision", "period_days",
                "computed_at"]:
        assert key in data, f"missing top-level {key}"
    assert isinstance(data["by_actor"], list)
    assert isinstance(data["top_cancel_reasons"], list)
    assert data["period_days"] == 30


# ---------- 2. management-insights ----------
def test_management_insights(gestor_token):
    # LLM ~5-15s, generous timeout
    r = requests.post(f"{API}/lousa/management-insights?days=30",
                      headers=_h(gestor_token), timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "kpis" in data and "insights" in data
    assert "method" in data and data["method"] in ("llm", "fallback")
    assert "computed_at" in data
    ins = data["insights"]
    for key in ["analysis_summary", "red_flags", "recommendations", "priority_action"]:
        assert key in ins, f"insights missing {key}"
    assert isinstance(ins["red_flags"], list)
    assert isinstance(ins["recommendations"], list)


# ---------- 3. reagendar com new_date+new_time ----------
def test_admin_close_reschedule_with_date_time(gestor_token):
    t = _create_pending_ticket(gestor_token, "resched")
    tid = t["id"]
    payload = {
        "action": "reagendar",
        "new_date": "2026-05-15",
        "new_time": "14:30",
        "notes": "Cliente pediu mudar — TEST",
    }
    r = requests.post(f"{API}/lousa/tickets/{tid}/admin-close",
                      json=payload, headers=_h(gestor_token), timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "reagendada"
    assert body["scheduled_time"] == "2026-05-15T14:30:00", f"got {body['scheduled_time']}"
    # GET to verify persistence
    r2 = requests.get(f"{API}/lousa/tickets/{tid}", headers=_h(gestor_token), timeout=15)
    if r2.status_code == 200:
        assert r2.json()["scheduled_time"] == "2026-05-15T14:30:00"


# ---------- 4. notification ao reagendar/cancelar ----------
def test_admin_close_creates_notification(gestor_token):
    t = _create_pending_ticket(gestor_token, "notif")
    tid = t["id"]
    payload = {"action": "cancelar", "notes": "TEST_iter11_notif_cancel"}
    r = requests.post(f"{API}/lousa/tickets/{tid}/admin-close",
                      json=payload, headers=_h(gestor_token), timeout=30)
    assert r.status_code == 200
    # GET notifications and check at least one references this ticket_id
    r2 = requests.get(f"{API}/notifications", headers=_h(gestor_token), timeout=20)
    assert r2.status_code == 200, r2.text
    notes = r2.json()
    if isinstance(notes, dict) and "items" in notes:
        notes = notes["items"]
    assert isinstance(notes, list)
    matched = [n for n in notes if (n.get("ticket_id") == tid)]
    assert matched, f"No notification found for ticket {tid}"
    # type contains 'cancelar' OR 'admin'
    types = [m.get("type", "") for m in matched]
    assert any("cancel" in t for t in types), f"Notification types: {types}"


# ---------- 5. by-collaborator público — cancelado some da lousa ----------
def test_canceled_ticket_disappears_from_mobile(gestor_token):
    t = _create_pending_ticket(gestor_token, "drop")
    tid = t["id"]
    # cancela
    r = requests.post(f"{API}/lousa/tickets/{tid}/admin-close",
                      json={"action": "cancelar", "notes": "TEST_iter11_drop"},
                      headers=_h(gestor_token), timeout=30)
    assert r.status_code == 200
    # PUBLIC endpoint, no auth
    r2 = requests.get(f"{API}/lousa/by-collaborator/{DEMO_CID}", timeout=20)
    assert r2.status_code == 200, r2.text
    body = r2.json()
    tids = [x["id"] for x in body.get("tickets", [])]
    assert tid not in tids, f"Canceled ticket {tid} still in mobile lousa: {tids}"


def test_rescheduled_ticket_disappears_from_mobile(gestor_token):
    t = _create_pending_ticket(gestor_token, "drop_resch")
    tid = t["id"]
    r = requests.post(f"{API}/lousa/tickets/{tid}/admin-close",
                      json={"action": "reagendar",
                            "new_date": "2026-06-10",
                            "new_time": "09:00",
                            "notes": "TEST_iter11_drop_resch"},
                      headers=_h(gestor_token), timeout=30)
    assert r.status_code == 200
    r2 = requests.get(f"{API}/lousa/by-collaborator/{DEMO_CID}", timeout=20)
    assert r2.status_code == 200
    tids = [x["id"] for x in r2.json().get("tickets", [])]
    assert tid not in tids, f"Rescheduled ticket {tid} still in mobile lousa"


# ---------- 6. admin-open log='aberta_admin' ----------
def test_admin_open_logs_aberta_admin(gestor_token):
    t = _create_pending_ticket(gestor_token, "openlog")
    tid = t["id"]
    r = requests.post(f"{API}/lousa/tickets/{tid}/admin-open",
                      headers=_h(gestor_token), timeout=20)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "aberta"
    r2 = requests.get(f"{API}/lousa/logs?ticket_id={tid}",
                      headers=_h(gestor_token), timeout=15)
    assert r2.status_code == 200, r2.text
    body = r2.json()
    logs = body.get("items", body) if isinstance(body, dict) else body
    actions = [log.get("action") for log in logs]
    assert "aberta_admin" in actions, f"Expected aberta_admin in {actions}"
    assert "aberta" not in actions, f"Should NOT have plain 'aberta' admin log: {actions}"
    # cleanup — cancel
    requests.post(f"{API}/lousa/tickets/{tid}/admin-close",
                  json={"action": "cancelar", "notes": "cleanup"},
                  headers=_h(gestor_token), timeout=15)


# ---------- 7. admin-close requires gestor role (sanity) ----------
def test_admin_close_requires_auth():
    r = requests.post(f"{API}/lousa/tickets/fake-id/admin-close",
                      json={"action": "cancelar"}, timeout=15)
    assert r.status_code in (401, 403)
