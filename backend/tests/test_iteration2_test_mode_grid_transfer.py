"""Iteration 2 tests:
- is_test_mode flag on Collaborator (create + update)
- POST /api/clock-records bypasses cerca/face when collab is_test_mode (no token)
- /api/lousa/by-collaborator/{cid} → needs_clock_in flag (before/after Entrada)
- /api/lousa/grid → kanban columns grouped by technician with is_test_mode
- POST /api/lousa/tickets/{tid}/transfer → drag-drop between technicians + 404/400 cases
- Regression: login admin/gestor/colaborador, /api/lousa/all, /api/notifications
"""
import os
import uuid

import pytest
import requests

# Load REACT_APP_BACKEND_URL from frontend/.env if not already set
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

TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


# ---------------------- Fixtures ----------------------
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


# ---------------------- Regression: logins (iter1) ----------------------
def test_regression_login_admin(admin_token):
    assert admin_token

def test_regression_login_gestor(gestor_token):
    assert gestor_token

def test_regression_login_colab(colab_token):
    assert colab_token


# ---------------------- 1. Create collab with is_test_mode=true ----------------------
@pytest.fixture(scope="module")
def test_collab(s, gestor_h):
    suffix = uuid.uuid4().hex[:6]
    payload = {
        "name": f"TEST_TM Colab {suffix}",
        "cpf": f"999.{suffix[:3]}.{suffix[3:6]}-99",
        "email": f"TEST_tm_{suffix}@example.com",
        "phone": "+5511999990000",
        "role": "Colaborador de Campo",
        "company": "Operação SP",
        "is_test_mode": True,
    }
    r = s.post(f"{API}/collaborators", headers=gestor_h, json=payload, timeout=15)
    assert r.status_code == 200, f"create collab -> {r.status_code} {r.text}"
    body = r.json()
    assert body["is_test_mode"] is True, f"is_test_mode not persisted: {body}"
    yield body
    # cleanup
    try:
        s.delete(f"{API}/collaborators/{body['id']}", headers=gestor_h, timeout=10)
    except Exception:
        pass


def test_create_collab_is_test_mode_persisted(s, test_collab):
    cid = test_collab["id"]
    r = s.get(f"{API}/collaborators/{cid}", timeout=10)
    assert r.status_code == 200
    assert r.json().get("is_test_mode") is True


