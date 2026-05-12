"""Secretária IA "Ligo" — assistente executiva do gestor.

Arquitetura:
  - Claude Sonnet 4.5 via Motor IA (agente `secretaria_ia`).
  - Tool-use: a IA escolhe quais "ferramentas" chamar para responder.
    Cada ferramenta executa uma query *somente leitura* no banco e devolve
    JSON estruturado. A IA então sintetiza a resposta final em pt-BR.
  - Canais: web (interno), WhatsApp (manager_assistant), ChatGPT webhook.
  - Audit log em `secretaria_log`.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core import DEMO_COMPANY_ID, now_iso
from database import db
from services.motor_ia import AgentDisabledError, chat_completion

logger = logging.getLogger("secretaria_ia")

AGENT_ID = "secretaria_ia"

SYSTEM_PROMPT = """Você é a Ligo, secretária executiva de IA do gestor de um provedor de internet (ISP).

Sua função: responder perguntas do gestor sobre dados operacionais do sistema (clientes, técnicos, lousa de serviços, rede óptica/OLT, churn, financeiro) de forma direta, curta e clara em português brasileiro.

REGRAS:
- Use ferramentas (tools) para buscar dados reais. NUNCA invente números.
- Quando o gestor te cumprimentar pelo nome (ex: "oi minha Ligo"), responda no mesmo tom amigável.
- Seja concisa: 1-3 frases. O gestor lê no WhatsApp/celular.
- Se a pergunta for ambígua, pergunte de volta antes de chutar.
- Se NENHUMA ferramenta serve, diga educadamente que você ainda não tem acesso a essa informação.
- Formate números em pt-BR (47, R$ 1.234, 3 OLTs).
- Não use markdown pesado — texto plano serve no WhatsApp.
- Trate o gestor por "você" ou pelo primeiro nome quando souber.
"""


# ============================================================
# TOOL CATALOG — definições no formato OpenAI/Anthropic tool_use
# ============================================================
TOOLS_SPEC: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "count_subscribers",
            "description": "Conta clientes (assinantes) ativos da empresa. Pode filtrar por período de criação.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "enum": ["total", "today", "this_week", "this_month", "this_year", "last_30_days"],
                        "description": "Recorte do período. 'total' = todos os ativos. 'this_month' = criados neste mês."
                    }
                },
                "required": ["period"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "count_tickets_by_status",
            "description": "Conta bolhas/tickets da Lousa agrupados por status. Use para perguntas tipo 'quantos chamados abertos', 'quantas instalações pendentes'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "enum": ["today", "this_week", "this_month", "last_30_days", "open_now"],
                        "description": "'open_now' retorna o backlog ativo. Outros recortam por created_at."
                    },
                    "ticket_type": {
                        "type": "string",
                        "enum": ["all", "instalacao", "reparo", "retirada", "preventiva", "troca_endereco"],
                        "description": "Filtrar por tipo de serviço. Default 'all'."
                    },
                },
                "required": ["period"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "smartolt_status",
            "description": "Status atual da rede óptica: OLTs cadastradas, ONUs em LOS (alarme óptico), ONUs offline. Use para 'como está a rede', 'tem cliente sem sinal', 'quantas ONUs offline'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_top_technicians",
            "description": "Top N técnicos por bolhas finalizadas em um período.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {"type": "string", "enum": ["today", "this_week", "this_month", "last_30_days"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                },
                "required": ["period"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "churn_summary",
            "description": "Resumo de churn (cancelamentos) deste mês: total cancelados, top motivos, MRR perdido estimado.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_subscriber",
            "description": "Localiza um assinante por nome, CPF ou telefone. Devolve resumo (nome, plano, status, último contato).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Nome parcial, telefone ou CPF."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ai_agents_status",
            "description": "Status dos AGENTES DE IA (bots): quais estão ativos/pausados. Use para 'os agentes IA estão funcionando?', 'quem tá pausado'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "count_human_attendants_online",
            "description": "Conta ATENDENTES HUMANOS ativos no momento (que enviaram mensagem nos últimos N minutos). Use para perguntas tipo 'quantos atendentes online?', 'quem está atendendo agora?', 'minha equipe está trabalhando?'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "window_minutes": {
                        "type": "integer",
                        "description": "Janela em minutos pra considerar 'online' (default 10).",
                        "minimum": 1,
                        "maximum": 120,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "count_clients_connected",
            "description": "Conta CLIENTES (ONUs) conectados no momento na rede óptica. Use para 'quantos clientes online?', 'quantas ONUs ativas?', 'quantas pessoas estão conectadas?'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "motor_ia_usage_today",
            "description": "Custo do Motor IA (Claude/OpenRouter) hoje em USD + quebra por agente.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recent_system_events",
            "description": "Últimos eventos relevantes do sistema (panes, alertas, agentes pausados, configurações alteradas).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
                },
            },
        },
    },
]


# ============================================================
# TOOL IMPLEMENTATIONS
# ============================================================
def _period_range(period: str) -> tuple[datetime, datetime]:
    """Retorna (start, end) UTC para um label de período."""
    now = datetime.now(timezone.utc)
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "this_week":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "this_month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif period == "this_year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    elif period == "last_30_days":
        start = now - timedelta(days=30)
    else:
        start = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return start, now


async def _tool_count_subscribers(cid: str, args: Dict[str, Any]) -> Dict[str, Any]:
    period = args.get("period", "total")
    q: Dict[str, Any] = {"company_id": cid, "status": {"$in": ["ativo", "active", "ATIVO"]}}
    if period != "total":
        start, _ = _period_range(period)
        q["created_at"] = {"$gte": start.isoformat()}
    count = await db.subscribers.count_documents(q)
    return {"count": count, "period": period}


async def _tool_count_tickets_by_status(cid: str, args: Dict[str, Any]) -> Dict[str, Any]:
    period = args.get("period", "open_now")
    ttype = args.get("ticket_type", "all")
    q: Dict[str, Any] = {"company_id": cid}
    if ttype != "all":
        q["type"] = ttype
    if period == "open_now":
        q["status"] = {"$in": ["pendente", "aberta", "aguardando_atendimento"]}
    else:
        start, _ = _period_range(period)
        q["created_at"] = {"$gte": start.isoformat()}
    pipeline = [
        {"$match": q},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]
    by_status: Dict[str, int] = {}
    async for row in db.tickets.aggregate(pipeline):
        by_status[row["_id"] or "unknown"] = int(row["count"])
    total = sum(by_status.values())
    return {"total": total, "by_status": by_status, "period": period, "type": ttype}


async def _tool_smartolt_status(cid: str, _: Dict[str, Any]) -> Dict[str, Any]:
    olt_count = await db.smartolt_olts.count_documents({"company_id": cid})
    los_count = await db.smartolt_onus.count_documents(
        {"company_id": cid, "status": {"$in": ["LOS", "los", "OFFLINE"]}}
    )
    onus_total = await db.smartolt_onus.count_documents({"company_id": cid})
    # Últimas panes
    last_panes = await db.smartolt_panes.find(
        {"company_id": cid}, {"_id": 0, "olt_name": 1, "started_at": 1, "status": 1}
    ).sort("started_at", -1).limit(3).to_list(3)
    return {
        "olts": olt_count, "onus_total": onus_total,
        "onus_los_or_offline": los_count, "recent_panes": last_panes,
    }


async def _tool_list_top_technicians(cid: str, args: Dict[str, Any]) -> Dict[str, Any]:
    period = args.get("period", "this_month")
    limit = int(args.get("limit", 5))
    start, _ = _period_range(period)
    pipeline = [
        {"$match": {
            "company_id": cid,
            "status": {"$in": ["finalizada", "encerrada"]},
            "closed_at": {"$gte": start.isoformat()},
        }},
        {"$group": {"_id": "$assigned_collaborator_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": limit},
    ]
    rows = []
    async for r in db.tickets.aggregate(pipeline):
        cid_t = r["_id"]
        if not cid_t:
            continue
        coll = await db.collaborators.find_one({"id": cid_t}, {"_id": 0, "name": 1})
        rows.append({"name": (coll or {}).get("name") or "—", "tickets": int(r["count"])})
    return {"period": period, "top": rows}


async def _tool_churn_summary(cid: str, _: Dict[str, Any]) -> Dict[str, Any]:
    start, _now = _period_range("this_month")
    iso_start = start.isoformat()
    canceled = await db.subscribers.count_documents({
        "company_id": cid,
        "status": {"$in": ["cancelado", "canceled", "CANCELADO"]},
        "$or": [
            {"canceled_at": {"$gte": iso_start}},
            {"updated_at": {"$gte": iso_start}},
        ],
    })
    # MRR perdido aproximado: soma `plan_price` dos cancelados desse mês
    cur = db.subscribers.find({
        "company_id": cid,
        "status": {"$in": ["cancelado", "canceled", "CANCELADO"]},
        "$or": [
            {"canceled_at": {"$gte": iso_start}},
            {"updated_at": {"$gte": iso_start}},
        ],
    }, {"_id": 0, "plan_price": 1, "cancel_reason": 1})
    mrr_lost = 0.0
    reasons: Dict[str, int] = {}
    async for s in cur:
        try:
            mrr_lost += float(s.get("plan_price") or 0)
        except (ValueError, TypeError):
            pass
        rs = s.get("cancel_reason") or "não informado"
        reasons[rs] = reasons.get(rs, 0) + 1
    top_reasons = sorted(reasons.items(), key=lambda x: -x[1])[:5]
    return {
        "canceled_this_month": canceled,
        "mrr_lost_estimated_brl": round(mrr_lost, 2),
        "top_reasons": [{"reason": r, "count": c} for r, c in top_reasons],
    }


async def _tool_find_subscriber(cid: str, args: Dict[str, Any]) -> Dict[str, Any]:
    query = (args.get("query") or "").strip()
    if not query:
        return {"found": False, "reason": "query vazia"}
    digits = re.sub(r"\D", "", query)
    or_clauses: List[Dict[str, Any]] = []
    if len(query) >= 2:
        or_clauses.append({"name": {"$regex": re.escape(query), "$options": "i"}})
    if digits:
        if len(digits) >= 8:
            or_clauses.append({"phone": {"$regex": digits}})
            or_clauses.append({"phones": {"$regex": digits}})
        if len(digits) == 11 or len(digits) == 14:
            or_clauses.append({"cpf": digits})
            or_clauses.append({"cnpj": digits})
    if not or_clauses:
        return {"found": False, "reason": "query muito curta"}
    doc = await db.subscribers.find_one(
        {"company_id": cid, "$or": or_clauses},
        {"_id": 0, "id": 1, "name": 1, "phone": 1, "status": 1, "plan_name": 1,
         "city": 1, "created_at": 1, "address": 1},
    )
    if not doc:
        return {"found": False}
    return {"found": True, "subscriber": doc}


async def _tool_ai_agents_status(cid: str, _: Dict[str, Any]) -> Dict[str, Any]:
    """Lista agentes IA (BOTS) e se estão ativos."""
    from services.motor_ia import AGENT_CATALOG, is_agent_enabled
    items = []
    for agent in AGENT_CATALOG:
        enabled = await is_agent_enabled(cid, agent["id"])
        items.append({"id": agent["id"], "label": agent["label"], "enabled": enabled})
    paused = [i for i in items if not i["enabled"]]
    return {"total": len(items), "paused_count": len(paused),
            "paused": [p["label"] for p in paused]}


async def _tool_count_human_attendants_online(cid: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Atendentes HUMANOS online = colaboradores que enviaram mensagem WhatsApp
    (direction=outbound, ai_generated=false) nos últimos N min."""
    window = int(args.get("window_minutes") or 10)
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=window)).isoformat()
    pipeline = [
        {"$match": {
            "company_id": cid,
            "direction": "outbound",
            "ai_generated": {"$ne": True},
            "created_at": {"$gte": cutoff},
            "sent_by_user_id": {"$nin": [None, ""]},
        }},
        {"$group": {"_id": "$sent_by_user_id", "last_msg": {"$max": "$created_at"},
                     "messages": {"$sum": 1}}},
        {"$sort": {"last_msg": -1}},
    ]
    rows = []
    async for r in db.aihub_wa_messages.aggregate(pipeline):
        uid = r.get("_id")
        if not uid:
            continue
        user = await db.users.find_one(
            {"id": uid, "company_id": cid},
            {"_id": 0, "name": 1, "email": 1, "roles": 1},
        )
        rows.append({
            "user_id": uid,
            "name": (user or {}).get("name") or (user or {}).get("email") or "—",
            "messages_in_window": int(r.get("messages", 0)),
            "last_activity": r.get("last_msg"),
        })
    return {"count": len(rows), "window_minutes": window, "attendants": rows[:15]}


