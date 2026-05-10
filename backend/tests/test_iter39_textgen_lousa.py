"""Iter39 - Test text-gen endpoint, schedule_lousa_ticket tool, agent fields persistence."""
import os
import pytest
import requests

def _load_base_url():
    url = os.environ.get('REACT_APP_BACKEND_URL')
    if not url:
        envf = '/app/frontend/.env'
        if os.path.exists(envf):
            with open(envf) as f:
                for line in f:
                    if line.startswith('REACT_APP_BACKEND_URL='):
                        url = line.split('=', 1)[1].strip()
                        break
    if not url:
        raise RuntimeError("REACT_APP_BACKEND_URL not set")
    return url.rstrip('/')

BASE_URL = _load_base_url()


@pytest.fixture(scope="module")
def auth_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "admin@empresa.com", "password": "123456"},
                      timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def H(auth_token):
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


# ----------- text-gen ---------------
class TestTextGen:
    def test_textgen_gerar_company_info(self, H):
        r = requests.post(f"{BASE_URL}/api/aihub/agents/text-gen",
                          headers=H, json={
                              "field": "company_info", "mode": "gerar",
                              "current_text": "",
                              "context": "Provedor ISP no RJ"
                          }, timeout=60)
        assert r.status_code == 200, f"got {r.status_code} {r.text[:300]}"
        data = r.json()
        assert data["field"] == "company_info"
        assert data["mode"] == "gerar"
        text = data["text"]
        assert isinstance(text, str)
        assert len(text) > 50, f"text too short: {text!r}"
        # No markdown bullets
        assert "**" not in text, "found markdown bold"
        # No bullet-only lines (allow numbers occasionally) - check it's not all bullets
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        bullet_lines = [l for l in lines if l.startswith(("- ", "* ", "• "))]
        assert len(bullet_lines) <= len(lines) * 0.3, f"too many bullets: {text}"

    def test_textgen_aprimorar_with_text(self, H):
        original = "Texto basico sobre nossa empresa de internet."
        r = requests.post(f"{BASE_URL}/api/aihub/agents/text-gen",
                          headers=H, json={
                              "field": "company_info", "mode": "aprimorar",
                              "current_text": original
                          }, timeout=60)
        assert r.status_code == 200, f"got {r.status_code} {r.text[:300]}"
        data = r.json()
        assert data["text"] != original
        assert len(data["text"]) > 20

    def test_textgen_aprimorar_empty_returns_400(self, H):
        r = requests.post(f"{BASE_URL}/api/aihub/agents/text-gen",
                          headers=H, json={
                              "field": "company_info", "mode": "aprimorar",
                              "current_text": ""
                          }, timeout=30)
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text[:200]}"


# ----------- schedule_lousa_ticket ---------------
class TestScheduleLousa:
    def test_schedule_creates_ticket(self, H):
        payload = {
            "client_name": "TEST_Cliente IA",
            "address": "Rua Teste 123, Centro, Rio de Janeiro",
            "neighborhood": "Centro",
            "phone": "21999990000",
            "relato": "Cliente sem internet há 2 horas, modem aceso vermelho",
            "type": "instalacao",
            "priority": "normal"
        }
        r = requests.post(f"{BASE_URL}/api/aihub/tools/schedule-lousa-ticket",
                          headers=H, json=payload, timeout=30)
        assert r.status_code == 200, f"got {r.status_code} {r.text[:300]}"
        data = r.json()
        assert data["ok"] is True
        assert data["ticket_id"].startswith("tkt-")
        assert data["assigned_to"], "no collaborator assigned"
        t = data["ticket"]
        assert t["client_snapshot"]["relato"].startswith("[IA] ")
        assert t["created_by_source"] == "aihub"
        assert t["type"] == "instalacao"
        assert t["status"] == "pendente"
        # store for next test
        pytest.shared_ticket_id = data["ticket_id"]

    def test_ticket_visible_in_lousa_list(self, H):
        ticket_id = getattr(pytest, "shared_ticket_id", None)
        assert ticket_id, "previous test must run first"
        # Use the gestor admin endpoint to list all tickets
        r = requests.get(f"{BASE_URL}/api/lousa/all",
                         headers=H, timeout=15)
        assert r.status_code == 200, f"got {r.status_code} {r.text[:300]}"
        data = r.json()
        items = data.get("tickets") or data.get("items") or []
        ids = [t.get("id") for t in items if isinstance(t, dict)]
        assert ticket_id in ids, f"ticket {ticket_id} not in lousa list (got {len(ids)} tickets)"
        # also verify direct GET works
        r2 = requests.get(f"{BASE_URL}/api/lousa/tickets/{ticket_id}",
                          headers=H, timeout=15)
        assert r2.status_code == 200
        t = r2.json()
        assert t["client_snapshot"]["relato"].startswith("[IA] ")
        assert t.get("created_by_source") == "aihub"


# ----------- agent fields persistence ---------------
class TestAgentNewFields:
    def test_create_agent_with_new_fields(self, H):
        payload = {
            "name": "TEST_Agent39",
            "system_prompt": "Você é uma atendente de teste para iter39.",
            "company_info": "Empresa Ligo Fibra Telecom RJ",
            "pricing_info": "Plano 100 Mega R$ 89/mes",
            "priority_situations": "Ex-cliente querendo voltar"
        }
        r = requests.post(f"{BASE_URL}/api/aihub/agents",
                          headers=H, json=payload, timeout=15)
        assert r.status_code == 200, f"got {r.status_code} {r.text[:300]}"
        a = r.json()
        aid = a["id"]
        assert a["company_info"] == payload["company_info"]
        assert a["pricing_info"] == payload["pricing_info"]
        assert a["priority_situations"] == payload["priority_situations"]

        # GET back to verify persistence
        r2 = requests.get(f"{BASE_URL}/api/aihub/agents/{aid}",
                          headers=H, timeout=15)
        assert r2.status_code == 200
        a2 = r2.json()
        assert a2["company_info"] == payload["company_info"]
        assert a2["pricing_info"] == payload["pricing_info"]
        assert a2["priority_situations"] == payload["priority_situations"]
        # cleanup
        requests.delete(f"{BASE_URL}/api/aihub/agents/{aid}", headers=H, timeout=15)


# ----------- tools catalog ---------------
class TestToolsCatalog:
    def test_schedule_lousa_in_catalog(self, H):
        r = requests.get(f"{BASE_URL}/api/aihub/catalog/tools",
                         headers=H, timeout=15)
        assert r.status_code == 200
        ids = [t["id"] for t in r.json().get("tools", [])]
        assert "schedule_lousa_ticket" in ids
        assert "schedule_appointment" not in ids


# ----------- regression voice + monitor ---------------
class TestRegression:
    def test_voice_session_start(self, H):
        r = requests.post(f"{BASE_URL}/api/voice/sessions/start",
                          headers=H, json={}, timeout=60)
        assert r.status_code == 200, f"got {r.status_code} {r.text[:300]}"
        data = r.json()
        assert "session_id" in data
        # greeting audio (base64 or url)
        assert any(k in data for k in ("greeting_audio_b64", "greeting_audio", "audio_b64", "audio"))

    def test_status_summary_keys(self, H):
        r = requests.get(f"{BASE_URL}/api/aihub/integrations/status-summary",
                         headers=H, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "magnusbilling" in data
        assert "whatsapp_cloud" in data
