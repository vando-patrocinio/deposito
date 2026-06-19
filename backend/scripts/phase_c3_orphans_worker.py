"""Phase C.3 — Pequenos órfãos (CEO 19/06/2026)

- 4 ativos órfãos: ONTs sintéticos do E2E validator (SN começando com
  'E2E-ONT-') → marca como `_e2e_synthetic=true` + `exclude_from_balance=true`
  para sair dos KPIs (estão poluindo o balanço sem refletir patrimônio real).
- 1 porta órfã: nac-cto-test-iter163-p8 → popula `ont_sn` a partir do
  ticket completion_data.

Zero delete. Audit log SHA-256.
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


async def run(company_id: str = "co-demo", dry_run: bool = False):
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    now = datetime.now(timezone.utc).isoformat()
    run_id = f"c3o-{uuid.uuid4().hex[:8]}"

    # 1) E2E synthetic ONTs → exclude_from_balance
    cur = db.stok_onts.find({
        "company_id": company_id, "tier": "official",
        "sn": {"$regex": "^E2E-ONT-"},
    }, {"_id": 0, "id": 1, "sn": 1})
    e2e_docs = await cur.to_list(length=None)
    e2e_ids = [d["id"] for d in e2e_docs]
    e2e_count = len(e2e_ids)

    if not dry_run and e2e_count > 0:
        await db.stok_onts.update_many(
            {"id": {"$in": e2e_ids}},
            {"$set": {
                "_e2e_synthetic": True,
                "exclude_from_balance": True,
                "asset_status": "synthetic_e2e",
                "phase_c3_run_id": run_id,
                "phase_c3_marked_at": now,
                "phase_c3_reason": (
                    "ONT sintético do validador E2E (Phase B). "
                    "Não representa patrimônio real. Excluído do balanço "
                    "para não distorcer KPIs."
                ),
            }},
        )

    # 2) Porta órfã: nac-cto-test-iter163-p8
    orphan_port_id = "nac-cto-test-iter163-p8"
    port = await db.network_access_canonical.find_one(
        {"id": orphan_port_id}, {"_id": 0})
    port_fixed = False
    port_fix_reason = "porta_nao_encontrada"
    if port:
        # Procura ont_sn do ticket associado
        tkt_id = port.get("ticket_id")
        if tkt_id:
            tkt = await db.tickets.find_one({"id": tkt_id},
                {"_id": 0, "completion_data": 1})
            cd = (tkt or {}).get("completion_data") or {}
            new_sn = cd.get("ont_sn") or cd.get("ont")
            new_mac = cd.get("ont_mac")
            if new_sn or new_mac:
                if not dry_run:
                    await db.network_access_canonical.update_one(
                        {"id": orphan_port_id},
                        {"$set": {
                            "ont_sn": new_sn,
                            "ont_mac": new_mac,
                            "phase_c3_run_id": run_id,
                            "phase_c3_repaired_at": now,
                            "phase_c3_source": f"ticket_completion_data:{tkt_id}",
                        }},
                    )
                port_fixed = True
                port_fix_reason = f"ont_sn={new_sn}_from_{tkt_id}"
            else:
                port_fix_reason = "ticket_sem_ont_sn"
        else:
            port_fix_reason = "porta_sem_ticket_associado"

    # 3) Final KPIs
    ativos_sem_resp = await db.stok_onts.count_documents({
        "company_id": company_id, "tier": "official",
        "subscriber_id": {"$in": [None, ""]},
        "_e2e_synthetic": {"$ne": True},
    })
    porta_orfa = await db.network_access_canonical.count_documents({
        "company_id": company_id, "status": "occupied",
        "$and": [
            {"$or": [{"ont_sn": {"$in": [None, ""]}},
                     {"ont_sn": {"$exists": False}}]},
            {"$or": [{"ont_mac": {"$in": [None, ""]}},
                     {"ont_mac": {"$exists": False}}]},
        ],
    })

    audit = {
        "run_id": run_id,
        "company_id": company_id,
        "executed_at": now,
        "executed_by": "phase_c3_orphans_worker",
        "dry_run": dry_run,
        "e2e_synthetic_marked": e2e_count,
        "e2e_ont_ids": e2e_ids,
        "orphan_port_id": orphan_port_id,
        "orphan_port_fixed": port_fixed,
        "orphan_port_fix_reason": port_fix_reason,
        "kpis_after": {
            "ativos_sem_responsavel_excl_e2e": ativos_sem_resp,
            "portas_orfas_remaining": porta_orfa,
        },
        "ceo_authorization": "Phase C.3 — 19/06/2026",
    }
    audit["hash_sha256"] = hashlib.sha256(
        json.dumps(audit, sort_keys=True, default=str).encode()
    ).hexdigest()
    if not dry_run:
        await db.phase_c3_orphans_runs.insert_one(dict(audit))

    print("=" * 64)
    print("PHASE C.3 — PEQUENOS ÓRFÃOS")
    print("=" * 64)
    print(f"run_id={run_id}  dry_run={dry_run}")
    print(f"  E2E synthetic ONTs marked:     {e2e_count}")
    print(f"  Orphan port fixed:             {port_fixed}")
    print(f"     reason: {port_fix_reason}")
    print(f"  Ativos sem resp. (excl E2E):   {ativos_sem_resp}")
    print(f"  Portas órfãs remaining:        {porta_orfa}")
    print(f"  hash_sha256: {audit['hash_sha256']}")
    print("=" * 64)
    return audit


if __name__ == "__main__":
    import sys
    asyncio.run(run(dry_run="--dry" in sys.argv))
