"""ONDA 1 — Medição read-only do patrimônio (sem mutação).

Roda no MongoDB local e devolve, por company_id:
  - contagem de ONTs por location_type
  - contagem de ONTs por status
  - histórico de operações destrutivas (stok_admin_log, purchases_deletion_audit)
  - heurística de valor patrimonial
"""
import asyncio
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import db  # noqa: E402


# Custo médio por categoria (a confirmar com CEO).
# Valores de referência ISP brasileiro 2026:
ONT_AVG_COST_BRL = 85.0          # ONU/ONT bridge típica
CONSUMABLE_AVG_COST = {
    "drop": 0.45,                # R$/metro
    "esticador": 0.80,
    "conector_fast": 4.50,
    "conector_fibra": 12.0,
    "conector_rede": 2.0,
    "cabo_rede": 1.20,           # R$/m
    "fibra_06fo": 4.50,          # R$/m
    "fibra_12fo": 6.50,
    "fibra_24fo": 11.0,
}


async def main():
    out = {}

    # Lista companies presentes em stok_onts
    companies = await db.stok_onts.distinct("company_id")
    print(f"\n=== Companies com inventário: {len(companies)} ===")
    for c in companies:
        print(f"  • {c}")

    print("\n=== PATRIMÔNIO POR LOCATION_TYPE × STATUS ===")
    grand_total = 0
    by_loc_total = defaultdict(int)
    by_status_total = defaultdict(int)
    for c in companies:
        pipeline = [
            {"$match": {"company_id": c}},
            {"$group": {
                "_id": {"loc": "$location_type", "st": "$status"},
                "n": {"$sum": 1},
            }},
            {"$sort": {"_id": 1}},
        ]
        rows = await db.stok_onts.aggregate(pipeline).to_list(1000)
        if not rows:
            continue
        print(f"\n  ─── {c} ───")
        c_total = 0
        for r in rows:
            loc = r["_id"].get("loc") or "(null)"
            st  = r["_id"].get("st")  or "(null)"
            n   = r["n"]
            c_total += n
            grand_total += n
            by_loc_total[loc] += n
            by_status_total[st] += n
            print(f"    {loc:14s} · {st:24s} · {n}")
        print(f"    TOTAL company {c}: {c_total}")

    print("\n=== GRAND TOTAL ===")
    print(f"  ONTs no sistema (todas companies): {grand_total}")
    print("\n  Por location_type:")
    for k, v in sorted(by_loc_total.items(), key=lambda x: -x[1]):
        print(f"    {k:14s} · {v}")
    print("\n  Por status:")
    for k, v in sorted(by_status_total.items(), key=lambda x: -x[1]):
        print(f"    {k:24s} · {v}")

    print("\n=== VALOR PATRIMONIAL (heurística R$/ONT={:.2f}) ===".format(ONT_AVG_COST_BRL))
    print(f"  Patrimônio total: R$ {grand_total * ONT_AVG_COST_BRL:,.2f}")
    for k, v in sorted(by_loc_total.items(), key=lambda x: -x[1]):
        print(f"    {k:14s} · R$ {v * ONT_AVG_COST_BRL:,.2f} ({v} unidades)")

    print("\n=== HISTÓRICO DE OPERAÇÕES DESTRUTIVAS ===")
    # stok_admin_log
    log_count = await db.stok_admin_log.count_documents({})
    print(f"  stok_admin_log: {log_count} registros totais")
    if log_count:
        actions = await db.stok_admin_log.aggregate([
            {"$group": {"_id": "$action", "n": {"$sum": 1}}}
        ]).to_list(50)
        for a in actions:
            print(f"    {a['_id']}: {a['n']}")
        # últimos 5
        last = await db.stok_admin_log.find(
            {}, {"_id": 0, "action": 1, "timestamp": 1,
                 "performed_by_email": 1, "before": 1, "deleted": 1}
        ).sort("timestamp", -1).limit(5).to_list(5)
        print("    Últimos 5 resets:")
        for l in last:
            print(f"      [{l.get('timestamp')}] {l.get('action')} by {l.get('performed_by_email')}")
            print(f"        before={l.get('before')} deleted={l.get('deleted')}")

    # purchases_deletion_audit
    pda_count = await db.purchases_deletion_audit.count_documents({})
    print(f"\n  purchases_deletion_audit: {pda_count} registros totais")
    if pda_count:
        last = await db.purchases_deletion_audit.find(
            {}, {"_id": 0, "deleted_at": 1, "deleted_by_email": 1,
                 "reverted_summary": 1}
        ).sort("deleted_at", -1).limit(5).to_list(5)
        for l in last:
            print(f"      [{l.get('deleted_at')}] by {l.get('deleted_by_email')}: "
                  f"reverted={l.get('reverted_summary')}")

    # scrap counts (status atual)
    scrap_count = await db.stok_onts.count_documents({"status": "sucateada"})
    defective_count = await db.stok_onts.count_documents(
        {"status": {"$in": ["defeito_devolver_empresa", "defeito_em_analise"]}})
    print(f"\n  ONTs sucateadas (status=sucateada): {scrap_count}")
    print(f"  ONTs em defeito: {defective_count}")

    # Inventory movements (trilha canônica)
    inv_count = await db.inventory_os_movements_audit.count_documents({})
    print(f"\n  inventory_os_movements_audit: {inv_count} registros totais")
    if inv_count:
        types = await db.inventory_os_movements_audit.aggregate([
            {"$group": {"_id": "$movement_type", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}}
        ]).to_list(50)
        for t in types:
            print(f"    {t['_id']:40s} · {t['n']}")

    # Observabilidade Onda 0 (recém ativadas — esperado 0 por enquanto)
    acl_count = await db.auto_close_legacy_observability.count_documents({})
    sclo_count = await db.stok_close_legacy_observability.count_documents({})
    print(f"\n  auto_close_legacy_observability (Onda 0b): {acl_count}")
    print(f"  stok_close_legacy_observability  (Onda 0c): {sclo_count}")

    print("\n=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
