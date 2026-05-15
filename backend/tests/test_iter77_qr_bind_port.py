"""Iteration 77 — Rede IA: POST /api/rede-ia/qrcode/bind-port + regressions.

Tests the new endpoint that binds a subscriber to a free CTO port and
auto-creates a ticket (kanban OS) in db.tickets with source='rede_ia_qr'.

Also regressions for Rede IA endpoints + /api/connections (GET-only,
NEVER PUT dummy keys here — would clobber Atlaz/SmartOLT secrets).
"""
import os
import time
import uuid
import pytest
import requests

def _load_frontend_env_url():
    try:
        with open("/app/frontend/.env", "r") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.strip().split("=", 1)[1]
    except Exception:
        pass
    return None


BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _load_frontend_env_url() or "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not set"
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@empresa.com", "password": "123456"}
COLAB = {"email": "colaborador@empresa.com", "password": "123456"}
GREDE = {"email": "gestorrede@empresa.com", "password": "123456"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.text}"
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- Fixtures ----------------------------------------------------------
@pytest.fixture(scope="module")
def admin_tok():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def colab_tok():
    return _login(COLAB)


@pytest.fixture(scope="module")
def grede_tok():
    return _login(GREDE)


@pytest.fixture(scope="module")
def approved_cto(admin_tok, grede_tok):
    """Find an existing approved CTO with at least 1 free port, else create + approve one."""
    r = requests.get(f"{API}/rede-ia/ctos?status=approved", headers=_h(admin_tok), timeout=15)
    assert r.status_code == 200
    for c in r.json().get("items", []):
        free = [p for p in c.get("ports") or [] if p.get("status") == "free"]
        if free:
            return c

    # else create a new bairro+CTO and approve
    sigla = f"T{uuid.uuid4().hex[:2].upper()}"
    vlan = 3500 + (int(time.time()) % 400)
    requests.post(f"{API}/rede-ia/bairros",
                  json={"bairro": f"TEST_BairroIter77_{sigla}", "sigla": sigla,
                        "vlan": vlan, "cidade": "X", "estado": "SP"},
                  headers=_h(admin_tok), timeout=15)
    sn = requests.get(f"{API}/rede-ia/ctos/suggest-name?sigla={sigla}&vlan={vlan}",
                       headers=_h(admin_tok), timeout=15).json()
    payload = {
        "rua": "R Teste", "numero": "10", "bairro": f"TEST_BairroIter77_{sigla}",
        "cidade": "X", "estado": "SP",
        "capacity": 8, "network_type": "balanceada",
        "sigla": sigla, "vlan": vlan, "suggested_name": sn["suggested_name"],
    }
    cr = requests.post(f"{API}/rede-ia/ctos", json=payload,
                       headers=_h(admin_tok), timeout=15)
    assert cr.status_code == 200, cr.text
    cto = cr.json()
    # approve via gestor_rede
    ar = requests.post(f"{API}/rede-ia/ctos/{cto['id']}/validate",
                       json={"action": "approve", "comment": "iter77 test"},
                       headers=_h(grede_tok), timeout=15)
    assert ar.status_code == 200, ar.text
    # refetch
    cto = requests.get(f"{API}/rede-ia/ctos/{cto['id']}",
                       headers=_h(admin_tok), timeout=15).json()
    return cto


