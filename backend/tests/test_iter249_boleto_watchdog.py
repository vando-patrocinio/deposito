"""Iter249 — Auditoria CEO: boleto_flow (PIX/juros) + WA Sidecar Watchdog.

Cobre:
  - GET  /api/whatsapp-baileys/sidecar-watchdog/status (gestor)
  - POST /api/whatsapp-baileys/sidecar-watchdog/tick   (gestor)
  - 401/403 sem auth
  - boleto_flow.format_invoices_message (mock fatura PIX+juros)
  - boleto_flow.format_invoices_message (lista vazia)
  - bubble_splitter.split_into_bubbles (aspas removidas/separador)
  - boleto_flow.detect_boleto_intent (positivo/negativo)

Test target: backend remoto via REACT_APP_BACKEND_URL.
Funções puras importadas direto de /app/backend.
"""
from __future__ import annotations

import os
import sys
import pytest
import requests

# Importa módulos do backend pra testes unitários
sys.path.insert(0, "/app/backend")

def _load_base_url() -> str:
    env = os.environ.get("REACT_APP_BACKEND_URL")
    if env:
        return env.rstrip("/")
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.strip().startswith("REACT_APP_BACKEND_URL="):
                    return line.strip().split("=", 1)[1].rstrip("/")
    except FileNotFoundError:
        pass
    raise RuntimeError("REACT_APP_BACKEND_URL not found")


BASE_URL = _load_base_url()
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def auth_token(api):
    """Login como admin/gestor."""
    r = api.post(f"{BASE_URL}/api/auth/login",
                 json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
                 timeout=15)
    assert r.status_code == 200, f"Login falhou: {r.status_code} {r.text[:200]}"
    data = r.json()
    tok = data.get("token") or data.get("access_token")
    assert tok, f"Token ausente em {data}"
    return tok


@pytest.fixture(scope="session")
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json"}


# ── 1. Watchdog endpoints ────────────────────────────────────


