"""Tools extras da Secretária IA "Ligo".

Cobertura ampla: WhatsApp, Financeiro, Lousa avançada, Técnicos em campo,
OLT/Rede, Estoque, Planos, Sistema/Saúde.

Cada tool retorna JSON pequeno (≤ 2KB) para o LLM sintetizar a resposta.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from database import db

logger = logging.getLogger("secretaria_tools")

# ============================================================
# TOOLS SPEC — formato OpenAI/Anthropic tool_use
# ============================================================
TOOLS_SPEC_EXTRA: List[Dict[str, Any]] = [
    # --------- WHATSAPP / ATENDIMENTO ---------
    {
        "type": "function",
        "function": {
            "name": "whatsapp_activity_summary",
            "description": "Resumo da atividade do WhatsApp (24h): mensagens recebidas, enviadas, IA vs humano, conversas abertas.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_open_conversations",
            "description": "Conversas WhatsApp em aberto/não respondidas. Use para 'quais conversas estão pendentes?', 'tem cliente esperando?'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
                },
            },
        },
    },
    # --------- FINANCEIRO ---------
    {
        "type": "function",
        "function": {
            "name": "revenue_summary",
            "description": "Resumo financeiro: MRR ativo, número de assinantes pagantes, ticket médio, distribuição por plano.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consult_subscriber_invoices",
            "description": "Consulta faturas/cobranças de um assinante específico via CPF/CNPJ ou nome. Use para 'qual minha fatura?', 'quanto eu devo?', 'meu pagamento de novembro caiu?', '2ª via', 'segunda via'. Retorna faturas em aberto, pagas e vencidas + linha digitável + LINK DIRETO DO BOLETO (campo `boleto_url`) que VOCÊ DEVE INCLUIR na resposta para facilitar o pagamento.",
            "parameters": {
                "type": "object",
                "properties": {
                    "document": {"type": "string",
                                  "description": "CPF/CNPJ (com ou sem máscara) do cliente"},
                    "subscriber_name": {"type": "string",
                                          "description": "Nome parcial do cliente (fallback se não tiver CPF)"},
                    "status": {"type": "string",
                                "enum": ["any", "open", "paid", "overdue"],
                                "default": "any"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 6},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "next_due_invoice",
            "description": "Próxima fatura a vencer (não paga) de um assinante. Use para 'quando vence minha próxima fatura?'. Retorna 1 fatura com vencimento, valor, linha digitável e LINK DO BOLETO (campo `boleto_url`) — SEMPRE inclua o link na resposta quando estiver presente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "document": {"type": "string"},
                    "subscriber_name": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_overdue_subscribers",
            "description": "Lista assinantes inadimplentes/em atraso. Use para 'quem está devendo?', 'clientes em atraso'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 15},
                },
            },
        },
    },
    # --------- LOUSA AVANÇADA ---------
    {
        "type": "function",
        "function": {
            "name": "list_tickets_due_today",
            "description": "Bolhas (tickets) agendadas para HOJE, com cliente e técnico responsável. Use para 'o que tem agendado hoje?', 'minha agenda do dia'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_overdue_tickets",
            "description": "Tickets com SLA vencido (atrasados). Use para 'quais bolhas estão atrasadas?', 'SLA vencendo'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ticket_distribution",
            "description": "Distribuição de tickets por TIPO de serviço (instalação, reparo, retirada...) em aberto.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    # --------- TÉCNICOS EM CAMPO ---------
    {
        "type": "function",
        "function": {
            "name": "list_technicians_status",
            "description": "Status de cada técnico: em rota, em atendimento, parado, ou offline. Use 'cadê meus técnicos?', 'quem está disponível?'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clock_records_today",
            "description": "Quem bateu ponto hoje (entrada/saída). Use 'quem chegou hoje?', 'minha equipe bateu ponto?'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    # --------- OLT / REDE ---------
    {
        "type": "function",
        "function": {
            "name": "list_olts",
            "description": "Lista das OLTs cadastradas com nome, IP e qtd de ONUs em cada.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_recent_outages",
            "description": "Panes/outages recentes da rede óptica (últimos N dias). Use 'teve queda?', 'panes recentes', 'rede caiu?'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "minimum": 1, "maximum": 30, "default": 7},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "top_problem_areas",
            "description": "Áreas/cidades com maior concentração de ONUs offline ou em LOS. Use 'qual região tá pior?', 'onde tem mais problema?'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    # --------- ESTOQUE ---------
    {
        "type": "function",
        "function": {
            "name": "stock_summary",
            "description": "Resumo do estoque: total de itens, em uso com técnicos, em estoque livre, alertas de quantidade baixa.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    # --------- PLANOS ---------
    {
        "type": "function",
        "function": {
            "name": "list_plans",
            "description": "Tabela de planos: nome, velocidade, preço, qtd de assinantes em cada. Use 'meus planos', 'tabela de preços'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    # --------- SISTEMA / SAÚDE ---------
    {
        "type": "function",
        "function": {
            "name": "system_health",
            "description": "Saúde geral do sistema: backup mais recente do Drive, WhatsApp conectado, integrações funcionando, alertas recentes.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ai_preventive_insights",
            "description": "Sugestões preventivas geradas pela IA (clientes em risco, ONUs que vão falhar). Use 'preditivo', 'previsões', 'manutenção preventiva'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notifications_unread",
            "description": "Notificações não lidas/pendentes dos últimos dias.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
                },
            },
        },
    },
    # --------- NEO (orquestrador IA executivo) ---------
    {
        "type": "function",
        "function": {
            "name": "ask_neo",
            "description": (
                "Encaminha uma pergunta executiva para o NEO — orquestrador IA "
                "que consolida dados de TODOS os agentes (Isabella, Álvaro, Camila, "
                "Secretaria) e gera respostas resumidas. Use para perguntas como: "
                "'me dê um resumo de vendas da Isabella esta semana', 'quantos "
                "tickets o Álvaro resolveu hoje?', 'quanto a Camila cobrou este mês?', "
                "'me dê a timeline do cliente 5582999...', 'me dê KPIs dos agentes "
                "no último mês'. Retorna texto pronto para exibir."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string",
                                  "description": "Pergunta em linguagem natural para o NEO."},
                },
                "required": ["question"],
            },
        },
    },
]


# ============================================================
# IMPLEMENTAÇÕES
# ============================================================

# ---------- WhatsApp ----------
async def _tool_whatsapp_activity_summary(cid: str, _: Dict[str, Any]) -> Dict[str, Any]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    inbound = await db.aihub_wa_messages.count_documents(
        {"company_id": cid, "direction": "inbound", "created_at": {"$gte": cutoff}})
    outbound = await db.aihub_wa_messages.count_documents(
        {"company_id": cid, "direction": "outbound", "created_at": {"$gte": cutoff}})
    ai_replies = await db.aihub_wa_messages.count_documents(
        {"company_id": cid, "direction": "outbound", "ai_generated": True,
         "created_at": {"$gte": cutoff}})
    open_convs = await db.wa_conversations.count_documents(
        {"company_id": cid, "status": {"$in": ["open", "open_pending", "pending"]}})
    return {
        "window_hours": 24,
        "msgs_received": inbound,
        "msgs_sent": outbound,
        "ai_replied": ai_replies,
        "human_replied": max(0, outbound - ai_replies),
        "open_conversations": open_convs,
    }


async def _tool_list_open_conversations(cid: str, args: Dict[str, Any]) -> Dict[str, Any]:
    limit = int(args.get("limit") or 10)
    cur = db.wa_conversations.find(
        {"company_id": cid, "status": {"$in": ["open", "open_pending", "pending"]}},
        {"_id": 0, "id": 1, "contact_name": 1, "contact_phone": 1, "last_message_at": 1,
         "unread_count": 1, "last_inbound_at": 1, "subscriber_id": 1},
    ).sort("last_inbound_at", -1).limit(limit)
    items = await cur.to_list(limit)
    # Resolve nome do cliente quando há subscriber_id
    for it in items:
        sid = it.get("subscriber_id")
        if sid and not it.get("contact_name"):
            s = await db.subscribers.find_one({"id": sid}, {"_id": 0, "name": 1})
            if s:
                it["contact_name"] = s.get("name")
    return {"count": len(items), "items": items}


# ---------- Financeiro ----------
async def _tool_revenue_summary(cid: str, _: Dict[str, Any]) -> Dict[str, Any]:
    active_q = {"company_id": cid, "status": {"$in": ["ativo", "active", "ATIVO"]}}
    active_count = await db.subscribers.count_documents(active_q)
    total_mrr = 0.0
    by_plan: Dict[str, Dict[str, Any]] = {}
    async for s in db.subscribers.find(active_q, {"_id": 0, "plan_price": 1, "plan_name": 1}):
        try:
            price = float(s.get("plan_price") or 0)
        except (ValueError, TypeError):
            price = 0
        total_mrr += price
        pn = s.get("plan_name") or "—"
        if pn not in by_plan:
            by_plan[pn] = {"count": 0, "mrr": 0}
        by_plan[pn]["count"] += 1
        by_plan[pn]["mrr"] += price
    avg = (total_mrr / active_count) if active_count else 0
    top_plans = sorted(by_plan.items(), key=lambda x: -x[1]["count"])[:5]
    return {
        "active_subscribers": active_count,
        "mrr_brl": round(total_mrr, 2),
        "avg_ticket_brl": round(avg, 2),
        "top_plans": [
            {"plan": p, "subscribers": v["count"], "mrr": round(v["mrr"], 2)}
            for p, v in top_plans
        ],
    }


async def _tool_list_overdue_subscribers(cid: str, args: Dict[str, Any]) -> Dict[str, Any]:
    limit = int(args.get("limit") or 15)
    q = {"company_id": cid,
          "$or": [
              {"status": {"$in": ["inadimplente", "overdue", "atrasado", "INADIMPLENTE"]}},
              {"financial_status": {"$in": ["overdue", "atrasado", "inadimplente"]}},
          ]}
    count = await db.subscribers.count_documents(q)
    cur = db.subscribers.find(
        q, {"_id": 0, "name": 1, "phone": 1, "plan_name": 1, "plan_price": 1,
            "days_overdue": 1, "city": 1},
    ).limit(limit)
    return {"overdue_count": count, "items": await cur.to_list(limit)}


def _norm_doc(s: str) -> str:
    """Remove tudo que não for dígito (CPF/CNPJ)."""
    return "".join(ch for ch in (s or "") if ch.isdigit())


async def _resolve_invoices_query(cid: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Monta o filtro de subscriber_invoices a partir de document OU nome."""
    doc = _norm_doc(args.get("document") or "")
    name = (args.get("subscriber_name") or "").strip()
    q: Dict[str, Any] = {"company_id": cid}
    if doc:
        # Tenta match em formatos possíveis (com/sem máscara armazenado)
        q["$or"] = [
            {"subscriber_document": doc},
            {"subscriber_document": {"$regex": doc, "$options": "i"}},
        ]
    elif name:
        q["subscriber_name"] = {"$regex": name, "$options": "i"}
    else:
        return {}
    return q


