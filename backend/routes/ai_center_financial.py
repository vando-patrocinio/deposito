"""ai_center_financial.py — FASE 11 endpoints (V5.0)."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException

from rbac import require_roles
from services import financial_foundation as fin

router = APIRouter(prefix="/api/ai-center/financial",
                    tags=["ai-center-financial"])


def _co(user):
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid: raise HTTPException(400, "company_id ausente")
    return cid


@router.get("/summary")
async def get_summary(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return await fin.summary(_co(user))


@router.get("/mrr")
async def get_mrr(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return await fin.mrr(_co(user))


@router.get("/arr")
async def get_arr(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return await fin.arr(_co(user))


@router.get("/ltv")
async def get_ltv(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return await fin.ltv(_co(user))


@router.get("/at-risk")
async def get_risk(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return await fin.revenue_at_risk(_co(user))


@router.get("/churn-cost")
async def get_churn(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return await fin.churn_cost(_co(user))


@router.get("/overdue")
async def get_overdue(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return await fin.overdue_summary(_co(user))
