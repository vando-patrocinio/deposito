"""Iter 66 — AI Training Scheduler endpoints (GET/PUT /api/ai-training/schedule)."""
import os
import pytest
import requests

# Load REACT_APP_BACKEND_URL from frontend/.env if not in environment
def _load_base_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        url = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass
    assert url, "REACT_APP_BACKEND_URL not configured"
    return url.rstrip("/")

BASE_URL = _load_base_url()
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASSWORD = "123456"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no token in {data}"
    return tok


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---- Auth ----------------------------------------------------------------
def test_schedule_get_requires_auth():
    r = requests.get(f"{BASE_URL}/api/ai-training/schedule", timeout=10)
    assert r.status_code in (401, 403), f"unauth GET: {r.status_code}"


def test_schedule_put_requires_auth():
    r = requests.put(f"{BASE_URL}/api/ai-training/schedule",
                     json={"enabled": True}, timeout=10)
    assert r.status_code in (401, 403)


# ---- GET defaults / persistence -----------------------------------------
def test_schedule_get_returns_config(auth_headers):
    r = requests.get(f"{BASE_URL}/api/ai-training/schedule",
                     headers=auth_headers, timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    # All expected keys
    for k in ("enabled", "hour_utc", "minute", "alert_threshold"):
        assert k in data, f"missing key {k} in {data}"
    assert isinstance(data["enabled"], bool)
    assert 0 <= int(data["hour_utc"]) <= 23
    assert 0 <= int(data["minute"]) <= 59
    assert 0.0 <= float(data["alert_threshold"]) <= 10.0


# ---- PUT happy path ------------------------------------------------------
def test_schedule_put_update_and_persist(auth_headers):
    payload = {"enabled": True, "hour_utc": 3, "minute": 0,
               "alert_threshold": 7.5}
    r = requests.put(f"{BASE_URL}/api/ai-training/schedule",
                     headers=auth_headers, json=payload, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    sch = body.get("schedule") or {}
    assert sch.get("enabled") is True
    assert int(sch.get("hour_utc")) == 3
    assert int(sch.get("minute")) == 0
    assert float(sch.get("alert_threshold")) == 7.5

    # GET-verify persistence
    r2 = requests.get(f"{BASE_URL}/api/ai-training/schedule",
                      headers=auth_headers, timeout=10)
    assert r2.status_code == 200
    sch2 = r2.json()
    assert sch2["enabled"] is True
    assert int(sch2["hour_utc"]) == 3
    assert float(sch2["alert_threshold"]) == 7.5


def test_schedule_put_change_threshold(auth_headers):
    r = requests.put(f"{BASE_URL}/api/ai-training/schedule",
                     headers=auth_headers,
                     json={"alert_threshold": 8.0}, timeout=10)
    assert r.status_code == 200
    sch = r.json()["schedule"]
    assert float(sch["alert_threshold"]) == 8.0
    # restore
    requests.put(f"{BASE_URL}/api/ai-training/schedule",
                 headers=auth_headers,
                 json={"alert_threshold": 7.5}, timeout=10)


# ---- Validations ---------------------------------------------------------
def test_schedule_put_invalid_hour(auth_headers):
    r = requests.put(f"{BASE_URL}/api/ai-training/schedule",
                     headers=auth_headers,
                     json={"hour_utc": 25}, timeout=10)
    assert r.status_code == 400, f"expected 400 got {r.status_code} {r.text}"


def test_schedule_put_invalid_minute(auth_headers):
    r = requests.put(f"{BASE_URL}/api/ai-training/schedule",
                     headers=auth_headers,
                     json={"minute": 99}, timeout=10)
    assert r.status_code == 400


def test_schedule_put_invalid_threshold_high(auth_headers):
    r = requests.put(f"{BASE_URL}/api/ai-training/schedule",
                     headers=auth_headers,
                     json={"alert_threshold": 11.5}, timeout=10)
    assert r.status_code == 400


def test_schedule_put_invalid_threshold_negative(auth_headers):
    r = requests.put(f"{BASE_URL}/api/ai-training/schedule",
                     headers=auth_headers,
                     json={"alert_threshold": -1.0}, timeout=10)
    assert r.status_code == 400


def test_schedule_put_empty_payload(auth_headers):
    r = requests.put(f"{BASE_URL}/api/ai-training/schedule",
                     headers=auth_headers,
                     json={}, timeout=10)
    assert r.status_code == 400


# ---- Drift state already present (last_run from earlier batch) ----------
def test_schedule_has_last_run_history(auth_headers):
    """Worker já rodou hoje com avg=6.06 < 7.5 → last_run + last_alert presentes."""
    r = requests.get(f"{BASE_URL}/api/ai-training/schedule",
                     headers=auth_headers, timeout=10)
    assert r.status_code == 200
    sch = r.json()
    # These should be present after the morning auto-run
    assert sch.get("last_run_at"), "expected last_run_at set after worker ran"
    assert sch.get("last_average") is not None
    assert sch.get("last_alert_at"), "drift alert should have been emitted (avg 6.06 < 7.5)"
