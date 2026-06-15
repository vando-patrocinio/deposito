"""routes/isabella_negotiation.py — Endpoints de regras de negociação.

GET  /api/isabella/negotiation-rules         — leitura (gestor+)
PUT  /api/isabella/negotiation-rules         — update (admin+ por segurança)
POST /api/isabella/negotiation-rules/test    — simular can_offer sem persistir lado-efeito
GET  /api/isabella/negotiation-attempts      — audit log paginado
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, require_role
from database import db
from services import isabella_negotiation as negotiation

router = APIRouter(prefix="/api/isabella", tags=["isabella_negotiation"])


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


class RulesUpdateIn(BaseModel):
    rules: Dict[str, Dict[str, Any]]


@router.get("/negotiation-rules")
async def get_rules(user: dict = Depends(require_role("gestor"))):
    doc = await negotiation.get_rules(_cid(user))
    return doc


@router.put("/negotiation-rules")
async def update_rules(p: RulesUpdateIn,
                       user: dict = Depends(require_role("administrador"))):
    if not p.rules:
        raise HTTPException(400, "rules obrigatório")
    doc = await negotiation.update_rules(
        _cid(user), p.rules, actor=user.get("email") or "?")
    return doc


class CanOfferIn(BaseModel):
    action: str
    subscriber_id: Optional[str] = None
    params: Optional[Dict[str, Any]] = None


@router.post("/negotiation-rules/test")
async def test_can_offer(p: CanOfferIn,
                          user: dict = Depends(require_role("gestor"))):
    """Simula can_offer SEM gravar attempt (modo dry-run para painel/QA).

    Persiste em log à parte (`negotiation_simulations`) — utilidade pro
    gestor entender o que IA decidiria sem poluir audit real.
    """
    if p.action not in negotiation.CANONICAL_ACTIONS:
        raise HTTPException(400, f"action inválida. Use: "
                                  f"{sorted(negotiation.CANONICAL_ACTIONS)}")
    rules_doc = await negotiation.get_rules(_cid(user))
    rule = (rules_doc.get("rules") or {}).get(p.action) or {}
    # Reproduz lógica de can_offer sem persistir attempt (chamada simples)
    result = await negotiation.can_offer(
        p.action, _cid(user), p.subscriber_id, p.params or {},
        actor=f"test:{user.get('email') or '?'}")
    return {**result, "rule_full": rule}


@router.get("/negotiation-attempts")
async def list_attempts(action: Optional[str] = None,
                         subscriber_id: Optional[str] = None,
                         allowed: Optional[bool] = None,
                         limit: int = 100,
                         user: dict = Depends(require_role("gestor"))):
    q: Dict[str, Any] = {"company_id": _cid(user)}
    if action:
        q["action"] = action
    if subscriber_id:
        q["subscriber_id"] = subscriber_id
    if allowed is not None:
        q["result.allowed"] = allowed
    rows = await db.negotiation_attempts.find(q, {"_id": 0}).sort(
        "created_at", -1).to_list(min(limit, 500))
    return {"attempts": rows, "count": len(rows)}