def test_update_collab_toggle_is_test_mode(s, gestor_h, test_collab):
    cid = test_collab["id"]
    # toggle off
    payload = {
        "name": test_collab["name"],
        "cpf": test_collab["cpf"],
        "email": test_collab["email"],
        "phone": test_collab["phone"],
        "is_test_mode": False,
    }
    r = s.put(f"{API}/collaborators/{cid}", headers=gestor_h, json=payload, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json().get("is_test_mode") is False
    # toggle back on
    payload["is_test_mode"] = True
    r = s.put(f"{API}/collaborators/{cid}", headers=gestor_h, json=payload, timeout=15)
    assert r.status_code == 200
    assert r.json().get("is_test_mode") is True


# ---------------------- 2. Clock-records public bypass ----------------------
def test_clock_record_public_bypass_with_test_mode_collab(s, test_collab):
    """SEM token: collaborator is_test_mode=true → status=Válido + admin_test_mode=true."""
    cid = test_collab["id"]
    payload = {
        "collaborator_id": cid,
        "type": "Entrada",
        "selfie_base64": f"data:image/png;base64,{TINY_PNG_B64}",
        "lat": 99.0,
        "lng": -99.0,
    }
    # Use bare session (no auth) to prove bypass requires no admin token.
    bare = requests.Session()
    bare.headers.update({"Content-Type": "application/json"})
    r = bare.post(f"{API}/clock-records", json=payload, timeout=60)
    assert r.status_code == 200, f"clock public bypass -> {r.status_code} {r.text}"
    body = r.json()
    assert body["status"] == "Válido", f"expected Válido, got {body['status']} ({body.get('public_block_message')})"
    assert body.get("admin_test_mode") is True
    assert body.get("test_actor") == "colaborador_teste"
    assert "Teste admin" in (body.get("geo_status") or ""), f"geo_status={body.get('geo_status')}"


def test_clock_record_blocked_for_normal_collab_with_invalid_coords(s, gestor_h):
    """Cria colab SEM is_test_mode em coordenadas absurdas → status=Bloqueado (cerca exigida)."""
    suffix = uuid.uuid4().hex[:6]
    payload = {
        "name": f"TEST_NORMAL Colab {suffix}",
        "cpf": f"888.{suffix[:3]}.{suffix[3:6]}-88",
        "email": f"TEST_normal_{suffix}@example.com",
        "phone": "+5511888880000",
        "is_test_mode": False,
    }
    r = s.post(f"{API}/collaborators", headers=gestor_h, json=payload, timeout=15)
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    try:
        bare = requests.Session()
        bare.headers.update({"Content-Type": "application/json"})
        clock = {
            "collaborator_id": cid,
            "type": "Entrada",
            "selfie_base64": f"data:image/png;base64,{TINY_PNG_B64}",
            "lat": 99.0,
            "lng": -99.0,
        }
        r2 = bare.post(f"{API}/clock-records", json=clock, timeout=60)
        assert r2.status_code == 200, r2.text
        body = r2.json()
        assert body["status"] == "Bloqueado", f"expected Bloqueado, got {body['status']}"
    finally:
        s.delete(f"{API}/collaborators/{cid}", headers=gestor_h, timeout=10)


# ---------------------- 3. Lousa needs_clock_in flag ----------------------
def test_lousa_by_collaborator_needs_clock_in_true_for_fresh_collab(s, test_collab):
    """Colaborador novo (sem Entrada hoje) → needs_clock_in=true, tickets=[]."""
    # Note: test_clock_record_public_bypass_with_test_mode_collab might have run first
    # creating an Entrada. To stay independent we use a FRESH collab here.
    suffix = uuid.uuid4().hex[:6]
    payload = {
        "name": f"TEST_FRESH {suffix}",
        "cpf": f"777.{suffix[:3]}.{suffix[3:6]}-77",
        "email": f"TEST_fresh_{suffix}@example.com",
        "phone": "+5511777770000",
        "is_test_mode": True,
    }
    gestor_token = _login(s, GESTOR)
    h = {"Authorization": f"Bearer {gestor_token}", "Content-Type": "application/json"}
    r = s.post(f"{API}/collaborators", headers=h, json=payload, timeout=15)
    assert r.status_code == 200
    cid = r.json()["id"]
    try:
        r = s.get(f"{API}/lousa/by-collaborator/{cid}", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body.get("needs_clock_in") is True
        assert body.get("tickets") == []
    finally:
        s.delete(f"{API}/collaborators/{cid}", headers=h, timeout=10)


def test_lousa_by_collaborator_after_entrada_returns_tickets(s):
    """Após Entrada bem-sucedida → needs_clock_in=false. Usa col-demo-001 (tem 5 seed tickets)."""
    # 1) Garantir que col-demo-001 está em is_test_mode (para podermos fazer Entrada sem cerca/face)
    gestor_token = _login(s, GESTOR)
    h = {"Authorization": f"Bearer {gestor_token}", "Content-Type": "application/json"}
    cur = s.get(f"{API}/collaborators/{DEMO_CID}", timeout=10)
    if cur.status_code != 200:
        pytest.skip("col-demo-001 not present")
    cur_data = cur.json()
    upd = {
        "name": cur_data["name"],
        "cpf": cur_data["cpf"],
        "email": cur_data["email"],
        "phone": cur_data["phone"],
        "role": cur_data.get("role", "Colaborador de Campo"),
        "company": cur_data.get("company", "Operação SP"),
        "is_test_mode": True,
    }
    r = s.put(f"{API}/collaborators/{DEMO_CID}", headers=h, json=upd, timeout=15)
    assert r.status_code == 200, r.text

    # 2) Limpar clock-records de hoje do col-demo-001 (marcar Recusado para não contar)
    today = __import__("datetime").date.today().isoformat()
    recs = s.get(f"{API}/clock-records?collaborator_id={DEMO_CID}&date_from={today}&date_to={today}", timeout=10)
    if recs.status_code == 200:
        for rec in recs.json():
            try:
                s.delete(f"{API}/clock-records/{rec['id']}?reason=test_reset", timeout=10)
            except Exception:
                pass

    # 3) Confirma que está em needs_clock_in
    r = s.get(f"{API}/lousa/by-collaborator/{DEMO_CID}", timeout=10)
    assert r.status_code == 200
    assert r.json().get("needs_clock_in") is True, f"after cleanup expected needs_clock_in true, got {r.json()}"

    # 4) Bate Entrada (sem token, bypass via is_test_mode)
    bare = requests.Session()
    bare.headers.update({"Content-Type": "application/json"})
    payload = {
        "collaborator_id": DEMO_CID,
        "type": "Entrada",
        "selfie_base64": f"data:image/png;base64,{TINY_PNG_B64}",
        "lat": 0.0, "lng": 0.0,
    }
    r2 = bare.post(f"{API}/clock-records", json=payload, timeout=60)
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "Válido", r2.json()

    # 5) Agora needs_clock_in=false e tickets >=1 (seed=5)
    r = s.get(f"{API}/lousa/by-collaborator/{DEMO_CID}", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body.get("needs_clock_in") is False
    tickets = body.get("tickets") or []
    assert len(tickets) >= 1, f"expected seed tickets, got {len(tickets)}"


# ---------------------- 4. /api/lousa/grid ----------------------
def test_lousa_grid_returns_columns_by_technician(s, gestor_h):
    r = s.get(f"{API}/lousa/grid", headers=gestor_h, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "columns" in body and isinstance(body["columns"], list)
    assert len(body["columns"]) >= 1
    col = body["columns"][0]
    assert "collaborator" in col and "tickets" in col and "clock_state" in col
    assert "is_test_mode" in col["collaborator"]
    # has_entrada/in_intervalo/ended_day keys present
    cs = col["clock_state"]
    for k in ("has_entrada", "in_intervalo", "ended_day"):
        assert k in cs


def test_lousa_grid_unauthorized_for_colab(s, colab_token):
    r = s.get(
        f"{API}/lousa/grid",
        headers={"Authorization": f"Bearer {colab_token}"},
        timeout=10,
    )
    assert r.status_code == 403, r.text


# ---------------------- 5. Transfer ticket ----------------------
@pytest.fixture(scope="module")
def transfer_setup(s, gestor_h):
    """Cria 2 colaboradores TM e 1 ticket atribuído ao primeiro."""
    suffix = uuid.uuid4().hex[:6]
    a = s.post(f"{API}/collaborators", headers=gestor_h, json={
        "name": f"TEST_T_A {suffix}",
        "cpf": f"111.{suffix[:3]}.{suffix[3:6]}-11",
        "email": f"TEST_a_{suffix}@example.com",
        "phone": "+5511111110000",
        "is_test_mode": True,
    }, timeout=15).json()
    b = s.post(f"{API}/collaborators", headers=gestor_h, json={
        "name": f"TEST_T_B {suffix}",
        "cpf": f"222.{suffix[:3]}.{suffix[3:6]}-22",
        "email": f"TEST_b_{suffix}@example.com",
        "phone": "+5511222220000",
        "is_test_mode": True,
    }, timeout=15).json()
    tk = s.post(f"{API}/lousa/tickets", headers=gestor_h, json={
        "client_name": f"TEST_CLI {suffix}",
        "address": "Av. Paulista 1000, São Paulo",
        "neighborhood": "Bela Vista",
        "phone": "+551133334444",
        "relato": "teste",
        "type": "reparo",
        "priority": "normal",
        "assigned_collaborator_id": a["id"],
    }, timeout=20).json()
    yield {"a": a, "b": b, "ticket": tk}
    try:
        s.delete(f"{API}/lousa/tickets/{tk['id']}", headers=gestor_h, timeout=10)
    except Exception:
        pass
    for x in (a, b):
        try:
            s.delete(f"{API}/collaborators/{x['id']}", headers=gestor_h, timeout=10)
        except Exception:
            pass


def test_transfer_ticket_between_technicians(s, gestor_h, transfer_setup):
    tid = transfer_setup["ticket"]["id"]
    new_cid = transfer_setup["b"]["id"]
    r = s.post(
        f"{API}/lousa/tickets/{tid}/transfer",
        headers=gestor_h,
        json={"new_collaborator_id": new_cid},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assigned_collaborator_id"] == new_cid
    # status is 'pendente' (was 'pendente' originally, stays pendente). Should NOT be 'aberta'
    assert body["status"] in ("pendente", "aguardando_atendimento")


def test_transfer_to_nonexistent_collab_returns_404(s, gestor_h, transfer_setup):
    tid = transfer_setup["ticket"]["id"]
    r = s.post(
        f"{API}/lousa/tickets/{tid}/transfer",
        headers=gestor_h,
        json={"new_collaborator_id": "col-nonexistent-xyz"},
        timeout=15,
    )
    assert r.status_code == 404, r.text


def test_transfer_finalized_ticket_returns_400(s, gestor_h):
    """Cria um ticket, finaliza-o por fora (status=encerrada via admin-close), tenta transferir → 400."""
    suffix = uuid.uuid4().hex[:6]
    a = s.post(f"{API}/collaborators", headers=gestor_h, json={
        "name": f"TEST_TFin_A {suffix}",
        "cpf": f"333.{suffix[:3]}.{suffix[3:6]}-33",
        "email": f"TEST_fa_{suffix}@example.com",
        "phone": "+5511333330000",
        "is_test_mode": True,
    }, timeout=15).json()
    b = s.post(f"{API}/collaborators", headers=gestor_h, json={
        "name": f"TEST_TFin_B {suffix}",
        "cpf": f"444.{suffix[:3]}.{suffix[3:6]}-44",
        "email": f"TEST_fb_{suffix}@example.com",
        "phone": "+5511444440000",
        "is_test_mode": True,
    }, timeout=15).json()
    tk = s.post(f"{API}/lousa/tickets", headers=gestor_h, json={
        "client_name": f"TEST_CLI_FIN {suffix}",
        "address": "R. Test 1, SP",
        "type": "reparo",
        "priority": "normal",
        "assigned_collaborator_id": a["id"],
    }, timeout=20).json()
    try:
        # admin-close → encerrada
        rc = s.post(
            f"{API}/lousa/tickets/{tk['id']}/admin-close",
            headers=gestor_h,
            json={"action": "encerrar", "notes": "test"},
            timeout=15,
        )
        assert rc.status_code == 200, rc.text
        # tentar transferir
        r = s.post(
            f"{API}/lousa/tickets/{tk['id']}/transfer",
            headers=gestor_h,
            json={"new_collaborator_id": b["id"]},
            timeout=15,
        )
        assert r.status_code == 400, r.text
    finally:
        try:
            s.delete(f"{API}/lousa/tickets/{tk['id']}", headers=gestor_h, timeout=10)
        except Exception:
            pass
        for x in (a, b):
            try:
                s.delete(f"{API}/collaborators/{x['id']}", headers=gestor_h, timeout=10)
            except Exception:
                pass


# ---------------------- 6. Regression iter1 ----------------------
def test_regression_lousa_all(s, gestor_h):
    r = s.get(f"{API}/lousa/all", headers=gestor_h, timeout=15)
    assert r.status_code == 200
    assert "tickets" in r.json()


def test_regression_notifications(s, gestor_h):
    r = s.get(f"{API}/notifications", headers=gestor_h, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and "unread_count" in body
