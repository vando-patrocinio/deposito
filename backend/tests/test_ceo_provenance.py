"""Tests for CEO Digital audit items 9 + 10: source flag + stale warning."""
import os
import pytest
import requests
from datetime import datetime, timedelta, timezone

# Read backend URL from frontend env to validate ingress routing
def _read_backend_url() -> str:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().strip('"').rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not found")


def _read_token() -> str:
    with open("/app/backend/.env") as f:
        for line in f:
            if line.startswith("CEO_BRIEFING_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("CEO_BRIEFING_TOKEN not found")


BASE_URL = _read_backend_url()
TOKEN = _read_token()
HDR = {"Authorization": f"Bearer {TOKEN}"}


# ──────────── helpers / shape validation ────────────
def _assert_dp(payload: dict, expect_source="prod"):
    assert "source" in payload, f"missing source on payload (keys={list(payload.keys())})"
    assert payload["source"] == expect_source, f"source={payload['source']}"
    dp = payload.get("_data_provenance")
    assert isinstance(dp, dict), "missing _data_provenance dict"
    for k in ("source", "collected_at", "stale_hours",
              "stale_threshold_hours", "stale_warning",
              "decision_safe", "message"):
        assert k in dp, f"_data_provenance missing key {k}"
    assert dp["stale_threshold_hours"] == 24.0
    assert dp["source"] == expect_source
    return dp


# ──────────── ITEM 9 — source flag ────────────
def test_briefing_today_source_and_provenance():
    r = requests.get(f"{BASE_URL}/api/ceo/briefing/today", headers=HDR, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    dp = _assert_dp(j, "prod")
    # fresh after recent snapshot
    assert dp["stale_warning"] is False
    assert dp["decision_safe"] is True
    assert dp["stale_hours"] is not None and dp["stale_hours"] >= 0


def test_briefing_now_source_and_provenance_fresh():
    r = requests.post(f"{BASE_URL}/api/ceo/briefing/now", headers=HDR, timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    dp = _assert_dp(j, "prod")
    # just generated => fresh, < 0.1h
    assert dp["stale_warning"] is False
    assert dp["decision_safe"] is True
    assert dp["stale_hours"] is not None
    assert dp["stale_hours"] < 0.5, f"stale_hours unexpectedly high: {dp['stale_hours']}"


def test_memory_top_level_and_items_source():
    r = requests.get(f"{BASE_URL}/api/ceo/memory?days=3", headers=HDR, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    _assert_dp(j, "prod")
    assert isinstance(j.get("items"), list)
    assert len(j["items"]) >= 1
    for it in j["items"]:
        assert "source" in it, f"item missing source: {it.get('date_key')}"
        assert it["source"] == "prod"


def test_cto_digest_source_and_provenance():
    r = requests.get(f"{BASE_URL}/api/ceo/cto/digest", headers=HDR, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    _assert_dp(j, "prod")


def test_metas_has_source_and_kind_config_no_dp():
    r = requests.get(f"{BASE_URL}/api/ceo/metas", headers=HDR, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("source") == "prod"
    assert j.get("kind") == "config"
    assert j.get("store") == "corporate_goals"
    assert "_data_provenance" not in j, "metas (config) MUST NOT have _data_provenance"


def test_goals_has_source_kind_config_no_dp():
    r = requests.get(f"{BASE_URL}/api/ceo/goals", headers=HDR, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("source") == "prod"
    assert j.get("kind") == "config"
    assert "_data_provenance" not in j


def test_decisions_list_source_kind_registry_no_dp():
    r = requests.get(f"{BASE_URL}/api/ceo/decisions", headers=HDR, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("source") == "prod"
    assert j.get("kind") == "registry"
    assert "_data_provenance" not in j


def test_decisions_create_persists_source():
    payload = {
        "decision": "TEST_provenance_source_persist",
        "context": "automated test for audit item 9",
        "priority": "p3",
        "proposed_by": "presidente_ia",
    }
    r = requests.post(f"{BASE_URL}/api/ceo/decisions", headers=HDR, json=payload, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("ok") is True
    assert j.get("source") == "prod"
    dec = j["decision"]
    assert dec.get("source") == "prod", f"created decision missing source=prod: {dec}"
    created_id = dec["id"]

    # verify persistence via list
    r2 = requests.get(f"{BASE_URL}/api/ceo/decisions?limit=200", headers=HDR, timeout=30)
    assert r2.status_code == 200
    items = r2.json()["items"]
    matched = [d for d in items if d["id"] == created_id]
    assert matched, "created decision not found in list"
    assert matched[0].get("source") == "prod"


def test_goals_upsert_new_doc_persists_source():
    """NEW docs created via upsert_goal must carry source='prod'."""
    kpi = "TEST_kpi_provenance"
    payload = {"baseline": 0, "target": 10, "direction": "up",
               "owner": "qa", "deadline": "2026-12-31"}
    r = requests.put(f"{BASE_URL}/api/ceo/goals/{kpi}",
                     headers=HDR, json=payload, timeout=30)
    assert r.status_code == 200, r.text
    # fetch list and find the new doc
    r2 = requests.get(f"{BASE_URL}/api/ceo/goals", headers=HDR, timeout=30)
    items = r2.json()["items"]
    target = [g for g in items if g.get("kpi_key") == kpi]
    assert target, f"{kpi} goal missing after upsert"
    assert target[0].get("source") == "prod", (
        f"new goal source != 'prod': {target[0].get('source')}")
    # cleanup
    from pymongo import MongoClient
    cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    cli[os.environ.get("DB_NAME", "test_database")].corporate_goals.delete_many(
        {"kpi_key": kpi})
    cli.close()


# ──────────── ITEM 10 — stale warning ────────────
def test_stale_warning_when_collected_at_old(mongo_set_collected_at):
    """Force _collected_at to 48h ago and assert stale_warning + decision_safe=False."""
    today_key = datetime.now(timezone.utc).date().isoformat()
    stale_iso = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    mongo_set_collected_at(today_key, stale_iso)

    r = requests.get(f"{BASE_URL}/api/ceo/briefing/today", headers=HDR, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    dp = j["_data_provenance"]
    assert dp["stale_warning"] is True, f"expected stale_warning=True, got {dp}"
    assert dp["decision_safe"] is False
    msg = dp.get("message", "").lower()
    assert ("aten" in msg) or ("stale" in msg), f"message missing stale wording: {dp['message']}"
    assert dp["stale_hours"] is not None and dp["stale_hours"] >= 24

    # Restore via fresh snapshot
    r2 = requests.post(f"{BASE_URL}/api/ceo/briefing/now", headers=HDR, timeout=60)
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["_data_provenance"]["stale_warning"] is False
    assert j2["_data_provenance"]["decision_safe"] is True


# ──────────── OpenAPI structure ────────────
def test_openapi_valid_and_contains_dataprovenance():
    r = requests.get(f"{BASE_URL}/api/ceo/openapi.json", timeout=30)
    assert r.status_code == 200, r.text
    spec = r.json()
    assert spec.get("openapi") == "3.1.0"
    schemas = spec.get("components", {}).get("schemas", {})
    assert "DataProvenance" in schemas, "DataProvenance schema missing"
    dp = schemas["DataProvenance"]
    for prop in ("source", "collected_at", "stale_hours",
                 "stale_threshold_hours", "stale_warning",
                 "decision_safe", "message"):
        assert prop in dp["properties"], f"DataProvenance missing {prop}"
    # 11 operations should be exposed
    paths = spec.get("paths", {})
    op_ids = []
    for path, methods in paths.items():
        for method, meta in methods.items():
            if isinstance(meta, dict) and meta.get("operationId"):
                op_ids.append(meta["operationId"])
    expected = {
        "ceoBriefingToday", "ceoBriefingNow", "ceoMemory", "ceoMetas",
        "ctoSendMessage", "ctoInbox", "decisionsList", "decisionsCreate",
        "decisionsUpdate", "goalsList", "ctoDigest",
    }
    missing = expected - set(op_ids)
    assert not missing, f"missing operationIds: {missing}"
    assert len(op_ids) == 11, f"expected 11 ops, got {len(op_ids)}: {op_ids}"


# ──────────── auth/security sanity ────────────
def test_auth_required_briefing_today():
    r = requests.get(f"{BASE_URL}/api/ceo/briefing/today", timeout=10)
    assert r.status_code == 401


# ──────────── fixtures ────────────
@pytest.fixture
def mongo_set_collected_at():
    """Helper to mutate one_truth._collected_at directly in MongoDB.

    Uses sync pymongo to bypass routes and force stale state.
    """
    from pymongo import MongoClient
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    client = MongoClient(mongo_url)
    db = client[db_name]

    def _set(date_key: str, iso: str):
        res = db.president_daily.update_one(
            {"company_id": "co-demo", "date_key": date_key,
             "one_truth": {"$exists": True}},
            {"$set": {"one_truth._collected_at": iso}})
        assert res.matched_count == 1, f"no snapshot to mutate for {date_key}"
    yield _set
    client.close()


# ──────────── unit-level edge cases for data_provenance ────────────
class TestDataProvenanceUnits:
    """Direct unit tests on services.data_provenance."""

    def test_malformed_DATA_SOURCE_MODE_falls_back_prod(self, monkeypatch):
        import importlib, sys
        sys.path.insert(0, "/app/backend")
        from services import data_provenance as dp
        monkeypatch.setenv("DATA_SOURCE_MODE", "foo")
        assert dp.current_source() == "prod"
        monkeypatch.setenv("DATA_SOURCE_MODE", "")
        assert dp.current_source() == "prod"
        monkeypatch.setenv("DATA_SOURCE_MODE", "TEST")  # case-insensitive
        assert dp.current_source() == "test"
        monkeypatch.setenv("DATA_SOURCE_MODE", " mock ")  # trim
        assert dp.current_source() == "mock"

    def test_missing_collected_at_marks_stale(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from services import data_provenance as dp
        block = dp.freshness_block(None)
        assert block["stale_warning"] is True
        assert block["decision_safe"] is False
        assert block["stale_hours"] is None
        assert "sem timestamp" in block["message"].lower() or "stale" in block["message"].lower()

    def test_malformed_iso_treated_as_stale(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from services import data_provenance as dp
        block = dp.freshness_block("not-a-date")
        assert block["stale_warning"] is True
        assert block["decision_safe"] is False

    def test_DATA_STALE_HOURS_override(self, monkeypatch):
        import sys
        sys.path.insert(0, "/app/backend")
        from services import data_provenance as dp
        monkeypatch.setenv("DATA_STALE_HOURS", "1")
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        two_h_ago = (_dt.now(_tz.utc) - _td(hours=2)).isoformat()
        block = dp.freshness_block(two_h_ago)
        assert block["stale_threshold_hours"] == 1.0
        assert block["stale_warning"] is True

    def test_test_source_makes_decision_unsafe_even_if_fresh(self, monkeypatch):
        import sys
        sys.path.insert(0, "/app/backend")
        from services import data_provenance as dp
        from datetime import datetime as _dt, timezone as _tz
        monkeypatch.setenv("DATA_SOURCE_MODE", "test")
        block = dp.freshness_block(_dt.now(_tz.utc).isoformat())
        assert block["stale_warning"] is False
        # decision_safe must require source==prod
        assert block["decision_safe"] is False
        assert block["source"] == "test"
