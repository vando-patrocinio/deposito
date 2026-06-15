"""Backend tests for iter156 — Evolution API provider (CTO 15/06/2026).

Scope (from review_request):
 1. GET /api/whatsapp-channels returns 4 channels, each with provider field
    (default 'baileys') + evolution_url/evolution_instance_name present
    (possibly null). evolution_api_key NEVER appears in clear in the list —
    only evolution_api_key_masked when configured.
 2. PATCH /api/whatsapp-channels/channel-1/provider with provider='evolution'
    WITHOUT url/key/instance → 400 mentioning 'Evolution requer'.
 3. PATCH with full Evolution payload → 200; persists provider+3 fields.
 4. After PATCH above, response does NOT contain evolution_api_key in clear;
    must show evolution_api_key_masked like '***CDEF'.
 5. PATCH with provider='invalido' → 400.
 6. PATCH provider='baileys' clears the 3 Evolution fields (all null).
 7. GET /qr when provider='evolution' (fake URL) → 502 'Evolution API
    inacessível' (NO silent fallback to Baileys, NO 500).
 8. GET /qr when provider='baileys' → calls sidecar (502 if down, 200 if up).
 9. Restore channel-1 to provider='baileys' at end (cleanup).
"""
import os
import pytest
import requests

def _read_base_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if url:
        return url.rstrip("/")
    try:
        with open("/app/frontend/.env", "r") as fh:
            for line in fh:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass
    raise RuntimeError("REACT_APP_BACKEND_URL not set")


BASE_URL = _read_base_url()
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASSWORD = "123456"


@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token")
    assert tok, "no access_token in login response"
    return tok


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module", autouse=True)
def cleanup(headers):
    """At session end, restore channel-1 to baileys."""
    yield
    try:
        requests.patch(
            f"{BASE_URL}/api/whatsapp-channels/channel-1/provider",
            json={"provider": "baileys"},
            headers=headers,
            timeout=15,
        )
    except Exception:
        pass


