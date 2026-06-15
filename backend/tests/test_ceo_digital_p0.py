"""CTO Audit P0 — corporate_goals + executive_decisions backend tests.

Cobre review_request:
- /api/ceo/metas (com/sem token, source=corporate_goals, 5 KPIs)
- /api/ceo/goals (kpi_key based, isolado dos goals Isabella legados)
- /api/ceo/decisions CRUD (POST validações, GET filtros, PATCH transições)
- /api/ceo/openapi.json (operations + schemas novos)
- /api/ceo/briefing/today + /briefing/now (não-regressão, targets dos 5 KPIs)
- /api/ceo/memory?days=7
- Idempotência do auto-seed (chamar /metas duas vezes não duplica).
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
# Fallback to local if env not set in shell (production env preferred).
if not BASE_URL:
    BASE_URL = "http://localhost:8001"

# Token need not be hidden — used only inside test runtime.
TOKEN = os.environ.get("CEO_BRIEFING_TOKEN")
if not TOKEN:
    # Read from backend .env directly
    try:
        with open("/app/backend/.env") as fh:
            for line in fh:
                if line.startswith("CEO_BRIEFING_TOKEN"):
                    TOKEN = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    except Exception:
        pass

AUTH = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
EXPECTED_KPIS = {
    "clientes_ativos": 3500.0,
    "mrr": 450000.0,
    "inadimplencia_brl": 31000.0,
    "embaixadores": 50.0,
    "fundadores_aptos": 30.0,
}


# ─────────────────────────────── metas/goals ───────────────────────────────
class TestMetasAndGoals:
    def test_metas_requires_token(self):
        r = requests.get(f"{BASE_URL}/api/ceo/metas", timeout=15)
        assert r.status_code == 401

    def test_metas_returns_corporate_goals_source(self):
        r = requests.get(f"{BASE_URL}/api/ceo/metas", headers=AUTH, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("source") == "corporate_goals"
        assert "baseline_date" in data
        metas = data.get("metas_2026") or {}
        # 5 KPIs canônicos
        for kpi, target in EXPECTED_KPIS.items():
            assert kpi in metas, f"KPI {kpi} ausente em metas_2026"
            m = metas[kpi]
            for field in ("baseline", "target", "direction", "owner", "deadline"):
                assert field in m, f"{kpi}.{field} ausente"
            assert float(m["target"]) == target, (
                f"target divergente {kpi}: {m['target']} != {target}")

    def test_metas_idempotent_autoseed(self):
        # Two consecutive calls must not duplicate docs
        r1 = requests.get(f"{BASE_URL}/api/ceo/metas", headers=AUTH, timeout=15)
        r2 = requests.get(f"{BASE_URL}/api/ceo/metas", headers=AUTH, timeout=15)
        assert r1.status_code == r2.status_code == 200
        # /goals shows count: must remain 5
        g = requests.get(f"{BASE_URL}/api/ceo/goals", headers=AUTH, timeout=15)
        assert g.status_code == 200
        items = g.json().get("items") or []
        # filter de kpi_key already applied server-side
        kpi_keys = {i.get("kpi_key") for i in items if i.get("kpi_key")}
        # exatamente os 5 KPIs canônicos (não mais — auto-seed idempotente)
        assert set(EXPECTED_KPIS.keys()).issubset(kpi_keys), (
            f"KPIs faltando: {set(EXPECTED_KPIS.keys()) - kpi_keys}")
        # Idempotency strict: each kpi_key must appear exactly once
        from collections import Counter
        counts = Counter(i.get("kpi_key") for i in items)
        dups = {k: v for k, v in counts.items() if v > 1}
        assert not dups, f"Duplicate kpi_key docs: {dups}"

    def test_goals_list_schema(self):
        r = requests.get(f"{BASE_URL}/api/ceo/goals", headers=AUTH, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "count" in data and "items" in data
        assert data["count"] >= 5
        for it in data["items"]:
            for field in ("kpi_key", "baseline", "target", "direction",
                          "owner", "deadline", "status"):
                assert field in it, f"campo {field} ausente: {it}"
            assert it["status"] == "active"
            # Garantir que goals legados Isabella (com metric/area) NÃO vêm
            assert "metric" not in it or it.get("kpi_key"), (
                "Isabella legacy goal vazou: " + str(it))


# ─────────────────────────────── decisions ───────────────────────────────
@pytest.fixture(scope="module")
def created_decision_id():
    """Cria uma decisão para reuso e cleanup ao final."""
    payload = {
        "decision": "TEST_p0_decision migrar billing v2",
        "context": "smoke test backend",
        "priority": "p1",
        "proposed_by": "presidente_ia",
        "owner": "cto",
        "deadline": "2026-12-31",
        "related_kpi": "mrr",
    }
    r = requests.post(f"{BASE_URL}/api/ceo/decisions", headers=AUTH,
                      json=payload, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    dec = body.get("decision") or {}
    assert dec.get("id", "").startswith("dec-"), f"id format: {dec.get('id')}"
    assert dec.get("status") == "proposed"
    assert dec.get("created_at") and dec.get("updated_at")
    return dec["id"]


class TestDecisionsCreate:
    def test_create_minimal_defaults(self):
        r = requests.post(f"{BASE_URL}/api/ceo/decisions", headers=AUTH,
                          json={"decision": "TEST_p0_minimal payload"},
                          timeout=15)
        assert r.status_code == 200, r.text
        dec = r.json()["decision"]
        assert dec["status"] == "proposed"
        assert dec["priority"] == "p2"
        assert dec["proposed_by"] == "presidente_ia"
        assert dec["id"].startswith("dec-")

    def test_create_missing_decision_field_400(self):
        r = requests.post(f"{BASE_URL}/api/ceo/decisions", headers=AUTH,
                          json={"priority": "p1"}, timeout=15)
        assert r.status_code == 400, r.text
        msg = (r.json().get("detail") or "").lower()
        assert "decision" in msg and "obrigat" in msg

    def test_create_invalid_priority_400(self):
        r = requests.post(f"{BASE_URL}/api/ceo/decisions", headers=AUTH,
                          json={"decision": "x", "priority": "p9"},
                          timeout=15)
        assert r.status_code == 400, r.text
        msg = (r.json().get("detail") or "").lower()
        assert "priority" in msg


class TestDecisionsListAndPatch:
    def test_list_returns_count_and_items(self, created_decision_id):
        r = requests.get(f"{BASE_URL}/api/ceo/decisions", headers=AUTH,
                         timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "count" in data and "items" in data
        ids = [d.get("id") for d in data["items"]]
        assert created_decision_id in ids

    def test_filter_status_proposed(self, created_decision_id):
        r = requests.get(
            f"{BASE_URL}/api/ceo/decisions?status=proposed",
            headers=AUTH, timeout=15)
        assert r.status_code == 200
        data = r.json()
        for it in data["items"]:
            assert it["status"] == "proposed"

    def test_patch_approve(self, created_decision_id):
        r = requests.patch(
            f"{BASE_URL}/api/ceo/decisions/{created_decision_id}",
            headers=AUTH,
            json={"status": "approved", "approved_by": "ceo"}, timeout=15)
        assert r.status_code == 200, r.text
        dec = r.json()["decision"]
        assert dec["status"] == "approved"
        assert dec["approved_by"] == "ceo"
        # Verify persistence via GET
        g = requests.get(
            f"{BASE_URL}/api/ceo/decisions?status=approved",
            headers=AUTH, timeout=15)
        assert g.status_code == 200
        assert any(d["id"] == created_decision_id for d in g.json()["items"])

    def test_patch_done_sets_completed_at(self, created_decision_id):
        r = requests.patch(
            f"{BASE_URL}/api/ceo/decisions/{created_decision_id}",
            headers=AUTH, json={"status": "done"}, timeout=15)
        assert r.status_code == 200
        dec = r.json()["decision"]
        assert dec["status"] == "done"
        assert dec.get("completed_at"), "completed_at não foi preenchido"

    def test_patch_unknown_id_404(self):
        r = requests.patch(
            f"{BASE_URL}/api/ceo/decisions/dec-doesnotexist123",
            headers=AUTH, json={"status": "approved"}, timeout=15)
        assert r.status_code == 404


# ─────────────────────────────── openapi.json ───────────────────────────────
class TestOpenApi:
    def test_openapi_schema_has_new_ops_and_schemas(self):
        r = requests.get(f"{BASE_URL}/api/ceo/openapi.json", timeout=15)
        assert r.status_code == 200
        spec = r.json()
        assert spec.get("openapi") == "3.1.0"
        # Collect operationIds
        op_ids = set()
        for path, methods in (spec.get("paths") or {}).items():
            for method, op in methods.items():
                if isinstance(op, dict) and op.get("operationId"):
                    op_ids.add(op["operationId"])
        expected_ops = {"decisionsList", "decisionsCreate",
                        "decisionsUpdate", "goalsList"}
        missing_ops = expected_ops - op_ids
        assert not missing_ops, f"operations ausentes: {missing_ops}"

        schemas = (spec.get("components") or {}).get("schemas") or {}
        expected_schemas = {"DecisionItem", "DecisionsList",
                            "DecisionResult", "GoalItem", "GoalsList"}
        missing_schemas = expected_schemas - set(schemas.keys())
        assert not missing_schemas, f"schemas ausentes: {missing_schemas}"


# ─────────────────────────────── briefing/memory (no regression) ────────────
class TestBriefingNoRegression:
    def test_briefing_today(self):
        r = requests.get(f"{BASE_URL}/api/ceo/briefing/today",
                         headers=AUTH, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        # API expõe os 5 KPIs em course_status; targets aparecem no
        # briefing_text. Validar AMBOS (não-regressão pós migração).
        course_status = data.get("course_status") or {}
        for kpi in EXPECTED_KPIS:
            assert kpi in course_status, (
                f"KPI {kpi} ausente em course_status: {list(course_status)}")
        text = data.get("briefing_text") or ""
        # targets de corporate_goals devem aparecer no texto
        for kpi, target in EXPECTED_KPIS.items():
            assert str(target) in text, (
                f"target {target} (KPI {kpi}) não consta em briefing_text")

    def test_briefing_now_post(self):
        r = requests.post(f"{BASE_URL}/api/ceo/briefing/now",
                          headers=AUTH, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        cc = data.get("course_correction") or {}
        # course_correction precisa ter os 5 KPIs com targets de
        # corporate_goals (não-regressão pós migração).
        for kpi, target in EXPECTED_KPIS.items():
            assert kpi in cc, (
                f"KPI {kpi} ausente em course_correction: {list(cc)}")
            assert float(cc[kpi].get("target") or 0) == target, (
                f"target {kpi}: {cc[kpi].get('target')} != {target}")

    def test_memory_returns_array(self):
        r = requests.get(f"{BASE_URL}/api/ceo/memory?days=7",
                         headers=AUTH, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        # Accept either list or {"items":[...]}
        items = body if isinstance(body, list) else (
            body.get("items") or body.get("snapshots") or [])
        assert isinstance(items, list)
