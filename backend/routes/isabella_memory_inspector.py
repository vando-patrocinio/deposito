"""Endpoint /api/isabella/memory/preview — Dashboard Memória da Isabella.

Reproduz a montagem do system_prompt + history_turns que a Isabella
faria AGORA para um determinado telefone (ou subscriber_id), expondo
cada bloco em separado pra o CTO/Gestor auditar o contexto real
carregado pela IA.

Sem mocks. Tudo é construído com as MESMAS funções do pipeline
de atendimento (`whatsapp_twilio._generate_isabella_reply`).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core import require_role
from database import db

logger = logging.getLogger("ponto.isabella_memory_inspector")

router = APIRouter(prefix="/api/isabella/memory",
                    tags=["isabella-memory-inspector"])


def _approx_tokens(text: str) -> int:
    """Aproximação ~4 chars/token (PT-BR)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


async def _resolve_phone(cid: str, phone: Optional[str],
                              subscriber_id: Optional[str]) -> Optional[str]:
    """Se vier só subscriber_id, tenta resolver o telefone primário."""
    if phone:
        return phone.strip()
    if not subscriber_id:
        return None
    # Tenta achar phone vinculado em subscriber_phones / aihub_wa_messages
    doc = await db.subscriber_phones.find_one(
        {"company_id": cid, "subscriber_id": subscriber_id},
        {"_id": 0, "phone": 1, "primary": 1},
        sort=[("primary", -1)],
    )
    if doc and doc.get("phone"):
        return doc["phone"]
    # Fallback — qualquer mensagem com esse subscriber_id
    msg = await db.aihub_wa_messages.find_one(
        {"company_id": cid, "subscriber_id": subscriber_id},
        {"_id": 0, "phone": 1},
        sort=[("created_at", -1)],
    )
    return (msg or {}).get("phone")


async def _resolve_subscriber_id(cid: str,
                                       phone: str) -> Optional[str]:
    """Tenta resolver o subscriber_id atual do phone."""
    try:
        from phone_normalizer import link_phone_to_subscriber
        link = await link_phone_to_subscriber(phone, cid)
        if link and link.get("subscriber_id"):
            return link["subscriber_id"]
    except Exception:
        pass
    msg = await db.aihub_wa_messages.find_one(
        {"company_id": cid, "phone": phone,
         "subscriber_id": {"$exists": True, "$ne": None}},
        {"_id": 0, "subscriber_id": 1},
        sort=[("created_at", -1)],
    )
    return (msg or {}).get("subscriber_id")


async def _build_subscriber_ctx(cid: str,
                                       subscriber_id: Optional[str]) -> str:
    """Reproduz o bloco [Dados do cliente] (best effort)."""
    if not subscriber_id:
        return ""
    sub = await db.subscribers.find_one(
        {"company_id": cid, "id": subscriber_id},
        {"_id": 0, "name": 1, "plan": 1, "status": 1, "city": 1,
         "neighborhood": 1, "due_day": 1, "cpf": 1},
    ) or await db.subscribers.find_one(
        {"company_id": cid, "_id": subscriber_id},
        {"_id": 0, "name": 1, "plan": 1, "status": 1, "city": 1,
         "neighborhood": 1, "due_day": 1, "cpf": 1},
    )
    if not sub:
        return ""
    parts = []
    for k in ("name", "plan", "status", "city", "neighborhood", "due_day"):
        if sub.get(k):
            parts.append(f"{k}: {sub[k]}")
    return " | ".join(parts)


