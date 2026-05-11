"""Lousa AI · Triagem — endpoints REST."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from core import DEMO_COMPANY_ID, require_role
from services.lousa_ai_triagem import (
    INTERVAL_SECONDS, revert_triage, stats, triage_ticket,
)

router = APIRouter(prefix="/api/lousa-ai", tags=["lousa-ai"])
logger = logging.getLogger("lousa_ai_triagem.routes")


@router.get("/summary")
async def summary(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    s = await stats(cid)
    s["config"] = {"interval_seconds": INTERVAL_SECONDS}
    return s


@router.post("/triage/{ticket_id}")
async def triage_one(ticket_id: str,
                       force: bool = False,
                       user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    r = await triage_ticket(cid, ticket_id, force=force)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "falha"))
    return r


@router.post("/triage/{ticket_id}/revert")
async def revert(ticket_id: str,
                   user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    r = await revert_triage(cid, ticket_id, user.get("email") or user.get("id"))
    if not r.get("ok"):
        raise HTTPException(404, r.get("error"))
    return r
