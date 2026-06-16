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

    # Pré-calcula weighted_avg uma única vez
    try:
        weighted_avg = await compute_weighted_avg(company_id=company_id)
    except Exception:
        weighted_avg = None

    # Aplica motor em cada ONT
    grade_counts: Counter = Counter()
    source_counts: Counter = Counter()
    model_counts: Counter = Counter()
    patrimony_per_grade: Dict[str, float] = defaultdict(float)
    sample_grade_A: List[Dict[str, Any]] = []
    sample_grade_F: List[Dict[str, Any]] = []
    no_purchase_id_count = 0
    autosn_locked_count = 0
    model_garbage_count = 0
    fantasma_macs: List[str] = []

    for ont in onts:
        v = await resolve_valuation(ont, weighted_avg_cache=weighted_avg)
        g = v["valuation_grade"]
        grade_counts[g] += 1
        source_counts[v["valuation_source"]] += 1
        patrimony_per_grade[g] += effective_value(v)

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

    # Range patrimonial total
    patrimony_total = sum(patrimony_per_grade.values())
    auditable = (patrimony_per_grade.get("A", 0)
                  + patrimony_per_grade.get("B", 0))
    speculative = (patrimony_per_grade.get("C", 0)
                    + patrimony_per_grade.get("D", 0)
                    + patrimony_per_grade.get("F", 0))

    # Min/Max (R$ 50 entry, R$ 400 high-end)
    patrimony_min = total * 50.0
    patrimony_max = total * 400.0

    # Confiança
    confidence_pct = round(((grade_counts["A"] + grade_counts["B"])
                             / max(1, total)) * 100, 2)

    finished = datetime.now(timezone.utc).isoformat()

    report = {
        "scanned_at": started,
        "finished_at": finished,
        "company_id": company_id,
        "ont_total": total,
        "grade_distribution": {g: grade_counts.get(g, 0)
                                 for g in "ABCDEF"},
        "grade_pct": {g: round(grade_counts.get(g, 0) / total * 100, 2)
                       for g in "ABCDEF"},
        "source_distribution": dict(source_counts),
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
        "confidence_pct": confidence_pct,
        "model_canonical_table_size": len(MODEL_CANONICAL),
        "dry_run": True,
        "would_write": 0,
    }
    return report


async def apply_backfill(company_id: str) -> Dict[str, Any]:
    """R1.3 — bloqueado até autorização CEO."""
    raise SystemExit(
        "R1.3 (--apply) NÃO autorizado ainda.\n"
        "Critério CEO: somente após leitura do relatório dry-run."
    )


async def main():
    parser = argparse.ArgumentParser(description="Valuation Backfill")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--company", default="co-demo")
    parser.add_argument("--output-dir", default="/app/memory")
    args = parser.parse_args()

    if args.apply and not args.dry_run:
        await apply_backfill(args.company)
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
