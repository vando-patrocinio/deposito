"""IA Patrimonial · Shadow Run · Onda IA-1.

Roda em OS finalizadas dos últimos N dias. Para cada uma:
  • Extrai materiais via IA (Claude Sonnet 4.5 + regex catálogo)
  • Compara com o que o técnico digitou no formulário
  • Gera estatísticas: match perfeito / só formulário / só IA / divergência

Saída: /app/memory/IA_PATRIMONIAL_SHADOW_REPORT_<data>.md
Modo: READ-ONLY (zero writes).

Uso:
  python /app/backend/scripts/ia_patrimonial_shadow.py --company-id co-demo --days 14 --limit 30
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, "/app/backend")
for _ln in open("/app/backend/.env"):
    if "=" in _ln and not _ln.startswith("#"):
        _k, _v = _ln.strip().split("=", 1)
        os.environ.setdefault(_k, _v.strip('"'))

from database import db  # noqa: E402
from services.ia_patrimonial_extractor import (  # noqa: E402
    extract_from_narrative, compare_ia_vs_form,
)

OUT_DIR = Path("/app/memory")


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


async def run(cid: str, days: int, limit: int, use_llm: bool) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cursor = db.tickets.find({
        "company_id": cid,
        "status": {"$in": ["finalizada", "encerrada"]},
        "closed_at": {"$gte": cutoff},
    }, {"_id": 0}).sort("closed_at", -1).limit(limit)
    tickets: List[Dict[str, Any]] = await cursor.to_list(limit)
    print("\n══ IA Patrimonial · Shadow Run ══")
    print(f"  Empresa : {cid}")
    print(f"  Janela  : {days}d · Limite: {limit}")
    print(f"  Tickets : {len(tickets)}")
    print(f"  LLM     : {'ON' if use_llm else 'OFF (regex only)'}\n")

    stats = defaultdict(int)
    per_service: Dict[str, Dict[str, int]] = defaultdict(
        lambda: defaultdict(int))
    rows: List[Dict[str, Any]] = []
    cost_estimate_calls = 0

    for i, t in enumerate(tickets, 1):
        cd = t.get("completion_data") or {}
        narrative = (cd.get("descricao") or cd.get("observacao")
                      or t.get("description") or "")
        if not narrative.strip():
            stats["empty_narrative"] += 1
            continue
        try:
            ia = await extract_from_narrative(
                narrative, ticket_type_hint=t.get("type"), use_llm=use_llm)
            if use_llm:
                cost_estimate_calls += 1
        except Exception as e:  # noqa: BLE001
            stats["extract_error"] += 1
            rows.append({"ticket_id": t["id"], "err": str(e)})
            continue
        cmp = compare_ia_vs_form(ia, cd)
        stats["processed"] += 1
        stats["perfect_match"] += cmp["perfect_match"]
        stats["only_form"] += cmp["only_form"]
        stats["only_ia"] += cmp["only_ia"]
        stats["qty_mismatch"] += cmp["qty_mismatch"]
        st = ia.get("service_type") or "?"
        per_service[st]["count"] += 1
        per_service[st]["materials_detected"] += len(
            ia.get("materials_detected") or [])
        rows.append({
            "ticket_id": t["id"], "type": t.get("type"),
            "ia_service": ia.get("service_type"),
            "narrative": narrative[:120].replace("\n", " "),
            "ia_materials": ia.get("materials_detected") or [],
            "form_summary": {k: cd.get(k) for k in (
                "qtd_drop", "conectores_fast", "esticadores",
                "cabo_rede", "conectores_rede") if cd.get(k)},
            "comparison": cmp,
            "ont_new_sn": ia.get("ont_new_sn"),
            "ont_old_sn": ia.get("ont_old_sn"),
            "defect": ia.get("has_defect_signal"),
            "method": ia.get("method"),
            "warnings": ia.get("warnings"),
        })
        if i % 5 == 0:
            print(f"  ⏵ {i}/{len(tickets)} processado")

    # ── REPORT ───────────────────────────────────────────────────────
    out: List[str] = []
    out.append("# IA PATRIMONIAL · SHADOW RUN · Onda IA-1")
    out.append("")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out.append(f"**Empresa**: `{cid}` · **Gerado**: {now}")
    out.append(f"**Janela**: {days}d · **Limite**: {limit} · **Modo**: "
                f"{'IA Claude + regex' if use_llm else 'regex only'}")
    out.append("**Mandato CEO**: shadow primeiro · zero writes · zero migração")
    out.append("")
    out.append("## 1. RESUMO")
    out.append("")
    tot_proc = stats.get("processed", 0)
    out.append(f"- Tickets escaneados: **{_fmt(len(tickets))}**")
    out.append(f"- Processados com sucesso: **{_fmt(tot_proc)}**")
    out.append(f"- Narrativas vazias: **{_fmt(stats.get('empty_narrative', 0))}**")
    out.append(f"- Erros de extração: **{_fmt(stats.get('extract_error', 0))}**")
    out.append(f"- Chamadas Claude: **{_fmt(cost_estimate_calls)}** "
                f"(≈ ${cost_estimate_calls*0.003:.3f} USD a 3 milicent/chamada)")
    out.append("")
    out.append("## 2. CONCORDÂNCIA IA × FORMULÁRIO (por item)")
    out.append("")
    out.append("| Categoria              |   Qtd | % | Significado |")
    out.append("|------------------------|------:|--:|-------------|")
    tot_items = (stats["perfect_match"] + stats["only_form"]
                  + stats["only_ia"] + stats["qty_mismatch"]) or 1
    def _pct(n):
        return f"{round(n/tot_items*100, 1)}%"
    out.append(f"| ✅ Match perfeito        | {_fmt(stats['perfect_match'])} | {_pct(stats['perfect_match'])} | IA bateu com formulário |")
    out.append(f"| 📋 Só no formulário     | {_fmt(stats['only_form'])} | {_pct(stats['only_form'])} | Técnico digitou, IA não pegou |")
    out.append(f"| 🤖 Só na IA             | {_fmt(stats['only_ia'])} | {_pct(stats['only_ia'])} | IA pegou, técnico não digitou |")
    out.append(f"| ⚠️  Quantidade diferente | {_fmt(stats['qty_mismatch'])} | {_pct(stats['qty_mismatch'])} | Mesmo item, qtd diferente |")
    out.append("")
    confianca = round(stats["perfect_match"] / tot_items * 100, 1) \
        if tot_items > 0 else 0.0
    if confianca >= 80:
        tier = "🟢 PRONTA para Onda IA-2 (UI confirmação)"
    elif confianca >= 60:
        tier = "🟡 PROMISSORA — refinar catálogo de aliases antes de Onda IA-2"
    elif confianca >= 40:
        tier = "🟠 ATENÇÃO — IA + form complementares; revisar regras"
    else:
        tier = "🔴 BAIXA — dataset insuficiente OU formulário pouco preenchido"
    out.append(f"### Veredito: **{tier}** (match perfeito = {confianca}%)")
    out.append("")
    out.append("## 3. DETECÇÃO POR TIPO DE SERVIÇO")
    out.append("")
    out.append("| Tipo IA      | OS | Materiais Detectados (Σ) |")
    out.append("|--------------|---:|-------------------------:|")
    for st_name, stats_st in sorted(per_service.items(),
                                       key=lambda x: -x[1]["count"]):
        out.append(f"| {st_name} | {_fmt(stats_st['count'])} | {_fmt(stats_st['materials_detected'])} |")
    out.append("")
    out.append("## 4. AMOSTRA DE 10 OS PROCESSADAS")
    out.append("")
    for r in rows[:10]:
        if r.get("err"):
            out.append(f"### ❌ {r['ticket_id']} — erro: {r['err']}")
            continue
        out.append(f"### `{r['ticket_id']}` · tipo={r['type']} → IA={r['ia_service']}")
        out.append("")
        out.append(f"**Relato**: _{r['narrative']}…_")
        out.append("")
        if r["ia_materials"]:
            out.append("**IA detectou**:")
            for m in r["ia_materials"]:
                out.append(f"- {m['qty']} {m['unit']} de **{m['item']}** "
                           f"(conf {m['confidence']:.2f}, via {m['source']})")
        if r["form_summary"]:
            out.append("")
            out.append(f"**Formulário**: `{r['form_summary']}`")
        if r["ont_new_sn"] or r["ont_old_sn"]:
            out.append(f"**SN detectados**: novo=`{r['ont_new_sn']}` antigo=`{r['ont_old_sn']}`")
        if r["defect"] is not None:
            out.append(f"**Defeito sinalizado?**: `{r['defect']}`")
        out.append(f"**Verdict comparação**: {r['comparison']['perfect_match']} ✅ · "
                   f"{r['comparison']['only_form']} 📋 · "
                   f"{r['comparison']['only_ia']} 🤖 · "
                   f"{r['comparison']['qty_mismatch']} ⚠️")
        out.append("")
    out.append("## 5. PRÓXIMOS PASSOS")
    out.append("")
    if confianca >= 60:
        out.append("- ✅ Onda IA-2 pode ser implementada (tela 'Confirma leitura' na Lousa Mobile)")
        out.append("- 🔧 Ajustar catálogo de aliases para reduzir 'Só no formulário'")
    else:
        out.append("- 🟠 Aumentar amostra (rodar com `--days 30` e mais limit)")
        out.append("- 🔧 Refinar regex e adicionar mais sinônimos no catálogo")
        out.append("- ⏳ Não destravar Onda IA-2 ainda")
    out.append("")
    out.append("---")
    out.append("_Engine: `services/ia_patrimonial_extractor.py` · "
                "Modelo: claude-sonnet-4-5-20250929 · Modo: shadow read-only_")

    path = OUT_DIR / (
        f"IA_PATRIMONIAL_SHADOW_REPORT_"
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print()
    print(f"✓ Relatório salvo em: {path}")
    print(f"✓ Confiança IA × formulário: {confianca}%")
    print(f"✓ Veredito: {tier}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--company-id", default="co-demo")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--no-llm", action="store_true",
                       help="Desabilita Claude (só regex)")
    args = ap.parse_args()
    await run(args.company_id, args.days, args.limit,
                use_llm=not args.no_llm)


if __name__ == "__main__":
    asyncio.run(main())
