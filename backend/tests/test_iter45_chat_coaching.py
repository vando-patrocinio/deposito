"""Iteration 45: WhatsApp chat coaching popup + customer profile backend validation."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"
PHONE = "552199141226"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def client(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


# --- Auth ---
def test_login_returns_token(token):
    assert isinstance(token, str) and len(token) > 20


# --- Central IA coaching counters ---
def test_coaching_by_user_returns_counters(client):
    r = client.get(f"{BASE_URL}/api/central-ia/coaching/by-user", timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert isinstance(data["items"], list)
    # admin should appear with counts
    admin_item = next((i for i in data["items"] if i.get("user_email") == ADMIN_EMAIL or "Administrador" in (i.get("user_name") or "")), None)
    assert admin_item is not None, f"admin not found in {data}"
    for k in ("user_id", "user_name", "count", "avg_score", "tones", "unread", "ack"):
        assert k in admin_item, f"missing field {k}"
    assert isinstance(admin_item["count"], int) and admin_item["count"] >= 1
    assert isinstance(admin_item["tones"], dict)
    for t in ("positivo", "construtivo", "urgente"):
        assert t in admin_item["tones"]


# --- Coaching for conversation (filtered by user) ---
def test_coaching_for_conversation_filtered(client):
    r = client.get(f"{BASE_URL}/api/central-ia/coaching/for-conversation/{PHONE}", timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    items = data["items"]
    assert isinstance(items, list)
    assert len(items) >= 1, "expected at least 1 coaching for admin on this phone"
    # all items must belong to the logged-in user
    for it in items:
        assert it.get("phone") == PHONE
        assert it.get("user_email") == ADMIN_EMAIL or it.get("user_name") == "Administrador"
        for k in ("id", "score", "tone", "strengths", "improvements", "next_action"):
            assert k in it, f"missing {k}"
        assert it["tone"] in ("positivo", "construtivo", "urgente")


# --- Customer profile (whatsapp + subscriber + olt) ---
def test_customer_profile_shape(client):
    r = client.get(f"{BASE_URL}/api/whatsapp-baileys/customer-profile/{PHONE}", timeout=20)
    assert r.status_code == 200
    data = r.json()
    assert data.get("phone") == PHONE
    assert "whatsapp" in data
    wa = data["whatsapp"]
    for k in ("avatar", "presence", "last_seen"):
        assert k in wa, f"whatsapp missing {k}"
    # subscriber and olt may be null
    assert "subscriber" in data
    assert "olt_signal" in data


# --- Subscribe presence (200 if connected, 503 tolerated if disconnected) ---
def test_subscribe_presence(client):
    r = client.post(f"{BASE_URL}/api/whatsapp-baileys/contact/{PHONE}/subscribe-presence", json={}, timeout=15)
    assert r.status_code in (200, 503), f"unexpected status {r.status_code} {r.text}"
    if r.status_code == 200:
        d = r.json()
        assert d.get("ok") is True
        assert "jid" in d


# --- Coaching action: read ---
def test_coaching_action_read_then_acknowledge(client):
    # get a coaching id for this user/phone
    r = client.get(f"{BASE_URL}/api/central-ia/coaching/for-conversation/{PHONE}", timeout=15)
    assert r.status_code == 200
    items = r.json().get("items", [])
    if not items:
        pytest.skip("no coaching items available")
    cid = items[0]["id"]

    # mark as read
    r1 = client.post(
        f"{BASE_URL}/api/central-ia/coaching/action",
        json={"coaching_id": cid, "action": "read"},
        timeout=15,
    )
    assert r1.status_code == 200, r1.text
    assert r1.json().get("ok") is True

    # acknowledge
    r2 = client.post(
        f"{BASE_URL}/api/central-ia/coaching/action",
        json={"coaching_id": cid, "action": "acknowledged"},
        timeout=15,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json().get("ok") is True

    # verify via list
    r3 = client.get(f"{BASE_URL}/api/central-ia/coaching/for-conversation/{PHONE}", timeout=15)
    assert r3.status_code == 200
    updated = next((i for i in r3.json().get("items", []) if i["id"] == cid), None)
    assert updated is not None
    assert updated.get("acknowledged") is True
    assert updated.get("read") is True
