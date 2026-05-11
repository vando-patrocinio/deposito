"""Iter51 — Validate WhatsApp Baileys /send delivery_status persistence.

Tests for the BUG fix:
- POST /api/whatsapp-baileys/send with OWN connected number → 502 with explicit error
- POST /api/whatsapp-baileys/send with valid different number → 200 + message_id
- Last doc in aihub_wa_messages must have delivery_status ('sent'/'failed')
  and delivery_error populated when failed.
"""
import os
import time
import pytest
import requests

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
    assert url, "REACT_APP_BACKEND_URL missing"
    return url.rstrip("/")


BASE_URL = _load_base_url()
API = f"{BASE_URL}/api"

OWN_PHONE = "5521965680949"          # connected (Patrocínio)
VALID_TARGET = "5521997381702"        # different valid phone

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
               timeout=20)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    token = r.json().get("access_token") or r.json().get("token")
    assert token, f"No token in login response: {r.json()}"
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


# ---- Sanity: sidecar status -------------------------------------------------
def test_sidecar_connected(session):
    r = session.get(f"{API}/whatsapp-baileys/status", timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("connected") is True, f"sidecar not connected: {data}"
    me = data.get("me") or {}
    assert OWN_PHONE in (me.get("id") or ""), \
        f"unexpected connected number: {me}"


# ---- Test 1: Send to OWN number → must 502 with explicit error --------------
def test_send_to_own_number_returns_502(session):
    payload = {"phone": OWN_PHONE, "text": "TEST_iter51_own_number_check"}
    r = session.post(f"{API}/whatsapp-baileys/send", json=payload, timeout=30)
    assert r.status_code == 502, \
        f"expected 502, got {r.status_code}: {r.text}"
    detail = r.json().get("detail", "")
    assert "próprio número" in detail.lower() or "proprio numero" in detail.lower() \
        or "own number" in detail.lower(), \
        f"detail does not mention own number: {detail!r}"


def test_own_number_persists_failed_doc(session):
    """After the own-number send attempt, last outbound to that phone must be
    delivery_status='failed' with delivery_error populated."""
    # ensure recent failed attempt
    payload = {"phone": OWN_PHONE, "text": "TEST_iter51_own_persist"}
    session.post(f"{API}/whatsapp-baileys/send", json=payload, timeout=30)
    time.sleep(0.5)

    r = session.get(f"{API}/whatsapp-baileys/conversations/{OWN_PHONE}/messages",
                    timeout=15)
    assert r.status_code == 200, r.text
    items = r.json().get("items") or []
    # last outbound TEST_iter51_own_persist
    outbound = [m for m in items
                if m.get("direction") == "outbound"
                and "TEST_iter51_own_persist" in (m.get("text") or "")]
    assert outbound, "outbound TEST_iter51_own_persist not persisted"
    last = outbound[-1]
    assert last.get("delivery_status") == "failed", \
        f"delivery_status not 'failed': {last.get('delivery_status')}"
    assert last.get("delivery_error"), \
        f"delivery_error missing: {last}"


# ---- Test 2: Send to a valid different number → must 200 + message_id -------
def test_send_to_valid_other_number(session):
    payload = {"phone": VALID_TARGET,
               "text": "TEST_iter51_delivery_ok " + str(int(time.time()))}
    r = session.post(f"{API}/whatsapp-baileys/send", json=payload, timeout=30)
    # Sidecar real -> if number exists on WhatsApp returns 200, else 502.
    # We do NOT control the remote inbox so we only check that the API path
    # is HEALTHY: either 200+message_id, or 502 (never 500 / never silent 200
    # without message_id).
    assert r.status_code in (200, 502), \
        f"unexpected status {r.status_code}: {r.text}"
    body = r.json()
    if r.status_code == 200:
        assert body.get("ok") is True, f"ok flag not true: {body}"
        assert body.get("message_id"), f"missing message_id in 200: {body}"
    else:
        # 502 must carry detail
        assert body.get("detail"), f"502 without detail: {body}"


def test_other_number_persists_with_delivery_status(session):
    """Last outbound for VALID_TARGET should carry delivery_status field."""
    marker = "TEST_iter51_persist_other " + str(int(time.time()))
    session.post(f"{API}/whatsapp-baileys/send",
                 json={"phone": VALID_TARGET, "text": marker}, timeout=30)
    time.sleep(0.5)
    r = session.get(f"{API}/whatsapp-baileys/conversations/{VALID_TARGET}/messages",
                    timeout=15)
    assert r.status_code == 200, r.text
    items = r.json().get("items") or []
    outbound = [m for m in items
                if m.get("direction") == "outbound"
                and marker in (m.get("text") or "")]
    assert outbound, f"outbound with marker {marker!r} not found"
    last = outbound[-1]
    assert last.get("delivery_status") in ("sent", "failed"), \
        f"delivery_status invalid: {last.get('delivery_status')}"
    if last.get("delivery_status") == "failed":
        assert last.get("delivery_error"), \
            f"failed doc missing delivery_error: {last}"
    else:
        assert last.get("message_id"), \
            f"sent doc missing message_id: {last}"


# ---- Test 3: Validation — empty/short fields --------------------------------
def test_send_empty_text_returns_422(session):
    r = session.post(f"{API}/whatsapp-baileys/send",
                     json={"phone": VALID_TARGET, "text": ""}, timeout=15)
    assert r.status_code == 422, r.text


def test_send_short_phone_returns_422(session):
    r = session.post(f"{API}/whatsapp-baileys/send",
                     json={"phone": "123", "text": "x"}, timeout=15)
    assert r.status_code == 422, r.text
