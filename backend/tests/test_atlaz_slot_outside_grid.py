"""Regressão CTO 12/06/2026 — Bug "OS TESTE sumiu da Lousa".

Quando o Atlaz manda uma OS com `visit_date` FORA da grid de horário da
empresa (ex.: 18:58 quando `lousa_grid_end_hour = 18`), o algoritmo
`_next_available_slot` DEVE respeitar o horário original em vez de
empurrar pra próximo dia útil silenciosamente.

Cenário real reproduzido:
  • Atlaz cria chamado #6542237 às 18:58 BRT (12/06/2026)
  • Antes do fix: bolha caía 3 dias depois (segunda 15/06 18:00 BRT)
  • Depois do fix: bolha respeita 18:00 BRT do MESMO DIA (12/06)
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")


@pytest.mark.asyncio
async def test_slot_outside_grid_respects_atlaz():
    from database import db
    from routes.atlaz import _next_available_slot

    company_id = f"co-test-{uuid.uuid4().hex[:8]}"
    tech_id = f"col-test-{uuid.uuid4().hex[:8]}"

    # Settings: grid 9-18, slots 60min, max 2 por slot
    await db.settings.insert_one({
        "id": company_id,
        "lousa_grid_start_hour": 9,
        "lousa_grid_end_hour": 18,
        "lousa_grid_slot_minutes": 60,
        "lousa_grid_max_per_slot": 2,
    })

    try:
        # Atlaz pediu 18:58 BRT = 21:58 UTC, fora da grid (>=18)
        target_iso = "2026-06-12T21:58:00+00:00"
        result = await _next_available_slot(
            company_id, tech_id, target_iso,
        )

        # Fix esperado: respeita slot 18:00 BRT (=21:00 UTC) do MESMO DIA
        # 12/06, NÃO empurra pro próximo dia útil 15/06.
        result_dt = datetime.fromisoformat(result.replace("Z", "+00:00"))
        assert result_dt.date() == datetime(2026, 6, 12, tzinfo=timezone.utc).date(), \
            f"Esperado dia 12/06 (mesmo dia), recebeu {result_dt}"
        # Hora local BRT esperada: 18:00
        from zoneinfo import ZoneInfo
        local = result_dt.astimezone(ZoneInfo("America/Sao_Paulo"))
        assert local.hour == 18, \
            f"Esperado 18:00 BRT, recebeu {local.hour:02d}:{local.minute:02d}"
    finally:
        await db.settings.delete_one({"id": company_id})
        await db.tickets.delete_many({"company_id": company_id})


@pytest.mark.asyncio
async def test_slot_before_grid_start_respects_atlaz():
    """Atlaz pedindo horário ANTES do grid_start também deve ser respeitado."""
    from database import db
    from routes.atlaz import _next_available_slot

    company_id = f"co-test-{uuid.uuid4().hex[:8]}"
    tech_id = f"col-test-{uuid.uuid4().hex[:8]}"

    await db.settings.insert_one({
        "id": company_id,
        "lousa_grid_start_hour": 9,
        "lousa_grid_end_hour": 18,
        "lousa_grid_slot_minutes": 60,
        "lousa_grid_max_per_slot": 2,
    })

    try:
        # Atlaz pede 07:30 BRT = 10:30 UTC, antes do grid_start (9)
        target_iso = "2026-06-12T10:30:00+00:00"
        result = await _next_available_slot(
            company_id, tech_id, target_iso,
        )
        result_dt = datetime.fromisoformat(result.replace("Z", "+00:00"))
        from zoneinfo import ZoneInfo
        local = result_dt.astimezone(ZoneInfo("America/Sao_Paulo"))
        # Deve respeitar 07:00 BRT do mesmo dia
        assert local.hour == 7, \
            f"Esperado 07:00 BRT (antes da grid), recebeu {local.hour:02d}"
        assert local.date() == datetime(2026, 6, 12).date()
    finally:
        await db.settings.delete_one({"id": company_id})


if __name__ == "__main__":
    asyncio.run(test_slot_outside_grid_respects_atlaz())
    asyncio.run(test_slot_before_grid_start_respects_atlaz())
    print("OK")
