"""ai_center_alvaro.py — FASE 7 endpoints REST."""
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
from services import alvaro_director as alv

router = APIRouter(prefix="/api/ai-center/alvaro",
                    tags=["ai-center-alvaro"])


def _co(user):
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid: raise HTTPException(400, "company_id ausente")
    return cid


@router.get("/director-summary")
async def get_director(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return await alv.director_summary(_co(user))


@router.get("/technicians")
async def get_technicians(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return {"items": await alv.technician_ranking(_co(user))}


@router.get("/regions")
async def get_regions(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return {"items": await alv.region_ranking(_co(user))}


@router.get("/bottlenecks")
async def get_bottlenecks(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return {"items": await alv.bottlenecks(_co(user))}


@router.get("/waste")
async def get_waste(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return await alv.waste_detection(_co(user))


@router.get("/recommendations")
async def get_recs(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return {"items": await alv.recommendations(_co(user))}


@router.post("/briefing")
async def post_briefing(
    kind: str = Query("07h", regex="^(07h|12h|18h)$"),
    user=Depends(require_roles("administrador"))):
    return await alv.daily_briefing(_co(user), kind=kind)


@router.get("/briefings")
async def get_briefings(
    limit: int = Query(20, ge=1, le=100),
    user=Depends(require_roles("administrador", "auditor", "gestor"))):
    from database import db
    cur = db.motor_ia_daily_briefings.find(
        {"company_id": _co(user)}).sort("generated_at", -1).limit(limit)
    items = []
    async for d in cur:
        d.pop("_id", None)
        items.append(d)
    return {"items": items}
