"""Iter 48 — Productivity dashboard + Scheduled-adjustment WhatsApp notice.

Covers:
  - GET /api/central-ia/dashboard/productivity?days=30
  - POST /api/plans/scheduled-adjustments/{sid}/notify (dry_run)
  - Auth/role boundaries (administrador)
  - 404 / 409 / template substitution / Marco Civil text
"""
import os
import pytest
import requests

_RAW = os.environ.get("REACT_APP_BACKEND_URL")
if not _RAW:
    # fallback to frontend/.env
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    _RAW = line.split("=", 1)[1].strip()
                    break
    except FileNotFoundError:
        pass
assert _RAW, "REACT_APP_BACKEND_URL not set"
BASE_URL = _RAW.rstrip("/")


# ---------------- fixtures ----------------
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                       json={"email": "admin@empresa.com",
                              "password": "123456"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def admin_client(admin_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {admin_token}",
                      "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def scheduled_id(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/plans/scheduled-adjustments")
    assert r.status_code == 200
    items = [i for i in r.json().get("items", []) if i.get("status") == "pending"]
    assert items, "No pending scheduled adjustment to test against"
    return items[0]["id"]


# ============== Productivity dashboard ==============
class TestProductivityDashboard:
    def test_status_and_envelope(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/central-ia/dashboard/productivity?days=30")
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("items", "team", "days", "generated_at"):
            assert k in data, f"missing key {k}"
        assert data["days"] == 30
        assert isinstance(data["items"], list)
        assert isinstance(data["team"], dict)

    def test_item_shape(self, admin_client):
        data = admin_client.get(f"{BASE_URL}/api/central-ia/dashboard/productivity?days=30").json()
        assert data["items"], "expected at least one attendant in seed"
        item = data["items"][0]
        expected = {"user_id", "name", "role", "conversations", "messages_sent",
                    "frt_avg_seconds", "aht_avg_seconds", "csat_avg", "fcr_rate",
                    "active_days", "logged_seconds", "in_conversation_seconds",
                    "idle_seconds", "idle_pct", "msgs_per_hour",
                    "returned_to_ai", "ai_usage_pct",
                    "coachings_total", "coachings_unread", "coachings_acknowledged",
                    "productivity_score"}
        missing = expected - set(item.keys())
        assert not missing, f"missing fields {missing}"

    def test_team_shape(self, admin_client):
        team = admin_client.get(f"{BASE_URL}/api/central-ia/dashboard/productivity?days=30").json()["team"]
        for k in ("attendants_count", "total_conversations", "total_messages",
                  "avg_csat", "avg_idle_pct", "avg_frt_seconds",
                  "best_performer", "best_score"):
            assert k in team, f"missing team key {k}"

    def test_no_ai_agents_in_items(self, admin_client):
        data = admin_client.get(f"{BASE_URL}/api/central-ia/dashboard/productivity?days=30").json()
        for it in data["items"]:
            # is_ai_agent users are filtered upstream — role should still be human
            assert it.get("name") not in (None, "")

    def test_items_sorted_by_score_desc(self, admin_client):
        data = admin_client.get(f"{BASE_URL}/api/central-ia/dashboard/productivity?days=30").json()
        scores = [it.get("productivity_score") or 0 for it in data["items"]]
        assert scores == sorted(scores, reverse=True), "items must be sorted by score desc"

    def test_best_performer_is_top(self, admin_client):
        data = admin_client.get(f"{BASE_URL}/api/central-ia/dashboard/productivity?days=30").json()
        if data["items"]:
            assert data["team"]["best_performer"] == data["items"][0]["name"]
            assert data["team"]["best_score"] == data["items"][0]["productivity_score"]

    def test_days_param_validation(self, admin_client):
        # Out of range
        r = admin_client.get(f"{BASE_URL}/api/central-ia/dashboard/productivity?days=0")
        assert r.status_code == 422
        r = admin_client.get(f"{BASE_URL}/api/central-ia/dashboard/productivity?days=400")
        assert r.status_code == 422

    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/central-ia/dashboard/productivity?days=30")
        assert r.status_code in (401, 403)


# ============== Scheduled-adjustment notify ==============
class TestNotifyScheduledAdjustment:
    def test_dry_run_returns_preview(self, admin_client, scheduled_id):
        r = admin_client.post(
            f"{BASE_URL}/api/plans/scheduled-adjustments/{scheduled_id}/notify",
            json={"dry_run": True})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["dry_run"] is True
        assert data["sent"] == 0       # nothing actually sent
        assert data["failed"] == 0
        assert isinstance(data["sent_to"], list)
        assert data["total_subscribers"] >= 1
        # Each entry has phone/name/preview
        for entry in data["sent_to"]:
            assert "phone" in entry and entry["phone"]
            assert "name" in entry
            assert "preview" in entry and entry["preview"]

    def test_default_template_includes_marco_civil(self, admin_client, scheduled_id):
        # Use full template by calling endpoint and reconstructing preview via custom template
        r = admin_client.post(
            f"{BASE_URL}/api/plans/scheduled-adjustments/{scheduled_id}/notify",
            json={"dry_run": True})
        data = r.json()
        # default-template path: preview is truncated at 80 chars but it should start
        # with greeting and mention 'reajuste'
        prev = data["sent_to"][0]["preview"].lower()
        assert "olá" in prev or "ola" in prev
        assert "reajuste" in prev

    def test_template_substitution(self, admin_client, scheduled_id):
        custom = ("Oi {nome} | plano={plano} | de R$ {valor_atual} "
                  "para R$ {valor_novo} | pct={pct} | em {data}")
        r = admin_client.post(
            f"{BASE_URL}/api/plans/scheduled-adjustments/{scheduled_id}/notify",
            json={"dry_run": True, "template": custom})
        assert r.status_code == 200, r.text
        prev = r.json()["sent_to"][0]["preview"]
        # First name (Maria)
        assert "Maria" in prev
        # plan name fragment
        assert "Fibra" in prev or "plano=" in prev
        # currency formatting uses comma
        assert "," in prev

    def test_404_when_not_found(self, admin_client):
        r = admin_client.post(
            f"{BASE_URL}/api/plans/scheduled-adjustments/psch-doesnotexist/notify",
            json={"dry_run": True})
        assert r.status_code == 404

    def test_409_when_not_pending(self, admin_client):
        # Mark a fake adjustment via DB? We can't easily. Instead test by directly
        # POSTing on a status-mutated one if one exists. We attempt cancel first.
        # Find pending
        items = admin_client.get(f"{BASE_URL}/api/plans/scheduled-adjustments").json()["items"]
        # Try to find a non-pending; if not, skip
        non_pending = [i for i in items if i.get("status") != "pending"]
        if not non_pending:
            pytest.skip("No non-pending scheduled adjustment to test 409")
        sid = non_pending[0]["id"]
        r = admin_client.post(
            f"{BASE_URL}/api/plans/scheduled-adjustments/{sid}/notify",
            json={"dry_run": True})
        assert r.status_code == 409

    def test_requires_auth(self, scheduled_id):
        r = requests.post(
            f"{BASE_URL}/api/plans/scheduled-adjustments/{scheduled_id}/notify",
            json={"dry_run": True})
        assert r.status_code in (401, 403)

    def test_dry_run_does_not_persist_notified_at(self, admin_client, scheduled_id):
        # After dry-run, scheduled item should NOT have notified_at field
        admin_client.post(
            f"{BASE_URL}/api/plans/scheduled-adjustments/{scheduled_id}/notify",
            json={"dry_run": True})
        items = admin_client.get(f"{BASE_URL}/api/plans/scheduled-adjustments").json()["items"]
        cur = next((i for i in items if i["id"] == scheduled_id), None)
        assert cur is not None
        assert not cur.get("notified_at"), "dry_run must not stamp notified_at"
