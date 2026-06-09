"""iter217 — Pre-Attendance Promos + WA Campaigns drafts API tests."""
import base64
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback for inside container
    with open("/app/frontend/.env") as fh:
        for ln in fh:
            if ln.startswith("REACT_APP_BACKEND_URL"):
                BASE_URL = ln.split("=", 1)[1].strip().rstrip("/")

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


# --- Auth fixture ---
@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
                      timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    j = r.json()
    tok = j.get("token") or j.get("access_token")
    assert tok, f"no token in response: {j}"
    return tok


@pytest.fixture(scope="module")
def H(token):
    return {"Authorization": f"Bearer {token}",
            "Content-Type": "application/json"}


# --- Pre-Attendance: CRUD ---
class TestPreAttendanceCRUD:
    promo_id = None

    def test_list_promos(self, H):
        r = requests.get(f"{BASE_URL}/api/pre-attendance/promos",
                         headers=H, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert "items" in j and "total" in j
        assert isinstance(j["items"], list)

    def test_create_promo(self, H):
        payload = {
            "title": "TEST_iter217 Upgrade Premium",
            "message_text": "Olá {primeiro_nome}, plano {plano}, upgrade!",
            "target_filter": "active",
            "weight": 3,
            "ai_enabled": True,
            "active": True,
        }
        r = requests.post(f"{BASE_URL}/api/pre-attendance/promos",
                          headers=H, json=payload, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["id"].startswith("promo-")
        assert j["title"] == payload["title"]
        assert j["weight"] == 3
        assert j["active"] is True
        TestPreAttendanceCRUD.promo_id = j["id"]

    def test_promo_persisted(self, H):
        pid = TestPreAttendanceCRUD.promo_id
        assert pid
        r = requests.get(f"{BASE_URL}/api/pre-attendance/promos",
                         headers=H, timeout=15)
        ids = [it["id"] for it in r.json()["items"]]
        assert pid in ids

    def test_update_promo(self, H):
        pid = TestPreAttendanceCRUD.promo_id
        payload = {
            "title": "TEST_iter217 Upgrade Premium V2",
            "message_text": "Atualizado!",
            "target_filter": "all",
            "weight": 5,
            "ai_enabled": False,
            "active": True,
        }
        r = requests.put(f"{BASE_URL}/api/pre-attendance/promos/{pid}",
                         headers=H, json=payload, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("ok") is True
        # verify
        r2 = requests.get(f"{BASE_URL}/api/pre-attendance/promos",
                          headers=H, timeout=15)
        found = next(it for it in r2.json()["items"] if it["id"] == pid)
        assert found["title"].endswith("V2")
        assert found["weight"] == 5
        assert found["ai_enabled"] is False

    def test_toggle_promo(self, H):
        pid = TestPreAttendanceCRUD.promo_id
        r = requests.post(
            f"{BASE_URL}/api/pre-attendance/promos/{pid}/toggle",
            headers=H, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert "active" in j
        # toggle back
        r2 = requests.post(
            f"{BASE_URL}/api/pre-attendance/promos/{pid}/toggle",
            headers=H, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["active"] != j["active"]

    def test_stats(self, H):
        r = requests.get(f"{BASE_URL}/api/pre-attendance/stats",
                         headers=H, timeout=15)
        assert r.status_code == 200
        j = r.json()
        for k in ("total_promos", "active_promos", "total_sent",
                  "total_replied", "reply_rate_pct", "ai_picks"):
            assert k in j, f"missing {k}"

    def test_delete_promo(self, H):
        pid = TestPreAttendanceCRUD.promo_id
        r = requests.delete(f"{BASE_URL}/api/pre-attendance/promos/{pid}",
                            headers=H, timeout=15)
        assert r.status_code == 200
        # verify removed
        r2 = requests.get(f"{BASE_URL}/api/pre-attendance/promos",
                          headers=H, timeout=15)
        ids = [it["id"] for it in r2.json()["items"]]
        assert pid not in ids


# --- Pre-Attendance: Upload + Image serve ---
class TestPreAttendanceUpload:
    filename = None

    def _png_b64(self):
        # minimal 1x1 PNG
        png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
               b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
               b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xfc\xff\xff"
               b"?\x00\x05\xfe\x02\xfe\xa75\x81\x84\x00\x00\x00\x00"
               b"IEND\xaeB`\x82") * 50  # ensure >32 bytes
        return base64.b64encode(png).decode("ascii")

    def test_upload_valid_png(self, H):
        b64 = self._png_b64()
        r = requests.post(
            f"{BASE_URL}/api/pre-attendance/upload-image",
            headers=H,
            json={"image_b64": b64, "filename": "TEST_iter217.png"},
            timeout=20)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is True
        assert j["url"].startswith("/api/pre-attendance/image/")
        assert j["size_bytes"] > 0
        TestPreAttendanceUpload.filename = j["filename"]

    def test_upload_with_data_uri_prefix(self, H):
        b64 = "data:image/png;base64," + self._png_b64()
        r = requests.post(
            f"{BASE_URL}/api/pre-attendance/upload-image",
            headers=H, json={"image_b64": b64}, timeout=20)
        assert r.status_code == 200

    def test_upload_invalid_too_small(self, H):
        r = requests.post(
            f"{BASE_URL}/api/pre-attendance/upload-image",
            headers=H,
            json={"image_b64": base64.b64encode(b"abc").decode()},
            timeout=15)
        assert r.status_code == 400

    def test_upload_too_large(self, H):
        # 6 MB of random-ish data
        big = base64.b64encode(b"x" * (6 * 1024 * 1024)).decode()
        r = requests.post(
            f"{BASE_URL}/api/pre-attendance/upload-image",
            headers=H, json={"image_b64": big}, timeout=30)
        assert r.status_code == 413

    def test_get_image(self):
        fn = TestPreAttendanceUpload.filename
        assert fn
        r = requests.get(f"{BASE_URL}/api/pre-attendance/image/{fn}",
                         timeout=15)
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert ct.startswith("image/"), f"got {ct}"

    def test_get_image_traversal_rejected(self):
        r = requests.get(
            f"{BASE_URL}/api/pre-attendance/image/..%2Fetc%2Fpasswd",
            timeout=15)
        # FastAPI may resolve %2F as / and route differently; backend
        # validates ".." and "/" — should return 400 or 404
        assert r.status_code in (400, 404)


# --- Service unit tests ---
class TestServiceUnits:
    def test_filter_matches_and_placeholders(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from services.pre_attendance_promo import (
            _filter_matches, _placeholders)

        sub = {"name": "Maria Silva", "status": "ATIVO",
               "financial_status": "inadimplente", "plan_id": "p1",
               "plan_name": "Fibra 500"}

        assert _filter_matches({"target_filter": "all"}, sub) is True
        assert _filter_matches({"target_filter": "active"}, sub) is True
        assert _filter_matches({"target_filter": "inactive"}, sub) is False
        assert _filter_matches(
            {"target_filter": "inadimplentes"}, sub) is True
        assert _filter_matches(
            {"target_filter": "by_plan", "target_plan_ids": ["p1"]},
            sub) is True
        assert _filter_matches(
            {"target_filter": "by_plan", "target_plan_ids": ["p9"]},
            sub) is False

        out = _placeholders(
            "Olá {primeiro_nome} {nome}, plano {plano}!", sub)
        assert "Maria" in out
        assert "Fibra 500" in out
        assert "Maria Silva" in out

    @pytest.mark.asyncio
    async def test_was_dispatched_recently(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from services.pre_attendance_promo import _was_dispatched_recently
        # should return False for fresh unknown phone
        r = await _was_dispatched_recently(
            "demo", "5500000000000_TEST_iter217")
        assert r is False


# --- WA Campaigns ---
class TestWACampaigns:
    draft_id = None

    def test_list_with_filter(self, H):
        for status in ("pending_approval", "dispatching",
                       "completed", "rejected"):
            r = requests.get(
                f"{BASE_URL}/api/wa-campaigns/drafts?status={status}",
                headers=H, timeout=15)
            assert r.status_code == 200, f"{status}: {r.text}"
            j = r.json()
            assert "items" in j

    def test_create_draft(self, H):
        payload = {
            "segment_name": "TEST_iter217 segmento",
            "template": "Oi {primeiro_nome}, mensagem teste!",
            "subscriber_ids": ["sub-1", "sub-2", "sub-3"],
        }
        r = requests.post(f"{BASE_URL}/api/wa-campaigns/drafts",
                          headers=H, json=payload, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["id"].startswith("camp-")
        assert j["status"] == "pending_approval"
        assert j["segment_name"] == payload["segment_name"]
        TestWACampaigns.draft_id = j["id"]

    def test_get_draft_detail(self, H):
        did = TestWACampaigns.draft_id
        r = requests.get(f"{BASE_URL}/api/wa-campaigns/drafts/{did}",
                         headers=H, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j["id"] == did
        assert "recipients_total" in j
        assert j["recipients_total"] == 3
        # recipients_preview should exist (may be empty if subs don't exist)
        assert "recipients_preview" in j or j["recipients_total"] == 0

    def test_edit_draft(self, H):
        did = TestWACampaigns.draft_id
        payload = {"template": "Edited template {primeiro_nome}",
                   "segment_name": "TEST_iter217 edited"}
        r = requests.put(f"{BASE_URL}/api/wa-campaigns/drafts/{did}",
                         headers=H, json=payload, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is True
        # verify
        r2 = requests.get(f"{BASE_URL}/api/wa-campaigns/drafts/{did}",
                          headers=H, timeout=15)
        assert r2.json()["template"].startswith("Edited")

    def test_approve_dispatch(self, H):
        # Create a second draft for approve test
        payload = {
            "segment_name": "TEST_iter217 approve",
            "template": "Approve test {primeiro_nome}",
            "subscriber_ids": ["sub-x"],
        }
        rc = requests.post(f"{BASE_URL}/api/wa-campaigns/drafts",
                           headers=H, json=payload, timeout=15)
        did = rc.json()["id"]
        r = requests.post(
            f"{BASE_URL}/api/wa-campaigns/drafts/{did}/approve",
            headers=H,
            json={"delay_min_sec": 2.0, "delay_max_sec": 5.0},
            timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is True
        assert j["queued"] == 1
        # status should be dispatching
        r2 = requests.get(f"{BASE_URL}/api/wa-campaigns/drafts/{did}",
                          headers=H, timeout=15)
        assert r2.json()["status"] in (
            "dispatching", "completed", "completed_partial", "failed")

    def test_approve_empty_recipients_fails(self, H):
        # create empty draft
        payload = {"segment_name": "TEST_iter217 empty",
                   "template": "x", "subscriber_ids": []}
        rc = requests.post(f"{BASE_URL}/api/wa-campaigns/drafts",
                           headers=H, json=payload, timeout=15)
        did = rc.json()["id"]
        r = requests.post(
            f"{BASE_URL}/api/wa-campaigns/drafts/{did}/approve",
            headers=H, json={"delay_min_sec": 2, "delay_max_sec": 5},
            timeout=15)
        assert r.status_code == 400

    def test_edit_after_dispatch_409(self, H):
        # use the first draft (still pending — we edited then never
        # approved) — approve it first, then try editing
        did = TestWACampaigns.draft_id
        # approve
        ra = requests.post(
            f"{BASE_URL}/api/wa-campaigns/drafts/{did}/approve",
            headers=H, json={"delay_min_sec": 2, "delay_max_sec": 5},
            timeout=15)
        # might already be in dispatching status, that's ok
        # attempt edit
        time.sleep(0.5)
        r = requests.put(
            f"{BASE_URL}/api/wa-campaigns/drafts/{did}",
            headers=H,
            json={"template": "should fail"}, timeout=15)
        # 409 expected (or 404 if already completed/changed)
        assert r.status_code in (409, 404), r.text

    def test_reject_draft(self, H):
        # create + reject
        payload = {"segment_name": "TEST_iter217 reject",
                   "template": "x", "subscriber_ids": ["sub-z"]}
        rc = requests.post(f"{BASE_URL}/api/wa-campaigns/drafts",
                           headers=H, json=payload, timeout=15)
        did = rc.json()["id"]
        r = requests.post(
            f"{BASE_URL}/api/wa-campaigns/drafts/{did}/reject",
            headers=H, timeout=15)
        assert r.status_code == 200
        # reject again — should 404
        r2 = requests.post(
            f"{BASE_URL}/api/wa-campaigns/drafts/{did}/reject",
            headers=H, timeout=15)
        assert r2.status_code == 404
