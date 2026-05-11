"""AI Topology — endpoint que retorna o fluxograma das IAs e volume de dados.

Calcula em tempo-real: chamadas LLM nas últimas 24h por agente + edges
(qual IA passou dado pra qual nas últimas 24h).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends

from core import DEMO_COMPANY_ID, require_role
from database import db

router = APIRouter(prefix="/api/ai-topology", tags=["ai-topology"])


@router.get("/flow")
async def topology_flow(user: dict = Depends(require_role("gestor"))) -> Dict[str, Any]:
    """Retorna nós (IAs) + arestas (fluxo de dados nas últimas 24h)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    # Contadores reais
    wa_inbound = await db.aihub_wa_messages.count_documents(
        {"company_id": cid, "direction": "inbound", "created_at": {"$gte": cutoff}})
    wa_ai_replies = await db.aihub_wa_messages.count_documents(
        {"company_id": cid, "direction": "outbound", "auto_reply": True,
         "created_at": {"$gte": cutoff}})
    wa_human_replies = await db.aihub_wa_messages.count_documents(
        {"company_id": cid, "direction": "outbound", "auto_reply": {"$ne": True},
         "sent_by_user_id": {"$nin": [None, ""]},
         "created_at": {"$gte": cutoff}})
    evaluations = await db.aihub_evaluations.count_documents(
        {"company_id": cid, "evaluated_at": {"$gte": cutoff}})
    coachings = await db.ai_coaching.count_documents(
        {"company_id": cid, "created_at": {"$gte": cutoff}})
    outages_active = await db.network_outages.count_documents(
        {"company_id": cid, "status": "active"})
    outages_detected = await db.network_outages.count_documents(
        {"company_id": cid, "first_detected_at": {"$gte": cutoff}})
    # Quantas conversas tinham contexto de outage (cliente afetado)
    outage_aware = 0
    async for o in db.network_outages.find(
        {"company_id": cid, "status": "active"},
        {"_id": 0, "affected_phones": 1},
    ):
        outage_aware += len(o.get("affected_phones") or [])
    # Few-shots ativos (CSAT >= 8 últimos 30d)
    cutoff_30 = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    high_csat = await db.aihub_evaluations.count_documents(
        {"company_id": cid, "csat_score": {"$gte": 8},
         "evaluated_at": {"$gte": cutoff_30}})

    nodes = [
        {"id": "smartolt", "label": "SmartOLT AI",
         "subtitle": "Monitoramento", "icon": "Radio", "color": "#0d9488",
         "metric": f"{outages_active} ativos",
         "metric_sub": f"{outages_detected} novos/24h"},
        {"id": "atendimento", "label": "Isabella IA",
         "subtitle": "Atendimento WhatsApp", "icon": "Bot", "color": "#16a34a",
         "metric": f"{wa_ai_replies} respostas/24h",
         "metric_sub": f"{wa_inbound} recebidas"},
        {"id": "evaluator", "label": "Avaliador IA",
         "subtitle": "Central IA", "icon": "Award", "color": "#0ea5e9",
         "metric": f"{evaluations} avaliações/24h",
         "metric_sub": "CSAT/Sentimento/FCR"},
        {"id": "coach", "label": "Coach IA",
         "subtitle": "Recomendações", "icon": "GraduationCap", "color": "#a855f7",
         "metric": f"{coachings} coachings/24h",
         "metric_sub": "Inline no chat"},
        {"id": "learning", "label": "Aprendizado",
         "subtitle": "Few-shot loop", "icon": "Sparkles", "color": "#eab308",
         "metric": f"{high_csat} exemplos",
         "metric_sub": "CSAT≥8 nos últimos 30d"},
        {"id": "human", "label": "Atendente Humano",
         "subtitle": "Operação", "icon": "Users", "color": "#64748b",
         "metric": f"{wa_human_replies} mensagens/24h",
         "metric_sub": "Mensagens enviadas"},
    ]

    # Arestas (origem → destino) com volume real
    edges = [
        {"from": "smartolt", "to": "atendimento", "value": outage_aware,
         "label": "Contexto de pane", "desc": "Clientes em outage avisados proativamente"},
        {"from": "atendimento", "to": "evaluator", "value": wa_ai_replies + wa_human_replies,
         "label": "Conversas → análise"},
        {"from": "evaluator", "to": "coach", "value": evaluations,
         "label": "Avaliações → coaching"},
        {"from": "evaluator", "to": "learning", "value": high_csat,
         "label": "CSAT alto → exemplos"},
        {"from": "learning", "to": "atendimento", "value": high_csat,
         "label": "Few-shots no prompt"},
        {"from": "coach", "to": "human", "value": coachings,
         "label": "Sugestões pro atendente"},
        {"from": "human", "to": "atendimento", "value": wa_human_replies,
         "label": "Handover (Assumir)"},
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "totals": {
            "wa_inbound_24h": wa_inbound,
            "wa_ai_24h": wa_ai_replies,
            "wa_human_24h": wa_human_replies,
            "evaluations_24h": evaluations,
            "coachings_24h": coachings,
            "outages_active": outages_active,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
