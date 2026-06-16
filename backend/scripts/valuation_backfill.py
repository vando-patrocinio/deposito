"""R1.2 — VALUATION BACKFILL · DRY RUN (READ-ONLY).

Lê todas as ONTs de uma `company_id` e, sem escrever, simula o valuation:

  - Distribuição por Grade (A, B, C, D, E, F).
  - Patrimônio mínimo, máximo, auditável, especulativo.
  - Top 20 modelos.
  - Top 20 ONTs sem valuation (Grade F).
  - Percentual de confiança.
  - Sample dump dos casos limite.

ESCRITA EM BANCO: ZERO. Apenas grava 1 relatório JSON em
`/app/memory/VALUATION_BACKFILL_DRY_RUN_<ts>.json`.

Uso:
  python3 scripts/valuation_backfill.py --dry-run [--company co-demo]
  python3 scripts/valuation_backfill.py --apply    [BLOQUEADO ATÉ AUTORIZAÇÃO]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import db  # noqa: E402
from services.inventory_valuation import (  # noqa: E402
    resolve_valuation, effective_value, compute_weighted_avg,
    is_model_garbage, MODEL_CANONICAL,
)


async def run_dry_run(company_id: str) -> Dict[str, Any]:
    started = datetime.now(timezone.utc).isoformat()
    onts = await db.stok_onts.find(
        {"company_id": company_id}, {"_id": 0}).to_list(None)
    total = len(onts)
    if total == 0:
        return {
            "company_id": company_id,
            "scanned_at": started,
            "ont_total": 0,
            "warning": "Tenant sem ONTs cadastradas.",
        }

    try:
        weighted_avg = await compute_weighted_avg(company_id=company_id)
    except Exception:
        weighted_avg = None

    grade_counts: Counter = Counter()
    source_counts: Counter = Counter()
    model_counts: Counter = Counter()
    patrimony_per_grade: Dict[str, float] = defaultdict(float)
    patrimony_per_source: Dict[str, float] = defaultdict(float)
    sample_grade_A: List[Dict[str, Any]] = []
    sample_grade_F: List[Dict[str, Any]] = []
    no_purchase_id_count = 0
    autosn_locked_count = 0
    model_garbage_count = 0
    fantasma_macs: List[str] = []
    # Onda 1.2 — coleta valores por ONT para top 20 high/low
    per_ont_values: List[Dict[str, Any]] = []

    for ont in onts:
        v = await resolve_valuation(ont, weighted_avg_cache=weighted_avg)
        g = v["valuation_grade"]
        src = v["valuation_source"]
        ev = effective_value(v)
        grade_counts[g] += 1
        source_counts[src] += 1
        patrimony_per_grade[g] += ev
        patrimony_per_source[src] += ev

        per_ont_values.append({
            "id": ont.get("id"), "mac": ont.get("mac"),
            "scan_sn": ont.get("scan_sn"), "model": ont.get("model"),
            "purchase_id": ont.get("purchase_id"),
            "location_type": ont.get("location_type"),
            "status": ont.get("status"),
            "grade": g, "source": src, "value": round(ev, 2),
            "valor_nf": v["valor_nf"],
        })

        mdl = (ont.get("model") or "(null)").strip() or "(null)"
        model_counts[mdl] += 1
        if not ont.get("purchase_id"):
            no_purchase_id_count += 1
        sn = ont.get("scan_sn") or ""
        if isinstance(sn, str) and sn.upper().startswith("AUTOSN_"):
            autosn_locked_count += 1
        if is_model_garbage(ont.get("model")):
            model_garbage_count += 1
        if g == "A" and len(sample_grade_A) < 5:
            sample_grade_A.append({
                "id": ont.get("id"), "mac": ont.get("mac"),
                "scan_sn": ont.get("scan_sn"), "model": ont.get("model"),
                "purchase_id": ont.get("purchase_id"),
                "resolved_valor_nf": v["valor_nf"],
            })
        if g == "F":
            if len(sample_grade_F) < 20:
                sample_grade_F.append({
                    "id": ont.get("id"), "mac": ont.get("mac"),
                    "scan_sn": ont.get("scan_sn"),
                    "model": ont.get("model"),
                    "location_type": ont.get("location_type"),
                    "status": ont.get("status"),
                    "client_name": ont.get("client_name"),
                })
            if len(fantasma_macs) < 200:
                fantasma_macs.append(ont.get("mac"))

    # Onda 1.2 — Top 20 maior valor + Top 20 menor valor
    sorted_high = sorted(per_ont_values, key=lambda x: x["value"], reverse=True)
    sorted_low = sorted(per_ont_values, key=lambda x: x["value"])
    top20_highest = sorted_high[:20]
    top20_lowest = sorted_low[:20]

    patrimony_total = sum(patrimony_per_grade.values())
    auditable = (patrimony_per_grade.get("A", 0)
                  + patrimony_per_grade.get("B", 0))
    speculative = (patrimony_per_grade.get("C", 0)
                    + patrimony_per_grade.get("D", 0)
                    + patrimony_per_grade.get("F", 0))
    patrimony_min = total * 50.0
    patrimony_max = total * 400.0
    confidence_pct = round(((grade_counts["A"] + grade_counts["B"])
                             / max(1, total)) * 100, 2)
    finished = datetime.now(timezone.utc).isoformat()

    return {
        "scanned_at": started,
        "finished_at": finished,
        "company_id": company_id,
        "ont_total": total,
        "grade_distribution": {g: grade_counts.get(g, 0) for g in "ABCDEF"},
        "grade_pct": {g: round(grade_counts.get(g, 0) / total * 100, 2)
                       for g in "ABCDEF"},
        "source_distribution": dict(source_counts),
        # Onda 1.2 — patrimônio por SOURCE também
        "patrimony_per_source": {k: round(v, 2)
                                   for k, v in patrimony_per_source.items()},
        "weighted_avg_used": weighted_avg,
        "patrimony": {
            "min_possible": patrimony_min,
            "max_possible": patrimony_max,
            "calculated_total": round(patrimony_total, 2),
            "auditable_AB": round(auditable, 2),
            "speculative_CDF": round(speculative, 2),
            "per_grade": {g: round(patrimony_per_grade.get(g, 0), 2)
                            for g in "ABCDEF"},
        },
        "needs_human_review": {
            "no_purchase_id_count": no_purchase_id_count,
            "autosn_locked_count": autosn_locked_count,
            "model_garbage_count": model_garbage_count,
            "grade_F_total": grade_counts.get("F", 0),
        },
        "top_20_models": model_counts.most_common(20),
        "top_20_grade_F_samples": sample_grade_F,
        "sample_grade_A": sample_grade_A,
        # Onda 1.2 — sanity check outliers
        "top_20_highest_value": top20_highest,
        "top_20_lowest_value": top20_lowest,
        "confidence_pct": confidence_pct,
        "model_canonical_table_size": len(MODEL_CANONICAL),
        "dry_run": True,
        "would_write": 0,
    }


async def apply_backfill(company_id: str, batch_size: int = 200) -> Dict[str, Any]:
    """R1.3 — Apply autorizado pelo CEO.

    Executa update_many idempotente em batches. Para cada ONT:
    - Calcula valuation via resolve_valuation().
    - Faz $set com os 7 campos.
    - Re-rodar é seguro: sobrescreve valuation_calculated_at, valor_*, grade.

    Rollback: armazenado em /app/memory/VALUATION_APPLY_ROLLBACK_<ts>.json
    com snapshot do estado anterior por ONT (caso seja necessário reverter).
    """
    started = datetime.now(timezone.utc).isoformat()
    onts = await db.stok_onts.find(
        {"company_id": company_id}, {"_id": 0}).to_list(None)
    total = len(onts)
    if total == 0:
        return {"company_id": company_id, "ont_total": 0,
                "warning": "Tenant sem ONTs cadastradas."}

    weighted_avg = await compute_weighted_avg(company_id=company_id)

    # Snapshot pré-apply (rollback)
    rollback_docs = []
    grade_counts: Counter = Counter()
    source_counts: Counter = Counter()
    patrimony_per_grade: Dict[str, float] = defaultdict(float)
    updated = 0
    errors: List[Dict[str, Any]] = []

    # Bootstrap dos índices antes do apply
    from services.inventory_valuation import ensure_indexes
    await ensure_indexes()

    for i in range(0, total, batch_size):
        chunk = onts[i:i + batch_size]
        for ont in chunk:
            try:
                v = await resolve_valuation(ont, weighted_avg_cache=weighted_avg)
                rollback_docs.append({
                    "id": ont.get("id"),
                    "mac": ont.get("mac"),
                    "previous": {
                        "valor_nf": ont.get("valor_nf"),
                        "valor_medio_ponderado": ont.get("valor_medio_ponderado"),
                        "valor_referencia": ont.get("valor_referencia"),
                        "valuation_grade": ont.get("valuation_grade"),
                        "valuation_source": ont.get("valuation_source"),
                        "valuation_calculated_at": ont.get("valuation_calculated_at"),
                        "valuation_needs_human_review": ont.get(
                            "valuation_needs_human_review"),
                    },
                })
                # Filtra preferencialmente por (id, company) OU por (mac, company).
                # 26/28 das ONTs legadas no co-demo não têm campo `id` —
                # usar id=None colapsaria todas. MAC é único garantido.
                mac = ont.get("mac")
                ont_id = ont.get("id")
                if ont_id:
                    filt = {"id": ont_id, "company_id": company_id}
                elif mac:
                    filt = {"mac": mac, "company_id": company_id}
                else:
                    errors.append({
                        "id": None, "mac": None,
                        "error": "ONT sem id e sem mac — não pode ser localizada",
                    })
                    continue
                res = await db.stok_onts.update_one(filt, {"$set": v})
                if res.matched_count == 1:
                    updated += 1
                    g = v["valuation_grade"]
                    grade_counts[g] += 1
                    source_counts[v["valuation_source"]] += 1
                    patrimony_per_grade[g] += effective_value(v)
                elif res.matched_count == 0:
                    errors.append({
                        "id": ont_id, "mac": mac,
                        "error": f"filter não bateu: {filt}",
                    })
            except Exception as e:
                errors.append({"id": ont.get("id"),
                                "mac": ont.get("mac"),
                                "error": str(e)[:200]})

    finished = datetime.now(timezone.utc).isoformat()

    auditable = (patrimony_per_grade.get("A", 0)
                  + patrimony_per_grade.get("B", 0))
    speculative = (patrimony_per_grade.get("C", 0)
                    + patrimony_per_grade.get("D", 0)
                    + patrimony_per_grade.get("F", 0))
    confidence_pct = round(((grade_counts["A"] + grade_counts["B"])
                              / max(1, total)) * 100, 2)

    # Salva rollback
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rollback_path = Path("/app/memory") / f"VALUATION_APPLY_ROLLBACK_{ts}.json"
    rollback_path.write_text(json.dumps({
        "company_id": company_id,
        "applied_at": started, "finished_at": finished,
        "total": total, "updated": updated,
        "rollback_docs": rollback_docs,
    }, indent=2, ensure_ascii=False))

    return {
        "company_id": company_id,
        "started_at": started, "finished_at": finished,
        "ont_total": total,
        "updated": updated,
        "errors_count": len(errors),
        "errors_sample": errors[:10],
        "grade_distribution": {g: grade_counts.get(g, 0) for g in "ABCDEF"},
        "source_distribution": dict(source_counts),
        "patrimony": {
            "auditable_AB": round(auditable, 2),
            "speculative_CDF": round(speculative, 2),
            "total": round(auditable + speculative, 2),
            "per_grade": {g: round(patrimony_per_grade.get(g, 0), 2)
                            for g in "ABCDEF"},
        },
        "confidence_pct": confidence_pct,
        "rollback_file": str(rollback_path),
    }


async def main():
    parser = argparse.ArgumentParser(description="Valuation Backfill")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--company", default="co-demo")
    parser.add_argument("--output-dir", default="/app/memory")
    args = parser.parse_args()

    if args.apply and not args.dry_run:
        print(f"\n▶ APPLY autorizado pelo CEO — company_id={args.company}\n")
        result = await apply_backfill(args.company)
        print(f"ONT total:         {result.get('ont_total')}")
        print(f"Atualizadas:       {result.get('updated')}")
        print(f"Erros:             {result.get('errors_count')}")
        if result.get("grade_distribution"):
            print(f"\nDistribuição final por Grade:")
            for g in "ABCDEF":
                n = result["grade_distribution"].get(g, 0)
                pat = result["patrimony"]["per_grade"].get(g, 0)
                print(f"  Grade {g}: {n:5d} · R$ {pat:>12,.2f}")
            print(f"\nAuditável (A+B):  R$ {result['patrimony']['auditable_AB']:,.2f}")
            print(f"Especulativo:     R$ {result['patrimony']['speculative_CDF']:,.2f}")
            print(f"Total:            R$ {result['patrimony']['total']:,.2f}")
            print(f"Confiança:        {result['confidence_pct']}%")
        print(f"\nRollback file:    {result.get('rollback_file')}")
        if result.get("errors_sample"):
            print("\nERROS (primeiros 10):")
            for e in result["errors_sample"]:
                print(f"  {e}")
        # Persiste relatório apply
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        apply_path = Path(args.output_dir) / f"VALUATION_APPLY_REPORT_{ts}.json"
        apply_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"📝 Relatório apply: {apply_path}")
        return

    if not args.dry_run:
        print("Uso: --dry-run ou --apply (--apply requer autorização CEO)")
        sys.exit(2)

    print(f"\n▶ Dry-run para company_id={args.company}\n")
    report = await run_dry_run(args.company)

    # Imprime resumo no stdout
    print(f"ONT total: {report['ont_total']}")
    if report.get("ont_total", 0) == 0:
        print(report.get("warning", "(sem dados)"))
        return
    print(f"\nDistribuição por Grade:")
    for g in "ABCDEF":
        n = report["grade_distribution"][g]
        pct = report["grade_pct"][g]
        pat = report["patrimony"]["per_grade"][g]
        print(f"  Grade {g}: {n:5d} ({pct:5.1f}%) · R$ {pat:>12,.2f}")
    print(f"\nPatrimônio (calculado): R$ {report['patrimony']['calculated_total']:,.2f}")
    print(f"  Auditável (A+B):       R$ {report['patrimony']['auditable_AB']:,.2f}")
    print(f"  Especulativo (C+D+F):  R$ {report['patrimony']['speculative_CDF']:,.2f}")
    print(f"  Range mínimo possível: R$ {report['patrimony']['min_possible']:,.2f}")
    print(f"  Range máximo possível: R$ {report['patrimony']['max_possible']:,.2f}")
    print(f"\nConfiança: {report['confidence_pct']}%")
    print(f"Weighted avg usado: R$ {report['weighted_avg_used']}")
    print(f"\nNeeds Human Review:")
    for k, v in report["needs_human_review"].items():
        print(f"  {k}: {v}")
    print(f"\nTop 10 modelos:")
    for m, n in report["top_20_models"][:10]:
        print(f"  {n:4d} × {m!r}")

    # Persiste
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(args.output_dir) / f"VALUATION_BACKFILL_DRY_RUN_{ts}.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n📝 Relatório completo: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
