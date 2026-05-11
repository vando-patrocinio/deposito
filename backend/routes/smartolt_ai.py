"""SmartOLT AI — endpoints REST."""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

from core import DEMO_COMPANY_ID, require_role
from services.smartolt_ai import (
    detect_outages, list_active_outages, list_recent_resolved,
)

router = APIRouter(prefix="/api/smartolt-ai", tags=["smartolt-ai"])


@router.get("/outages/active")
async def get_active(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    items = await list_active_outages(cid)
    return {"items": items, "count": len(items)}


@router.get("/outages/recent")
async def get_recent(hours: int = Query(24, ge=1, le=168),
                       user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    items = await list_recent_resolved(cid, hours=hours)
    return {"items": items, "count": len(items), "hours": hours}


@router.post("/outages/detect")
async def force_detect(user: dict = Depends(require_role("gestor"))):
    """Força uma rodada de detecção manualmente (botão Atualizar no UI)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    result = await detect_outages(cid)
    return result


@router.get("/summary")
async def summary(user: dict = Depends(require_role("gestor"))):
    """Resumo executivo para card no Central IA."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    active = await list_active_outages(cid)
    recent = await list_recent_resolved(cid, hours=24)
    total_affected = sum(len(o.get("affected_phones") or []) for o in active)
    return {
        "active_count": len(active),
        "resolved_24h": len(recent),
        "total_affected_clients": total_affected,
        "active": active[:5],
    }
