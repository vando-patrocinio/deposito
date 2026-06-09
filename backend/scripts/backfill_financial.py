"""
backfill_financial.py — FASE 11 (Constituição V5.0 / Prioridade Nº 1)

Popula `plan_price` e `monthly_fee` em subscribers usando 3 fontes em cascata:
  1. mediana das invoices pagas do subscriber (via document/external_id)
  2. mediana de todas invoices do subscriber (independente do status)
  3. plan_name match em plans.monthly_price
  4. mediana global de invoices da empresa (último recurso)

Uso:
    cd /app/backend && python -m scripts.backfill_financial [audit|fix]
"""
from __future__ import annotations
import asyncio, os, sys, statistics
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))


async def _plan_index(db) -> dict:
    out = {}
    async for p in db.plans.find({"monthly_price": {"$gt": 0}}):
        name = (p.get("name") or "").strip().lower()
        if name:
            out[name] = p["monthly_price"]
    return out


async def _company_median(db, company_id: str) -> float | None:
    docs = await db.subscriber_invoices.find(
        {"company_id": company_id, "amount": {"$gt": 0}, "status": "paid"},
        {"amount": 1}).limit(5000).to_list(5000)
    if not docs:
        return None
    return round(statistics.median(d["amount"] for d in docs), 2)


def _median(values: list[float]) -> float | None:
    values = [v for v in values if v and v > 0]
    if not values:
        return None
    return round(statistics.median(values), 2)


async def backfill(db, dry_run: bool = False) -> dict:
    plans_by_name = await _plan_index(db)
    company_medians: dict = {}

    stats = {
        "scanned": 0, "already_priced": 0,
        "filled_by_paid_invoices": 0,
        "filled_by_any_invoices": 0,
        "filled_by_plan_name": 0,
        "filled_by_company_median": 0,
        "unresolved": 0,
        "total_updated": 0,
    }

    cursor = db.subscribers.find({}, {
        "id": 1, "company_id": 1, "document": 1, "external_code": 1,
        "plan_name": 1, "plan_price": 1, "monthly_fee": 1, "status": 1})
    async for s in cursor:
        stats["scanned"] += 1
        existing = s.get("plan_price") or s.get("monthly_fee")
        if existing and float(existing) > 0:
            stats["already_priced"] += 1
            continue
        cid = s.get("company_id")
        doc = s.get("document") or ""
        ext = s.get("external_code") or ""
        match_inv = []
        if doc or ext:
            inv_filter = {"company_id": cid,
                          "amount": {"$gt": 0}, "status": "paid"}
            ors = []
            if doc: ors.append({"subscriber_document": doc})
            if ext: ors.append({"subscriber_external_id": ext})
            if ors:
                inv_filter["$or"] = ors
                async for x in db.subscriber_invoices.find(
                        inv_filter, {"amount": 1}).limit(12):
                    match_inv.append(x["amount"])

        price = _median(match_inv)
        source = None
        if price:
            source = "paid_invoices"
            stats["filled_by_paid_invoices"] += 1
        else:
            # fonte 2: qualquer invoice
            any_inv = []
            if doc or ext:
                f2 = {"company_id": cid, "amount": {"$gt": 0}}
                ors = []
                if doc: ors.append({"subscriber_document": doc})
                if ext: ors.append({"subscriber_external_id": ext})
                if ors:
                    f2["$or"] = ors
                    async for x in db.subscriber_invoices.find(
                            f2, {"amount": 1}).limit(12):
                        any_inv.append(x["amount"])
            price = _median(any_inv)
            if price:
                source = "any_invoices"
                stats["filled_by_any_invoices"] += 1

        if not price:
            pn = (s.get("plan_name") or "").strip().lower()
            if pn and pn in plans_by_name:
                price = plans_by_name[pn]
                source = "plan_name"
                stats["filled_by_plan_name"] += 1

        if not price:
            if cid not in company_medians:
                company_medians[cid] = await _company_median(db, cid)
            price = company_medians.get(cid)
            if price:
                source = "company_median"
                stats["filled_by_company_median"] += 1

        if not price:
            stats["unresolved"] += 1
            continue

        if not dry_run:
            await db.subscribers.update_one(
                {"id": s["id"]},
                {"$set": {"plan_price": float(price),
                          "monthly_fee": float(price),
                          "_plan_price_source": source,
                          "_plan_price_backfilled_at":
                              "2026-06-08T00:00:00Z"}})
            stats["total_updated"] += 1

    return stats


async def main(mode: str = "audit"):
    load_dotenv(ROOT / ".env")
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    dry = (mode == "audit")
    r = await backfill(db, dry_run=dry)
    import json
    print(json.dumps(r, indent=2))
    c.close()
    return r


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "audit"
    asyncio.run(main(mode))
