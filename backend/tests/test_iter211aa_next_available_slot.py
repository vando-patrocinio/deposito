"""
test_iter211aa_next_available_slot.py
======================================
iter211aa — Distribui bolhas Atlaz pelos horários livres quando o slot pedido
está cheio (max_per_slot=2 default).
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_iter211aa")

from database import db  # noqa: E402
from routes.atlaz import _next_available_slot  # noqa: E402


@pytest.mark.asyncio
async def test_next_available_slot_full_flow():
    """Single async test (motor client global → loop reuse) cobrindo:
      1. Slot cheio empurra pro próximo (10:00)
      2. 10:00 ainda tem espaço → reusa
      3. Lota 10:00 → vai pra 11:00
      4. None technician → não distribui
      5. Dia inteiro lotado → rola pro próximo dia útil
    """
    company_id = f"co-test-{uuid.uuid4().hex[:6]}"
    tech_id = f"tech-{uuid.uuid4().hex[:6]}"
    tech_friday = f"tech-fri-{uuid.uuid4().hex[:6]}"
    await db.settings.update_one(
        {"id": company_id},
        {"$set": {"id": company_id,
                   "lousa_grid_max_per_slot": 2,
                   "lousa_grid_slot_minutes": 60,
                   "lousa_grid_start_hour": 8,
                   "lousa_grid_end_hour": 18}},
        upsert=True,
    )
    target = "2026-06-15T12:00:00+00:00"  # seg, 09h SP
    base_dt = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    created_ids = []
    try:
        # Lota 09:00 SP com 2 bolhas
        for _ in range(2):
            tid = f"tkt-{uuid.uuid4().hex[:8]}"
            await db.tickets.insert_one({
                "id": tid, "company_id": company_id,
                "assigned_collaborator_id": tech_id,
                "status": "pendente", "priority": "horario",
                "scheduled_time": base_dt.isoformat(),
                "atlaz_external_id": str(uuid.uuid4()),
                "created_at": base_dt.isoformat(),
            })
            created_ids.append(tid)
        # 1) 09:00 cheio → 10:00
        out = await _next_available_slot(company_id, tech_id, target)
        out_dt = datetime.fromisoformat(out.replace("Z", "+00:00"))
        assert out_dt == base_dt + timedelta(hours=1), f"Expected 10:00, got {out}"

        # 2) Adiciona 1 às 10:00 → ainda tem espaço (1/2)
        tid_a = f"tkt-{uuid.uuid4().hex[:8]}"
        await db.tickets.insert_one({
            "id": tid_a, "company_id": company_id,
            "assigned_collaborator_id": tech_id,
            "status": "pendente", "priority": "horario",
            "scheduled_time": (base_dt + timedelta(hours=1)).isoformat(),
            "atlaz_external_id": str(uuid.uuid4()),
            "created_at": base_dt.isoformat(),
        })
        created_ids.append(tid_a)
        out2 = await _next_available_slot(company_id, tech_id, target)
        out2_dt = datetime.fromisoformat(out2.replace("Z", "+00:00"))
        assert out2_dt == base_dt + timedelta(hours=1), out2

        # 3) Lota 10:00 também → 11:00
        tid_b = f"tkt-{uuid.uuid4().hex[:8]}"
        await db.tickets.insert_one({
            "id": tid_b, "company_id": company_id,
            "assigned_collaborator_id": tech_id,
            "status": "pendente", "priority": "horario",
            "scheduled_time": (base_dt + timedelta(hours=1)).isoformat(),
            "atlaz_external_id": str(uuid.uuid4()),
            "created_at": base_dt.isoformat(),
        })
        created_ids.append(tid_b)
        out3 = await _next_available_slot(company_id, tech_id, target)
        out3_dt = datetime.fromisoformat(out3.replace("Z", "+00:00"))
        assert out3_dt == base_dt + timedelta(hours=2), out3

        # 4) None technician → retorna original (não distribui pra inbox)
        out_inbox = await _next_available_slot(company_id, None, target)
        assert out_inbox == target

        # 5) Próximo dia útil: 2026-06-19 (sexta) cheio das 14h às 17h SP →
        # vai pra 2026-06-22 (segunda) 14h SP (17:00 UTC).
        fri_target = "2026-06-19T17:00:00+00:00"
        for h in (17, 18, 19, 20):  # 14h..17h SP
            for _ in range(2):
                tid = f"tkt-{uuid.uuid4().hex[:8]}"
                await db.tickets.insert_one({
                    "id": tid, "company_id": company_id,
                    "assigned_collaborator_id": tech_friday,
                    "status": "pendente", "priority": "horario",
                    "scheduled_time": f"2026-06-19T{h:02d}:00:00+00:00",
                    "atlaz_external_id": str(uuid.uuid4()),
                    "created_at": "2026-06-19T17:00:00+00:00",
                })
                created_ids.append(tid)
        out_friday = await _next_available_slot(company_id, tech_friday, fri_target)
        out_fri_dt = datetime.fromisoformat(out_friday.replace("Z", "+00:00"))
        assert out_fri_dt.strftime("%Y-%m-%d") == "2026-06-22"
        assert out_fri_dt.strftime("%H:%M") == "17:00"
    finally:
        for tid in created_ids:
            await db.tickets.delete_one({"id": tid})
        await db.settings.delete_one({"id": company_id})
