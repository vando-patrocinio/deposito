"""
ai_center_alvaro_v5.py — Endpoints REST do Álvaro IA 2.0 (Constituição V5.0)

Sprint 1 — Fundação Cognitiva:
  - POST /api/ai-center/alvaro-v5/triage
  - GET  /api/ai-center/alvaro-v5/consult-network/{subscriber_id}
  - GET  /api/ai-center/alvaro-v5/recurrence/{subscriber_id}
  - POST /api/ai-center/alvaro-v5/recurrence/batch
  - GET  /api/ai-center/alvaro-v5/recurrence/list
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

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database import db
from rbac import require_roles
from services import alvaro_v5

router = APIRouter(
    prefix="/api/ai-center/alvaro-v5",
    tags=["ai-center-alvaro-v5"],
)


def _co(user) -> str:
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid:
        raise HTTPException(400, "company_id ausente no token.")
    return cid


class TriageIn(BaseModel):
    subscriber_id: str = Field(..., min_length=1)
    complaint: str = Field(..., min_length=1, max_length=2000)


@router.post("/triage")
async def post_triage(
    body: TriageIn,
    persist: bool = Query(False, description="Se True, grava a decisão "
                                              "em motor_ia_decisions."),
    user=Depends(require_roles("administrador", "auditor", "gestor")),
):
    """Triagem Álvaro 2.0 — pré-consulta de rede obrigatória.

    Sempre devolve uma DecisionV5 (cause/effect/impact/recommended_action/
    confidence/evidence). Quando a ONU está em LOS/Power Fail/Offline o
    Álvaro PROÍBE sugerir reboot.
    """
    company_id = _co(user)
    out = await alvaro_v5.triage(
        body.subscriber_id, body.complaint, company_id=company_id)
    if persist and out.get("decision"):
        await alvaro_v5.persist_v5_decision(out["decision"])
    return out


@router.get("/consult-network/{subscriber_id}")
async def get_consult_network(
    subscriber_id: str,
    user=Depends(require_roles("administrador", "auditor", "gestor")),
):
    """Pré-consulta de rede (Fase A). Não cria decisão."""
    company_id = _co(user)
    return await alvaro_v5.consult_network(
        subscriber_id, company_id=company_id)


@router.get("/recurrence/list")
async def get_recurrence_list(
    classification: Optional[str] = Query(
        None, regex="^(BAIXO|MEDIO|ALTO|CRITICO)$"),
    min_score: int = Query(0, ge=0, le=100),
    limit: int = Query(100, ge=1, le=1000),
    user=Depends(require_roles("administrador", "auditor", "gestor")),
):
    """Lista assinantes ordenados por recurrence_score (desc)."""
    company_id = _co(user)
    q: dict = {"company_id": company_id}
    if classification:
        q["classification"] = classification
    if min_score > 0:
        q["score"] = {"$gte": min_score}
    cur = db.motor_ia_recurrence_scores.find(q).sort(
        "score", -1).limit(limit)
    items = []
    async for d in cur:
        d.pop("_id", None)
        items.append(d)
    return {
        "items": items,
        "count": len(items),
        "filter": {"classification": classification,
                    "min_score": min_score},
    }


@router.get("/recurrence/{subscriber_id}")
async def get_recurrence(
    subscriber_id: str,
    recompute: bool = Query(False, description="Recalcula on the fly."),
    user=Depends(require_roles("administrador", "auditor", "gestor")),
):
    """Devolve recurrence_score do assinante.

    Se `recompute=true` ou nunca foi calculado, computa agora.
    """
    company_id = _co(user)
    if recompute:
        return await alvaro_v5.compute_recurrence_score(
            subscriber_id, company_id=company_id, persist=True)
    doc = await db.motor_ia_recurrence_scores.find_one(
        {"subscriber_id": subscriber_id, "company_id": company_id})
    if not doc:
        return await alvaro_v5.compute_recurrence_score(
            subscriber_id, company_id=company_id, persist=True)
    doc.pop("_id", None)
    return doc


@router.post("/recurrence/batch")
async def post_recurrence_batch(
    limit: int = Query(500, ge=1, le=5000),
    user=Depends(require_roles("administrador")),
):
    """Recalcula recurrence_score para até `limit` assinantes ativos."""
    company_id = _co(user)
    return await alvaro_v5.recompute_recurrence_batch(
        company_id, limit=limit)
