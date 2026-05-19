"""iter106 — Refactor WhatsAppChatLayout.js + whatsapp_baileys.py.

Garantia de backward-compat:
- Endpoints WhatsApp continuam respondendo (status_code esperado).
- Imports backward-compat dos símbolos extraídos para services/wa/*.
- Função _is_sales_completion ainda detecta padrões de venda.
- Cascata IA continua acessível via /api/ai-config.
- /api/motor-ia/usage expõe cache_hit_rate_pct / cache_savings_usd.
"""
from __future__ import annotations

import os
import pytest
import requests


def _read_backend_url():
    v = os.environ.get("REACT_APP_BACKEND_URL", "")
    if v:
        return v.rstrip("/")
    for path in ("/app/frontend/.env",):
        try:
            with open(path) as fh:
                for line in fh:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        return line.split("=", 1)[1].strip().rstrip("/")
        except FileNotFoundError:
            pass
    pytest.skip("REACT_APP_BACKEND_URL not set")


BASE_URL = _read_backend_url()
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
               timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    body = r.json()
    token = body.get("token") or body.get("access_token")
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


# ===========================================================================
# 1. Backward-compat imports (símbolos extraídos para services/wa/*)
# ===========================================================================
class TestBackwardCompatImports:
    """Símbolos antes em routes.whatsapp_baileys devem continuar importáveis."""

    def test_sidecar_helpers_reexport(self):
        from routes.whatsapp_baileys import (
            SIDECAR_BASE, _sidecar_headers, _sidecar_get,
            _sidecar_post, _sidecar_post_silent,
        )
        assert isinstance(SIDECAR_BASE, str)
        assert SIDECAR_BASE.startswith("http")
        assert callable(_sidecar_headers)
        assert callable(_sidecar_get)
        assert callable(_sidecar_post)
        assert callable(_sidecar_post_silent)

    def test_split_ai_reply_reexport(self):
        from routes.whatsapp_baileys import _split_ai_reply
        assert callable(_split_ai_reply)
        # quick functional sanity
        out = _split_ai_reply("primeiro paragrafo\n\nsegundo paragrafo bem maior aqui")
        assert isinstance(out, list)
        assert len(out) == 2

    def test_split_ai_reply_quoted_bubbles(self):
        from routes.whatsapp_baileys import _split_ai_reply
        # Padrão "bolhas-aspas Isabella": cada linha é uma bolha
        txt = '"Olá, tudo bem?"\n""\n"Posso te ajudar com planos?"\n""\n"Qual o seu CEP?"'
        out = _split_ai_reply(txt)
        assert isinstance(out, list)
        assert "tudo bem" in out[0]
        assert "CEP" in out[-1]

    def test_is_sales_completion_reexport(self):
        from routes.whatsapp_baileys import _is_sales_completion
        assert callable(_is_sales_completion)
        # padrão claro de conclusão
        assert _is_sales_completion(
            "contratação foi concluída pela equipe"
        ) is True
        # frase casual no meio da conversa
        assert _is_sales_completion("obrigada pela mensagem") is False
        # texto curto
        assert _is_sales_completion("ok") is False

    def test_fetch_human_few_shots_reexport(self):
        from routes.whatsapp_baileys import _fetch_human_few_shots
        assert callable(_fetch_human_few_shots)

    def test_persist_ai_failure_reexport(self):
        from routes.whatsapp_baileys import _persist_ai_failure
        assert callable(_persist_ai_failure)

    def test_maybe_auto_reply_still_present(self):
        from routes.whatsapp_baileys import _maybe_auto_reply
        assert callable(_maybe_auto_reply)

    def test_services_wa_direct_imports(self):
        # Novo caminho canônico
        from services.wa.sidecar import (
            SIDECAR_BASE, _sidecar_post, _sidecar_post_silent
        )
        from services.wa.text_utils import _split_ai_reply
        from services.wa.sales_detection import (
            is_sales_completion, _SALES_DONE_PATTERNS, _SALES_DONE_RE
        )
        from services.wa.ai_helpers import (
            fetch_human_few_shots, persist_ai_failure
        )
        assert SIDECAR_BASE.startswith("http")
        assert callable(_sidecar_post)
        assert callable(_split_ai_reply)
        assert callable(is_sales_completion)
        assert len(_SALES_DONE_PATTERNS) >= 5
        assert _SALES_DONE_RE.search("contratação foi concluída")
        assert callable(fetch_human_few_shots)
        assert callable(persist_ai_failure)

    def test_old_alias_matches_new(self):
        # Os aliases legados devem apontar para a mesma callable
        from routes.whatsapp_baileys import (
            _is_sales_completion, _fetch_human_few_shots, _persist_ai_failure,
        )
        from services.wa.sales_detection import is_sales_completion
        from services.wa.ai_helpers import (
            fetch_human_few_shots, persist_ai_failure
        )
        assert _is_sales_completion is is_sales_completion
        assert _fetch_human_few_shots is fetch_human_few_shots
        assert _persist_ai_failure is persist_ai_failure


