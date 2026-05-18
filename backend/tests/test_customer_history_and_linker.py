"""Testes UNITÁRIOS do customer_history e subscriber_phone_linker.

Apenas testes puros (sem acesso a Motor/DB) — os testes de integração com
DB foram movidos pra `test_customer_history_integration.py` que usa o
endpoint REST via requests pra evitar problemas de event loop com Motor.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

from services.customer_history import format_history_for_prompt  # noqa: E402
from services.subscriber_phone_linker import extract_identifiers  # noqa: E402


# ---------------------------------------------------------------------------
# format_history_for_prompt (puro)
# ---------------------------------------------------------------------------

def test_format_history_returns_empty_when_not_found():
    assert format_history_for_prompt({"found": False}) == ""


def test_format_history_returns_empty_when_none():
    assert format_history_for_prompt(None) == ""
    assert format_history_for_prompt({}) == ""


def test_format_history_includes_classification_badge_persistente():
    analysis = {
        "found": True,
        "classification": "persistente",
        "summary": "Vando teve 3 chamados.",
    }
    text = format_history_for_prompt(analysis)
    assert "HISTÓRICO DO CLIENTE" in text
    assert "PERSISTENTE" in text
    assert "Vando teve 3 chamados." in text


def test_format_history_includes_recorrente():
    analysis = {"found": True, "classification": "recorrente", "summary": "x"}
    text = format_history_for_prompt(analysis)
    assert "RECORRENTE" in text


def test_format_history_includes_esporadico():
    analysis = {"found": True, "classification": "esporádico", "summary": "x"}
    text = format_history_for_prompt(analysis)
    assert "ESPORÁDICO" in text


def test_format_history_includes_eventual():
    analysis = {"found": True, "classification": "eventual", "summary": "x"}
    text = format_history_for_prompt(analysis)
    assert "EVENTUAL" in text


# ---------------------------------------------------------------------------
# extract_identifiers (puro)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected_cpf", [
    ("meu cpf é 035.123.456-78", "03512345678"),
    ("CPF 03512345678", "03512345678"),
    ("documento: 999.888.777-66", "99988877766"),
    ("oi tudo bem?", None),
    ("", None),
])
def test_extract_cpf(text, expected_cpf):
    r = extract_identifiers(text)
    assert r["cpf"] == expected_cpf


@pytest.mark.parametrize("text,expected_cnpj", [
    ("CNPJ 39.061.296/0001-96", "39061296000196"),
    ("nosso cnpj 39061296000196", "39061296000196"),
    ("12.345.678/0001-90 esse é", "12345678000190"),
])
def test_extract_cnpj(text, expected_cnpj):
    r = extract_identifiers(text)
    assert r["cnpj"] == expected_cnpj


def test_extract_name_full():
    r = extract_identifiers(
        "Meu nome é Vando Patrocinio Silva e estou sem net"
    )
    assert r["name"] is not None
    assert "Vando" in r["name"]


def test_extract_empty():
    r = extract_identifiers("")
    assert r["cpf"] is None
    assert r["cnpj"] is None
    assert r["name"] is None


def test_extract_short_name_not_matched():
    """Apenas 1 ou 2 palavras não conta como nome completo."""
    r = extract_identifiers("oi sou Vando")
    assert r["name"] is None


def test_extract_invalid_cpf_length():
    """CPF com 10 dígitos é rejeitado."""
    r = extract_identifiers("documento 1234567890")
    assert r["cpf"] is None
