"""Iter38 — Jerusa Voice pipeline + MagnusBilling/WhatsApp status-summary.

Pre-req: admin@empresa.com / 123456 (administrador) — full access.
Pipeline endpoints exercise real Whisper STT / LLM / TTS via EMERGENT_LLM_KEY.
"""
import base64
import os
import time

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


# -- Fixtures ----------------------------------------------------------------
@pytest.fixture(scope="module")
def session() -> requests.Session:
    s = requests.Session()
    r = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="module")
def started_session(session) -> dict:
    """Inicia a sessão de voz uma vez (gera saudação real via TTS)."""
    r = session.post(
        f"{BASE_URL}/api/voice/sessions/start",
        json={"channel": "browser"},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    return r.json()


# -- 1) Integrations status-summary ------------------------------------------
def test_status_summary_shape(session):
    r = session.get(f"{BASE_URL}/api/aihub/integrations/status-summary", timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    for key in ("magnusbilling", "whatsapp_cloud"):
        assert key in data, f"chave {key} ausente"
        item = data[key]
        for field in ("configured", "status", "last_test_at"):
            assert field in item, f"{key}.{field} ausente"
        assert isinstance(item["configured"], bool)


def test_status_summary_requires_auth():
    r = requests.get(
        f"{BASE_URL}/api/aihub/integrations/status-summary", timeout=20,
    )
    assert r.status_code in (401, 403)


# -- 2) Monitor worker auto-updates last_test_at -----------------------------
@pytest.mark.timeout(180)
def test_monitor_worker_running(session):
    """If MagnusBilling is configured, last_test_at must update within ~70s."""
    r1 = session.get(
        f"{BASE_URL}/api/aihub/integrations/status-summary", timeout=20,
    )
    mb1 = r1.json().get("magnusbilling") or {}
    if not mb1.get("configured"):
        pytest.skip("MagnusBilling not configured — monitor cannot probe.")
    t0 = mb1.get("last_test_at")
    # Wait up to ~80s for monitor tick (interval=60s)
    deadline = time.time() + 80
    last = t0
    while time.time() < deadline:
        time.sleep(10)
        r = session.get(
            f"{BASE_URL}/api/aihub/integrations/status-summary", timeout=20,
        )
        last = (r.json().get("magnusbilling") or {}).get("last_test_at")
        if last and last != t0:
            break
    assert last and last != t0, (
        f"monitor worker did not update last_test_at (t0={t0}, last={last})"
    )


# -- 3) Voice start session --------------------------------------------------
def test_voice_start_session(started_session):
    data = started_session
    assert "session_id" in data and data["session_id"].startswith("voice-")
    assert data["agent"]["name"] == "Jerusa"
    assert isinstance(data["greeting_text"], str) and len(data["greeting_text"]) > 5
    assert data["audio_mime"] == "audio/mpeg"
    audio_b64 = data["greeting_audio_b64"]
    assert isinstance(audio_b64, str) and len(audio_b64) > 5000
    # Validate decodes
    raw = base64.b64decode(audio_b64)
    assert len(raw) > 1000, "greeting audio bytes suspiciously small"
    assert isinstance(data.get("tts_ms"), int)


# -- 4) Voice turn (real STT+LLM+TTS) ----------------------------------------
@pytest.fixture(scope="module")
def sample_mp3(session) -> bytes:
    """Generate a real mp3 saying 'Olá Jerusa, minha internet está lenta hoje'
    by piggy-backing on start_session greeting (it's also Jerusa's voice mp3,
    but Whisper will transcribe to a similar PT greeting — that's good enough
    to validate full pipeline). To make Whisper return user-like text we
    instead generate via a fresh start (greeting is short)."""
    # Generate via /sessions/start which gives us a small valid mp3
    r = session.post(
        f"{BASE_URL}/api/voice/sessions/start",
        json={"channel": "browser"},
        timeout=60,
    )
    assert r.status_code == 200
    return base64.b64decode(r.json()["greeting_audio_b64"])


@pytest.mark.timeout(120)
def test_voice_turn_full_pipeline(session, started_session, sample_mp3):
    sid = started_session["session_id"]
    files = {"audio": ("turn.mp3", sample_mp3, "audio/mpeg")}
    r = session.post(
        f"{BASE_URL}/api/voice/sessions/{sid}/turn",
        files=files,
        timeout=90,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    # transcript is allowed to be empty IF no_speech=True, otherwise must
    # be non-empty
    if data.get("no_speech"):
        pytest.skip("Whisper detected no speech in TTS-generated audio.")
    assert isinstance(data["transcript"], str) and len(data["transcript"]) > 0
    assert isinstance(data["reply_text"], str) and len(data["reply_text"]) > 0
    audio_b64 = data["reply_audio_b64"]
    assert isinstance(audio_b64, str) and len(audio_b64) > 5000
    assert data["audio_mime"] == "audio/mpeg"
    for k in ("stt_ms", "llm_ms", "tts_ms"):
        assert isinstance(data[k], int), f"{k} should be int"


# -- 5) Voice end + GET session ----------------------------------------------
def test_voice_end_and_get(session, started_session):
    sid = started_session["session_id"]
    r = session.post(
        f"{BASE_URL}/api/voice/sessions/{sid}/end",
        json={"reason": "user_hangup"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body.get("ended_at")
    assert isinstance(body.get("transcript_lines"), list)
    # at least greeting line
    assert len(body["transcript_lines"]) >= 1

    # GET status
    r = session.get(f"{BASE_URL}/api/voice/sessions/{sid}", timeout=20)
    assert r.status_code == 200
    s = r.json()
    assert s.get("status") == "ended"
    assert isinstance(s.get("transcript_lines"), list)


# -- 6) MongoDB direct check -------------------------------------------------
def test_aihub_calls_persisted(started_session):
    sid = started_session["session_id"]
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    cli = MongoClient(mongo_url)
    try:
        doc = cli[db_name].aihub_calls.find_one(
            {"session_id": sid}, {"_id": 0}
        )
        assert doc is not None, "aihub_calls doc missing"
        assert doc["channel"] == "browser"
        assert doc["agent_name"] == "Jerusa"
        assert doc.get("status") == "ended"
    finally:
        cli.close()


# -- 7) Regression: old magnusbilling/test endpoint --------------------------
def test_magnusbilling_test_regression(session):
    r = session.post(
        f"{BASE_URL}/api/aihub/integrations/magnusbilling/test", timeout=20,
    )
    # Either 200 (works) or 400 (not configured) — both indicate route works.
    assert r.status_code in (200, 400), r.text
    body = r.json()
    if r.status_code == 200:
        assert "ok" in body
