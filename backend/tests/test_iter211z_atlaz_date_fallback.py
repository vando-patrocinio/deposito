"""
test_iter211z_atlaz_date_fallback.py
=====================================
iter211z — Garante que bolhas Atlaz caem na DATA ORIGINAL do chamado, não
no dia da importação local.

Cenários:
  • Atlaz manda `visit_date` (agendamento)        → HORARIO no dia/hora certo
  • Atlaz manda só `data_criacao` (sem agend.)    → NORMAL mas scheduled_time
                                                     na data original
  • Atlaz manda só uma data sem hora              → ancora 09:00 local
  • Atlaz manda formato BR `dd/mm/yyyy hh:mm`     → parseia corretamente
  • Atlaz não manda nada                          → fallback (created_at local)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_iter211z")

from routes.atlaz import _resolve_schedule  # noqa: E402
from routes.lousa import _ticket_day_iso  # noqa: E402


def _utc_iso(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute,
                       tzinfo=timezone.utc).isoformat()


def test_visit_date_iso_format_horario():
    chamado = {"visit_date": "2026-05-11 15:00:00"}
    pri, pos, iso = _resolve_schedule(chamado, "America/Sao_Paulo")
    assert pri == "horario"
    assert pos > 0
    # 15:00 em São Paulo = 18:00 UTC
    assert iso.startswith("2026-05-11T18:00:00")


def test_visit_date_br_format_horario():
    chamado = {"visit_date": "11/05/2026 15:00"}
    pri, _pos, iso = _resolve_schedule(chamado)
    assert pri == "horario"
    assert iso.startswith("2026-05-11T18:00:00")


def test_data_criacao_fallback_when_no_visit_date():
    # Atlaz não mandou visit_date, mas mandou data_criacao
    chamado = {"data_criacao": "2026-04-20 10:30:00"}
    pri, pos, iso = _resolve_schedule(chamado)
    # Prioridade NORMAL (não é agendamento), mas a data deve aparecer
    # no scheduled_time pra que `_ticket_day_iso` use a data correta.
    assert pri == "normal"
    assert pos == 0
    assert iso is not None
    assert iso.startswith("2026-04-20")


def test_date_only_anchors_at_9am():
    chamado = {"data_criacao": "2026-04-20"}
    _pri, _pos, iso = _resolve_schedule(chamado, "America/Sao_Paulo")
    # 09:00 em São Paulo = 12:00 UTC
    assert iso is not None
    assert iso.startswith("2026-04-20T12:00:00")


def test_no_dates_at_all():
    chamado = {"id": "x", "tipo": "instalacao"}
    pri, pos, iso = _resolve_schedule(chamado)
    assert pri == "normal"
    assert pos == 0
    assert iso is None


def test_alternative_field_names():
    """data_abertura e criado_em devem funcionar como fallback."""
    pri1, _, iso1 = _resolve_schedule({"data_abertura": "2026-04-15 14:00:00"})
    assert iso1 is not None and iso1.startswith("2026-04-15")
    assert pri1 == "normal"
    pri2, _, iso2 = _resolve_schedule({"criado_em": "2026-04-16 14:00:00"})
    assert iso2 is not None and iso2.startswith("2026-04-16")
    assert pri2 == "normal"


def test_data_marcada_horario_priority():
    """data_marcada (agendamento alternativo) → HORARIO."""
    chamado = {"data_marcada": "2026-05-30 09:00:00"}
    pri, _pos, iso = _resolve_schedule(chamado)
    assert pri == "horario"
    assert iso is not None


def test_visit_date_wins_over_data_criacao():
    """visit_date tem prioridade sobre data_criacao."""
    chamado = {
        "visit_date": "2026-06-01 10:00:00",
        "data_criacao": "2026-05-15 08:00:00",
    }
    pri, _pos, iso = _resolve_schedule(chamado)
    assert pri == "horario"
    assert iso.startswith("2026-06-01")


def test_ticket_day_iso_prefers_atlaz_created_at_over_local_created_at():
    """_ticket_day_iso é o orquestrador no lousa.py. Mesmo sem
    scheduled_time/opened_at, atlaz_created_at deve ganhar do created_at
    local (que é o dia da importação)."""
    ticket = {
        "atlaz_created_at": "2026-04-20T13:00:00+00:00",  # Atlaz: 20/04
        "created_at": "2026-05-10T23:32:37+00:00",        # import: 10/05
    }
    # Sem scheduled_time e sem opened_at → tem que cair em 20/04 (Atlaz)
    # e não em 10/05 (import local).
    day = _ticket_day_iso(ticket)
    assert day == "2026-04-20"


def test_ticket_day_iso_scheduled_time_wins():
    """scheduled_time sempre vence quando presente."""
    ticket = {
        "scheduled_time": "2026-06-05T18:00:00+00:00",  # 15h SP → 18 UTC
        "atlaz_created_at": "2026-04-20T13:00:00+00:00",
        "created_at": "2026-05-10T23:32:37+00:00",
    }
    assert _ticket_day_iso(ticket) == "2026-06-05"
