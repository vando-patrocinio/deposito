"""routes/interactions.py — Timeline 360° por subscriber.

GET  /api/interactions/360/{subscriber_id}      — timeline ordenada
POST /api/interactions                          — registro manual (notas humanas)
POST /api/interactions/handoff                  — disparar handoff_to_human
GET  /api/interactions/handoffs                 — fila de handoffs pendentes
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, require_role
from database import db
from services.interactions import (
    CHANNELS, DIRECTION_INTERNAL, get_timeline_360,
    handoff_to_human, record_interaction,
)

router = APIRouter(prefix="/api/interactions", tags=["interactions"])


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


@router.get("/360/{subscriber_id}")
async def timeline_360(subscriber_id: str,
                        limit: int = 200,
                        channel: Optional[str] = None,
                        user: dict = Depends(require_role("gestor"))):
    if channel and channel not in CHANNELS:
        raise HTTPException(400, f"channel inválido. Use: {sorted(CHANNELS)}")
    sub = await db.subscribers.find_one(
        {"id": subscriber_id, "company_id": _cid(user)},
        {"_id": 0, "id": 1, "name": 1, "phone": 1, "plan_name": 1,
         "city": 1, "neighborhood": 1, "status": 1},
    )
    rows = await get_timeline_360(
        company_id=_cid(user), subscriber_id=subscriber_id,
        limit=min(limit, 500), channel=channel,
    )
    # Stats rápidos pra header do drawer
    counts_by_channel: Dict[str, int] = {}
    for r in rows:
        c = r.get("channel") or "note"
        counts_by_channel[c] = counts_by_channel.get(c, 0) + 1
    return {
        "subscriber": sub,
        "timeline": rows,
        "count": len(rows),
        "counts_by_channel": counts_by_channel,
    }


class InteractionIn(BaseModel):
    subscriber_id: str
    channel: str
    direction: Optional[str] = None
    content_text: Optional[str] = None
    content_meta: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None


@router.post("")
async def create_interaction(p: InteractionIn,
                              user: dict = Depends(require_role("gestor"))):
    if p.channel not in CHANNELS:
        raise HTTPException(400, f"channel inválido. Use: {sorted(CHANNELS)}")
    doc = await record_interaction(
        company_id=_cid(user), subscriber_id=p.subscriber_id,
        channel=p.channel, direction=p.direction or DIRECTION_INTERNAL,
        actor=f"human:{user.get('email') or '?'}",
        content_text=p.content_text, content_meta=p.content_meta,
        tags=p.tags,
    )
    return doc


class HandoffIn(BaseModel):
    subscriber_id: Optional[str] = None
    phone: Optional[str] = None
    reason: str
    urgency: str = "normal"
    context_text: Optional[str] = None


@router.post("/handoff")
async def trigger_handoff(p: HandoffIn,
                           user: dict = Depends(require_role("gestor"))):
    if not p.subscriber_id and not p.phone:
        raise HTTPException(400, "informe subscriber_id ou phone")
    if not p.reason or len(p.reason) < 3:
        raise HTTPException(400, "reason mínimo 3 chars")
    if p.urgency not in ("low", "normal", "high"):
        raise HTTPException(400, "urgency: low | normal | high")
    out = await handoff_to_human(
        company_id=_cid(user), subscriber_id=p.subscriber_id,
        reason=p.reason, urgency=p.urgency, phone=p.phone,
        triggered_by=f"human:{user.get('email') or '?'}",
        context_text=p.context_text,
    )
    return out


@router.get("/handoffs")
async def list_pending_handoffs(status: Optional[str] = None,
                                  limit: int = 100,
                                  user: dict = Depends(require_role("gestor"))):
    """Lista tickets em fila humana (categoria aguarda_humano).

    Default: status aberto/aberta/pendente (cobre normalização interna
    do ticket_schema STATUS_ALIASES que mapeia 'aberto'→'aberta').
    """
    q: Dict[str, Any] = {"company_id": _cid(user),
                          "category": "aguarda_humano"}
    if status:
        q["status"] = status
    else:
        q["status"] = {"$in": ["aberta", "aberto", "pendente"]}
    rows = await db.tickets.find(q, {"_id": 0}).sort(
        "created_at", -1).to_list(min(limit, 500))
    return {"handoffs": rows, "count": len(rows)}