async def _tool_count_clients_connected(cid: str, _: Dict[str, Any]) -> Dict[str, Any]:
    """Clientes online = ONUs com status online no SmartOLT."""
    total = await db.smartolt_onus.count_documents({"company_id": cid})
    online = await db.smartolt_onus.count_documents({
        "company_id": cid,
        "status": {"$in": ["online", "ONLINE", "Online", "active", "ATIVE", "ATIVO"]},
    })
    offline = await db.smartolt_onus.count_documents({
        "company_id": cid,
        "status": {"$in": ["offline", "OFFLINE", "LOS", "los", "Offline"]},
    })
    return {
        "total_onus": total,
        "online": online,
        "offline_or_los": offline,
        "online_percent": round((online / total * 100), 1) if total else 0,
    }


async def _tool_motor_ia_usage_today(cid: str, _: Dict[str, Any]) -> Dict[str, Any]:
    start_today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    pipeline = [
        {"$match": {"company_id": cid, "ts": {"$gte": start_today.isoformat()}}},
        {"$group": {
            "_id": "$agent",
            "cost_usd": {"$sum": "$cost_usd"},
            "calls": {"$sum": 1},
        }},
        {"$sort": {"cost_usd": -1}},
    ]
    by_agent = []
    total_usd = 0.0
    async for r in db.motor_ia_usage.aggregate(pipeline):
        cost = float(r.get("cost_usd") or 0)
        total_usd += cost
        by_agent.append({"agent": r["_id"], "cost_usd": round(cost, 4),
                          "calls": int(r["calls"])})
    return {"total_usd_today": round(total_usd, 4), "by_agent": by_agent[:8]}


