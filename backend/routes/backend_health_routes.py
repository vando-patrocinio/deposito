"""
backend_health_routes.py — Sprint 6 / iter225
Rotas REST do painel de saúde técnica.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from typing import Any, Dict

from fastapi import APIRouter, Depends, Query

from rbac import require_roles
from services import backend_health as bh

router = APIRouter(prefix="/api/health-panel", tags=["health"])


@router.get("/deep")
async def deep_status(
    window_seconds: int = Query(3600, ge=60, le=86400),
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
):
    return await bh.deep_health(window_seconds=window_seconds)


@router.get("/latency")
async def latency(
    window_seconds: int = Query(3600, ge=60, le=86400),
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
):
    return bh.latency_snapshot(window_seconds=window_seconds)


@router.get("/services")
async def services(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
):
    return {"services": await bh.all_services()}


@router.get("/indexes")
async def indexes(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
):
    return {"hints": await bh.index_hints()}
