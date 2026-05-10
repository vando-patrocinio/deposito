"""Iter36 — Atendimento IA Hub (aihub) backend tests.

Cobertura:
- Catálogos (models / tools)
- CRUD de agentes
- Playground multi-turn (chama Emergent LLM key — Gemini 2.5 Flash)
- Sessions / messages
- Integrações (magnusbilling/whatsapp_cloud) com mascaramento
- Test endpoints (sem credenciais válidas → ok=false)
- Webhook receiver público
- Dashboard
"""
import os
import time
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


@pytest.fixture(scope="module")
def auth():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.text}"
    tok = r.json()["access_token"]
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


# ---- Catálogos ---------------------------------------------------------------
class TestCatalog:
    def test_models_non_empty(self, auth):
        r = auth.get(f"{BASE_URL}/api/aihub/catalog/models", timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "models" in data and isinstance(data["models"], list)
        assert len(data["models"]) >= 1
        m0 = data["models"][0]
        assert {"provider", "model", "label"} <= set(m0.keys())

    def test_tools_non_empty(self, auth):
        r = auth.get(f"{BASE_URL}/api/aihub/catalog/tools", timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "tools" in data and len(data["tools"]) >= 1
        t0 = data["tools"][0]
        assert {"id", "label", "description"} <= set(t0.keys())


# ---- Agents CRUD -------------------------------------------------------------
@pytest.fixture(scope="module")
def created_agent(auth):
    payload = {
        "name": f"TEST_Agent_{uuid.uuid4().hex[:6]}",
        "description": "Agente de teste automatizado",
        "initial_message": "Olá! Sou o agente de testes.",
        "system_prompt": "Você é um assistente de testes automatizados. Responda de forma concisa.",
        "model_provider": "gemini",
        "model_name": "gemini-2.5-flash",
        "temperature": 0.5,
        "max_tokens": 300,
        "form_fields": [
            {"key": "nome_cliente", "description": "Nome completo do cliente",
             "question": "Qual é o seu nome completo?", "required": True}
        ],
        "tools_enabled": ["send_whatsapp", "create_lead"],
        "active": True,
    }
    r = auth.post(f"{BASE_URL}/api/aihub/agents", json=payload, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == payload["name"]
    assert body["model_provider"] == "gemini"
    assert body["model_name"] == "gemini-2.5-flash"
    assert body.get("id", "").startswith("agent-")
    assert "_id" not in body  # mongo _id excluded
    yield body
    # teardown
    try:
        auth.delete(f"{BASE_URL}/api/aihub/agents/{body['id']}", timeout=10)
    except Exception:
        pass


class TestAgentsCRUD:
    def test_list_contains_created(self, auth, created_agent):
        r = auth.get(f"{BASE_URL}/api/aihub/agents", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        ids = [a["id"] for a in data["items"]]
        assert created_agent["id"] in ids

    def test_get_single(self, auth, created_agent):
        r = auth.get(f"{BASE_URL}/api/aihub/agents/{created_agent['id']}", timeout=10)
        assert r.status_code == 200
        assert r.json()["id"] == created_agent["id"]

    def test_patch_updates(self, auth, created_agent):
        r = auth.patch(f"{BASE_URL}/api/aihub/agents/{created_agent['id']}",
                       json={"description": "Atualizado", "temperature": 0.9}, timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body["description"] == "Atualizado"
        assert abs(body["temperature"] - 0.9) < 1e-6

    def test_get_unknown_returns_404(self, auth):
        r = auth.get(f"{BASE_URL}/api/aihub/agents/agent-doesnotexist", timeout=10)
        assert r.status_code == 404


# ---- Playground multi-turn ---------------------------------------------------
class TestPlayground:
    @pytest.fixture(scope="class")
    def first_turn(self, auth, created_agent):
        r = auth.post(f"{BASE_URL}/api/aihub/agents/{created_agent['id']}/playground",
                      json={"message": "oi"}, timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "session_id" in data and data["session_id"]
        assert "reply" in data and isinstance(data["reply"], str) and data["reply"].strip()
        assert data["agent_name"] == created_agent["name"]
        assert data["model"].startswith("gemini/")
        assert data["turn_count"] >= 2  # user + assistant
        return data

    def test_first_turn_basic(self, first_turn):
        assert first_turn["session_id"]

    def test_second_turn_keeps_session(self, auth, created_agent, first_turn):
        sid = first_turn["session_id"]
        r = auth.post(f"{BASE_URL}/api/aihub/agents/{created_agent['id']}/playground",
                      json={"session_id": sid, "message": "Meu nome é Diego"}, timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["session_id"] == sid
        assert data["turn_count"] >= 4  # 2 prev + 2 new

    def test_sessions_aggregate(self, auth, created_agent, first_turn):
        r = auth.get(f"{BASE_URL}/api/aihub/agents/{created_agent['id']}/sessions", timeout=10)
        assert r.status_code == 200
        sessions = r.json()["sessions"]
        sids = [s["session_id"] for s in sessions]
        assert first_turn["session_id"] in sids

    def test_session_messages_chronological(self, auth, first_turn):
        r = auth.get(f"{BASE_URL}/api/aihub/sessions/{first_turn['session_id']}/messages",
                     timeout=10)
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) >= 2
        # ordem cronológica ascendente
        ts = [m["created_at"] for m in items]
        assert ts == sorted(ts)
        roles = [m["role"] for m in items]
        assert "user" in roles and "assistant" in roles


# ---- Integrations: MagnusBilling --------------------------------------------
class TestIntegrationsMagnus:
    def test_put_then_list_masks_secret(self, auth):
        cfg = {"url": "https://magnus.example.com",
               "key": "REALKEY1234567890",
               "secret": "REALSECRET1234567890ABC"}
        r = auth.put(f"{BASE_URL}/api/aihub/integrations/magnusbilling",
                     json={"config": cfg}, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        # secrets devem voltar mascarados
        assert "•" in body["config"]["key"]
        assert "•" in body["config"]["secret"]
        assert body["config"]["url"] == cfg["url"]

        r2 = auth.get(f"{BASE_URL}/api/aihub/integrations", timeout=10)
        assert r2.status_code == 200
        items = r2.json()["items"]
        mb = next((i for i in items if i["type"] == "magnusbilling"), None)
        assert mb is not None
        assert "•" in mb["config"]["key"]
        assert "•" in mb["config"]["secret"]

    def test_put_with_masked_value_preserves_real(self, auth):
        # 1) salva valor real
        real_cfg = {"url": "https://magnus.example.com",
                    "key": "REALKEY_KEEP_ME_42",
                    "secret": "REALSECRET_KEEP_ME_42"}
        auth.put(f"{BASE_URL}/api/aihub/integrations/magnusbilling",
                 json={"config": real_cfg}, timeout=10)
        # 2) lê mascarado
        items = auth.get(f"{BASE_URL}/api/aihub/integrations", timeout=10).json()["items"]
        mb = next(i for i in items if i["type"] == "magnusbilling")
        masked_secret = mb["config"]["secret"]
        assert "•" in masked_secret
        # 3) re-PUT com o secret mascarado e key alterada → secret real preservado, key atualizada
        new_payload = {"url": real_cfg["url"], "key": "NEWKEY_CHANGED_999", "secret": masked_secret}
        auth.put(f"{BASE_URL}/api/aihub/integrations/magnusbilling",
                 json={"config": new_payload}, timeout=10)
        # 4) testa endpoint com config inválida — deve retornar ok=false (secret antigo preservado, mas URL fake)
        rt = auth.post(f"{BASE_URL}/api/aihub/integrations/magnusbilling/test", timeout=20)
        assert rt.status_code == 200, rt.text
        body = rt.json()
        assert body["ok"] is False
        assert body.get("error")

    def test_test_without_config_returns_400(self, auth):
        # remove config primeiro
        auth.delete(f"{BASE_URL}/api/aihub/integrations/magnusbilling", timeout=10)
        r = auth.post(f"{BASE_URL}/api/aihub/integrations/magnusbilling/test", timeout=10)
        assert r.status_code == 400


# ---- Integrations: WhatsApp Cloud -------------------------------------------
class TestIntegrationsWhatsapp:
    def test_test_without_config_returns_400(self, auth):
        auth.delete(f"{BASE_URL}/api/aihub/integrations/whatsapp_cloud", timeout=10)
        r = auth.post(f"{BASE_URL}/api/aihub/integrations/whatsapp_cloud/test", timeout=10)
        assert r.status_code == 400

    def test_bogus_credentials_returns_ok_false(self, auth):
        cfg = {"phone_number_id": "999999999999999",
               "access_token": "BOGUS_TOKEN_FOR_TESTING_PURPOSES",
               "graph_version": "v23.0"}
        rput = auth.put(f"{BASE_URL}/api/aihub/integrations/whatsapp_cloud",
                        json={"config": cfg}, timeout=10)
        assert rput.status_code == 200
        rt = auth.post(f"{BASE_URL}/api/aihub/integrations/whatsapp_cloud/test", timeout=20)
        assert rt.status_code == 200, rt.text
        body = rt.json()
        assert body["ok"] is False
        assert body.get("error")


# ---- Webhook receiver --------------------------------------------------------
class TestWebhook:
    def test_webhook_no_auth_creates_call(self):
        s = requests.Session()
        cid_test = "co-demo"
        ext_id = f"call-test-{uuid.uuid4().hex[:8]}"
        payload = {
            "company_id": cid_test,
            "call_id": ext_id,
            "caller": "+5511999990000",
            "callee": "+5511888887777",
            "status": "answered",
            "duration": 42,
        }
        r = s.post(f"{BASE_URL}/api/aihub/webhooks/call-event",
                   json=payload, timeout=10)
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        # GET history (precisa auth)
        a = requests.Session()
        a.headers.update({"Content-Type": "application/json"})
        tok = a.post(f"{BASE_URL}/api/auth/login",
                     json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
                     timeout=10).json()["access_token"]
        a.headers.update({"Authorization": f"Bearer {tok}"})
        time.sleep(0.5)
        r2 = a.get(f"{BASE_URL}/api/aihub/history/calls", timeout=10)
        assert r2.status_code == 200
        ext_ids = [c.get("external_id") for c in r2.json()["items"]]
        assert ext_id in ext_ids


# ---- Dashboard ---------------------------------------------------------------
class TestDashboard:
    def test_shape(self, auth):
        r = auth.get(f"{BASE_URL}/api/aihub/dashboard", timeout=10)
        assert r.status_code == 200
        d = r.json()
        for key in ("agents", "calls", "sessions", "integrations"):
            assert key in d
        assert "total" in d["agents"]
        assert "active" in d["agents"]
        assert "total" in d["calls"]
        assert "total" in d["sessions"]
        assert isinstance(d["integrations"], dict)


# ---- Agent delete cleanup ----------------------------------------------------
class TestAgentDeleteCleanup:
    def test_delete_removes_agent_and_messages(self, auth):
        # cria e usa playground para gerar mensagens, depois deleta
        payload = {
            "name": f"TEST_DelAgent_{uuid.uuid4().hex[:6]}",
            "system_prompt": "Você é um agente temporário para teste de cleanup.",
            "model_provider": "gemini",
            "model_name": "gemini-2.5-flash",
        }
        c = auth.post(f"{BASE_URL}/api/aihub/agents", json=payload, timeout=10)
        assert c.status_code == 200
        aid = c.json()["id"]

        pg = auth.post(f"{BASE_URL}/api/aihub/agents/{aid}/playground",
                       json={"message": "ping"}, timeout=60)
        assert pg.status_code == 200
        sid = pg.json()["session_id"]

        d = auth.delete(f"{BASE_URL}/api/aihub/agents/{aid}", timeout=10)
        assert d.status_code == 200
        assert d.json().get("ok") is True

        # GET 404
        g = auth.get(f"{BASE_URL}/api/aihub/agents/{aid}", timeout=10)
        assert g.status_code == 404

        # session messages limpos
        sm = auth.get(f"{BASE_URL}/api/aihub/sessions/{sid}/messages", timeout=10)
        assert sm.status_code == 200
        assert len(sm.json()["items"]) == 0
