"""iter182 — Backend regression tests for the OS CTO Picker refactor.

Validates:
 1. GET  /api/rede-ia/sentinela/config — returns default + threshold.
 2. PATCH /api/rede-ia/sentinela/config with {sentinela_min_score: 69} — persists.
 3. POST /api/rede-ia/smartolt/sync-vlan-to-subscribers?dry_run=true — fallback fields.

Uses the live preview backend via REACT_APP_BACKEND_URL (no localhost).
"""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL",
                          "https://dual-combine-3.preview.emergentagent.com"
                          ).rstrip("/")

ADMIN_EMAIL = "vando@ligotelecom.com"
ADMIN_PASS = "Vs5879@@@"


# ---------------------- helpers ----------------------
def _login():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
                      timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    token = data.get("access_token") or data.get("token")
    assert token, f"no token in login payload: {data}"
    return token


def _h(token):
    return {"Authorization": f"Bearer {token}",
            "Content-Type": "application/json"}


# ---------------------- tests ------------------------
class TestSentinelaConfig:
    """Sentinela threshold GET/PATCH endpoints."""

    def test_get_sentinela_config(self):
        token = _login()
        r = requests.get(f"{BASE_URL}/api/rede-ia/sentinela/config",
                         headers=_h(token), timeout=20)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert "sentinela_min_score" in data
        assert data.get("default") == 69
        assert isinstance(data.get("presets"), list) and len(data["presets"]) >= 3
        # presets must have value/label/desc
        for p in data["presets"]:
            assert "value" in p and "label" in p and "desc" in p

    def test_patch_sentinela_config_69(self):
        token = _login()
        r = requests.patch(f"{BASE_URL}/api/rede-ia/sentinela/config",
                           headers=_h(token),
                           json={"sentinela_min_score": 69},
                           timeout=20)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert data.get("ok") is True
        assert data.get("sentinela_min_score") == 69

        # persistence check: GET should reflect 69
        r2 = requests.get(f"{BASE_URL}/api/rede-ia/sentinela/config",
                          headers=_h(token), timeout=20)
        assert r2.status_code == 200
        assert r2.json().get("sentinela_min_score") == 69

    def test_patch_sentinela_config_validation_out_of_range(self):
        token = _login()
        r = requests.patch(f"{BASE_URL}/api/rede-ia/sentinela/config",
                           headers=_h(token),
                           json={"sentinela_min_score": 250},
                           timeout=20)
        # pydantic ge=0,le=100 → 422
        assert r.status_code in (400, 422), r.text[:300]


class TestSmartOltSyncVlanDryRun:
    """sync-vlan-to-subscribers must include the default_vlan_1 fallback fields."""

    def test_dry_run_returns_200_and_fallback_fields(self):
        token = _login()
        r = requests.post(
            f"{BASE_URL}/api/rede-ia/smartolt/sync-vlan-to-subscribers"
            "?dry_run=true",
            headers=_h(token), timeout=120,
        )
        # Accept 200 or 502/503 if SmartOLT external is unreachable on the env,
        # but the contract under test is the response shape when reachable.
        if r.status_code in (502, 503, 504):
            import pytest
            pytest.skip(f"SmartOLT upstream unreachable: {r.status_code}")
        assert r.status_code == 200, r.text[:500]
        data = r.json()
        # core counters
        for f in ("updated", "unchanged", "no_subscriber",
                  "default_vlan_1_applied",
                  "default_vlan_1_skipped_instalacao"):
            assert f in data, f"missing field {f} in response: {list(data.keys())}"
        # types are ints (counters)
        assert isinstance(data["default_vlan_1_applied"], int)
        assert isinstance(data["default_vlan_1_skipped_instalacao"], int)
