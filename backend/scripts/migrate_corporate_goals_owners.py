"""Migration: aplica owner mapping CEO 15/06/2026 em corporate_goals.

Spec (cto_inbox cto-7f1b3d5e3de846):
  - clientes_ativos -> diretor_comercial
  - mrr -> diretor_comercial
  - inadimplencia_brl -> CFO
  - embaixadores -> marketing_growth
  - fundadores_aptos -> CEO
"""
from __future__ import annotations
import asyncio
import sys
import os

# Ensure backend dir is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db  # noqa: E402

OWNER_MAP = {
    "clientes_ativos": "diretor_comercial",
    "mrr": "diretor_comercial",
    "inadimplencia_brl": "CFO",
    "embaixadores": "marketing_growth",
    "fundadores_aptos": "CEO",
}

COMPANY_ID = os.environ.get("MIGRATION_CID", "co-demo")


async def main() -> int:
    updated = 0
    for kpi, owner in OWNER_MAP.items():
        res = await db.corporate_goals.update_one(
            {"company_id": COMPANY_ID, "kpi_key": kpi, "status": "active"},
            {"$set": {"owner": owner}},
        )
        if res.modified_count:
            updated += 1
            print(f"  ✓ {kpi:25} -> {owner}")
        else:
            doc = await db.corporate_goals.find_one(
                {"company_id": COMPANY_ID, "kpi_key": kpi, "status": "active"})
            cur_owner = (doc or {}).get("owner")
            print(f"  · {kpi:25} já = {cur_owner} (skip)")
    print(f"\nDone. {updated} docs atualizados em corporate_goals ({COMPANY_ID}).")
    return updated


if __name__ == "__main__":
    asyncio.run(main())
