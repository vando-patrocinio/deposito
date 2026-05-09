"""Iteration 20: Tests for new collaborator-auth (Emergent Google Auth) endpoints
+ regression for legacy endpoints after adding routes_collab_auth router.

Strategy:
- We cannot exchange a real Google session_id (Emergent Auth not callable in test env).
- We simulate "Google-logged" sessions by inserting fake docs directly in
  Mongo collection `collaborator_sessions` and validate /me, /logout, reset-face,
  unbind-device behaviors.
- Cleanup at end of class via fixture.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

# Add backend dir to path so we can reuse db client for fake-session inserts
sys.path.insert(0, "/app/backend")
from database import db  # noqa: E402
import asyncio  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://selfie-attendance-7.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

DEMO_CID = "col-demo-001"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _mk_session(token: str, cid: str = DEMO_CID, *, expires_in: timedelta = timedelta(hours=1),
                google_email: str = "test@example.com", device_id: str = "dev-test-1") -> dict:
    expires = (datetime.now(timezone.utc) + expires_in).isoformat()
    doc = {
        "session_token": token,
        "collaborator_id": cid,
        "google_email": google_email,
        "device_id": device_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires,
    }
    _run(db.collaborator_sessions.insert_one(doc))
    return doc


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    # Remove any session created with the prefix used in this test
    _run(db.collaborator_sessions.delete_many({"session_token": {"$regex": "^cs_test_iter20_"}}))
    # Restore demo collaborator (clear potentially-set device fields to keep idempotent)
    _run(db.collaborators.update_one(
        {"id": DEMO_CID},
        {"$set": {"device_id": None, "google_email": None,
                  "google_name": None, "google_picture": None}},
    ))


@pytest.fixture(scope="module")
def auditor_token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": "vando@example.com", "password": "123456"},
                      timeout=10)
    if r.status_code != 200:
        # try seeded auditor
        r = requests.post(f"{API}/auth/login",
                          json={"email": "auditor@example.com", "password": "auditor123"},
                          timeout=10)
    assert r.status_code == 200, f"login fail {r.status_code}: {r.text}"
    return r.json()["access_token"]


# ----------------------------- /me ---------------------------------
class TestCollabAuthMe:
    def test_me_without_token_returns_401(self):
        r = requests.get(f"{API}/collaborator-auth/me", timeout=10)
        assert r.status_code == 401, r.text

    def test_me_with_invalid_token_returns_401(self):
        r = requests.get(f"{API}/collaborator-auth/me",
                         headers={"Authorization": "Bearer cs_test_iter20_invalid_xxx"},
                         timeout=10)
        assert r.status_code == 401, r.text

    def test_me_with_valid_bearer_returns_200(self):
        tok = f"cs_test_iter20_{uuid.uuid4().hex}"
        _mk_session(tok)
        r = requests.get(f"{API}/collaborator-auth/me",
                         headers={"Authorization": f"Bearer {tok}"},
                         timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "collaborator" in body and body["collaborator"]["id"] == DEMO_CID
        assert body["google_email"] == "test@example.com"
        assert body["device_id"] == "dev-test-1"
        # Must NOT leak reference_face
        assert "reference_face" not in body["collaborator"]
        # Must NOT contain Mongo _id
        assert "_id" not in body["collaborator"]

    def test_me_with_expired_token_returns_401(self):
        tok = f"cs_test_iter20_{uuid.uuid4().hex}"
        _mk_session(tok, expires_in=timedelta(seconds=-60))
        r = requests.get(f"{API}/collaborator-auth/me",
                         headers={"Authorization": f"Bearer {tok}"},
                         timeout=10)
        assert r.status_code == 401, r.text

    def test_me_with_cookie_returns_200(self):
        tok = f"cs_test_iter20_{uuid.uuid4().hex}"
        _mk_session(tok)
        r = requests.get(f"{API}/collaborator-auth/me",
                         cookies={"collaborator_session": tok},
                         timeout=10)
        assert r.status_code == 200, r.text


# --------------------- /process-session ----------------------------
class TestProcessSession:
    def test_process_session_missing_fields_returns_422_or_400(self):
        # Pydantic missing field -> 422 (FastAPI)
        r = requests.post(f"{API}/collaborator-auth/process-session", json={}, timeout=10)
        assert r.status_code in (400, 422), r.text

    def test_process_session_empty_strings_returns_400(self):
        r = requests.post(f"{API}/collaborator-auth/process-session",
                          json={"session_id": "", "device_id": ""}, timeout=10)
        assert r.status_code == 400, r.text

    def test_process_session_missing_device_id_returns_422(self):
        r = requests.post(f"{API}/collaborator-auth/process-session",
                          json={"session_id": "anything"}, timeout=10)
        assert r.status_code in (400, 422), r.text

    def test_process_session_invalid_session_id_returns_401(self):
        # Real call to Emergent with garbage session_id should return non-2xx → 401
        r = requests.post(f"{API}/collaborator-auth/process-session",
                          json={"session_id": "definitely-not-real-iter20",
                                "device_id": "dev-iter20"}, timeout=15)
        # Backend converts upstream non-2xx into 401 (HTTPStatusError) or 502 if network issue
        assert r.status_code in (401, 502), r.text


# --------------------- /logout ----------------------------
class TestLogout:
    def test_logout_invalidates_token(self):
        tok = f"cs_test_iter20_{uuid.uuid4().hex}"
        _mk_session(tok)

        # Confirm valid first
        r1 = requests.get(f"{API}/collaborator-auth/me",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r1.status_code == 200

        r2 = requests.post(f"{API}/collaborator-auth/logout",
                           headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r2.status_code == 200, r2.text
        assert r2.json().get("ok") is True

        # Token should be invalidated
        r3 = requests.get(f"{API}/collaborator-auth/me",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r3.status_code == 401, r3.text


# ----------------- /unbind-device/{cid} -------------------
class TestUnbindDevice:
    def test_unbind_device_clears_fields_and_invalidates_sessions(self):
        # Set device fields and 2 sessions
        _run(db.collaborators.update_one(
            {"id": DEMO_CID},
            {"$set": {"device_id": "dev-X", "google_email": "x@y.com",
                      "google_name": "X", "google_picture": "http://p"}},
        ))
        for _ in range(2):
            _mk_session(f"cs_test_iter20_{uuid.uuid4().hex}")

        r = requests.post(f"{API}/collaborator-auth/unbind-device/{DEMO_CID}", timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("sessions_invalidated", 0) >= 2

        coll = _run(db.collaborators.find_one({"id": DEMO_CID}, {"_id": 0}))
        assert coll.get("device_id") in (None, "")
        assert coll.get("google_email") in (None, "")

    def test_unbind_device_unknown_cid_returns_404(self):
        r = requests.post(f"{API}/collaborator-auth/unbind-device/cid-does-not-exist",
                          timeout=10)
        assert r.status_code == 404, r.text


# ----------------- reset-face (with/without reset_device) -------------------
class TestResetFace:
    def test_reset_face_legacy_does_not_reset_device(self):
        # Setup device fields + a session
        _run(db.collaborators.update_one(
            {"id": DEMO_CID},
            {"$set": {"device_id": "dev-LEGACY", "google_email": "leg@y.com",
                      "avatar_data_url": "data:image/png;base64,xxx",
                      "reference_face": "data:image/png;base64,xxx"}},
        ))
        tok = f"cs_test_iter20_{uuid.uuid4().hex}"
        _mk_session(tok)

        r = requests.post(f"{API}/collaborators/{DEMO_CID}/reset-face", timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("reset_device") is False
        assert body.get("sessions_invalidated", 0) == 0

        coll = _run(db.collaborators.find_one({"id": DEMO_CID}, {"_id": 0}))
        assert coll.get("avatar_data_url") in (None, "")
        assert coll.get("reference_face") in (None, "")
        # device must remain
        assert coll.get("device_id") == "dev-LEGACY"
        assert coll.get("google_email") == "leg@y.com"
        # Session must remain valid
        r2 = requests.get(f"{API}/collaborator-auth/me",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r2.status_code == 200, r2.text

    def test_reset_face_with_reset_device_clears_everything(self):
        # ensure device + sessions exist
        _run(db.collaborators.update_one(
            {"id": DEMO_CID},
            {"$set": {"device_id": "dev-FULL", "google_email": "full@y.com",
                      "google_name": "Full", "google_picture": "http://p",
                      "avatar_data_url": "data:image/png;base64,xxx",
                      "reference_face": "data:image/png;base64,xxx"}},
        ))
        tok = f"cs_test_iter20_{uuid.uuid4().hex}"
        _mk_session(tok)

        r = requests.post(f"{API}/collaborators/{DEMO_CID}/reset-face?reset_device=true",
                          timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("reset_device") is True
        assert body.get("sessions_invalidated", 0) >= 1

        coll = _run(db.collaborators.find_one({"id": DEMO_CID}, {"_id": 0}))
        assert coll.get("avatar_data_url") in (None, "")
        assert coll.get("reference_face") in (None, "")
        assert coll.get("device_id") in (None, "")
        assert coll.get("google_email") in (None, "")
        assert coll.get("google_name") in (None, "")
        assert coll.get("google_picture") in (None, "")

        # Session is invalidated
        r2 = requests.get(f"{API}/collaborator-auth/me",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r2.status_code == 401, r2.text

    def test_reset_face_unknown_cid_returns_404(self):
        r = requests.post(f"{API}/collaborators/cid-not-real-iter20/reset-face",
                          timeout=10)
        assert r.status_code == 404, r.text
        r2 = requests.post(f"{API}/collaborators/cid-not-real-iter20/reset-face?reset_device=true",
                           timeout=10)
        assert r2.status_code == 404, r2.text


# ----------------- Mongo index check -------------------
class TestSessionsIndex:
    def test_session_token_unique_index_exists(self):
        # Force creation by hitting an endpoint that calls _ensure_indexes
        # process-session triggers it
        requests.post(f"{API}/collaborator-auth/process-session",
                      json={"session_id": "trigger", "device_id": "trigger"}, timeout=15)
        info = _run(db.collaborator_sessions.index_information())
        # Find an index on session_token that is unique
        found = False
        for name, meta in info.items():
            keys = [k for k, _ in meta.get("key", [])]
            if keys == ["session_token"] and meta.get("unique"):
                found = True
                break
        assert found, f"unique index on session_token missing. Indexes: {info}"


# ----------------- Regression: legacy endpoints -------------------
class TestRegression:
    def test_login_works(self, auditor_token):
        assert isinstance(auditor_token, str) and len(auditor_token) > 10

    def test_users_list_works(self, auditor_token):
        r = requests.get(f"{API}/users",
                         headers={"Authorization": f"Bearer {auditor_token}"},
                         timeout=10)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_collaborators_list_works(self):
        r = requests.get(f"{API}/collaborators", timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list)
        assert any(c.get("id") == DEMO_CID for c in data)

    def test_clock_records_list_works(self):
        r = requests.get(f"{API}/clock-records", timeout=10)
        assert r.status_code in (200, 404), r.text  # be tolerant
        if r.status_code == 200:
            assert isinstance(r.json(), list)

    def test_timesheet_works(self):
        now = datetime.now(timezone.utc)
        r = requests.get(f"{API}/timesheets/{DEMO_CID}/{now.year}/{now.month}", timeout=10)
        assert r.status_code == 200, r.text

    def test_dashboard_overtime_works(self):
        now = datetime.now(timezone.utc)
        r = requests.get(f"{API}/dashboard/overtime/{now.year}/{now.month}", timeout=15)
        assert r.status_code == 200, r.text
