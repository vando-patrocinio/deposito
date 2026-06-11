"""ai_center_isabella.py — FASE 6 endpoints REST."""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Query
from rbac import require_roles
from services import isabella_scoring as isa

router = APIRouter(prefix="/api/ai-center/isabella",
                    tags=["ai-center-isabella"])


def _co(user):
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid: raise HTTPException(400, "company_id ausente")
    return cid


@router.post("/recalculate")
async def post_recalculate(
    user: Dict[str, Any] = Depends(require_roles("administrador"))):
    return await isa.calculate_all(_co(user))


@router.get("/top/{score_field}")
async def get_top(
    score_field: str,
    limit: int = Query(20, ge=1, le=100),
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor"))):
    try:
        items = await isa.top(_co(user), score_field, limit)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"items": items}


@router.get("/revenue-potential")
async def get_potential(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor"))):
    return await isa.revenue_potential(_co(user))


@router.get("/where-to-sell")
async def get_where_to_sell(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor"))):
    return await isa.where_to_sell(_co(user))


@router.post("/run-playbooks")
async def post_run_playbooks(
    user: Dict[str, Any] = Depends(require_roles("administrador"))):
    return await isa.run_playbooks(_co(user))


@router.get("/opportunities")
async def get_opportunities(
    limit: int = Query(50, ge=1, le=200),
    kind: str | None = Query(None),
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor"))):
    from database import db
    q = {"company_id": _co(user)}
    if kind: q["kind"] = kind
    cur = db.isabella_opportunities.find(q).sort(
        "created_at", -1).limit(limit)
    items = []
    async for d in cur:
        d.pop("_id", None)
        items.append(d)
    return {"items": items}