async def _tool_recent_system_events(cid: str, args: Dict[str, Any]) -> Dict[str, Any]:
    limit = int(args.get("limit", 10))
    events: List[Dict[str, Any]] = []
    # Lousa logs
    async for d in db.lousa_logs.find(
        {"company_id": cid}, {"_id": 0, "action": 1, "created_at": 1, "ticket_id": 1, "by": 1}
    ).sort("created_at", -1).limit(limit):
        events.append({"type": "lousa", "when": d.get("created_at"), "summary": d.get("action")})
    # Agent switch history
    async for d in db.ai_agent_switch_history.find(
        {"company_id": cid}, {"_id": 0, "agent_id": 1, "enabled": 1, "created_at": 1, "by_user": 1}
    ).sort("created_at", -1).limit(limit):
        action = "ativado" if d.get("enabled") else "pausado"
        events.append({
            "type": "agente",
            "when": d.get("created_at"),
            "summary": f"agente {d.get('agent_id')} {action} por {d.get('by_user', '—')}",
        })
    events.sort(key=lambda e: e.get("when") or "", reverse=True)
    return {"events": events[:limit]}


TOOL_FUNCS = {
    "count_subscribers": _tool_count_subscribers,
    "count_tickets_by_status": _tool_count_tickets_by_status,
    "smartolt_status": _tool_smartolt_status,
    "list_top_technicians": _tool_list_top_technicians,
    "churn_summary": _tool_churn_summary,
    "find_subscriber": _tool_find_subscriber,
    "ai_agents_status": _tool_ai_agents_status,
    "count_human_attendants_online": _tool_count_human_attendants_online,
    "count_clients_connected": _tool_count_clients_connected,
    "motor_ia_usage_today": _tool_motor_ia_usage_today,
    "recent_system_events": _tool_recent_system_events,
}


