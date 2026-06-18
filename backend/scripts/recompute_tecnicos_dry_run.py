"""Onda C P0.2 — Recompute dry-run dos técnicos com saldo negativo.

READ-ONLY. Reconstrói o saldo esperado de cada técnico a partir de:

  ENTRADAS conhecidas:
    • stok_transfer_audit  → transferências da empresa pro técnico.
    • stok_history (type=transfer_in OR tag=reposicao*) → adiabáticas legadas.

  SAÍDAS conhecidas:
    • tickets.completion_data.* nos tickets atribuídos ao técnico que estão
      em estados terminais (finalizada, encerrada, resolvida_*).

  Comparação:
    saldo_calc(cons) = sum(entradas) - sum(saídas)
    diferenca       = saldo_atual - saldo_calc

  Diferença > 0  → técnico está com ESTOQUE FANTASMA (mais do que deveria).
  Diferença = 0  → consistente.
  Diferença < 0  → técnico está com DÉFICIT NÃO REGISTRADO (consumiu além
                    do rastreável; pode ser legado pré-Onda A).

Modos:
  --dry-run (default): apenas imprime e/ou escreve markdown.
  --output PATH      : caminho do markdown (default
                        /app/memory/TECNICOS_NEGATIVOS_DIFF.md).

ZERO writes em qualquer collection. Estritamente diagnóstico.
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
from routes.stok import CONSUMABLE_IDS, CONSUMABLE_BY_ID  # noqa: E402

OUTPUT_DEFAULT = "/app/memory/TECNICOS_NEGATIVOS_DIFF.md"

# Mapa consumable_id → key em completion_data (quando diferente)
# A maioria é igual ao próprio id (qtd_drop é diferente).
COMP_KEY_MAP = {
    "drop": "qtd_drop",
    "esticador": "esticadores",
    "conectores_fast": "conectores_fast",
    "cabo_rede": "cabo_rede",
    "conectores_rede": "conectores_rede",
    "conector_externo": "conector_externo",
    "conector_interno": "conector_interno",
}

# Técnicos identificados no audit (Onda C P1)
TARGET_TECHS = [
    {"id": "col-30aafc3c", "company_id": "co-demo"},
    {"id": "col-b4db2145", "company_id": "co-demo"},
]


async def _get_tech_info(tid: str) -> Dict[str, Any]:
    return await db.collaborators.find_one(
        {"id": tid}, {"_id": 0, "id": 1, "name": 1, "cargo": 1, "company_id": 1}
    ) or {"id": tid, "name": "(desconhecido)"}


async def _get_stock(cid: str, location: str) -> Dict[str, Any]:
    s = await db.stok_stock.find_one(
        {"company_id": cid, "location": location}, {"_id": 0})
    return s or {}


async def _sum_transfers_in(cid: str, tid: str) -> Dict[str, int]:
    """Entradas via stok_transfer_audit (Onda A)."""
    out: Dict[str, int] = defaultdict(int)
    async for t in db.stok_transfer_audit.find(
        {"company_id": cid, "technician_id": tid},
        {"_id": 0, "consumable_id": 1, "quantity_transferred": 1},
    ):
        cons = t.get("consumable_id")
        qty = t.get("quantity_transferred") or 0
        if cons in CONSUMABLE_IDS:
            out[cons] += int(qty)
    return dict(out)


async def _sum_consumption(cid: str, tid: str) -> Dict[str, int]:
    """Saídas via completion_data dos tickets atribuídos ao técnico em
    estados terminais."""
    out: Dict[str, int] = defaultdict(int)
    terminal_states = ["finalizada", "encerrada",
                       "resolvida_sucesso", "resolvida_sem_execucao"]
    async for t in db.tickets.find(
        {"company_id": cid, "assigned_collaborator_id": tid,
         "status": {"$in": terminal_states}},
        {"_id": 0, "completion_data": 1, "status": 1, "id": 1},
    ):
        cd = t.get("completion_data") or {}
        if not isinstance(cd, dict):
            continue
        for cons_id in CONSUMABLE_IDS:
            comp_key = COMP_KEY_MAP.get(cons_id, cons_id)
            v = cd.get(comp_key)
            if isinstance(v, (int, float)) and v:
                # consumo positivo = saída do técnico
                out[cons_id] += int(v)
    return dict(out)


async def _service_status_breakdown(cid: str, tid: str) -> Dict[str, int]:
    """Para contexto: quantos stok_services por status este técnico tem."""
    pipe = [
        {"$match": {"company_id": cid, "technician_id": tid}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ]
    out: Dict[str, int] = {}
    async for r in db.stok_services.aggregate(pipe):
        out[r["_id"]] = int(r["n"])
    return out


async def _ticket_status_breakdown(cid: str, tid: str) -> Dict[str, int]:
    pipe = [
        {"$match": {"company_id": cid, "assigned_collaborator_id": tid}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ]
    out: Dict[str, int] = {}
    async for r in db.tickets.aggregate(pipe):
        out[r["_id"]] = int(r["n"])
    return out


async def _audit_tech(cid: str, tid: str) -> Dict[str, Any]:
    info = await _get_tech_info(tid)
    stock = await _get_stock(cid, tid)
    entradas = await _sum_transfers_in(cid, tid)
    saidas = await _sum_consumption(cid, tid)
    svc_status = await _service_status_breakdown(cid, tid)
    tkt_status = await _ticket_status_breakdown(cid, tid)

    # Calcula saldo esperado a partir do histórico rastreável
    rows: List[Dict[str, Any]] = []
    all_cons = sorted(set(CONSUMABLE_IDS) |
                       set(entradas.keys()) | set(saidas.keys()) |
                       {k for k in stock.keys() if k in CONSUMABLE_IDS})
    for cons in all_cons:
        atual = stock.get(cons)
        # Trata atual None como "sem registro" (= 0 implícito)
        atual_v = int(atual) if isinstance(atual, (int, float)) else 0
        e = entradas.get(cons, 0)
        s = saidas.get(cons, 0)
        calc = e - s
        diff = atual_v - calc
        # Filtra linhas onde tudo é zero (irrelevante)
        if atual_v == 0 and e == 0 and s == 0:
            continue
        rows.append({
            "consumable_id": cons,
            "consumable_name": (CONSUMABLE_BY_ID.get(cons) or {}).get(
                "name", cons),
            "atual": atual_v,
            "atual_raw": atual,  # mostra None vs 0
            "entradas": e,
            "saidas": s,
            "calculado": calc,
            "diferenca": diff,
        })
    return {
        "tech_id": tid,
        "tech_name": info.get("name"),
        "company_id": cid,
        "stock_doc_present": bool(stock),
        "rows": rows,
        "service_status_breakdown": svc_status,
        "ticket_status_breakdown": tkt_status,
        "raw_stock": {k: stock.get(k) for k in CONSUMABLE_IDS if k in stock},
    }


def _md_table(headers: List[str], rows: List[List[Any]]) -> str:
    align = []
    for h in headers:
        align.append("---:" if "Δ" in h or "atual" in h.lower()
                     or "calc" in h.lower() or "ent" in h.lower()
                     or "saí" in h.lower() else "---")
    out = ["| " + " | ".join(headers) + " |"]
    out.append("| " + " | ".join(align) + " |")
    for r in rows:
        out.append("| " + " | ".join(
            str(c) if c is not None else "—" for c in r) + " |")
    return "\n".join(out)


def _classify_diff(diff: int, atual: int) -> str:
    if diff == 0:
        return "✅ consistente"
    if atual < 0 and diff < 0:
        return "🔴 déficit não-registrado (legado)"
    if atual < 0 and diff >= 0:
        return "🟡 negativo histórico (rastreável)"
    if diff > 0:
        return "🟠 estoque fantasma (mais do que deveria)"
    return "🟡 inconsistente"


def _format_report(results: List[Dict[str, Any]]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out: List[str] = []
    out.append("# TÉCNICOS COM SALDO NEGATIVO — DRY-RUN DIFF (Onda C P0.2)")
    out.append("")
    out.append(f"> Gerado em: **{now}** · Modo: **DRY-RUN** (zero writes)")
    out.append("> Script: `/app/backend/scripts/recompute_tecnicos_dry_run.py`")
    out.append("> Origem: Auditoria Praça x Técnico (Onda C P1).")
    out.append("")
    out.append("## Metodologia")
    out.append("")
    out.append("```")
    out.append("  Entradas  = SUM(stok_transfer_audit.quantity_transferred)")
    out.append("  Saídas    = SUM(tickets.completion_data por técnico)")
    out.append("              em status terminais (finalizada/encerrada/resolvida_*)")
    out.append("  Calculado = Entradas - Saídas")
    out.append("  Diferença = Atual - Calculado")
    out.append("```")
    out.append("")
    out.append("**Interpretação da diferença:**")
    out.append("- ✅ `diff = 0` → saldo bate com histórico rastreável.")
    out.append("- 🔴 `atual < 0 e diff < 0` → técnico consumiu além do rastreado (legado pré-Onda A; tickets antigos sem `completion_data` ou movimentações pré-audit).")
    out.append("- 🟡 `atual < 0 e diff ≥ 0` → negativo veio do histórico rastreado (consumo > transferências).")
    out.append("- 🟠 `diff > 0` → estoque fantasma (técnico tem mais do que histórico justifica).")
    out.append("")
    for r in results:
        out.append("---")
        out.append("")
        out.append(f"## 👤 {r['tech_name']} (`{r['tech_id']}`)")
        out.append("")
        out.append(f"- Empresa: `{r['company_id']}`")
        out.append(f"- Documento stok_stock: {'presente' if r['stock_doc_present'] else '⚠️ AUSENTE'}")
        out.append(f"- Tickets por status: `{r['ticket_status_breakdown']}`")
        out.append(f"- Stok_services por status: `{r['service_status_breakdown']}`")
        out.append("")
        out.append("### Diff por consumível")
        out.append("")
        rows = []
        for row in r["rows"]:
            classif = _classify_diff(row["diferenca"], row["atual"])
            rows.append([
                row["consumable_name"],
                row["atual_raw"] if row["atual_raw"] is not None else "—",
                f"+{row['entradas']}" if row["entradas"] else 0,
                f"-{row['saidas']}" if row["saidas"] else 0,
                row["calculado"],
                f"{row['diferenca']:+d}" if row["diferenca"] else 0,
                classif,
            ])
        out.append(_md_table(
            ["Consumível", "Atual", "Entradas", "Saídas",
             "Calculado", "Δ Diferença", "Classificação"],
            rows,
        ))
        out.append("")

    # Resumo executivo final
    out.append("---")
    out.append("")
    out.append("## 📋 Resumo executivo")
    out.append("")
    total_deficit_legado = total_neg_rastreavel = total_fantasma = total_ok = 0
    for r in results:
        for row in r["rows"]:
            c = _classify_diff(row["diferenca"], row["atual"])
            if "✅" in c: total_ok += 1
            elif "🔴" in c: total_deficit_legado += 1
            elif "🟡" in c: total_neg_rastreavel += 1
            elif "🟠" in c: total_fantasma += 1
    out.append(_md_table(
        ["Categoria", "Quantidade"],
        [
            ["✅ Consistente (diff=0)", total_ok],
            ["🔴 Déficit não-registrado (legado pré-Onda A)", total_deficit_legado],
            ["🟡 Negativo rastreável (consumo > entradas)", total_neg_rastreavel],
            ["🟠 Estoque fantasma (atual > calculado)", total_fantasma],
        ],
    ))
    out.append("")
    out.append("## 🩹 Recomendações de correção (sem executar)")
    out.append("")
    out.append("Para cada linha 🔴 / 🟡 / 🟠:")
    out.append("")
    out.append("1. **Não deletar** nenhum stok_services nem stok_stock. Sempre $set/$inc auditável.")
    out.append("2. **Negativos rastreáveis (🟡)** podem ser zerados via reposição admin com tag `recompute_p0_2_20260618` (similar à Onda A reposicao mode).")
    out.append("3. **Déficits legados (🔴)** exigem decisão CEO: aceitar como histórico (zerar com tag `legacy_orphan_consumption`) OU investigar caso-a-caso.")
    out.append("4. **Estoque fantasma (🟠)** exige investigação: pode indicar transferências sem audit ou entradas duplicadas.")
    out.append("")
    out.append("> ⚠️ NADA será executado automaticamente. Este documento é apenas evidência para decisão.")
    out.append("")
    return "\n".join(out) + "\n"


def _print_short(results):
    """Resumo curto pro CEO ver no terminal."""
    print()
    print("=" * 72)
    print("  TÉCNICOS NEGATIVOS — DRY-RUN DIFF (READ-ONLY)")
    print("=" * 72)
    for r in results:
        print(f"\n  👤 {r['tech_name']} ({r['tech_id']})")
        print("  ┌─────────────────────┬───────┬─────────┬────────┬─────────┬──────────┐")
        print("  │ Consumível          │ Atual │ Entrada │ Saída  │  Calc   │   Δ Diff │")
        print("  ├─────────────────────┼───────┼─────────┼────────┼─────────┼──────────┤")
        for row in r["rows"]:
            print(f"  │ {row['consumable_name']:<19} │ {str(row['atual_raw'] if row['atual_raw'] is not None else '—'):>5} │"
                  f" {('+' + str(row['entradas'])) if row['entradas'] else '0':>7} │"
                  f" {('-' + str(row['saidas'])) if row['saidas'] else '0':>6} │"
                  f" {row['calculado']:>7} │ {row['diferenca']:>+8} │")
        print("  └─────────────────────┴───────┴─────────┴────────┴─────────┴──────────┘")
    print()


async def main():
    ap = argparse.ArgumentParser(description="P0.2 Recompute dry-run")
    ap.add_argument("--output", default=OUTPUT_DEFAULT,
                    help="Caminho do markdown")
    ap.add_argument("--print-only", action="store_true",
                    help="Não escreve arquivo")
    args = ap.parse_args()

    results: List[Dict[str, Any]] = []
    for t in TARGET_TECHS:
        try:
            results.append(await _audit_tech(t["company_id"], t["id"]))
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  Falha auditando {t['id']}: {e}")

    _print_short(results)

    if not args.print_only:
        md = _format_report(results)
        Path(args.output).write_text(md, encoding="utf-8")
        print(f"✅ Diff salvo em: {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
