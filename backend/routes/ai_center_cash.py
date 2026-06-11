"""ai_center_cash.py — V7.1 OPERAÇÃO CAIXA endpoints."""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from fastapi import APIRouter, Depends, HTTPException

from rbac import require_roles
from services import cash_operation as cash

router = APIRouter(prefix="/api/ai-center/cash",
                    tags=["ai-center-cash"])


def _co(user):
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid: raise HTTPException(400, "company_id ausente")
    return cid


@router.get("/war-room")
async def get_war_room(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return await cash.war_room(_co(user))


@router.get("/kpi-money")
async def get_kpi(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return await cash.kpi_money_generated(_co(user))


@router.get("/action-to-cash")
async def get_a2c(days: int = 30,
                    user=Depends(require_roles(
                        "administrador", "auditor", "gestor"))):
    return await cash.action_to_cash(_co(user), days)


@router.get("/attribution")
async def get_attribution(group_by: str = "action_kind",
                            days: int = 30,
                            user=Depends(require_roles(
                                "administrador", "auditor", "gestor"))):
    return await cash.revenue_attribution_by(_co(user), group_by, days)


@router.get("/go-live")
async def get_go_live(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return await cash.go_live_status(_co(user))


@router.get("/top-money-actions")
async def get_top_money(top_n: int = 10,
                         user=Depends(require_roles(
                             "administrador", "auditor", "gestor"))):
    return await cash.top_money_actions(_co(user), top_n)
