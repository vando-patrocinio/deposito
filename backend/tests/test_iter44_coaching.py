"""Iteration 44 — Central IA Coaching tests."""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, f"login: {r.status_code} {r.text}"
    tk = r.json().get("access_token") or r.json().get("token")
    assert tk
    return tk


@pytest.fixture(scope="module")
def hdr(token):
    return {"Authorization": f"Bearer {token}"}


# --------- helpers ----------
def _find_human_phone(hdr):
    """Returns a phone that has at least one human outbound + inbound message."""
    r = requests.get(f"{BASE_URL}/api/central-ia/evaluations", headers=hdr, timeout=20)
    if r.status_code != 200:
        return None
    for e in r.json().get("items", []):
        if (not e.get("is_ai_only")) and e.get("assignee_user_id") and e.get("phone"):
            return e["phone"]
    return None


def _find_ai_only_phone(hdr):
    r = requests.get(f"{BASE_URL}/api/central-ia/evaluations", headers=hdr, timeout=20)
    if r.status_code != 200:
        return None
    for e in r.json().get("items", []):
        if e.get("is_ai_only") and e.get("phone"):
            return e["phone"]
    return None


# ---------------- Coaching list ----------------
class TestCoachingList:
    def test_coaching_list_shape(self, hdr):
        r = requests.get(f"{BASE_URL}/api/central-ia/coaching", headers=hdr, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "items" in d and "count" in d
        assert isinstance(d["items"], list)
        if d["items"]:
            it = d["items"][0]
            for k in ["id", "score", "tone", "strengths", "improvements",
                      "next_action", "csat_at_time", "user_id", "user_name",
                      "read", "acknowledged"]:
                assert k in it, f"missing {k} in coaching item"
            assert it["tone"] in ("positivo", "construtivo", "urgente")
            assert isinstance(it["strengths"], list)
            assert 1 <= len(it["strengths"]) <= 3
            assert isinstance(it["improvements"], list)
            assert 2 <= len(it["improvements"]) <= 5
            assert isinstance(it["score"], (int, float))
            assert 0 <= it["score"] <= 10

    def test_coaching_unread_only(self, hdr):
        r = requests.get(f"{BASE_URL}/api/central-ia/coaching?unread_only=true",
                         headers=hdr, timeout=20)
        assert r.status_code == 200
        for it in r.json().get("items", []):
            assert not it.get("read"), "unread_only should not return read=True items"

    def test_coaching_filter_by_user(self, hdr):
        # First get any coaching to find a user_id
        r = requests.get(f"{BASE_URL}/api/central-ia/coaching", headers=hdr, timeout=20)
        items = r.json().get("items", [])
        if not items:
            pytest.skip("no coachings to filter by user")
        uid = items[0].get("user_id")
        if not uid:
            pytest.skip("no user_id")
        r2 = requests.get(f"{BASE_URL}/api/central-ia/coaching?user_id={uid}",
                          headers=hdr, timeout=20)
        assert r2.status_code == 200
        for it in r2.json().get("items", []):
            assert it.get("user_id") == uid

    def test_coaching_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/central-ia/coaching", timeout=10)
        assert r.status_code in (401, 403)


# ---------------- Coaching by-user ----------------
class TestCoachingByUser:
    def test_by_user_shape(self, hdr):
        r = requests.get(f"{BASE_URL}/api/central-ia/coaching/by-user",
                         headers=hdr, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "items" in d
        for it in d["items"]:
            for k in ["user_id", "user_name", "count", "avg_score",
                      "tones", "unread", "ack"]:
                assert k in it, f"missing {k}"
            assert isinstance(it["tones"], dict)
            for t in ("positivo", "construtivo", "urgente"):
                assert t in it["tones"]
            assert it["count"] >= 1
            assert 0 <= it["avg_score"] <= 10


# ---------------- Generate now (real LLM, slow) ----------------
class TestCoachingGenerate:
    def test_generate_for_ai_only_returns_400_with_IA(self, hdr):
        ai_phone = _find_ai_only_phone(hdr)
        if not ai_phone:
            pytest.skip("no AI-only conversation found")
        r = requests.post(f"{BASE_URL}/api/central-ia/coaching/generate",
                          headers=hdr, json={"phone": ai_phone}, timeout=90)
        assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text}"
        detail = (r.json().get("detail") or "").lower()
        assert "ia" in detail, f"detail should mention IA, got: {detail}"

    def test_generate_for_human_returns_doc(self, hdr):
        ph = _find_human_phone(hdr)
        if not ph:
            pytest.skip("no human-handled conversation found")
        r = requests.post(f"{BASE_URL}/api/central-ia/coaching/generate",
                          headers=hdr, json={"phone": ph}, timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ["id", "score", "tone", "strengths", "improvements",
                  "next_action", "csat_at_time", "user_id", "user_name",
                  "read", "acknowledged"]:
            assert k in d, f"missing {k}"
        assert d["tone"] in ("positivo", "construtivo", "urgente")
        assert d["read"] is False
        assert d["acknowledged"] is False
        assert 1 <= len(d["strengths"]) <= 3
        assert 2 <= len(d["improvements"]) <= 5


# ---------------- Coaching action ----------------
class TestCoachingAction:
    def _new_coach(self, hdr):
        """Create a fresh coaching by calling generate. Returns id."""
        ph = _find_human_phone(hdr)
        if not ph:
            return None
        r = requests.post(f"{BASE_URL}/api/central-ia/coaching/generate",
                          headers=hdr, json={"phone": ph}, timeout=120)
        if r.status_code != 200:
            return None
        return r.json().get("id")

    def test_action_acknowledged(self, hdr):
        cid = self._new_coach(hdr)
        if not cid:
            pytest.skip("could not create coaching to ack")
        r = requests.post(f"{BASE_URL}/api/central-ia/coaching/action",
                          headers=hdr,
                          json={"coaching_id": cid, "action": "acknowledged"},
                          timeout=15)
        assert r.status_code == 200, r.text
        # Verify via list
        r2 = requests.get(f"{BASE_URL}/api/central-ia/coaching",
                          headers=hdr, timeout=15)
        found = next((x for x in r2.json()["items"] if x["id"] == cid), None)
        assert found is not None
        assert found.get("read") is True
        assert found.get("acknowledged") is True
        assert found.get("acknowledged_at")

    def test_action_read(self, hdr):
        cid = self._new_coach(hdr)
        if not cid:
            pytest.skip("could not create coaching to mark read")
        r = requests.post(f"{BASE_URL}/api/central-ia/coaching/action",
                          headers=hdr,
                          json={"coaching_id": cid, "action": "read"},
                          timeout=15)
        assert r.status_code == 200
        r2 = requests.get(f"{BASE_URL}/api/central-ia/coaching",
                          headers=hdr, timeout=15)
        found = next((x for x in r2.json()["items"] if x["id"] == cid), None)
        assert found is not None
        assert found.get("read") is True
        assert not found.get("acknowledged"), "read action should NOT set acknowledged"

    def test_action_dismiss(self, hdr):
        cid = self._new_coach(hdr)
        if not cid:
            pytest.skip("could not create coaching to dismiss")
        r = requests.post(f"{BASE_URL}/api/central-ia/coaching/action",
                          headers=hdr,
                          json={"coaching_id": cid, "action": "dismiss"},
                          timeout=15)
        assert r.status_code == 200
        r2 = requests.get(f"{BASE_URL}/api/central-ia/coaching",
                          headers=hdr, timeout=15)
        found = next((x for x in r2.json()["items"] if x["id"] == cid), None)
        assert found is not None
        assert found.get("read") is True
        assert found.get("dismissed") is True

    def test_action_invalid(self, hdr):
        r = requests.post(f"{BASE_URL}/api/central-ia/coaching/action",
                          headers=hdr,
                          json={"coaching_id": "fake", "action": "bogus"},
                          timeout=10)
        assert r.status_code == 400

    def test_action_not_found(self, hdr):
        r = requests.post(f"{BASE_URL}/api/central-ia/coaching/action",
                          headers=hdr,
                          json={"coaching_id": f"nope-{uuid.uuid4().hex}",
                                "action": "read"},
                          timeout=10)
        assert r.status_code == 404


# ---------------- Auto-trigger inside _evaluate_conversation ----------------
class TestAutoTrigger:
    def test_auto_trigger_on_evaluate(self, hdr):
        """When csat<7 + human + assignee, /evaluations/{phone} must auto-create coaching."""
        ph = _find_human_phone(hdr)
        if not ph:
            pytest.skip("no human-handled conversation")
        # Snapshot existing coachings for this phone
        before = requests.get(f"{BASE_URL}/api/central-ia/coaching",
                              headers=hdr, timeout=15).json().get("items", [])
        before_count_phone = sum(1 for c in before if c.get("phone") == ph)

        r = requests.post(f"{BASE_URL}/api/central-ia/evaluations/{ph}",
                          headers=hdr, timeout=120)
        assert r.status_code == 200, r.text
        ev = r.json()
        # Only if csat < 7 the auto-trigger should fire
        if ev.get("csat_score", 10) >= 7:
            pytest.skip(f"CSAT={ev.get('csat_score')} >=7 — no auto-coaching expected")
        # Wait a bit (LLM call inside)
        time.sleep(2)
        after = requests.get(f"{BASE_URL}/api/central-ia/coaching",
                             headers=hdr, timeout=15).json().get("items", [])
        after_count_phone = sum(1 for c in after if c.get("phone") == ph)
        assert after_count_phone > before_count_phone, \
            f"coaching count for {ph} did not increase ({before_count_phone}->{after_count_phone})"


# ---------------- Regression ----------------
class TestRegression:
    def test_kpis(self, hdr):
        r = requests.get(f"{BASE_URL}/api/central-ia/dashboard/kpis?days=7",
                         headers=hdr, timeout=20)
        assert r.status_code == 200

    def test_attendants(self, hdr):
        r = requests.get(f"{BASE_URL}/api/central-ia/dashboard/attendants?days=7",
                         headers=hdr, timeout=20)
        assert r.status_code == 200

    def test_intents(self, hdr):
        r = requests.get(f"{BASE_URL}/api/central-ia/dashboard/intents?days=7",
                         headers=hdr, timeout=20)
        assert r.status_code == 200

    def test_alerts(self, hdr):
        r = requests.get(f"{BASE_URL}/api/central-ia/alerts", headers=hdr, timeout=15)
        assert r.status_code == 200

    def test_evaluations(self, hdr):
        r = requests.get(f"{BASE_URL}/api/central-ia/evaluations",
                         headers=hdr, timeout=15)
        assert r.status_code == 200

    def test_wa_qr(self, hdr):
        r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/qr",
                         headers=hdr, timeout=15)
        assert r.status_code in (200, 202, 503)

    def test_wa_conversations(self, hdr):
        r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/conversations",
                         headers=hdr, timeout=15)
        assert r.status_code == 200
