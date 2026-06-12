"""iter241 — Score Recovery endpoints (simulate/execute/rollback/history)."""
import os
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback: try reading frontend/.env
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass

CREDS = {"email": "admin@empresa.com", "password": "123456"}


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=CREDS, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token in {r.json()}"
    return tok


@pytest.fixture(scope="module")
def H(token):
    return {"Authorization": f"Bearer {token}"}


# ── SIMULATE ───────────────────────────────────────────────────────────
def test_simulate(H):
    r = requests.get(
        f"{BASE_URL}/api/presidente-ia/score-recovery/simulate",
        headers=H, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "current" in d and "projected" in d and "actions" in d
    assert "score" in d["current"] and "components" in d["current"]
    assert "score" in d["projected"] and "delta" in d["projected"]
    a = d["actions"]
    for k in ("onus_status_null_to_archive", "onus_los_offline_to_archive",
              "tickets_stale_to_autoclose",
              "onus_total_before", "onus_total_after"):
        assert k in a, f"missing actions key: {k}"
    p = d["params"]
    assert p["days_los_archive"] == 30
    assert p["days_ticket_autoclose"] == 60
    assert p["reversible"] is True
    # Delta should be sane
    expected_delta = round(d["projected"]["score"] - d["current"]["score"], 1)
    assert abs(d["projected"]["delta"] - expected_delta) <= 0.2


# ── EXECUTE: validation ───────────────────────────────────────────────
def test_execute_short_reason_400(H):
    r = requests.post(
        f"{BASE_URL}/api/presidente-ia/score-recovery/execute",
        headers=H, json={"reason": ""}, timeout=15)
    assert r.status_code == 400, r.text


# ── EXECUTE: happy ────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def executed_batch(H):
    r = requests.post(
        f"{BASE_URL}/api/presidente-ia/score-recovery/execute",
        headers=H, json={"reason": "limpeza de débito técnico CTO"},
        timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "batch_id" in d
    assert "executed_by" in d
    assert d["reversible"] is True
    assert "actions" in d
    for k in ("onus_archived_null", "onus_archived_los",
              "tickets_autoclosed"):
        assert k in d["actions"]
    return d


def test_execute_returns_batch(executed_batch):
    assert executed_batch["batch_id"].startswith("rec-")


# ── BATCHES list ─────────────────────────────────────────────────────
def test_batches_lists_recent(H, executed_batch):
    r = requests.get(
        f"{BASE_URL}/api/presidente-ia/score-recovery/batches",
        headers=H, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "batches" in d
    ids = [b.get("batch_id") for b in d["batches"]]
    assert executed_batch["batch_id"] in ids


# ── IDEMPOTENCY: simulate after execute → delta ~0 ───────────────────
def test_idempotency_simulate_after_execute(H, executed_batch):
    time.sleep(0.5)
    r = requests.get(
        f"{BASE_URL}/api/presidente-ia/score-recovery/simulate",
        headers=H, timeout=30)
    assert r.status_code == 200
    d = r.json()
    a = d["actions"]
    # After cleanup there should be ~0 null/los onus left
    assert a["onus_status_null_to_archive"] == 0
    assert a["onus_los_offline_to_archive"] == 0


# ── HISTORY + SNAPSHOT ────────────────────────────────────────────────
def test_snapshot_and_history(H):
    r = requests.post(
        f"{BASE_URL}/api/presidente-ia/score-history/snapshot",
        headers=H, timeout=30)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert "score" in doc and "snapshot_at" in doc and "source" in doc

    r = requests.get(
        f"{BASE_URL}/api/presidente-ia/score-history?days=30",
        headers=H, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["days"] == 30
    assert isinstance(d["history"], list)
    assert len(d["history"]) >= 1


# ── ROLLBACK ─────────────────────────────────────────────────────────
def test_rollback(H, executed_batch):
    bid = executed_batch["batch_id"]
    r = requests.post(
        f"{BASE_URL}/api/presidente-ia/score-recovery/rollback/{bid}",
        headers=H, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["batch_id"] == bid
    assert "rolled_back_onus" in d
    assert "rolled_back_tickets" in d


# ── Cron job import sanity ──────────────────────────────────────────
def test_cron_job_import_ok():
    from services.score_recovery import daily_snapshot_job
    assert callable(daily_snapshot_job)
