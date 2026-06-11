"""ai_center_v62.py — V6.2 FASES 3 (Receita Real) + 5 (Pres NL) + 6 (ROI)."""
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
from services import real_revenue
from services import presidente_ia_nl

router = APIRouter(prefix="/api/ai-center/v62",
                    tags=["ai-center-v62"])


def _co(user):
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid: raise HTTPException(400, "company_id ausente")
    return cid


@router.get("/revenue-real")
async def get_revenue_real(days: int = 30,
                            user=Depends(require_roles(
                                "administrador", "auditor", "gestor"))):
    return await real_revenue.revenue_breakdown(_co(user), days)


@router.get("/roi-priorities")
async def get_roi_priorities(user=Depends(require_roles(
    "administrador", "auditor", "gestor"))):
    items = await real_revenue.roi_priorities(_co(user))
    total = sum(i["roi_BRL"] for i in items)
    return {"items": items, "count": len(items),
             "total_BRL_at_stake": round(total, 2)}


@router.get("/presidente-natural")
async def get_president_natural(user=Depends(require_roles(
    "administrador", "auditor", "gestor"))):
    return await presidente_ia_nl.daily_natural(_co(user))
