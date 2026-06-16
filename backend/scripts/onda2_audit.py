"""ONDA 2.0 — Auditoria read-only de transferências.

Lê apenas. ZERO escrita. Responde às 10 perguntas do CEO.
"""
import asyncio
import sys
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import db  # noqa: E402


async def main():
    print("=" * 70)
    print("ONDA 2.0 — AUDITORIA TRANSFERÊNCIAS · READ-ONLY")
    print("=" * 70)

    # Janela: últimos 30 dias
    now = datetime.now(timezone.utc)
    since_30d = (now - timedelta(days=30)).isoformat()
    since_7d = (now - timedelta(days=7)).isoformat()

    # ─── Q1 — Rotas que movimentam estoque (estática conhecida) ───────────
    # (mapeada na fase A do main agent — não medível em runtime)

    # ─── Q2 — Movimentações totais pelo helper canônico ───────────────────
    inv_total = await db.inventory_os_movements_audit.count_documents({})
    inv_30d = await db.inventory_os_movements_audit.count_documents(
        {"created_at": {"$gte": since_30d}})
    inv_7d = await db.inventory_os_movements_audit.count_documents(
        {"created_at": {"$gte": since_7d}})
    print(f"\nQ2 — inventory_movements canônico:")
    print(f"  Total: {inv_total} · 30d: {inv_30d} · 7d: {inv_7d}")

    # Tipos de movimento canônicos
    types = await db.inventory_os_movements_audit.aggregate([
        {"$group": {"_id": "$movement_type", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
    ]).to_list(50)
    print(f"  Tipos:")
    for t in types:
        print(f"    {t['_id']:40s} {t['n']}")

    # ─── Q4 — Transferências/dia (via stok_history) ───────────────────────
    hist_total = await db.stok_history.count_documents({})
    hist_30d = await db.stok_history.count_documents(
        {"created_at": {"$gte": since_30d}})
    hist_7d = await db.stok_history.count_documents(
        {"created_at": {"$gte": since_7d}})
    print(f"\nQ4 — stok_history (transferências históricas):")
    print(f"  Total: {hist_total} · 30d: {hist_30d} · 7d: {hist_7d}")
    if hist_30d:
        print(f"  Média/dia (30d): {hist_30d / 30:.2f}")

    # Histórico por action
    actions = await db.stok_history.aggregate([
        {"$group": {"_id": "$action", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 20},
    ]).to_list(20)
    print(f"  Actions (top 15):")
    for a in actions[:15]:
        print(f"    {(a['_id'] or '(null)'):28s} {a['n']}")

    # ─── Q3 — Snapshot atual de ONTs por owner ────────────────────────────
    print(f"\nQ3 — Estado atual stok_onts:")
    by_loc = await db.stok_onts.aggregate([
        {"$group": {"_id": "$location_type", "n": {"$sum": 1}}},
    ]).to_list(50)
    for r in by_loc:
        print(f"  {(r['_id'] or '(null)'):14s} {r['n']}")

    # ─── Q5 — Top técnicos por movimentação (via histórico) ───────────────
    print(f"\nQ5 — Top 10 técnicos por movimentação (stok_history.actor):")
    top_actors = await db.stok_history.aggregate([
        {"$group": {"_id": "$actor", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 10},
    ]).to_list(10)
    for a in top_actors:
        print(f"  {(a['_id'] or '(null)'):30s} {a['n']}")

    # ─── Q6 — Dupla movimentação (mesma ONT, mesmo dia, ações diferentes) ─
    print(f"\nQ6 — Dupla movimentação (mesmo MAC > 1 ação no mesmo dia):")
    dup = await db.stok_history.aggregate([
        {"$match": {"created_at": {"$gte": since_30d}}},
        {"$project": {
            "mac": 1, "day": {"$substr": ["$created_at", 0, 10]}, "action": 1,
        }},
        {"$group": {
            "_id": {"mac": "$mac", "day": "$day"},
            "count": {"$sum": 1},
            "actions": {"$push": "$action"},
        }},
        {"$match": {"count": {"$gt": 1}}},
        {"$count": "n_dup_days"},
    ]).to_list(1)
    n_dup = dup[0]["n_dup_days"] if dup else 0
    print(f"  ONT×dia com >1 movimento: {n_dup}")

    # ─── Q7 — Movimento sem origem em inventory_movements ─────────────────
    print(f"\nQ7/Q8 — Trilhas com origem/destino faltando (inventory_movements):")
    no_origin = await db.inventory_os_movements_audit.count_documents(
        {"$or": [
            {"origin_type": {"$exists": False}},
            {"origin_type": None}, {"origin_type": ""},
        ]})
    no_dest = await db.inventory_os_movements_audit.count_documents(
        {"$or": [
            {"destination_type": {"$exists": False}},
            {"destination_type": None}, {"destination_type": ""},
        ]})
    print(f"  Sem origin_type: {no_origin}")
    print(f"  Sem destination_type: {no_dest}")

    # ─── Q9 — Transferência sem auditoria (heurística) ────────────────────
    print(f"\nQ9 — ONTs em técnico/cliente que NUNCA tiveram entrada em "
          f"inventory_movements:")
    onts_tech = await db.stok_onts.find(
        {"location_type": {"$in": ["tecnico", "cliente"]}},
        {"_id": 0, "mac": 1, "scan_sn": 1, "location_type": 1,
         "location_id": 1, "client_name": 1}).to_list(2000)
    macs_with_trail = set()
    cur = db.inventory_os_movements_audit.find(
        {}, {"_id": 0, "mac": 1, "sn": 1})
    async for m in cur:
        if m.get("mac"):
            macs_with_trail.add(m["mac"])
        if m.get("sn"):
            macs_with_trail.add(m["sn"])
    untracked = [o for o in onts_tech
                  if o.get("mac") not in macs_with_trail
                  and o.get("scan_sn") not in macs_with_trail]
    print(f"  Total em técnico/cliente: {len(onts_tech)}")
    print(f"  SEM trilha em inventory_movements: {len(untracked)}")
    if untracked[:5]:
        print(f"  Sample (5):")
        for u in untracked[:5]:
            print(f"    {u.get('location_type')[:8]} mac={u.get('mac')} sn={u.get('scan_sn')}")

    # ─── Q10 — Diff entre owner atual e última trilha histórica ───────────
    print(f"\nQ10 — Discrepâncias owner_atual ≠ último_destino_da_trilha:")
    discrepant = 0
    sample_disc = []
    for o in onts_tech[:200]:  # amostra
        mac = o.get("mac")
        if not mac:
            continue
        last = await db.inventory_os_movements_audit.find_one(
            {"mac": mac}, {"_id": 0, "destination_type": 1, "created_at": 1},
            sort=[("created_at", -1)])
        if not last:
            continue
        if last.get("destination_type") != o.get("location_type"):
            discrepant += 1
            if len(sample_disc) < 5:
                sample_disc.append({
                    "mac": mac, "current": o.get("location_type"),
                    "last_trail": last.get("destination_type"),
                })
    print(f"  Discrepantes (amostra 200): {discrepant}")
    for s in sample_disc:
        print(f"    {s}")

    # Status atual das collections cross-cutting
    print(f"\n═══ Observabilidade Onda 0/0c (recém-ativadas) ═══")
    acl = await db.auto_close_legacy_observability.count_documents({})
    sclo = await db.stok_close_legacy_observability.count_documents({})
    da = await db.destructive_actions_audit.count_documents({})
    print(f"  auto_close_legacy_observability: {acl}")
    print(f"  stok_close_legacy_observability: {sclo}")
    print(f"  destructive_actions_audit:       {da}")


if __name__ == "__main__":
    asyncio.run(main())
