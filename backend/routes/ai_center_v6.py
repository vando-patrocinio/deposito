"""ai_center_v6.py — Endpoints REST V6.0 (consolidação, sem novas telas)."""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from core import require_role
from services import company_v6 as v6

router = APIRouter(prefix="/api/ai-center/v6", tags=["company-v6"])


def _co(user):
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid:
        raise HTTPException(400, "company_id ausente.")
    return cid


# P1 — Smart Field Ops
@router.post("/smart-field/sync")
async def sync_sfo(window_days: int = Query(30, ge=1, le=365),
                   user=Depends(require_role("administrador"))):
    return await v6.sync_smart_field_ops(_co(user),
                                          window_days=window_days)


@router.get("/smart-field/kpis")
async def get_sfo_kpis(window_days: int = Query(30, ge=1, le=365),
                       user=Depends(require_role("administrador",
                                                  "auditor", "gestor"))):
    return await v6.smart_field_ops_kpis(_co(user),
                                          window_days=window_days)


# P3 — Autonomous Company Score
@router.get("/company-score")
async def get_score(window_days: int = Query(30, ge=1, le=365),
                    user=Depends(require_role("administrador",
                                              "auditor", "gestor"))):
    return await v6.autonomous_company_score(_co(user),
                                              window_days=window_days)


# P4 — Receita Real
class MarkReceivedIn(BaseModel):
    outcome_id: str = Field(..., min_length=1)
    actual_BRL: float = Field(..., ge=0)
    source: str = Field(default="manual_admin")
    payment_ref: str | None = None


@router.post("/revenue/mark-received")
async def mark_received(body: MarkReceivedIn,
                        user=Depends(require_role("administrador",
                                                   "financeiro"))):
    return await v6.mark_revenue_received(
        _co(user), body.outcome_id, body.actual_BRL,
        source=body.source, payment_ref=body.payment_ref)


@router.post("/revenue/reconcile")
async def reconcile(window_days: int = Query(30, ge=1, le=365),
                    user=Depends(require_role("administrador",
                                              "financeiro"))):
    return await v6.reconcile_with_cash(_co(user),
                                         window_days=window_days)


# P2 — Digital Twin Summary
@router.get("/digital-twin")
async def digital_twin(window_days: int = Query(30, ge=1, le=365),
                       user=Depends(require_role("administrador",
                                                 "auditor", "gestor"))):
    return await v6.digital_twin_summary(_co(user),
                                          window_days=window_days)
