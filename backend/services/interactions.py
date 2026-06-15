"""interactions.py — Coleção unificada 360° por subscriber (P0 CTO 2026-02).

Hoje contatos com cliente estão fragmentados em 5+ collections distintas:
  - wa_messages (WhatsApp Baileys/Meta)
  - tickets / lousa_history (OSs e atendimento técnico)
  - subscriber_notes (anotações manuais)
  - financeiro_alerts (cobrança)
  - marker_router_log (decisões IA)

Sem timeline unificada, NINGUÉM consegue responder "o que aconteceu com este
cliente?" em <30s. Isso quebra atendimento, retenção e auditoria PROCON/LGPD.

Esta coleção é APPEND-ONLY. Cada interação relevante é REGISTRADA via
`record_interaction(...)` chamado por chokepoints. Painel 360° consulta
`/api/interactions/360/{subscriber_id}` que retorna timeline ordenada.

`handoff_to_human(...)` é o canal oficial para IA passar a bola pra
humano. Grava interaction tipo `handoff` + cria ticket Lousa pendente
+ flag a conversa WA + retorna IDs para o caller usar no marker.
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "interactions",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["interaction.recorded", "handoff.created"],
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db

log = logging.getLogger("ponto.interactions")

# Canais oficiais
CHANNEL_WHATSAPP = "whatsapp"
CHANNEL_TICKET = "ticket"
CHANNEL_LOUSA = "lousa"
CHANNEL_ISABELLA = "isabella"
CHANNEL_PHONE = "phone"
CHANNEL_EMAIL = "email"
CHANNEL_HANDOFF = "handoff"
CHANNEL_CTO = "cto"
CHANNEL_NOTE = "note"

CHANNELS = {
    CHANNEL_WHATSAPP, CHANNEL_TICKET, CHANNEL_LOUSA, CHANNEL_ISABELLA,
    CHANNEL_PHONE, CHANNEL_EMAIL, CHANNEL_HANDOFF, CHANNEL_CTO, CHANNEL_NOTE,
}

DIRECTION_IN = "in"     # cliente → empresa
DIRECTION_OUT = "out"   # empresa → cliente
DIRECTION_INTERNAL = "internal"  # nota/handoff dentro da empresa


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def record_interaction(
    *, company_id: str, subscriber_id: Optional[str],
    channel: str, direction: str, actor: str,
    content_text: Optional[str] = None,
    content_meta: Optional[Dict[str, Any]] = None,
    tags: Optional[List[str]] = None,
    related_negotiation_id: Optional[str] = None,
    related_ticket_id: Optional[str] = None,
    handoff_id: Optional[str] = None,
    occurred_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Append-only. NUNCA falha — não pode quebrar fluxo de WhatsApp/Lousa.

    Args:
        actor: "subscriber" | "isabella" | "human:<email>" | "system" | "cto"
        channel: ver constantes CHANNEL_*
        direction: in | out | internal
        content_text: preview/resumo (max 2000 chars)
        content_meta: ids correlatos (wa_msg_id, ticket_id, etc)
        tags: ex ["negotiation", "second_invoice", "complaint", "praise"]
    """
    if channel not in CHANNELS:
        log.warning("interactions: invalid channel %s — defaulting to note", channel)
        channel = CHANNEL_NOTE
    iid = f"int-{uuid.uuid4().hex[:14]}"
    doc = {
        "id": iid,
        "company_id": company_id,
        "subscriber_id": subscriber_id,
        "channel": channel,
        "direction": direction or DIRECTION_INTERNAL,
        "actor": actor,
        "content_text": (content_text or "")[:2000] or None,
        "content_meta": content_meta or {},
        "tags": tags or [],
        "related_negotiation_id": related_negotiation_id,
        "related_ticket_id": related_ticket_id,
        "handoff_id": handoff_id,
        "occurred_at": occurred_at or _now(),
        "created_at": _now(),
    }
    try:
        await db.interactions.insert_one(dict(doc))
    except Exception as e:
        log.warning("interactions insert failed: %s", e)
    return doc


