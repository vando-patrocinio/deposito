"""
agent_tools.py — Toolkit do Agente IA do Conselho Estratégico (iter215bt)

Cada "tool" é uma função executável que o LLM pode invocar.
Registro central + executor com whitelist (Modelo B).

iter215bw — Notificações proativas: após executar uma ação, o agente
manda um resumo no WhatsApp do operador configurado em
`conselho_ia_settings.notify_phone`.
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

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from database import db

logger = logging.getLogger(__name__)

SIDECAR_BASE = os.environ.get("WHATSAPP_SIDECAR_BASE",
                                 "http://127.0.0.1:3002")
WA_SEND_TIMEOUT = 10.0


async def _send_wa_summary(cid: str, phone: str, action: Dict[str, Any]
                              ) -> bool:
    """Envia 1 mensagem ao operador resumindo a ação que o agente
    executou. Best-effort, não bloqueia se falhar."""
    if not phone or not action:
        return False
    tool = action.get("tool", "?")
    status = action.get("status", "?")
    just = action.get("justification", "")
    result = action.get("result") or {}
    LABELS = {
        "flag_dunning": "Marcar para cobrança",
        "create_inspection_ticket": "Criar chamado de inspeção",
        "bulk_whatsapp_campaign": "Rascunho de campanha WhatsApp",
        "escalate_dunning": "Escalar régua de cobrança",
        "assign_technician": "Atribuir técnico a chamado",
        "pause_promo_inactive": "Pausar promoção inativa",
    }
    title = LABELS.get(tool, tool)
    matched = result.get("matched") or result.get("targets") or ""
    matched_str = f" ({matched} registros)" if matched else ""
    text = (
        f"*Agente IA · Conselho Estratégico*\n\n"
        f"Acabei de executar: *{title}*{matched_str}\n"
        f"Status: {status}\n\n"
        f"_{just}_\n\n"
        f"Veja em Conselho IA > Timeline."
    )
    try:
        async with httpx.AsyncClient(timeout=WA_SEND_TIMEOUT) as cli:
            r = await cli.post(f"{SIDECAR_BASE}/send",
                                 json={"phone": phone, "text": text})
            data = {}
            try:
                data = r.json()
            except Exception:
                pass
            ok = r.status_code < 400 and data.get("ok")
            if not ok:
                logger.warning("[agent_ia] WA falhou: %s body=%s",
                                r.status_code, data.get("error") or "")
            return bool(ok)
    except Exception as e:
        logger.warning("[agent_ia] WA exc: %s", e)
        return False


async def _maybe_notify_operator(cid: str,
                                    action_result: Dict[str, Any]) -> None:
    """Lê config `conselho_ia_settings` e dispara WA se estiver
    habilitado."""
    cfg = await db.conselho_ia_settings.find_one(
        {"company_id": cid}, {"_id": 0}) or {}
    if not cfg.get("notify_on_action"):
        return
    phone = cfg.get("notify_phone")
    if not phone:
        return
    # Só notifica em ações realmente executadas
    if action_result.get("status") != "executed":
        return
    await _send_wa_summary(cid, phone, action_result)


# ───── Catálogo (description vai pro LLM) ─────
TOOL_CATALOG: Dict[str, Dict[str, Any]] = {
    "flag_dunning": {
        "description": (
            "Marca uma lista de assinantes (subscriber_ids) pra "
            "entrar na régua de cobrança. Apenas marca um campo "
            "`dunning_queue=True` e `dunning_flagged_at`, sem "
            "disparar mensagem. Use quando inadimplência for "
            "detectada. Limite máximo: 100 ids por chamada."),
        "args_schema": {
            "subscriber_ids": "list[str] — até 100 ids",
            "reason": "string — motivo (ex.: 'Detectado pelo Conselho IA')",
        },
        "auto_apply": True,
    },
    "create_inspection_ticket": {
        "description": (
            "Cria um chamado de inspeção técnica em uma CTO. "
            "Use quando o relatório identificar CTO com >85% "
            "de saturação ou múltiplos chamados na região."),
        "args_schema": {
            "cto_id": "string — id da CTO",
            "reason": "string — motivo (ex.: 'Saturação > 90%')",
            "priority": "string — 'baixa' | 'media' | 'alta'",
        },
        "auto_apply": True,
    },
    "bulk_whatsapp_campaign": {
        "description": (
            "Cria uma campanha de WhatsApp pra um segmento. "
            "NÃO envia automaticamente — entra como rascunho que "
            "precisa aprovação. Use pra cross-sell, retenção, NPS."),
        "args_schema": {
            "segment_name": "string — nome do segmento",
            "subscriber_ids": "list[str] — até 500 ids",
            "template": "string — texto do template",
        },
        "auto_apply": False,  # precisa aprovação humana
    },
    "escalate_dunning": {
        "description": (
            "Escala assinantes que JÁ estão na régua de cobrança "
            "(dunning_queue=True) para o próximo nível de severidade "
            "(dunning_stage). Use quando o cliente continua "
            "inadimplente após várias execuções no estágio anterior. "
            "Não cria nova régua, apenas eleva. Limite: 100 ids."),
        "args_schema": {
            "subscriber_ids": "list[str] — até 100 ids",
            "to_stage": "int — estágio destino 2..5 (mais alto = mais severo)",
            "reason": "string — motivo da escalada",
        },
        "auto_apply": True,
    },
    "assign_technician": {
        "description": (
            "Atribui um técnico (collaborator) a um ticket aberto. "
            "Use quando o relatório indicar tickets sem responsável "
            "ou redistribuição por carga. Falha se o técnico não "
            "estiver com role compatível ou se o ticket já estiver "
            "fechado."),
        "args_schema": {
            "ticket_id": "string — id do ticket",
            "technician_id": "string — id do collaborator/técnico",
            "reason": "string — motivo da atribuição",
        },
        "auto_apply": True,
    },
    "pause_promo_inactive": {
        "description": (
            "Pausa (active=False) uma promoção de parceria que não "
            "está gerando engajamento. Use quando uma promo tem zero "
            "ou pouquíssimos resgates em janela longa. Idempotente: "
            "pausar duas vezes não faz mal."),
        "args_schema": {
            "promotion_id": "string — id da promoção em parcerias_promotions",
            "reason": "string — motivo da pausa",
        },
        "auto_apply": True,
    },
}


def llm_tool_catalog_prompt() -> str:
    """Devolve o catálogo formatado pro prompt do LLM."""
    lines = ["CATÁLOGO DE FERRAMENTAS DISPONÍVEIS:"]
    for name, spec in TOOL_CATALOG.items():
        lines.append(f"\n  {name}({', '.join(spec['args_schema'].keys())})")
        lines.append(f"    {spec['description']}")
        for arg, t in spec["args_schema"].items():
            lines.append(f"      - {arg}: {t}")
    return "\n".join(lines)


async def _log_agent_action(cid: str, tool: str, args: Dict[str, Any],
                              status: str, result: Dict[str, Any],
                              justification: str, source: str) -> str:
    aid = f"cia-act-{uuid.uuid4().hex[:14]}"
    await db.conselho_ia_agent_actions.insert_one({
        "id": aid,
        "company_id": cid,
        "tool": tool,
        "args": args,
        "status": status,        # executed | pending | failed | rejected
        "result": result,
        "justification": justification,
        "source": source,        # "agent_ia" | "user"
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return aid


async def _exec_flag_dunning(cid: str,
                                args: Dict[str, Any]) -> Dict[str, Any]:
    ids = args.get("subscriber_ids") or []
    if not isinstance(ids, list) or len(ids) == 0:
        raise ValueError("subscriber_ids vazio ou inválido")
    ids = ids[:100]
    base_q: Dict[str, Any] = {"id": {"$in": ids}}
    if cid:
        base_q["company_id"] = cid
    r = await db.subscribers.update_many(
        base_q,
        {"$set": {
            "dunning_queue": True,
            "dunning_flagged_at": datetime.now(timezone.utc).isoformat(),
            "dunning_reason": args.get("reason", "")[:200],
        }})
    return {"matched": r.matched_count, "modified": r.modified_count,
             "ids_requested": len(ids)}


async def _exec_create_inspection_ticket(cid: str,
                                            args: Dict[str, Any]) -> Dict[str, Any]:
    cto_id = args.get("cto_id")
    if not cto_id:
        raise ValueError("cto_id ausente")
    cto = await db.ctos.find_one({"id": cto_id}, {"_id": 0})
    if not cto:
        raise ValueError(f"CTO {cto_id} não encontrada")
    ticket_id = f"tk-{uuid.uuid4().hex[:14]}"
    ticket = {
        "id": ticket_id,
        "company_id": cid,
        "type": "inspecao_preventiva",
        "subject": (f"Inspeção CTO {cto.get('label', cto_id)} — "
                     f"{args.get('reason', '')[:80]}"),
        "description": args.get("reason", ""),
        "priority": (args.get("priority", "media") or "media").lower(),
        "status": "ABERTO",
        "cto_id": cto_id,
        "neighborhood": cto.get("neighborhood"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": "agent_ia",
    }
    await db.tickets.insert_one(ticket)
    return {"ticket_id": ticket_id,
             "cto": cto.get("label", cto_id),
             "neighborhood": cto.get("neighborhood")}


async def _exec_bulk_whatsapp(cid: str,
                                 args: Dict[str, Any]) -> Dict[str, Any]:
    """NÃO envia — apenas grava o rascunho da campanha. Precisa
    aprovação humana via outro endpoint pra disparar."""
    ids = args.get("subscriber_ids") or []
    draft_id = f"camp-{uuid.uuid4().hex[:14]}"
    await db.whatsapp_campaigns_drafts.insert_one({
        "id": draft_id,
        "company_id": cid,
        "segment_name": args.get("segment_name", "Segmento IA")[:80],
        "subscriber_ids": ids[:500],
        "template": args.get("template", "")[:1000],
        "status": "pending_approval",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": "agent_ia",
    })
    return {"draft_id": draft_id, "targets": min(len(ids), 500)}


async def _exec_escalate_dunning(cid: str,
                                    args: Dict[str, Any]) -> Dict[str, Any]:
    """Eleva dunning_stage dos subscribers (somente os que já estão
    em dunning_queue=True e cujo stage atual < to_stage)."""
    ids = args.get("subscriber_ids") or []
    if not isinstance(ids, list) or len(ids) == 0:
        raise ValueError("subscriber_ids vazio ou inválido")
    ids = ids[:100]
    try:
        to_stage = int(args.get("to_stage", 0))
    except (ValueError, TypeError):
        raise ValueError("to_stage inválido (esperado int 2..5)")
    if to_stage < 2 or to_stage > 5:
        raise ValueError("to_stage fora do intervalo permitido (2..5)")

    base_q: Dict[str, Any] = {
        "id": {"$in": ids},
        "dunning_queue": True,
        "$or": [
            {"dunning_stage": {"$exists": False}},
            {"dunning_stage": {"$lt": to_stage}},
        ],
    }
    if cid:
        base_q["company_id"] = cid

    now_iso = datetime.now(timezone.utc).isoformat()
    r = await db.subscribers.update_many(
        base_q,
        {"$set": {
            "dunning_stage": to_stage,
            "dunning_escalated_at": now_iso,
            "dunning_escalation_reason": (args.get("reason") or "")[:200],
        }})
    return {"matched": r.matched_count, "modified": r.modified_count,
             "ids_requested": len(ids), "to_stage": to_stage}


async def _exec_assign_technician(cid: str,
                                     args: Dict[str, Any]) -> Dict[str, Any]:
    """Atribui um collaborator (técnico) a um ticket aberto."""
    ticket_id = args.get("ticket_id")
    tech_id = args.get("technician_id")
    if not ticket_id:
        raise ValueError("ticket_id ausente")
    if not tech_id:
        raise ValueError("technician_id ausente")

    ticket_q: Dict[str, Any] = {"id": ticket_id}
    if cid:
        ticket_q["company_id"] = cid
    ticket = await db.tickets.find_one(ticket_q, {"_id": 0, "id": 1,
        "status": 1, "type": 1, "assigned_collaborator_id": 1})
    if not ticket:
        raise ValueError(f"ticket {ticket_id} não encontrado")
    status = (ticket.get("status") or "").upper()
    if status in ("FECHADO", "RESOLVIDO", "CLOSED", "RESOLVED",
                    "CANCELADO", "CANCELED"):
        raise ValueError(f"ticket está {status}, não pode ser atribuído")

    tech_q: Dict[str, Any] = {"id": tech_id}
    if cid:
        tech_q["company_id"] = cid
    tech = await db.collaborators.find_one(tech_q, {"_id": 0,
        "id": 1, "name": 1, "role": 1, "active": 1})
    if not tech:
        raise ValueError(f"técnico {tech_id} não encontrado")
    if tech.get("active") is False:
        raise ValueError(f"técnico {tech.get('name')} está inativo")
    role = (tech.get("role") or "").lower()
    if "tec" not in role and "colab" not in role and "instal" not in role:
        raise ValueError(f"role '{tech.get('role')}' não é técnico/colab")

    now_iso = datetime.now(timezone.utc).isoformat()
    r = await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {
            "assigned_collaborator_id": tech_id,
            "assigned_by": "agent_ia",
            "assigned_at": now_iso,
            "assign_reason": (args.get("reason") or "")[:200],
            "updated_at": now_iso,
        }})
    return {"ticket_id": ticket_id, "technician_id": tech_id,
             "technician_name": tech.get("name"),
             "previous_assignee": ticket.get("assigned_collaborator_id"),
             "matched": r.matched_count, "modified": r.modified_count}


async def _exec_pause_promo_inactive(cid: str,
                                        args: Dict[str, Any]) -> Dict[str, Any]:
    """Pausa (active=False) uma promoção de parceria."""
    promo_id = args.get("promotion_id")
    if not promo_id:
        raise ValueError("promotion_id ausente")

    promo_q: Dict[str, Any] = {"id": promo_id}
    if cid:
        promo_q["company_id"] = cid
    promo = await db.parcerias_promotions.find_one(promo_q, {"_id": 0,
        "id": 1, "title": 1, "active": 1, "partner_name": 1,
        "total_redemptions": 1})
    if not promo:
        raise ValueError(f"promoção {promo_id} não encontrada")

    if promo.get("active") is False:
        # Idempotente: já está pausada
        return {"promotion_id": promo_id, "title": promo.get("title"),
                 "already_paused": True, "matched": 1, "modified": 0}

    now_iso = datetime.now(timezone.utc).isoformat()
    r = await db.parcerias_promotions.update_one(
        {"id": promo_id},
        {"$set": {
            "active": False,
            "paused_at": now_iso,
            "paused_by": "agent_ia",
            "pause_reason": (args.get("reason") or "")[:200],
        }})
    return {"promotion_id": promo_id, "title": promo.get("title"),
             "partner_name": promo.get("partner_name"),
             "total_redemptions": promo.get("total_redemptions", 0),
             "matched": r.matched_count, "modified": r.modified_count}


TOOL_EXECUTORS = {
    "flag_dunning": _exec_flag_dunning,
    "create_inspection_ticket": _exec_create_inspection_ticket,
    "bulk_whatsapp_campaign": _exec_bulk_whatsapp,
    "escalate_dunning": _exec_escalate_dunning,
    "assign_technician": _exec_assign_technician,
    "pause_promo_inactive": _exec_pause_promo_inactive,
}


async def execute_tool_call(cid: str, call: Dict[str, Any]) -> Dict[str, Any]:
    """Executa uma chamada de ferramenta.
    Modelo B (whitelist): se `auto_apply=True` no catálogo, executa.
    Se `auto_apply=False`, marca como `pending` (precisa aprovação).

    call = {tool, args, justification}
    Retorna {tool, status, result, action_id}.
    """
    tool = call.get("tool")
    args = call.get("args") or {}
    just = call.get("justification", "")

    if tool not in TOOL_CATALOG:
        aid = await _log_agent_action(cid, tool or "?", args, "rejected",
            {"error": "tool desconhecida"}, just, "agent_ia")
        return {"tool": tool, "status": "rejected", "error": "unknown_tool",
                 "action_id": aid}

    spec = TOOL_CATALOG[tool]
    if not spec.get("auto_apply", False):
        # pending — só registra, não executa
        aid = await _log_agent_action(cid, tool, args, "pending",
            {"reason": "requires_human_approval"}, just, "agent_ia")
        return {"tool": tool, "status": "pending", "action_id": aid}

    # auto-execute
    executor = TOOL_EXECUTORS.get(tool)
    if not executor:
        aid = await _log_agent_action(cid, tool, args, "failed",
            {"error": "executor não implementado"}, just, "agent_ia")
        return {"tool": tool, "status": "failed",
                 "error": "no_executor", "action_id": aid}
    try:
        result = await executor(cid, args)
        aid = await _log_agent_action(cid, tool, args, "executed",
            result, just, "agent_ia")
        out = {"tool": tool, "status": "executed", "result": result,
                "action_id": aid}
        # iter215bw — notifica o operador via WhatsApp (best-effort)
        try:
            await _maybe_notify_operator(cid, out)
        except Exception:
            logger.exception("[agent_ia] notify operator falhou")
        return out
    except Exception as e:
        logger.exception("[agent_ia] tool %s falhou: %s", tool, e)
        aid = await _log_agent_action(cid, tool, args, "failed",
            {"error": str(e)}, just, "agent_ia")
        return {"tool": tool, "status": "failed",
                 "error": str(e), "action_id": aid}