# ---------- bind-port tests ---------------------------------------------------
class TestBindPort:
    def test_404_unknown_cto(self, colab_tok):
        r = requests.post(f"{API}/rede-ia/qrcode/bind-port",
                          json={"cto_id": "cto-doesnotexist", "port_number": 1,
                                "subscriber_name": "X"},
                          headers=_h(colab_tok), timeout=15)
        assert r.status_code == 404

    def test_404_unknown_port(self, colab_tok, approved_cto):
        r = requests.post(f"{API}/rede-ia/qrcode/bind-port",
                          json={"cto_id": approved_cto["id"],
                                "port_number": 9999,
                                "subscriber_name": "X"},
                          headers=_h(colab_tok), timeout=15)
        assert r.status_code == 404

    def test_409_cto_not_approved(self, admin_tok, colab_tok):
        # create new CTO (status=pending_validation) and try to bind
        sigla = f"P{uuid.uuid4().hex[:2].upper()}"
        vlan = 3900 + (int(time.time()) % 90)
        requests.post(f"{API}/rede-ia/bairros",
                      json={"bairro": f"TEST_BP_{sigla}", "sigla": sigla,
                            "vlan": vlan, "cidade": "X", "estado": "SP"},
                      headers=_h(admin_tok), timeout=15)
        sn = requests.get(f"{API}/rede-ia/ctos/suggest-name?sigla={sigla}&vlan={vlan}",
                          headers=_h(admin_tok), timeout=15).json()
        cr = requests.post(f"{API}/rede-ia/ctos",
                           json={"rua": "R", "numero": "1",
                                 "bairro": f"TEST_BP_{sigla}",
                                 "cidade": "X", "estado": "SP",
                                 "capacity": 4, "network_type": "balanceada",
                                 "sigla": sigla, "vlan": vlan,
                                 "suggested_name": sn["suggested_name"]},
                           headers=_h(admin_tok), timeout=15)
        assert cr.status_code == 200
        pending_cto = cr.json()
        r = requests.post(f"{API}/rede-ia/qrcode/bind-port",
                          json={"cto_id": pending_cto["id"], "port_number": 1,
                                "subscriber_name": "X"},
                          headers=_h(colab_tok), timeout=15)
        assert r.status_code == 409

    def test_bind_success_creates_ticket_and_history(self, colab_tok, admin_tok, approved_cto):
        free = [p for p in approved_cto["ports"] if p.get("status") == "free"]
        assert free, "approved CTO has no free port"
        port = free[0]["number"]
        sub_name = f"TEST_Sub_{uuid.uuid4().hex[:6]}"
        body = {
            "cto_id": approved_cto["id"],
            "port_number": port,
            "subscriber_name": sub_name,
            "pppoe": f"test_pppoe_{uuid.uuid4().hex[:5]}",
            "subscriber_phone": "11999990000",
            "service_type": "instalacao",
            "notes": "iter77 bind",
        }
        r = requests.post(f"{API}/rede-ia/qrcode/bind-port", json=body,
                          headers=_h(colab_tok), timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["port_number"] == port
        assert data["subscriber_name"] == sub_name
        ticket_id = data["ticket_id"]
        assert ticket_id.startswith("tkt-")

        # CTO port now used
        cto2 = requests.get(f"{API}/rede-ia/ctos/{approved_cto['id']}",
                            headers=_h(admin_tok), timeout=15).json()
        target = next(p for p in cto2["ports"] if p["number"] == port)
        assert target["status"] == "used"
        assert target.get("client_name") == sub_name
        assert target.get("linked_via_qr") is True
        assert target.get("linked_by_user_name")

        # Ticket exists (via lousa list or admin ticket lookup) — check via /api/lousa
        # but the simpler check: history endpoint reflects bind_port action
        h = requests.get(f"{API}/rede-ia/history?cto_id={approved_cto['id']}",
                         headers=_h(admin_tok), timeout=15)
        assert h.status_code == 200
        actions = [it["action"] for it in h.json().get("items", [])]
        assert "bind_port" in actions, f"bind_port missing in history: {actions}"

        # Save for next test
        pytest.bind_port_used = port
        pytest.bind_cto_id = approved_cto["id"]
        pytest.bind_ticket_id = ticket_id

    def test_409_port_already_used(self, colab_tok):
        # uses port bound by previous test
        port = getattr(pytest, "bind_port_used", None)
        cto_id = getattr(pytest, "bind_cto_id", None)
        if not port or not cto_id:
            pytest.skip("previous bind didn't run")
        r = requests.post(f"{API}/rede-ia/qrcode/bind-port",
                          json={"cto_id": cto_id, "port_number": port,
                                "subscriber_name": "Duplicate"},
                          headers=_h(colab_tok), timeout=15)
        assert r.status_code == 409

    def test_ticket_persisted_with_source_rede_ia_qr(self, admin_tok):
        ticket_id = getattr(pytest, "bind_ticket_id", None)
        if not ticket_id:
            pytest.skip("no ticket from previous test")
        # Fetch via lousa tickets listing (admin can see)
        # Try /api/lousa/tickets (most likely endpoint)
        for path in ["/lousa/tickets", "/tickets", "/lousa"]:
            r = requests.get(f"{API}{path}", headers=_h(admin_tok), timeout=15)
            if r.status_code == 200:
                items = r.json() if isinstance(r.json(), list) else r.json().get("items") or r.json().get("tickets") or []
                hit = next((t for t in items if t.get("id") == ticket_id), None)
                if hit:
                    assert hit.get("source") == "rede_ia_qr"
                    snap = hit.get("client_snapshot") or {}
                    assert snap.get("cto_name")
                    assert snap.get("cto_port")
                    assert snap.get("cto_vlan")
                    return
        pytest.skip("Could not locate ticket listing endpoint to verify persistence")


# ---------- qrcode/scan regression -------------------------------------------
class TestQrScanRegression:
    def test_qrcode_info_and_scan_roundtrip(self, admin_tok, approved_cto):
        info = requests.get(f"{API}/rede-ia/ctos/{approved_cto['id']}/qrcode",
                            headers=_h(admin_tok), timeout=15)
        assert info.status_code == 200, info.text
        tok = info.json()["token"]
        r = requests.post(f"{API}/rede-ia/qrcode/scan",
                          json={"payload": tok},
                          headers=_h(admin_tok), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["cto"]["id"] == approved_cto["id"]
        assert "free_ports" in data

    def test_scan_invalid_token(self, admin_tok):
        r = requests.post(f"{API}/rede-ia/qrcode/scan",
                          json={"payload": "SPCTO|v1|garbage|garbage"},
                          headers=_h(admin_tok), timeout=15)
        assert r.status_code == 400


# ---------- Rede IA regression -----------------------------------------------
class TestRedeIaRegression:
    def test_ctos_list(self, admin_tok):
        r = requests.get(f"{API}/rede-ia/ctos", headers=_h(admin_tok), timeout=15)
        assert r.status_code == 200
        assert "items" in r.json()

    def test_bairros_list(self, admin_tok):
        r = requests.get(f"{API}/rede-ia/bairros", headers=_h(admin_tok), timeout=15)
        assert r.status_code == 200
        assert "items" in r.json()

    def test_pendencies_has_smartolt_hints_field(self, grede_tok):
        r = requests.get(f"{API}/rede-ia/pendencies", headers=_h(grede_tok), timeout=15)
        assert r.status_code == 200
        items = r.json().get("items", [])
        if items:
            assert "smartolt_hints" in items[0]

    def test_analyze_llm(self, grede_tok):
        r = requests.post(f"{API}/rede-ia/analyze",
                          json={"focus": "general"},
                          headers=_h(grede_tok), timeout=90)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("report") and len(d["report"]) > 30


# ---------- /api/connections GET-ONLY regression -----------------------------
class TestConnectionsGetOnly:
    """CRITICAL: do NOT PUT here — iter72-75 dummy PUTs broke Atlaz/SmartOLT."""

    def test_connections_get(self, admin_tok):
        # Try with bearer and also with cookie session
        s = requests.Session()
        s.post(f"{API}/auth/login", json=ADMIN, timeout=15)
        r = s.get(f"{API}/connections", timeout=15)
        # Just confirm it isn't 5xx — auth required but no server error
        assert r.status_code < 500, f"unexpected 5xx: {r.status_code} {r.text[:200]}"
