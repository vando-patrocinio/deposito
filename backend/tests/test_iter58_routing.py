"""Iteration 58 — Intelligent routing per inbound message.

Tests:
- Update Isabella agent with routing_intent (vendas, ...)
- Create second agent Bruno Suporte with routing_intent (suporte ...)
- Enable WhatsApp auto-reply
- Inbound with sales intent → outbound from Isabella
- Inbound with support intent (different phone) → outbound from Bruno Suporte
- Second inbound on sales phone → still Isabella (consistency via routed_agent_id)
- Cleanup
"""
import os
import time
import pytest
import requests

_url = os.environ.get("REACT_APP_BACKEND_URL")
if not _url:
    # fallback: read from frontend/.env
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    _url = line.strip().split("=", 1)[1].strip().strip('"')
                    break
    except Exception:
        pass
assert _url, "REACT_APP_BACKEND_URL not set"
BASE_URL = _url.rstrip("/")
WA_TOKEN = "JAALRyFdv9z7OaxeHkoSM4ll4AjpPmhFNHUATVr-mNg"

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PWD = "123456"

PHONE_VENDAS = "5511955550101"
PHONE_SUPORTE = "5511955550102"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                       json={"email": ADMIN_EMAIL, "password": ADMIN_PWD},
                       timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def agent_ids(headers):
    """Ensure Isabella has routing_intent and create Bruno Suporte. Returns ids dict."""
    # Find Isabella
    r = requests.get(f"{BASE_URL}/api/aihub/agents", headers=headers, timeout=15)
    assert r.status_code == 200, r.text
    agents = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
    assert len(agents) >= 1, "Expected at least one agent"
    isabella = next((a for a in agents if "isabella" in (a.get("name") or "").lower()), agents[0])
    isabella_id = isabella["id"]

    # PATCH Isabella with routing_intent
    pr = requests.patch(
        f"{BASE_URL}/api/aihub/agents/{isabella_id}",
        headers=headers,
        json={"routing_intent": "vendas, novos planos, contratação, preço"},
        timeout=15,
    )
    assert pr.status_code == 200, pr.text
    assert pr.json().get("routing_intent", "").lower().find("vendas") >= 0

    # POST Bruno Suporte
    cr = requests.post(
        f"{BASE_URL}/api/aihub/agents",
        headers=headers,
        json={
            "name": "Bruno Suporte",
            "system_prompt": "Você é Bruno, técnico de suporte. Responda breve.",
            "model_provider": "gemini",
            "model_name": "gemini-2.5-flash",
            "routing_intent": "suporte técnico, sem sinal, internet lenta, lentidão",
            "active": True,
        },
        timeout=20,
    )
    assert cr.status_code in (200, 201), cr.text
    bruno_id = cr.json()["id"]

    yield {"isabella": isabella_id, "bruno": bruno_id, "isabella_name": isabella.get("name", "Isabella")}

    # Cleanup: delete Bruno
    requests.delete(f"{BASE_URL}/api/aihub/agents/{bruno_id}", headers=headers, timeout=10)
    # Clear routing_intent? Leave Isabella's routing_intent (testing intent in frontend later)


@pytest.fixture(scope="module")
def autoreply_on(headers, agent_ids):
    pr = requests.put(
        f"{BASE_URL}/api/whatsapp-baileys/auto-reply",
        headers=headers,
        json={"enabled": True, "agent_name": agent_ids["isabella_name"]},
        timeout=15,
    )
    assert pr.status_code == 200, pr.text
    yield
    # Restore: disable
    requests.put(f"{BASE_URL}/api/whatsapp-baileys/auto-reply",
                  headers=headers, json={"enabled": False}, timeout=10)


def _send_inbound(phone, text, msg_id, ts, push_name="Cliente"):
    return requests.post(
        f"{BASE_URL}/api/whatsapp-baileys/inbound",
        headers={"Content-Type": "application/json", "X-WA-Token": WA_TOKEN},
        json={
            "phone": phone,
            "jid": f"{phone}@s.whatsapp.net",
            "text": text,
            "push_name": push_name,
            "message_id": msg_id,
            "timestamp": ts,
        },
        timeout=20,
    )


