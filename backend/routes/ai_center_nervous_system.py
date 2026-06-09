"""
ai_center_nervous_system.py — FASE 3 Constituição V3.0
Endpoints REST do Sistema Nervoso 90%.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from rbac import require_roles
from services import nervous_coverage as nc
from services import nervous_synchronizer as ns


router = APIRouter(prefix="/api/ai-center/nervous-system",
                    tags=["ai-center-nervous-system"])


def _company_id(user: Dict[str, Any]) -> str:
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid:
        raise HTTPException(400, "company_id ausente")
    return cid


@router.get("/coverage")
async def get_coverage(
    window_days: int = Query(7, ge=1, le=90),
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    """Cobertura nervosa por domínio."""
    return await nc.coverage_report(_company_id(user), window_days=window_days)


@router.get("/top-events")
async def get_top_events(
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(20, ge=1, le=50),
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    return {"items": await nc.top_events(_company_id(user),
                                              hours=hours, limit=limit)}


@router.get("/by-domain")
async def get_by_domain(
    hours: int = Query(24, ge=1, le=168),
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    return {"items": await nc.events_by_domain(_company_id(user),
                                                    hours=hours)}


@router.get("/by-company")
async def get_by_company(
    hours: int = Query(24, ge=1, le=168),
    user: Dict[str, Any] = Depends(require_roles("administrador")),
):
    return {"items": await nc.events_per_company(hours=hours)}


@router.get("/timeline-today")
async def get_timeline_today(
    limit: int = Query(80, ge=1, le=300),
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    return {"items": await nc.timeline_today(_company_id(user), limit=limit)}


@router.get("/what-happened-today")
async def get_what_happened(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    """Resposta autônoma da IA: "O que aconteceu na empresa hoje?" """
    return await nc.what_happened_today(_company_id(user))


@router.post("/run-sync")
async def run_sync(
    bootstrap: bool = Query(False),
    user: Dict[str, Any] = Depends(require_roles("administrador")),
):
    """Roda 1 ciclo do synchronizer manualmente (admin).
    bootstrap=True marca checkpoints=now() sem emitir histórico."""
    return await ns.run_synchronization(bootstrap=bootstrap)