@router.get("/preview")
async def preview_isabella_memory(
        phone: Optional[str] = Query(None, description="Telefone E.164 ou só dígitos"),
        subscriber_id: Optional[str] = Query(None),
        user_text: str = Query("sim",
                                description="Texto simulado do cliente"),
        user: dict = Depends(require_role("gestor"))) -> Dict[str, Any]:
    """Devolve cada bloco que a Isabella veria AGORA + history_turns +
    contadores de chars/tokens. Útil pra auditoria do CTO."""
    cid = user.get("company_id")
    if not cid:
        raise HTTPException(403, "company_id ausente no usuário")
    if not (phone or subscriber_id):
        raise HTTPException(400, "phone OU subscriber_id obrigatório")

    phone_resolved = await _resolve_phone(cid, phone, subscriber_id)
    if not phone_resolved:
        raise HTTPException(404, "phone não pôde ser resolvido")

    sub_id = subscriber_id or await _resolve_subscriber_id(cid, phone_resolved)

    blocks: List[Dict[str, Any]] = []
    sys_prompt_parts: List[str] = []

    # 0) Base prompt do agente Isabella
    agent = await db.aihub_agents.find_one(
        {"company_id": cid, "name": "Isabella", "active": {"$ne": False}},
        {"_id": 0, "system_prompt": 1, "temperature": 1, "max_tokens": 1},
    )
    base_prompt = (agent or {}).get("system_prompt", "")
    if base_prompt:
        blocks.append({
            "id": "base_prompt", "label": "Prompt Base do Agente",
            "content": base_prompt, "chars": len(base_prompt),
            "tokens_est": _approx_tokens(base_prompt),
        })
        sys_prompt_parts.append(base_prompt)

    # 1) Dados do cliente
    sub_ctx = await _build_subscriber_ctx(cid, sub_id)
    if sub_ctx:
        content = f"[Dados do cliente]\n{sub_ctx}"
        blocks.append({
            "id": "subscriber_ctx", "label": "Dados do Cliente",
            "content": content, "chars": len(content),
            "tokens_est": _approx_tokens(content),
        })
        sys_prompt_parts.append(content)

    # 2) Anti-CPF Guardian
    try:
        from phone_normalizer import link_phone_to_subscriber
        link = await link_phone_to_subscriber(phone_resolved, cid)
        history_inbound: List[str] = []
        async for m in db.aihub_wa_messages.find(
                {"company_id": cid, "phone": phone_resolved,
                 "direction": "inbound"},
                {"_id": 0, "text": 1}).sort("created_at", -1).limit(20):
            history_inbound.append(m.get("text", ""))
        from services.anti_cpf_guardian import inject_identification_block
        anti_cpf_block = inject_identification_block(
            link, history_inbound=history_inbound)
        if anti_cpf_block:
            blocks.append({
                "id": "anti_cpf", "label": "Guardião Anti-CPF",
                "content": anti_cpf_block, "chars": len(anti_cpf_block),
                "tokens_est": _approx_tokens(anti_cpf_block),
            })
            sys_prompt_parts.append(anti_cpf_block)
    except Exception as e:
        logger.info("[memory_inspector] anti_cpf skip: %s", e)

    # 3) Memória de curto prazo
    try:
        from services.short_term_memory_guard import (
            analyze_short_term_context, inject_memory_block,
        )
        analysis = await analyze_short_term_context(
            company_id=cid, phone=phone_resolved, user_text=user_text)
        st_block = inject_memory_block(analysis)
        if st_block:
            blocks.append({
                "id": "short_term", "label": "Memória de Curto Prazo",
                "content": st_block, "chars": len(st_block),
                "tokens_est": _approx_tokens(st_block),
                "meta": {
                    "is_short_reply": analysis.get("is_short_reply"),
                    "open_topic": analysis.get("open_topic"),
                    "last_isabella_question":
                        analysis.get("last_isabella_question"),
                },
            })
            sys_prompt_parts.append(st_block)
    except Exception as e:
        logger.info("[memory_inspector] short_term skip: %s", e)

    # 4) Memória de longo prazo (15/30/60d)
    try:
        from services.long_term_memory import (
            build_long_term_block, summarize_subscriber_history,
        )
        lt_block = await build_long_term_block(
            company_id=cid, phone=phone_resolved, subscriber_id=sub_id)
        if lt_block:
            lt_summary = await summarize_subscriber_history(
                company_id=cid, phone=phone_resolved, subscriber_id=sub_id)
            blocks.append({
                "id": "long_term",
                "label": "Memória Histórica (15/30/60 dias)",
                "content": lt_block, "chars": len(lt_block),
                "tokens_est": _approx_tokens(lt_block),
                "meta": {
                    "first_contact": lt_summary.get("first_contact"),
                    "windows": {
                        d: {
                            "messages": w.get("messages"),
                            "tickets_count": len(w.get("tickets") or []),
                            "outcomes_count": len(w.get("outcomes") or []),
                            "ledger_count": len(w.get("ledger") or []),
                        }
                        for d, w in (lt_summary.get("windows") or {}).items()
                    },
                },
            })
            sys_prompt_parts.append(lt_block)
    except Exception as e:
        logger.info("[memory_inspector] long_term skip: %s", e)

    # 5) Correções (Edit & Teach)
    try:
        from routes.ai_corrections import (fetch_recent_for_prompt,
                                              format_corrections_for_prompt)
        corr = format_corrections_for_prompt(
            await fetch_recent_for_prompt(cid, limit=12))
        if corr:
            blocks.append({
                "id": "corrections", "label": "Correções Recentes",
                "content": corr, "chars": len(corr),
                "tokens_est": _approx_tokens(corr),
            })
            sys_prompt_parts.append(corr)
    except Exception as e:
        logger.info("[memory_inspector] corrections skip: %s", e)

    # 6) Contexto orquestrado (motor_ia, truck_roll_guard, etc)
    try:
        from services.ai_orchestrator import build_orchestrated_context
        orch = await build_orchestrated_context(
            cid, phone_resolved, user_text, subscriber_id=sub_id)
        if orch:
            blocks.append({
                "id": "orchestrated", "label": "Contexto Orquestrado",
                "content": orch, "chars": len(orch),
                "tokens_est": _approx_tokens(orch),
            })
            sys_prompt_parts.append(orch)
    except Exception as e:
        logger.info("[memory_inspector] orchestrated skip: %s", e)

    # 7) History turns
    try:
        from services.ai_history import fetch_history_turns
        turns = await fetch_history_turns(cid, phone_resolved, limit=200,
                                              token_budget=6000)
    except Exception as e:
        logger.info("[memory_inspector] history_turns falhou: %s", e)
        turns = []

    history_chars = sum(len(t.get("content") or "") for t in turns)

    full_prompt = "\n\n".join(sys_prompt_parts)
    return {
        "company_id": cid,
        "phone": phone_resolved,
        "subscriber_id": sub_id,
        "simulated_user_text": user_text,
        "blocks": blocks,
        "history_turns": turns,
        "history_turns_count": len(turns),
        "history_chars": history_chars,
        "history_tokens_est": _approx_tokens("x" * history_chars),
        "full_system_prompt": full_prompt,
        "full_prompt_chars": len(full_prompt),
        "full_prompt_tokens_est": _approx_tokens(full_prompt),
        "total_payload_chars": len(full_prompt) + history_chars + len(user_text),
        "agent_settings": {
            "temperature": (agent or {}).get("temperature"),
            "max_tokens": (agent or {}).get("max_tokens"),
        },
    }


@router.get("/recent-phones")
async def list_recent_phones(
        limit: int = Query(20, ge=1, le=100),
        user: dict = Depends(require_role("gestor"))) -> Dict[str, Any]:
    """Lista os telefones com mais interação recente — atalho pro inspector."""
    cid = user.get("company_id")
    if not cid:
        raise HTTPException(403, "company_id ausente")
    pipeline = [
        {"$match": {"company_id": cid}},
        {"$group": {"_id": "$phone", "count": {"$sum": 1},
                     "last_at": {"$max": "$created_at"},
                     "subscriber_id": {"$last": "$subscriber_id"}}},
        {"$sort": {"last_at": -1}},
        {"$limit": limit},
    ]
    items: List[Dict[str, Any]] = []
    async for d in db.aihub_wa_messages.aggregate(pipeline):
        items.append({
            "phone": d["_id"],
            "messages": d.get("count", 0),
            "last_at": d.get("last_at"),
            "subscriber_id": d.get("subscriber_id"),
        })
    return {"items": items, "count": len(items)}