# ===========================================================================
# 2. WhatsApp Baileys endpoints
# ===========================================================================
class TestWhatsAppBaileysEndpoints:

    def test_ai_health(self, session):
        r = session.get(f"{BASE_URL}/api/whatsapp-baileys/ai-health",
                          timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        # campos esperados (saúde)
        assert isinstance(body, dict)

    def test_auto_reply_get(self, session):
        r = session.get(f"{BASE_URL}/api/whatsapp-baileys/auto-reply",
                          timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "enabled" in body or "auto_reply" in body \
                or "ai_enabled" in body

    def test_auto_reply_put_toggle(self, session):
        # Lê estado atual
        r = session.get(f"{BASE_URL}/api/whatsapp-baileys/auto-reply",
                          timeout=20)
        assert r.status_code == 200
        cur = r.json()
        cur_val = cur.get("enabled")
        if cur_val is None:
            cur_val = cur.get("ai_enabled")
        if cur_val is None:
            cur_val = cur.get("auto_reply")
        # Tenta inverter
        new_val = not bool(cur_val)
        r2 = session.put(
            f"{BASE_URL}/api/whatsapp-baileys/auto-reply",
            json={"enabled": new_val}, timeout=20,
        )
        assert r2.status_code in (200, 204), r2.text
        # Restaura
        session.put(
            f"{BASE_URL}/api/whatsapp-baileys/auto-reply",
            json={"enabled": bool(cur_val)}, timeout=20,
        )

    def test_status(self, session):
        # Sidecar pode estar offline — endpoint não pode crashar
        r = session.get(f"{BASE_URL}/api/whatsapp-baileys/status",
                          timeout=20)
        # 200 (com state=down ok) ou 503 (sidecar inalcançável) são aceitáveis
        assert r.status_code in (200, 503), r.text

    def test_conversations(self, session):
        r = session.get(f"{BASE_URL}/api/whatsapp-baileys/conversations",
                          timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        # body pode ser lista ou dict com items
        assert isinstance(body, (list, dict))

    def test_qr_endpoint(self, session):
        # Sidecar pode estar offline; aceitar 200 ou 503
        r = session.get(f"{BASE_URL}/api/whatsapp-baileys/qr",
                          timeout=20)
        assert r.status_code in (200, 503), r.text


# ===========================================================================
# 3. AI Config + Cascata
# ===========================================================================
class TestAIConfigEndpoints:

    def test_ai_config_get(self, session):
        r = session.get(f"{BASE_URL}/api/ai-config", timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        # chain deve existir (cascata)
        assert isinstance(body, dict)
        # algum campo de chain deve estar presente
        keys = set(body.keys())
        assert any(k in keys for k in ("chain", "providers", "primary")), \
            f"ai-config faltando chain/providers/primary, got keys: {keys}"

    def test_ai_config_test_gemini(self, session):
        # Teste de provider gemini — não pode dar 5xx
        r = session.post(f"{BASE_URL}/api/ai-config/test/gemini",
                           json={}, timeout=60)
        # Aceita 200 (sucesso), 400/422 (sem chave configurada),
        # 401/403 (auth), mas não 5xx
        assert r.status_code < 500, r.text

    def test_ai_config_chain_put(self, session):
        # Primeiro lê
        r = session.get(f"{BASE_URL}/api/ai-config", timeout=20)
        assert r.status_code == 200
        body = r.json()
        chain = body.get("chain") or []
        if not chain:
            pytest.skip("chain vazia — endpoint PUT chain pode não validar")
        # Tenta enviar mesma chain (idempotente)
        r2 = session.put(f"{BASE_URL}/api/ai-config/chain",
                           json={"chain": chain}, timeout=20)
        # Aceita 200/204 — não pode dar 5xx
        assert r2.status_code < 500, r2.text


# ===========================================================================
# 4. Central IA dashboards
# ===========================================================================
class TestCentralIADashboards:

    def test_handoffs(self, session):
        r = session.get(
            f"{BASE_URL}/api/central-ia/dashboard/handoffs?days=7",
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body, dict)

    def test_sentiment(self, session):
        r = session.get(
            f"{BASE_URL}/api/central-ia/dashboard/sentiment?days=7",
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body, dict)


# ===========================================================================
# 5. Motor IA usage (cache fields)
# ===========================================================================
class TestMotorIAUsage:

    def test_usage_has_cache_fields(self, session):
        r = session.get(f"{BASE_URL}/api/motor-ia/usage?days=1",
                          timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body, dict)
        # Cache fields ficam dentro de `totals`
        totals = body.get("totals") or {}
        assert "cache_hit_rate_pct" in totals, \
            f"cache_hit_rate_pct ausente em totals; totals_keys={list(totals.keys())}"
        assert "cache_savings_usd" in totals, \
            f"cache_savings_usd ausente em totals; totals_keys={list(totals.keys())}"
        hit = totals["cache_hit_rate_pct"]
        sav = totals["cache_savings_usd"]
        assert hit is None or isinstance(hit, (int, float)), \
            f"cache_hit_rate_pct tipo errado: {type(hit)}"
        assert sav is None or isinstance(sav, (int, float)), \
            f"cache_savings_usd tipo errado: {type(sav)}"


# ===========================================================================
# 6. Routing — pick_agent_for_message integrity
# ===========================================================================
class TestRoutingIntegrity:

    def test_pick_agent_callable(self):
        from services.routing import pick_agent_for_message
        assert callable(pick_agent_for_message)

    def test_pick_agent_keyword_scoring(self):
        # Função interna _keyword_matches deve pontuar corretamente
        from services.routing import _keyword_matches
        # texto de vendas
        score_vendas = _keyword_matches(
            "qual o preço do plano de fibra de 500 mega?",
            "vendas:preço,plano,mega,fibra",
        )
        # texto de suporte
        score_suporte = _keyword_matches(
            "estou sem internet há 2 horas",
            "suporte:sem internet,lento,sinal",
        )
        # ambos devem somar pontos > 0
        assert score_vendas > 0
        assert score_suporte > 0
