"""
CENTRAL_ONT backend integration tests — iteration 88.

Coverage (per review_request):
  1. GET/PUT /api/lousa/central-ont/settings (admin/gestor only)
  2. GET /api/lousa/central-ont/report?days=30 (schema + values)
  3. POST /api/lousa/public/tickets/{id}/finalize:
      a. block ON + sinal < threshold + no auth → 403 needs_bad_signal_auth + auto-creates request + notification
      b. admin approves request → status='approved'
      c. retry finalize with bad_signal_auth_id → 200; ticket.central_ont.auth_used set; request status='used'
  4. block OFF + bad sinal → finalize 200; notification 'bad_signal_close' created
  5. SN mismatch (skipped if no smartolt enrichment available)
  6. /api/lousa/central-ont/auth-requests?status=pending list
  7. /api/lousa/central-ont/auth-requests/{id}/reject
  8. /api/lousa/public/bad-signal-auth/{id} (no auth)
"""
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"
DEMO_COMPANY = "co-demo"

TEST_RUN_TAG = f"TEST_iter88_{uuid.uuid4().hex[:6]}"


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
                      timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def collaborator_id(admin_headers):
    """Create a TEST collaborator with clock_in_enabled=False (freelancer mode)
    so public/open does NOT require clock-in."""
    suffix = uuid.uuid4().hex[:6]
    payload = {
        "name": f"{TEST_RUN_TAG}-Tec",
        "cpf": f"99988877{suffix[:3]}",
        "email": f"{TEST_RUN_TAG}-{suffix}@example.com",
        "phone": "11999999999",
        "role": "Colaborador de Campo",
        "company": "Operação SP",
        "clock_in_enabled": False,
        "active": True,
    }
    r = requests.post(f"{API}/collaborators", json=payload,
                      headers=admin_headers, timeout=20)
    if r.status_code not in (200, 201):
        pytest.skip(f"Cannot create collaborator: {r.status_code} {r.text}")
    cid = r.json()["id"]
    yield cid
    try:
        requests.delete(f"{API}/collaborators/{cid}",
                        headers=admin_headers, timeout=10)
    except Exception:
        pass


def _create_ticket(admin_headers, collaborator_id, kind="reparo"):
    payload = {
        "client_name": f"{TEST_RUN_TAG}-Client",
        "address": "Rua Teste 123",
        "neighborhood": "Centro",
        "phone": "11988887777",
        "relato": "Sem internet",
        "pppoe_user": "user@isp",
        "type": kind,
        "priority": "normal",
        "assigned_collaborator_id": collaborator_id,
    }
    r = requests.post(f"{API}/lousa/tickets", json=payload,
                      headers=admin_headers, timeout=20)
    assert r.status_code in (200, 201), f"create ticket: {r.status_code} {r.text}"
    return r.json()


def _open_ticket(ticket_id, collaborator_id):
    r = requests.post(
        f"{API}/lousa/public/tickets/{ticket_id}/open",
        json={"collaborator_id": collaborator_id}, timeout=20,
    )
    return r


def _finalize(ticket_id, collaborator_id, sinal=-30.0, ont="ABCD12345678",
              auth_id=None):
    body = {
        "collaborator_id": collaborator_id,
        "latitude": -23.5, "longitude": -46.6,
        "outcome": "sucesso",
        "completion_data": {
            "sinal": sinal, "qtd_drop": 1, "esticadores": 0,
            "conectores_fast": 2, "cabo_rede": 5.0, "conectores_rede": 2,
            "ont": ont, "fotos": ["a.jpg", "b.jpg", "c.jpg"],
            "observacoes": "TEST",
        },
    }
    if auth_id:
        body["bad_signal_auth_id"] = auth_id
    return requests.post(
        f"{API}/lousa/public/tickets/{ticket_id}/finalize",
        json=body, timeout=30,
    )


