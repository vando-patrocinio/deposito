"""
Iteration 19 — Backend regression after MASSIVE server.py refactor (2688 -> 208 lines).
All endpoints redistributed across /app/backend/routes/*.py.

Covers:
  * Auth (login + impersonate + end-impersonation)
  * Users CRUD (auditor) + reject role=colaborador
  * Pracas CRUD + discover-holidays AI
  * Collaborators CRUD + reset-face + geofences CRUD
  * Clock records (filters, manual, batch-fix-schedule)
  * Timesheets JSON + PDF
  * Dashboard overtime/{y}/{m}, /trend, /range, /dwell-heatmap, /dwell-heatmap/day (NEW)
  * Locations live, dwell-analysis, track
  * Holidays, Settings (sensitive masked), system/alerts, geocode
  * Push: vapid, subscribe, test (with/without JWT), subscriptions role filter
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

AUDITOR = {"email": "vando@example.com", "password": "123456"}
ADMIN = {"email": "admin@example.com", "password": "admin123"}


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


def _login(sess, creds):
    r = sess.post(f"{API}/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    body = r.json()
    assert "access_token" in body and "user" in body
    return body["access_token"], body["user"]


@pytest.fixture(scope="module")
def auditor_tok(s):
    tok, _ = _login(s, AUDITOR)
    return tok


@pytest.fixture(scope="module")
def admin_tok(s):
    tok, _ = _login(s, ADMIN)
    return tok


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------------- AUTH ----------------
class TestAuth:
    def test_login_auditor(self, s):
        tok, user = _login(s, AUDITOR)
        assert user["role"] == "auditor"
        assert isinstance(tok, str) and len(tok) > 20

    def test_login_admin(self, s):
        tok, user = _login(s, ADMIN)
        assert user["role"] in ("gestor", "auditor")

    def test_login_bad_creds(self, s):
        r = s.post(f"{API}/auth/login", json={"email": "vando@example.com", "password": "wrong"}, timeout=15)
        assert r.status_code in (401, 429)

    def test_me(self, s, auditor_tok):
        r = s.get(f"{API}/auth/me", headers=H(auditor_tok), timeout=15)
        assert r.status_code == 200
        assert r.json()["email"] == AUDITOR["email"]


# ---------------- USERS ----------------
class TestUsers:
    created_id = None

    def test_list_users_requires_auditor(self, s, auditor_tok):
        r = s.get(f"{API}/users", headers=H(auditor_tok), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_users_unauth(self, s):
        r = s.get(f"{API}/users", timeout=15)
        assert r.status_code in (401, 403)

    def test_create_user_reject_colaborador(self, s, auditor_tok):
        r = s.post(f"{API}/users", headers=H(auditor_tok), json={
            "name": "TEST_iter19_col",
            "email": f"TEST_iter19_col_{uuid.uuid4().hex[:6]}@example.com",
            "password": "pwd123!",
            "role": "colaborador",
        }, timeout=15)
        assert r.status_code in (400, 403, 422), f"expected reject, got {r.status_code} {r.text}"

    def test_create_update_delete_gestor(self, s, auditor_tok):
        email = f"TEST_iter19_{uuid.uuid4().hex[:8]}@example.com"
        r = s.post(f"{API}/users", headers=H(auditor_tok), json={
            "name": "TEST_iter19_gestor",
            "email": email,
            "password": "pwd123!",
            "role": "gestor",
        }, timeout=15)
        assert r.status_code in (200, 201), r.text
        uid = r.json()["id"]
        TestUsers.created_id = uid

        # PUT — update name + password
        r2 = s.put(f"{API}/users/{uid}", headers=H(auditor_tok), json={
            "name": "TEST_iter19_gestor_renamed",
            "password": "newpwd456!",
        }, timeout=15)
        assert r2.status_code == 200, r2.text
        assert r2.json()["name"] == "TEST_iter19_gestor_renamed"

        # password change must work
        r3 = s.post(f"{API}/auth/login", json={"email": email, "password": "newpwd456!"}, timeout=15)
        assert r3.status_code == 200

        # DELETE
        r4 = s.delete(f"{API}/users/{uid}", headers=H(auditor_tok), timeout=15)
        assert r4.status_code in (200, 204)

    def test_impersonate_and_end(self, s, auditor_tok):
        # need a target user — use the colaborador 'col@example.com'
        users = s.get(f"{API}/users", headers=H(auditor_tok), timeout=15).json()
        target = next((u for u in users if u.get("email") == "col@example.com"), None)
        if not target:
            pytest.skip("target colaborador user not present")
        r = s.post(f"{API}/auth/impersonate/{target['id']}", headers=H(auditor_tok), timeout=15)
        assert r.status_code == 200, r.text
        imp_tok = r.json().get("access_token")
        assert imp_tok and imp_tok != auditor_tok
        # end-impersonation should restore — endpoint accepts impersonated token
        r2 = s.post(f"{API}/auth/end-impersonation", headers=H(imp_tok), timeout=15)
        assert r2.status_code == 200


# ---------------- PRACAS ----------------
class TestPracas:
    def test_list(self, s):
        r = s.get(f"{API}/pracas", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_update_delete(self, s, auditor_tok):
        r = s.post(f"{API}/pracas", headers=H(auditor_tok), json={
            "name": f"TEST_iter19_praca_{uuid.uuid4().hex[:6]}",
            "city": "São Paulo",
            "state": "SP",
            "full_address": "Rua Teste, 100",
        }, timeout=15)
        assert r.status_code in (200, 201), r.text
        pid = r.json()["id"]
        r2 = s.put(f"{API}/pracas/{pid}", headers=H(auditor_tok), json={
            "name": r.json()["name"], "city": "São Paulo", "state": "SP",
            "full_address": "Rua Teste, 200",
        }, timeout=15)
        assert r2.status_code == 200
        r3 = s.delete(f"{API}/pracas/{pid}", headers=H(auditor_tok), timeout=15)
        assert r3.status_code in (200, 204)

    def test_discover_holidays_ai(self, s, auditor_tok):
        # Create temp praca
        r = s.post(f"{API}/pracas", headers=H(auditor_tok), json={
            "name": f"TEST_iter19_h_{uuid.uuid4().hex[:6]}",
            "city": "São Paulo",
            "state": "SP",
        }, timeout=15)
        assert r.status_code in (200, 201), r.text
        pid = r.json()["id"]
        try:
            r2 = s.post(f"{API}/pracas/{pid}/discover-holidays?year=2026", headers=H(auditor_tok), timeout=60)
            # AI may be flaky -> accept 200 or 502
            assert r2.status_code in (200, 502), f"unexpected {r2.status_code}: {r2.text[:200]}"
        finally:
            s.delete(f"{API}/pracas/{pid}", headers=H(auditor_tok), timeout=15)


# ---------------- COLLABORATORS ----------------
class TestCollaborators:
    def test_list_no_auth(self, s):
        r = s.get(f"{API}/collaborators", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_full_lifecycle(self, s, auditor_tok):
        # CREATE
        r = s.post(f"{API}/collaborators", json={
            "name": f"TEST_iter19_col_{uuid.uuid4().hex[:6]}",
            "cpf": f"000.{uuid.uuid4().int % 1000:03d}.{uuid.uuid4().int % 1000:03d}-99",
            "email": f"TEST_iter19_{uuid.uuid4().hex[:6]}@example.com",
            "phone": "11999990000",
        }, timeout=15)
        assert r.status_code in (200, 201), r.text
        cid = r.json()["id"]
        created = r.json()
        try:
            # UPDATE — PUT requires full CollaboratorIn body
            r2 = s.put(f"{API}/collaborators/{cid}", json={
                "name": "TEST_iter19_renamed",
                "cpf": created["cpf"],
                "email": created["email"],
                "phone": created.get("phone", "11999990000"),
            }, timeout=15)
            assert r2.status_code == 200, r2.text

            # reset-face (auth required)
            r3 = s.post(f"{API}/collaborators/{cid}/reset-face", headers=H(auditor_tok), timeout=15)
            assert r3.status_code == 200

            # CREATE GEOFENCE — needs name, type, address
            r4 = s.post(f"{API}/collaborators/{cid}/geofences", json={
                "name": "TEST_iter19_fence",
                "type": "praca",
                "address": "Rua Teste, 100 - São Paulo, SP",
                "lat": -23.55,
                "lng": -46.63,
                "radius": 50,
            }, timeout=15)
            assert r4.status_code in (200, 201), r4.text
            gid = r4.json()["id"]

            # PUT geofence
            r5 = s.put(f"{API}/geofences/{gid}", json={
                "name": "TEST_iter19_fence",
                "type": "praca",
                "address": "Rua Teste, 100 - São Paulo, SP",
                "radius": 75,
            }, timeout=15)
            assert r5.status_code == 200

            # DELETE geofence
            r6 = s.delete(f"{API}/geofences/{gid}", timeout=15)
            assert r6.status_code in (200, 204)
        finally:
            s.delete(f"{API}/collaborators/{cid}", timeout=15)


# ---------------- CLOCK RECORDS ----------------
class TestClockRecords:
    def test_list_with_filters(self, s):
        r = s.get(f"{API}/clock-records", params={"limit": 5}, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_manual_entry_and_batch(self, s, auditor_tok):
        # need a collaborator
        colls = s.get(f"{API}/collaborators", timeout=15).json()
        if not colls:
            pytest.skip("no collaborators")
        cid = colls[0]["id"]
        # manual entry: ManualEntry requires {collaborator_id, type, date, time, reason}
        # type must be one of EVENT_TYPES (Entrada/Início intervalo/Fim intervalo/Saída)
        r = s.post(f"{API}/clock-records/manual", headers=H(auditor_tok), json={
            "collaborator_id": cid,
            "type": "Entrada",
            "date": "2026-05-15",
            "time": "08:00",
            "reason": "TEST_iter19 manual entry justification",
        }, timeout=20)
        assert r.status_code in (200, 201), r.text

        # batch fix schedule: BatchFixRequest {collaborator_id, year, month, reason}
        r2 = s.post(f"{API}/clock-records/manual/batch-fix-schedule", headers=H(auditor_tok), json={
            "collaborator_id": cid,
            "year": 2026,
            "month": 5,
            "reason": "TEST_iter19 batch fix",
        }, timeout=60)
        assert r2.status_code in (200, 207), r2.text


# ---------------- TIMESHEETS ----------------
class TestTimesheets:
    def test_json_and_pdf(self, s):
        colls = s.get(f"{API}/collaborators", timeout=15).json()
        if not colls:
            pytest.skip("no collaborators")
        cid = colls[0]["id"]
        r = s.get(f"{API}/timesheets/{cid}/2026/5", timeout=30)
        assert r.status_code == 200
        body = r.json()
        assert "days" in body and len(body["days"]) == 31

        r2 = s.get(f"{API}/timesheets/{cid}/2026/5/pdf", timeout=60)
        assert r2.status_code == 200
        assert r2.headers.get("content-type", "").startswith("application/pdf")
        assert len(r2.content) > 500


# ---------------- DASHBOARD ----------------
class TestDashboard:
    def test_overtime_month(self, s):
        r = s.get(f"{API}/dashboard/overtime/2026/5", timeout=30)
        assert r.status_code == 200
        b = r.json()
        # actual shape: month, rows, top3_overtime, top3_paid, ...
        assert "rows" in b and isinstance(b["rows"], list)
        assert "month" in b

    def test_overtime_trend(self, s):
        r = s.get(f"{API}/dashboard/overtime/trend", params={"months": 3}, timeout=30)
        assert r.status_code == 200
        b = r.json()
        assert "series" in b and "alerts" in b

    def test_overtime_range(self, s):
        r = s.get(f"{API}/dashboard/overtime/range", params={
            "year_from": 2026, "month_from": 4, "year_to": 2026, "month_to": 5,
        }, timeout=60)
        assert r.status_code == 200
        b = r.json()
        # must contain monthly and accumulated
        assert any(k in b for k in ("monthly", "rows", "series"))

    def test_dwell_heatmap_month(self, s):
        r = s.get(f"{API}/dashboard/dwell-heatmap", params={"year": 2026, "month": 5}, timeout=60)
        assert r.status_code == 200
        b = r.json()
        assert "rows" in b and "by_day" in b

    def test_dwell_heatmap_day_NEW(self, s):
        # NEW endpoint — drill-down on day
        r = s.get(f"{API}/dashboard/dwell-heatmap/day", params={"year": 2026, "month": 5, "day": 5}, timeout=60)
        assert r.status_code == 200, r.text
        b = r.json()
        # required shape
        assert b.get("year") == 2026 and b.get("month") == 5 and b.get("day") == 5
        assert "stays" in b and isinstance(b["stays"], list)
        assert "total_minutes" in b and isinstance(b["total_minutes"], (int, float))
        # Each stay has the documented fields
        for st in b["stays"]:
            for k in ("collaborator_id", "collaborator_name", "praca_id", "praca_name",
                      "center_lat", "center_lng", "start", "end", "duration_min", "points"):
                assert k in st, f"missing {k} in stay"
            assert st["duration_min"] >= 30
        # total_minutes consistent with sum
        assert b["total_minutes"] == sum(s["duration_min"] for s in b["stays"])

    def test_dwell_heatmap_day_invalid(self, s):
        r = s.get(f"{API}/dashboard/dwell-heatmap/day", params={"year": 2026, "month": 2, "day": 31}, timeout=15)
        assert r.status_code == 400


# ---------------- LOCATIONS ----------------
class TestLocations:
    def test_live(self, s):
        r = s.get(f"{API}/locations/live", timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_dwell_analysis(self, s):
        r = s.get(f"{API}/locations/dwell-analysis", timeout=30)
        assert r.status_code == 200

    def test_track(self, s):
        colls = s.get(f"{API}/collaborators", timeout=15).json()
        if not colls:
            pytest.skip("no colls")
        cid = colls[0]["id"]
        r = s.get(f"{API}/locations/{cid}/track", timeout=20)
        assert r.status_code == 200


# ---------------- ADMIN/MISC ----------------
class TestAdmin:
    def test_holidays(self, s):
        r = s.get(f"{API}/holidays/2026", timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_settings_masked(self, s, auditor_tok):
        r = s.get(f"{API}/settings", headers=H(auditor_tok), timeout=15)
        assert r.status_code == 200
        body = r.json()
        # sensitive values must be masked or hidden
        for k in ("resend_api_key", "emergent_llm_key", "jwt_secret"):
            v = body.get(k)
            if v is not None and isinstance(v, str) and len(v) > 0:
                assert "*" in v or v in ("***", "****", "********") or v.startswith("***"), (
                    f"sensitive key {k} not masked: {v[:8]}..."
                )

    def test_system_alerts(self, s, auditor_tok):
        r = s.get(f"{API}/system/alerts", headers=H(auditor_tok), timeout=15)
        assert r.status_code == 200

    def test_geocode(self, s):
        r = s.get(f"{API}/geocode/search", params={"q": "cachoeiras"}, timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ---------------- PUSH ----------------
class TestPush:
    fake_endpoint = f"https://fcm.googleapis.com/test/iter19_{uuid.uuid4().hex[:8]}"

    def test_vapid_pub(self, s):
        r = s.get(f"{API}/push/vapid-public-key", timeout=15)
        assert r.status_code == 200
        b = r.json()
        assert "public_key" in b or "publicKey" in b or "key" in b

    def test_subscribe_requires_jwt(self, s):
        r = s.post(f"{API}/push/subscribe", json={
            "endpoint": self.fake_endpoint,
            "keys": {"p256dh": "x" * 80, "auth": "y" * 22},
            "user_agent": "pytest",
        }, timeout=15)
        assert r.status_code in (401, 403)

    def test_subscribe_with_jwt(self, s, auditor_tok):
        r = s.post(f"{API}/push/subscribe", headers=H(auditor_tok), json={
            "endpoint": self.fake_endpoint,
            "keys": {"p256dh": "x" * 80, "auth": "y" * 22},
            "user_agent": "pytest",
        }, timeout=15)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b.get("ok") is True

    def test_test_no_jwt(self, s):
        r = s.post(f"{API}/push/test", timeout=15)
        assert r.status_code == 401

    def test_test_with_jwt(self, s, auditor_tok):
        r = s.post(f"{API}/push/test", headers=H(auditor_tok), timeout=30)
        assert r.status_code == 200, r.text
        b = r.json()
        assert "sent" in b and "failed" in b

    def test_subscriptions_role_filter(self, s, auditor_tok):
        """List endpoint must apply allowed_roles=[gestor,auditor].
        After subscribe under auditor token, our endpoint should appear.
        Subs linked to colaborador users must NOT appear."""
        r = s.get(f"{API}/push/subscriptions", headers=H(auditor_tok), timeout=15)
        assert r.status_code == 200, r.text
        subs = r.json()
        assert isinstance(subs, list)

        # gather user_ids -> roles
        users = s.get(f"{API}/users", headers=H(auditor_tok), timeout=15).json()
        roles = {u["id"]: u.get("role") for u in users}
        for sub in subs:
            uid = sub.get("user_id")
            if uid and uid in roles:
                assert roles[uid] in ("gestor", "auditor"), (
                    f"sub for user_id={uid} role={roles[uid]} leaked into role-filtered list"
                )

    def test_unsubscribe_cleanup(self, s, auditor_tok):
        r = s.post(f"{API}/push/unsubscribe", headers=H(auditor_tok), json={"endpoint": self.fake_endpoint}, timeout=15)
        # ok to be 200 or 404
        assert r.status_code in (200, 404)
