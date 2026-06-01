"""Tests for iter142 — NEO Executive Briefing (1-click).

Coverage:
- POST /api/neo-reports/briefing/activate (validations, idempotency)
- GET  /api/neo-reports/briefing/status
- POST /api/neo-reports/briefing/deactivate
- POST /api/neo-reports/schedules/{id}/run (PDF >2000 bytes, consolidates 4 agents)
- GET  /api/neo-reports/report-types (8 types incl. executive_briefing)
- POST /api/neo-reports/schedules with report_type=executive_briefing (avulso)
- Auth: all 3 /briefing/* endpoints require role gestor
"""
from __future__ import annotations

import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

GESTOR_EMAIL = "gestor@empresa.com"
GESTOR_PASS = "123456"

# Collaborator (NOT gestor) — used to test role enforcement
COLAB_EMAIL = "colaborador@empresa.com"
COLAB_PASS = "123456"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(session, email, password):
    r = session.post(f"{BASE_URL}/api/auth/login",
                     json={"email": email, "password": password}, timeout=20)
    if r.status_code != 200:
        return None
    data = r.json()
    return data.get("access_token") or data.get("token")


@pytest.fixture(scope="session")
def gestor_token(session):
    tok = _login(session, GESTOR_EMAIL, GESTOR_PASS)
    assert tok, "gestor login failed"
    return tok


@pytest.fixture(scope="session")
def colab_token(session):
    return _login(session, COLAB_EMAIL, COLAB_PASS)


@pytest.fixture(scope="session")
def auth(gestor_token):
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {gestor_token}",
    })
    return s


@pytest.fixture(scope="session")
def auth_colab(colab_token):
    if not colab_token:
        return None
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {colab_token}",
    })
    return s


@pytest.fixture(scope="session", autouse=True)
def _cleanup_briefing(auth):
    """Garante estado limpo antes/depois do suite."""
    try:
        auth.post(f"{BASE_URL}/api/neo-reports/briefing/deactivate", timeout=15)
    except Exception:
        pass
    yield
    try:
        auth.post(f"{BASE_URL}/api/neo-reports/briefing/deactivate", timeout=15)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Report types — 8 types incl. executive_briefing
# ---------------------------------------------------------------------------
class TestReportTypes:
    def test_report_types_includes_executive_briefing(self, auth):
        r = auth.get(f"{BASE_URL}/api/neo-reports/report-types", timeout=20)
        assert r.status_code == 200, r.text
        items = r.json().get("items", [])
        keys = {i["key"] for i in items}
        assert "executive_briefing" in keys, f"missing executive_briefing in {keys}"
        # 8 types total per spec
        assert len(items) >= 8, f"expected >=8 report types, got {len(items)}: {keys}"


# ---------------------------------------------------------------------------
# Briefing /activate validations
# ---------------------------------------------------------------------------
class TestBriefingActivateValidation:
    def test_activate_empty_phones_returns_400(self, auth):
        r = auth.post(f"{BASE_URL}/api/neo-reports/briefing/activate",
                      json={"phones": [], "hour": 7, "minute": 0}, timeout=20)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# /briefing/status (off state) — must run BEFORE activate
