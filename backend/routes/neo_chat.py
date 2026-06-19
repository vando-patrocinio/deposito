"""NEO • Orquestrador IA — chat unificado conectado a todos os agentes.

NEO age como um maestro: o usuário (gestor) pergunta em linguagem natural e o
NEO decide qual ferramenta usar (Isabella, Álvaro, Pâmela, Secretaria,
relatórios agendados ou timeline cross-agent) e devolve a resposta resumida.

Arquitetura:
1. `POST /api/neo-chat/ask` recebe `{question, session_id}`
2. O LLM (Emergent · gpt-4o-mini) decide qual ferramenta executar e seus
   parâmetros via prompt estruturado JSON.
3. Backend chama a ferramenta interna (lê dados das collections já existentes).
4. O LLM sintetiza a resposta final em PT-BR.
5. Mensagens são persistidas em `neo_chat_messages` para histórico.

Tools disponíveis:
- isabella_kpis(days)        — vendas/conversão da Isabella
- alvaro_tickets(days)       — tickets de suporte (Álvaro)
- camila_billing(days)       — cobranças/recebimentos (Pâmela)
- secretaria_intents(days)   — interações da Secretaria
- customer_timeline(phone)   — histórico unificado cross-agent de 1 contato
- neo_reports_recent()       — últimos relatórios gerados
- list_schedules()           — agendamentos ativos

Se a IA não conseguir mapear pra uma tool, devolve `freeform` (resposta direta).
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

import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, EMERGENT_LLM_KEY, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.neo_chat")
router = APIRouter(prefix="/api/neo-chat", tags=["neo-chat"])


# ---------------------------------------------------------------------------
# Knowledge Base de navegação (carregada uma vez no startup).
# Permite ao NEO responder "Onde eu faço X?" usando o mapa em
# /app/memory/neo_navigation_kb.md.
# ---------------------------------------------------------------------------
def _load_navigation_kb() -> str:
    try:
        kb_path = os.environ.get(
            "NEO_KB_PATH", "/app/memory/neo_navigation_kb.md")
        with open(kb_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.warning("[neo-chat] KB navegação ausente: %s", e)
        return ""


_NAV_KB: str = _load_navigation_kb()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class AskIn(BaseModel):
    question: str
    session_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Tools (funções internas que rodam queries em coleções existentes)
# ---------------------------------------------------------------------------
async def _tool_isabella_kpis(cid: str, days: int = 7) -> Dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.isoformat()
    base = {"company_id": cid, "created_at": {"$gte": since_iso}}
    out_total = await db.aihub_wa_messages.count_documents({**base, "direction": "outbound"})
    out_ai = await db.aihub_wa_messages.count_documents(
        {**base, "direction": "outbound", "auto_reply": True})
    out_human = out_total - out_ai
    inbound = await db.aihub_wa_messages.count_documents({**base, "direction": "inbound"})
    # Vendas atribuídas (best-effort)
    sales = await db.aihub_evaluations.count_documents({
        "company_id": cid, "at": {"$gte": since_iso},
        "intent": {"$in": ["venda_nova", "upgrade"]},
    })
    return {
        "agent": "Isabella",
        "period_days": days,
        "messages_outbound_ai": out_ai,
        "messages_outbound_human": out_human,
        "messages_inbound": inbound,
        "ai_share_pct": round(out_ai / out_total * 100, 1) if out_total else 0,
        "sales_intent_count": sales,
    }


async def _tool_alvaro_tickets(cid: str, days: int = 7) -> Dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.isoformat()
    # tickets criados por agentes IA (Álvaro normalmente cria via lousa_ai_triagem)
    base = {"company_id": cid, "created_at": {"$gte": since_iso}}
    total = await db.tickets.count_documents(base)
    closed = await db.tickets.count_documents({**base, "status": "closed"})
    by_alvaro = await db.tickets.count_documents({
        **base, "created_by_agent": {"$regex": "alvaro|álvaro", "$options": "i"},
    })
    # análises do Álvaro
    analyses = await db.alvaro_analyses.count_documents({
        "company_id": cid, "created_at": {"$gte": since_iso},
    }) if "alvaro_analyses" in await db.list_collection_names() else 0
    return {
        "agent": "Álvaro",
        "period_days": days,
        "tickets_total": total,
        "tickets_closed": closed,
        "tickets_created_by_alvaro": by_alvaro,
        "analyses_run": analyses,
        "resolution_rate_pct": round(closed / total * 100, 1) if total else 0,
    }


async def _tool_camila_billing(cid: str, days: int = 7) -> Dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.isoformat()
    # Mensagens da Pâmela / fluxo boleto
    base = {"company_id": cid, "created_at": {"$gte": since_iso}}
    msgs = await db.aihub_wa_messages.count_documents({
        **base, "agent": {"$in": ["boleto_flow", "camila", "pamela"]},
    })
    # Recebimentos no período (best-effort)
    paid_amount = 0.0
    try:
        cur = db.financeiro_recebimentos.find({
            "company_id": cid, "paid_at": {"$gte": since_iso},
        }, {"_id": 0, "amount": 1})
        async for row in cur:
            try:
                paid_amount += float(row.get("amount") or 0)
            except Exception:
                pass
    except Exception:
        pass
    return {
        "agent": "Pâmela",
        "period_days": days,
        "billing_messages": msgs,
        "received_amount_brl": round(paid_amount, 2),
    }


async def _tool_secretaria_intents(cid: str, days: int = 7) -> Dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.isoformat()
    base = {"company_id": cid, "at": {"$gte": since_iso}}
    total = await db.secretaria_logs.count_documents(base)
    # top intents
    pipeline = [
        {"$match": base},
        {"$group": {"_id": "$intent", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    intents: List[Dict[str, Any]] = []
    try:
        async for row in db.secretaria_logs.aggregate(pipeline):
            intents.append({"intent": row.get("_id") or "outros",
                             "count": row.get("count", 0)})
    except Exception:
        pass
    return {
        "agent": "Secretaria",
        "period_days": days,
        "total_interactions": total,
        "top_intents": intents,
    }


async def _tool_customer_timeline(cid: str, phone: str,
                                       limit: int = 50) -> Dict[str, Any]:
    """Histórico unificado cross-agent para um contato (telefone)."""
    phone_norm = re.sub(r"\D", "", phone or "")
    if not phone_norm:
        return {"error": "telefone inválido"}
    items: List[Dict[str, Any]] = []
    # WhatsApp
    try:
        cur = db.aihub_wa_messages.find({
            "company_id": cid,
            "phone": {"$regex": phone_norm[-9:]},
        }, {"_id": 0, "direction": 1, "text": 1, "created_at": 1,
            "agent": 1, "auto_reply": 1}).sort("created_at", -1).limit(limit)
        async for m in cur:
            items.append({
                "source": "whatsapp",
                "at": m.get("created_at"),
                "agent": m.get("agent") or ("ai" if m.get("auto_reply") else "human"),
                "direction": m.get("direction"),
                "text": (m.get("text") or "")[:200],
            })
    except Exception:
        pass
    # Tickets vinculados
    try:
        cur = db.tickets.find({
            "company_id": cid,
            "phone": {"$regex": phone_norm[-9:]},
        }, {"_id": 0, "id": 1, "title": 1, "status": 1, "created_at": 1,
            "created_by_agent": 1}).sort("created_at", -1).limit(20)
        async for t in cur:
            items.append({
                "source": "lousa_ticket",
                "at": t.get("created_at"),
                "agent": t.get("created_by_agent") or "humano",
                "ref": t.get("id"),
                "text": f"[{t.get('status')}] {t.get('title') or ''}",
            })
    except Exception:
        pass
    # Secretaria logs
    try:
        cur = db.secretaria_logs.find({
            "company_id": cid,
            "phone": {"$regex": phone_norm[-9:]},
        }, {"_id": 0, "intent": 1, "question": 1, "answer": 1, "at": 1}).sort("at", -1).limit(20)
        async for s in cur:
            items.append({
                "source": "secretaria",
                "at": s.get("at"),
                "agent": "secretaria",
                "text": f"[{s.get('intent') or '?'}] {(s.get('question') or '')[:120]}",
            })
    except Exception:
        pass
    items.sort(key=lambda x: x.get("at") or "", reverse=True)
    return {
        "phone": phone_norm,
        "total": len(items),
        "items": items[:limit],
    }


async def _tool_neo_reports_recent(cid: str, limit: int = 10) -> Dict[str, Any]:
    items = await db.neo_report_runs.find(
        {"company_id": cid}, {"_id": 0},
    ).sort("at", -1).limit(limit).to_list(limit)
    return {"recent_runs": items, "total": len(items)}


async def _tool_list_schedules(cid: str) -> Dict[str, Any]:
    items = await db.neo_report_schedules.find(
        {"company_id": cid, "active": True}, {"_id": 0, "id": 1, "name": 1,
            "report_type": 1, "frequency": 1, "next_run_at": 1},
    ).limit(50).to_list(50)
    return {"active_schedules": items, "total": len(items)}


TOOLS: Dict[str, Any] = {
    "isabella_kpis": _tool_isabella_kpis,
    "alvaro_tickets": _tool_alvaro_tickets,
    "camila_billing": _tool_camila_billing,
    "secretaria_intents": _tool_secretaria_intents,
    "customer_timeline": _tool_customer_timeline,
    "neo_reports_recent": _tool_neo_reports_recent,
    "list_schedules": _tool_list_schedules,
}


TOOL_CATALOG_PROMPT = """
Você é o NEO — assistente executivo da operação SmartProv (ISP). Sua função é
responder perguntas do gestor consultando dados consolidados dos agentes IA da
empresa (Isabella, Álvaro, Pâmela e Secretaria) e dos relatórios agendados.

