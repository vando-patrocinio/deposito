"""
ai_center_failure_risk.py — Endpoints REST do motor de risco (Sprint 2).

Prefix: /api/ai-center/failure-risk
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

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from database import db
from rbac import require_roles
from services import failure_risk

router = APIRouter(
    prefix="/api/ai-center/failure-risk",
    tags=["ai-center-failure-risk"],
)


def _co(user) -> str:
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid:
        raise HTTPException(400, "company_id ausente no token.")
    return cid


@router.get("/list")
async def list_risk(
    classification: Optional[str] = Query(
        None, pattern="^(BAIXO|MEDIO|ALTO|CRITICO)$"),
    min_score: int = Query(0, ge=0, le=100),
    limit: int = Query(100, ge=1, le=1000),
    user=Depends(require_roles("administrador", "auditor", "gestor")),
):
    """Lista clientes ordenados por failure_risk_score (desc)."""
    cid = _co(user)
    q: dict = {"company_id": cid}
    if classification:
        q["classification"] = classification
    if min_score > 0:
        q["score"] = {"$gte": min_score}
    cur = db.motor_ia_failure_risk_scores.find(q).sort(
        "score", -1).limit(limit)
    items = []
    async for d in cur:
        d.pop("_id", None)
        items.append(d)
    return {"items": items, "count": len(items)}


@router.get("/metrics")
async def get_metrics(
    window_days: int = Query(30, ge=1, le=365),
    user=Depends(require_roles("administrador", "auditor", "gestor")),
):
    """Métricas Fase H: preventive_ratio + prevented_churn_BRL +
    prevented_revenue_loss_BRL no período."""
    return await failure_risk.phase_h_metrics(
        _co(user), window_days=window_days)


@router.post("/drive")
async def drive_company(
    limit: int = Query(200, ge=1, le=5000),
    user=Depends(require_roles("administrador")),
):
    """Computa failure_risk para até `limit` assinantes ativos e dispara
    ciclo autônomo Decision V5 → Action → Outcome → Learning para todos
    com score > 80 (cria OS preventiva real)."""
    return await failure_risk.drive_from_failure_risk(
        _co(user), limit=limit)


@router.get("/{subscriber_id}")
async def get_one(
    subscriber_id: str,
    recompute: bool = Query(False),
    user=Depends(require_roles("administrador", "auditor", "gestor")),
):
    """Devolve (ou recomputa) o failure_risk_score de um assinante."""
    cid = _co(user)
    if recompute:
        return await failure_risk.compute_failure_risk(
            subscriber_id, company_id=cid, persist=True)
    doc = await db.motor_ia_failure_risk_scores.find_one(
        {"subscriber_id": subscriber_id, "company_id": cid})
    if not doc:
        return await failure_risk.compute_failure_risk(
            subscriber_id, company_id=cid, persist=True)
    doc.pop("_id", None)
    return doc
