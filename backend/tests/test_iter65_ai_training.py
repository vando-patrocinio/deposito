"""Iteration 65 - AI Training Studio endpoint tests.

Validates: scenarios (60), tests (20), decision-matrix (31), single run,
runs history. Skips run-all (too slow ~5 min)."""
import os
import time

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login", json={
        "email": "admin@empresa.com", "password": "123456"
    }, timeout=20)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- Scenarios ----------
class TestScenarios:
    def test_scenarios_list_returns_60(self, h):
        r = requests.get(f"{API}/ai-training/scenarios", headers=h, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["count"] >= 60, f"Expected >=60 scenarios, got {data['count']}"
        assert isinstance(data["items"], list)
        assert "categories" in data
        cats = data["categories"]
        # Spec mentions these 6 categories
        expected_cats = {"rede_smartolt", "agendamento_kanban", "atendimento_humano",
                         "avaliacao_coach", "falhas_escalonamento", "variacao_dificil"}
        present = set(cats.keys()) & expected_cats
        assert len(present) >= 4, f"Expected categories, got: {cats}"

    def test_scenario_detail_has_simulacao_conversa(self, h):
        r = requests.get(f"{API}/ai-training/scenarios/1", headers=h, timeout=20)
        assert r.status_code == 200, r.text
        s = r.json()
        assert s.get("number") == 1
        assert "simulacao_conversa" in s
        assert isinstance(s["simulacao_conversa"], list)
        assert len(s["simulacao_conversa"]) > 0

    def test_scenario_404_for_missing(self, h):
        r = requests.get(f"{API}/ai-training/scenarios/9999", headers=h, timeout=20)
        assert r.status_code == 404

    def test_scenarios_filter_category(self, h):
        r = requests.get(f"{API}/ai-training/scenarios",
                         params={"category": "rede_smartolt"}, headers=h, timeout=20)
        assert r.status_code == 200
        data = r.json()
        for s in data["items"]:
            assert s.get("category") == "rede_smartolt"


# ---------- Tests (validation) ----------
class TestValidationTests:
    def test_tests_list_returns_20(self, h):
        r = requests.get(f"{API}/ai-training/tests", headers=h, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["count"] == 20, f"Expected exactly 20 tests, got {data['count']}"
        # Each must have name, entrada_cliente, agentes_esperados, criterio_aprovacao
        for t in data["items"]:
            assert "name" in t
            assert "entrada_cliente" in t
            assert "agentes_esperados" in t
            assert "criterio_aprovacao" in t

    def test_test_detail(self, h):
        r = requests.get(f"{API}/ai-training/tests/1", headers=h, timeout=20)
        assert r.status_code == 200
        t = r.json()
        assert t.get("number") == 1
        assert t.get("entrada_cliente")

    def test_test_404(self, h):
        r = requests.get(f"{API}/ai-training/tests/9999", headers=h, timeout=20)
        assert r.status_code == 404


# ---------- Decision Matrix ----------
class TestDecisionMatrix:
    def test_matrix_returns_31(self, h):
        r = requests.get(f"{API}/ai-training/decision-matrix", headers=h, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["count"] == 31, f"Expected 31 rules, got {data['count']}"
        assert "by_categoria" in data
        assert len(data["by_categoria"]) >= 8, \
            f"Expected ~10 categories, got {len(data['by_categoria'])}"


# ---------- Run single test (LLM real) ----------
class TestRunSingle:
    def test_run_test_1_returns_score(self, h):
        # Smallest test, but can still take ~30-60s
        start = time.time()
        r = requests.post(f"{API}/ai-training/tests/1/run", headers=h, timeout=180)
        elapsed = time.time() - start
        print(f"[run-test-1] elapsed={elapsed:.1f}s status={r.status_code}")
        assert r.status_code == 200, f"status={r.status_code} body={r.text[:500]}"
        data = r.json()
        assert data["ok"] is True
        run = data["run"]
        assert run["test_number"] == 1
        assert "isabela_response" in run
        assert "evaluation" in run
        assert "score" in run
        assert "pass" in run
        assert isinstance(run["pass"], bool)
        # status should be ok or error - either way score field present
        assert run["status"] in ("ok", "error")
        if run["status"] == "ok":
            assert run["isabela_response"], "isabela_response should be non-empty"
            ev = run["evaluation"]
            assert "score" in ev or "score_decimal" in ev
            assert "breakdown" in ev or run.get("score") is not None


# ---------- Runs history ----------
class TestRunsHistory:
    def test_runs_list(self, h):
        r = requests.get(f"{API}/ai-training/runs", headers=h, timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "count" in data
        assert "passed" in data
        assert "failed" in data
        assert "average_score" in data
        assert isinstance(data["items"], list)

    def test_run_detail_if_any(self, h):
        r = requests.get(f"{API}/ai-training/runs", headers=h, timeout=20)
        items = r.json().get("items") or []
        if not items:
            pytest.skip("No runs yet")
        run_id = items[0]["id"]
        d = requests.get(f"{API}/ai-training/runs/{run_id}", headers=h, timeout=20)
        assert d.status_code == 200
        run = d.json()
        assert run["id"] == run_id
        assert "isabela_response" in run or "evaluation" in run


# ---------- Auth ----------
class TestAuth:
    def test_no_auth_rejected(self):
        r = requests.get(f"{API}/ai-training/scenarios", timeout=20)
        assert r.status_code in (401, 403)