class TestWatchdogEndpoints:
    """WA Sidecar Watchdog (CH1..CH4 monitoring + auto-retry)."""

    def test_status_with_auth(self, api, auth_headers):
        r = api.get(f"{BASE_URL}/api/whatsapp-baileys/sidecar-watchdog/status",
                    headers=auth_headers, timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        data = r.json()
        assert data.get("ok") is True
        assert "sidecars" in data
        assert "configured" in data
        assert isinstance(data["sidecars"], list)
        assert isinstance(data["configured"], list)
        assert "interval_s" in data
        assert "retry_window_h" in data
        assert "max_retry_per_tick" in data
        # CH1..CH4 devem estar configurados
        ids = [s.get("id") for s in data["configured"]]
        assert any(("CH1" in str(i) or "ch1" in str(i).lower())
                   for i in ids), f"CH1 não encontrado em {ids}"

    def test_status_without_auth(self, api):
        r = api.get(f"{BASE_URL}/api/whatsapp-baileys/sidecar-watchdog/status",
                    timeout=15)
        assert r.status_code in (401, 403), \
            f"Esperado 401/403, obteve {r.status_code}"

    def test_tick_with_auth(self, api, auth_headers):
        r = api.post(f"{BASE_URL}/api/whatsapp-baileys/sidecar-watchdog/tick",
                     headers=auth_headers, json={}, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        data = r.json()
        assert data.get("ok") is True
        assert "sidecars" in data
        # Cada sidecar deve ter campos esperados pós-tick
        for s in data.get("sidecars", []):
            assert "sidecar" in s or "url" in s

    def test_tick_without_auth(self, api):
        r = api.post(f"{BASE_URL}/api/whatsapp-baileys/sidecar-watchdog/tick",
                     json={}, timeout=15)
        assert r.status_code in (401, 403), \
            f"Esperado 401/403, obteve {r.status_code}"


# ── 2. bubble_splitter ───────────────────────────────────────


class TestBubbleSplitter:
    """Quebras de bolha + remoção de aspas envolventes/separadoras."""

    def test_strip_surrounding_quotes(self):
        from services.bubble_splitter import split_into_bubbles
        bubbles = split_into_bubbles('"Tudo certo!"')
        assert len(bubbles) >= 1
        joined = " ".join(bubbles)
        assert '"' not in joined, f"Aspa não removida: {bubbles!r}"
        assert "Tudo certo" in joined

    def test_quotes_as_bubble_separator(self):
        from services.bubble_splitter import split_into_bubbles
        # LLM gera "Bolha1." "" "Bolha2." "" "Bolha3."
        inp = 'Bolha1." "" "Bolha2." "" "Bolha3.'
        bubbles = split_into_bubbles(inp)
        # Deve produzir 3 bolhas distintas, SEM aspas
        joined = " ".join(bubbles)
        assert '"' not in joined, f"Aspas residuais: {bubbles!r}"
        assert any("Bolha1" in b for b in bubbles)
        assert any("Bolha2" in b for b in bubbles)
        assert any("Bolha3" in b for b in bubbles)
        # Spec exige 3 bolhas separadas
        assert len(bubbles) == 3, f"Esperado 3 bolhas, obteve {len(bubbles)}: {bubbles!r}"

    def test_preserve_text_without_quotes(self):
        from services.bubble_splitter import split_into_bubbles
        bubbles = split_into_bubbles(
            "Olá! Como posso ajudar você hoje?")
        assert len(bubbles) >= 1
        joined = " ".join(bubbles)
        assert "Olá" in joined or "Ola" in joined
        assert "?" in joined


# ── 3. detect_boleto_intent ──────────────────────────────────


class TestDetectBoletoIntent:
    """Spec do CEO: precisa reconhecer 7 frases positivas e rejeitar 3."""

    @pytest.mark.parametrize("text", [
        "quero meu boleto",
        "segunda via",
        "pagar",
        "fatura",
        "pix",
        "linha digitável",
        "venceu",
    ])
    def test_positive_intent(self, text):
        from services.boleto_flow import detect_boleto_intent
        assert detect_boleto_intent(text) is True, f"FALSE NEG: {text!r}"

    @pytest.mark.parametrize("text", ["?", "oi", "tudo bem"])
    def test_negative_intent(self, text):
        from services.boleto_flow import detect_boleto_intent
        assert detect_boleto_intent(text) is False, f"FALSE POS: {text!r}"


# ── 4. format_invoices_message ───────────────────────────────


MOCK_INVOICE = {
    "external_id": "INV-1",
    "amount": 99.9,
    "amount_with_interest": 102.1,
    "fine_value": 2.0,
    "interest_value": 1.0,
    "pix_brcode": "00020126360014BR.GOV.BCB.PIX0114+5511999999990520400005303986540510."
                   "215802BR5915Ligo Fibra LTDA6009Sao Paulo62290525TX123456ABCDEFGHIJ630438DC",
    "boleto_url": "https://atlaz.example.com/boletos/INV-1.pdf",
    "barcode": "12345678901234567890123456789012345678901234567",  # 47 dígitos
    "due_date": "2026-01-05T00:00:00",  # vencido (CEO já passou)
    "description": "Mensalidade Janeiro",
    "status": "overdue",
}


class TestFormatInvoicesMessage:

    def test_full_fields(self):
        from services.boleto_flow import format_invoices_message
        msg = format_invoices_message(
            {"name": "Maria Silva"}, [MOCK_INVOICE])
        # PIX copia-e-cola presente
        assert MOCK_INVOICE["pix_brcode"] in msg, "PIX brcode ausente"
        assert "PIX copia-e-cola" in msg or "PIX" in msg
        # Valor original
        assert "R$ 99,90" in msg, f"Valor original ausente em: {msg[:500]}"
        # Valor atualizado + multa + juros
        assert "R$ 102,10" in msg, f"Valor atualizado ausente em: {msg[:500]}"
        assert "multa R$ 2.00" in msg, f"Multa ausente: {msg[:500]}"
        assert "juros R$ 1.00" in msg, f"Juros ausente: {msg[:500]}"
        # Linha digitável FEBRABAN: XXXXX.XXXXX XXXXX.XXXXXX ...
        assert "12345.67890" in msg, f"Linha digitável não formatada: {msg[:600]}"
        # Boleto URL
        assert MOCK_INVOICE["boleto_url"] in msg
        # Status emoji (vencido → 🔴)
        assert ("🔴" in msg or "🟡" in msg or "🟢" in msg), \
            "Nenhum emoji de status presente"

    def test_empty_list_friendly(self):
        from services.boleto_flow import format_invoices_message
        msg = format_invoices_message({"name": "Maria Silva"}, [])
        assert "em dia" in msg.lower() or "✅" in msg
        assert "Maria" in msg
