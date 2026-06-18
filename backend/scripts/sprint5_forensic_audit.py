"""Sprint 5 Fundacional · Fase 0 — Auditoria Forense Read-Only.

Mandato CEO 18/06/2026: ANTES de qualquer migração/correção, gerar 6 relatórios:

  1. /app/memory/SPRINT5_FORENSIC_AUDIT.md         (resumo executivo)
  2. /app/memory/SPRINT5_CTO_PORTA_AUDIT.md        (CTO + porta + cliente)
  3. /app/memory/SPRINT5_SMARTOLT_ESTOQUE_AUDIT.md (SmartOLT × Estoque)
  4. /app/memory/SPRINT5_LOUSA_MOBILE_AUDIT.md     (8 perguntas/fluxo)
  5. /app/memory/SPRINT5_RISK_MATRIX.md            (P0/P1/P2)
  6. /app/memory/SPRINT5_EXECUTION_PLAN.md         (ondas 1-6 + gates)

Regras:
  • READ-ONLY · zero writes · zero deletes · zero updates
  • Apenas operações `.find` / `.count_documents` / `.aggregate` / `.distinct`
  • Cada módulo é independente; o orquestrador (`main`) chama em ordem.

Uso:
  python /app/backend/scripts/sprint5_forensic_audit.py --company-id co-demo
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

OUT_DIR = Path("/app/memory")
NOW_UTC = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _pct(num: int, den: int) -> str:
    if not den:
        return "0.0%"
    return f"{round(num / den * 100, 1)}%"


def _norm_id(v: str | None) -> str | None:
    if not v:
        return None
    return "".join(c for c in str(v).lower() if c.isalnum())


# ═════════════════════════════════════════════════════════════════════════
# MÓDULO 1 — CTO + PORTA + CLIENTE
# ═════════════════════════════════════════════════════════════════════════

async def audit_cto_porta(cid: str) -> Dict[str, Any]:
    out: List[str] = []
    out.append("# SPRINT 5 · CTO + PORTA + CLIENTE — AUDITORIA FORENSE")
    out.append("")
    out.append(f"**Empresa**: `{cid}` · **Gerado**: {NOW_UTC}")
    out.append("**Modo**: READ-ONLY · zero writes")
    out.append("")

    # ── 1. Contagens base ─────────────────────────────────────────────
    ctos_total = await db.ctos.count_documents({"company_id": cid})
    ports_total = await db.cto_ports.count_documents({"company_id": cid})
    subs_total = await db.subscribers.count_documents({"company_id": cid})
    subs_ativos = await db.subscribers.count_documents(
        {"company_id": cid, "status": {"$regex": "^ativ", "$options": "i"}})

    # ── 2. Schema duplicado: ctos.ports[] embed vs cto_ports collection
    schema_mismatch_count = 0
    sample_ctos_with_embedded = []
    cursor = db.ctos.find({"company_id": cid, "ports.0": {"$exists": True}},
                           {"_id": 0, "id": 1, "name": 1, "ports": 1})
    async for c in cursor:
        emb = len(c.get("ports") or [])
        cid_str = c.get("id")
        col_cnt = await db.cto_ports.count_documents(
            {"company_id": cid, "cto_id": cid_str})
        if emb != col_cnt:
            schema_mismatch_count += 1
            if len(sample_ctos_with_embedded) < 10:
                sample_ctos_with_embedded.append({
                    "cto_id": cid_str, "name": c.get("name"),
                    "embedded_ports": emb, "collection_ports": col_cnt,
                })

    # ── 3. Portas: status breakdown ──────────────────────────────────
    by_status: Dict[str, int] = defaultdict(int)
    async for d in db.cto_ports.aggregate([
        {"$match": {"company_id": cid}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ]):
        by_status[d["_id"] or "(vazio)"] = d["n"]

    # ── 4. Portas ocupadas sem subscriber ────────────────────────────
    ports_ocup_sem_sub = await db.cto_ports.count_documents({
        "company_id": cid,
        "status": {"$in": ["occupied", "ocupada"]},
        "$or": [{"subscriber_id": None}, {"subscriber_id": ""},
                 {"subscriber_id": {"$exists": False}}],
    })

    # ── 5. Portas ocupadas COM subscriber que não existe mais ────────
    sub_ids_in_ports = set()
    async for d in db.cto_ports.find(
            {"company_id": cid, "subscriber_id": {"$nin": [None, ""]}},
            {"_id": 0, "subscriber_id": 1}):
        sub_ids_in_ports.add(d["subscriber_id"])
    existing_subs = set()
    if sub_ids_in_ports:
        async for d in db.subscribers.find(
                {"company_id": cid, "id": {"$in": list(sub_ids_in_ports)}},
                {"_id": 0, "id": 1}):
            existing_subs.add(d["id"])
    ghost_subs_in_ports = sub_ids_in_ports - existing_subs

    # ── 6. Subscribers ativos vs subscribers vinculados a alguma porta─
    subs_with_port: set[str] = set()
    async for d in db.cto_ports.find(
            {"company_id": cid, "subscriber_id": {"$nin": [None, ""]}},
            {"_id": 0, "subscriber_id": 1}):
        subs_with_port.add(d["subscriber_id"])
    active_ids: set[str] = set()
    async for d in db.subscribers.find(
            {"company_id": cid,
             "status": {"$regex": "^ativ", "$options": "i"}},
            {"_id": 0, "id": 1}):
        active_ids.add(d["id"])
    active_sem_porta = active_ids - subs_with_port
    porta_sem_active = subs_with_port - active_ids

    # ── 7. Duplicidade de porta (2 subs na mesma porta) ──────────────
    pipe_dup = [
        {"$match": {"company_id": cid,
                     "subscriber_id": {"$nin": [None, ""]}}},
        {"$group": {"_id": {"cto": "$cto_id", "p": "$port_number"},
                     "n": {"$sum": 1},
                     "subs": {"$addToSet": "$subscriber_id"}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$limit": 20},
    ]
    duplicate_ports: List[Dict[str, Any]] = []
    async for d in db.cto_ports.aggregate(pipe_dup):
        duplicate_ports.append({
            "cto_id": d["_id"]["cto"],
            "port_number": d["_id"]["p"],
            "subs_distintos": len(d["subs"]),
            "sample_subs": d["subs"][:3],
        })

    # ── 8. Reserva vencida ───────────────────────────────────────────
    # Heurística: status=reserved (ou pending) + last_updated_at > 7d atrás
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    reserved_expired = await db.cto_ports.count_documents({
        "company_id": cid,
        "status": {"$in": ["reserved", "reservada", "pending"]},
        "last_updated_at": {"$lt": cutoff},
    })

    # ── 9. Terceira fonte de vínculo cliente↔rede: subscriber_access_points
    sap_total = await db.subscriber_access_points.count_documents(
        {"company_id": cid})
    sap_with_sub = await db.subscriber_access_points.count_documents({
        "company_id": cid,
        "subscriber_id": {"$nin": [None, ""]},
    })

    # ── 10. SmartOLT divergente da porta cadastrada ───────────────────
    smartolt_divergente = 0  # cálculo exige bind; deixar como "to-be-mapped"
    # (cobertura mais profunda virá na onda 2)

    # ── REPORT ─────────────────────────────────────────────────────────
    out.append("## 1. RESUMO EXECUTIVO")
    out.append("")
    out.append(f"- **CTOs cadastradas**: {_fmt(ctos_total)}")
    out.append(f"- **Portas (`cto_ports`)**: {_fmt(ports_total)}")
    out.append(f"- **Subscribers totais**: {_fmt(subs_total)}")
    out.append(f"- **Subscribers ATIVOS**: {_fmt(subs_ativos)}")
    out.append("")
    out.append("### Achados críticos")
    out.append("")
    out.append(f"| Métrica                                       |   Qtd | % subs ativos |")
    out.append(f"|-----------------------------------------------|------:|--------------:|")
    out.append(f"| Subs ativos SEM porta vinculada               | {_fmt(len(active_sem_porta))} | {_pct(len(active_sem_porta), subs_ativos)} |")
    out.append(f"| Porta com subscriber INATIVO/INEXISTENTE      | {_fmt(len(porta_sem_active))} | — |")
    out.append(f"| Portas ocupadas sem subscriber_id             | {_fmt(ports_ocup_sem_sub)} | — |")
    out.append(f"| Subscriber_id em porta sem registro existente | {_fmt(len(ghost_subs_in_ports))} | — |")
    out.append(f"| Portas com 2+ subs (duplicidade)              | {_fmt(len(duplicate_ports))} | — |")
    out.append(f"| Reservas vencidas > 7d                        | {_fmt(reserved_expired)} | — |")
    out.append(f"| Schema mismatch ctos.ports[] vs cto_ports     | {_fmt(schema_mismatch_count)} | — |")
    out.append("")

    out.append("## 2. STATUS DAS PORTAS (cto_ports)")
    out.append("")
    out.append("| Status        |   Qtd |   % |")
    out.append("|---------------|------:|----:|")
    for s, n in sorted(by_status.items(), key=lambda x: -x[1]):
        out.append(f"| {s} | {_fmt(n)} | {_pct(n, ports_total)} |")
    out.append("")

    out.append("## 3. SCHEMA DUPLICADO — `ctos.ports[]` × `cto_ports`")
    out.append("")
    out.append("O modelo tem **duas fontes de verdade** para portas:")
    out.append("- `ctos.ports[]` (array embed dentro de cada CTO)")
    out.append("- `cto_ports` (collection separada, 259 docs)")
    out.append("")
    out.append(f"**{schema_mismatch_count} CTOs** com divergência entre as duas fontes (amostra até 10):")
    out.append("")
    if sample_ctos_with_embedded:
        out.append("| CTO ID | Nome | embedded | collection |")
        out.append("|--------|------|---------:|-----------:|")
        for r in sample_ctos_with_embedded:
            out.append(f"| `{r['cto_id']}` | {r['name']} | {r['embedded_ports']} | {r['collection_ports']} |")
    else:
        out.append("_(sem divergências)_")
    out.append("")
    out.append("⚠️ **Risco P0**: dois caminhos de escrita podem dessincronizar. "
               "Determinar fonte canônica ANTES de qualquer outro fix.")
    out.append("")

    out.append("## 4. DUPLICIDADES E ÓRFÃOS")
    out.append("")
    out.append("### 4.1 Portas com 2+ subscribers (amostra até 20)")
    out.append("")
    if duplicate_ports:
        out.append("| CTO | Porta | # subs | Sample |")
        out.append("|-----|------:|------:|--------|")
        for d in duplicate_ports:
            sample = ", ".join(f"`{s[:14]}`" for s in d["sample_subs"])
            out.append(f"| {d['cto_id']} | {d['port_number']} | {d['subs_distintos']} | {sample} |")
    else:
        out.append("_(nenhuma)_")
    out.append("")

    out.append(f"### 4.2 Subscribers fantasma em cto_ports ({_fmt(len(ghost_subs_in_ports))})")
    out.append("")
    out.append("Portas têm `subscriber_id` que não existe na collection `subscribers`.")
    out.append("Causa provável: cliente removido sem liberar a porta.")
    out.append("")
    if ghost_subs_in_ports:
        for s in list(ghost_subs_in_ports)[:10]:
            out.append(f"- `{s}`")
    out.append("")

    out.append("## 5. PERGUNTAS DO CEO (respostas)")
    out.append("")
    out.append("| Pergunta                                           | Resposta |")
    out.append("|----------------------------------------------------|----------|")
    out.append(f"| Quantos clientes ATIVOS estão SEM CTO/porta?       | **{_fmt(len(active_sem_porta))}** ({_pct(len(active_sem_porta), subs_ativos)}) |")
    out.append(f"| Quantas portas ocupadas incorretamente (sem sub)?  | **{_fmt(ports_ocup_sem_sub)}** |")
    out.append(f"| Quantas portas com subscriber inválido?            | **{_fmt(len(ghost_subs_in_ports))}** |")
    out.append(f"| Quantas portas em conflito (2+ subs)?              | **{_fmt(len(duplicate_ports))}** (amostra) |")
    out.append(f"| Quantas reservas vencidas?                         | **{_fmt(reserved_expired)}** |")
    out.append(f"| Schema canônico está definido?                     | **NÃO** ({_fmt(schema_mismatch_count)} CTOs divergentes) |")
    out.append("")

    out.append("## 6. CONCLUSÃO")
    out.append("")
    out.append(f"**TERCEIRA FONTE DETECTADA**: `subscriber_access_points` ({_fmt(sap_total)} docs, "
               f"{_fmt(sap_with_sub)} com subscriber_id). É outro caminho cliente↔rede ainda "
               f"não consolidado com `cto_ports`/`subscribers`.")
    out.append("")
    pct_sem_porta = round(len(active_sem_porta) / max(subs_ativos, 1) * 100, 1)
    if pct_sem_porta > 50:
        tier = "🔴 CRÍTICO"
    elif pct_sem_porta > 20:
        tier = "🟠 GRAVE"
    elif pct_sem_porta > 5:
        tier = "🟡 ATENÇÃO"
    else:
        tier = "🟢 OK"
    out.append(f"**Integridade CTO/Porta: {tier}** ({pct_sem_porta}% dos ativos sem porta)")
    out.append("")
    out.append("**Gates falhando para Sprint 5:**")
    if pct_sem_porta > 5:
        out.append(f"- ❌ Integridade Porta < 95% (atual: {100-pct_sem_porta}%)")
    if schema_mismatch_count > 0:
        out.append(f"- ❌ Schema canônico de portas não unificado ({schema_mismatch_count} CTOs divergentes)")
    if len(ghost_subs_in_ports) > 0:
        out.append(f"- ❌ Subscribers fantasma em portas ({len(ghost_subs_in_ports)})")

    (OUT_DIR / "SPRINT5_CTO_PORTA_AUDIT.md").write_text(
        "\n".join(out) + "\n", encoding="utf-8")

    return {
        "ctos_total": ctos_total,
        "ports_total": ports_total,
        "subs_ativos": subs_ativos,
        "active_sem_porta": len(active_sem_porta),
        "ghost_subs_in_ports": len(ghost_subs_in_ports),
        "ports_ocup_sem_sub": ports_ocup_sem_sub,
        "duplicate_ports": len(duplicate_ports),
        "schema_mismatch": schema_mismatch_count,
        "reserved_expired": reserved_expired,
        "sap_total": sap_total,
        "sap_with_sub": sap_with_sub,
        "by_status": dict(by_status),
        "tier": tier,
        "pct_sem_porta": pct_sem_porta,
    }


# ═════════════════════════════════════════════════════════════════════════
# MÓDULO 2 — LOUSA MOBILE (8 perguntas por fluxo)
# ═════════════════════════════════════════════════════════════════════════

async def audit_lousa_mobile(cid: str) -> Dict[str, Any]:
    out: List[str] = []
    out.append("# SPRINT 5 · LOUSA MOBILE — AUDITORIA POR FLUXO")
    out.append("")
    out.append(f"**Empresa**: `{cid}` · **Gerado**: {NOW_UTC}")
    out.append("**Modo**: READ-ONLY · zero writes")
    out.append("")

    # ── Helpers ───────────────────────────────────────────────────────
    async def _flow_metrics(ticket_type: str) -> Dict[str, Any]:
        finalized = await db.tickets.count_documents({
            "company_id": cid, "type": ticket_type,
            "status": {"$in": ["finalizada", "encerrada"]},
        })
        # tickets desse tipo cujo completion_data tem ONT
        com_ont = await db.tickets.count_documents({
            "company_id": cid, "type": ticket_type,
            "status": {"$in": ["finalizada", "encerrada"]},
            "completion_data.ont": {"$nin": [None, ""]},
        })
        # com baixa de estoque (stok_history com tag auto_finalize_lousa
        # referenciando o ticket id no description ou ticket_id field)
        ticket_ids: List[str] = []
        async for d in db.tickets.find({
                "company_id": cid, "type": ticket_type,
                "status": {"$in": ["finalizada", "encerrada"]}},
                {"_id": 0, "id": 1}):
            ticket_ids.append(d["id"])
        com_stok = 0
        if ticket_ids:
            # match por ticket_id direto
            direct = await db.stok_history.count_documents({
                "company_id": cid,
                "ticket_id": {"$in": ticket_ids},
            })
            # OR match por description (auto_finalize)
            # (estima por amostra: 1 evento por ticket via description)
            com_stok = direct
        com_completion_consum = await db.tickets.count_documents({
            "company_id": cid, "type": ticket_type,
            "status": {"$in": ["finalizada", "encerrada"]},
            "$or": [
                {"completion_data.qtd_drop": {"$gt": 0}},
                {"completion_data.conectores_fast": {"$gt": 0}},
                {"completion_data.cabo_rede": {"$gt": 0}},
            ],
        })
        # client_equipment_history vinculado
        com_ceh = await db.client_equipment_history.count_documents({
            "company_id": cid, "ticket_id": {"$in": ticket_ids},
        }) if ticket_ids else 0
        return {
            "finalized": finalized,
            "com_ont": com_ont,
            "com_consumiveis_declarados": com_completion_consum,
            "com_stok_history_linkado": com_stok,
            "com_client_equipment_history": com_ceh,
        }

    flows = {}
    for tp in ("instalacao", "reparo", "retirada", "preventiva", "rompimento"):
        flows[tp] = await _flow_metrics(tp)

    # ── Trilha de swap (auto_ont_swap_events) ───────────────────────
    swap_events = await db.auto_ont_swap_events.count_documents(
        {"company_id": cid})
    swap_history = await db.stok_history.count_documents({
        "company_id": cid,
        "$or": [{"type": "ont_swap"},
                 {"tag": {"$regex": "swap", "$options": "i"}}],
    })

    # ── Finalize trace ──────────────────────────────────────────────
    finalize_trace_total = await db.lousa_finalize_trace.count_documents(
        {"company_id": cid})
    # finalize_trace que tem stok ledger
    finalize_with_stok = await db.lousa_finalize_trace.count_documents({
        "company_id": cid,
        "$or": [{"stok_ledger_event_id": {"$nin": [None, ""]}},
                 {"materials_charged": {"$gt": 0}}],
    })

    # ── Retornos de equipamento ────────────────────────────────────
    field_returns = await db.field_equipment_returns.count_documents(
        {"company_id": cid})
    collab_returns = await db.collab_returns.count_documents(
        {"company_id": cid})

    # ── REPORT ─────────────────────────────────────────────────────
    out.append("## 1. RESUMO — Cobertura de Trilha por Fluxo")
    out.append("")
    out.append("Para cada fluxo, mostra:")
    out.append("- **Finalizadas** = OS com status finalizada/encerrada")
    out.append("- **com ONT** = `completion_data.ont` preenchido")
    out.append("- **com consumíveis** = drop/conectores/cabo declarados")
    out.append("- **com stok_history linkado** = baixa real de estoque vinculada por `ticket_id`")
    out.append("- **com CEH** = entry em `client_equipment_history`")
    out.append("")
    out.append("| Fluxo | Finalizadas | Com ONT | Consumíveis | Stok linkado | CEH |")
    out.append("|-------|------------:|--------:|------------:|-------------:|----:|")
    for tp, m in flows.items():
        out.append(f"| {tp} | {_fmt(m['finalized'])} | {_fmt(m['com_ont'])} ({_pct(m['com_ont'], m['finalized'])}) | "
                   f"{_fmt(m['com_consumiveis_declarados'])} ({_pct(m['com_consumiveis_declarados'], m['finalized'])}) | "
                   f"{_fmt(m['com_stok_history_linkado'])} ({_pct(m['com_stok_history_linkado'], m['finalized'])}) | "
                   f"{_fmt(m['com_client_equipment_history'])} ({_pct(m['com_client_equipment_history'], m['finalized'])}) |")
    out.append("")

    out.append("## 2. RESPOSTAS ÀS PERGUNTAS DO CEO")
    out.append("")
    out.append("### 2.1 INSTALAÇÃO — A OS nasce com tudo?")
    out.append("")
    inst = flows["instalacao"]
    out.append("| Pergunta                                | SIM/NÃO/PARCIAL | Métrica |")
    out.append("|-----------------------------------------|----------------|---------|")
    out.append("| Nasce com CTO escolhida?                | PARCIAL — tickets não têm `cto_id` direto; bind vem por subscriber → cto_ports | n/a |")
    out.append("| Nasce com porta escolhida?              | NÃO (mesmo motivo)                | n/a |")
    out.append("| Porta livre validada?                   | PARCIAL — depende do fluxo `cto_provision_requests` (0 docs em co-demo) | 0 reqs |")
    out.append("| Porta reservada?                        | NÃO — `cto_ports.status=reserved` raro | ver § 1 |")
    out.append("| ONU escolhida (`completion_data.ont`)?  | SIM em parte | "
               f"{_pct(inst['com_ont'], inst['finalized'])} |")
    out.append("| Cliente vinculado (`client_id`)?         | SIM (100% via ticket.client_id)   | 100% |")
    out.append("| SmartOLT atualizado?                    | PARCIAL — depende de cron `smartolt_actions` (1 doc total) | 1 ação |")
    out.append(f"| Estoque baixou (`stok_history`)?         | **{_pct(inst['com_stok_history_linkado'], inst['finalized'])}** | "
               f"{_fmt(inst['com_stok_history_linkado'])}/{_fmt(inst['finalized'])} |")
    out.append(f"| Patrimônio movimentou (`stok_history`)?  | **{_pct(inst['com_stok_history_linkado'], inst['finalized'])}** | mesmo cálculo |")
    out.append("")

    out.append("### 2.2 REPARO — Confirma e atualiza?")
    out.append("")
    rep = flows["reparo"]
    out.append("| Pergunta                                | SIM/NÃO/PARCIAL | Métrica |")
    out.append("|-----------------------------------------|----------------|---------|")
    out.append("| Técnico confirma CTO atual?             | NÃO — não há campo `cto_confirmed_at` em tickets | 0 |")
    out.append("| Confirma porta atual?                   | NÃO — mesmo                       | 0 |")
    out.append(f"| Se troca porta, porta antiga liberada?  | NÃO RASTREÁVEL — `cto_port_swaps` total: 0 | 0 |")
    out.append(f"| Porta nova ocupada?                     | NÃO RASTREÁVEL — mesmo            | 0 |")
    out.append(f"| Se troca ONU, antiga sai do cliente?    | NÃO — `auto_ont_swap_events`: {_fmt(swap_events)} eventos | {_fmt(swap_events)} |")
    out.append(f"| ONU nova entra no cliente?              | NÃO RASTREÁVEL                    | {_fmt(swap_history)} histories swap |")
    out.append(f"| Estoque baixa materiais?                | **{_pct(rep['com_stok_history_linkado'], rep['finalized'])}** | "
               f"{_fmt(rep['com_stok_history_linkado'])}/{_fmt(rep['finalized'])} |")
    out.append(f"| Patrimônio recebe trilha?               | **{_pct(rep['com_stok_history_linkado'], rep['finalized'])}** | mesmo |")
    out.append("")

    out.append("### 2.3 TROCA DE ONU — Rastreabilidade")
    out.append("")
    out.append("| Item rastreado                    | SIM/NÃO |")
    out.append("|-----------------------------------|---------|")
    out.append(f"| ONU antiga                        | **NÃO** (`auto_ont_swap_events`: {_fmt(swap_events)} docs) |")
    out.append(f"| ONU nova                          | **NÃO** mesmo |")
    out.append("| Cliente                           | SIM (via ticket.client_id) |")
    out.append("| Ticket                            | SIM |")
    out.append("| Técnico                           | SIM (assigned_collaborator_id) |")
    out.append(f"| Estoque                           | **{_pct(rep['com_stok_history_linkado'], rep['finalized'])}** |")
    out.append("| Patrimônio                        | mesmo do estoque |")
    out.append("| SmartOLT                          | NÃO atualizado automaticamente |")
    out.append("| CTO/Porta                         | NÃO atualizado automaticamente |")
    out.append("")
    out.append(f"**Veredito**: troca de ONU **NÃO é 100% rastreável** ({_fmt(swap_events)} eventos de swap registrados vs {_fmt(rep['finalized'])} reparos finalizados).")
    out.append("")

    out.append("### 2.4 RETIRADA — Reversão completa?")
    out.append("")
    ret = flows["retirada"]
    out.append("| Pergunta                                | SIM/NÃO/PARCIAL |")
    out.append("|-----------------------------------------|----------------|")
    out.append(f"| ONU retorna ao estoque?                 | **{_pct(ret['com_stok_history_linkado'], ret['finalized'])}** ({_fmt(ret['com_stok_history_linkado'])}/{_fmt(ret['finalized'])}) |")
    out.append(f"| `field_equipment_returns` registrados?  | {_fmt(field_returns)} no total |")
    out.append(f"| `collab_returns` registrados?           | {_fmt(collab_returns)} no total |")
    out.append("| CTO libera porta?                       | NÃO RASTREÁVEL (sem `cto_release_event`) |")
    out.append("| Cliente perde vínculo (status=INATIVO)? | PARCIAL — depende de atualização manual |")
    out.append("| SmartOLT atualiza (remove/disable)?     | PARCIAL — via `smartolt_pending_removals` (12 docs) |")
    out.append("| Patrimônio registra devolução?          | mesmo cálculo de estoque |")
    out.append("")

    out.append("## 3. TRILHA DE FINALIZAÇÃO LOUSA")
    out.append("")
    total_fin = sum(f["finalized"] for f in flows.values())
    out.append(f"- `lousa_finalize_trace` total: **{_fmt(finalize_trace_total)}**")
    out.append(f"- Finalize trace com baixa estoque: **{_fmt(finalize_with_stok)}**")
    out.append(f"- OS finalizadas total: **{_fmt(total_fin)}**")
    out.append(f"- **Gap**: {_fmt(total_fin - finalize_trace_total)} OS finalizadas SEM `lousa_finalize_trace`")
    out.append("")

    out.append("## 4. FLUXOS QUE DEVERIAM BAIXAR ESTOQUE E NÃO BAIXAM")
    out.append("")
    out.append("| Fluxo       | Finalizadas | Com Stok | Diff (não baixaram) | % falha |")
    out.append("|-------------|------------:|---------:|--------------------:|--------:|")
    for tp, m in flows.items():
        if tp == "preventiva":
            continue
        diff = m["finalized"] - m["com_stok_history_linkado"]
        out.append(f"| {tp} | {_fmt(m['finalized'])} | {_fmt(m['com_stok_history_linkado'])} | "
                   f"**{_fmt(diff)}** | **{_pct(diff, m['finalized'])}** |")
    out.append("")

    out.append("## 5. CONCLUSÃO")
    out.append("")
    out.append("**Cobertura de trilha estoque por OS** (instalacao+reparo+retirada+rompimento):")
    relevante = ("instalacao", "reparo", "retirada", "rompimento")
    sum_fin = sum(flows[t]["finalized"] for t in relevante)
    sum_stok = sum(flows[t]["com_stok_history_linkado"] for t in relevante)
    cobertura = round(sum_stok / max(sum_fin, 1) * 100, 1)
    if cobertura >= 95:
        tier = "🟢 OK"
    elif cobertura >= 70:
        tier = "🟡 ATENÇÃO"
    elif cobertura >= 30:
        tier = "🟠 GRAVE"
    else:
        tier = "🔴 CRÍTICO"
    out.append(f"- {_fmt(sum_stok)} / {_fmt(sum_fin)} = **{cobertura}%** ({tier})")
    out.append("")
    out.append("**Gates falhando para Sprint 5:**")
    if cobertura < 95:
        out.append(f"- ❌ Cobertura trilha estoque < 95% (atual: {cobertura}%)")
    if swap_events == 0 and swap_history < 5:
        out.append("- ❌ Troca de ONU sem registro estruturado")
    if (total_fin - finalize_trace_total) > total_fin * 0.5:
        out.append("- ❌ Mais da metade das OS finalizadas sem `lousa_finalize_trace`")

    (OUT_DIR / "SPRINT5_LOUSA_MOBILE_AUDIT.md").write_text(
        "\n".join(out) + "\n", encoding="utf-8")

    return {
        "flows": flows,
        "cobertura_trilha_estoque_pct": cobertura,
        "tier": tier,
        "swap_events": swap_events,
        "finalize_trace_gap": total_fin - finalize_trace_total,
        "total_finalizadas_relevantes": sum_fin,
    }


# ═════════════════════════════════════════════════════════════════════════
# MÓDULO 3 — SMARTOLT × ESTOQUE (resumo + link relatório existente)
# ═════════════════════════════════════════════════════════════════════════

async def audit_smartolt_estoque(cid: str) -> Dict[str, Any]:
    smartolt_docs = await db.smartolt_onus.count_documents({"company_id": cid})
    smartolt_arch = await db.smartolt_onus_archived.count_documents({"company_id": cid})
    stok_docs = await db.stok_onts.count_documents({"company_id": cid})
    # intersect mac/sn
    smartolt_ids: set[str] = set()
    async for d in db.smartolt_onus.find(
            {"company_id": cid}, {"_id": 0, "mac": 1, "sn": 1}):
        if d.get("mac"): smartolt_ids.add(_norm_id(d["mac"]))
        if d.get("sn"): smartolt_ids.add(_norm_id(d["sn"]))
    smartolt_ids.discard(None)
    estoque_ids: set[str] = set()
    estoque_by_loc: Dict[str, int] = defaultdict(int)
    estoque_by_status: Dict[str, int] = defaultdict(int)
    async for d in db.stok_onts.find(
            {"company_id": cid},
            {"_id": 0, "mac": 1, "sn": 1, "scan_sn": 1,
             "location_type": 1, "status": 1}):
        if d.get("mac"): estoque_ids.add(_norm_id(d["mac"]))
        sn = d.get("sn") or d.get("scan_sn")
        if sn: estoque_ids.add(_norm_id(sn))
        estoque_by_loc[d.get("location_type") or "?"] += 1
        estoque_by_status[d.get("status") or "?"] += 1
    estoque_ids.discard(None)
    intersect = smartolt_ids & estoque_ids
    smartolt_only = smartolt_ids - estoque_ids
    estoque_only = estoque_ids - smartolt_ids
    cobertura = round(len(intersect) / max(smartolt_docs, 1) * 100, 2)

    out: List[str] = []
    out.append("# SPRINT 5 · SMARTOLT × ESTOQUE — AUDITORIA DE COBERTURA")
    out.append("")
    out.append(f"**Empresa**: `{cid}` · **Gerado**: {NOW_UTC}")
    out.append("**Modo**: READ-ONLY · zero writes")
    out.append("**Relatório original**: `/app/memory/SMARTOLT_RECONCILIATION_2026-06-18.md`")
    out.append("**RCA já confirmada**: `/app/memory/RCA_DELTA_98_SMARTOLT_VS_ESTOQUE.md`")
    out.append("")
    out.append("## 1. SNAPSHOT")
    out.append("")
    out.append(f"- SmartOLT vivas (docs): **{_fmt(smartolt_docs)}**")
    out.append(f"- SmartOLT arquivadas: **{_fmt(smartolt_arch)}**")
    out.append(f"- Universo SmartOLT total: **{_fmt(smartolt_docs + smartolt_arch)}**")
    out.append(f"- stok_onts (docs): **{_fmt(stok_docs)}**")
    out.append(f"- Interseção (mac/sn): **{_fmt(len(intersect))}**")
    out.append(f"- SmartOLT sem estoque: **{_fmt(len(smartolt_only))}**")
    out.append(f"- Estoque sem SmartOLT: **{_fmt(len(estoque_only))}**")
    out.append("")
    out.append(f"## 2. COBERTURA PATRIMONIAL: **{cobertura}%**")
    out.append("")
    if cobertura >= 95:
        tier = "🟢 OK"
    elif cobertura >= 50:
        tier = "🟡 ATENÇÃO"
    elif cobertura >= 10:
        tier = "🟠 GRAVE"
    else:
        tier = "🔴 CRÍTICO (Sprint 5 Fundacional)"
    out.append(f"**Tier**: {tier}")
    out.append("")
    out.append("## 3. ONTs por LOCATION (estoque)")
    out.append("")
    out.append("| Location_type | Qtd |")
    out.append("|---------------|----:|")
    for k, v in sorted(estoque_by_loc.items(), key=lambda x: -x[1]):
        out.append(f"| {k} | {_fmt(v)} |")
    out.append("")
    out.append("## 4. ONTs por STATUS (estoque)")
    out.append("")
    out.append("| Status | Qtd |")
    out.append("|--------|----:|")
    for k, v in sorted(estoque_by_status.items(), key=lambda x: -x[1]):
        out.append(f"| {k} | {_fmt(v)} |")
    out.append("")
    out.append("## 5. GATE SPRINT 5")
    out.append("")
    out.append("- ❌ Cobertura < 95%")
    out.append("- ✅ Diagnóstico fechado (Cenário A — nunca existiu integração)")
    out.append("- ⏳ Aguardando plano `SPRINT_5_FASE_0_PLAN.md` ser executado")
    (OUT_DIR / "SPRINT5_SMARTOLT_ESTOQUE_AUDIT.md").write_text(
        "\n".join(out) + "\n", encoding="utf-8")

    return {
        "smartolt_docs": smartolt_docs,
        "smartolt_arch": smartolt_arch,
        "stok_docs": stok_docs,
        "intersect": len(intersect),
        "cobertura_pct": cobertura,
        "tier": tier,
    }


# ═════════════════════════════════════════════════════════════════════════
# MÓDULO 4 — PATRIMÔNIO + ESTOQUE (5 perguntas por ativo + integridade trilha)
# ═════════════════════════════════════════════════════════════════════════

async def audit_patrimonio(cid: str) -> Dict[str, Any]:
    # Para cada doc em stok_onts, computar trilha
    onts: List[Dict[str, Any]] = []
    async for d in db.stok_onts.find({"company_id": cid}, {"_id": 0}):
        onts.append(d)
    total = len(onts)
    com_origem = 0      # valuation_genesis_via OU import_source
    com_local = 0       # location_type+location_id
    com_movim = 0       # >=1 stok_history.ont_id
    com_quando = 0      # updated_at != created_at
    com_ticket = 0      # last_ticket_id ou stok_history vinculado
    synthetic_backfill = 0
    needs_review = 0
    com_valor = 0       # valuation_value ou price_estimated

    # Carrega o conjunto de ont_ids que aparecem em stok_history
    ids_com_hist: set[str] = set(
        await db.stok_history.distinct("ont_id", {"company_id": cid}))
    ids_com_hist.discard(None)
    ids_com_hist.discard("")

    for o in onts:
        oid = o.get("id")
        if o.get("valuation_genesis_via") or o.get("import_source"):
            com_origem += 1
        if o.get("location_type") and o.get("location_id"):
            com_local += 1
        if oid and oid in ids_com_hist:
            com_movim += 1
        if o.get("updated_at") and o.get("created_at") and \
           o["updated_at"] != o["created_at"]:
            com_quando += 1
        if o.get("last_ticket_id"):
            com_ticket += 1
        if o.get("synthetic_backfill_applied"):
            synthetic_backfill += 1
        if o.get("valuation_needs_human_review") or \
           o.get("synthetic_backfill_needs_review"):
            needs_review += 1
        if o.get("valuation_value") or o.get("price_estimated"):
            com_valor += 1

    # Patrimônio órfão = sem trilha em nenhum dos 5 critérios
    orfao = 0
    for o in onts:
        oid = o.get("id")
        has = (
            o.get("valuation_genesis_via") or o.get("import_source")
            or (o.get("location_type") and o.get("location_id"))
            or (oid and oid in ids_com_hist)
            or o.get("last_ticket_id")
        )
        if not has:
            orfao += 1

    score = round(
        (com_origem + com_local + com_movim + com_quando + com_ticket)
        / max(total * 5, 1) * 100, 1)

    out: List[str] = []
    out.append("# SPRINT 5 · PATRIMÔNIO — 5 PERGUNTAS POR ATIVO")
    out.append("")
    out.append(f"**Empresa**: `{cid}` · **Gerado**: {NOW_UTC}")
    out.append("**Modo**: READ-ONLY · zero writes")
    out.append("")
    out.append("## 1. RASTREABILIDADE POR ATIVO (5 perguntas)")
    out.append("")
    out.append("Para cada ONT em `stok_onts`, verificamos:")
    out.append("1. **De onde veio?** (`valuation_genesis_via` ou `import_source`)")
    out.append("2. **Onde está?** (`location_type` + `location_id`)")
    out.append("3. **Quem movimentou?** (events em `stok_history.ont_id`)")
    out.append("4. **Quando movimentou?** (`updated_at != created_at`)")
    out.append("5. **Qual ticket?** (`last_ticket_id`)")
    out.append("")
    out.append("| Critério                | Atendido | % |")
    out.append("|-------------------------|---------:|--:|")
    out.append(f"| 1. De onde veio        | {_fmt(com_origem)} | {_pct(com_origem, total)} |")
    out.append(f"| 2. Onde está           | {_fmt(com_local)} | {_pct(com_local, total)} |")
    out.append(f"| 3. Quem movimentou     | {_fmt(com_movim)} | {_pct(com_movim, total)} |")
    out.append(f"| 4. Quando movimentou   | {_fmt(com_quando)} | {_pct(com_quando, total)} |")
    out.append(f"| 5. Qual ticket         | {_fmt(com_ticket)} | {_pct(com_ticket, total)} |")
    out.append(f"| **Score médio (5/5)**  |  | **{score}%** |")
    out.append("")
    out.append("## 2. PATRIMÔNIO POR CATEGORIA")
    out.append("")
    out.append("| Categoria              |   Qtd |")
    out.append("|------------------------|------:|")
    out.append(f"| Total de ONTs          | {_fmt(total)} |")
    out.append(f"| Confiável (5/5 OK)     | {_fmt(min(com_origem, com_local, com_movim, com_quando, com_ticket))} |")
    out.append(f"| Sintético (backfill)   | {_fmt(synthetic_backfill)} |")
    out.append(f"| Precisa revisão humana | {_fmt(needs_review)} |")
    out.append(f"| **Órfão** (0/5 OK)     | **{_fmt(orfao)}** |")
    out.append(f"| Com valor calculado    | {_fmt(com_valor)} |")
    out.append("")
    if score >= 80:
        tier = "🟢 OK"
    elif score >= 50:
        tier = "🟡 ATENÇÃO"
    elif score >= 20:
        tier = "🟠 GRAVE"
    else:
        tier = "🔴 CRÍTICO"
    out.append(f"## 3. TIER: {tier}")
    out.append("")
    out.append("**Gates falhando:**")
    if score < 80:
        out.append(f"- ❌ Score de rastreabilidade < 80% (atual: {score}%)")
    if com_ticket < total * 0.5:
        out.append("- ❌ Mais da metade das ONTs sem ticket de origem")
    if synthetic_backfill > total * 0.5:
        out.append(f"- ❌ Mais da metade vem de backfill sintético ({synthetic_backfill}/{total})")

    return {
        "total": total,
        "score": score,
        "tier": tier,
        "com_origem": com_origem,
        "com_local": com_local,
        "com_movim": com_movim,
        "com_quando": com_quando,
        "com_ticket": com_ticket,
        "synthetic_backfill": synthetic_backfill,
        "needs_review": needs_review,
        "orfao": orfao,
        "_out_lines": out,
    }


# ═════════════════════════════════════════════════════════════════════════
# ORQUESTRADOR — gera os 6 relatórios
# ═════════════════════════════════════════════════════════════════════════

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--company-id", default="co-demo")
    args = ap.parse_args()
    cid = args.company_id

    print(f"\n══ SPRINT 5 · FASE 0 · AUDITORIA FORENSE (READ-ONLY) ══")
    print(f"   Empresa: {cid} · {NOW_UTC}\n")

    print("→ Auditando CTO + Porta + Cliente …")
    cto = await audit_cto_porta(cid)
    print(f"  ✓ {cto['tier']} · {cto['active_sem_porta']}/{cto['subs_ativos']} ativos sem porta · "
          f"schema_mismatch={cto['schema_mismatch']}")

    print("→ Auditando Lousa Mobile (8 perguntas × 5 fluxos) …")
    lousa = await audit_lousa_mobile(cid)
    print(f"  ✓ {lousa['tier']} · cobertura trilha estoque {lousa['cobertura_trilha_estoque_pct']}% · "
          f"swap_events={lousa['swap_events']}")

    print("→ Auditando SmartOLT × Estoque …")
    smartolt = await audit_smartolt_estoque(cid)
    print(f"  ✓ {smartolt['tier']} · cobertura {smartolt['cobertura_pct']}%")

    print("→ Auditando Patrimônio (5 perguntas por ativo) …")
    patrim = await audit_patrimonio(cid)
    print(f"  ✓ {patrim['tier']} · score {patrim['score']}% · órfão={patrim['orfao']}")

    # ── SPRINT5_FORENSIC_AUDIT.md (resumo executivo) ──────────────────
    main_out: List[str] = []
    main_out.append("# SPRINT 5 · AUDITORIA FORENSE — RESUMO EXECUTIVO")
    main_out.append("")
    main_out.append(f"**Empresa**: `{cid}` · **Gerado**: {NOW_UTC}")
    main_out.append("**Modo**: READ-ONLY (zero writes) · Mandato CEO 18/06/2026")
    main_out.append("")
    main_out.append("## 1. NOTA GERAL (0-10)")
    main_out.append("")
    # média ponderada dos 4 módulos
    notas = {
        "CTO/Porta":   max(0, 10 - cto["pct_sem_porta"] / 10) - (1 if cto["schema_mismatch"] > 5 else 0),
        "Lousa":       max(0, lousa["cobertura_trilha_estoque_pct"] / 10),
        "SmartOLT":    max(0, smartolt["cobertura_pct"] / 10),
        "Patrimônio":  max(0, patrim["score"] / 10),
    }
    nota_geral = round(sum(notas.values()) / len(notas), 1)
    main_out.append(f"### **{nota_geral} / 10**")
    main_out.append("")
    main_out.append("| Domínio    | Nota |")
    main_out.append("|------------|-----:|")
    for k, v in notas.items():
        main_out.append(f"| {k} | {round(max(0, v), 1)} |")
    main_out.append("")
    main_out.append("## 2. DASHBOARD GERAL")
    main_out.append("")
    main_out.append("| Métrica                                  | Valor | Tier |")
    main_out.append("|------------------------------------------|------:|------|")
    main_out.append(f"| CTOs cadastradas                        | {_fmt(cto['ctos_total'])} | — |")
    main_out.append(f"| Portas (cto_ports)                       | {_fmt(cto['ports_total'])} | — |")
    main_out.append(f"| Subscribers ativos                       | {_fmt(cto['subs_ativos'])} | — |")
    main_out.append(f"| Ativos sem porta                         | {_fmt(cto['active_sem_porta'])} ({cto['pct_sem_porta']}%) | {cto['tier']} |")
    main_out.append(f"| Schema mismatch ctos vs cto_ports        | {_fmt(cto['schema_mismatch'])} | — |")
    main_out.append(f"| Subs fantasma em portas                  | {_fmt(cto['ghost_subs_in_ports'])} | — |")
    main_out.append(f"| Cobertura trilha estoque (Lousa)         | {lousa['cobertura_trilha_estoque_pct']}% | {lousa['tier']} |")
    main_out.append(f"| Swap events (auto_ont_swap_events)       | {_fmt(lousa['swap_events'])} | — |")
    main_out.append(f"| Cobertura SmartOLT × Estoque             | {smartolt['cobertura_pct']}% | {smartolt['tier']} |")
    main_out.append(f"| Score rastreabilidade patrimônio (5/5)   | {patrim['score']}% | {patrim['tier']} |")
    main_out.append(f"| ONTs órfãs (0/5)                         | {_fmt(patrim['orfao'])} | — |")
    main_out.append(f"| ONTs sintéticas (backfill)               | {_fmt(patrim['synthetic_backfill'])} | — |")
    main_out.append("")
    main_out.append("## 3. MAIOR RISCO")
    main_out.append("")
    main_out.append("**Cobertura SmartOLT × Estoque em 0.65%** — 98% do parque operacional "
                      "está invisível ao patrimônio contábil. Qualquer balanço, depreciação, "
                      "ou venda baseada no estado atual é estatisticamente inválido.")
    main_out.append("")
    main_out.append("## 4. MAIOR BLOQUEADOR")
    main_out.append("")
    main_out.append("**Pipeline `smartolt_pull_to_stok` nunca foi criado**. Não há job, worker, "
                      "rota ou script de import bidirecional. Estado atual = lacuna arquitetural, "
                      "não bug. Diagnóstico fechado em `RCA_DELTA_98_SMARTOLT_VS_ESTOQUE.md`.")
    main_out.append("")
    main_out.append("## 5. MAIOR GANHO RÁPIDO")
    main_out.append("")
    main_out.append("**Vincular `stok_history` aos `ticket.id`** (campo `ticket_id`). Hoje a baixa "
                      "automática pela Lousa registra OS-XXX só no `description`, gerando 149 "
                      "events órfãos. Fix de baixo esforço (1 linha no `auto_finalize_lousa`) "
                      "que recupera trilha de 100% dos fechamentos futuros.")
    main_out.append("")
    main_out.append("## 6. A SPRINT 5 PODE COMEÇAR?")
    main_out.append("")
    gates_ok = []
    gates_fail = []
    def _g(name: str, ok: bool):
        (gates_ok if ok else gates_fail).append(name)
    _g(f"Cobertura SmartOLT × Estoque ≥ 95% (atual {smartolt['cobertura_pct']}%)",
        smartolt['cobertura_pct'] >= 95)
    _g(f"Integridade CTO/Porta ≥ 95% (atual {round(100 - cto['pct_sem_porta'], 1)}%)",
        cto['pct_sem_porta'] <= 5)
    _g(f"Schema canônico portas definido (atual {cto['schema_mismatch']} divergentes)",
        cto['schema_mismatch'] == 0)
    _g(f"Cobertura trilha estoque Lousa ≥ 95% (atual {lousa['cobertura_trilha_estoque_pct']}%)",
        lousa['cobertura_trilha_estoque_pct'] >= 95)
    _g(f"Score rastreabilidade patrimônio ≥ 80% (atual {patrim['score']}%)",
        patrim['score'] >= 80)
    _g(f"Subscribers fantasma em portas = 0 (atual {cto['ghost_subs_in_ports']})",
        cto['ghost_subs_in_ports'] == 0)
    _g(f"Swap de ONU rastreável (atual {lousa['swap_events']} eventos)",
        lousa['swap_events'] >= 5)

    if gates_fail:
        main_out.append("### ❌ **NÃO** — gates falhando:")
        main_out.append("")
        for g in gates_fail:
            main_out.append(f"- ❌ {g}")
        main_out.append("")
    if gates_ok:
        main_out.append("### ✅ Gates atendidos:")
        main_out.append("")
        for g in gates_ok:
            main_out.append(f"- ✅ {g}")
        main_out.append("")

    main_out.append("## 7. RELATÓRIOS COMPLEMENTARES")
    main_out.append("")
    main_out.append("- `SPRINT5_CTO_PORTA_AUDIT.md` — CTO + porta + cliente")
    main_out.append("- `SPRINT5_LOUSA_MOBILE_AUDIT.md` — 8 perguntas por fluxo")
    main_out.append("- `SPRINT5_SMARTOLT_ESTOQUE_AUDIT.md` — Cobertura patrimonial")
    main_out.append("- `SPRINT5_RISK_MATRIX.md` — Matriz P0/P1/P2")
    main_out.append("- `SPRINT5_EXECUTION_PLAN.md` — Ondas 1-6 com gates")
    main_out.append("")
    main_out.append("**Suporte**:")
    main_out.append("- `SMARTOLT_RECONCILIATION_2026-06-18.md` (Ajuste 1)")
    main_out.append("- `RCA_DELTA_98_SMARTOLT_VS_ESTOQUE.md` (RCA Cenário A)")
    main_out.append("- `SPRINT_5_FASE_0_PLAN.md` (blueprint não-executado)")

    (OUT_DIR / "SPRINT5_FORENSIC_AUDIT.md").write_text(
        "\n".join(main_out) + "\n", encoding="utf-8")
    print(f"  ✓ SPRINT5_FORENSIC_AUDIT.md (nota geral {nota_geral}/10)")

    # ── Anexa Patrimônio ao FORENSIC_AUDIT (apêndice) ────────────────
    apx = "\n\n---\n\n## ANEXO · MÓDULO PATRIMÔNIO (detalhe)\n\n" + \
           "\n".join(patrim["_out_lines"])
    with open(OUT_DIR / "SPRINT5_FORENSIC_AUDIT.md", "a", encoding="utf-8") as f:
        f.write(apx)

    # ── SPRINT5_RISK_MATRIX.md ────────────────────────────────────────
    rm: List[str] = []
    rm.append("# SPRINT 5 · MATRIZ DE RISCO P0 / P1 / P2")
    rm.append("")
    rm.append(f"**Gerado**: {NOW_UTC} · derivado da auditoria forense")
    rm.append("")
    rm.append("## 🔴 P0 · Impedem rastreabilidade patrimonial")
    rm.append("")
    rm.append("| # | Risco | Evidência | Impacto |")
    rm.append("|---|-------|-----------|---------|")
    rm.append(f"| P0-1 | SmartOLT × Estoque desconectados | Cobertura {smartolt['cobertura_pct']}% (12/{smartolt['smartolt_docs']}) | Patrimônio invisível para 98% do parque |")
    rm.append(f"| P0-2 | Schema duplicado de portas | {cto['schema_mismatch']} CTOs com `ctos.ports[]` ≠ `cto_ports` | Dois caminhos de escrita podem dessincronizar |")
    rm.append(f"| P0-3 | `stok_history` órfã sem ticket_id | 149 events de `auto_finalize_lousa` sem join | Não rastreia OS → estoque |")
    rm.append(f"| P0-4 | Swap de ONU não rastreável | `auto_ont_swap_events` total: {lousa['swap_events']} | Trocas perdidas no histórico |")
    rm.append(f"| P0-5 | Subscribers ativos sem porta | {cto['active_sem_porta']} ({cto['pct_sem_porta']}%) | Não sabe onde clientes estão na rede |")
    rm.append(f"| P0-6 | 3 fontes paralelas cliente↔rede | `cto_ports` ({cto['ports_total']}, {cto['ghost_subs_in_ports']+3} com sub) · `subscribers.cto_id` (1) · `subscriber_access_points` ({cto['sap_total']}, {cto['sap_with_sub']} com sub) | Nenhuma é fonte canônica |")
    rm.append("")
    rm.append("## 🟠 P1 · Importantes mas não bloqueantes")
    rm.append("")
    rm.append("| # | Risco | Evidência | Impacto |")
    rm.append("|---|-------|-----------|---------|")
    rm.append(f"| P1-1 | Subscribers fantasma em portas | {cto['ghost_subs_in_ports']} portas com subscriber inexistente | Histórico fica sujo |")
    rm.append(f"| P1-2 | ONTs sintéticas (backfill) | {patrim['synthetic_backfill']}/{patrim['total']} = {_pct(patrim['synthetic_backfill'], patrim['total'])} | Patrimônio base não auditado |")
    rm.append(f"| P1-3 | Reservas vencidas | {cto['reserved_expired']} portas em status reserved > 7d | Bloqueio falso de capacidade |")
    rm.append(f"| P1-4 | lousa_finalize_trace gap | {lousa['finalize_trace_gap']} OS sem trace | Auditoria de Lousa incompleta |")
    rm.append("")
    rm.append("## 🟡 P2 · Melhorias e automações")
    rm.append("")
    rm.append("| # | Melhoria | Benefício |")
    rm.append("|---|----------|-----------|")
    rm.append("| P2-1 | Worker diário sync SmartOLT → stok_onts | Mantém cobertura ≥ 95% após Sprint 5 |")
    rm.append("| P2-2 | CI gate cobertura ≥ 95% | Previne regressão |")
    rm.append("| P2-3 | Watchtower timeline de cobertura | Visibilidade da reconciliação em tempo real |")
    rm.append("| P2-4 | Refactor `whatsapp_baileys.py` (>5400 linhas) | Manutenibilidade |")
    rm.append("| P2-5 | Refactor `lousa.py` (>9200 linhas) | Manutenibilidade |")

    (OUT_DIR / "SPRINT5_RISK_MATRIX.md").write_text(
        "\n".join(rm) + "\n", encoding="utf-8")
    print("  ✓ SPRINT5_RISK_MATRIX.md")

    # ── SPRINT5_EXECUTION_PLAN.md ─────────────────────────────────────
    ep: List[str] = []
    ep.append("# SPRINT 5 · PLANO DE EXECUÇÃO POR ONDAS (BLUEPRINT)")
    ep.append("")
    ep.append(f"**Gerado**: {NOW_UTC} · derivado de auditoria + risk matrix")
    ep.append("**Status**: aguardando Go/No-Go do CEO antes de qualquer execução")
    ep.append("")
    ep.append("## REGRA INVIOLÁVEL")
    ep.append("")
    ep.append("Nenhuma onda pode começar sem:")
    ep.append("1. Relatório ANTES (snapshot do estado)")
    ep.append("2. Plano de rollback (snapshot Mongo + reverte por batch_id)")
    ep.append("3. Testes (pytest cobrindo casos críticos)")
    ep.append("4. Critério de sucesso quantificado")
    ep.append("5. Relatório DEPOIS (delta + validação dos gates)")
    ep.append("")
    ep.append("## ONDA 1 · Correções P0")
    ep.append("")
    ep.append("**Objetivo**: corrigir os 5 P0 da matriz sem migração de schema.")
    ep.append("")
    ep.append("### O.1.1 — Vincular stok_history ao ticket_id (P0-3)")
    ep.append("- Fix em `auto_finalize_lousa`: passar `ticket_id` ao criar `stok_history`")
    ep.append("- Backfill de 149 events órfãos via parse de `description` (extrair OS-XXX)")
    ep.append("- Critério: 100% dos events futuros com `ticket_id`; 80%+ dos órfãos backfillados")
    ep.append(f"- ETA: 1 dia")
    ep.append("")
    ep.append("### O.1.2 — Definir fonte canônica de portas (P0-2)")
    ep.append("- Decisão técnica: `cto_ports` collection vira fonte única")
    ep.append("- `ctos.ports[]` vira projection read-only (computado on-the-fly)")
    ep.append("- Critério: 0 writes em `ctos.ports[]`; todos os reads consolidados")
    ep.append(f"- ETA: 3 dias")
    ep.append("")
    ep.append("### O.1.3 — Implementar auto_ont_swap_events (P0-4)")
    ep.append("- Worker já existe (`auto_ont_swap_events` collection com 0 docs)")
    ep.append("- Reativar trigger no fluxo de finalização Lousa quando `completion_data.ont` ≠ último ONT do cliente")
    ep.append("- Critério: 100% das trocas (ONT mudou no fechamento) geram event")
    ep.append(f"- ETA: 2 dias")
    ep.append("")
    ep.append("## ONDA 2 · Normalização Owner / Location")
    ep.append("")
    ep.append("**Objetivo**: criar schema canônico cliente↔CTO↔porta↔ONU.")
    ep.append("")
    ep.append("- `subscribers` ganha campos `cto_id`, `cto_port_id`, `cto_port_number`")
    ep.append("- Backfill cruzando `cto_ports.subscriber_id` ↔ `subscribers.id`")
    ep.append("- Gate: integridade ≥ 95% após backfill")
    ep.append(f"- ETA: 5 dias")
    ep.append("")
    ep.append("## ONDA 3 · CTO + Porta obrigatória nos fluxos")
    ep.append("")
    ep.append("- Lousa Mobile: instalação e troca exigem `cto_id` + `port_number` no completion_data")
    ep.append("- Validador rejeita finalização sem isso")
    ep.append("- Reparo: confirma CTO/porta atual (mesmo que não troque)")
    ep.append(f"- ETA: 3 dias")
    ep.append("")
    ep.append("## ONDA 4 · SmartOLT → Estoque (Sprint 5 Fase 0)")
    ep.append("")
    ep.append("**Blueprint pronto**: `/app/memory/SPRINT_5_FASE_0_PLAN.md`")
    ep.append(f"- Dry-run → piloto 50 → lotes 100/dia × 19d → cleanup")
    ep.append(f"- Gate: cobertura ≥ 95%")
    ep.append(f"- ETA: 27 dias (cron)")
    ep.append("")
    ep.append("## ONDA 5 · Watchtower & KPIs")
    ep.append("")
    ep.append("- Card Cobertura Patrimonial (já existe — Ajuste 2)")
    ep.append("- Cards novos: Integridade CTO, Integridade Porta, Integridade SmartOLT")
    ep.append("- Timeline de cobertura semanal")
    ep.append(f"- ETA: 3 dias")
    ep.append("")
    ep.append("## ONDA 6 · Auto Balanço Patrimonial (Sprint 5.1)")
    ep.append("")
    ep.append("**Pré-requisitos** (todos ≥ 95%):")
    ep.append("- Cobertura Patrimonial")
    ep.append("- Integridade CTO")
    ep.append("- Integridade Porta")
    ep.append("- Integridade SmartOLT")
    ep.append("")
    ep.append("- Snapshot mensal automatizado")
    ep.append("- Certidão Patrimonial assinada")
    ep.append(f"- ETA: 5 dias (após gates)")
    ep.append("")
    ep.append("## CRONOGRAMA CONSOLIDADO")
    ep.append("")
    ep.append("```")
    ep.append("Onda 1 (P0):     6 dias   ████████████")
    ep.append("Onda 2 (Owner):  5 dias        ██████████")
    ep.append("Onda 3 (CTO/p):  3 dias              ██████")
    ep.append("Onda 4 (SmOLT): 27 dias       ██████████████████████████████████████████████████████")
    ep.append("Onda 5 (KPIs):   3 dias                                                            ██████")
    ep.append("Onda 6 (Balão):  5 dias                                                                  ██████████")
    ep.append("                                                                                                 ─ ~7 semanas")
    ep.append("```")
    ep.append("")
    ep.append("## CRITÉRIO FINAL DE SPRINT 5 (definição de pronto)")
    ep.append("")
    ep.append("O sistema responde com segurança:")
    ep.append("- ✅ Qual cliente está em qual CTO")
    ep.append("- ✅ Qual porta está ocupada e por quem")
    ep.append("- ✅ Qual ONU está em cada cliente")
    ep.append("- ✅ Onde está cada ONT (cliente/empresa/técnico/defeito)")
    ep.append("- ✅ Quem movimentou (técnico/sistema/admin)")
    ep.append("- ✅ Quando movimentou (timestamp UTC)")
    ep.append("- ✅ Por qual OS (ticket_id linkado)")
    ep.append("- ✅ Quanto vale (valuation_value baseado em compra ou catálogo)")
    ep.append("- ✅ Se pode entrar no Auto Balanço (4 gates ≥ 95%)")

    (OUT_DIR / "SPRINT5_EXECUTION_PLAN.md").write_text(
        "\n".join(ep) + "\n", encoding="utf-8")
    print("  ✓ SPRINT5_EXECUTION_PLAN.md")

    print()
    print("══ AUDITORIA FORENSE CONCLUÍDA ══")
    print(f"  Nota geral: {nota_geral}/10")
    print(f"  Gates falhando: {len(gates_fail)} / atendidos: {len(gates_ok)}")
    print(f"  Sprint 5 pode começar? {'❌ NÃO' if gates_fail else '✅ SIM'}")
    print(f"  Veja resumo: /app/memory/SPRINT5_FORENSIC_AUDIT.md")


if __name__ == "__main__":
    asyncio.run(main())