async def _tool_consult_subscriber_invoices(cid: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Consulta faturas/cobranças do assinante (sync Atlaz Financeiro Fase 4)."""
    limit = int(args.get("limit") or 6)
    status = (args.get("status") or "any").lower()
    q = await _resolve_invoices_query(cid, args)
    if not q:
        return {"error": "Forneça document (CPF/CNPJ) ou subscriber_name."}
    # Filtro de status — heurístico (Atlaz retorna strings variadas)
    if status == "open":
        q["status"] = {"$nin": ["paga", "pago", "paid", "quitado", "baixada",
                                  "cancelada", "cancelled"]}
        q["paid_date"] = None
    elif status == "paid":
        q["$or"] = (q.get("$or") or []) + [
            {"status": {"$in": ["paga", "pago", "paid", "quitado", "baixada"]}},
            {"paid_date": {"$ne": None}},
        ] if q.get("$or") else None
        # Simplifica
        q = {**q, "status": {"$in": ["paga", "pago", "paid", "quitado", "baixada"]}}
    elif status == "overdue":
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        q["paid_date"] = None
        q["due_date"] = {"$lt": today}

    cur = db.subscriber_invoices.find(
        q, {"_id": 0, "external_id": 1, "subscriber_name": 1,
            "subscriber_document": 1, "amount": 1, "amount_paid": 1,
            "due_date": 1, "paid_date": 1, "status": 1, "barcode": 1,
            "boleto_url": 1, "subscriber_phone": 1},
    ).sort([("due_date", -1)]).limit(limit)
    items = await cur.to_list(limit)
    total = await db.subscriber_invoices.count_documents(q)
    # Resumo
    total_open = sum(float(i.get("amount") or 0) for i in items
                      if not i.get("paid_date"))
    return {
        "total_found": total,
        "shown": len(items),
        "total_open_amount_brl": round(total_open, 2),
        "invoices": items,
        "hint": ("Se nenhum resultado, peça o CPF ao cliente."
                  if total == 0 else None),
    }


async def _tool_next_due_invoice(cid: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Próxima fatura a vencer (não paga) do assinante."""
    q = await _resolve_invoices_query(cid, args)
    if not q:
        return {"error": "Forneça document (CPF/CNPJ) ou subscriber_name."}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    q["paid_date"] = None
    q["due_date"] = {"$gte": today}
    inv = await db.subscriber_invoices.find_one(
        q, {"_id": 0, "external_id": 1, "subscriber_name": 1,
            "amount": 1, "due_date": 1, "status": 1, "barcode": 1,
            "boleto_url": 1},
        sort=[("due_date", 1)],
    )
    if not inv:
        return {"found": False,
                 "message": "Nenhuma fatura em aberto futura encontrada."}
    return {"found": True, "invoice": inv}


# ---------- Lousa avançada ----------
async def _tool_list_tickets_due_today(cid: str, args: Dict[str, Any]) -> Dict[str, Any]:
    limit = int(args.get("limit") or 20)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cur = db.tickets.find(
        {"company_id": cid,
         "scheduled_time": {"$regex": f"^{today}"},
         "status": {"$nin": ["finalizada", "encerrada", "cancelada"]}},
        {"_id": 0, "id": 1, "type": 1, "scheduled_time": 1, "subscriber_name": 1,
         "address": 1, "status": 1, "assigned_collaborator_id": 1, "priority": 1},
    ).sort("scheduled_time", 1).limit(limit)
    items = await cur.to_list(limit)
    # Resolve técnico
    for t in items:
        cid_t = t.pop("assigned_collaborator_id", None)
        if cid_t:
            c = await db.collaborators.find_one({"id": cid_t}, {"_id": 0, "name": 1})
            t["technician"] = (c or {}).get("name")
    return {"date": today, "count": len(items), "tickets": items}


async def _tool_list_overdue_tickets(cid: str, _: Dict[str, Any]) -> Dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat()
    cur = db.tickets.find(
        {"company_id": cid,
         "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]},
         "sla_due_at": {"$lt": now_iso}},
        {"_id": 0, "id": 1, "type": 1, "subscriber_name": 1, "sla_due_at": 1,
         "created_at": 1, "priority": 1, "assigned_collaborator_id": 1},
    ).sort("sla_due_at", 1).limit(15)
    items = await cur.to_list(15)
    for t in items:
        cid_t = t.pop("assigned_collaborator_id", None)
        if cid_t:
            c = await db.collaborators.find_one({"id": cid_t}, {"_id": 0, "name": 1})
            t["technician"] = (c or {}).get("name")
    return {"overdue_count": len(items), "tickets": items}


async def _tool_ticket_distribution(cid: str, _: Dict[str, Any]) -> Dict[str, Any]:
    pipeline = [
        {"$match": {"company_id": cid,
                     "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]}}},
        {"$group": {"_id": "$type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    rows = []
    total = 0
    async for r in db.tickets.aggregate(pipeline):
        c = int(r.get("count", 0))
        total += c
        rows.append({"type": r["_id"] or "outros", "count": c})
    return {"total_open": total, "by_type": rows}


# ---------- Técnicos ----------
async def _tool_list_technicians_status(cid: str, _: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    out = []
    async for c in db.collaborators.find(
        {"company_id": cid, "role": {"$in": ["tecnico", "técnico", "tech"]}},
        {"_id": 0, "id": 1, "name": 1},
    ):
        cid_t = c["id"]
        # tickets ativos atribuídos
        active = await db.tickets.count_documents({
            "company_id": cid, "assigned_collaborator_id": cid_t,
            "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]},
        })
        # ponto batido hoje?
        clock = await db.clock_records.find_one(
            {"company_id": cid, "collaborator_id": cid_t,
             "date": today, "type": "in"},
            {"_id": 0, "created_at": 1})
        # última localização nas últimas 30 min?
        cutoff = (now - timedelta(minutes=30)).isoformat()
        last_loc = await db.location_logs.find_one(
            {"company_id": cid, "collaborator_id": cid_t,
             "created_at": {"$gte": cutoff}},
            {"_id": 0, "created_at": 1}, sort=[("created_at", -1)])
        status_label = (
            "em campo (rastreado)" if last_loc else
            "presente (sem rastreamento)" if clock else
            "offline (não bateu ponto)")
        out.append({
            "name": c.get("name") or "—",
            "active_tickets": active,
            "clocked_in": bool(clock),
            "tracked_now": bool(last_loc),
            "status": status_label,
        })
    out.sort(key=lambda x: -x["active_tickets"])
    return {"count": len(out), "technicians": out[:15]}


async def _tool_clock_records_today(cid: str, _: Dict[str, Any]) -> Dict[str, Any]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cur = db.clock_records.find(
        {"company_id": cid, "date": today},
        {"_id": 0, "collaborator_id": 1, "type": 1, "created_at": 1, "_collaborator_name": 1},
    ).sort("created_at", -1).limit(50)
    items = await cur.to_list(50)
    by_collab: Dict[str, Dict[str, Any]] = {}
    for it in items:
        cid_t = it.get("collaborator_id")
        if not cid_t:
            continue
        if cid_t not in by_collab:
            c = await db.collaborators.find_one({"id": cid_t}, {"_id": 0, "name": 1})
            by_collab[cid_t] = {"name": (c or {}).get("name") or "—",
                                 "first_in": None, "last_event": None}
        if it.get("type") == "in" and not by_collab[cid_t]["first_in"]:
            by_collab[cid_t]["first_in"] = it.get("created_at")
        by_collab[cid_t]["last_event"] = it.get("created_at")
    return {"date": today, "clocked_in_count": len(by_collab),
            "records": list(by_collab.values())[:20]}


# ---------- OLT / Rede ----------
async def _tool_list_olts(cid: str, _: Dict[str, Any]) -> Dict[str, Any]:
    items = []
    async for olt in db.smartolt_olts.find(
        {"company_id": cid},
        {"_id": 0, "id": 1, "name": 1, "ip": 1, "vendor": 1, "status": 1},
    ):
        oid = olt.get("id")
        onus = await db.smartolt_onus.count_documents(
            {"company_id": cid, "olt_id": oid})
        online = await db.smartolt_onus.count_documents(
            {"company_id": cid, "olt_id": oid,
             "status": {"$in": ["online", "ONLINE", "active"]}})
        items.append({
            "name": olt.get("name"),
            "vendor": olt.get("vendor"),
            "onus": onus,
            "online": online,
            "status": olt.get("status"),
        })
    return {"count": len(items), "olts": items}


async def _tool_list_recent_outages(cid: str, args: Dict[str, Any]) -> Dict[str, Any]:
    days = int(args.get("days") or 7)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cur = db.network_outages.find(
        {"company_id": cid, "started_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1, "olt_name": 1, "started_at": 1, "ended_at": 1,
         "affected_onus": 1, "status": 1, "description": 1},
    ).sort("started_at", -1).limit(20)
    items = await cur.to_list(20)
    active = [i for i in items if not i.get("ended_at")]
    return {"window_days": days, "total": len(items),
            "active_now": len(active), "outages": items}


async def _tool_top_problem_areas(cid: str, _: Dict[str, Any]) -> Dict[str, Any]:
    pipeline = [
        {"$match": {"company_id": cid,
                     "status": {"$in": ["LOS", "los", "offline", "OFFLINE"]}}},
        {"$group": {"_id": {"$ifNull": ["$city", "$region"]}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    rows = []
    async for r in db.smartolt_onus.aggregate(pipeline):
        rows.append({"area": r["_id"] or "—", "offline_onus": int(r["count"])})
    return {"areas": rows}


# ---------- Estoque ----------
async def _tool_stock_summary(cid: str, _: Dict[str, Any]) -> Dict[str, Any]:
    total = await db.stok_stock.count_documents({"company_id": cid})
    onts = await db.stok_onts.count_documents({"company_id": cid})
    services = await db.stok_services.count_documents({"company_id": cid})
    in_use = await db.collaborator_assets.count_documents(
        {"company_id": cid, "returned_at": None})
    return {
        "stock_items": total,
        "onts": onts,
        "services_cataloged": services,
        "items_with_technicians": in_use,
    }


# ---------- Planos ----------
async def _tool_list_plans(cid: str, _: Dict[str, Any]) -> Dict[str, Any]:
    items = []
    async for p in db.plans.find(
        {"company_id": cid},
        {"_id": 0, "id": 1, "name": 1, "price": 1, "download_mbps": 1,
         "upload_mbps": 1, "active": 1},
    ).sort("price", -1):
        pid = p.get("id")
        subs = await db.subscribers.count_documents({"company_id": cid, "plan_id": pid})
        items.append({
            "name": p.get("name"),
            "price_brl": p.get("price"),
            "download": p.get("download_mbps"),
            "subscribers": subs,
            "active": p.get("active", True),
        })
    return {"count": len(items), "plans": items}


# ---------- Sistema / Saúde ----------
async def _tool_system_health(cid: str, _: Dict[str, Any]) -> Dict[str, Any]:
    # Último backup Drive
    last_backup = await db.drive_backups.find_one(
        {"company_id": cid, "status": "ok"},
        {"_id": 0, "started_at": 1, "file_name": 1, "triggered_by": 1},
        sort=[("started_at", -1)],
    )
    drive_connected = bool(await db.drive_credentials.find_one(
        {"company_id": cid, "refresh_token": {"$nin": [None, ""]}}))
    # WhatsApp conectado?
    wa_status = await db.whatsapp_system_events.find_one(
        {"company_id": cid},
        {"_id": 0, "event_type": 1, "created_at": 1, "data": 1},
        sort=[("created_at", -1)],
    )
    # Alertas do sistema abertos
    alerts_open = await db.system_alerts.count_documents(
        {"company_id": cid, "resolved": {"$ne": True}})
    return {
        "drive": {
            "connected": drive_connected,
            "last_backup": last_backup,
        },
        "whatsapp": wa_status,
        "alerts_open": alerts_open,
    }


async def _tool_ai_preventive_insights(cid: str, args: Dict[str, Any]) -> Dict[str, Any]:
    limit = int(args.get("limit") or 8)
    cur = db.ai_preventive_suggestions.find(
        {"company_id": cid, "resolved": {"$ne": True}},
        {"_id": 0, "id": 1, "title": 1, "severity": 1, "subject_type": 1,
         "subject_id": 1, "created_at": 1, "summary": 1},
    ).sort([("severity", -1), ("created_at", -1)]).limit(limit)
    return {"count": await db.ai_preventive_suggestions.count_documents(
                {"company_id": cid, "resolved": {"$ne": True}}),
            "insights": await cur.to_list(limit)}


async def _tool_notifications_unread(cid: str, args: Dict[str, Any]) -> Dict[str, Any]:
    limit = int(args.get("limit") or 10)
    cur = db.notifications.find(
        {"company_id": cid, "read": {"$ne": True}},
        {"_id": 0, "id": 1, "title": 1, "body": 1, "kind": 1, "created_at": 1},
    ).sort("created_at", -1).limit(limit)
    return {"unread_count": await db.notifications.count_documents(
                {"company_id": cid, "read": {"$ne": True}}),
            "items": await cur.to_list(limit)}


# ---------- NEO orquestrador ----------
async def _tool_ask_neo(cid: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Encaminha pergunta ao NEO. Reutiliza o LLM + tools do NEO Chat.

    Diferente da Secretaria (que faz tool-use Anthropic style), o NEO usa
    um pipeline mais simples: 1 LLM call escolhe a tool, 1 LLM call sintetiza.
    """
    question = (args or {}).get("question") or ""
    if not question:
        return {"error": "question vazia"}
    try:
        from routes.neo_chat import (
            TOOL_CATALOG_PROMPT, SUMMARIZE_PROMPT, TOOLS as NEO_TOOLS,
            _llm_chat, _parse_json_loose,
        )
        from emergentintegrations.llm.chat import UserMessage
        import uuid as _uuid
        sid = f"sec2neo-{_uuid.uuid4().hex[:8]}"
        chat1 = _llm_chat(f"{sid}-route", TOOL_CATALOG_PROMPT)
        raw1 = await chat1.send_message(UserMessage(text=question))
        decision = _parse_json_loose(raw1)
        tool_name = decision.get("tool") or "freeform"
        params = decision.get("params") or {}
        if tool_name == "freeform":
            return {"answer": decision.get("answer") or "Sem dados.", "via_neo": True}
        if tool_name in NEO_TOOLS:
            fn = NEO_TOOLS[tool_name]
            allowed = {}
            if tool_name == "customer_timeline":
                allowed["phone"] = str(params.get("phone") or "")
            elif "days" in params:
                try:
                    allowed["days"] = max(1, min(90, int(params["days"])))
                except Exception:
                    pass
            data = await fn(cid, **allowed)
            chat2 = _llm_chat(f"{sid}-sum", "Você é o NEO. PT-BR, breve.")
            import json as _json
            prompt = SUMMARIZE_PROMPT.format(
                question=question, tool=tool_name,
                data=_json.dumps(data, ensure_ascii=False, default=str)[:5000],
            )
            answer = await chat2.send_message(UserMessage(text=prompt))
            return {"answer": answer, "via_neo": True, "tool_used": tool_name}
        return {"answer": f"NEO não encontrou tool para '{tool_name}'", "via_neo": True}
    except Exception as e:
        logger.warning("[secretaria] ask_neo fail: %s", e)
        return {"error": f"NEO indisponível: {e}"}


# ============================================================
# DISPATCH TABLE
# ============================================================
TOOL_FUNCS_EXTRA = {
    "whatsapp_activity_summary": _tool_whatsapp_activity_summary,
    "list_open_conversations": _tool_list_open_conversations,
    "revenue_summary": _tool_revenue_summary,
    "list_overdue_subscribers": _tool_list_overdue_subscribers,
    "consult_subscriber_invoices": _tool_consult_subscriber_invoices,
    "next_due_invoice": _tool_next_due_invoice,
    "list_tickets_due_today": _tool_list_tickets_due_today,
    "list_overdue_tickets": _tool_list_overdue_tickets,
    "ticket_distribution": _tool_ticket_distribution,
    "list_technicians_status": _tool_list_technicians_status,
    "clock_records_today": _tool_clock_records_today,
    "list_olts": _tool_list_olts,
    "list_recent_outages": _tool_list_recent_outages,
    "top_problem_areas": _tool_top_problem_areas,
    "stock_summary": _tool_stock_summary,
    "list_plans": _tool_list_plans,
    "system_health": _tool_system_health,
    "ai_preventive_insights": _tool_ai_preventive_insights,
    "notifications_unread": _tool_notifications_unread,
    "ask_neo": _tool_ask_neo,
}


# ─────────────────────────────────────────────────────────────────
# iter219 — Tools do Presidente IA (saúde corporativa, riscos,
# oportunidades). Permite que Leo/Ligo responda perguntas tipo:
# "como está a saúde da empresa?", "quais riscos hoje?",
# "qual oportunidade está sobrando?", "roda uma varredura agora".
# ─────────────────────────────────────────────────────────────────
async def _tool_corporate_health(company_id: str,
                                    args: Dict[str, Any]) -> Dict[str, Any]:
    from services.presidente_ia import compute_corporate_health
    return await compute_corporate_health(company_id)


async def _tool_top_risks(company_id: str,
                             args: Dict[str, Any]) -> Dict[str, Any]:
    from services.presidente_ia import (
        compute_corporate_health, compute_risks)
    h = await compute_corporate_health(company_id)
    r = await compute_risks(company_id, h)
    limit = int(args.get("limit") or 5)
    flat = (r.get("criticos") or []) + (r.get("altos") or []) \
        + (r.get("medios") or [])
    return {"total": r.get("total", 0),
             "criticos": len(r.get("criticos") or []),
             "altos": len(r.get("altos") or []),
             "medios": len(r.get("medios") or []),
             "top": flat[:limit]}


async def _tool_top_opportunities(company_id: str,
                                      args: Dict[str, Any]) -> Dict[str, Any]:
    from services.presidente_ia import compute_opportunities
    o = await compute_opportunities(company_id)
    limit = int(args.get("limit") or 5)
    return {"total": o.get("total", 0),
             "receita_potencial_brl": o.get("receita_potencial_brl", 0),
             "top": (o.get("items") or [])[:limit]}


async def _tool_presidente_scan(company_id: str,
                                   args: Dict[str, Any]) -> Dict[str, Any]:
    from services.presidente_ia import proactive_scan
    res = await proactive_scan(company_id)
    # devolve só o essencial pro LLM (sem evidências pesadas)
    return {
        "ok": res.get("ok"),
        "elapsed_ms": res.get("elapsed_ms"),
        "health_score": res.get("health", {}).get("score"),
        "health_status": res.get("health", {}).get("status"),
        "risks_total": res.get("risks", {}).get("total"),
        "opportunities_total": res.get("opportunities", {}).get("total"),
        "receita_potencial_brl": res.get("opportunities", {})
            .get("receita_potencial_brl"),
        "predictions_made": res.get("predictions", {}).get("predicted"),
        "correlations_found": len(res.get("correlations") or []),
    }


async def _tool_clients_at_risk(company_id: str,
                                    args: Dict[str, Any]) -> Dict[str, Any]:
    from services.presidente_ia import compute_clients_at_risk
    limit = int(args.get("limit") or 10)
    items = await compute_clients_at_risk(company_id, limit=limit)
    return {"total": len(items), "items": items}


# Adiciona specs + funcs ao registro
TOOLS_SPEC_EXTRA.extend([
    {
        "type": "function",
        "function": {
            "name": "corporate_health",
            "description": (
                "Saúde corporativa atual da empresa (score 0-100, "
                "status saudavel/atencao/alerta/critico) e indicadores "
                "principais (churn, inadimplência, ONUs offline). "
                "Use quando o gestor perguntar 'como está a saúde da "
                "empresa', 'tudo bem?', 'situação geral'."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "top_risks",
            "description": (
                "Top riscos corporativos atuais (críticos/altos/médios). "
                "Use quando perguntarem 'qual risco temos hoje', 'o que "
                "está em risco', 'onde devo focar', 'algum problema "
                "grave'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1,
                                "maximum": 20, "default": 5},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "top_opportunities",
            "description": (
                "Top oportunidades de receita identificadas (upsell, "
                "cross-sell SecurityHome, leads parados, etc.). "
                "Use quando perguntarem 'onde tem dinheiro pra ganhar', "
                "'oportunidades', 'o que estamos perdendo', 'onde "
                "investir'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1,
                                "maximum": 20, "default": 5},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clients_at_risk",
            "description": (
                "Clientes ativos com maior risco de churn (score 0-100 "
                "baseado em inadimplência, sinal baixo, etc.). "
                "Use quando perguntarem 'quem está pra cancelar', "
                "'churn alto', 'clientes em risco', 'quem perdeu sinal'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1,
                                "maximum": 30, "default": 10},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "presidente_scan",
            "description": (
                "Executa uma varredura completa AGORA pelo Presidente "
                "IA (health + riscos + oportunidades + predições + "
                "correlações) e devolve o resumo. Use só quando o "
                "gestor pedir explicitamente 'roda uma varredura', "
                "'atualiza tudo', 'me dá um status agora'."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
])

TOOL_FUNCS_EXTRA.update({
    "corporate_health": _tool_corporate_health,
    "top_risks": _tool_top_risks,
    "top_opportunities": _tool_top_opportunities,
    "clients_at_risk": _tool_clients_at_risk,
    "presidente_scan": _tool_presidente_scan,
})


# ─────────────────────────────────────────────────────────────────
# iter219c — Tools de EXECUÇÃO (chefe de gabinete digital).
# Ações destrutivas: o LLM já foi instruído via SYSTEM_PROMPT a pedir
# confirmação ANTES de chamar essas tools. Cada tool delega para
# services/agent_tools.py (que já tem audit log em
# conselho_ia_agent_actions).
# ─────────────────────────────────────────────────────────────────
async def _exec_via_agent_tools(company_id: str, tool_name: str,
                                    args: Dict[str, Any]) -> Dict[str, Any]:
    """Wrapper único: chama services.agent_tools.execute_tool_call."""
    from services.agent_tools import execute_tool_call
    payload = {
        "tool": tool_name,
        "args": args,
        "justification": args.pop("_justification", None)
            or "Solicitado pelo gestor via Leo (WhatsApp)",
    }
    res = await execute_tool_call(company_id, payload)
    return {
        "status": res.get("status"),
        "tool": tool_name,
        "result": res.get("result"),
        "error": res.get("error"),
        "action_id": res.get("action_id"),
    }


async def _tool_exec_pause_promo(company_id: str,
                                    args: Dict[str, Any]) -> Dict[str, Any]:
    return await _exec_via_agent_tools(
        company_id, "pause_promo_inactive",
        {"promotion_id": args.get("promotion_id"),
         "reason": args.get("reason") or "solicitação do gestor via Leo"})


async def _tool_exec_escalate_dunning(company_id: str,
                                          args: Dict[str, Any]) -> Dict[str, Any]:
    return await _exec_via_agent_tools(
        company_id, "escalate_dunning",
        {"subscriber_ids": args.get("subscriber_ids") or [],
         "to_stage": int(args.get("to_stage") or 2),
         "reason": args.get("reason") or "escalada solicitada via Leo"})


async def _tool_exec_assign_technician(company_id: str,
                                           args: Dict[str, Any]) -> Dict[str, Any]:
    return await _exec_via_agent_tools(
        company_id, "assign_technician",
        {"ticket_id": args.get("ticket_id"),
         "technician_id": args.get("technician_id"),
         "reason": args.get("reason") or "atribuição via Leo"})


async def _tool_exec_flag_dunning(company_id: str,
                                      args: Dict[str, Any]) -> Dict[str, Any]:
    return await _exec_via_agent_tools(
        company_id, "flag_dunning",
        {"subscriber_ids": args.get("subscriber_ids") or [],
         "reason": args.get("reason") or "marcar pra cobrança via Leo"})


async def _tool_exec_create_inspection_ticket(company_id: str,
                                                  args: Dict[str, Any]
                                                  ) -> Dict[str, Any]:
    return await _exec_via_agent_tools(
        company_id, "create_inspection_ticket",
        {"cto_id": args.get("cto_id"),
         "neighborhood": args.get("neighborhood"),
         "reason": args.get("reason") or "inspeção solicitada via Leo"})


TOOLS_SPEC_EXTRA.extend([
    {
        "type": "function",
        "function": {
            "name": "exec_pause_promo",
            "description": (
                "EXECUTA: pausa (active=False) uma promoção de parceria. "
                "AÇÃO DESTRUTIVA — só chame depois que o gestor "
                "responder 'sim' ou 'confirmo'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "promotion_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["promotion_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "exec_escalate_dunning",
            "description": (
                "EXECUTA: eleva o dunning_stage (2..5) de assinantes "
                "que já estão na régua de cobrança. AÇÃO DESTRUTIVA — "
                "só chame depois que o gestor confirmar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subscriber_ids": {"type": "array",
                                          "items": {"type": "string"}},
                    "to_stage": {"type": "integer", "minimum": 2,
                                    "maximum": 5},
                    "reason": {"type": "string"},
                },
                "required": ["subscriber_ids", "to_stage"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "exec_assign_technician",
            "description": (
                "EXECUTA: atribui um técnico (collaborator) a um ticket "
                "aberto. AÇÃO DESTRUTIVA — confirmação obrigatória."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string"},
                    "technician_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["ticket_id", "technician_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "exec_flag_dunning",
            "description": (
                "EXECUTA: marca assinantes para entrar na régua de "
                "cobrança (dunning_queue=True). AÇÃO DESTRUTIVA — "
                "confirmação obrigatória."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subscriber_ids": {"type": "array",
                                          "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["subscriber_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "exec_create_inspection_ticket",
            "description": (
                "EXECUTA: cria um ticket de inspeção/preventiva para "
                "uma CTO ou bairro. AÇÃO que cria registro — pedir "
                "confirmação."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cto_id": {"type": "string"},
                    "neighborhood": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
    },
])

TOOL_FUNCS_EXTRA.update({
    "exec_pause_promo": _tool_exec_pause_promo,
    "exec_escalate_dunning": _tool_exec_escalate_dunning,
    "exec_assign_technician": _tool_exec_assign_technician,
    "exec_flag_dunning": _tool_exec_flag_dunning,
    "exec_create_inspection_ticket": _tool_exec_create_inspection_ticket,
})