# ---------------------------------------------------------------------------
class TestBriefingStatusOff:
    def test_status_inactive_initially(self, auth):
        r = auth.get(f"{BASE_URL}/api/neo-reports/briefing/status", timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("active") is False, f"expected active=false, got {d}"
        assert d.get("count") == 0, f"expected count=0, got {d}"


# ---------------------------------------------------------------------------
# Activate + status + idempotency + run + deactivate (sequenced)
# ---------------------------------------------------------------------------
class TestBriefingFullFlow:
    PHONE = "5582999998888"

    def test_a_activate_creates_schedule(self, auth):
        r = auth.post(f"{BASE_URL}/api/neo-reports/briefing/activate",
                      json={"phones": [self.PHONE], "hour": 7, "minute": 0},
                      timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("activated") is True
        assert d.get("count") == 1, f"expected count=1, got {d}"
        scheds = d.get("schedules") or []
        assert len(scheds) == 1
        s0 = scheds[0]
        # Name starts with 📋 Briefing
        assert s0.get("name", "").startswith("📋 Briefing"), f"name={s0.get('name')}"
        assert s0.get("report_type") == "executive_briefing"
        assert s0.get("hour") == 7 and s0.get("minute") == 0
        assert (s0.get("metadata") or {}).get("is_briefing") is True
        assert s0.get("whatsapp_phone") == self.PHONE
        assert s0.get("active") is True
        assert s0.get("next_run_at")
        # Persist id for later steps
        TestBriefingFullFlow._sid = s0["id"]

    def test_b_status_active_after_activate(self, auth):
        r = auth.get(f"{BASE_URL}/api/neo-reports/briefing/status", timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("active") is True
        assert d.get("count") == 1, f"expected count=1, got {d}"

    def test_c_activate_idempotent_no_duplicate(self, auth):
        # Re-activate with same phone — should still result in count=1 (deletes old)
        r = auth.post(f"{BASE_URL}/api/neo-reports/briefing/activate",
                      json={"phones": [self.PHONE], "hour": 8, "minute": 15},
                      timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("count") == 1

        r2 = auth.get(f"{BASE_URL}/api/neo-reports/briefing/status", timeout=20)
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2.get("count") == 1, f"duplicate created! {d2}"
        # New schedule should have hour=8
        sched = (d2.get("schedules") or [{}])[0]
        assert sched.get("hour") == 8 and sched.get("minute") == 15
        # Update sid (since old was deleted)
        TestBriefingFullFlow._sid = sched["id"]

    def test_d_run_briefing_generates_pdf(self, auth):
        sid = getattr(TestBriefingFullFlow, "_sid", None)
        assert sid, "no schedule id from previous step"
        # LLM call may take 8-15s — use generous timeout
        r = auth.post(f"{BASE_URL}/api/neo-reports/schedules/{sid}/run",
                      timeout=90)
        assert r.status_code == 200, f"run failed: {r.status_code} {r.text}"
        d = r.json()
        # Accept delivery_failed (sidecar offline) — but PDF must be generated
        size = (d.get("pdf_size_bytes") or d.get("file_size")
                or d.get("size") or d.get("pdf_size") or 0)
        if not size:
            for k in ("meta", "log", "result"):
                v = d.get(k)
                if isinstance(v, dict):
                    size = (size or v.get("pdf_size_bytes")
                            or v.get("file_size") or v.get("size") or 0)
        assert size and size > 2000, (
            f"PDF too small or missing (got {size}). Full response: {d}"
        )
        # Status should be success or delivery_failed (sidecar offline)
        st = d.get("status") or (d.get("log") or {}).get("status")
        assert st in ("success", "delivery_failed", "ok"), f"unexpected status: {st} | {d}"

    def test_e_deactivate_removes_all(self, auth):
        r = auth.post(f"{BASE_URL}/api/neo-reports/briefing/deactivate", timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("deactivated") is True
        assert d.get("removed", -1) >= 0
        # status off
        r2 = auth.get(f"{BASE_URL}/api/neo-reports/briefing/status", timeout=20)
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2.get("active") is False
        assert d2.get("count") == 0


# ---------------------------------------------------------------------------
# POST /schedules with executive_briefing (avulso)
# ---------------------------------------------------------------------------
class TestSchedulesAcceptExecutiveBriefing:
    def test_create_schedule_executive_briefing(self, auth):
        unique = uuid.uuid4().hex[:6]
        payload = {
            "name": f"TEST_avulso_briefing_{unique}",
            "report_type": "executive_briefing",
            "frequency": "daily",
            "hour": 9,
            "minute": 30,
            "whatsapp_phone": "5582988887777",
            "active": True,
            "params": {"days": 1},
        }
        r = auth.post(f"{BASE_URL}/api/neo-reports/schedules",
                      json=payload, timeout=20)
        assert r.status_code in (200, 201), f"create failed: {r.status_code} {r.text}"
        sid = r.json().get("id")
        assert sid
        # Cleanup
        try:
            auth.delete(f"{BASE_URL}/api/neo-reports/schedules/{sid}", timeout=15)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Auth — role gestor required for all /briefing/* endpoints
# ---------------------------------------------------------------------------
class TestBriefingAuth:
    def test_activate_unauth(self, session):
        r = session.post(f"{BASE_URL}/api/neo-reports/briefing/activate",
                         json={"phones": ["5582999998888"]}, timeout=20)
        assert r.status_code in (401, 403)

    def test_status_unauth(self, session):
        r = session.get(f"{BASE_URL}/api/neo-reports/briefing/status", timeout=20)
        assert r.status_code in (401, 403)

    def test_deactivate_unauth(self, session):
        r = session.post(f"{BASE_URL}/api/neo-reports/briefing/deactivate", timeout=20)
        assert r.status_code in (401, 403)

    def test_activate_forbidden_for_colaborador(self, auth_colab):
        if not auth_colab:
            pytest.skip("colaborador login not available")
        r = auth_colab.post(f"{BASE_URL}/api/neo-reports/briefing/activate",
                            json={"phones": ["5582999998888"]}, timeout=20)
        assert r.status_code == 403, f"expected 403 for colaborador, got {r.status_code}: {r.text}"

    def test_status_forbidden_for_colaborador(self, auth_colab):
        if not auth_colab:
            pytest.skip("colaborador login not available")
        r = auth_colab.get(f"{BASE_URL}/api/neo-reports/briefing/status", timeout=20)
        assert r.status_code == 403

    def test_deactivate_forbidden_for_colaborador(self, auth_colab):
        if not auth_colab:
            pytest.skip("colaborador login not available")
        r = auth_colab.post(f"{BASE_URL}/api/neo-reports/briefing/deactivate", timeout=20)
        assert r.status_code == 403
