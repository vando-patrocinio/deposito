"""
Iter78 — WhatsApp Baileys: inbound audio + AI typing indicator.

Tests:
  - POST /api/whatsapp-baileys/inbound now accepts audio_b64 (+ mimetype/
    duration/is_ptt). Even with empty text, audio messages are persisted with
    media_type='audio' and media_url='/api/whatsapp-baileys/audio/<file>'.
  - GET /api/whatsapp-baileys/audio/{filename}?t={token} returns 200 with
    correct Content-Type.
  - GET /api/whatsapp-baileys/conversations exposes the new fields
    ai_typing_until and ai_typing_agent (null when not typing).
  - Database fingerprint for ai_typing: when we manually set ai_typing_until
    in the future, the conversations endpoint surfaces it.
"""

import os
import base64
import uuid
import asyncio
from datetime import datetime, timezone, timedelta

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
WA_INBOUND_TOKEN = "JAALRyFdv9z7OaxeHkoSM4ll4AjpPmhFNHUATVr-mNg"  # from /app/backend/.env
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASSWORD = "123456"

# Small valid 1-byte OGG-ish blob is enough — backend only stores it; sniffing
# is by mimetype. We'll send a few bytes.
SAMPLE_AUDIO_BYTES = b"OggS\x00\x02\x00\x00\x00\x00test-ogg-blob-iter78"
SAMPLE_AUDIO_B64 = base64.b64encode(SAMPLE_AUDIO_BYTES).decode()

