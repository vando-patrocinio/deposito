"""ai_center_home.py — Endpoint executivo único da FASE 5.

Responde em <2s: KPIs consolidados + briefing executivo em linguagem natural.
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException
from rbac import require_roles
from database import db
from services import (revenue_attribution as rev, data_quality_v2 as dq,
                       nervous_coverage as nc, smartolt_twin as twin)

router = APIRouter(prefix="/api/ai-center", tags=["ai-center"])


def _co(user):
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid: raise HTTPException(400, "company_id ausente")
    return cid


def _now() -> datetime: return datetime.now(timezone.utc)


def _fmt_brl(n) -> str:
    return f"R$ {(n or 0):,.2f}"


@router.get("/executive-summary")
async def executive_summary(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    """KPIs consolidados + briefing do Presidente IA."""
    company_id = _co(user)
    since_mtd = _now().replace(day=1, hour=0, minute=0,
                                  second=0, microsecond=0)
    since_24h = _now() - timedelta(hours=24)

    # KPIs financeiros (MTD)
    s = await rev.summary(company_id, since=since_mtd)
    # KPI dados
    dqr = await dq.full_report(company_id)
    # KPI sistema nervoso (today)
    nsh = await nc.what_happened_today(company_id)
    # KPI rede
    rev_risk = await twin.revenue_at_risk(company_id)
    worry = await twin.what_to_worry(company_id)
    # Decisions + Actions
    decisions_count = await db.motor_ia_decisions.count_documents(
        {"company_id": company_id, "created_at": {"$gte": since_24h.isoformat()}})
    actions_count = await db.motor_ia_actions.count_documents(
        {"company_id": company_id, "created_at": {"$gte": since_24h.isoformat()}})
    actions_done = await db.motor_ia_actions.count_documents(
        {"company_id": company_id, "status": "done",
         "created_at": {"$gte": since_24h.isoformat()}})

    # Predictions
    preds = await twin.predictions(company_id)
    subs_at_risk = preds["CHURN_BY_SIGNAL"]["predicted_count"]

    kpis = {
        "receita_gerada_MTD": s["_total_BRL"],
        "receita_recuperada_MTD": s["recovered"]["total_BRL"],
        "receita_em_risco_mensal": rev_risk["monthly_BRL_at_risk"],
        "churn_previsto_30d": subs_at_risk,
        "clientes_em_risco": rev_risk["subs_in_bad_onu"]
                              + rev_risk["subs_in_critical_cto"],
        "ctos_criticas": len(rev_risk["critical_ctos"]),
        "data_quality_score": dqr["overall_score"],
        "data_quality_level": dqr["overall_level"],
        "eventos_hoje": sum(nsh["domain_counts"].values()),
        "decisoes_24h": decisions_count,
        "acoes_24h": actions_count,
        "acoes_executadas_24h": actions_done,
        "nervous_coverage_pct": nsh["coverage_today_pct"],
        "nervous_coverage_level": nsh["coverage_level"],
    }

    # Briefing em linguagem natural
    nervous = nsh["domain_counts"]
    n_vendas = nervous.get("comercial", 0)
    n_pag = nervous.get("financeiro", 0)
    n_tickets = nervous.get("atendimento", 0)
    n_inst = nervous.get("instalacoes", 0)
    n_wa = nervous.get("whatsapp", 0)

    status_word = (
        "saudável" if dqr["overall_score"] >= 90
                       and kpis["ctos_criticas"] == 0
        else "em atenção" if dqr["overall_score"] >= 80
        else "em alerta"
    )
    attention = worry["qual_cto_preocupa"]

    briefing = (
        f"Hoje a empresa está **{status_word}**.\n\n"
        f"Nas últimas 24h foram registrados:\n"
        f"  • {n_vendas} eventos comerciais\n"
        f"  • {n_pag} eventos financeiros\n"
        f"  • {n_inst} eventos de instalação\n"
        f"  • {n_tickets} tickets\n"
        f"  • {n_wa} mensagens WhatsApp\n"
        f"  • {kpis['decisoes_24h']} decisões da IA + "
            f"{kpis['acoes_24h']} ações ({kpis['acoes_executadas_24h']} concluídas)\n\n"
        f"**Receita gerada pela IA (MTD):** {_fmt_brl(kpis['receita_gerada_MTD'])}\n"
        f"**Receita recuperada (MTD):** {_fmt_brl(kpis['receita_recuperada_MTD'])}\n"
        f"**Receita em risco (mensal):** {_fmt_brl(kpis['receita_em_risco_mensal'])}\n"
        f"**Clientes em risco:** {kpis['clientes_em_risco']} subs · "
            f"**CTOs críticas:** {kpis['ctos_criticas']}\n"
        f"**Qualidade dos dados:** {kpis['data_quality_score']}% "
            f"({kpis['data_quality_level']})\n\n"
        f"**Principal atenção:** {attention}\n"
        f"**Onde investir primeiro:** {worry['onde_investir_primeiro']}\n"
        f"**Próximo problema previsto (30d):** "
            f"{worry['predicted_next_problem_30d']}"
    )

    return {
        "company_id": company_id,
        "generated_at": _now().isoformat(),
        "kpis": kpis,
        "briefing": briefing,
        "headline": f"Empresa {status_word.upper()}",
        "alert_level": (
            "VERDE" if status_word == "saudável"
            else "AMARELO" if status_word == "em atenção"
            else "VERMELHO"
        ),
    }


@router.get("/decisions")
async def get_decisions(
    limit: int = 50,
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    company_id = _co(user)
    cur = db.motor_ia_decisions.find(
        {"company_id": company_id}).sort("created_at", -1).limit(limit)
    items = []
    async for d in cur:
        d.pop("_id", None)
        items.append(d)
    return {"items": items}


@router.get("/actions")
async def get_actions(
    limit: int = 50,
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    company_id = _co(user)
    cur = db.motor_ia_actions.find(
        {"company_id": company_id}).sort("created_at", -1).limit(limit)
    items = []
    async for d in cur:
        d.pop("_id", None)
        items.append(d)
    # Estatísticas
    total = await db.motor_ia_actions.count_documents(
        {"company_id": company_id})
    done = await db.motor_ia_actions.count_documents(
        {"company_id": company_id, "status": "done"})
    failed = await db.motor_ia_actions.count_documents(
        {"company_id": company_id, "status": "failed"})
    return {"items": items, "stats": {
        "total": total, "done": done, "failed": failed,
        "success_rate": round(done / max(total, 1) * 100, 1),
    }}


@router.get("/learnings")
async def get_learnings(
    limit: int = 50,
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    company_id = _co(user)
    cur = db.motor_ia_learnings.find(
        {"company_id": company_id}).sort("created_at", -1).limit(limit)
    items = []
    async for d in cur:
        d.pop("_id", None)
        items.append(d)
    # Top templates que convertem (vem de rev attribution)
    top_templates = await rev.by_template(company_id, limit=10)
    return {"items": items, "top_templates": top_templates}