# ============================================================
# MAIN ASK
# ============================================================
async def ask(company_id: str, question: str,
              channel: str = "internal",
              who: Optional[str] = None,
              max_iterations: int = 4) -> Dict[str, Any]:
    """Pergunta à Secretária. Faz N iterações de tool-use até a IA dar resposta final.

    Args:
        company_id: empresa
        question: texto do usuário
        channel: "internal" | "whatsapp" | "chatgpt"
        who: nome/telefone de quem pergunta (pra registro)
        max_iterations: limite de chamadas iterativas (anti-loop)

    Returns: {"answer": str, "tools_used": [...], "iterations": int}
    """
    cid = company_id or DEMO_COMPANY_ID
    started = datetime.now(timezone.utc)

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question or ""},
    ]
    tools_used: List[Dict[str, Any]] = []
    iterations = 0
    answer = ""

    for _ in range(max_iterations):
        iterations += 1
        try:
            result = await _chat_with_tools(cid, messages)
        except AgentDisabledError:
            answer = "A Secretária IA está pausada. Reative em Motor IA → Agentes."
            break
        except Exception as e:
            logger.exception("[secretaria] erro motor IA: %s", e)
            answer = "Tive um problema técnico aqui ao consultar o sistema. Tenta de novo em alguns segundos?"
            break

        msg = result.get("message") or {}
        # Acumula a mensagem assistente no histórico (com tool_calls)
        assistant_msg: Dict[str, Any] = {
            "role": "assistant",
            "content": msg.get("content") or "",
        }
        if msg.get("tool_calls"):
            assistant_msg["tool_calls"] = msg["tool_calls"]
        messages.append(assistant_msg)

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            answer = (msg.get("content") or "").strip()
            break

        # Executa cada tool call e injeta o resultado no histórico
        for tc in tool_calls:
            fn_name = (tc.get("function") or {}).get("name") or ""
            fn_args_raw = (tc.get("function") or {}).get("arguments") or "{}"
            try:
                fn_args = json.loads(fn_args_raw) if isinstance(fn_args_raw, str) else fn_args_raw
            except Exception:
                fn_args = {}
            impl = TOOL_FUNCS.get(fn_name)
            if not impl:
                tool_result: Dict[str, Any] = {"error": f"tool {fn_name} desconhecida"}
            else:
                try:
                    tool_result = await impl(cid, fn_args)
                except Exception as e:
                    logger.exception("[secretaria] tool %s falhou: %s", fn_name, e)
                    tool_result = {"error": str(e)[:200]}
            tools_used.append({"name": fn_name, "args": fn_args, "result_keys": list(tool_result.keys())})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id") or fn_name,
                "name": fn_name,
                "content": json.dumps(tool_result, ensure_ascii=False, default=str),
            })

    if not answer:
        answer = "Não consegui chegar a uma resposta em tempo hábil. Tenta refrasear?"

    # Audit log (best-effort)
    try:
        elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        await db.secretaria_log.insert_one({
            "id": f"sec-{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "channel": channel,
            "who": who,
            "question": (question or "")[:500],
            "answer": (answer or "")[:1000],
            "tools_used": tools_used[:10],
            "iterations": iterations,
            "elapsed_ms": elapsed_ms,
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.info("[secretaria] log skip: %s", e)

    return {"answer": answer, "tools_used": tools_used, "iterations": iterations}


async def _chat_with_tools(cid: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Wrapper que faz uma chamada ao OpenRouter com tools. Devolve {message}.

    NOTA: como `motor_ia.chat_completion()` não expõe `tools` diretamente,
    construímos a chamada usando o mesmo cliente HTTP do Motor IA. Mantém
    coerência com o kill-switch e log de uso.
    """
    from services.motor_ia import (
        DEFAULT_TEXT_MODEL,
        _build_text_client,  # type: ignore
        get_motor_config,
        is_agent_enabled,
        _log_usage,  # type: ignore
    )

    if not await is_agent_enabled(cid, AGENT_ID):
        raise AgentDisabledError(AGENT_ID)

    cfg = await get_motor_config(cid)
    api_key = cfg.get("openrouter_api_key") or ""
    if not cfg.get("enabled") or not api_key:
        raise RuntimeError("Motor IA não configurado. Configure em Sistemas → Motor IA.")

    model = cfg.get("default_text_model") or DEFAULT_TEXT_MODEL
    client = _build_text_client(api_key)
    resp = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.3,
        max_tokens=800,
        tools=TOOLS_SPEC,
        tool_choice="auto",
    )
    choice = resp.choices[0]
    msg = choice.message
    msg_dict: Dict[str, Any] = {"content": msg.content or ""}
    if getattr(msg, "tool_calls", None):
        msg_dict["tool_calls"] = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ]
    # Log usage (best-effort)
    try:
        usage = getattr(resp, "usage", None)
        pt = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        ct = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
        await _log_usage(cid, AGENT_ID, getattr(resp, "model", model),
                           getattr(resp, "provider", None) or "openrouter", pt, ct)
    except Exception as e:
        logger.info("[secretaria] usage log skip: %s", e)
    return {"message": msg_dict}
