"""AI Topology — endpoint que retorna o fluxograma das IAs e volume de dados.

Calcula em tempo-real: chamadas LLM nas últimas 24h por agente + edges
(qual IA passou dado pra qual nas últimas 24h).

Atualizações (11/05/2026):
- Adiciona nó "Co-Pilot IA" (dicas internas a atendentes humanos)
- Separa cada atendente humano como nó individual (1 quadro por usuário ativo)
- Quantifica edges Co-Pilot → cada atendente
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from core import DEMO_COMPANY_ID, require_role
from database import db
from services.motor_ia import (
    DEFAULT_TEXT_MODEL, ATENDIMENTO_MODEL, get_motor_config,
)

router = APIRouter(prefix="/api/ai-topology", tags=["ai-topology"])

MAX_HUMAN_NODES = 8   # mostra top-N atendentes humanos


@router.get("/flow")
async def topology_flow(user: dict = Depends(require_role("gestor"))) -> Dict[str, Any]:
    """Retorna nós (IAs + cada atendente humano) + arestas (volume real 24h)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    # Carrega configuração do Motor IA pra mostrar qual modelo cada IA usa
    try:
        motor_cfg = await get_motor_config(cid)
        ATENDIMENTO_M = motor_cfg.get("atendimento_model") or ATENDIMENTO_MODEL
        DEFAULT_M = motor_cfg.get("default_text_model") or DEFAULT_TEXT_MODEL
        TTS_VOICE = motor_cfg.get("tts_voice") or "nova"
        motor_enabled = bool(motor_cfg.get("enabled"))
    except Exception:
        ATENDIMENTO_M = ATENDIMENTO_MODEL
        DEFAULT_M = DEFAULT_TEXT_MODEL
        TTS_VOICE = "nova"
        motor_enabled = False

    # Contadores das IAs
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
    # Co-Pilot — dicas geradas nas últimas 24h
    try:
        from services.copilot_ai import count_hints_24h, hints_per_user_24h
        copilot_hints = await count_hints_24h(cid)
        hints_per_user = await hints_per_user_24h(cid)
    except Exception:
        copilot_hints = 0
        hints_per_user = {}
    # Sentinela Lousa — alertas ativos + novos 24h
    try:
        from services.sentinela_lousa import count_alerts_24h
        sentinela = await count_alerts_24h(cid)
    except Exception:
        sentinela = {"active": 0, "new_24h": 0, "resolved_24h": 0, "by_kind": {}}
    # Tickets ativos na Lousa (para a aresta Sentinela → Lousa)
    try:
        active_tickets = await db.tickets.count_documents({
            "company_id": cid,
            "status": {"$nin": ["finalizada", "cancelada", "encerrada", "reagendada"]},
        })
    except Exception:
        active_tickets = 0
    outage_aware = 0
    async for o in db.network_outages.find(
        {"company_id": cid, "status": "active"},
        {"_id": 0, "affected_phones": 1},
    ):
        outage_aware += len(o.get("affected_phones") or [])
    cutoff_30 = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    high_csat = await db.aihub_evaluations.count_documents(
        {"company_id": cid, "csat_score": {"$gte": 8},
         "evaluated_at": {"$gte": cutoff_30}})

    # ── ATENDENTES HUMANOS INDIVIDUAIS (top-N por volume 24h) ──────────
    # Agrega quantas msgs cada usuário enviou + quantas conversas pegou
    pipe = [
        {"$match": {"company_id": cid, "direction": "outbound",
                      "auto_reply": {"$ne": True},
                      "sent_by_user_id": {"$nin": [None, ""]},
                      "created_at": {"$gte": cutoff}}},
        {"$group": {"_id": "$sent_by_user_id",
                      "msgs": {"$sum": 1},
                      "convs": {"$addToSet": "$phone"}}},
        {"$project": {"msgs": 1, "conv_count": {"$size": "$convs"}}},
        {"$sort": {"msgs": -1}},
        {"$limit": MAX_HUMAN_NODES},
    ]
    rows = await db.aihub_wa_messages.aggregate(pipe).to_list(MAX_HUMAN_NODES)
    user_ids = [r["_id"] for r in rows]
    users_map: Dict[str, Dict[str, Any]] = {}
    if user_ids:
        async for u in db.users.find(
            {"id": {"$in": user_ids}},
            {"_id": 0, "id": 1, "name": 1, "email": 1, "is_ai_agent": 1},
        ):
            users_map[u["id"]] = u

    human_nodes: List[Dict[str, Any]] = []
    human_edges_in: List[Dict[str, Any]] = []   # entrada (IAs → cada humano)
    human_edges_out: List[Dict[str, Any]] = []  # saída (humano → atendimento)
    for r in rows:
        uid = r["_id"]
        u = users_map.get(uid) or {}
        # Skip IAs registradas como usuário (Isabella, Jerusa, etc)
        if u.get("is_ai_agent"):
            continue
        name = u.get("name") or u.get("email") or uid
        short = (name or "").strip().split()[0] if name else "Atendente"
        node_id = f"human_{uid}"
        hints_for_user = hints_per_user.get(uid, 0)
        human_nodes.append({
            "id": node_id,
            "label": short,
            "subtitle": (u.get("email") or uid)[:28],
            "icon": "User",
            "color": "#475569",
            "kind": "human",
            "user_id": uid,
            "metric": f"{r['msgs']} msgs/24h",
            "metric_sub": f"{r['conv_count']} conversas",
            "hints_received": hints_for_user,
        })
        # Edges das IAs → este atendente
        human_edges_in.append({
            "from": "copilot", "to": node_id, "value": hints_for_user,
            "label": "Dicas internas",
            "desc": f"Co-Pilot enviou {hints_for_user} dicas a {short}"
        })
        # Edges humano → atendimento (handover)
        human_edges_out.append({
            "from": node_id, "to": "atendimento", "value": r["msgs"],
            "label": f"{short} → cliente"
        })

    # Caso não haja humanos com volume, mostra ao menos um "humanos" agregado
    if not human_nodes:
        human_nodes.append({
            "id": "human_none", "label": "Atendentes Humanos",
            "subtitle": "Sem atividade 24h", "icon": "Users",
            "color": "#94a3b8", "kind": "human", "user_id": None,
            "metric": "0 msgs/24h", "metric_sub": "—",
            "hints_received": 0,
        })

    # ── NÓS DE IA ──────────────────────────────────────────────────────
    nodes: List[Dict[str, Any]] = [
        {"id": "smartolt", "label": "SmartOLT AI",
         "subtitle": "Detecção + análise Claude", "icon": "Radio", "color": "#0d9488",
         "kind": "ai",
         "model": DEFAULT_M,
         "model_kind": "llm",
         "metric": f"{outages_active} ativos",
         "metric_sub": f"{outages_detected} novos/24h"},
        {"id": "atendimento", "label": "Isabella IA",
         "subtitle": "Atendimento WhatsApp", "icon": "Bot", "color": "#16a34a",
         "kind": "ai",
         "model": ATENDIMENTO_M,
         "model_kind": "llm",
         "metric": f"{wa_ai_replies} respostas/24h",
         "metric_sub": f"{wa_inbound} recebidas"},
        {"id": "copilot", "label": "Co-Pilot IA",
         "subtitle": "Dicas internas (humanos)", "icon": "Lightbulb",
         "color": "#d97706", "kind": "ai",
         "model": DEFAULT_M,
         "model_kind": "llm",
         "metric": f"{copilot_hints} dicas/24h",
         "metric_sub": "Cliente NÃO vê"},
        {"id": "evaluator", "label": "Avaliador IA",
         "subtitle": "Central IA", "icon": "Award", "color": "#0ea5e9",
         "kind": "ai",
         "model": DEFAULT_M,
         "model_kind": "llm",
         "metric": f"{evaluations} avaliações/24h",
         "metric_sub": "CSAT/Sentimento/FCR"},
        {"id": "coach", "label": "Coach IA",
         "subtitle": "Recomendações pós-chat", "icon": "GraduationCap",
         "color": "#a855f7", "kind": "ai",
         "model": DEFAULT_M,
         "model_kind": "llm",
         "metric": f"{coachings} coachings/24h",
         "metric_sub": "Inline no chat"},
        {"id": "learning", "label": "Aprendizado",
         "subtitle": "Few-shot loop", "icon": "Sparkles", "color": "#eab308",
         "kind": "ai",
         "model": "Few-shot (CSAT≥8)",
         "model_kind": "retrieval",
         "metric": f"{high_csat} exemplos",
         "metric_sub": "CSAT≥8 nos últimos 30d"},
        {"id": "sentinela", "label": "Sentinela Lousa",
         "subtitle": "Monitor + análise Claude", "icon": "Shield", "color": "#ef4444",
         "kind": "ai",
         "model": DEFAULT_M,
         "model_kind": "llm",
         "metric": f"{sentinela['active']} alertas",
         "metric_sub": f"{sentinela['new_24h']} novos/24h"},
        {"id": "lousa", "label": "Lousa (Kanban)",
         "subtitle": "Tickets em curso", "icon": "ClipboardList",
         "color": "#64748b", "kind": "system",
         "model": "Backend (DB)",
         "model_kind": "rule",
         "metric": f"{active_tickets} ativos",
         "metric_sub": "Bolhas em aberto"},
    ]
    nodes.extend(human_nodes)

    # ── ARESTAS ────────────────────────────────────────────────────────
    edges: List[Dict[str, Any]] = [
        {"from": "smartolt", "to": "atendimento", "value": outage_aware,
         "label": "Contexto de pane",
         "desc": "Clientes em outage avisados proativamente"},
        {"from": "smartolt", "to": "copilot", "value": outages_active,
         "label": "Sinaliza pane ativa",
         "desc": "Co-Pilot enriquece dica com info de pane"},
        {"from": "atendimento", "to": "copilot", "value": wa_inbound,
         "label": "Contexto da conversa",
         "desc": "Co-Pilot analisa histórico recente"},
        {"from": "atendimento", "to": "evaluator", "value": wa_ai_replies + wa_human_replies,
         "label": "Conversas → análise"},
        {"from": "evaluator", "to": "coach", "value": evaluations,
         "label": "Avaliações → coaching"},
        {"from": "evaluator", "to": "learning", "value": high_csat,
         "label": "CSAT alto → exemplos"},
        {"from": "learning", "to": "atendimento", "value": high_csat,
         "label": "Few-shots no prompt"},
        # Sentinela Lousa: monitora tickets e gera alertas
        {"from": "lousa", "to": "sentinela", "value": active_tickets,
         "label": "Tickets monitorados",
         "desc": "Sentinela varre todos os tickets ativos a cada 2min"},
        {"from": "sentinela", "to": "lousa", "value": sentinela["active"],
         "label": "Alertas ativos",
         "desc": "Alertas inseridos como notas internas nos tickets"},
    ]
    # Co-Pilot → cada humano + cada humano → atendimento
    edges.extend(human_edges_in)
    edges.extend(human_edges_out)
    # Coach → humanos (agregada — toda dica de coaching pra todos)
    if human_nodes and human_nodes[0]["id"] != "human_none":
        coach_per = max(1, coachings // max(1, len(human_nodes)))
        for hn in human_nodes:
            edges.append({"from": "coach", "to": hn["id"],
                            "value": coach_per,
                            "label": "Coaching pós-chat"})

    return {
        "nodes": nodes,
        "edges": edges,
        "totals": {
            "wa_inbound_24h": wa_inbound,
            "wa_ai_24h": wa_ai_replies,
            "wa_human_24h": wa_human_replies,
            "evaluations_24h": evaluations,
            "coachings_24h": coachings,
            "copilot_hints_24h": copilot_hints,
            "outages_active": outages_active,
            "human_attendants": len([n for n in human_nodes if n.get("user_id")]),
            "sentinela_active_alerts": sentinela["active"],
            "sentinela_new_24h": sentinela["new_24h"],
            "active_tickets": active_tickets,
        },
        "motor": {
            "enabled": motor_enabled,
            "atendimento_model": ATENDIMENTO_M,
            "default_text_model": DEFAULT_M,
            "tts_voice": TTS_VOICE,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