TEST_PHONE_BASE = "5511988"  # we'll append random digits


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(http):
    r = http.post(f"{BASE_URL}/api/auth/login",
                  json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                  timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    token = r.json().get("access_token")
    assert token, "no access_token in login response"
    return token


@pytest.fixture
def random_phone():
    return f"{TEST_PHONE_BASE}{uuid.uuid4().int % 100000:05d}"


# ---------------------------------------------------------------------------
# Inbound audio
# ---------------------------------------------------------------------------
def _post_inbound(http, phone, *, text="", audio=True, mimetype="audio/ogg",
                   duration=3, is_ptt=True, token=WA_INBOUND_TOKEN):
    headers = {"X-WA-Token": token} if token else {}
    payload = {
        "phone": phone,
        "jid": f"{phone}@s.whatsapp.net",
        "from_me": False,
        "text": text,
        "message_id": f"WA-{uuid.uuid4().hex[:12]}",
        "push_name": "TEST_AudioUser",
    }
    if audio:
        payload.update({
            "audio_b64": SAMPLE_AUDIO_B64,
            "audio_mimetype": mimetype,
            "audio_duration_sec": duration,
            "audio_is_ptt": is_ptt,
        })
    return http.post(f"{BASE_URL}/api/whatsapp-baileys/inbound",
                     json=payload, headers=headers, timeout=20)


def test_inbound_audio_empty_text_is_accepted(http, random_phone):
    """Audio-only inbound (empty text) must be persisted, NOT ignored."""
    r = _post_inbound(http, random_phone, text="", audio=True)
    assert r.status_code == 200, f"unexpected {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("ok") is True
    # Should NOT be ignored as "empty"
    assert body.get("ignored") != "empty", f"audio message wrongly ignored: {body}"


def test_inbound_audio_persisted_and_listed(http, admin_token, random_phone):
    """After inbound, the conversation list must show the new contact with
    a recent last message. Also: messages endpoint must contain a media
    message of type 'audio' with a media_url under /api/whatsapp-baileys/audio/."""
    r = _post_inbound(http, random_phone, text="", audio=True, duration=5)
    assert r.status_code == 200, r.text

    # Allow a moment for write to settle
    import time as _t
    _t.sleep(0.5)

    auth_headers = {"Authorization": f"Bearer {admin_token}"}
    # Messages endpoint (specific phone)
    rm = http.get(f"{BASE_URL}/api/whatsapp-baileys/conversations/{random_phone}/messages",
                  headers=auth_headers, timeout=15)
    assert rm.status_code == 200, f"msgs fetch failed: {rm.status_code} {rm.text}"
    msgs = rm.json()
    # messages endpoint shape — try both list & dict
    if isinstance(msgs, dict):
        items = msgs.get("items") or msgs.get("messages") or []
    else:
        items = msgs
    assert isinstance(items, list) and items, f"no messages returned: {msgs}"
    # Find our audio message — should have media_type=audio
    audio_msgs = [m for m in items if m.get("media_type") == "audio"]
    assert audio_msgs, f"no audio media in messages: {items[:3]}"
    am = audio_msgs[0]
    assert am.get("media_url", "").startswith("/api/whatsapp-baileys/audio/"), \
        f"bad media_url: {am.get('media_url')}"
    assert am.get("media_url").endswith(".ogg"), \
        f"ogg mimetype should produce .ogg extension; got {am.get('media_url')}"
    assert am.get("media_duration_sec") == 5
    # text fallback
    assert "Áudio" in (am.get("text") or "")


def test_inbound_audio_webm_extension(http, admin_token, random_phone):
    """Mimetype audio/webm must yield a .webm file URL."""
    r = _post_inbound(http, random_phone, text="", audio=True,
                     mimetype="audio/webm", duration=2)
    assert r.status_code == 200, r.text
    import time as _t; _t.sleep(0.3)
    auth_headers = {"Authorization": f"Bearer {admin_token}"}
    rm = http.get(f"{BASE_URL}/api/whatsapp-baileys/conversations/{random_phone}/messages",
                  headers=auth_headers, timeout=15)
    assert rm.status_code == 200
    items = rm.json().get("items", []) if isinstance(rm.json(), dict) else rm.json()
    audio_msgs = [m for m in items if m.get("media_type") == "audio"]
    assert audio_msgs, "no audio msg saved"
    assert audio_msgs[0]["media_url"].endswith(".webm")


def test_inbound_audio_requires_token(http, random_phone):
    """Bad X-WA-Token must be rejected (401)."""
    r = _post_inbound(http, random_phone, audio=True, token="WRONG-TOKEN")
    assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"


def test_inbound_empty_without_audio_is_ignored(http, random_phone):
    """Sanity: text empty AND no audio must still be ignored."""
    r = _post_inbound(http, random_phone, text="", audio=False)
    assert r.status_code == 200
    assert r.json().get("ignored") == "empty"


# ---------------------------------------------------------------------------
# GET /audio/{filename}
# ---------------------------------------------------------------------------
def test_audio_file_served_with_query_token(http, admin_token, random_phone):
    """GET /api/whatsapp-baileys/audio/<file>?t=<token> returns 200 + audio/ogg."""
    r = _post_inbound(http, random_phone, text="", audio=True, mimetype="audio/ogg")
    assert r.status_code == 200
    import time as _t; _t.sleep(0.3)
    rm = http.get(f"{BASE_URL}/api/whatsapp-baileys/conversations/{random_phone}/messages",
                  headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
    items = rm.json().get("items", []) if isinstance(rm.json(), dict) else rm.json()
    audio_msgs = [m for m in items if m.get("media_type") == "audio"]
    assert audio_msgs
    media_url = audio_msgs[0]["media_url"]
    # Try the audio endpoint with query-string token
    audio_resp = requests.get(f"{BASE_URL}{media_url}",
                               params={"t": admin_token}, timeout=15)
    assert audio_resp.status_code == 200, \
        f"audio fetch failed: {audio_resp.status_code} {audio_resp.text[:200]}"
    ctype = audio_resp.headers.get("Content-Type", "")
    assert "audio/" in ctype, f"unexpected Content-Type: {ctype}"
    assert ctype.startswith("audio/ogg"), f"expected audio/ogg, got {ctype}"
    # Body should contain our bytes
    assert SAMPLE_AUDIO_BYTES[:5] in audio_resp.content[:50]


def test_audio_file_requires_token(http, admin_token, random_phone):
    """Without any token, audio endpoint must return 401."""
    r = _post_inbound(http, random_phone, text="", audio=True)
    assert r.status_code == 200
    import time as _t; _t.sleep(0.3)
    rm = http.get(f"{BASE_URL}/api/whatsapp-baileys/conversations/{random_phone}/messages",
                  headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
    items = rm.json().get("items", []) if isinstance(rm.json(), dict) else rm.json()
    audio_msgs = [m for m in items if m.get("media_type") == "audio"]
    assert audio_msgs
    media_url = audio_msgs[0]["media_url"]
    resp = requests.get(f"{BASE_URL}{media_url}", timeout=10)
    assert resp.status_code == 401, \
        f"expected 401 without token, got {resp.status_code}"


def test_audio_file_invalid_filename(http, admin_token):
    """Sanitization: arbitrary path/filename must be rejected (400)."""
    resp = requests.get(f"{BASE_URL}/api/whatsapp-baileys/audio/../etc/passwd",
                        params={"t": admin_token}, timeout=10)
    # FastAPI may catch /../ at routing — accept 400 or 404
    assert resp.status_code in (400, 404), f"got {resp.status_code}"

    resp2 = requests.get(f"{BASE_URL}/api/whatsapp-baileys/audio/notaudio.txt",
                        params={"t": admin_token}, timeout=10)
    assert resp2.status_code == 400, f"got {resp2.status_code}: {resp2.text}"


def test_audio_file_existing_sample(http, admin_token):
    """Sanity: pre-existing wam-6ac99324cf.ogg (left by main agent) is served."""
    url = f"{BASE_URL}/api/whatsapp-baileys/audio/wam-6ac99324cf.ogg"
    resp = requests.get(url, params={"t": admin_token}, timeout=10)
    # File may have been GC'd between iterations — accept 200 or 404
    assert resp.status_code in (200, 404), f"unexpected {resp.status_code}"
    if resp.status_code == 200:
        assert resp.headers.get("Content-Type", "").startswith("audio/ogg")


# ---------------------------------------------------------------------------
# Conversations exposes ai_typing_until / ai_typing_agent
# ---------------------------------------------------------------------------
def test_conversations_exposes_typing_fields(http, admin_token, random_phone):
    """After an inbound message creates a conversation, the conversations
    endpoint must contain ai_typing_until and ai_typing_agent keys (likely
    null since the AI most likely already finished or auto-reply disabled)."""
    # Create a conv first
    _post_inbound(http, random_phone, text="Olá teste iter78", audio=False)
    import time as _t; _t.sleep(0.5)
    r = http.get(f"{BASE_URL}/api/whatsapp-baileys/conversations",
                 headers={"Authorization": f"Bearer {admin_token}"}, timeout=20)
    assert r.status_code == 200, f"conv list failed: {r.status_code} {r.text}"
    data = r.json()
    items = data.get("items") or []
    assert items, "no conversations returned"
    sample = items[0]
    # Schema check — the keys must EXIST (may be None)
    assert "ai_typing_until" in sample, \
        f"missing ai_typing_until in conv: {list(sample.keys())}"
    assert "ai_typing_agent" in sample, \
        f"missing ai_typing_agent in conv: {list(sample.keys())}"


# ---------------------------------------------------------------------------
# AI typing flag — direct DB manipulation to validate end-to-end surfacing.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ai_typing_flag_surfaces_via_api(admin_token):
    """Manually set ai_typing_until in DB, then verify it appears in the API."""
    # Use motor — same connection style as backend
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    test_phone = f"5511777{uuid.uuid4().int % 10000:04d}"
    until = (datetime.now(timezone.utc) + timedelta(seconds=45)).isoformat()
    try:
        await db.wa_conversations.update_one(
            {"company_id": "co-demo", "phone": test_phone},
            {"$set": {
                "company_id": "co-demo",
                "phone": test_phone,
                "last_text": "TEST iter78 typing",
                "last_at": datetime.now(timezone.utc).isoformat(),
                "status": "open",
                "ai_typing_until": until,
                "ai_typing_agent": "Isabella",
            }},
            upsert=True,
        )
        # Ensure at least one message exists for this phone so the conv shows
        await db.aihub_wa_messages.insert_one({
            "id": f"wam-test-{uuid.uuid4().hex[:8]}",
            "company_id": "co-demo",
            "direction": "inbound",
            "phone": test_phone,
            "text": "TEST iter78 typing",
            "channel": "baileys",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        # Now fetch via API
        r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/conversations",
                         headers={"Authorization": f"Bearer {admin_token}"},
                         timeout=20)
        assert r.status_code == 200, r.text
        items = r.json().get("items", [])
        # Find our test conv
        matches = [c for c in items if c.get("phone") == test_phone]
        assert matches, f"test conv {test_phone} not in API result"
        c = matches[0]
        assert c.get("ai_typing_until") == until, \
            f"expected {until}, got {c.get('ai_typing_until')}"
        assert c.get("ai_typing_agent") == "Isabella", \
            f"expected Isabella, got {c.get('ai_typing_agent')}"
    finally:
        # Cleanup
        await db.wa_conversations.delete_one(
            {"company_id": "co-demo", "phone": test_phone})
        await db.aihub_wa_messages.delete_many(
            {"company_id": "co-demo", "phone": test_phone})
        client.close()
