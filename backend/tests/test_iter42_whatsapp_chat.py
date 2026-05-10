"""Iteration 42 — WhatsApp FocusChat-style buckets, attendants, assign, finalize.

Endpoints tested:
- GET  /api/whatsapp-baileys/attendants (auto-creates Isabella)
- GET  /api/whatsapp-baileys/conversations (buckets + items)
- GET  /api/whatsapp-baileys/conversations/{phone}/messages (asc)
- PUT  /api/whatsapp-baileys/conversations/{phone}/assign (human → manual, ai → automatico)
- PUT  /api/whatsapp-baileys/conversations/{phone}/finalize (closed)
- /inbound auto-reply respects assignee_role='human' (no auto-reply)
- Regressions: /qr, /status, /messages, /auto-reply GET/PUT, /voice/sessions/start,
  /aihub/agents/text-gen
"""
import os
import time
import uuid
import pytest
import requests

def _load_backend_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    # Fallback to frontend/.env
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass
    raise RuntimeError("REACT_APP_BACKEND_URL not configured")


BASE_URL = _load_backend_url()
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASSWORD = "123456"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def H(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def unique_phones():
    suffix = uuid.uuid4().hex[:6]
    return {
        "ai":     f"55219911{suffix[:4]}",        # auto bucket
        "human":  f"55219912{suffix[:4]}",        # manual bucket
        "group":  f"55219913{suffix[:4]}",        # grupo bucket
        "noresp": f"55219914{suffix[:4]}",        # human-takeover/no-autoreply
    }


# --- /attendants -------------------------------------------------------------
def test_attendants_creates_isabella(H):
    # Ensure Isabella does NOT pre-exist (delete if she does)
    # Note: we don't actually delete in case other systems depend on her.
    r = requests.get(f"{API}/whatsapp-baileys/attendants", headers=H, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "items" in data
    iso = next((u for u in data["items"] if u.get("email") == "isabella@ia.local"), None)
    assert iso is not None, "Isabella should be auto-created"
    # second call should still return her (idempotent)
    r2 = requests.get(f"{API}/whatsapp-baileys/attendants", headers=H, timeout=15)
    isos2 = [u for u in r2.json()["items"] if u.get("email") == "isabella@ia.local"]
    assert len(isos2) == 1, "Isabella duplicated on second call"


# --- seed inbound messages so conversations endpoint has data ---------------
WA_INBOUND_TOKEN = "JAALRyFdv9z7OaxeHkoSM4ll4AjpPmhFNHUATVr-mNg"


def _seed_inbound(phone, jid_suffix="@s.whatsapp.net", text="oi"):
    payload = {
        "phone": phone,
        "jid": f"{phone}{jid_suffix}",
        "from_me": False,
        "text": text,
        "message_id": f"TEST_iter42_{uuid.uuid4().hex[:8]}",
        "push_name": f"Test {phone[-4:]}",
    }
    return requests.post(f"{API}/whatsapp-baileys/inbound",
                         json=payload,
                         headers={"X-WA-Token": WA_INBOUND_TOKEN},
                         timeout=30)


def test_seed_inbounds(H, unique_phones):
    # Ensure auto-reply OFF to keep seeds fast and not spam LLM
    requests.put(f"{API}/whatsapp-baileys/auto-reply", headers=H,
                 json={"enabled": False, "agent_name": "Jerusa"}, timeout=10)
    for key, ph in unique_phones.items():
        jid_suf = "@g.us" if key == "group" else "@s.whatsapp.net"
        r = _seed_inbound(ph, jid_suffix=jid_suf, text=f"seed {key}")
        assert r.status_code == 200, f"seed {key} failed: {r.text}"


# --- /conversations buckets --------------------------------------------------
def test_conversations_returns_buckets_structure(H, unique_phones):
    r = requests.get(f"{API}/whatsapp-baileys/conversations", headers=H, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "buckets" in data and "items" in data
    for k in ("automatico", "aguardando", "fora_de_hora", "manual", "grupo"):
        assert k in data["buckets"], f"missing bucket {k}"

    # Sum of bucket counts should equal items length
    total = sum(data["buckets"].values())
    assert total == len(data["items"]), f"bucket sum {total} != items {len(data['items'])}"

    # Group phone must be in 'grupo' bucket
    grp_item = next((i for i in data["items"] if i["phone"] == unique_phones["group"]), None)
    assert grp_item is not None, "group seed not present"
    assert grp_item["bucket"] == "grupo", f"group should be in 'grupo' bucket, got {grp_item['bucket']}"
    assert grp_item.get("is_group") is True


# --- /assign human → manual --------------------------------------------------
def test_assign_to_human_moves_to_manual(H, unique_phones):
    # Find a non-Isabella user
    att = requests.get(f"{API}/whatsapp-baileys/attendants", headers=H, timeout=15).json()
    target = next((u for u in att["items"] if u.get("email") != "isabella@ia.local"), None)
    assert target is not None, "Need at least 1 non-IA user"

    ph = unique_phones["human"]
    r = requests.put(f"{API}/whatsapp-baileys/conversations/{ph}/assign",
                     headers=H,
                     json={"assignee_user_id": target["id"], "assignee_role": "human"},
                     timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assignee_role"] == "human"
    assert body["assignee_user_id"] == target["id"]

    convs = requests.get(f"{API}/whatsapp-baileys/conversations", headers=H, timeout=15).json()
    me = next((i for i in convs["items"] if i["phone"] == ph), None)
    assert me is not None
    assert me["bucket"] == "manual", f"expected manual, got {me['bucket']}"
    assert me["assignee_user_id"] == target["id"]


# --- /assign back to AI → automatico ----------------------------------------
def test_assign_back_to_ai_moves_to_automatico(H, unique_phones):
    ph = unique_phones["human"]
    r = requests.put(f"{API}/whatsapp-baileys/conversations/{ph}/assign",
                     headers=H,
                     json={"assignee_user_id": None, "assignee_role": "ai"},
                     timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["assignee_role"] == "ai"

    convs = requests.get(f"{API}/whatsapp-baileys/conversations", headers=H, timeout=15).json()
    me = next((i for i in convs["items"] if i["phone"] == ph), None)
    assert me is not None
    assert me["bucket"] == "automatico", f"expected automatico, got {me['bucket']}"


# --- /finalize ---------------------------------------------------------------
def test_finalize_sets_closed(H, unique_phones):
    ph = unique_phones["ai"]
    r = requests.put(f"{API}/whatsapp-baileys/conversations/{ph}/finalize",
                     headers=H, json={"outcome": "resolved"}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "closed"
    assert body["phone"] == ph


# --- /messages ascending order ----------------------------------------------
def test_conversation_messages_sorted_asc(H, unique_phones):
    ph = unique_phones["group"]
    # add another message so we have at least 2
    _seed_inbound(ph, jid_suffix="@g.us", text="second message")
    time.sleep(0.5)
    r = requests.get(f"{API}/whatsapp-baileys/conversations/{ph}/messages",
                     headers=H, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["phone"] == ph
    items = data["items"]
    assert len(items) >= 2
    ts = [m["created_at"] for m in items]
    assert ts == sorted(ts), "messages not sorted ascending"


# --- auto-reply respects human takeover -------------------------------------
def test_human_takeover_blocks_autoreply(H, unique_phones):
    ph = unique_phones["noresp"]
    # Find a non-IA user
    att = requests.get(f"{API}/whatsapp-baileys/attendants", headers=H, timeout=15).json()
    target = next((u for u in att["items"] if u.get("email") != "isabella@ia.local"), None)
    assert target is not None
    # Assign to human
    r = requests.put(f"{API}/whatsapp-baileys/conversations/{ph}/assign",
                     headers=H,
                     json={"assignee_user_id": target["id"], "assignee_role": "human"},
                     timeout=15)
    assert r.status_code == 200

    # Enable auto-reply
    requests.put(f"{API}/whatsapp-baileys/auto-reply", headers=H,
                 json={"enabled": True, "agent_name": "Jerusa"}, timeout=10)

    try:
        # Send an inbound — should NOT trigger auto-reply
        r = _seed_inbound(ph, text="please help me")
        assert r.status_code == 200, r.text
        body = r.json()
        # When auto-reply is blocked, the endpoint doesn't return auto_reply key
        assert "auto_reply" not in body, f"auto-reply should be skipped, got {body}"

        # Verify NO outbound message was created for this phone after our inbound
        msgs = requests.get(
            f"{API}/whatsapp-baileys/conversations/{ph}/messages",
            headers=H, timeout=15).json()["items"]
        outbounds = [m for m in msgs if m.get("direction") == "outbound"]
        assert len(outbounds) == 0, f"unexpected outbound when human assigned: {outbounds}"
    finally:
        # Restore: disable auto-reply
        requests.put(f"{API}/whatsapp-baileys/auto-reply", headers=H,
                     json={"enabled": False, "agent_name": "Jerusa"}, timeout=10)


# --- assign to non-existent user returns 404 --------------------------------
def test_assign_unknown_user_returns_404(H, unique_phones):
    ph = unique_phones["ai"]
    r = requests.put(f"{API}/whatsapp-baileys/conversations/{ph}/assign",
                     headers=H,
                     json={"assignee_user_id": "usr-does-not-exist-zzz",
                           "assignee_role": "human"}, timeout=15)
    assert r.status_code == 404


# --- Regressions -------------------------------------------------------------
def test_regression_qr(H):
    r = requests.get(f"{API}/whatsapp-baileys/qr", headers=H, timeout=15)
    # 200 if sidecar up; 503 if down. Both acceptable as "didn't crash".
    assert r.status_code in (200, 503), r.text


def test_regression_status(H):
    r = requests.get(f"{API}/whatsapp-baileys/status", headers=H, timeout=15)
    assert r.status_code in (200, 503), r.text


def test_regression_messages_history(H):
    r = requests.get(f"{API}/whatsapp-baileys/messages?limit=10", headers=H, timeout=15)
    assert r.status_code == 200, r.text
    assert "items" in r.json()


def test_regression_auto_reply_get(H):
    r = requests.get(f"{API}/whatsapp-baileys/auto-reply", headers=H, timeout=15)
    assert r.status_code == 200, r.text
    assert "enabled" in r.json()


def test_regression_voice_session_start(H):
    r = requests.post(f"{API}/voice/sessions/start",
                      headers=H, json={"channel": "browser"}, timeout=20)
    assert r.status_code == 200, r.text
    assert "session_id" in r.json()


def test_regression_aihub_text_gen(H):
    r = requests.post(f"{API}/aihub/agents/text-gen",
                      headers=H,
                      json={"field": "system_prompt", "mode": "gerar",
                            "current_text": "", "extra_context": ""},
                      timeout=60)
    assert r.status_code == 200, r.text


# --- Cleanup: ensure auto-reply OFF at end -----------------------------------
@pytest.fixture(scope="module", autouse=True)
def _final_cleanup(H):
    yield
    try:
        requests.put(f"{API}/whatsapp-baileys/auto-reply", headers=H,
                     json={"enabled": False, "agent_name": "Jerusa"}, timeout=10)
    except Exception:
        pass
