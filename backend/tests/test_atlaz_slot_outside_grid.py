"""Regressão CTO 12/06/2026 — Regra de negócio do gestor para
encaixe de OSs do Atlaz na grade da Lousa.

REGRA:
  • cutoff_hour (default 17h): Atlaz visit_date >= 17h → pula pro
    PRÓXIMO DIA ÚTIL, primeiro slot LIVRE da grade.
  • Dia útil = SEG-SÁB (DOMINGO pula).
  • Atlaz visit_date < 17h → encaixa no MESMO dia (slot ≥ grid_start,
    avançando até achar vaga).
  • Dia todo lotado → próximo dia útil, 1º slot livre.

Caso real reproduzido:
  • Atlaz cria #6542237 às 18:58 BRT sex 12/06/2026.
  • Comportamento ANTES (bug iter211aa): pulava pra 15/06 seg 18:00.
  • Comportamento DEPOIS (regra do gestor): vai pra 13/06 sáb 09:00.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

load_dotenv("/app/backend/.env")

TZ_BR = ZoneInfo("America/Sao_Paulo")


async def _setup_company(grid_start=9, grid_end=18, cutoff=17, max_per_slot=2):
    from database import db
    cid = f"co-test-{uuid.uuid4().hex[:8]}"
    await db.settings.insert_one({
        "id": cid,
        "lousa_grid_start_hour": grid_start,
        "lousa_grid_end_hour": grid_end,
        "lousa_grid_slot_minutes": 60,
        "lousa_grid_max_per_slot": max_per_slot,
        "lousa_atlaz_cutoff_hour": cutoff,
    })
    return cid


async def _cleanup(cid: str):
    from database import db
    await db.settings.delete_one({"id": cid})
    await db.tickets.delete_many({"company_id": cid})


@pytest.mark.asyncio
async def test_after_cutoff_pushes_to_next_business_day_first_slot():
    """Atlaz 12/06 sex 18:58 → vai pra 13/06 sáb 09:00 BRT (1º slot livre)."""
    from routes.atlaz import _next_available_slot
    cid = await _setup_company()
    tech = f"col-{uuid.uuid4().hex[:8]}"
    try:
        # Sex 12/06 às 18:58 BRT = 21:58 UTC
        target = "2026-06-12T21:58:00+00:00"
        result = await _next_available_slot(cid, tech, target)
        dt = datetime.fromisoformat(result.replace("Z", "+00:00")).astimezone(TZ_BR)
        assert dt.date() == datetime(2026, 6, 13).date(), f"Esperado 13/06, recebeu {dt}"
        assert dt.hour == 9 and dt.minute == 0, f"Esperado 09:00 BRT, recebeu {dt.hour:02d}:{dt.minute:02d}"
    finally:
        await _cleanup(cid)


@pytest.mark.asyncio
async def test_after_cutoff_saturday_pushes_to_monday_skipping_sunday():
    """Atlaz 13/06 sáb 18:00 → pula domingo → 15/06 seg 09:00 BRT."""
    from routes.atlaz import _next_available_slot
    cid = await _setup_company()
    tech = f"col-{uuid.uuid4().hex[:8]}"
    try:
        # Sáb 13/06 às 18:00 BRT = 21:00 UTC (depois do cutoff)
        target = "2026-06-13T21:00:00+00:00"
        result = await _next_available_slot(cid, tech, target)
        dt = datetime.fromisoformat(result.replace("Z", "+00:00")).astimezone(TZ_BR)
        # Domingo (14/06) deve ser pulado
        assert dt.date() == datetime(2026, 6, 15).date(), f"Esperado 15/06 (seg), recebeu {dt}"
        assert dt.hour == 9 and dt.minute == 0, f"Esperado 09:00 BRT, recebeu {dt.hour:02d}:{dt.minute:02d}"
    finally:
        await _cleanup(cid)


@pytest.mark.asyncio
async def test_before_cutoff_same_day_first_free_slot():
    """Atlaz 12/06 sex 14:30 → mesmo dia 14:00 BRT (1º slot livre desde target)."""
    from routes.atlaz import _next_available_slot
    cid = await _setup_company()
    tech = f"col-{uuid.uuid4().hex[:8]}"
    try:
        # Sex 12/06 às 14:30 BRT = 17:30 UTC (antes do cutoff 17h)
        target = "2026-06-12T17:30:00+00:00"
        result = await _next_available_slot(cid, tech, target)
        dt = datetime.fromisoformat(result.replace("Z", "+00:00")).astimezone(TZ_BR)
        assert dt.date() == datetime(2026, 6, 12).date(), f"Esperado mesmo dia 12/06, recebeu {dt}"
        assert dt.hour == 14, f"Esperado 14:00 BRT, recebeu {dt.hour:02d}"
    finally:
        await _cleanup(cid)


@pytest.mark.asyncio
async def test_before_grid_start_normalizes_to_grid_start_same_day():
    """Atlaz 12/06 sex 07:00 (antes da grade 9-18) → mesmo dia 09:00 BRT."""
    from routes.atlaz import _next_available_slot
    cid = await _setup_company()
    tech = f"col-{uuid.uuid4().hex[:8]}"
    try:
        # Sex 12/06 às 07:00 BRT = 10:00 UTC
        target = "2026-06-12T10:00:00+00:00"
        result = await _next_available_slot(cid, tech, target)
        dt = datetime.fromisoformat(result.replace("Z", "+00:00")).astimezone(TZ_BR)
        assert dt.date() == datetime(2026, 6, 12).date()
        assert dt.hour == 9
    finally:
        await _cleanup(cid)


@pytest.mark.asyncio
async def test_exact_cutoff_17h_pushes_next_day():
    """17:00 EXATO conta como 'após cutoff' (>=) → próximo dia útil."""
    from routes.atlaz import _next_available_slot
    cid = await _setup_company()
    tech = f"col-{uuid.uuid4().hex[:8]}"
    try:
        # Sex 12/06 às 17:00 BRT = 20:00 UTC
        target = "2026-06-12T20:00:00+00:00"
        result = await _next_available_slot(cid, tech, target)
        dt = datetime.fromisoformat(result.replace("Z", "+00:00")).astimezone(TZ_BR)
        assert dt.date() == datetime(2026, 6, 13).date(), f"Esperado 13/06 sáb, recebeu {dt}"
        assert dt.hour == 9
    finally:
        await _cleanup(cid)


@pytest.mark.asyncio
async def test_no_technician_returns_original_iso():
    """Sem técnico (inbox) → não compete por slot, retorna ISO original."""
    from routes.atlaz import _next_available_slot
    cid = await _setup_company()
    try:
        target = "2026-06-12T21:58:00+00:00"
        result = await _next_available_slot(cid, None, target)
        assert result == target
    finally:
        await _cleanup(cid)


if __name__ == "__main__":
    async def _all():
        await test_after_cutoff_pushes_to_next_business_day_first_slot()
        await test_after_cutoff_saturday_pushes_to_monday_skipping_sunday()
        await test_before_cutoff_same_day_first_free_slot()
        await test_before_grid_start_normalizes_to_grid_start_same_day()
        await test_exact_cutoff_17h_pushes_next_day()
        await test_no_technician_returns_original_iso()
    asyncio.run(_all())
    print("OK — todos os 6 cenários passaram")
