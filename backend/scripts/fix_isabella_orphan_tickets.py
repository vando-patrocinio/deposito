"""fix_isabella_orphan_tickets.py — Backfill.

Tickets criados pela Isabella ANTES da correção têm:
  - status='AGENDADO' (Lousa filtra apenas 'pendente'/'aberta'/'aguardando_atendimento')
  - sem assigned_collaborator_id  (Lousa filtra por collaborator)
  - sem client_snapshot  (frontend depende para mostrar bolha)
  - priority='media'  (deveria ser 'horario' para visita agendada)

Este script conserta TODOS os tickets `created_by=isabella` cujo status
seja 'AGENDADO'/'ABERTO' (estados não-Lousa), mantendo `id`/`short_id`
para auditoria.

Zero mocks. Roda direto contra MongoDB.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
    "notes": "Backfill one-shot.",
}

import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db
from services.isabella_actions import _pick_default_collaborator


BROKEN_STATES = ["AGENDADO", "ABERTO"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def fix_one(t: dict) -> dict:
    cid = t.get("company_id")
    phone = t.get("phone") or ""
    sub_name = t.get("subscriber_name") or "Cliente WhatsApp"
    motivo = t.get("description") or t.get("subject") or ""
    is_visit = t.get("scheduled_time") or t.get("scheduled_date")

    assigned = t.get("assigned_collaborator_id") \
        or await _pick_default_collaborator(cid)

    next_pos = 0
    if assigned:
        last = await db.tickets.find(
            {"assigned_collaborator_id": assigned,
             "status": {"$in": ["pendente", "aberta",
                                  "aguardando_atendimento"]}},
            {"_id": 0, "position": 1}).sort("position", -1).to_list(1)
        next_pos = ((last[0].get("position") or 0) + 1) if last else 0

    # scheduled_time canonical com timezone
    sched = t.get("scheduled_time")
    if sched and "+" not in sched and "Z" not in sched:
        sched = sched + "+00:00"

    update = {
        "status": "pendente",
        "priority": "horario" if is_visit else "normal",
        "type": "reparo",
        "client_id": t.get("subscriber_id")
                       or t.get("client_id") or "",
        "client_snapshot": {
            "name": sub_name,
            "address": "",
            "neighborhood": "",
            "phone": phone,
            "latitude": None, "longitude": None,
            "relato": motivo,
            "pppoe_user": "",
            "test_history": [],
        },
        "assigned_collaborator_id": assigned,
        "position": next_pos,
        "needs_assignment_review": assigned is None,
        "auto_created_by_isabella": True,
        "ai_triage_pending": True,
        "backfilled_at": _now_iso(),
        "backfilled_by": "fix_isabella_orphan_tickets",
    }
    if sched and sched != t.get("scheduled_time"):
        update["scheduled_time"] = sched

    await db.tickets.update_one({"id": t["id"]}, {"$set": update})
    return {"id": t["id"], "short_id": t.get("short_id"),
              "assigned_collaborator_id": assigned,
              "company_id": cid, "phone": phone}


async def main():
    cursor = db.tickets.find({
        "created_by": "isabella",
        "status": {"$in": BROKEN_STATES},
    })
    targets = [t async for t in cursor]
    print(f"Tickets órfãos da Isabella detectados: {len(targets)}")
    for t in targets:
        print(f"  • {t.get('short_id')}  status={t.get('status')}  "
              f"phone={t.get('phone')}  date={t.get('scheduled_date')}")

    if not targets:
        print("\nNada a corrigir.")
        return 0

    print()
    fixed = []
    for t in targets:
        r = await fix_one(t)
        print(f"  ✓ {r['short_id']} → assigned={r['assigned_collaborator_id']}")
        fixed.append(r)
    print(f"\n{len(fixed)} ticket(s) corrigido(s).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
