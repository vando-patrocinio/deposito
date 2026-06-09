"""ai_center_predictive.py — V6.0 Bloco 8"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException

from rbac import require_roles
from services import smartolt_predictive as pred

router = APIRouter(prefix="/api/ai-center/predictive",
                    tags=["ai-center-predictive"])


def _co(user):
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid: raise HTTPException(400, "company_id ausente")
    return cid


@router.get("/summary")
async def get_summary(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return await pred.predictive_summary(_co(user))


@router.get("/ctos-at-risk")
async def get_ctos(limit: int = 50,
                    user=Depends(require_roles(
                        "administrador", "auditor", "gestor"))):
    return {"items": await pred.predict_cto_failures(_co(user), limit)}


@router.get("/recurrent-onus")
async def get_recurrent(limit: int = 30,
                          user=Depends(require_roles(
                              "administrador", "auditor", "gestor"))):
    return {"items": await pred.predict_recurrent_onu_failures(
        _co(user), limit)}


@router.get("/signal-churn")
async def get_signal_churn(limit: int = 30,
                             user=Depends(require_roles(
                                 "administrador", "auditor", "gestor"))):
    return {"items": await pred.predict_signal_churn(_co(user), limit)}


@router.post("/auto-tickets")
async def post_auto_tickets(max_tickets: int = 10,
                              user=Depends(require_roles(
                                  "administrador", "auditor"))):
    return await pred.auto_create_preventive_tickets(
        _co(user), max_tickets=max_tickets)
