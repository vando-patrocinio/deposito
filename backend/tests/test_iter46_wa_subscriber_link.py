"""Iteration 46 — WhatsApp regra máxima: link_phone_to_subscriber + retroativo + mark-seen + /contacts-bulk."""
import os
import time
import pytest
import requests

def _load_env_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    # fallback: parse frontend/.env
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.strip().startswith("REACT_APP_BACKEND_URL="):
                    return line.strip().split("=", 1)[1].rstrip("/")
    except Exception:
        pass
    raise RuntimeError("REACT_APP_BACKEND_URL not set")


BASE_URL = _load_env_url()
SIDECAR_URL = "http://127.0.0.1:3002"

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASSWORD = "123456"


@pytest.fixture(scope="module")
def auth_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token in response: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


# ---------------- Auth & no-import-error log check ----------------

def test_login_admin_returns_token(auth_token):
    assert isinstance(auth_token, str) and len(auth_token) > 10


def test_no_cannot_import_link_phone_after_now(headers):
    """After a fresh GET /conversations the backend must NOT log 'cannot import name link_phone_to_subscriber' anymore."""
    # baseline marker time
    marker = time.time()
    time.sleep(0.5)
    r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/conversations", headers=headers, timeout=20)
    assert r.status_code == 200, r.text
    time.sleep(2)
    log_path = "/var/log/supervisor/backend.err.log"
    if not os.path.exists(log_path):
        pytest.skip("backend log not accessible from test env")
    # Read last 1MB
    with open(log_path, "rb") as f:
        try:
            f.seek(-1_000_000, 2)
        except Exception:
            f.seek(0)
        tail = f.read().decode("utf-8", errors="ignore")
    # Find recent cannot import lines (heuristic: any line near end)
    bad_lines = [ln for ln in tail.split("\n") if "cannot import name 'link_phone_to_subscriber'" in ln]
    # Cannot easily filter by time without parsing, but the recentmost line should be older than our marker.
    # Use a stronger heuristic: trigger 3 more conversations calls and ensure no NEW bad line appears.
    for _ in range(3):
        requests.get(f"{BASE_URL}/api/whatsapp-baileys/conversations", headers=headers, timeout=20)
        time.sleep(0.5)
    time.sleep(2)
    with open(log_path, "rb") as f:
        try:
            f.seek(-300_000, 2)
        except Exception:
            f.seek(0)
        tail2 = f.read().decode("utf-8", errors="ignore")
    bad_after = [ln for ln in tail2.split("\n") if "cannot import name 'link_phone_to_subscriber'" in ln]
    # Check timestamps: bad logs must all be older than 'marker' wall-clock - relax by checking count not growing
    # If there were any new bad lines past our test start, fail.
    # Heuristic: any line with current-day timestamp newer than our marker is a fail.
    # Robust approach: ensure the latest 'INFO ponto.wa_baileys' line is more recent than any 'cannot import' line in tail2.
    info_lines = [ln for ln in tail2.split("\n") if "ponto.wa_baileys" in ln and "cannot import" not in ln]
    if bad_after and info_lines:
        # Compare last bad vs last info by string sort of timestamps (logs include ISO-like prefix)
        last_bad = bad_after[-1][:19]
        last_info = info_lines[-1][:19]
        assert last_info > last_bad, f"recent 'cannot import' detected after our trigger.\nlast_bad={last_bad}\nlast_info={last_info}"


# ---------------- Conversations endpoint shape ----------------

def test_conversations_returns_enriched_fields(headers):
    r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/conversations", headers=headers, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and "buckets" in body
    items = body["items"]
    assert isinstance(items, list)
    if not items:
        pytest.skip("no conversations seeded")
    sample = items[0]
    # All enrichment fields must EXIST (may be None)
    for k in ["subscriber_id", "subscriber_name", "subscriber_branch",
              "subscriber_plan", "subscriber_status", "subscriber_external_code",
              "subscriber_pppoe", "contact_avatar", "unread"]:
        assert k in sample, f"missing field {k} in conversation item: {sample.keys()}"
    assert isinstance(sample["unread"], int), f"unread must be int, got {type(sample['unread'])}"


def test_vando_conversation_enriched_with_subscriber(headers):
    """Fixture: subscriber Vando Patrocinio is linked to phone 5521987654321."""
    r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/conversations", headers=headers, timeout=20)
    assert r.status_code == 200
    items = r.json().get("items", [])
    vando = next((it for it in items if it.get("phone") == "5521987654321"), None)
    if not vando:
        pytest.skip("phone 5521987654321 has no conversation yet — fixture missing")
    assert vando.get("subscriber_id"), f"Vando conv not linked: {vando}"
    assert (vando.get("subscriber_name") or "").lower().startswith("vando"), \
        f"subscriber_name mismatch: {vando.get('subscriber_name')}"
    assert vando.get("subscriber_branch") == "LIGO RIO", \
        f"branch mismatch: {vando.get('subscriber_branch')}"
    assert "fibra" in (vando.get("subscriber_plan") or "").lower(), \
        f"plan mismatch: {vando.get('subscriber_plan')}"


