"""Onda C P0.2 + P0.3 — RECONCILIAÇÃO LEGADO (combo 1a + 2a + 3d).

Aprovado CEO 18/06/2026. Executa em modo seguro (idempotente):

  1) Para cada técnico com saldo negativo (P0.2):
      • Zera os saldos negativos via $inc no stok_stock.
      • Cria stok_history `type=recovery` com tag
        `legacy_orphan_consumption_recovery_20260618` por consumível
        regularizado.

  2) Para cada stok_service órfã do técnico (P0.3):
      • Cria stok_history `type=legacy_orphan_link` apontando para
        o service_id + ticket_id deletado, com mesmo tag.

  3) Cria 1 doc master em stok_admin_log:
      `legacy_orphan_reconciliation_20260618` — a certidão.

Idempotente: roda 2x = 1 efeito (audit_id determinístico). Modo
--execute exige flag. Sem flag = dry-run completo.

ZERO deletes. Tudo via $set / $inc / upsert.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

sys.path.insert(0, "/app/backend")
for _ln in open("/app/backend/.env"):
    if "=" in _ln and not _ln.startswith("#"):
        _k, _v = _ln.strip().split("=", 1)
        os.environ.setdefault(_k, _v.strip('"'))

from database import db  # noqa: E402
from routes.stok import CONSUMABLE_IDS, CONSUMABLE_BY_ID  # noqa: E402

TAG = "legacy_orphan_consumption_recovery_20260618"
RCA_REFS = {
    "p0_2_doc": "/app/memory/TECNICOS_NEGATIVOS_DIFF.md",
    "p0_3_csv": "/app/memory/STOK_SERVICES_ORFAOS.csv",
    "audit_doc": "/app/memory/PRAÇA_TECNICO_AUDIT.md",
    "onda_a_report": "/app/memory/ONDA_A_REPORT_2026-06-18.md",
}
COMPANY_ID = "co-demo"
TARGET_TECHS = ["col-30aafc3c", "col-b4db2145"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit_id(prefix: str, *parts: str) -> str:
    base = f"{TAG}|{prefix}|" + "|".join(parts)
    return f"{prefix}-" + hashlib.sha256(base.encode()).hexdigest()[:12]


async def _get_tech_info(tid: str) -> Dict[str, Any]:
    return await db.collaborators.find_one(
        {"id": tid}, {"_id": 0, "id": 1, "name": 1}) or {"id": tid}


async def _get_stock(loc: str) -> Dict[str, Any]:
    return await db.stok_stock.find_one(
        {"company_id": COMPANY_ID, "location": loc}, {"_id": 0}) or {}


async def _orfas_of(tid: str) -> List[Dict[str, Any]]:
    out = []
    async for d in db.stok_services.find(
        {"company_id": COMPANY_ID, "technician_id": tid,
         "status": "orfa_sem_ticket"}, {"_id": 0}):
        out.append(d)
    return out


async def _plan_for_tech(tid: str) -> Dict[str, Any]:
    info = await _get_tech_info(tid)
    stock = await _get_stock(tid)
    orfas = await _orfas_of(tid)
    # Quais consumíveis precisam ser zerados (atualmente negativos)
    to_zero: List[Tuple[str, int]] = []
    for cons in sorted(CONSUMABLE_IDS):
        v = stock.get(cons)
        if isinstance(v, (int, float)) and v < 0:
            to_zero.append((cons, -int(v)))  # delta positivo pra zerar
    return {
        "tech_id": tid,
        "tech_name": info.get("name", tid),
        "to_zero": to_zero,
        "orfas": orfas,
    }


async def _execute_for_tech(plan: Dict[str, Any], dry_run: bool,
                            executor: str) -> Dict[str, Any]:
    tid = plan["tech_id"]
    name = plan["tech_name"]
    now = _now_iso()
    recovery_history_ids: List[str] = []
    link_history_ids: List[str] = []
    inc_doc: Dict[str, int] = {}

    # ── 1) Para cada consumível negativo: recovery ─────────────────────
    for cons, delta in plan["to_zero"]:
        aid = _audit_id("rec", tid, cons)
        hist_id = f"hist-{aid}"
        recovery_history_ids.append(hist_id)
        inc_doc[cons] = delta
        if not dry_run:
            cons_label = (CONSUMABLE_BY_ID.get(cons) or {}).get("name", cons)
            await db.stok_history.update_one(
                {"id": hist_id},
                {"$setOnInsert": {
                    "id": hist_id,
                    "company_id": COMPANY_ID,
                    "type": "recovery",
                    "tag": TAG,
                    "technician_id": tid,
                    "technician_name": name,
                    "consumable_id": cons,
                    "consumable_name": cons_label,
                    "delta_signed": +delta,
                    "description": (
                        f"Recovery legado: {name} +{delta} {cons_label} "
                        f"(zerando saldo negativo). "
                        f"Causa raiz: tickets deletados com consumo não "
                        f"rastreado (ver órfãos {TAG})."
                    ),
                    "user": executor,
                    "created_at": now,
                    "audit_id": aid,
                    "rca_refs": RCA_REFS,
                    "location": tid,
                }},
                upsert=True,
            )

    # ── 2) Para cada órfã: link explícito ──────────────────────────────
    for o in plan["orfas"]:
        sid = o.get("id")
        aid = _audit_id("link", tid, sid or "noid")
        hist_id = f"hist-{aid}"
        link_history_ids.append(hist_id)
        if not dry_run:
            await db.stok_history.update_one(
                {"id": hist_id},
                {"$setOnInsert": {
                    "id": hist_id,
                    "company_id": COMPANY_ID,
                    "type": "legacy_orphan_link",
                    "tag": TAG,
                    "technician_id": tid,
                    "technician_name": name,
                    "service_id": sid,
                    "original_ticket_id": o.get("ticket_id"),
                    "service_type": o.get("type"),
                    "service_previous_status": o.get("previous_status"),
                    "service_orphan_reason": o.get("orphan_reason"),
                    "service_orphaned_at": o.get("orphaned_at"),
                    "client_id": o.get("client_id"),
                    "client_name": o.get("client_name"),
                    "description": (
                        f"Link patrimonial: stok_service órfã {sid} "
                        f"({o.get('type')}) — ticket pai "
                        f"{o.get('ticket_id')} deletado. Consumo associado "
                        f"contribuiu para o saldo negativo regularizado."
                    ),
                    "user": executor,
                    "created_at": now,
                    "audit_id": aid,
                    "rca_refs": RCA_REFS,
                    "location": tid,
                }},
                upsert=True,
            )

    # ── 3) $inc no stok_stock ─────────────────────────────────────────
    if inc_doc and not dry_run:
        await db.stok_stock.update_one(
            {"company_id": COMPANY_ID, "location": tid},
            {"$inc": inc_doc, "$set": {"updated_at": now}},
        )

    after = await _get_stock(tid) if not dry_run else None
    return {
        "tech_id": tid,
        "tech_name": name,
        "consumables_zeroed": [
            {"consumable_id": c, "delta": d} for c, d in plan["to_zero"]
        ],
        "orfas_linked_count": len(plan["orfas"]),
        "recovery_history_ids": recovery_history_ids,
        "link_history_ids": link_history_ids,
        "stock_after": (
            {k: after.get(k) for k in CONSUMABLE_IDS if k in (after or {})}
            if after else None
        ),
    }


async def _write_master(executor: str, results: List[Dict[str, Any]],
                         dry_run: bool) -> Dict[str, Any]:
    master_aid = _audit_id("master", "all")
    master_id = f"adm-{master_aid}"
    total_orfas = sum(r["orfas_linked_count"] for r in results)
    total_units = sum(sum(c["delta"] for c in r["consumables_zeroed"])
                      for r in results)
    payload = {
        "id": master_id,
        "company_id": COMPANY_ID,
        "action": "legacy_orphan_reconciliation_20260618",
        "tag": TAG,
        "executor": executor,
        "executed_at": _now_iso(),
        "techs_processed": [r["tech_id"] for r in results],
        "techs_summary": [
            {"tech_id": r["tech_id"], "name": r["tech_name"],
             "orfas_linked": r["orfas_linked_count"],
             "consumables_zeroed": r["consumables_zeroed"],
             "units_recovered": sum(c["delta"]
                                     for c in r["consumables_zeroed"])}
            for r in results
        ],
        "totals": {
            "orfas_linked": total_orfas,
            "units_recovered": total_units,
            "techs_count": len(results),
            "recovery_history_docs": sum(
                len(r["recovery_history_ids"]) for r in results),
            "link_history_docs": sum(
                len(r["link_history_ids"]) for r in results),
        },
        "rca_refs": RCA_REFS,
        "csv_orfas": "/app/memory/STOK_SERVICES_ORFAOS.csv",
        "p0_2_report": "/app/memory/TECNICOS_NEGATIVOS_DIFF.md",
    }
    if not dry_run:
        await db.stok_admin_log.update_one(
            {"id": master_id},
            {"$setOnInsert": payload},
            upsert=True,
        )
    return payload


def _print_report(executor: str, planning: List[Dict[str, Any]],
                  results: List[Dict[str, Any]], master: Dict[str, Any],
                  dry_run: bool):
    print()
    print("=" * 76)
    print(f"  RECONCILIAÇÃO LEGADO ÓRFÃS — {'DRY-RUN' if dry_run else 'EXECUTADO'}")
    print(f"  Tag: {TAG}")
    print(f"  Executor: {executor}")
    print("=" * 76)
    for p, r in zip(planning, results):
        print(f"\n  👤 {p['tech_name']} ({p['tech_id']})")
        print(f"     Órfãs vinculadas: {p['orfas']}")
        if p["to_zero"]:
            print("     Saldos zerados:")
            for cons, delta in p["to_zero"]:
                label = (CONSUMABLE_BY_ID.get(cons) or {}).get("name", cons)
                print(f"        · {label}: +{delta}")
        if r.get("stock_after") is not None:
            neg = [
                (k, v) for k, v in r["stock_after"].items()
                if isinstance(v, (int, float)) and v < 0
            ]
            status = "✅ todos os negativos zerados" if not neg else f"❌ ainda negativos: {neg}"
            print(f"     Pós-execução: {status}")
    print(f"\n  📋 Totais master:")
    t = master["totals"]
    print(f"     Técnicos processados: {t['techs_count']}")
    print(f"     Órfãs vinculadas:     {t['orfas_linked']}")
    print(f"     Unidades recuperadas: {t['units_recovered']}")
    print(f"     stok_history docs:    {t['recovery_history_docs']} (recovery) + {t['link_history_docs']} (orphan_link)")
    print(f"     Master log id:        {master['id']}")
    print()


async def main():
    ap = argparse.ArgumentParser(
        description="P0.2+P0.3 Reconciliação legado (1a+2a+3d)")
    ap.add_argument("--execute", action="store_true",
                    help="Executa (sem essa flag = dry-run)")
    ap.add_argument("--executor", default="rca_20260618_ceo_approved",
                    help="Identificador executor")
    args = ap.parse_args()
    dry = not args.execute

    # 1) Planejar para cada técnico

    def _orfas_count(p):
        return len(p["orfas"])

    planning = []
    for tid in TARGET_TECHS:
        plan = await _plan_for_tech(tid)
        # truque pra printar a contagem (não a lista enorme)
        plan["orfas_count_display"] = _orfas_count(plan)
        plan["orfas"] = plan["orfas"]  # mantido para execução
        planning.append({**plan, "orfas": plan["orfas"]})

    # converte só pro print
    planning_print = [{**p, "orfas": _orfas_count(p)} for p in planning]

    # 2) Executar (ou simular)
    results = []
    for p in planning:
        r = await _execute_for_tech(p, dry_run=dry, executor=args.executor)
        results.append(r)

    # 3) Master
    master = await _write_master(args.executor, results, dry_run=dry)

    _print_report(args.executor, planning_print, results, master, dry)


if __name__ == "__main__":
    asyncio.run(main())
