"""
ai_center_revenue.py — Endpoints REST do RevenueOps IA (Fase 1 Constituição)

Pergunta-chave que esses endpoints respondem em <2s:
  "Quanto dinheiro a IA gerou este mês?"
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, HTTPException

from rbac import require_roles
from services import revenue_attribution as rev


router = APIRouter(prefix="/api/ai-center/revenue",
                    tags=["ai-center-revenue"])


def _resolve_period(period: str) -> tuple[datetime, datetime]:
    """MTD | YTD | 7d | 30d | 90d | all"""
    now = datetime.now(timezone.utc)
    if period == "MTD":
        since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif period == "YTD":
        since = now.replace(month=1, day=1, hour=0, minute=0, second=0,
                              microsecond=0)
    elif period.endswith("d"):
        try:
            days = int(period[:-1])
        except ValueError:
            raise HTTPException(400, "period inválido")
        since = now - timedelta(days=days)
    elif period == "all":
        since = datetime(2020, 1, 1, tzinfo=timezone.utc)
    else:
        raise HTTPException(400, "period inválido")
    return since, now


def _company_id(user: Dict[str, Any]) -> str:
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid:
        raise HTTPException(400, "company_id ausente no usuário")
    return cid


@router.get("/summary")
async def get_summary(
    period: str = Query("MTD"),
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    """KPIs principais: recuperado, gerado, churn evitado, custo poupado, ROI."""
    company_id = _company_id(user)
    since, until = _resolve_period(period)
    s = await rev.summary(company_id, since=since, until=until)
    return {
        "period": period,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "kpis": {
            "recovered_BRL": s["recovered"]["total_BRL"],
            "generated_BRL": s["generated"]["total_BRL"],
            "churn_prevented_BRL": s["churn_prevented"]["total_BRL"],
            "cost_saved_BRL": s["cost_saved"]["total_BRL"],
            "total_BRL": s["_total_BRL"],
            "actions_count": s["_total_count"],
        },
        "detail": s,
    }


@router.get("/by-template")
async def get_by_template(
    period: str = Query("MTD"),
    limit: int = Query(20, ge=1, le=100),
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    """Conversão por template (qual mensagem converte mais)."""
    company_id = _company_id(user)
    since, until = _resolve_period(period)
    items = await rev.by_template(company_id, since=since, until=until,
                                       limit=limit)
    return {"period": period, "items": items}


@router.get("/by-channel")
async def get_by_channel(
    period: str = Query("MTD"),
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    company_id = _company_id(user)
    since, until = _resolve_period(period)
    items = await rev.by_channel(company_id, since=since, until=until)
    return {"period": period, "items": items}


@router.get("/by-action-type")
async def get_by_action_type(
    period: str = Query("MTD"),
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    company_id = _company_id(user)
    since, until = _resolve_period(period)
    items = await rev.by_action_type(company_id, since=since, until=until)
    return {"period": period, "items": items}


@router.get("/timeline")
async def get_timeline(
    period: str = Query("30d"),
    granularity: str = Query("day"),
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    company_id = _company_id(user)
    since, until = _resolve_period(period)
    items = await rev.timeline(company_id, since=since, until=until,
                                    granularity=granularity)
    return {"period": period, "granularity": granularity, "items": items}


@router.get("/top-actions")
async def get_top_actions(
    period: str = Query("MTD"),
    limit: int = Query(10, ge=1, le=50),
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    company_id = _company_id(user)
    since, until = _resolve_period(period)
    items = await rev.top_actions(company_id, since=since, until=until,
                                       limit=limit)
    return {"period": period, "items": items}
