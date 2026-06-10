"""Endpoints OPERAÇÃO ISABELLA AGENDA NA LOUSA — /api/isabella-lousa/*."""
from __future__ import annotations
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import require_role
from rbac import require_roles
from services import isabella_lousa_scheduler as ils
from services import isabella_lousa_metrics as ilm

router = APIRouter(prefix="/api/isabella-lousa", tags=["isabella-lousa"])


class ProposeIn(BaseModel):
    subscriber_id: Optional[str] = None
    phone: Optional[str] = None
    user_text: str


@router.post("/propose-window")
async def propose_window(payload: ProposeIn,
                            user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id")
    return await ils.propose_window(cid, payload.subscriber_id, payload.user_text)


class ConfirmIn(BaseModel):
    subscriber_id: Optional[str] = None
    phone: str
    user_text: str
    proposal: Dict[str, Any]
    confirmation_text: str = "sim"


@router.post("/confirm-create-os")
async def confirm_create_os(payload: ConfirmIn,
                                user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id")
    res = await ils.confirm_and_create_os(
        company_id=cid,
        subscriber_id=payload.subscriber_id,
        phone=payload.phone, user_text=payload.user_text,
        proposal=payload.proposal,
        confirmation_text=payload.confirmation_text)
    if res.get("error"):
        raise HTTPException(400, res["error"])
    return res


@router.get("/follow-up")
async def follow_up(phone: Optional[str] = None,
                       user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id")
    return await ils.followup_open_tickets_by_isabella(cid, phone=phone)


@router.get("/decide")
async def decide(user_text: str, subscriber_id: Optional[str] = None,
                    user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id")
    return await ils.decide_action(cid, subscriber_id, user_text)


@router.get("/metrics")
async def metrics(days: int = 7,
                     user: dict = Depends(require_roles(
                         "administrador", "gestor", "auditor"))):
    """KPIs das OS criadas pela Isabella na Lousa.

    Aceita admin/gestor/auditor. Lê APENAS coleções existentes.
    """
    cid = user.get("company_id")
    days = max(1, min(days, 90))
    return await ilm.isabella_lousa_metrics(cid, days=days)
