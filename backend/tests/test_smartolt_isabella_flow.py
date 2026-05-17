"""Testes do fluxo de diagnóstico SmartOLT V6.70 (Isabella IA).

Valida a orquestração nova:
  - LOS  → cria bolha (TICKET_TRIGGER_STATUSES), NÃO rebooting
  - Offline → handoff humano via marker, sem ticket, sem reboot
  - Power Fail → mantém oferta de agendamento + ticket
  - Helpers de formatação produzem texto não-vazio

Esses testes são unitários — operam sobre dicts mockados e funções puras /
async com fakes do mongo. Não requerem a stack completa do FastAPI.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Garante que MONGO_URL aponta pra mongo local antes dos imports.
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_smartolt_flow")

from services import subscriber_connection as sc  # noqa: E402


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

def test_los_is_ticket_trigger():
    assert "los" in sc.TICKET_TRIGGER_STATUSES


def test_power_fail_is_ticket_trigger():
    assert "power fail" in sc.TICKET_TRIGGER_STATUSES


def test_offline_no_longer_creates_ticket_automatically():
    """Per 02/2026: Offline NÃO abre chamado — handoff humano."""
    assert "offline" not in sc.TICKET_TRIGGER_STATUSES


def test_reboot_first_statuses_is_empty():
    """Per 02/2026: nenhum status dispara reboot automático."""
    assert sc.REBOOT_FIRST_STATUSES == set()


# ---------------------------------------------------------------------------
# is_problem_intent
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "minha internet caiu",
    "ta sem sinal aqui",
    "tá lento demais",
    "não funciona o wi-fi",
    "luz vermelha no modem",
    "Defeito na conexão",
])
def test_is_problem_intent_detects(text):
    assert sc.is_problem_intent(text) is True


@pytest.mark.parametrize("text", [
    "bom dia",
    "quero contratar fibra",
    "qual o preço?",
    "",
    None,
])
def test_is_problem_intent_negative(text):
    assert sc.is_problem_intent(text or "") is False


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def test_format_for_prompt_online_mentions_action():
    info = {
        "found": True,
        "subscriber_name": "Cliente Teste",
        "plan_name": "Fibra 600",
        "branch": "Centro",
        "connected": True,
        "status": "Online",
        "signal_text": "Very good",
        "signal_1310": -23.5,
        "signal_1490": -22.0,
        "olt_name": "OLT-01",
        "port": "1/1/1",
        "minutes_since_change": 10,
        "onu_name": "ONU-Test",
        "onu_id": "abc123",
        "onu_sn": "ZTEG00112233",
        "onu_model": "F670L",
    }
    text = sc.format_for_prompt(info)
    assert "VERIFICAÇÃO DA CONEXÃO" in text
    assert "Cliente Teste" in text
    assert "ONLINE" in text or "Online" in text


def test_format_for_prompt_los_mentions_lousa_and_no_reset():
    info = {
        "found": True,
        "subscriber_name": "Joao Silva",
        "plan_name": "Fibra 600",
        "branch": "Centro",
        "connected": False,
        "status": "LOS",
        "signal_text": "—",
        "olt_name": "OLT-01",
        "port": "1/1/1",
        "minutes_since_change": 5,
        "onu_name": "ONU-Joao",
        "onu_id": "xyz789",
        "onu_sn": "ZTEG00998877",
        "onu_model": "F670L",
    }
    text = sc.format_for_prompt(info)
    assert "LOS" in text
    assert "Lousa" in text  # menção explícita à Lousa
    assert "NÃO peça reset" in text or "não resolve LOS" in text


def test_format_for_prompt_offline_mentions_transfer():
    info = {
        "found": True,
        "subscriber_name": "Maria",
        "plan_name": "Fibra 300",
        "branch": "Centro",
        "connected": False,
        "status": "Offline",
        "signal_text": "—",
        "olt_name": "OLT-02",
        "port": "1/2/3",
        "minutes_since_change": 30,
    }
    text = sc.format_for_prompt(info)
    assert "Offline" in text or "OFFLINE" in text
    assert "TRANSFERIR" in text or "Atendimento Especializado" in text


def test_format_offline_transfer_prompt_block():
    text = sc.format_offline_transfer_for_prompt()
    assert "Atendimento Especializado" in text
    assert "transferir" in text.lower()
    # frase exata exigida pelo gatilho de handoff (normaliza whitespace)
    normalized = " ".join(text.split())
    assert "transferir você agora pro nosso Atendimento Especializado" in normalized


# ---------------------------------------------------------------------------
# Marker de handoff Offline
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("reply", [
    "Verifiquei. Vou transferir você agora pro nosso Atendimento Especializado, em instantes alguém te chama.",
    "vou transferir voce pro atendimento especializado",
    "Vou transferir pra o Atendimento Especializado",
])
def test_is_offline_handoff_message_positive(reply):
    assert sc.is_offline_handoff_message(reply) is True


@pytest.mark.parametrize("reply", [
    "Vou abrir um chamado pra você",
    "Aguarde 2 minutos e tente novamente",
    "Posso ajudar em mais alguma coisa?",
    "",
])
def test_is_offline_handoff_message_negative(reply):
    assert sc.is_offline_handoff_message(reply) is False


# ---------------------------------------------------------------------------
# ensure_repair_ticket — comportamento de filtro por status
# ---------------------------------------------------------------------------

def test_ensure_repair_ticket_skips_offline():
    """Offline NÃO deve gerar ticket — handoff humano cobre o caso."""
    info = {
        "found": True,
        "subscriber_name": "X",
        "status": "Offline",
        "onu_id": "id1",
    }
    # Como TICKET_TRIGGER_STATUSES exclui 'offline', função retorna None
    # ANTES de tocar no banco. Logo, não precisa de mongo aqui.
    result = asyncio.run(sc.ensure_repair_ticket("co-demo", info, "5551999999", "caiu"))
    assert result is None


def test_ensure_repair_ticket_skips_when_not_found():
    info = {"found": False, "reason": "telefone não vinculado"}
    result = asyncio.run(sc.ensure_repair_ticket("co-demo", info, "5551999999", "caiu"))
    assert result is None
