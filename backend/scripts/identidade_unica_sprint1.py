"""SPRINT 1 — Backfill subscribers.atlaz_external_id ← loyalty.external_id.

Escolhe o snapshot loyalty CANÔNICO por (company_id, document):
  status=Ativo mais recente > registration_date mais recente.

Aplica em todos os tenants reais (skip SYNTHETIC_TENANTS).
Idempotente. Reversível via --rollback.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
from database import db  # noqa: E402
from constants.synthetic_tenants import SYNTHETIC_TENANTS  # noqa: E402

TAG = "identidade_unica_sprint1"
BATCH = 1000


def _sort_key(d):
    return (1 if d.get("status") == "Ativo" else 0, d.get("registration_date") or "")


async def ensure_indexes():
    await db.subscribers.create_index(
        [("company_id", 1), ("atlaz_external_id", 1)],
        name="company_id_1_atlaz_external_id_1", background=True)
    await db.loyalty_imported_db.create_index(
        [("company_id", 1), ("external_id", 1)],
        name="company_id_1_external_id_1", background=True)


async def coverage(tag: str):
    real = {"company_id": {"$nin": SYNTHETIC_TENANTS},
            "status": {"$in": ["ACTIVE", "ATIVO", "active", "ativo"]},
            "excluded_from_kpi": {"$ne": True}}
    total = await db.subscribers.count_documents(real)
    with_ext = await db.subscribers.count_documents(
        {**real, "atlaz_external_id": {"$nin": ["", None]}})
    pct = (with_ext / total * 100) if total else 0
    print(f"[COVERAGE {tag}] total_real_active={total} · with_atlaz_external_id={with_ext} ({pct:.2f}%)")
    return total, with_ext


async def backfill():
    from pymongo import UpdateOne
    now = datetime.now(timezone.utc).isoformat()

    print("[STEP 1] Lendo loyalty (tenants reais)…")
    canonical: dict[tuple[str, str], dict] = {}
    cur = db.loyalty_imported_db.find(
        {"company_id": {"$nin": SYNTHETIC_TENANTS},
         "document": {"$nin": ["", None]},
         "external_id": {"$nin": ["", None]}},
        {"company_id": 1, "document": 1, "status": 1,
         "registration_date": 1, "external_id": 1})
    n = 0
    async for d in cur:
        n += 1
        k = (d["company_id"], d["document"])
        best = canonical.get(k)
        if best is None or _sort_key(d) > _sort_key(best):
            canonical[k] = d
    print(f"[STEP 1] {n} loyalty docs scanned · {len(canonical)} canônicos")

    print("[STEP 2] Backfill subscribers.atlaz_external_id…")
    stats = defaultdict(int)
    ops: list = []
    conflicts: list = []
    cur = db.subscribers.find(
        {"company_id": {"$nin": SYNTHETIC_TENANTS}},
        {"id": 1, "company_id": 1, "document": 1, "atlaz_external_id": 1,
         "excluded_from_kpi": 1, "status": 1})
    async for s in cur:
        sid = s.get("id")
        cid = s.get("company_id")
        doc = (s.get("document") or "").strip()
        already = (s.get("atlaz_external_id") or "").strip()
        if not doc:
            stats["skip_no_document"] += 1
            continue
        best = canonical.get((cid, doc))
        if not best:
            stats["no_atlaz_record"] += 1
            continue
        ext = best.get("external_id")
        if already and already != ext:
            conflicts.append({"subscriber_id": sid, "company_id": cid,
                              "document": doc, "current": already, "new": ext})
            stats["conflict_kept_current"] += 1
            continue
        if already == ext:
            stats["already_correct"] += 1
            continue
        ops.append(UpdateOne({"id": sid}, {"$set": {
            "atlaz_external_id": ext,
            "_atlaz_ext_link_at": now,
            "_atlaz_ext_link_by": TAG}}))
        stats["filled"] += 1
        if len(ops) >= BATCH:
            await db.subscribers.bulk_write(ops, ordered=False)
            ops.clear()
    if ops:
        await db.subscribers.bulk_write(ops, ordered=False)

    print(f"[STEP 2] STATS: {dict(stats)}")
    if conflicts:
        print(f"[CONFLICTS] {len(conflicts)} (mantido valor atual):")
        for c in conflicts[:5]:
            print(f"    {c}")
    return stats, conflicts


async def rollback():
    res = await db.subscribers.update_many(
        {"_atlaz_ext_link_by": TAG},
        {"$unset": {"atlaz_external_id": "", "_atlaz_ext_link_at": "",
                     "_atlaz_ext_link_by": ""}})
    print(f"[ROLLBACK] modified={res.modified_count}")


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--rollback", action="store_true")
    args = p.parse_args()

    if args.rollback:
        await rollback()
        return 0

    await ensure_indexes()
    await coverage("BEFORE")
    t0 = time.time()
    stats, conflicts = await backfill()
    elapsed = time.time() - t0
    await coverage("AFTER")
    print(f"[TIME] {elapsed:.2f}s · conflicts={len(conflicts)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
