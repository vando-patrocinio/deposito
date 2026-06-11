"""
backfill_sala_orphans.py — CTO P0 11/06/2026

Backfill: tickets abertos em `tickets` sem `assigned_collaborator_id`
recebem o `col-sala-<tenant>` correspondente. Marca:
  - `system_generated = True`
  - `sala_route_reason = 'backfill_orphan'`
  - `sala_routed_at = ISO timestamp`
  - `backfilled_orphan_at = ISO timestamp` (auditoria)

Idempotente: pula tickets que já têm assigned.
"""
import asyncio
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")

from database import db
from services.isabella_actions import _ensure_sala


async def main():
    now = datetime.now(timezone.utc).isoformat()
    q = {
        "$or": [
            {"assigned_collaborator_id": None},
            {"assigned_collaborator_id": {"$exists": False}},
            {"assigned_collaborator_id": ""},
        ],
        "status": {"$ne": "closed"},
    }
    total = await db.tickets.count_documents(q)
    print(f"Tickets órfãos abertos: {total}")
    if total == 0:
        print("Nada a fazer.")
        return

    # Resolve sala por tenant (1 lookup por cid distinto)
    cids = await db.tickets.distinct("company_id", q)
    print(f"Tenants envolvidos: {cids}")
    sala_by_cid = {}
    for cid in cids:
        if cid:
            sala_by_cid[cid] = await _ensure_sala(cid)
    print(f"SALAs resolvidas: {sala_by_cid}")

    fixed = defaultdict(int)
    skipped_no_cid = 0
    async for t in db.tickets.find(q, {"_id": 0, "id": 1, "company_id": 1}):
        cid = t.get("company_id")
        if not cid:
            skipped_no_cid += 1
            continue
        sala_id = sala_by_cid.get(cid)
        if not sala_id:
            continue
        await db.tickets.update_one(
            {"id": t["id"]},
            {"$set": {
                "assigned_collaborator_id": sala_id,
                "system_generated": True,
                "sala_route_reason": "backfill_orphan",
                "sala_routed_at": now,
                "backfilled_orphan_at": now,
            }},
        )
        fixed[cid] += 1

    print("\n=== Resultado ===")
    for cid, n in fixed.items():
        print(f"  {cid}: {n} tickets movidos para {sala_by_cid[cid]}")
    print(f"  Pulados (sem company_id): {skipped_no_cid}")
    print(f"  TOTAL: {sum(fixed.values())}")


if __name__ == "__main__":
    asyncio.run(main())
