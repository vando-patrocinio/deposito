"""BACKFILL ISABELLA — fecha o gap entre outbounds enviados e ai_evaluations.

Para cada outbound twilio do co-demo sem ai_evaluation, executa
register_followup usando o turn correspondente (inbound mais recente
ANTES do outbound).

Idempotente: pula outbounds que já têm evaluation associada.
"""
from __future__ import annotations
import asyncio
import sys
import time

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")

from database import db  # noqa: E402
from services.isabella_ceo_followup import register_followup  # noqa: E402


CID = "co-demo"


async def main():
    t0 = time.time()
    # Lista outbounds twilio em ordem cronológica
    outs = await db.aihub_wa_messages.find(
        {"company_id": CID, "channel": "twilio", "direction": "outbound",
         "auto_reply": True},
        {"_id": 0, "id": 1, "phone": 1, "text": 1, "created_at": 1,
         "subscriber_id": 1}
    ).sort("created_at", 1).to_list(20000)

    print(f"[backfill] {len(outs)} outbounds twilio para processar")

    processed = 0
    skipped = 0
    errors = 0
    # Idempotência por outbound_id: marcador em ai_evaluations.evidence
    already = set()
    async for r in db.ai_evaluations.find(
            {"company_id": CID, "backfill_outbound_id": {"$exists": True}},
            {"_id": 0, "backfill_outbound_id": 1}):
        already.add(r["backfill_outbound_id"])
    print(f"[backfill] {len(already)} já marcadas como backfill")

    for o in outs:
        phone = o.get("phone")
        if not phone:
            continue
        if o["id"] in already:
            skipped += 1
            continue
        # Busca inbound imediatamente anterior do mesmo phone
        prev = await db.aihub_wa_messages.find_one(
            {"company_id": CID, "phone": phone, "direction": "inbound",
             "created_at": {"$lte": o["created_at"]}},
            {"_id": 0, "text": 1},
            sort=[("created_at", -1)])
        user_text = (prev or {}).get("text", "") if prev else ""
        try:
            doc = await register_followup(
                company_id=CID,
                subscriber_id=o.get("subscriber_id"),
                phone=phone, user_text=user_text or "",
                isabella_reply=o.get("text", "") or "",
                context_used="backfill")
            # Marca outbound_id para idempotência futura
            await db.ai_evaluations.update_one(
                {"id": doc["id"]},
                {"$set": {"backfill_outbound_id": o["id"]}})
            processed += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"[backfill] error phone={phone}: {e}")
        if processed % 1000 == 0 and processed:
            print(f"[backfill] progress: processed={processed} skipped={skipped} errors={errors}")

    elapsed = time.time() - t0
    total_eval_after = await db.ai_evaluations.count_documents(
        {"company_id": CID})
    eval_with_outcome = await db.ai_evaluations.count_documents(
        {"company_id": CID, "outcome": {"$exists": True}})
    print(f"\n[backfill] DONE em {elapsed:.1f}s")
    print(f"  processed={processed} skipped={skipped} errors={errors}")
    print(f"  ai_evaluations total agora: {total_eval_after}")
    print(f"  com outcome: {eval_with_outcome}")


if __name__ == "__main__":
    asyncio.run(main())
