"""
presidente_evolution.py — V20 Diretor de Evolução Contínua.

Fases:
  1. backlog_executivo()     — gargalos → itens de backlog
  2. gerar_sprints()         — agrupa por ROI/h em sprints
  3. arquiteto_automatico()  — plano técnico por item (sem código)
  4. auditor_execucao()      — diff prometido vs entregue por sprint
  5. roadmap_12m()           — 30/90/180/365d × 1k/10k/50k

100% reuso. 0 coleções novas persistentes (apenas `evolution_sprints`
opcional para histórico — única coleção pequena).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(p): return f"{p}-{uuid.uuid4().hex[:10]}"


# Mapas técnicos por gargalo (plano sem código)
ARCH_PLAN: Dict[str, Dict[str, Any]] = {
    "backup_offsite_quebrado": {
        "arquivos": ["services/drive_backup.py"],
        "rotas": ["/api/oauth/drive/connect",
                    "/api/drive/backup"],
        "collections": ["drive_oauth_tokens", "drive_backups"],
        "riscos": ["interrupção temporária de backup"],
        "testes": ["test_drive_oauth_flow",
                     "test_drive_backup_manual"],
        "rollback": "Desativar S3 fallback se incidente"},
    "allow_mock_em_prod": {
        "arquivos": ["backend/.env"],
        "rotas": ["/api/security/* (503 esperado)"],
        "collections": [],
        "riscos": ["SecurityHome retorna 503"],
        "testes": ["smoke test 322 endpoints"],
        "rollback": "Restaurar .env e restart"},
    "ai_center_versoes_coexistindo": {
        "arquivos": ["routes/ai_center_v6.py",
                       "routes/ai_center_v7.py"],
        "rotas": ["/api/ai-center/v6/*", "/v7/*"],
        "collections": [],
        "riscos": ["consumer externo desconhecido"],
        "testes": ["grep frontend + services"],
        "rollback": "Remover Deprecation header"},
    "col_sem_indice_subscriber_match_log": {
        "arquivos": ["migrations/idx_match_log.py"],
        "rotas": [],
        "collections": ["subscriber_match_log"],
        "riscos": ["lock durante createIndex em 392k docs"],
        "testes": ["explain plan antes/depois"],
        "rollback": "dropIndex"},
    "col_sem_indice_smartolt_onus": {
        "arquivos": ["migrations/idx_onus.py"],
        "rotas": [],
        "collections": ["smartolt_onus"],
        "riscos": ["lock leve"],
        "testes": ["explain plan"],
        "rollback": "dropIndex"},
    "tenant_unico": {
        "arquivos": [],
        "rotas": ["/api/admin/companies"],
        "collections": ["companies"],
        "riscos": ["enxergar dados cruzados sem RBAC"],
        "testes": ["test_multi_tenant_isolation"],
        "rollback": "delete tenants de teste"},
    "scheduler_single_node": {
        "arquivos": ["server.py", "services/scheduler_lock.py"],
        "rotas": [],
        "collections": ["scheduler_locks"],
        "riscos": ["jobs duplicados durante migração"],
        "testes": ["test_distributed_lock"],
        "rollback": "voltar APScheduler simples"},
    "wa_baileys_stateful": {
        "arquivos": ["routes/whatsapp_baileys.py"],
        "rotas": ["/api/whatsapp/*"],
        "collections": ["wa_auth_state"],
        "riscos": ["sessões perdem reconexão"],
        "testes": ["E2E Baileys 4 instâncias"],
        "rollback": "voltar para Mongo state"},
    "sem_s3_redundancia": {
        "arquivos": ["services/s3_backup.py"],
        "rotas": ["/api/backup/s3/status"],
        "collections": ["s3_backups"],
        "riscos": ["custo AWS"],
        "testes": ["test_s3_upload_download"],
        "rollback": "desativar cron S3"},
    "executor_em_dry_run": {
        "arquivos": [],
        "rotas": ["/api/presidente-ia/actions/{id}/execute"],
        "collections": ["motor_ia_actions", "motor_ia_kpis"],
        "riscos": ["1ª execução real altera dados produtivos"],
        "testes": ["validar reversibilidade reajuste"],
        "rollback": "unset readjustment_pending_*"},
}


# ───────────── FASE 1 — Backlog Executivo ─────────────
async def backlog_executivo(company_id: str) -> Dict[str, Any]:
    from services.presidente_self_audit import (autoconsciencia,
                                                     conselho_evolucao)
    aud = await autoconsciencia(company_id)
    evo = await conselho_evolucao(company_id)

    # Junta gargalos × plano de evolução por id
    evo_by_origem = {e["gargalo_origem"]: e
                       for e in evo["top_10_evolucoes"]}

    items = []
    for g in aud["top_20_gargalos"]:
        eplan = evo_by_origem.get(g["id"], {})
        items.append({
            "id": _new_id("bl"),
            "gargalo_id": g["id"],
            "area": g["area"],
            "problema": g["descricao"],
            "impacto": g["impacto_descricao"],
            "causa_raiz": _causa_raiz(g["id"]),
            "solucao": eplan.get("evolucao") or
                          f"Endereçar: {g['descricao']}",
            "esforco_horas": eplan.get("esforco_horas", 16),
            "prazo_dias": eplan.get("prazo_dias", 30),
            "risco": eplan.get("risco", "MÉDIO"),
            "roi_brl": g["impacto_financeiro_brl"],
            "roi_brl_por_hora": eplan.get(
                "roi_brl_por_hora",
                round(g["impacto_financeiro_brl"]
                       / max(eplan.get("esforco_horas", 16), 1), 1)),
            "dependencias": eplan.get("dependencias", []),
            "prioridade_score": _prio(g, eplan),
            "status": "novo",
            "created_at": _now().isoformat(),
        })
    items.sort(key=lambda x: x["prioridade_score"], reverse=True)
    return {"company_id": company_id,
            "backlog_total": len(items),
            "top_20": items[:20],
            "valor_total_brl": round(sum(
                i["roi_brl"] for i in items), 2),
            "generated_at": _now().isoformat()}


def _causa_raiz(gid: str) -> str:
    M = {
        "backup_offsite_quebrado":
            "OAuth Google Drive sem refresh_token persistido",
        "allow_mock_em_prod":
            ".env preview ainda em produção",
        "ai_center_versoes_coexistindo":
            "Iteração rápida sem deprecation",
        "col_sem_indice_subscriber_match_log":
            "Migration de índice nunca rodou após volume",
        "col_sem_indice_smartolt_onus":
            "Coleção cresceu sem revisão de query plan",
        "tenant_unico": "Produto rodando apenas em dev tenant",
        "scheduler_single_node":
            "APScheduler sem backend de lock externo",
        "wa_baileys_stateful":
            "Sessão Baileys em-processo, fila não externalizada",
        "sem_s3_redundancia":
            "Off-site depende exclusivamente do Drive",
        "executor_em_dry_run":
            "P1 entregou braços mas dry_run nunca foi desligado",
    }
    return M.get(gid, "Causa não mapeada — investigação requerida")


def _prio(g, eplan):
    sev_w = {"ALTO": 3, "MÉDIO": 2, "BAIXO": 1}
    return (g["impacto_financeiro_brl"]
              * sev_w.get(g["impacto_financeiro"], 1)
              + sev_w.get(g["impacto_comercial"], 1) * 1000
              + sev_w.get(g["risco_operacional"], 1) * 500
              + (eplan.get("roi_brl_por_hora", 0) * 5))


# ───────────── FASE 2 — Gerador de Sprints ─────────────
async def gerar_sprints(company_id: str,
                            sprint_horas: int = 16) -> Dict[str, Any]:
    """Empilha backlog em sprints de N horas, ordenadas por
    ROI/h decrescente."""
    bl = await backlog_executivo(company_id)
    items = bl["top_20"][:]
    items.sort(key=lambda x: x["roi_brl_por_hora"], reverse=True)

    sprints = []
    cur_items: List[Dict] = []
    cur_h = 0.0
    cur_roi = 0.0
    cur_idx = 1
    for it in items:
        h = it["esforco_horas"]
        if cur_h + h > sprint_horas and cur_items:
            sprints.append(_close_sprint(cur_idx, cur_items,
                                              cur_h, cur_roi))
            cur_idx += 1
            cur_items = []
            cur_h = 0
            cur_roi = 0
        cur_items.append(it)
        cur_h += h
        cur_roi += it["roi_brl"]
    if cur_items:
        sprints.append(_close_sprint(cur_idx, cur_items, cur_h, cur_roi))

    return {"company_id": company_id,
            "sprint_horas_alvo": sprint_horas,
            "sprints": sprints[:10],
            "sprints_total": len(sprints),
            "generated_at": _now().isoformat()}


def _close_sprint(idx, items, h, roi):
    nome = f"Sprint {chr(64 + idx)}"  # A, B, C...
    return {
        "sprint_id": _new_id("spr"),
        "nome": nome,
        "items": items,
        "items_count": len(items),
        "esforco_horas": round(h, 1),
        "impacto_financeiro_brl": round(roi, 2),
        "roi_brl_por_hora": round(roi / max(h, 0.5), 1),
        "objetivo": _objetivo(items),
    }


def _objetivo(items):
    if not items:
        return ""
    areas = list({i["area"] for i in items})[:3]
    return f"Endereçar {len(items)} item(ns) nas áreas: " + ", ".join(
        areas)


# ───────────── FASE 3 — Arquiteto Automático ─────────────
async def arquiteto_item(backlog_id_or_gargalo: str) -> Dict[str, Any]:
    """Plano técnico para 1 item aprovado. Sem alterar código."""
    arch = ARCH_PLAN.get(backlog_id_or_gargalo, {
        "arquivos": ["(a definir)"], "rotas": [],
        "collections": [], "riscos": ["a avaliar"],
        "testes": ["smoke test"], "rollback": "git revert"})
    return {
        "gargalo_id": backlog_id_or_gargalo,
        "plano_tecnico": arch,
        "checklist_pre_deploy": [
            "branch feature/<gargalo_id>",
            "PR com link para este plano",
            "code review obrigatório",
            "rodar testes listados",
            "validar em staging",
            "comunicar janela de manutenção se aplicável",
        ],
        "generated_at": _now().isoformat(),
    }


# ───────────── FASE 4 — Auditor de Execução ─────────────
async def auditor_execucao_sprint(sprint_id: str) -> Dict[str, Any]:
    """Compara o que foi prometido (snapshot inicial) vs entregue
    (snapshot atual). Reusa motor_ia_kpis."""
    sprint = await db.evolution_sprints.find_one(
        {"sprint_id": sprint_id}, {"_id": 0})
    if not sprint:
        return {"sprint_id": sprint_id,
                "veredito": "sprint não encontrada",
                "msg": "registre o sprint via save_sprint() para auditar"}
    # Compara baseline vs atual
    baseline = sprint.get("baseline_metrics", {})
    cur = await _read_current_metrics(sprint["company_id"])
    prometido = sprint.get("impacto_financeiro_brl", 0)
    deltas = {}
    for k, vbase in baseline.items():
        deltas[k] = round((cur.get(k, vbase) or 0) - (vbase or 0), 2)
    melhorou = [k for k, d in deltas.items() if d > 0]
    piorou = [k for k, d in deltas.items() if d < 0]
    return {
        "sprint_id": sprint_id,
        "promessa_brl": prometido,
        "entregue_brl_estimado":
            sum(d for d in deltas.values() if d > 0),
        "deltas_metricas": deltas,
        "melhorou": melhorou,
        "piorou": piorou,
        "veredito": "ENTREGUE" if not piorou else
                      "PARCIAL" if melhorou else "REGRESSAO",
        "generated_at": _now().isoformat(),
    }


async def save_sprint_baseline(company_id: str,
                                    sprint: Dict[str, Any]) -> Dict:
    cur = await _read_current_metrics(company_id)
    rec = {**sprint, "company_id": company_id,
            "baseline_metrics": cur,
            "started_at": _now().isoformat()}
    await db.evolution_sprints.insert_one(rec)
    return rec


async def _read_current_metrics(company_id: str) -> Dict:
    from services.presidente_executive import build_executive_report
    rep = await build_executive_report(company_id)
    return {
        "mrr_brl": rep["contexto_financeiro"]["mrr_atual_brl"],
        "president_score": rep["president_score"]["score"],
        "dinheiro_em_risco_brl": rep["dinheiro_em_risco"]["total_brl"],
        "dinheiro_recuperavel_brl":
            rep["dinheiro_recuperavel"]["total_brl"],
    }


# ───────────── FASE 5 — Roadmap 12 meses ─────────────
async def roadmap_12m(company_id: str) -> Dict[str, Any]:
    from services.presidente_self_audit import prontidao_comercial
    prontidao = await prontidao_comercial(company_id)
    bl = await backlog_executivo(company_id)
    items = bl["top_20"]

    # Bucketiza por prazo
    def filt_prazo(d_max):
        return [i for i in items if i["prazo_dias"] <= d_max]

    d30 = filt_prazo(30)
    d90 = filt_prazo(90)
    d180 = filt_prazo(180)
    d365 = items

    def cont(it_list):
        return {
            "itens": len(it_list),
            "horas": round(sum(i["esforco_horas"]
                                  for i in it_list), 1),
            "roi_brl": round(sum(i["roi_brl"]
                                    for i in it_list), 2),
            "bloqueadores": [i["problema"]
                                for i in it_list
                                if i["risco"] == "ALTO"][:3],
            "dependencias": list({d
                                     for i in it_list
                                     for d in i["dependencias"]}),
        }

    return {
        "company_id": company_id,
        "30d": cont(d30),
        "90d": cont(d90),
        "180d": cont(d180),
        "365d": cont(d365),
        "por_escala": {
            "1k_clientes": prontidao["1000_clientes"],
            "10k_clientes": prontidao["10000_clientes"],
            "50k_clientes": prontidao["50000_clientes"],
        },
        "valor_total_brl_365d": round(
            sum(i["roi_brl"] for i in items), 2),
        "horas_total_365d": round(
            sum(i["esforco_horas"] for i in items), 1),
        "generated_at": _now().isoformat(),
    }
