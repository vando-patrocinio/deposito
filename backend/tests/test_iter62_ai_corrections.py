"""Iter62: 'Edit & Teach' feature — AI corrections + Motor IA non-DeepSeek
support + ai_history / ai_orchestrator integrations.

Backend-only test suite as requested by main agent E1.

Coverage:
1. POST /api/ai-corrections  (create — admin role)
2. GET  /api/ai-corrections  (list filtered by company)
3. DELETE /api/ai-corrections/{id}
4. PUT  /api/motor-ia/config accepts non-DeepSeek vendors (anthropic/openai/google)
5. Internal imports: services.ai_history.fetch_history_turns,
   services.ai_orchestrator.build_orchestrated_context,
   routes.ai_corrections.fetch_recent_for_prompt + format_corrections_for_prompt
6. Non-regression: GET /api/whatsapp-baileys/conversations and /messages
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://dual-combine-3.preview.emergentagent.com",
).rstrip("/")
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def admin_token() -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no token in response: {data}"
    return tok


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {admin_token}",
    }


# ---------------------------------------------------------------------------
# 1) AI Corrections CRUD
# ---------------------------------------------------------------------------

class TestAiCorrectionsCRUD:
    """CRUD for /api/ai-corrections — Edit & Teach feature."""

    _created_ids: list[str] = []

    def test_create_correction(self, auth_headers):
        payload = {
            "phone": "5511999998888",
            "original_msg_id": "wam-TESTITER62",
            "user_question": "TEST_ITER62 minha internet caiu",
            "ai_original_reply": "Por favor reinicie o roteador.",
            "correct_reply": "TEST_ITER62 corrigida — vi aqui que sua ONU está offline, vou abrir chamado.",
            "reason": "TEST_ITER62 IA pediu reinicialização sem checar status real da ONU.",
            "tags": ["TEST_ITER62", "tecnico"],
            "resend_to_client": False,
        }
        r = requests.post(f"{BASE_URL}/api/ai-corrections",
                          headers=auth_headers, json=payload, timeout=20)
        assert r.status_code == 200, f"create failed: {r.status_code} {r.text}"
        doc = r.json()
        # Data assertions
        assert "id" in doc and doc["id"].startswith("corr-")
        assert doc["phone"] == payload["phone"]
        assert doc["user_question"] == payload["user_question"]
        assert doc["ai_original_reply"] == payload["ai_original_reply"]
        assert doc["correct_reply"] == payload["correct_reply"]
        assert doc["reason"] == payload["reason"]
        assert doc["tags"] == ["TEST_ITER62", "tecnico"]
        assert doc["resent_to_client"] is False
        assert doc["corrected_by"] == ADMIN_EMAIL
        assert "_id" not in doc  # MongoDB ObjectId must be excluded
        TestAiCorrectionsCRUD._created_ids.append(doc["id"])

    def test_create_correction_validation_short_reply(self, auth_headers):
        """min_length=2 on correct_reply should reject 1-char input."""
        bad = {
            "phone": "5511999998888",
            "ai_original_reply": "x",
            "correct_reply": "x",  # too short
        }
        r = requests.post(f"{BASE_URL}/api/ai-corrections",
                          headers=auth_headers, json=bad, timeout=15)
        assert r.status_code in (400, 422), \
            f"expected validation error, got {r.status_code} {r.text}"

    def test_list_corrections_contains_new(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/ai-corrections?limit=50",
                         headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "items" in body and "count" in body
        assert isinstance(body["items"], list)
        assert body["count"] == len(body["items"])
        # Verify the just-created correction is present
        ids = {it.get("id") for it in body["items"]}
        for cid in TestAiCorrectionsCRUD._created_ids:
            assert cid in ids, f"created id {cid} not present in list"
        # No mongo _id leak
        for it in body["items"]:
            assert "_id" not in it

    def test_list_corrections_limit_param(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/ai-corrections?limit=1",
                         headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["items"]) <= 1

    def test_delete_correction(self, auth_headers):
        assert TestAiCorrectionsCRUD._created_ids, "no id to delete"
        cid = TestAiCorrectionsCRUD._created_ids[0]
        r = requests.delete(f"{BASE_URL}/api/ai-corrections/{cid}",
                            headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True

        # Verify deletion persisted
        r2 = requests.get(f"{BASE_URL}/api/ai-corrections?limit=200",
                          headers=auth_headers, timeout=15)
        assert r2.status_code == 200
        ids = {it.get("id") for it in r2.json().get("items", [])}
        assert cid not in ids, f"correction {cid} still present after delete"

    def test_delete_unknown_returns_404(self, auth_headers):
        r = requests.delete(
            f"{BASE_URL}/api/ai-corrections/corr-doesnotexistxxx",
            headers=auth_headers, timeout=15,
        )
        assert r.status_code == 404, f"expected 404 got {r.status_code} {r.text}"

    def test_unauth_blocked(self):
        # No auth header → must be 401 or 403
        r = requests.get(f"{BASE_URL}/api/ai-corrections", timeout=10)
        assert r.status_code in (401, 403), \
            f"unauth should be blocked, got {r.status_code}"


# ---------------------------------------------------------------------------
# 2) Motor IA — accepts non-DeepSeek vendors now
# ---------------------------------------------------------------------------

class TestMotorIaMultiVendor:
    """Motor IA used to be DeepSeek-only; now must accept any vendor/model."""

    _original_atendimento_model: str | None = None

    def test_get_config(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/motor-ia/config",
                         headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        cfg = r.json()
        assert isinstance(cfg, dict)
        TestMotorIaMultiVendor._original_atendimento_model = cfg.get(
            "atendimento_model"
        )

    def test_put_config_anthropic_claude(self, auth_headers):
        payload = {"atendimento_model": "anthropic/claude-3.5-sonnet"}
        r = requests.put(f"{BASE_URL}/api/motor-ia/config",
                         headers=auth_headers, json=payload, timeout=15)
        assert r.status_code == 200, f"anthropic claude rejected: {r.status_code} {r.text}"
        cfg = r.json()
        assert cfg.get("atendimento_model") == "anthropic/claude-3.5-sonnet"

    def test_put_config_openai_gpt(self, auth_headers):
        payload = {"atendimento_model": "openai/gpt-4o-mini"}
        r = requests.put(f"{BASE_URL}/api/motor-ia/config",
                         headers=auth_headers, json=payload, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("atendimento_model") == "openai/gpt-4o-mini"

    def test_put_config_google_gemini(self, auth_headers):
        payload = {"atendimento_model": "google/gemini-pro-1.5"}
        r = requests.put(f"{BASE_URL}/api/motor-ia/config",
                         headers=auth_headers, json=payload, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("atendimento_model") == "google/gemini-pro-1.5"

    def test_put_config_invalid_format_rejected(self, auth_headers):
        """Missing slash must be rejected with 400."""
        payload = {"atendimento_model": "invalidmodelnoSlash"}
        r = requests.put(f"{BASE_URL}/api/motor-ia/config",
                         headers=auth_headers, json=payload, timeout=15)
        assert r.status_code == 400, \
            f"expected 400 for bad format, got {r.status_code} {r.text}"

    def test_put_config_fallbacks_filtered(self, auth_headers):
        payload = {
            "atendimento_fallbacks": [
                "anthropic/claude-3-haiku",
                "invalidnoSlash",  # must be filtered out
                "openai/gpt-4o-mini",
            ],
        }
        r = requests.put(f"{BASE_URL}/api/motor-ia/config",
                         headers=auth_headers, json=payload, timeout=15)
        assert r.status_code == 200, r.text
        fallbacks = r.json().get("atendimento_fallbacks") or []
        assert "invalidnoSlash" not in fallbacks
        assert "anthropic/claude-3-haiku" in fallbacks
        assert "openai/gpt-4o-mini" in fallbacks

    def test_restore_original_atendimento_model(self, auth_headers):
        """Cleanup: restore the original atendimento_model so other tests
        / runtime behavior is unaffected.
        """
        original = TestMotorIaMultiVendor._original_atendimento_model
        if not original or "/" not in original:
            original = "deepseek/deepseek-chat"
        r = requests.put(f"{BASE_URL}/api/motor-ia/config",
                         headers=auth_headers,
                         json={"atendimento_model": original}, timeout=15)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# 3) Internal services imports + prompt-block helpers (in-process)
# ---------------------------------------------------------------------------

class TestInternalServiceImports:
    """Validate that ai_history, ai_orchestrator and the correction prompt
    helpers import + execute without raising. Runs in-process (adds the
    backend dir to sys.path).

    NOTE: Motor (async MongoDB driver) binds its executor to the first
    asyncio loop used. Re-creating loops across tests causes
    'Event loop is closed' errors, so we use a single shared module-level
    loop via the `_loop` classmethod.
    """

    _loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def setup_class(cls):
        sys.path.insert(0, "/app/backend")
        cls._loop = asyncio.new_event_loop()

    @classmethod
    def teardown_class(cls):
        if cls._loop:
            cls._loop.close()
            cls._loop = None

    def _run(self, coro):
        return TestInternalServiceImports._loop.run_until_complete(coro)

    def test_import_ai_history_fetch_history_turns(self):
        from services.ai_history import (  # noqa: F401
            DEFAULT_HISTORY_LIMIT,
            fetch_history_turns,
        )
        assert DEFAULT_HISTORY_LIMIT == 100, \
            f"history window must be 100, got {DEFAULT_HISTORY_LIMIT}"
        assert callable(fetch_history_turns)

        result = self._run(fetch_history_turns(
            company_id="co-demo", phone="5511000000000", limit=10,
        ))
        assert isinstance(result, list)

    def test_import_ai_orchestrator_build_context(self):
        from services.ai_orchestrator import build_orchestrated_context  # noqa: F401
        assert callable(build_orchestrated_context)

        out = self._run(build_orchestrated_context(
            company_id="co-demo",
            phone="5511000000000",
            user_text="minha internet caiu sem internet",
        ))
        assert isinstance(out, str)

    def test_corrections_prompt_helpers(self, auth_headers):
        """fetch_recent_for_prompt + format_corrections_for_prompt should
        produce a non-empty formatted block when at least one correction
        exists for the tenant.
        """
        seed = {
            "phone": "5511999997777",
            "ai_original_reply": "Reinicie o roteador.",
            "correct_reply": "TEST_ITER62_PROMPT — verifique a luz vermelha "
                              "do PON antes de pedir reinício.",
            "reason": "Sempre checar PON antes de orientar reinício.",
            "user_question": "minha internet caiu",
        }
        r = requests.post(f"{BASE_URL}/api/ai-corrections",
                          headers=auth_headers, json=seed, timeout=15)
        assert r.status_code == 200, r.text
        seeded_id = r.json()["id"]

        try:
            from routes.ai_corrections import (
                fetch_recent_for_prompt,
                format_corrections_for_prompt,
            )

            items = self._run(fetch_recent_for_prompt("co-demo", limit=5))
            block = format_corrections_for_prompt(items)
            assert isinstance(items, list) and len(items) >= 1
            assert isinstance(block, str) and block
            assert "MEMÓRIA DE CORREÇÕES" in block
            assert "Resposta CORRETA" in block
            assert "TEST_ITER62_PROMPT" in block
        finally:
            requests.delete(f"{BASE_URL}/api/ai-corrections/{seeded_id}",
                            headers=auth_headers, timeout=10)


# ---------------------------------------------------------------------------
# 4) Non-regression: WhatsApp Baileys conversations & messages
# ---------------------------------------------------------------------------

class TestWhatsAppBaileysNonRegression:
    """The prompt builder in whatsapp_baileys.py was modified to inject
    corrections + orchestrator + history. These endpoints must still
    respond 200 even when the sidecar is offline (the user notes this is
    expected — sidecar offline is NOT a regression).
    """

    def test_get_conversations(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/whatsapp-baileys/conversations?limit=20",
            headers=auth_headers, timeout=15,
        )
        assert r.status_code == 200, f"baileys conversations broken: {r.status_code} {r.text[:200]}"
        body = r.json()
        # Accept either {items:[...]} or list
        if isinstance(body, dict):
            assert "items" in body or "conversations" in body
        else:
            assert isinstance(body, list)

    def test_get_messages(self, auth_headers):
        # Pick a phone — try grabbing one from conversations first
        r = requests.get(
            f"{BASE_URL}/api/whatsapp-baileys/conversations?limit=5",
            headers=auth_headers, timeout=15,
        )
        phone = "5511999990000"
        if r.status_code == 200:
            body = r.json()
            convs = body.get("items") if isinstance(body, dict) else body
            if convs:
                phone = (convs[0].get("phone") or convs[0].get("from")
                         or phone)
        r2 = requests.get(
            f"{BASE_URL}/api/whatsapp-baileys/messages?phone={phone}&limit=20",
            headers=auth_headers, timeout=15,
        )
        assert r2.status_code == 200, \
            f"baileys messages broken: {r2.status_code} {r2.text[:200]}"
