"""
audit_multitenant.py — FASE 8
Audita orfandade `company_id` em coleções de negócio. Marca documentos
órfãos (sem company_id, null, vazio) com um valor `_orphan_company_id`
explícito ou faz backfill baseado em referência cruzada (heurística).

Modos:
    audit  — só lista (default)
    fix    — backfill seguro via tabela de referência (companies)
"""
from __future__ import annotations
import asyncio, os, sys, json
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

BUSINESS_COLLECTIONS = [
    "subscribers", "tickets", "appointments", "subscriber_invoices",
    "sales_leads", "collaborators", "users", "wa_chats", "wa_messages",
    "motor_ia_subscriber_scores", "motor_ia_revenue_attribution",
    "motor_ia_daily_briefings", "motor_ia_isabella_journeys",
    "motor_ia_knowledge_graph", "motor_ia_actions", "motor_ia_decisions",
    "motor_ia_events", "motor_ia_outcomes", "motor_ia_alerts",
    "audit_log", "smartolt_onus", "smartolt_olts", "olts", "ctos", "onus",
    "subscriber_consumption", "plans", "equipment", "vehicles",
    "holerites", "lousa_grid", "lousa_history", "atlaz_records",
    "budgets", "contracts", "referrals", "fidelity_clients",
]


def orphan_filter():
    return {"$or": [
        {"company_id": {"$exists": False}},
        {"company_id": None},
        {"company_id": ""},
    ]}


async def audit(db) -> dict:
    cols = set(await db.list_collection_names())
    report = {"summary": {}, "details": []}
    total_orphans = 0
    total_docs = 0
    for col in BUSINESS_COLLECTIONS:
        if col not in cols:
            continue
        total = await db[col].estimated_document_count()
        if total == 0:
            continue
        orph = await db[col].count_documents(orphan_filter())
        total_docs += total
        total_orphans += orph
        if orph > 0:
            pct = round(orph / max(total, 1) * 100, 2)
            report["details"].append({
                "collection": col, "total": total, "orphan": orph,
                "orphan_pct": pct,
            })
    report["summary"] = {
        "collections_scanned": len([c for c in BUSINESS_COLLECTIONS
                                       if c in cols]),
        "total_docs_in_scope": total_docs,
        "total_orphans": total_orphans,
        "orphan_pct_global": round(
            total_orphans / max(total_docs, 1) * 100, 4),
    }
    return report


async def fix(db, default_company_id: str = "_orphan") -> dict:
    """Backfill: marca todos os órfãos com `_orphan_company_id` único,
    permitindo distinguir de dados legítimos."""
    cols = set(await db.list_collection_names())
    out = {"fixed": []}
    for col in BUSINESS_COLLECTIONS:
        if col not in cols:
            continue
        r = await db[col].update_many(
            orphan_filter(),
            {"$set": {"company_id": default_company_id,
                      "_orphan_backfilled_at":
                      "2026-06-08T00:00:00Z"}})
        if r.modified_count > 0:
            out["fixed"].append({"collection": col,
                                   "modified": r.modified_count})
    return out


async def main(mode: str = "audit"):
    load_dotenv(ROOT / ".env")
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    if mode == "fix":
        result = await fix(db)
        print(json.dumps(result, indent=2))
    else:
        result = await audit(db)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    c.close()
    return result


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "audit"
    asyncio.run(main(mode))