async def handoff_to_human(
    *, company_id: str, subscriber_id: Optional[str],
    reason: str, urgency: str = "normal",
    phone: Optional[str] = None,
    triggered_by: str = "isabella",
    context_text: Optional[str] = None,
    negotiation_attempt_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Pasa atendimento para humano de forma auditável e idempotente.

    1. Grava interaction `channel=handoff`.
    2. Cria ticket Lousa categoria `aguarda_humano` (status=aberto, priority
       conforme urgency).
    3. Se phone informado, pausa IA na wa_conversation (`ai_paused=true`,
       `routed_to=handoff`).
    4. Retorna {handoff_id, ticket_id, interaction_id}.

    Args:
        urgency: low | normal | high
        reason: motivo curto (ex "negotiation_blocked:discount_above_threshold")
    """
    handoff_id = f"hof-{uuid.uuid4().hex[:12]}"
    priority = {"low": "baixa", "normal": "media",
                "high": "alta"}.get(urgency, "media")

    # 1) Ticket Lousa pra fila humana
    ticket_id = f"tkt-{uuid.uuid4().hex[:10]}"
    snap = {"phone": phone}
    if subscriber_id:
        sub = await db.subscribers.find_one(
            {"id": subscriber_id},
            {"_id": 0, "name": 1, "phone": 1, "address": 1,
             "neighborhood": 1, "city": 1, "plan_name": 1},
        )
        if sub:
            snap = {**sub, **({"phone": phone} if phone else {})}
    ticket_doc = {
        "id": ticket_id,
        "company_id": company_id,
        "type": "atendimento_humano",
        "category": "aguarda_humano",
        "status": "aberto",
        "priority": priority,
        "subscriber_id": subscriber_id,
        "client_snapshot": snap,
        "origin_source": f"handoff:{triggered_by}",
        "origin_phone": phone,
        "notes": f"Handoff Isabella → humano. Motivo: {reason}\n\n"
                  f"Contexto: {context_text or '(sem contexto adicional)'}",
        "handoff_id": handoff_id,
        "handoff_reason": reason,
        "handoff_urgency": urgency,
        "created_at": _now(),
        "mobile_visible": False,  # ticket de fila humana, não vai pro técnico
    }
    try:
        await db.tickets.insert_one(dict(ticket_doc))
    except Exception as e:
        log.warning("handoff ticket insert failed: %s", e)
        ticket_id = None

    # 2) Pausa IA na conversa WA
    if phone:
        try:
            await db.wa_conversations.update_one(
                {"company_id": company_id, "phone": phone},
                {"$set": {
                    "ai_paused": True, "ai_paused_at": _now(),
                    "ai_pause_reason": f"handoff:{reason}",
                    "routed_to": "humano_handoff",
                    "handoff_id": handoff_id,
                }},
            )
        except Exception as e:
            log.warning("wa_conversations pause failed: %s", e)

    # 3) Grava interaction
    interaction = await record_interaction(
        company_id=company_id, subscriber_id=subscriber_id,
        channel=CHANNEL_HANDOFF, direction=DIRECTION_INTERNAL,
        actor=f"handoff:{triggered_by}",
        content_text=f"[HANDOFF] {reason}",
        content_meta={"urgency": urgency, "phone": phone,
                      "context": context_text},
        tags=["handoff", urgency, triggered_by],
        related_ticket_id=ticket_id,
        related_negotiation_id=negotiation_attempt_id,
        handoff_id=handoff_id,
    )

    log.info("[handoff_to_human] cid=%s sub=%s reason=%s urgency=%s ticket=%s",
             company_id, subscriber_id, reason, urgency, ticket_id)

    return {
        "handoff_id": handoff_id,
        "ticket_id": ticket_id,
        "interaction_id": interaction.get("id"),
        "urgency": urgency,
        "reason": reason,
    }


async def get_timeline_360(
    *, company_id: str, subscriber_id: str, limit: int = 200,
    channel: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retorna timeline ordenada desc por occurred_at."""
    q: Dict[str, Any] = {"company_id": company_id,
                         "subscriber_id": subscriber_id}
    if channel:
        q["channel"] = channel
    rows = await db.interactions.find(q, {"_id": 0}).sort(
        "occurred_at", -1).to_list(limit)
    return rows
