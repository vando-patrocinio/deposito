"""
estrategista_ia.py — Sprint 9 / iter228
Agente ESTRATEGISTA_IA. Gera relatórios executivos com LLM.

Lê dados reais (events/decisions/outcomes/insights/audit_log) e usa
Claude Sonnet 4.5 (Emergent LLM Key) para gerar:
  - daily   : briefing das últimas 24h + prioridades de hoje
  - weekly  : tendências, riscos, oportunidades
  - monthly : desempenho vs metas + recomendações estratégicas

Cada relatório é cacheado em motor_ia_memory por 1h (daily) /
24h (weekly) / 7d (monthly) para evitar custo desnecessário.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from database import db


CACHE_TTL = {
    "daily": timedelta(hours=1),
    "weekly": timedelta(hours=24),
    "monthly": timedelta(days=7),
}

WINDOWS = {
    "daily": timedelta(hours=24),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
}

PROMPTS = {
    "daily": (
        "Você é o Estrategista IA do SmartProv (ERP-ISP). Gere um "
        "BRIEFING DIÁRIO em português brasileiro, tom executivo "
        "(2-3 parágrafos curtos) cobrindo:\n"
        "1) O QUE ACONTECEU nas últimas 24h (eventos mais críticos)\n"
        "2) DECISÕES tomadas e seus resultados\n"
        "3) 3 PRIORIDADES OBJETIVAS para hoje\n\n"
        "Seja direto. Use bullets quando útil. Cite números reais."),
    "weekly": (
        "Você é o Estrategista IA do SmartProv. Gere uma ANÁLISE "
        "SEMANAL em pt-BR, tom executivo (4-6 parágrafos). Cubra:\n"
        "1) TENDÊNCIAS (o que cresceu, o que caiu)\n"
        "2) RISCOS identificados (operacional/financeiro/segurança)\n"
        "3) OPORTUNIDADES (clientes, parcerias, expansão)\n"
        "4) RECOMENDAÇÕES para a próxima semana"),
    "monthly": (
        "Você é o Estrategista IA do SmartProv. Gere um RELATÓRIO "
        "MENSAL EXECUTIVO em pt-BR (6-10 parágrafos). Cubra:\n"
        "1) DESEMPENHO no mês (saúde, op, comercial, financeiro, "
        "segurança)\n"
        "2) PRINCIPAIS DECISÕES e seus outcomes\n"
        "3) GARGALOS e oportunidades de melhoria\n"
        "4) RECOMENDAÇÕES ESTRATÉGICAS para o próximo mês\n"
        "5) Investimentos sugeridos"),
}


async def _collect_context(period: str) -> Dict[str, Any]:
    """Junta um pacote de dados reais para alimentar o LLM."""
    since = (datetime.now(timezone.utc) - WINDOWS[period]).isoformat()

    # Contagens
    events_total = await db.motor_ia_events.count_documents(
        {"timestamp": {"$gte": since}})
    decisions_total = await db.motor_ia_decisions.count_documents(
        {"created_at": {"$gte": since}})
    actions_total = await db.motor_ia_actions.count_documents(
        {"created_at": {"$gte": since}})

    # Top tipos de eventos
    top_types = []
    async for r in db.motor_ia_events.aggregate([
        {"$match": {"timestamp": {"$gte": since}}},
        {"$group": {"_id": "$event_type", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 8}]):
        top_types.append({"type": r["_id"], "count": r["n"]})

    # Decisões
    decisions = []
    async for d in db.motor_ia_decisions.find(
        {"created_at": {"$gte": since}}, {"_id": 0}
    ).sort("created_at", -1).limit(20):
        decisions.append({
            "title": d.get("title"),
            "action_type": d.get("action_type"),
            "confidence": d.get("confidence"),
            "executed": d.get("executed"),
        })

    # Outcomes
    out_ok = await db.motor_ia_outcomes.count_documents(
        {"created_at": {"$gte": since}, "ok": True})
    out_fail = await db.motor_ia_outcomes.count_documents(
        {"created_at": {"$gte": since}, "ok": False})

    # Insights recentes (data_quality + executive_health)
    insights = []
    async for ins in db.motor_ia_insights.find(
        {"created_at": {"$gte": since}}, {"_id": 0}
    ).sort("created_at", -1).limit(3):
        insights.append({
            "kind": ins.get("kind"),
            "score": ins.get("score") or ins.get("overall_score"),
            "status": ins.get("status"),
        })

    # Audit summary
    audit_summary = {
        "deletes": await db.audit_log.count_documents(
            {"category": "destructive",
             "created_at": {"$gte": since}}),
        "exports": await db.audit_log.count_documents(
            {"category": "export", "created_at": {"$gte": since}}),
        "rbac_blocked": await db.audit_log.count_documents(
            {"category": "rbac_blocked",
             "created_at": {"$gte": since}}),
    }

    return {
        "period": period,
        "since": since,
        "metrics": {
            "events_total": events_total,
            "decisions_total": decisions_total,
            "actions_total": actions_total,
            "outcomes_ok": out_ok,
            "outcomes_fail": out_fail,
        },
        "top_event_types": top_types,
        "recent_decisions": decisions,
        "recent_insights": insights,
        "audit_summary": audit_summary,
    }


async def _cached(period: str) -> Dict[str, Any]:
    """Retorna relatório cacheado (ou None)."""
    cutoff = (datetime.now(timezone.utc) - CACHE_TTL[period]).isoformat()
    return await db.motor_ia_memory.find_one(
        {"kind": "estrategista_report",
         "period": period,
         "created_at": {"$gte": cutoff}},
        sort=[("created_at", -1)],
    )


async def generate_report(period: str = "daily",
                              force: bool = False) -> Dict[str, Any]:
    """Gera relatório usando LLM. Cache se disponível."""
    if period not in PROMPTS:
        raise ValueError(f"period inválido: {period}")

    if not force:
        cached = await _cached(period)
        if cached:
            cached.pop("_id", None)
            cached["cached"] = True
            return cached

    ctx = await _collect_context(period)

    # Pós-CTO audit (P2): budget guard
    from services.llm_budget import check_budget, increment
    budget = await check_budget(company_id=None)
    if not budget["ok"]:
        text = (
            f"# Briefing {period} (BLOQUEADO POR BUDGET)\n\n"
            f"O orçamento mensal do Estrategista IA foi atingido "
            f"({budget['used']}/{budget['limit']} chamadas em "
            f"{budget['ym']}). Para aumentar, ajuste "
            f"ESTRATEGISTA_BUDGET_MONTHLY.\n\n"
            f"Métricas do período:\n"
            f"- Eventos: {ctx['metrics']['events_total']}\n"
            f"- Decisões: {ctx['metrics']['decisions_total']}\n"
            f"- Ações: {ctx['metrics']['actions_total']}")
        report = {
            "id": f"rpt-{uuid.uuid4().hex[:12]}",
            "kind": "estrategista_report",
            "period": period,
            "title": {
                "daily": "Briefing Diário",
                "weekly": "Análise Semanal",
                "monthly": "Relatório Mensal Executivo",
            }[period],
            "text": text,
            "context": ctx,
            "llm_used": False,
            "error": "budget_exhausted",
            "budget_status": budget,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "cached": False,
        }
        try:
            await db.motor_ia_memory.insert_one(dict(report))
        except Exception:
            pass
        report.pop("_id", None)
        return report

    # Chama LLM via emergentintegrations
    text = None
    error = None
    api_key = os.environ.get("EMERGENT_LLM_KEY") \
        or os.environ.get("ANTHROPIC_API_KEY")
    try:
        if not api_key:
            raise RuntimeError("EMERGENT_LLM_KEY ausente")
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=api_key,
            session_id=f"estrategista-{period}-{uuid.uuid4().hex[:8]}",
            system_message=PROMPTS[period],
        ).with_model("anthropic", "claude-sonnet-4-5")
        msg = UserMessage(text=(
            f"Dados reais do SmartProv para o período {period}:\n\n"
            f"{json.dumps(ctx, ensure_ascii=False, indent=2)}\n\n"
            f"Gere o relatório seguindo o template do system."))
        text = await chat.send_message(msg)
        try:
            await increment(company_id=None)
        except Exception:
            pass
    except Exception as e:
        error = str(e)[:200]
        # Fallback: relatório determinístico baseado em contagens
        m = ctx["metrics"]
        text = (
            f"# Briefing {period} (modo fallback — LLM indisponível)\n\n"
            f"Últimas {WINDOWS[period].days or '24'} h/dias:\n"
            f"- {m['events_total']} eventos registrados\n"
            f"- {m['decisions_total']} decisões tomadas pelo Presidente IA\n"
            f"- {m['actions_total']} ações executadas "
            f"({m['outcomes_ok']} ok / {m['outcomes_fail']} falhas)\n"
            f"- Audit Trail: {ctx['audit_summary']['deletes']} deletes, "
            f"{ctx['audit_summary']['exports']} exports, "
            f"{ctx['audit_summary']['rbac_blocked']} 403s\n\n"
            f"Erro LLM: {error}")

    report = {
        "id": f"rpt-{uuid.uuid4().hex[:12]}",
        "kind": "estrategista_report",
        "period": period,
        "title": {
            "daily": "Briefing Diário",
            "weekly": "Análise Semanal",
            "monthly": "Relatório Mensal Executivo",
        }[period],
        "text": text,
        "context": ctx,
        "llm_used": error is None,
        "error": error,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }
    try:
        await db.motor_ia_memory.insert_one(dict(report))
    except Exception:
        pass
    report.pop("_id", None)
    return report
