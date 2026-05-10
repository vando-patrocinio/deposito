"""Iteration 43 — Central IA Dashboard tests."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tk = r.json().get("access_token") or r.json().get("token")
    assert tk, f"no token in: {r.json()}"
    return tk


@pytest.fixture(scope="module")
def hdr(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------- Central IA KPIs ----------------
class TestCentralIaKpis:
    def test_kpis_default_7d(self, hdr):
        r = requests.get(f"{BASE_URL}/api/central-ia/dashboard/kpis?days=7",
                         headers=hdr, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ["days", "total_conversations", "csat_avg", "frt_avg_seconds",
                  "fcr_rate", "arr_rate", "sentiment", "no_data"]:
            assert k in d, f"missing key {k}"
        assert d["days"] == 7
        assert isinstance(d["sentiment"], dict)
        for s in ["positivo", "neutro", "negativo"]:
            assert s in d["sentiment"]
        if not d["no_data"]:
            assert d["total_conversations"] > 0
            if d["csat_avg"] is not None:
                assert 0 <= d["csat_avg"] <= 10
            if d["fcr_rate"] is not None:
                assert 0 <= d["fcr_rate"] <= 100
            if d["arr_rate"] is not None:
                assert 0 <= d["arr_rate"] <= 100

    def test_kpis_30d_param(self, hdr):
        r = requests.get(f"{BASE_URL}/api/central-ia/dashboard/kpis?days=30",
                         headers=hdr, timeout=20)
        assert r.status_code == 200
        assert r.json()["days"] == 30

    def test_kpis_invalid_days(self, hdr):
        r = requests.get(f"{BASE_URL}/api/central-ia/dashboard/kpis?days=999",
                         headers=hdr, timeout=10)
        assert r.status_code == 422

    def test_kpis_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/central-ia/dashboard/kpis?days=7", timeout=10)
        assert r.status_code in (401, 403)


# ---------------- Attendants ranking ----------------
class TestCentralIaAttendants:
    def test_attendants_ranking(self, hdr):
        r = requests.get(f"{BASE_URL}/api/central-ia/dashboard/attendants?days=7",
                         headers=hdr, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "items" in d
        assert isinstance(d["items"], list)
        for it in d["items"]:
            for k in ["user_id", "name", "is_ai", "volume", "csat_avg",
                      "fcr_rate", "frt_avg_seconds", "negative_count"]:
                assert k in it, f"missing {k} in attendant item"
            assert isinstance(it["volume"], int)
        # Isabella (IA) should be present if there are AI-only conversations
        ai_items = [i for i in d["items"] if i.get("is_ai")]
        if d["items"]:
            # at least one should be Isabella IA
            assert any("Isabella" in (i.get("name") or "") for i in ai_items) or len(ai_items) == 0


# ---------------- Intents ----------------
class TestCentralIaIntents:
    def test_intents(self, hdr):
        r = requests.get(f"{BASE_URL}/api/central-ia/dashboard/intents?days=7",
                         headers=hdr, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "items" in d and "total" in d
        for it in d["items"]:
            for k in ["intent", "count", "pct", "csat_avg"]:
                assert k in it
            assert isinstance(it["count"], int)
            assert 0 <= it["pct"] <= 100
        counts = [i["count"] for i in d["items"]]
        assert counts == sorted(counts, reverse=True), "items must be sorted by count desc"


# ---------------- Alerts ----------------
class TestCentralIaAlerts:
    def test_alerts(self, hdr):
        r = requests.get(f"{BASE_URL}/api/central-ia/alerts", headers=hdr, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "items" in d
        for a in d["items"]:
            for k in ["id", "kind", "severity", "title"]:
                assert k in a, f"missing {k}"
            assert a["severity"] in ("critical", "warning", "info")


# ---------------- Evaluations ----------------
class TestCentralIaEvaluations:
    def test_list_evaluations(self, hdr):
        r = requests.get(f"{BASE_URL}/api/central-ia/evaluations", headers=hdr, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "items" in d and "count" in d
        if d["items"]:
            it = d["items"][0]
            for k in ["csat_score", "sentiment", "fcr",
                      "resolution_outcome", "intent_category",
                      "summary", "frt_seconds"]:
                assert k in it, f"missing {k} in evaluation"

    def test_evaluate_now_short_conversation_returns_400(self, hdr):
        # Use a phone that doesn't exist / has 0 messages -> 400
        r = requests.post(f"{BASE_URL}/api/central-ia/evaluations/55999999999999",
                          headers=hdr, timeout=30)
        assert r.status_code == 400

    def test_evaluate_now_real_phone(self, hdr):
        # Find a phone with >=2 msgs from conversations endpoint
        rconv = requests.get(f"{BASE_URL}/api/whatsapp-baileys/conversations",
                             headers=hdr, timeout=20)
        if rconv.status_code != 200:
            pytest.skip("no conversations endpoint")
        items = rconv.json().get("items") or []
        target_phone = None
        for c in items:
            phone = c.get("phone")
            if not phone:
                continue
            rmsg = requests.get(
                f"{BASE_URL}/api/whatsapp-baileys/conversations/{phone}/messages",
                headers=hdr, timeout=15)
            if rmsg.status_code == 200 and len(rmsg.json().get("items") or []) >= 2:
                target_phone = phone
                break
        if not target_phone:
            pytest.skip("no phone with >=2 messages found")
        r = requests.post(f"{BASE_URL}/api/central-ia/evaluations/{target_phone}",
                          headers=hdr, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ["csat_score", "sentiment", "fcr",
                  "intent_category", "summary", "is_ai_only"]:
            assert k in d


# ---------------- Summary ----------------
class TestCentralIaSummary:
    def test_summary(self, hdr):
        r = requests.get(f"{BASE_URL}/api/central-ia/dashboard/summary",
                         headers=hdr, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ["evaluated_24h", "alerts_24h", "csat_avg_24h"]:
            assert k in d


# ---------------- Regression ----------------
class TestRegression:
    def test_qr(self, hdr):
        r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/qr", headers=hdr, timeout=15)
        assert r.status_code in (200, 202, 503)

    def test_conversations(self, hdr):
        r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/conversations",
                         headers=hdr, timeout=15)
        assert r.status_code == 200
        assert "items" in r.json()

    def test_voice_sessions_start(self, hdr):
        r = requests.post(f"{BASE_URL}/api/voice/sessions/start",
                          headers=hdr, json={}, timeout=20)
        assert r.status_code in (200, 201)

    def test_aihub_text_gen(self, hdr):
        r = requests.post(f"{BASE_URL}/api/aihub/agents/text-gen",
                          headers=hdr,
                          json={"field": "company_info", "mode": "gerar",
                                "current_text": "",
                                "context": "Provedor de internet em SP"},
                          timeout=60)
        assert r.status_code == 200, r.text
        assert "text" in r.json()
