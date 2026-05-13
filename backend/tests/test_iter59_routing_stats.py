"""Iteration 59 — Routing dashboard + IA health + Isabella real reply

Validates:
1) Backend health endpoints (ai-health, auto-reply, conversations, aihub agents).
2) New endpoint GET /api/whatsapp-baileys/routing-stats?days=7 schema.
3) Isabella actually replies to inbound (real LLM call) — outbound persisted.
"""
import os
import time
import pytest
import requests

def _load_base_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    url = line.strip().split("=", 1)[1]
                    break
    assert url, "REACT_APP_BACKEND_URL not found"
    return url.rstrip("/")


BASE_URL = _load_base_url()
WA_TOKEN = None
# Read from backend .env
with open("/app/backend/.env") as _f:
    for _l in _f:
        if _l.startswith("WA_INBOUND_TOKEN="):
            WA_TOKEN = _l.strip().split("=", 1)[1]
            break


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "admin@empresa.com", "password": "123456"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---------------- 1) Health basics ----------------
def test_ai_health_endpoint(auth_headers):
    r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/ai-health", headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "status" in d
    assert d["status"] in ("healthy", "degraded"), f"AI health is {d['status']}: {d}"


def test_auto_reply_state(auth_headers):
    r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/auto-reply", headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("enabled") is True, f"auto-reply must be ENABLED: {d}"
    assert d.get("agent_name") == "Isabella", f"agent must be Isabella, got {d.get('agent_name')}"


def test_conversations_list(auth_headers):
    r = requests.get(f"{BASE_URL}/api/whatsapp-baileys/conversations", headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    # Response can be a dict {items:[...]} or list
    items = d.get("items") if isinstance(d, dict) else d
    assert isinstance(items, list)


def test_aihub_agents_isabella(auth_headers):
    r = requests.get(f"{BASE_URL}/api/aihub/agents", headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    items = d.get("items") if isinstance(d, dict) else d
    names = [a.get("name") for a in items]
    assert "Isabella" in names, f"Isabella not in agents: {names}"
    isa = next(a for a in items if a.get("name") == "Isabella")
    assert isa.get("active") is True, f"Isabella must be active: {isa}"


# ---------------- 2) routing-stats schema ----------------
def test_routing_stats_schema(auth_headers):
    r = requests.get(
        f"{BASE_URL}/api/whatsapp-baileys/routing-stats?days=7",
        headers=auth_headers,
        timeout=20,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    for k in (
        "period_days",
        "total_responses",
        "total_routed_conversations",
        "human_handoffs",
        "by_agent",
        "by_reason",
        "agents_meta",
    ):
        assert k in d, f"missing key {k}: {list(d.keys())}"
    assert d["period_days"] == 7
    assert isinstance(d["by_agent"], list)
    assert isinstance(d["by_reason"], list)
    assert isinstance(d["agents_meta"], list)

    for a in d["by_agent"]:
        for k in ("agent_name", "total", "sent", "failed", "pct", "success_rate"):
            assert k in a, f"by_agent missing {k}: {a}"

    assert len(d["agents_meta"]) > 0, "Should have at least one agent in meta"
    for m in d["agents_meta"]:
        for k in ("id", "name", "active", "routing_intent", "has_routing_intent"):
            assert k in m, f"agents_meta missing {k}: {m}"


def test_routing_stats_24h(auth_headers):
    r = requests.get(
        f"{BASE_URL}/api/whatsapp-baileys/routing-stats?days=1",
        headers=auth_headers,
        timeout=20,
    )
    assert r.status_code == 200
    assert r.json()["period_days"] == 1


# ---------------- 3) Isabella real reply ----------------
def test_isabella_replies_inbound(auth_headers):
    assert WA_TOKEN, "WA_INBOUND_TOKEN missing in /app/backend/.env"
    phone = "5511988887777"
    payload = {
        "phone": phone,
        "jid": f"{phone}@s.whatsapp.net",
        "text": "Bom dia! Vocês tem plano fibra de 1 giga?",
        "message_id": f"wamid.test-iter59-{int(time.time())}",
        "push_name": "Teste Iter59",
    }
    r = requests.post(
        f"{BASE_URL}/api/whatsapp-baileys/inbound",
        json=payload,
        headers={"X-WA-Token": WA_TOKEN, "Content-Type": "application/json"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    # Wait for the LLM to respond and message to be persisted
    time.sleep(8)
    r2 = requests.get(
        f"{BASE_URL}/api/whatsapp-baileys/conversations/{phone}/messages?limit=5",
        headers=auth_headers,
        timeout=15,
    )
    assert r2.status_code == 200, r2.text
    d = r2.json()
    items = d.get("items") if isinstance(d, dict) else d
    assert isinstance(items, list) and len(items) >= 1
    outbound = [
        m for m in items
        if (m.get("direction") in ("outbound", "out"))
        and m.get("agent_name") == "Isabella"
    ]
    assert outbound, f"No Isabella outbound message: {items}"
    last = outbound[0]
    assert last.get("delivery_status") == "sent", f"delivery_status not 'sent': {last}"
    assert (last.get("text") or "").strip(), f"empty text: {last}"