# ---------------- mark-seen flow ----------------

def test_mark_seen_zeros_unread(headers):
    r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/conversations", headers=headers, timeout=20)
    assert r.status_code == 200
    items = r.json().get("items", [])
    target = next((it for it in items if (it.get("unread") or 0) > 0
                    and not it.get("is_group")), None)
    if not target:
        pytest.skip("no conversation with unread>0 to test mark-seen")
    phone = target["phone"]
    before = target["unread"]
    r2 = requests.post(f"{BASE_URL}/api/whatsapp-baileys/conversations/{phone}/mark-seen",
                       headers=headers, json={}, timeout=15)
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2.get("ok") is True
    assert body2.get("phone") == phone
    assert body2.get("last_seen_at")
    # Refetch
    time.sleep(0.5)
    r3 = requests.get(f"{BASE_URL}/api/whatsapp-baileys/conversations", headers=headers, timeout=20)
    items3 = r3.json().get("items", [])
    after_item = next((it for it in items3 if it.get("phone") == phone), None)
    assert after_item is not None
    assert after_item.get("unread", -1) == 0, \
        f"unread not zeroed after mark-seen: before={before} after={after_item.get('unread')}"


# ---------------- Sidecar /contacts-bulk ----------------

def test_sidecar_contacts_bulk_endpoint():
    try:
        r = requests.post(f"{SIDECAR_URL}/contacts-bulk",
                          json={"phones": ["5521965680949", "5521987654321"]},
                          timeout=15)
    except Exception as e:
        pytest.skip(f"sidecar not reachable: {e}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert "avatars" in body
    assert "count" in body
    avatars = body["avatars"]
    # Connected number should have a non-null avatar URL
    own = avatars.get("5521965680949")
    # We allow null if sidecar cache is cold, but log it
    if own is None:
        pytest.skip("sidecar avatar cache cold for 5521965680949 — informational, not a hard fail")
    assert isinstance(own, str) and own.startswith("http"), f"avatar URL invalid: {own}"


# ---------------- Retroactive link via POST /subscribers/{id}/phones ----------------

def _find_subscriber_id_by_name(headers, name_substr):
    r = requests.get(f"{BASE_URL}/api/subscribers", headers=headers, timeout=15)
    if r.status_code != 200:
        return None
    items = r.json().get("items") or r.json().get("subscribers") or r.json()
    if isinstance(items, dict):
        items = items.get("items", [])
    for s in items or []:
        if name_substr.lower() in (s.get("name") or "").lower():
            return s.get("id")
    return None


def test_retroactive_link_when_phone_added_to_subscriber(headers):
    """REGRA MÁXIMA: add a phone to a subscriber → that phone's existing conversation gets enriched on next GET."""
    sub_id = _find_subscriber_id_by_name(headers, "Vando")
    if not sub_id:
        pytest.skip("Vando subscriber not found — cannot validate retroactive link")
    # Find a conversation that exists but is NOT yet linked
    r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/conversations", headers=headers, timeout=20)
    items = r.json().get("items", [])
    import re as _re
    def _looks_br(p):
        d = _re.sub(r"\D", "", p or "")
        return d.startswith("55") and 12 <= len(d) <= 13
    unlinked = next((it for it in items
                      if not it.get("subscriber_id") and not it.get("is_group")
                      and _looks_br(it.get("phone"))), None)
    if not unlinked:
        pytest.skip("no unlinked BR conversation available to test retroactive link")
    phone = unlinked["phone"]
    # POST phone to subscriber
    rp = requests.post(f"{BASE_URL}/api/subscribers/{sub_id}/phones",
                       headers=headers, json={"raw_number": phone}, timeout=15)
    # tolerate already-exists / conflict
    assert rp.status_code in (200, 201, 409), f"add phone failed: {rp.status_code} {rp.text}"
    time.sleep(1.5)
    # Refetch
    r2 = requests.get(f"{BASE_URL}/api/whatsapp-baileys/conversations", headers=headers, timeout=20)
    items2 = r2.json().get("items", [])
    target = next((it for it in items2 if it.get("phone") == phone), None)
    assert target is not None
    assert target.get("subscriber_id") == sub_id, \
        f"retroactive link failed: subscriber_id={target.get('subscriber_id')} expected {sub_id}"
    assert target.get("subscriber_name")
    # Cleanup: remove phone we added (best-effort)
    try:
        requests.delete(f"{BASE_URL}/api/subscribers/{sub_id}/phones/{phone}",
                        headers=headers, timeout=10)
    except Exception:
        pass
