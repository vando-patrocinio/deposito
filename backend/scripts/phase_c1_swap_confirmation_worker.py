"""Phase C.1 — Swap Confirmation Worker

CEO 19/06/2026:
- Confirma os 95 swap_events `pending_confirmation`/`sent_to_technician`
- Backfill (Onda 2): auto-confirma como `confirmed_via_legacy_audit`
  (foram reconstruídos a partir de stok_history real, já confiáveis)
- Orgânicos pós-Onda 3: marca como `sent_to_technician` para follow-up
  WhatsApp (não automatiza envio — apenas registra a fila)

Zero delete. Audit log SHA-256 em `swap_confirmation_runs`.
"""
import asyncio
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")


def _backfill_filter():
    """Identifica swaps que vieram do backfill Onda 2."""
    return {
        "$or": [
            {"created_by": {"$regex": "backfill|onda2", "$options": "i"}},
            {"source": {"$regex": "backfill|onda2", "$options": "i"}},
        ]
    }


async def run(company_id: str = "co-demo", dry_run: bool = False):
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    now = datetime.now(timezone.utc).isoformat()
    run_id = f"swcr-{uuid.uuid4().hex[:8]}"

    # 1) Backfill auto-confirm
    bf_q = {
        "company_id": company_id,
        "confirmation_status": {
            "$in": ["pending_confirmation", "sent_to_technician"],
        },
        **_backfill_filter(),
    }
    cur = db.auto_ont_swap_events.find(bf_q, {"_id": 0, "id": 1})
    bf_ids = [d["id"] for d in await cur.to_list(length=None)]
    bf_count = len(bf_ids)

    if not dry_run and bf_count > 0:
        await db.auto_ont_swap_events.update_many(
            {"id": {"$in": bf_ids}},
            {"$set": {
                "confirmation_status": "confirmed_via_legacy_audit",
                "confirmed_at": now,
                "confirmed_by": "phase_c1_worker",
                "confirmation_reason": (
                    "Swap reconstruído a partir de stok_history existente "
                    "pela Onda 2; confirmado em massa pela auditoria "
                    "Phase C.1 (CEO 19/06/2026)."
                ),
                "phase_c1_run_id": run_id,
            }},
        )

    # 2) Organic pending: send to WhatsApp queue
    org_q = {
        "company_id": company_id,
        "confirmation_status": {
            "$in": ["pending_confirmation", "sent_to_technician"],
        },
        "$nor": [_backfill_filter()],
    }
    cur = db.auto_ont_swap_events.find(org_q, {"_id": 0, "id": 1,
        "subscriber_id": 1, "ticket_id": 1, "old_sn": 1, "new_sn": 1})
    org_docs = await cur.to_list(length=None)
    org_count = len(org_docs)

    org_queue_ids = []
    if not dry_run:
        for sw in org_docs:
            qid = f"swcq-{uuid.uuid4().hex[:10]}"
            await db.swap_confirmation_queue.insert_one({
                "id": qid,
                "company_id": company_id,
                "swap_event_id": sw["id"],
                "ticket_id": sw.get("ticket_id"),
                "subscriber_id": sw.get("subscriber_id"),
                "old_sn": sw.get("old_sn"),
                "new_sn": sw.get("new_sn"),
                "status": "queued_for_whatsapp",
                "phase_c1_run_id": run_id,
                "created_at": now,
            })
            org_queue_ids.append(qid)
            await db.auto_ont_swap_events.update_one(
                {"id": sw["id"]},
                {"$set": {
                    "confirmation_status": "sent_to_technician",
                    "sent_to_technician_at": now,
                    "whatsapp_queue_id": qid,
                    "phase_c1_run_id": run_id,
                }},
            )

    # 3) Audit log SHA-256
    summary = {
        "run_id": run_id,
        "company_id": company_id,
        "executed_at": now,
        "executed_by": "phase_c1_swap_confirmation_worker",
        "dry_run": dry_run,
        "backfill_auto_confirmed": bf_count,
        "organic_queued_for_whatsapp": org_count,
        "organic_queue_ids": org_queue_ids,
        "ceo_authorization": "Phase C.1 — 19/06/2026",
    }
    summary["hash_sha256"] = hashlib.sha256(
        json.dumps(summary, sort_keys=True, default=str).encode()
    ).hexdigest()
    if not dry_run:
        await db.swap_confirmation_runs.insert_one(dict(summary))

    # 4) Final state
    still_pending = await db.auto_ont_swap_events.count_documents({
        "company_id": company_id,
        "confirmation_status": {
            "$in": ["pending_confirmation"],
        },
    })

    print("=" * 64)
    print("PHASE C.1 — SWAP CONFIRMATION WORKER")
    print("=" * 64)
    print(f"run_id={run_id}  dry_run={dry_run}")
    print(f"  Backfill auto-confirmed:       {bf_count}")
    print(f"  Organic queued for WhatsApp:   {org_count}")
    print(f"  Still pending_confirmation:    {still_pending}")
    print(f"  hash_sha256: {summary['hash_sha256']}")
    print("=" * 64)
    return summary


if __name__ == "__main__":
    import sys
    dry = "--dry" in sys.argv
    asyncio.run(run(dry_run=dry))
