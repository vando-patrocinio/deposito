"""Onda C — Ajuste 1 · GATE DE ENTRADA DA SPRINT 5.

Reconciliação read-only entre as 4 fontes de verdade do patrimônio:
  • smartolt_onus       — fonte autoritativa da rede (OLT)
  • stok_onts           — pipeline novo de patrimônio
  • subscribers         — clientes (com pppoe_user/plano)
  • stok_onts location_type=defeito — ONTs marcadas defeituosas

Calcula Δ% e lista divergências. Gate: Δ ≥ 2% em qualquer par ⇒ Sprint 5
obrigatória.

Saída: /app/memory/SMARTOLT_RECONCILIATION_<YYYY-MM-DD>.md
ZERO writes em qualquer collection.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, "/app/backend")
for _ln in open("/app/backend/.env"):
    if "=" in _ln and not _ln.startswith("#"):
        _k, _v = _ln.strip().split("=", 1)
        os.environ.setdefault(_k, _v.strip('"'))

from database import db  # noqa: E402

DEFAULT_OUT = "/app/memory"


def _norm_id(v: str | None) -> str | None:
    if not v:
        return None
    return "".join(c for c in v.lower() if c.isalnum())


async def _smartolt_set(cid: str) -> Dict[str, Any]:
    """Coleta IDs únicos (mac/sn) das ONUs SmartOLT da empresa."""
    macs: set[str] = set()
    sns: set[str] = set()
    by_status: Dict[str, int] = defaultdict(int)
    cur = db.smartolt_onus.find(
        {"company_id": cid},
        {"_id": 0, "mac": 1, "sn": 1, "status": 1,
         "administrative_status": 1},
    )
    async for d in cur:
        m = _norm_id(d.get("mac"))
        s = _norm_id(d.get("sn"))
        if m:
            macs.add(m)
        if s:
            sns.add(s)
        st = (d.get("status") or d.get("administrative_status") or "unknown").lower()
        by_status[st] += 1
    return {"macs": macs, "sns": sns, "by_status": dict(by_status)}


async def _estoque_set(cid: str) -> Dict[str, Any]:
    """Coleta IDs únicos do stok_onts + breakdown por location_type."""
    macs: set[str] = set()
    sns: set[str] = set()
    by_location: Dict[str, int] = defaultdict(int)
    defective = 0
    no_location = 0
    cur = db.stok_onts.find(
        {"company_id": cid},
        {"_id": 0, "mac": 1, "sn": 1, "location_type": 1,
         "location_id": 1, "is_defective": 1},
    )
    async for d in cur:
        m = _norm_id(d.get("mac"))
        s = _norm_id(d.get("sn"))
        if m:
            macs.add(m)
        if s:
            sns.add(s)
        lt = d.get("location_type") or "sem_location_type"
        by_location[lt] += 1
        if d.get("is_defective"):
            defective += 1
        if not d.get("location_id"):
            no_location += 1
    return {
        "macs": macs, "sns": sns,
        "by_location": dict(by_location),
        "defective": defective,
        "no_location": no_location,
    }


async def _subscribers_set(cid: str) -> Dict[str, Any]:
    """Subscribers ativos: clientes que deveriam ter ONT em produção."""
    active = await db.subscribers.count_documents({
        "company_id": cid,
        "status": {"$regex": "^(ativ|activ)", "$options": "i"},
    })
    total = await db.subscribers.count_documents({"company_id": cid})
    return {"active": active, "total": total}


def _delta_pct(a: int, b: int) -> float:
    if a == 0 and b == 0:
        return 0.0
    if a == 0 or b == 0:
        return 100.0
    return round(abs(a - b) / max(a, b) * 100, 1)


def _classify(delta_pct: float) -> str:
    if delta_pct < 2:
        return "✅ ok (Sprint 5 pequena)"
    if delta_pct < 10:
        return "🟡 alerta (Sprint 5 média)"
    if delta_pct < 30:
        return "🟠 grave (Sprint 5 grande)"
    return "🚨 crítico (Sprint 5 fundacional)"


async def reconcile(cid: str) -> Dict[str, Any]:
    smartolt = await _smartolt_set(cid)
    estoque = await _estoque_set(cid)
    subs = await _subscribers_set(cid)
    # Universo combinado (mac ∪ sn)
    smartolt_ids = smartolt["macs"] | smartolt["sns"]
    estoque_ids = estoque["macs"] | estoque["sns"]
    intersect = smartolt_ids & estoque_ids
    smartolt_only = smartolt_ids - estoque_ids
    estoque_only = estoque_ids - smartolt_ids
    return {
        "company_id": cid,
        "smartolt_count": len(smartolt_ids),
        "smartolt_by_status": smartolt["by_status"],
        "estoque_count": len(estoque_ids),
        "estoque_by_location": estoque["by_location"],
        "estoque_defective": estoque["defective"],
        "estoque_no_location": estoque["no_location"],
        "subscribers_active": subs["active"],
        "subscribers_total": subs["total"],
        "intersect_count": len(intersect),
        "smartolt_only_count": len(smartolt_only),
        "estoque_only_count": len(estoque_only),
        "smartolt_only_sample": list(smartolt_only)[:30],
        "estoque_only_sample": list(estoque_only)[:30],
        "delta_pct_estoque_vs_smartolt": _delta_pct(
            len(estoque_ids), len(smartolt_ids)),
        "delta_pct_estoque_vs_subs_active": _delta_pct(
            len(estoque_ids), subs["active"]),
    }


def _format_report(rec: Dict[str, Any]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    delta_smartolt = rec["delta_pct_estoque_vs_smartolt"]
    delta_subs = rec["delta_pct_estoque_vs_subs_active"]
    veredito = _classify(max(delta_smartolt, delta_subs))
    out: List[str] = []
    out.append("# RECONCILIAÇÃO SMARTOLT × ESTOQUE × SUBSCRIBERS")
    out.append(f"\n**Empresa**: `{rec['company_id']}` · **Gerado**: {now}")
    out.append(f"**Modo**: READ-ONLY (gate de entrada da Sprint 5).\n")
    out.append("## 🎯 Veredito\n")
    out.append(f"### Δ Estoque vs SmartOLT: **{delta_smartolt}%** → {veredito}")
    out.append(f"### Δ Estoque vs Subscribers ativos: **{delta_subs}%**\n")
    out.append("## 📊 Quantidade por fonte\n")
    out.append("| Fonte                                    | Quantidade |")
    out.append("|------------------------------------------|-----------:|")
    out.append(f"| **SmartOLT** (ONUs registradas)          | {rec['smartolt_count']:,} |".replace(",", "."))
    out.append(f"| **stok_onts** (pipeline novo)            | {rec['estoque_count']:,} |".replace(",", "."))
    out.append(f"| **subscribers** ativos                   | {rec['subscribers_active']:,} |".replace(",", "."))
    out.append(f"| **subscribers** total                    | {rec['subscribers_total']:,} |".replace(",", "."))
    out.append(f"| **estoque** defeituosas                  | {rec['estoque_defective']:,} |".replace(",", "."))
    out.append(f"| **estoque** sem `location_id`            | {rec['estoque_no_location']:,} |".replace(",", "."))
    out.append("")
    # SmartOLT status breakdown
    out.append("### SmartOLT por status")
    out.append("")
    out.append("| Status        | Quantidade |")
    out.append("|---------------|-----------:|")
    for st, n in sorted(rec["smartolt_by_status"].items(),
                         key=lambda x: -x[1]):
        out.append(f"| {st} | {n:,} |".replace(",", "."))
    out.append("")
    # Estoque por location
    out.append("### Estoque por location_type")
    out.append("")
    out.append("| Location | Quantidade |")
    out.append("|----------|-----------:|")
    for lt, n in sorted(rec["estoque_by_location"].items(),
                         key=lambda x: -x[1]):
        out.append(f"| {lt} | {n:,} |".replace(",", "."))
    out.append("")
    out.append("## 🔍 Divergências\n")
    out.append("| Divergência                          | Quantidade |")
    out.append("|--------------------------------------|-----------:|")
    out.append(f"| Em **AMBOS** (intersect)             | {rec['intersect_count']:,} |".replace(",", "."))
    out.append(f"| **SmartOLT sem Estoque** (∖)         | {rec['smartolt_only_count']:,} |".replace(",", "."))
    out.append(f"| **Estoque sem SmartOLT** (∖)         | {rec['estoque_only_count']:,} |".replace(",", "."))
    out.append("")
    if rec["smartolt_only_count"] > 0:
        out.append("### Amostra · SmartOLT sem Estoque (até 30)")
        out.append("")
        for x in rec["smartolt_only_sample"]:
            out.append(f"- `{x}`")
        out.append("")
    if rec["estoque_only_count"] > 0:
        out.append("### Amostra · Estoque sem SmartOLT (até 30)")
        out.append("")
        for x in rec["estoque_only_sample"]:
            out.append(f"- `{x}`")
        out.append("")
    out.append("## 🛠️ Critério de entrada na Sprint 5\n")
    out.append("- Δ < 2%   → Sprint 5 pequena (ajustes finos)")
    out.append("- Δ 2-10%  → Sprint 5 média (lotes de reconciliação)")
    out.append("- Δ 10-30% → Sprint 5 grande (revisão estrutural)")
    out.append("- Δ ≥ 30%  → **Sprint 5 fundacional** (parar tudo e migrar)\n")
    out.append("## 📋 Próximos passos sugeridos\n")
    if delta_smartolt >= 30:
        out.append("1. 🚨 **CRÍTICO**: importar em batch todas as ONUs do SmartOLT em `stok_onts` com `synthetic_origin=true` e `location_type=cliente` quando bater com pppoe.")
        out.append("2. 🚨 Sprint 5 deve começar pelo `bulk_import_smartolt_to_stok` antes de qualquer normalização.")
        out.append("3. ⚠️ Não migrar `owner_type/owner_id` enquanto o pipeline não tiver 95%+ das ONUs reais.")
    elif delta_smartolt >= 10:
        out.append("1. 🟠 Sprint 5 deve ter fase 0: `reconcile_smartolt_to_stok` em lotes de 100/dia.")
        out.append("2. Mapeamento pppoe_user → subscriber_id → owner.")
    elif delta_smartolt >= 2:
        out.append("1. 🟡 Sprint 5 média — focar em normalização de `owner_type/location_type`.")
    else:
        out.append("1. ✅ Sprint 5 pequena — apenas normalização de schema.")
    out.append("\n## 🔒 Trilha\n")
    out.append("- Script: `/app/backend/scripts/audit_smartolt_vs_estoque.py`")
    out.append("- Modo: READ-ONLY (zero writes confirmado).")
    out.append("- Próxima execução: 1x por semana até a Sprint 5 começar; depois 1x/mês.")
    return "\n".join(out) + "\n"


async def main():
    ap = argparse.ArgumentParser(description="Ajuste 1 — Reconciliação")
    ap.add_argument("--company-id", default="co-demo")
    ap.add_argument("--output-dir", default=DEFAULT_OUT)
    ap.add_argument("--print-only", action="store_true")
    args = ap.parse_args()

    rec = await reconcile(args.company_id)

    md = _format_report(rec)
    if args.print_only:
        print(md)
    else:
        ymd = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = Path(args.output_dir) / f"SMARTOLT_RECONCILIATION_{ymd}.md"
        path.write_text(md, encoding="utf-8")
        print(f"✅ Relatório salvo em: {path}")

    # Resumo curto stdout
    print()
    print("=" * 60)
    print(f"  SmartOLT: {rec['smartolt_count']:,}   Estoque: {rec['estoque_count']:,}".replace(",", "."))
    print(f"  Δ vs SmartOLT:    {rec['delta_pct_estoque_vs_smartolt']}%")
    print(f"  Δ vs Subs ativos: {rec['delta_pct_estoque_vs_subs_active']}%")
    print(f"  Veredito: {_classify(rec['delta_pct_estoque_vs_smartolt'])}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
