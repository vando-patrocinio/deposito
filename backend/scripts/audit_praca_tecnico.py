"""Onda C P1 — Auditoria Praça x Técnico (READ-ONLY).

Mapeia o estado atual do estoque (`stok_stock`, `stok_onts`, `stok_services`)
sem alterar NADA no banco. Identifica:

  • Saldos negativos por consumível e localização.
  • Documentos duplicados (mesma location apontando para >1 documento).
  • Praças misturadas com técnicos (mesmo location_id usado pra ambos).
  • ONTs órfãs (location_id sem collaborator nem praça correspondente).
  • Serviços ativos sem técnico atribuído.
  • Itens defeituosos/descartados sem auditoria.
  • Stok_services órfãs (status `orfa_sem_ticket` — devem existir só pós-Onda A).

Saída: `/app/memory/PRAÇA_TECNICO_AUDIT.md` (executável: append-friendly).

Uso: `python3 /app/backend/scripts/audit_praca_tecnico.py [--company-id X]`

Regra de ouro: ZERO write em qualquer collection. Apenas reads.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, "/app/backend")
for _ln in open("/app/backend/.env"):
    if "=" in _ln and not _ln.startswith("#"):
        _k, _v = _ln.strip().split("=", 1)
        os.environ.setdefault(_k, _v.strip('"'))

from database import db  # noqa: E402
from routes.stok import CONSUMABLE_IDS, CONSUMABLE_BY_ID  # noqa: E402

OUTPUT_PATH = Path("/app/memory/PRAÇA_TECNICO_AUDIT.md")


def _is_praca_location(loc: str) -> bool:
    return isinstance(loc, str) and loc.startswith("praca:")


async def _collect_companies() -> List[str]:
    cur = db.companies.find({}, {"_id": 0, "id": 1, "name": 1})
    out = []
    async for c in cur:
        out.append(c.get("id"))
    return [c for c in out if c]


async def _audit_company(cid: str) -> Dict[str, Any]:
    """Coleta estado read-only para 1 empresa."""
    # ─── Collaborators (técnicos) ──────────────────────────────────────────
    techs = await db.collaborators.find(
        {"company_id": cid, "atlaz_inbox": {"$ne": True}},
        {"_id": 0, "id": 1, "name": 1, "role": 1, "cargo": 1, "active": 1},
    ).to_list(2000)
    tech_ids = {t["id"]: t for t in techs}

    # ─── Praças ───────────────────────────────────────────────────────────
    pracas = await db.pracas.find(
        {"company_id": cid}, {"_id": 0, "id": 1, "name": 1},
    ).to_list(500)
    praca_ids = {p["id"]: p for p in pracas}

    # ─── stok_stock ───────────────────────────────────────────────────────
    stocks = await db.stok_stock.find(
        {"company_id": cid}, {"_id": 0},
    ).to_list(5000)

    # ─── stok_onts ────────────────────────────────────────────────────────
    onts = await db.stok_onts.find(
        {"company_id": cid},
        {"_id": 0, "id": 1, "mac": 1, "sn": 1, "model": 1,
         "location_type": 1, "location_id": 1, "status": 1,
         "is_defective": 1, "defective_reason": 1},
    ).to_list(20000)

    # ─── stok_services (ativas + órfãs) ───────────────────────────────────
    services = await db.stok_services.find(
        {"company_id": cid, "status": {"$in": ["ativo", "orfa_sem_ticket"]}},
        {"_id": 0, "id": 1, "type": 1, "status": 1, "ticket_id": 1,
         "client_id": 1, "technician_id": 1, "technician_name": 1,
         "is_defective": 1, "defective_reason": 1},
    ).to_list(20000)

    # ─── Análises ──────────────────────────────────────────────────────────
    issues: Dict[str, List[Dict[str, Any]]] = {
        "negative_balance": [],
        "duplicate_location": [],
        "mixed_praca_tecnico": [],
        "orphan_onts": [],
        "service_without_technician": [],
        "defective_without_audit": [],
        "orphan_services_remaining": [],
    }

    # 1) Saldos negativos
    for s in stocks:
        loc = s.get("location") or "(sem location)"
        for cons_id in CONSUMABLE_IDS:
            val = s.get(cons_id)
            if isinstance(val, (int, float)) and val < 0:
                issues["negative_balance"].append({
                    "location": loc,
                    "consumable_id": cons_id,
                    "consumable_name": CONSUMABLE_BY_ID[cons_id]["name"],
                    "quantity": val,
                })

    # 2) Duplicate location (mesma string `location` em 2+ docs)
    loc_counter: Dict[str, int] = defaultdict(int)
    for s in stocks:
        loc_counter[s.get("location") or "(sem location)"] += 1
    for loc, n in loc_counter.items():
        if n > 1:
            issues["duplicate_location"].append({"location": loc, "count": n})

    # 3) Praça misturada com técnico — `location` é id de praça E técnico
    praca_id_set = set(praca_ids.keys())
    tech_id_set = set(tech_ids.keys())
    mixed = praca_id_set & tech_id_set
    if mixed:
        for mid in mixed:
            issues["mixed_praca_tecnico"].append({
                "id": mid,
                "praca_name": praca_ids[mid].get("name"),
                "tech_name": tech_ids[mid].get("name"),
            })

    # 4) ONTs órfãs — location_type=tecnico/praca mas location_id não bate
    for o in onts:
        lt = o.get("location_type")
        lid = o.get("location_id") or ""
        if lt == "tecnico" and lid and lid not in tech_id_set:
            issues["orphan_onts"].append({
                "ont_id": o.get("id"),
                "mac": o.get("mac"),
                "sn": o.get("sn"),
                "location_id": lid,
                "location_type": lt,
                "reason": "tecnico_id_nao_existe",
            })
        elif lt == "praca" and lid and lid not in praca_id_set:
            issues["orphan_onts"].append({
                "ont_id": o.get("id"),
                "mac": o.get("mac"),
                "sn": o.get("sn"),
                "location_id": lid,
                "location_type": lt,
                "reason": "praca_id_nao_existe",
            })

    # 5) Serviços ativos sem técnico atribuído
    for svc in services:
        if svc.get("status") == "ativo" and not svc.get("technician_id"):
            issues["service_without_technician"].append({
                "service_id": svc.get("id"),
                "type": svc.get("type"),
                "ticket_id": svc.get("ticket_id"),
                "client_id": svc.get("client_id"),
            })

    # 6) Defeituosas sem motivo (defective_reason vazio)
    for o in onts:
        if o.get("is_defective") and not (o.get("defective_reason") or "").strip():
            issues["defective_without_audit"].append({
                "ont_id": o.get("id"),
                "mac": o.get("mac"),
                "sn": o.get("sn"),
                "status": o.get("status"),
            })

    # 7) Stok_services órfãs — devem ter sido tageadas pela Onda A
    for svc in services:
        if svc.get("status") == "orfa_sem_ticket":
            issues["orphan_services_remaining"].append({
                "service_id": svc.get("id"),
                "type": svc.get("type"),
                "ticket_id": svc.get("ticket_id"),
                "technician_name": svc.get("technician_name"),
            })

    # ─── Sumário do mapeamento ─────────────────────────────────────────────
    empresa_stock = next((s for s in stocks if s.get("location") == "empresa"), None)
    summary = {
        "company_id": cid,
        "tech_count": len(techs),
        "praca_count": len(pracas),
        "stok_stock_docs": len(stocks),
        "onts_total": len(onts),
        "onts_empresa": sum(1 for o in onts if o.get("location_type") == "empresa"),
        "onts_tecnico": sum(1 for o in onts if o.get("location_type") == "tecnico"),
        "onts_cliente": sum(1 for o in onts if o.get("location_type") == "cliente"),
        "onts_defeituosa": sum(1 for o in onts if o.get("is_defective")),
        "services_ativo": sum(1 for s in services if s.get("status") == "ativo"),
        "services_orfa": sum(1 for s in services if s.get("status") == "orfa_sem_ticket"),
        "empresa_consumables": {
            c: (empresa_stock or {}).get(c, 0) for c in sorted(CONSUMABLE_IDS)
        },
    }

    return {"summary": summary, "issues": issues,
            "techs": techs, "pracas": pracas, "stocks": stocks}


def _md_table(headers: List[str], rows: List[List[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |"]
    out.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for r in rows:
        out.append("| " + " | ".join(str(c) if c is not None else "—" for c in r) + " |")
    return "\n".join(out)


def _format_report(audit_results: List[Tuple[str, Dict[str, Any]]]) -> str:
    """Gera Markdown estruturado a partir dos resultados read-only."""
    out: List[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    out.append("# AUDITORIA PRAÇA x TÉCNICO — Onda C P1 (READ-ONLY)")
    out.append("")
    out.append(f"> Gerado em: **{now}**")
    out.append(
        "> Script: `/app/backend/scripts/audit_praca_tecnico.py` · "
        "**ZERO writes** · regra de ouro Onda C respeitada"
    )
    out.append("")

    # ─── Sumário global ─────────────────────────────────────────────────
    out.append("## 📊 Sumário Global")
    out.append("")
    rows = []
    total_neg = total_dup = total_mixed = total_orphan_ont = 0
    total_svc_noTech = total_def = total_orfa = 0
    for cid, res in audit_results:
        s = res["summary"]
        i = res["issues"]
        total_neg += len(i["negative_balance"])
        total_dup += len(i["duplicate_location"])
        total_mixed += len(i["mixed_praca_tecnico"])
        total_orphan_ont += len(i["orphan_onts"])
        total_svc_noTech += len(i["service_without_technician"])
        total_def += len(i["defective_without_audit"])
        total_orfa += len(i["orphan_services_remaining"])
        rows.append([
            cid, s["tech_count"], s["praca_count"], s["stok_stock_docs"],
            s["onts_total"], s["services_ativo"], s["services_orfa"],
        ])
    out.append(_md_table(
        ["Empresa", "Técnicos", "Praças", "stok_stock", "ONTs", "Svc ativo", "Svc órfã"],
        rows,
    ))
    out.append("")
    out.append("### Totais de inconsistências (todas as empresas)")
    out.append("")
    out.append(_md_table(
        ["Categoria", "Quantidade"],
        [
            ["🔴 Saldos negativos", total_neg],
            ["🟠 Locations duplicadas", total_dup],
            ["🚨 Praça misturada com técnico (mesmo ID)", total_mixed],
            ["🟡 ONTs órfãs (location_id inexistente)", total_orphan_ont],
            ["🟠 Serviços ativos sem técnico", total_svc_noTech],
            ["🟡 ONTs defeituosas sem motivo", total_def],
            ["⚪ Serviços órfãos restantes (pós-Onda A)", total_orfa],
        ],
    ))
    out.append("")

    # ─── Por empresa ────────────────────────────────────────────────────
    for cid, res in audit_results:
        s = res["summary"]
        i = res["issues"]
        out.append("---")
        out.append("")
        out.append(f"## 🏢 Empresa `{cid}`")
        out.append("")
        # Estoque empresa
        out.append("### Estoque empresa (saldo atual)")
        out.append("")
        emp_rows = [[cons, qty] for cons, qty in s["empresa_consumables"].items()]
        out.append(_md_table(["Consumível", "Saldo"], emp_rows))
        out.append("")

        # ── Saldos negativos
        if i["negative_balance"]:
            out.append(f"### 🔴 Saldos NEGATIVOS ({len(i['negative_balance'])} ocorrências)")
            out.append("")
            out.append(_md_table(
                ["Location", "Consumível", "Quantidade"],
                [[b["location"], b["consumable_name"], b["quantity"]]
                 for b in i["negative_balance"]],
            ))
            out.append("")

        # ── Locations duplicadas
        if i["duplicate_location"]:
            out.append(f"### 🟠 Locations DUPLICADAS ({len(i['duplicate_location'])})")
            out.append("")
            out.append(_md_table(
                ["Location", "Docs encontrados"],
                [[d["location"], d["count"]] for d in i["duplicate_location"]],
            ))
            out.append("")

        # ── Praça x Técnico misturados
        if i["mixed_praca_tecnico"]:
            out.append(
                f"### 🚨 Praça MISTURADA com técnico ({len(i['mixed_praca_tecnico'])})"
            )
            out.append("")
            out.append("**Risco**: o mesmo ID é usado como ID de praça E como ID de técnico.")
            out.append("Movimentações podem estar sendo registradas no destino errado.")
            out.append("")
            out.append(_md_table(
                ["ID", "Praça (nome)", "Técnico (nome)"],
                [[m["id"], m["praca_name"], m["tech_name"]]
                 for m in i["mixed_praca_tecnico"]],
            ))
            out.append("")

        # ── ONTs órfãs (sample 25)
        if i["orphan_onts"]:
            sample = i["orphan_onts"][:25]
            out.append(
                f"### 🟡 ONTs órfãs ({len(i['orphan_onts'])} — sample de até 25)"
            )
            out.append("")
            out.append(_md_table(
                ["ONT ID", "MAC", "SN", "location_type", "location_id", "motivo"],
                [[o["ont_id"], o.get("mac"), o.get("sn"),
                  o["location_type"], o["location_id"], o["reason"]]
                 for o in sample],
            ))
            if len(i["orphan_onts"]) > 25:
                out.append("")
                out.append(f"… mais {len(i['orphan_onts']) - 25} casos truncados.")
            out.append("")

        # ── Serviços sem técnico
        if i["service_without_technician"]:
            out.append(
                f"### 🟠 Serviços ativos SEM técnico ({len(i['service_without_technician'])})"
            )
            out.append("")
            out.append(_md_table(
                ["Service ID", "Tipo", "Ticket", "Client"],
                [[x["service_id"], x["type"], x["ticket_id"], x["client_id"]]
                 for x in i["service_without_technician"][:25]],
            ))
            out.append("")

        # ── Defeituosas sem motivo
        if i["defective_without_audit"]:
            out.append(
                f"### 🟡 Defeituosas SEM motivo ({len(i['defective_without_audit'])})"
            )
            out.append("")
            out.append(_md_table(
                ["ONT ID", "MAC", "SN", "Status"],
                [[d["ont_id"], d.get("mac"), d.get("sn"), d.get("status")]
                 for d in i["defective_without_audit"][:25]],
            ))
            out.append("")

        # ── Órfãos remanescentes (pós-Onda A)
        if i["orphan_services_remaining"]:
            out.append(
                f"### ⚪ Stok_services órfãos remanescentes "
                f"({len(i['orphan_services_remaining'])})"
            )
            out.append("")
            out.append(
                "Status `orfa_sem_ticket` (marcação Onda A). NÃO devem ser "
                "deletados — apenas auditados manualmente. Já estão fora do "
                "fluxo operacional."
            )
            out.append("")
            out.append(_md_table(
                ["Service ID", "Tipo", "Ticket", "Técnico"],
                [[x["service_id"], x["type"], x["ticket_id"], x["technician_name"]]
                 for x in i["orphan_services_remaining"][:25]],
            ))
            out.append("")

        if not any(i.values()):
            out.append("✅ **Empresa limpa** — nenhuma inconsistência detectada.")
            out.append("")

    # ─── Recomendações ──────────────────────────────────────────────────
    out.append("---")
    out.append("")
    out.append("## 📋 Próximos passos (sem alterar DB)")
    out.append("")
    out.append("1. **Saldos negativos**: investigar transferências manuais sem audit prévio.")
    out.append("2. **Locations duplicadas**: candidatos a merge na Sprint 5 (migração estrutural).")
    out.append("3. **Praça x Técnico misturados**: corrigir IDs (renomear na origem) — só após review humano.")
    out.append("4. **ONTs órfãs**: linkar a um técnico/praça válido OU mover para empresa via UI.")
    out.append("5. **Serviços sem técnico**: revisar manualmente no painel de estoque.")
    out.append("6. **Defeituosas sem motivo**: backfill via UI (campo `defective_reason`).")
    out.append("")
    out.append("> ⚠️ NENHUMA dessas correções deve ser feita por script automático. "
                "Sprint 5 (Owner & Location Normalization) tratará migração estrutural "
                "após review CTO.")
    out.append("")
    return "\n".join(out) + "\n"


async def main():
    parser = argparse.ArgumentParser(description="Onda C — Auditoria Praça x Técnico (READ-ONLY)")
    parser.add_argument("--company-id", help="Auditar apenas 1 empresa", default=None)
    parser.add_argument("--output", help="Caminho do markdown",
                        default=str(OUTPUT_PATH))
    parser.add_argument("--print-only", action="store_true",
                        help="Não escreve arquivo, apenas stdout")
    args = parser.parse_args()

    if args.company_id:
        companies = [args.company_id]
    else:
        companies = await _collect_companies()

    print(f"[audit] {len(companies)} empresa(s) detectada(s). Iniciando varredura read-only…")
    results: List[Tuple[str, Dict[str, Any]]] = []
    for cid in companies:
        try:
            r = await _audit_company(cid)
            results.append((cid, r))
            issues_count = sum(len(v) for v in r["issues"].values())
            print(f"  · {cid}: {issues_count} inconsistência(s)")
        except Exception as e:  # noqa: BLE001
            print(f"  · {cid}: ERRO ao auditar — {e}")

    md = _format_report(results)
    if args.print_only:
        print(md)
    else:
        Path(args.output).write_text(md, encoding="utf-8")
        print(f"\n✅ Relatório salvo em: {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
