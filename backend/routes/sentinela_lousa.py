"""Sentinela Lousa AI — REST endpoints."""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "operacoes",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db
from services.sentinela_lousa import (
    INTERVAL_SECONDS, STUCK_HOURS, FIELD_STUCK_HOURS, SLA_WARNING_MIN,
    OVERLOAD_TICKETS, RECURRING_HOURS,
    count_alerts_24h, list_active_alerts, run_sentinel,
)

router = APIRouter(prefix="/api/sentinela-lousa", tags=["sentinela-lousa"])
logger = logging.getLogger("sentinela_lousa.routes")


@router.get("/summary")
async def summary(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    counts = await count_alerts_24h(cid)
    return {
        **counts,
        "config": {
            "interval_seconds": INTERVAL_SECONDS,
            "stuck_hours": STUCK_HOURS,
            "field_stuck_hours": FIELD_STUCK_HOURS,
            "sla_warning_min": SLA_WARNING_MIN,
            "overload_tickets": OVERLOAD_TICKETS,
            "recurring_hours": RECURRING_HOURS,
        },
    }


@router.get("/alerts")
async def alerts(severity: Optional[str] = Query(None, regex="^(low|medium|high)$"),
                   kind: Optional[str] = Query(None),
                   limit: int = Query(100, ge=1, le=500),
                   user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    items = await list_active_alerts(cid, severity=severity, limit=limit)
    if kind:
        items = [a for a in items if a.get("kind") == kind]
    return {"items": items, "count": len(items)}


@router.post("/scan")
async def force_scan(user: dict = Depends(require_role("gestor"))):
    """Força uma varredura imediata (botão na UI)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await run_sentinel(cid)


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str,
                                user: dict = Depends(require_role("gestor"))):
    """Marca alerta como reconhecido (gestor viu e está cuidando)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    res = await db.lousa_alerts.update_one(
        {"id": alert_id, "company_id": cid, "status": "active"},
        {"$set": {
            "status": "acknowledged",
            "acknowledged_at": now_iso(),
            "acknowledged_by": user.get("email") or user.get("id"),
        }},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Alerta não encontrado ou já processado.")
    return {"ok": True}


@router.post("/alerts/{alert_id}/dismiss")
async def dismiss_alert(alert_id: str,
                          user: dict = Depends(require_role("gestor"))):
    """Descarta alerta (falso positivo). Volta a aparecer se condição persistir."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    res = await db.lousa_alerts.update_one(
        {"id": alert_id, "company_id": cid, "status": "active"},
        {"$set": {
            "status": "dismissed",
            "dismissed_at": now_iso(),
            "dismissed_by": user.get("email") or user.get("id"),
        }},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Alerta não encontrado ou já processado.")
    return {"ok": True}
