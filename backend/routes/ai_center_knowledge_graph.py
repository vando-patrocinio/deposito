"""ai_center_knowledge_graph.py — FASE 6.5 endpoints REST."""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from rbac import require_roles
from services import knowledge_graph as kg

router = APIRouter(prefix="/api/ai-center/knowledge-graph",
                    tags=["ai-center-knowledge-graph"])


def _co(user):
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid: raise HTTPException(400, "company_id ausente")
    return cid


@router.get("/explain")
async def explain(
    question: str = Query(..., regex="^(client|cto|region|campaign|tech)$"),
    entity_id: str = Query(...),
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor"))):
    return await kg.explain(question, company_id=_co(user),
                                  entity_id=entity_id)


@router.get("/what-causes-problems")
async def what_causes(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor"))):
    return await kg.what_causes_problems(_co(user))
