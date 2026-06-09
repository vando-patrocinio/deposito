"""ai_center_smartolt_twin.py — FASE 4 endpoints REST."""
from __future__ import annotations
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException
from rbac import require_roles
from services import smartolt_twin as twin

router = APIRouter(prefix="/api/ai-center/smartolt-twin",
                    tags=["ai-center-smartolt-twin"])

def _co(user):
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid: raise HTTPException(400, "company_id ausente")
    return cid

@router.get("/cto-health")
async def get_cto_health(user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor"))):
    return {"items": await twin.cto_health(_co(user))}

@router.get("/pon-health")
async def get_pon_health(user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor"))):
    return {"items": await twin.pon_health(_co(user))}

@router.get("/vlan-health")
async def get_vlan_health(user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor"))):
    return {"items": await twin.vlan_health(_co(user))}

@router.get("/heatmap")
async def get_heatmap(user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor"))):
    return {"items": await twin.heatmap_by_zone(_co(user))}

@router.get("/predictions")
async def get_predictions(user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor"))):
    return await twin.predictions(_co(user))

@router.get("/revenue-at-risk")
async def get_revenue_at_risk(user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor"))):
    return await twin.revenue_at_risk(_co(user))

@router.get("/what-to-worry")
async def get_what_to_worry(user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor"))):
    return await twin.what_to_worry(_co(user))