Ao receber uma pergunta, decida qual UMA ferramenta usar e quais parâmetros
passar. Sua saída DEVE ser um JSON válido:

{ "tool": "<nome_da_ferramenta>", "params": { ... }, "intent_summary": "..." }

Ferramentas disponíveis:
- isabella_kpis(days:int=7)      — KPIs da Isabella (vendas/conversão WhatsApp)
- alvaro_tickets(days:int=7)     — Tickets do Álvaro (suporte técnico)
- camila_billing(days:int=7)     — Cobranças e recebimentos da Pâmela
- secretaria_intents(days:int=7) — Interações da Secretaria + top intents
- customer_timeline(phone:str)   — Histórico unificado de UM contato pelo telefone
- neo_reports_recent()           — Últimos relatórios agendados executados
- list_schedules()               — Agendamentos ativos

Se a pergunta NÃO precisar de DADOS (cumprimento, ajuda, "onde fica X?", "qual
aba", "como faço Y?"), responda:
{ "tool": "freeform", "answer": "<resposta direta em PT-BR>" }

Para perguntas de NAVEGAÇÃO ("onde", "qual aba", "como acesso", "em que menu"),
use o mapa abaixo (KB de Navegação) e devolva resposta direta no `answer`,
sempre no formato:
  "Sidebar > Caminho > Aba/Botão"
e adicione 1 dica útil quando aplicável.

==================== KB DE NAVEGAÇÃO SmartProv ====================
{NAV_KB}
==================== FIM KB ====================

Regras:
- Sempre PT-BR.
- Se a pergunta envolver telefone/CPF, extraia só dígitos e use customer_timeline.
- Se a pergunta mencionar "última semana" use days=7; "mês" use days=30; "hoje" use days=1.
- Se a pergunta for de NAVEGAÇÃO, use freeform com resposta baseada no KB.
- Se NÃO houver mapeamento no KB, responda "Não tenho mapeamento exato. Verifique em <sugestão>".
- Apenas UM JSON, sem markdown.
""".replace("{NAV_KB}", _NAV_KB or "(KB de navegação indisponível neste ambiente)")


SUMMARIZE_PROMPT = """
Você é o NEO. O usuário perguntou: "{question}"
A ferramenta `{tool}` retornou estes dados (JSON):

```json
{data}
```

Escreva uma resposta CURTA (até 6 linhas), em PT-BR, executiva, com números
formatados (R$ ou %), destacando insight principal. Use markdown leve (negrito
em números). Não invente dados. Se vazio, diga "Sem dados no período".
"""


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------
def _llm_chat(session_id: str, system: str):
    """Cria um LlmChat com Emergent LLM key (gpt-4o-mini)."""
    from emergentintegrations.llm.chat import LlmChat
    if not EMERGENT_LLM_KEY:
        raise HTTPException(503, "EMERGENT_LLM_KEY não configurada")
    return LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message=system,
    ).with_model("openai", "gpt-4o-mini")


def _parse_json_loose(raw: str) -> Dict[str, Any]:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", raw, flags=re.M)
    m = re.search(r"\{.*\}", raw, flags=re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/ask")
async def ask_neo(payload: AskIn,
                    user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    session_id = payload.session_id or f"neo-{uuid.uuid4().hex[:10]}"
    question = (payload.question or "").strip()
    if not question:
        raise HTTPException(400, "Pergunta vazia")

    # Persistir mensagem do usuário
    user_msg_id = f"nmsg-{uuid.uuid4().hex[:12]}"
    await db.neo_chat_messages.insert_one({
        "id": user_msg_id,
        "company_id": cid,
        "session_id": session_id,
        "role": "user",
        "text": question,
        "at": now_iso(),
        "user_id": user.get("id"),
    })

    # 1) LLM escolhe ferramenta
    try:
        from emergentintegrations.llm.chat import UserMessage
        chat1 = _llm_chat(f"{session_id}-route", TOOL_CATALOG_PROMPT)
        raw1 = await chat1.send_message(UserMessage(text=question))
        decision = _parse_json_loose(raw1)
    except Exception as e:
        logger.warning("[neo-chat] LLM route fail: %s", e)
        decision = {"tool": "freeform", "answer": "Desculpe, estou com instabilidade na IA. Tente novamente em segundos."}

    tool_name = decision.get("tool") or "freeform"
    params = decision.get("params") or {}

    # 2) Executar ferramenta (ou freeform)
    tool_data: Any = None
    final_answer = ""
    if tool_name == "freeform":
        final_answer = decision.get("answer") or "Como posso ajudar?"
    elif tool_name in TOOLS:
        try:
            fn = TOOLS[tool_name]
            # filtra apenas parâmetros aceitos
            allowed_kwargs = {}
            if tool_name == "customer_timeline":
                allowed_kwargs["phone"] = str(params.get("phone") or "")
            else:
                if "days" in params:
                    try:
                        allowed_kwargs["days"] = max(1, min(90, int(params["days"])))
                    except Exception:
                        pass
            tool_data = await fn(cid, **allowed_kwargs)
        except Exception as e:
            logger.exception("[neo-chat] tool %s fail: %s", tool_name, e)
            tool_data = {"error": str(e)}

        # 3) LLM sintetiza
        try:
            from emergentintegrations.llm.chat import UserMessage
            chat2 = _llm_chat(f"{session_id}-sum", "Você é o NEO. Responda em PT-BR, breve e executivo.")
            prompt = SUMMARIZE_PROMPT.format(
                question=question, tool=tool_name,
                data=json.dumps(tool_data, ensure_ascii=False, default=str)[:6000],
            )
            final_answer = await chat2.send_message(UserMessage(text=prompt))
        except Exception as e:
            logger.warning("[neo-chat] LLM summarize fail: %s", e)
            final_answer = f"Resultado bruto da ferramenta `{tool_name}`:\n```\n{json.dumps(tool_data, ensure_ascii=False, default=str, indent=2)[:1200]}\n```"
    else:
        final_answer = f"Ferramenta `{tool_name}` desconhecida."

    # Persistir resposta do NEO
    neo_msg_id = f"nmsg-{uuid.uuid4().hex[:12]}"
    await db.neo_chat_messages.insert_one({
        "id": neo_msg_id,
        "company_id": cid,
        "session_id": session_id,
        "role": "assistant",
        "text": final_answer,
        "tool": tool_name,
        "tool_params": params,
        "tool_data": tool_data,
        "at": now_iso(),
    })

    return {
        "session_id": session_id,
        "answer": final_answer,
        "tool": tool_name,
        "tool_data": tool_data,
        "message_id": neo_msg_id,
    }


@router.get("/history")
async def chat_history(session_id: Optional[str] = Query(None),
                          limit: int = Query(50, ge=1, le=200),
                          user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if session_id:
        q["session_id"] = session_id
    items = await db.neo_chat_messages.find(
        q, {"_id": 0},
    ).sort("at", -1).limit(limit).to_list(limit)
    items.reverse()
    return {"items": items, "total": len(items)}


@router.get("/sessions")
async def list_sessions(limit: int = Query(20, ge=1, le=100),
                          user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    pipeline = [
        {"$match": {"company_id": cid}},
        {"$sort": {"at": -1}},
        {"$group": {
            "_id": "$session_id",
            "last_at": {"$first": "$at"},
            "first_text": {"$last": "$text"},
            "msg_count": {"$sum": 1},
        }},
        {"$sort": {"last_at": -1}},
        {"$limit": limit},
    ]
    sessions: List[Dict[str, Any]] = []
    async for row in db.neo_chat_messages.aggregate(pipeline):
        sessions.append({
            "session_id": row["_id"],
            "last_at": row.get("last_at"),
            "preview": (row.get("first_text") or "")[:80],
            "msg_count": row.get("msg_count", 0),
        })
    return {"items": sessions, "total": len(sessions)}


@router.get("/tools")
async def list_tools(user: dict = Depends(require_role("gestor"))):
    """Lista de ferramentas disponíveis ao NEO (debug/docs)."""
    return {
        "tools": [
            {"name": "isabella_kpis", "params": {"days": "int 1-90"},
             "description": "KPIs da Isabella (vendas/conversão WhatsApp)"},
            {"name": "alvaro_tickets", "params": {"days": "int 1-90"},
             "description": "Tickets do Álvaro (suporte técnico)"},
            {"name": "camila_billing", "params": {"days": "int 1-90"},
             "description": "Cobranças e recebimentos da Pâmela"},
            {"name": "secretaria_intents", "params": {"days": "int 1-90"},
             "description": "Interações da Secretaria + top intents"},
            {"name": "customer_timeline", "params": {"phone": "str"},
             "description": "Histórico cross-agent de UM contato"},
            {"name": "neo_reports_recent", "params": {},
             "description": "Últimos relatórios gerados"},
            {"name": "list_schedules", "params": {},
             "description": "Agendamentos ativos"},
        ],
    }