def _wait_for_outbound(headers, phone, after_iso=None, want_agent_substr=None, timeout_s=40):
    """Polls conversation messages until an outbound (direction=outbound) appears.
    If want_agent_substr provided, returns when the latest outbound matches it.
    Returns the matched outbound message dict or None."""
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        r = requests.get(
            f"{BASE_URL}/api/whatsapp-baileys/conversations/{phone}/messages?limit=20",
            headers=headers, timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            msgs = data if isinstance(data, list) else data.get("items", data.get("messages", []))
            outs = [m for m in msgs if m.get("direction") in ("out", "outbound")]
            # if filter by after_iso (created_at ISO string)
            if after_iso:
                outs = [m for m in outs if (m.get("created_at") or "") > after_iso]
            if outs:
                last = outs[-1]
                if want_agent_substr is None:
                    return last
                agent = (last.get("agent_name") or "").lower()
                if want_agent_substr.lower() in agent:
                    return last
        time.sleep(2)
    return last


# ---- Test cases ----

def test_01_routing_intent_persisted(agent_ids, headers):
    r = requests.get(f"{BASE_URL}/api/aihub/agents/{agent_ids['isabella']}", headers=headers, timeout=10)
    assert r.status_code == 200
    assert "vendas" in (r.json().get("routing_intent") or "").lower()


def test_02_bruno_created(agent_ids, headers):
    r = requests.get(f"{BASE_URL}/api/aihub/agents/{agent_ids['bruno']}", headers=headers, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Bruno Suporte"
    assert "suporte" in (body.get("routing_intent") or "").lower()


def test_03_inbound_vendas_routes_to_isabella(autoreply_on, agent_ids, headers):
    ts = int(time.time())
    after_iso = "2026-01-01T00:00:00"  # accept any
    # use fresh message_id to avoid dedup
    msg_id = f"rt-vendas-fresh-{ts}"
    r = _send_inbound(PHONE_VENDAS,
                      "Bom dia, quero contratar o plano de 600 mega! Qual o preço?",
                      msg_id, ts, "Cliente V")
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True

    out = _wait_for_outbound(headers, PHONE_VENDAS,
                              want_agent_substr="isabella", timeout_s=60)
    assert out is not None, "No outbound auto-reply with Isabella received"
    agent = (out.get("agent_name") or "").lower()
    assert "isabella" in agent, f"Expected Isabella, got agent_name={out.get('agent_name')}"


def test_04_inbound_suporte_routes_to_bruno(autoreply_on, agent_ids, headers):
    ts = int(time.time())
    msg_id = f"rt-supt-fresh-{ts}"
    r = _send_inbound(PHONE_SUPORTE,
                      "Estou sem internet, caiu o sinal aqui em casa",
                      msg_id, ts, "Cliente S")
    assert r.status_code == 200, r.text

    out = _wait_for_outbound(headers, PHONE_SUPORTE,
                              want_agent_substr="bruno", timeout_s=60)
    assert out is not None, "No outbound auto-reply with Bruno received"
    agent = (out.get("agent_name") or "").lower()
    assert "bruno" in agent, f"Expected Bruno Suporte, got agent_name={out.get('agent_name')}"


def test_05_second_inbound_same_phone_keeps_isabella(autoreply_on, agent_ids, headers):
    ts = int(time.time())
    msg_id = f"rt-vendas2-fresh-{ts}"
    # snapshot existing outbound count first
    r0 = requests.get(f"{BASE_URL}/api/whatsapp-baileys/conversations/{PHONE_VENDAS}/messages?limit=50",
                       headers=headers, timeout=10)
    before_count = len([m for m in r0.json().get("items", []) if m.get("direction") in ("out", "outbound")])

    r = _send_inbound(PHONE_VENDAS,
                      "E o de 400 mega quanto custa?",
                      msg_id, ts, "Cliente V")
    assert r.status_code == 200, r.text

    # poll until outbound count grows
    deadline = time.time() + 60
    new_out = None
    while time.time() < deadline:
        rr = requests.get(f"{BASE_URL}/api/whatsapp-baileys/conversations/{PHONE_VENDAS}/messages?limit=50",
                           headers=headers, timeout=10)
        outs = [m for m in rr.json().get("items", []) if m.get("direction") in ("out", "outbound")]
        if len(outs) > before_count:
            new_out = outs[-1]
            break
        time.sleep(2)
    assert new_out is not None, "Second outbound not received"
    agent = (new_out.get("agent_name") or "").lower()
    assert "isabella" in agent, f"Conversation switched agent! got={new_out.get('agent_name')}"


def test_06_cleanup_autoreply_off(headers):
    r = requests.put(f"{BASE_URL}/api/whatsapp-baileys/auto-reply",
                     headers=headers, json={"enabled": False}, timeout=10)
    assert r.status_code == 200
