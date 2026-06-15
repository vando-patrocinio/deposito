"""IDENTIDADE ÚNICA — passo 1 · Subscriber ↔ Atlaz (loyalty_imported_db).

v2 (15/06/2026):
- Filtra pelo escopo real (skip SYNTHETIC_TENANTS).
- Resolve ambiguidade escolhendo: 1º loyalty status=Ativo mais recente,
  senão o mais recente por registration_date.
- Bulk writes em lotes de 1000 sem ordering.

Campos persistidos:
- subscribers: atlaz_linked, atlaz_loyalty_id, atlaz_link_status, _atlaz_link_at, _atlaz_link_by
  atlaz_link_status ∈ {linked, no_atlaz_record, no_document_or_test}
- loyalty_imported_db (apenas o doc CANÔNICO escolhido): subscriber_id, _subscriber_link_at, _subscriber_link_by

Reversível via `--rollback`.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
from database import db  # noqa: E402
from constants.synthetic_tenants import SYNTHETIC_TENANTS  # noqa: E402

TAGGED_BY = "identidade_unica_atlaz_v2"
BATCH = 1000


def _sort_key(d: dict) -> tuple:
    """Mais recente Ativo > mais recente por registration_date > qualquer."""
    is_ativo = 1 if d.get("status") == "Ativo" else 0
    reg = d.get("registration_date") or ""
    return (is_ativo, reg)


async def ensure_indexes() -> None:
    await db.subscribers.create_index(
        [("company_id", 1), ("document", 1)],
        name="company_id_1_document_1", background=True)
    await db.loyalty_imported_db.create_index(
        [("company_id", 1), ("document", 1)],
        name="company_id_1_document_1", background=True)
    await db.loyalty_imported_db.create_index(
        [("company_id", 1), ("subscriber_id", 1)],
        name="company_id_1_subscriber_id_1", background=True)
    print("[INDEX] OK")


async def link() -> None:
    from pymongo import UpdateOne
    now = datetime.now(timezone.utc).isoformat()
    real_filter = {"company_id": {"$nin": SYNTHETIC_TENANTS}}

    # 1. loyalty_map (apenas tenants reais): (cid, doc) -> melhor loyalty
    print("[STEP 1] Lendo loyalty (tenants reais)…")
    cand_map: dict[tuple[str, str], dict] = {}
    cur = db.loyalty_imported_db.find(
        {**real_filter, "document": {"$nin": ["", None]}},
        {"id": 1, "company_id": 1, "document": 1, "status": 1,
         "registration_date": 1})
    async for d in cur:
        k = (d["company_id"], d["document"])
        cur_best = cand_map.get(k)
        if cur_best is None or _sort_key(d) > _sort_key(cur_best):
            cand_map[k] = d
    print(f"[STEP 1] {len(cand_map)} pares (cid,doc) candidatos canônicos")

    # 2. Link subscribers
    print("[STEP 2] Linkando subscribers (tenants reais)…")
    stats = defaultdict(int)
    bulk_subs: list = []
    bulk_loy: list = []

    cur = db.subscribers.find(real_filter,
                               {"id": 1, "company_id": 1, "document": 1})
    async for s in cur:
        sid = s.get("id")
        cid = s.get("company_id")
        doc = (s.get("document") or "").strip()
        if not doc:
            stats["no_document_or_test"] += 1
            bulk_subs.append(UpdateOne({"id": sid}, {"$set": {
                "atlaz_linked": False,
                "atlaz_link_status": "no_document_or_test",
                "_atlaz_link_at": now, "_atlaz_link_by": TAGGED_BY}}))
        else:
            best = cand_map.get((cid, doc))
            if not best:
                stats["no_atlaz_record"] += 1
                bulk_subs.append(UpdateOne({"id": sid}, {"$set": {
                    "atlaz_linked": False, "atlaz_loyalty_id": None,
                    "atlaz_link_status": "no_atlaz_record",
                    "_atlaz_link_at": now, "_atlaz_link_by": TAGGED_BY}}))
            else:
                stats["linked"] += 1
                loy_id = best.get("id") or str(best.get("_id"))
                bulk_subs.append(UpdateOne({"id": sid}, {"$set": {
                    "atlaz_linked": True,
                    "atlaz_loyalty_id": loy_id,
                    "atlaz_link_status": "linked",
                    "_atlaz_link_at": now,
                    "_atlaz_link_by": TAGGED_BY}}))
                bulk_loy.append(UpdateOne({"id": loy_id}, {"$set": {
                    "subscriber_id": sid,
                    "_subscriber_link_at": now,
                    "_subscriber_link_by": TAGGED_BY}}))
        if len(bulk_subs) >= BATCH:
            await db.subscribers.bulk_write(bulk_subs, ordered=False)
            bulk_subs.clear()
        if len(bulk_loy) >= BATCH:
            await db.loyalty_imported_db.bulk_write(bulk_loy, ordered=False)
            bulk_loy.clear()

    if bulk_subs:
        await db.subscribers.bulk_write(bulk_subs, ordered=False)
    if bulk_loy:
        await db.loyalty_imported_db.bulk_write(bulk_loy, ordered=False)
    print(f"[STEP 2] STATS: {dict(stats)}")


async def rollback() -> None:
    res1 = await db.subscribers.update_many(
        {"_atlaz_link_by": {"$in": [TAGGED_BY, "identidade_unica_atlaz"]}},
        {"$unset": {"atlaz_linked": "", "atlaz_loyalty_id": "",
                     "atlaz_loyalty_ids_all": "", "atlaz_link_status": "",
                     "_atlaz_link_at": "", "_atlaz_link_by": ""}})
    res2 = await db.loyalty_imported_db.update_many(
        {"_subscriber_link_by": {"$in": [TAGGED_BY, "identidade_unica_atlaz"]}},
        {"$unset": {"subscriber_id": "", "_subscriber_link_at": "",
                     "_subscriber_link_by": ""}})
    print(f"[ROLLBACK] subs={res1.modified_count} · loyalty={res2.modified_count}")


async def report() -> None:
    cid = "co-demo"
    total = await db.subscribers.count_documents({"company_id": cid})
    by_status = {}
    for st in ("linked", "no_atlaz_record", "no_document_or_test"):
        by_status[st] = await db.subscribers.count_documents({
            "company_id": cid, "atlaz_link_status": st})
    loy_linked = await db.loyalty_imported_db.count_documents({
        "company_id": cid, "subscriber_id": {"$exists": True, "$ne": None}})
    loy_total = await db.loyalty_imported_db.count_documents({"company_id": cid})
    pct = (by_status['linked'] / total * 100) if total else 0
    print(f"[REPORT co-demo] subs={total} · {by_status}")
    print(f"[REPORT co-demo] loyalty linkadas (canônicas): {loy_linked}/{loy_total}")
    print(f"[REPORT co-demo] cobertura de link: {pct:.2f}%")


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--rollback", action="store_true")
    p.add_argument("--report-only", action="store_true")
    args = p.parse_args()
    if args.rollback:
        await rollback()
        return 0
    if args.report_only:
        await report()
        return 0
    await ensure_indexes()
    await link()
    await report()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
