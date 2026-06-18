"""HTTP-level tests for Watchtower IA Presidente / Relacionamento endpoints.

Uses live preview backend (REACT_APP_BACKEND_URL). Authenticates as
admin@empresa.com / 123456 and validates response shape + RBAC.
"""
import os
import pytest
import requests

BASE = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://dual-combine-3.preview.emergentagent.com",
).rstrip("/")

ADMIN = {"email": "admin@empresa.com", "password": "123456"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE}/api/auth/login", json=ADMIN, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed: {r.status_code} {r.text[:200]}")
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    if not tok:
        pytest.skip("no token in login response")
    return tok


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def test_ia_presidente_shape(admin_headers):
    r = requests.get(
        f"{BASE}/api/isabella/watchtower/ia-presidente?hours=24",
        headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    d = r.json()
    for k in ("isabella_index", "autonomy_alarms", "claims",
              "promises", "wa_dispatch", "window_hours", "company_id"):
        assert k in d, f"missing key {k}"
    assert d["window_hours"] == 24
    claims = d["claims"]
    for k in ("failed", "orphan_no_consume", "samples"):
        assert k in claims
    promises = d["promises"]
    for k in ("open", "overdue", "fulfilled", "overdue_samples"):
        assert k in promises
    wa = d["wa_dispatch"]
    for k in ("total", "failures", "success_rate",
              "latency_ms_avg", "latency_ms_p95", "fail_samples"):
        assert k in wa
    assert isinstance(claims["samples"], list)
    assert isinstance(wa["fail_samples"], list)


def test_ia_presidente_window_validation(admin_headers):
    r = requests.get(
        f"{BASE}/api/isabella/watchtower/ia-presidente?hours=0",
        headers=admin_headers, timeout=15,
    )
    assert r.status_code in (400, 422), f"expected 400/422, got {r.status_code}"

    r = requests.get(
        f"{BASE}/api/isabella/watchtower/ia-presidente?hours=10000",
        headers=admin_headers, timeout=15,
    )
    assert r.status_code in (400, 422)


def test_ia_presidente_window_variants(admin_headers):
    for h in (1, 6, 168, 720):
        r = requests.get(
            f"{BASE}/api/isabella/watchtower/ia-presidente?hours={h}",
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, f"hours={h} failed: {r.status_code}"
        assert r.json()["window_hours"] == h


def test_relacionamento_shape(admin_headers):
    r = requests.get(
        f"{BASE}/api/isabella/watchtower/relacionamento?hours=168",
        headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    d = r.json()
    for k in ("memories", "promises", "follow_ups_pending",
              "top_clients", "vip_clients", "window_hours",
              "company_id"):
        assert k in d, f"missing {k}"
    mems = d["memories"]
    for k in ("total", "by_type", "samples"):
        assert k in mems
    assert isinstance(d["top_clients"], list)
    assert isinstance(d["vip_clients"], list)
    fu = d["follow_ups_pending"]
    assert "count" in fu and "samples" in fu
    # Top clients shape check (when not empty)
    for tc in d["top_clients"]:
        for k in ("phone", "memory_count", "trust_score",
                  "last_memory_at"):
            assert k in tc, f"top_client missing {k}"


def test_endpoints_require_auth():
    """No token → 401/403."""
    r = requests.get(
        f"{BASE}/api/isabella/watchtower/ia-presidente?hours=24",
        timeout=15,
    )
    assert r.status_code in (401, 403), \
        f"expected 401/403, got {r.status_code}"
    r = requests.get(
        f"{BASE}/api/isabella/watchtower/relacionamento?hours=24",
        timeout=15,
    )
    assert r.status_code in (401, 403)


def test_endpoints_reject_bad_token():
    headers = {"Authorization": "Bearer not-a-real-token"}
    r = requests.get(
        f"{BASE}/api/isabella/watchtower/ia-presidente",
        headers=headers, timeout=15,
    )
    assert r.status_code in (401, 403)