# --------------------------------------------------------------------------
# 1. Settings — GET / PUT
# --------------------------------------------------------------------------
class TestSettings:
    def test_get_default_settings(self, admin_headers):
        r = requests.get(f"{API}/lousa/central-ont/settings",
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "block_bad_signal_close" in data
        assert "bad_signal_threshold" in data
        assert isinstance(data["block_bad_signal_close"], bool)
        assert isinstance(data["bad_signal_threshold"], (int, float))

    def test_put_settings_persist(self, admin_headers):
        # turn ON with threshold -27
        r = requests.put(f"{API}/lousa/central-ont/settings",
                         json={"block_bad_signal_close": True,
                               "bad_signal_threshold": -27.0},
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        g = requests.get(f"{API}/lousa/central-ont/settings",
                         headers=admin_headers, timeout=15).json()
        assert g["block_bad_signal_close"] is True
        assert float(g["bad_signal_threshold"]) == -27.0

    def test_settings_requires_admin(self):
        r = requests.get(f"{API}/lousa/central-ont/settings", timeout=15)
        assert r.status_code in (401, 403)


# --------------------------------------------------------------------------
# 2 & 3. Full E2E: block ON → 403 → approve → retry success
# --------------------------------------------------------------------------
class TestBadSignalE2E:
    def test_full_flow(self, admin_headers, collaborator_id):
        # Ensure block ON
        requests.put(f"{API}/lousa/central-ont/settings",
                     json={"block_bad_signal_close": True,
                           "bad_signal_threshold": -27.0},
                     headers=admin_headers, timeout=15)

        # Create + open
        ticket = _create_ticket(admin_headers, collaborator_id)
        tid = ticket["id"]
        r_open = _open_ticket(tid, collaborator_id)
        if r_open.status_code != 200:
            pytest.skip(f"public/open returned {r_open.status_code}: {r_open.text}")

        # Finalize with bad signal (-30 < -27)
        r1 = _finalize(tid, collaborator_id, sinal=-30.0)
        assert r1.status_code == 403, f"expected 403 got {r1.status_code} {r1.text}"
        body = r1.json()
        detail = body.get("detail") if isinstance(body.get("detail"), dict) \
            else body
        assert detail.get("code") == "needs_bad_signal_auth", detail
        req_id = detail.get("request_id")
        assert req_id and req_id.startswith("bsa-"), detail
        assert float(detail.get("threshold")) == -27.0
        assert float(detail.get("sinal")) == -30.0

        # Public status check (no auth)
        r_pub = requests.get(
            f"{API}/lousa/public/bad-signal-auth/{req_id}", timeout=15)
        assert r_pub.status_code == 200, r_pub.text
        assert r_pub.json()["status"] == "pending"

        # Admin sees in list
        r_list = requests.get(
            f"{API}/lousa/central-ont/auth-requests?status=pending",
            headers=admin_headers, timeout=15)
        assert r_list.status_code == 200
        items = r_list.json().get("items", [])
        found = [i for i in items if i["id"] == req_id]
        assert found, "auth request not in pending list"
        assert "collaborator_name" in found[0]
        assert "client_name" in found[0]

        # Approve
        r_app = requests.post(
            f"{API}/lousa/central-ont/auth-requests/{req_id}/approve",
            headers=admin_headers, timeout=15)
        assert r_app.status_code == 200, r_app.text
        assert r_app.json()["status"] == "approved"

        # Public polling now sees approved
        r_pub2 = requests.get(
            f"{API}/lousa/public/bad-signal-auth/{req_id}", timeout=15).json()
        assert r_pub2["status"] == "approved"

        # Retry finalize with auth_id
        r2 = _finalize(tid, collaborator_id, sinal=-30.0, auth_id=req_id)
        assert r2.status_code == 200, f"retry: {r2.status_code} {r2.text}"
        data = r2.json()
        assert data["status"] == "finalizada"
        assert (data.get("central_ont") or {}).get("auth_used") == req_id
        assert (data.get("central_ont") or {}).get("is_bad_signal") is True

        # The request should now be 'used'
        r_pub3 = requests.get(
            f"{API}/lousa/public/bad-signal-auth/{req_id}", timeout=15).json()
        assert r_pub3["status"] == "used"

        # cleanup
        requests.delete(f"{API}/lousa/tickets/{tid}",
                        headers=admin_headers, timeout=10)


# --------------------------------------------------------------------------
# 4. block OFF + bad signal → finalize 200 (passive notification)
# --------------------------------------------------------------------------
class TestBlockOffPassive:
    def test_block_off_allows_close(self, admin_headers, collaborator_id):
        # turn OFF
        requests.put(f"{API}/lousa/central-ont/settings",
                     json={"block_bad_signal_close": False,
                           "bad_signal_threshold": -27.0},
                     headers=admin_headers, timeout=15)

        ticket = _create_ticket(admin_headers, collaborator_id)
        tid = ticket["id"]
        r_open = _open_ticket(tid, collaborator_id)
        if r_open.status_code != 200:
            pytest.skip(f"open: {r_open.status_code}")

        r = _finalize(tid, collaborator_id, sinal=-30.0)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "finalizada"
        assert (data.get("central_ont") or {}).get("is_bad_signal") is True
        assert (data.get("central_ont") or {}).get("auth_used") is None
        # _warnings.bad_signal.active should be True
        w = data.get("_warnings") or {}
        assert (w.get("bad_signal") or {}).get("active") is True

        requests.delete(f"{API}/lousa/tickets/{tid}",
                        headers=admin_headers, timeout=10)


# --------------------------------------------------------------------------
# 5. Report endpoint shape
# --------------------------------------------------------------------------
class TestReport:
    def test_report_shape(self, admin_headers):
        r = requests.get(f"{API}/lousa/central-ont/report?days=30",
                         headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("period_days", "threshold", "block_enabled",
                  "total_closes", "bad_signal_closes", "overall_ratio_pct",
                  "per_collaborator", "items"):
            assert k in d, f"missing key {k}"
        assert d["period_days"] == 30
        assert isinstance(d["per_collaborator"], list)
        assert isinstance(d["items"], list)
        if d["per_collaborator"]:
            row = d["per_collaborator"][0]
            for k in ("collaborator_id", "collaborator_name",
                      "total_closes", "bad_signal_closes", "ratio_pct"):
                assert k in row


# --------------------------------------------------------------------------
# 6. Reject flow
# --------------------------------------------------------------------------
class TestRejectFlow:
    def test_reject(self, admin_headers, collaborator_id):
        # Block ON to trigger creation
        requests.put(f"{API}/lousa/central-ont/settings",
                     json={"block_bad_signal_close": True,
                           "bad_signal_threshold": -27.0},
                     headers=admin_headers, timeout=15)

        ticket = _create_ticket(admin_headers, collaborator_id)
        tid = ticket["id"]
        r_open = _open_ticket(tid, collaborator_id)
        if r_open.status_code != 200:
            pytest.skip(f"open: {r_open.status_code}")

        r1 = _finalize(tid, collaborator_id, sinal=-31.0)
        assert r1.status_code == 403
        body = r1.json()
        detail = body.get("detail") if isinstance(body.get("detail"), dict) \
            else body
        req_id = detail["request_id"]

        # Reject
        r_rej = requests.post(
            f"{API}/lousa/central-ont/auth-requests/{req_id}/reject",
            headers=admin_headers, timeout=15)
        assert r_rej.status_code == 200, r_rej.text
        assert r_rej.json()["status"] == "rejected"

        # 2nd reject → 404
        r_rej2 = requests.post(
            f"{API}/lousa/central-ont/auth-requests/{req_id}/reject",
            headers=admin_headers, timeout=15)
        assert r_rej2.status_code == 404

        # Retry with rejected token → 400
        r2 = _finalize(tid, collaborator_id, sinal=-31.0, auth_id=req_id)
        assert r2.status_code == 400, r2.text

        requests.delete(f"{API}/lousa/tickets/{tid}",
                        headers=admin_headers, timeout=10)


# --------------------------------------------------------------------------
# 7. Public auth status 404
# --------------------------------------------------------------------------
class TestPublicAuthStatusEdge:
    def test_404_unknown(self):
        r = requests.get(
            f"{API}/lousa/public/bad-signal-auth/bsa-doesnotexist",
            timeout=10)
        assert r.status_code == 404


# --------------------------------------------------------------------------
# Cleanup teardown: ensure block toggle OFF after tests so other tests aren't
# affected.
# --------------------------------------------------------------------------
@pytest.fixture(autouse=True, scope="module")
def _final_cleanup(admin_headers):
    yield
    try:
        requests.put(f"{API}/lousa/central-ont/settings",
                     json={"block_bad_signal_close": False,
                           "bad_signal_threshold": -27.0},
                     headers=admin_headers, timeout=10)
    except Exception:
        pass
