"""iter218 — Backend tests for Presidente IA V2.0 endpoints."""
from __future__ import annotations

import os
import time

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api/presidente-ia"

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASSWORD = "123456"

EXPECTED_AGENTS = {
    "alvaro", "isabella", "sentinela", "coach", "avaliador",
    "copilot", "secretaria", "rede", "smartolt", "financeiro",
    "parceiros", "clube_ligo", "gps", "seguranca",
}
EXPECTED_ROLES = {"ceo", "coo", "cto", "cfo", "cpo", "estrategista"}
EXPECTED_STATUSES = {"saudavel", "atencao", "alerta", "critico"}
EXPECTED_SEVERITIES = {"info", "warn", "alert", "critical"}


@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no token in response: {data}"
    return tok


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ───────────────── Auth required ─────────────────
class TestAuthRequired:
    def test_dashboard_requires_auth(self):
        r = requests.get(f"{API}/dashboard", timeout=20)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"

    def test_scan_requires_auth(self):
        r = requests.post(f"{API}/scan", timeout=20)
        assert r.status_code in (401, 403)

    def test_agents_requires_auth(self):
        r = requests.get(f"{API}/agents", timeout=20)
        assert r.status_code in (401, 403)

    def test_conselho_requires_auth(self):
        r = requests.get(f"{API}/conselho", timeout=20)
        assert r.status_code in (401, 403)


# ───────────────── Agents catalog ─────────────────
class TestAgents:
    def test_agents_returns_14(self, auth):
        r = requests.get(f"{API}/agents", headers=auth, timeout=20)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert "items" in data
        assert data["total"] == 14
        assert len(data["items"]) == 14
        ids = {a["id"] for a in data["items"]}
        assert ids == EXPECTED_AGENTS, f"missing/extra agents: {ids ^ EXPECTED_AGENTS}"
        for a in data["items"]:
            assert {"id", "label", "group", "color"}.issubset(a.keys()), a
            assert a["color"].startswith("#")


# ───────────────── Dashboard ─────────────────
class TestDashboard:
    def test_dashboard_shape(self, auth):
        r = requests.get(f"{API}/dashboard", headers=auth, timeout=60)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        # required top keys
        for k in ("agents", "health", "risks", "opportunities",
                  "clients_at_risk", "network", "attendance",
                  "commercial", "universo_ligo", "generated_at"):
            assert k in d, f"missing key: {k}"
        # agents
        assert len(d["agents"]) == 14
        # health
        h = d["health"]
        assert isinstance(h["score"], (int, float))
        assert 0 <= h["score"] <= 100
        assert h["status"] in EXPECTED_STATUSES, h
        # risks contains the 4 levels
        risks = d["risks"]
        for level in ("criticos", "altos", "medios", "baixos"):
            assert level in risks, f"risks missing {level}: {risks.keys()}"
        # opportunities
        opps = d["opportunities"]
        assert "items" in opps
        assert "receita_potencial_brl" in opps
        assert isinstance(opps["receita_potencial_brl"], (int, float))
        # clients_at_risk list (<=15)
        assert isinstance(d["clients_at_risk"], list)
        assert len(d["clients_at_risk"]) <= 15

    def test_health_status_thresholds(self, auth):
        r = requests.get(f"{API}/dashboard", headers=auth, timeout=60)
        h = r.json()["health"]
        s, st = h["score"], h["status"]
        if s >= 80:
            assert st == "saudavel"
        elif s >= 60:
            assert st == "atencao"
        elif s >= 40:
            assert st == "alerta"
        else:
            assert st == "critico"


# ───────────────── Scan + Predictions/Events ─────────────────
class TestScan:
    def test_scan_runs(self, auth):
        r = requests.post(f"{API}/scan", headers=auth, timeout=90)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert d.get("ok") is True, d
        assert "elapsed_ms" in d
        for k in ("health", "risks", "opportunities", "predictions", "correlations"):
            assert k in d, f"scan missing {k}"

    def test_events_after_scan(self, auth):
        r = requests.get(f"{API}/events?limit=50", headers=auth, timeout=30)
        assert r.status_code == 200
        items = r.json()["items"]
        assert isinstance(items, list)
        # severities should be valid when present
        for ev in items:
            if "severity" in ev:
                assert ev["severity"] in EXPECTED_SEVERITIES or ev["severity"] == ""

    def test_events_severity_filter(self, auth):
        r = requests.get(f"{API}/events?severity=info&limit=20", headers=auth, timeout=30)
        assert r.status_code == 200
        for ev in r.json()["items"]:
            assert ev.get("severity") == "info"

    def test_predictions_sorted(self, auth):
        r = requests.get(f"{API}/predictions?limit=50", headers=auth, timeout=30)
        assert r.status_code == 200
        items = r.json()["items"]
        # may be empty in fresh env but iter218 ran scan
        scores = [it.get("score", 0) for it in items]
        for s in scores:
            assert 0 <= s <= 100
        assert scores == sorted(scores, reverse=True), "predictions must be desc by score"


# ───────────────── Insights / Decisions / Actions ─────────────────
class TestStreams:
    def test_insights_open_only(self, auth):
        r = requests.get(f"{API}/insights", headers=auth, timeout=30)
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert it.get("status") == "open", f"non-open insight returned: {it.get('status')}"

    def test_decisions_endpoint(self, auth):
        r = requests.get(f"{API}/decisions", headers=auth, timeout=30)
        assert r.status_code == 200
        assert "items" in r.json()

    def test_actions_endpoint(self, auth):
        r = requests.get(f"{API}/actions", headers=auth, timeout=30)
        assert r.status_code == 200
        assert "items" in r.json()


# ───────────────── Conselho Executivo ─────────────────
class TestConselho:
    def test_conselho_returns_6(self, auth):
        t0 = time.time()
        r = requests.get(f"{API}/conselho", headers=auth, timeout=120)
        elapsed = time.time() - t0
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        items = d["items"]
        assert len(items) == 6
        roles = {i["role"] for i in items}
        assert roles == EXPECTED_ROLES, f"roles mismatch: {roles ^ EXPECTED_ROLES}"
        for it in items:
            for k in ("role", "label", "color", "parecer", "from_cache", "model"):
                assert k in it, f"missing {k} in {it.get('role')}: {list(it.keys())}"
            assert isinstance(it["parecer"], str)
            assert len(it["parecer"].strip()) > 0, f"empty parecer for {it['role']}"
        print(f"[conselho first/cache mixed] elapsed={elapsed:.1f}s")

    def test_conselho_cache_second_call_fast(self, auth):
        # Prime
        requests.get(f"{API}/conselho", headers=auth, timeout=120)
        t0 = time.time()
        r = requests.get(f"{API}/conselho", headers=auth, timeout=30)
        elapsed = time.time() - t0
        assert r.status_code == 200
        items = r.json()["items"]
        assert all(it.get("from_cache") is True for it in items), \
            f"expected all cached: {[(i['role'], i.get('from_cache')) for i in items]}"
        assert elapsed < 5.0, f"cached call took {elapsed:.2f}s (>5s)"
        print(f"[conselho cached] elapsed={elapsed:.2f}s")

    def test_conselho_role_unknown_404(self, auth):
        r = requests.post(f"{API}/conselho/foobar", headers=auth, timeout=20)
        assert r.status_code == 404

    def test_conselho_role_specific(self, auth):
        r = requests.post(f"{API}/conselho/ceo?force=false", headers=auth, timeout=120)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert d["role"] == "ceo"
        assert isinstance(d.get("parecer"), str) and len(d["parecer"].strip()) > 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