# ---------- 1) GET list shape -------------------------------------------------
class TestListChannels:
    def test_list_returns_four_channels(self, headers):
        r = requests.get(f"{BASE_URL}/api/whatsapp-channels", headers=headers, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        chans = data.get("channels")
        assert isinstance(chans, list), f"expected list, got {type(chans)}"
        assert len(chans) == 4, f"expected 4 channels, got {len(chans)}"

    def test_each_channel_has_provider_and_evolution_fields(self, headers):
        r = requests.get(f"{BASE_URL}/api/whatsapp-channels", headers=headers, timeout=20)
        assert r.status_code == 200
        chans = r.json()["channels"]
        for ch in chans:
            assert "provider" in ch, f"channel {ch.get('id')} missing 'provider'"
            assert ch["provider"] in ("baileys", "evolution"), ch["provider"]
            # New schema fields must be present (may be null)
            assert "evolution_url" in ch, f"channel {ch.get('id')} missing 'evolution_url'"
            assert "evolution_instance_name" in ch, (
                f"channel {ch.get('id')} missing 'evolution_instance_name'"
            )

    def test_api_key_never_in_clear_on_list(self, headers):
        """Even if some channel had api_key persisted, listing must not expose it."""
        r = requests.get(f"{BASE_URL}/api/whatsapp-channels", headers=headers, timeout=20)
        for ch in r.json()["channels"]:
            assert "evolution_api_key" not in ch, (
                f"channel {ch.get('id')} leaked evolution_api_key: {ch.get('evolution_api_key')}"
            )


# ---------- 2/5) Validation errors -------------------------------------------
class TestProviderValidation:
    def test_evolution_without_credentials_returns_400(self, headers):
        r = requests.patch(
            f"{BASE_URL}/api/whatsapp-channels/channel-1/provider",
            json={"provider": "evolution"},
            headers=headers,
            timeout=15,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
        body = r.json()
        # message must mention 'Evolution requer'
        msg = (body.get("detail") or body.get("message") or "").lower()
        assert "evolution requer" in msg, f"missing 'Evolution requer' in: {body}"

    def test_invalid_provider_returns_400(self, headers):
        r = requests.patch(
            f"{BASE_URL}/api/whatsapp-channels/channel-1/provider",
            json={"provider": "invalido"},
            headers=headers,
            timeout=15,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"


# ---------- 3/4/6) Full lifecycle: set evolution → verify mask → revert -----
class TestProviderLifecycle:
    EVO_URL = "https://evo.test"
    EVO_KEY = "KEY1234567890ABCDEF"
    EVO_INSTANCE = "ch1"

    def test_a_set_evolution_full_persists_and_masks(self, headers):
        r = requests.patch(
            f"{BASE_URL}/api/whatsapp-channels/channel-1/provider",
            json={
                "provider": "evolution",
                "evolution_url": self.EVO_URL,
                "evolution_api_key": self.EVO_KEY,
                "evolution_instance_name": self.EVO_INSTANCE,
            },
            headers=headers,
            timeout=15,
        )
        assert r.status_code == 200, f"PATCH failed: {r.status_code} {r.text}"
        body = r.json()
        # Response must NOT contain api_key in clear
        assert "evolution_api_key" not in body or body.get("evolution_api_key") is None, (
            f"response leaked evolution_api_key in clear: {body}"
        )
        # Must contain masked
        masked = body.get("evolution_api_key_masked")
        assert masked, f"missing evolution_api_key_masked: {body}"
        assert masked.endswith("CDEF"), f"mask doesn't end with CDEF: {masked}"
        assert masked.startswith("***"), f"mask doesn't start with ***: {masked}"
        # Persisted fields
        assert body.get("provider") == "evolution"
        assert body.get("evolution_url") == self.EVO_URL
        assert body.get("evolution_instance_name") == self.EVO_INSTANCE

    def test_b_get_list_after_set_shows_mask_not_clear_key(self, headers):
        r = requests.get(f"{BASE_URL}/api/whatsapp-channels", headers=headers, timeout=20)
        assert r.status_code == 200
        ch1 = next((c for c in r.json()["channels"] if c["id"] == "channel-1"), None)
        assert ch1, "channel-1 missing"
        assert ch1["provider"] == "evolution"
        assert "evolution_api_key" not in ch1, f"clear key leaked: {ch1}"
        assert ch1.get("evolution_api_key_masked", "").endswith("CDEF"), ch1

    def test_c_qr_evolution_returns_502_not_500_not_baileys(self, headers):
        """Fake URL https://evo.test → must return 502 (NOT 500 / NOT crash).
        Backend returns JSON detail 'Evolution API inacessível', but the
        preview ingress (Cloudflare) may rewrite the body to its own 502
        HTML page. The CRITICAL contract is status_code==502.
        Backend log direct verification showed:
          {"detail":"Evolution API inacessível: [Errno -2] Name or service not known"}
        """
        r = requests.get(
            f"{BASE_URL}/api/whatsapp-channels/channel-1/qr",
            headers=headers,
            timeout=30,
        )
        assert r.status_code == 502, (
            f"expected 502, got {r.status_code}: {r.text[:300]}"
        )
        # If ingress preserved JSON body, also validate detail
        ct = r.headers.get("content-type", "")
        if "json" in ct:
            body = r.json()
            detail = (body.get("detail") or "").lower()
            assert "evolution" in detail, f"detail missing 'evolution': {body}"
            assert "inacess" in detail, f"detail missing 'inacess': {body}"

    def test_d_revert_to_baileys_clears_evolution_fields(self, headers):
        r = requests.patch(
            f"{BASE_URL}/api/whatsapp-channels/channel-1/provider",
            json={"provider": "baileys"},
            headers=headers,
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("provider") == "baileys"
        assert body.get("evolution_url") is None, f"evolution_url not cleared: {body}"
        # Either field absent or None — both acceptable as 'null'
        assert body.get("evolution_api_key") in (None,), f"evolution_api_key not cleared: {body}"
        assert body.get("evolution_instance_name") is None, (
            f"evolution_instance_name not cleared: {body}"
        )
        # No mask either since key is null
        assert not body.get("evolution_api_key_masked"), (
            f"mask should be absent after revert: {body}"
        )

    def test_e_get_list_after_revert(self, headers):
        r = requests.get(f"{BASE_URL}/api/whatsapp-channels", headers=headers, timeout=20)
        ch1 = next((c for c in r.json()["channels"] if c["id"] == "channel-1"), None)
        assert ch1["provider"] == "baileys"
        assert ch1.get("evolution_url") is None
        assert ch1.get("evolution_instance_name") is None


# ---------- 8) Baileys qr path legacy preserved -----------------------------
class TestBaileysPathPreserved:
    def test_qr_baileys_does_not_500(self, headers):
        """When provider='baileys' (default), the endpoint should call the local sidecar.
        Expected: 200 (sidecar up) or 502 (sidecar down). NEVER 500 / NEVER crash.
        """
        r = requests.get(
            f"{BASE_URL}/api/whatsapp-channels/channel-1/qr",
            headers=headers,
            timeout=30,
        )
        assert r.status_code in (200, 502), (
            f"unexpected status {r.status_code}: {r.text[:300]}"
        )
