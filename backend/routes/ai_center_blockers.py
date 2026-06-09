"""ai_center_blockers.py — V6.0 Bloco 2"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException

from rbac import require_roles
from services import blockers_audit
from services import self_healing

router = APIRouter(prefix="/api/ai-center/blockers",
                    tags=["ai-center-blockers"])


def _co(user):
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid: raise HTTPException(400, "company_id ausente")
    return cid


@router.get("/audit")
async def get_full_audit(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    audit = await blockers_audit.full_audit(_co(user))
    # V6.2: marca quais bloqueadores têm healer disponível
    for b in audit["blockers"]:
        b["healing_available"] = b.get("blocker") in self_healing.HEALERS
    return audit


@router.post("/heal")
async def post_heal(blocker_key: str,
                     user=Depends(require_roles(
                         "administrador", "auditor"))):
    """V6.2 FASE 1 — APLICAR CORREÇÃO."""
    try:
        return await self_healing.apply_correction(_co(user), blocker_key)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/healing-score")
async def get_healing_score(days: int = 7,
                              user=Depends(require_roles(
                                  "administrador", "auditor", "gestor"))):
    """V6.2 FASE 2 — Self Healing Score."""
    return await self_healing.healing_score(_co(user), days)


@router.get("/healing-history")
async def get_history(limit: int = 50,
                        user=Depends(require_roles(
                            "administrador", "auditor", "gestor"))):
    from database import db
    rows = await db.motor_ia_self_healing.find(
        {"company_id": _co(user)}
    ).sort("started_at", -1).limit(limit).to_list(limit)
    for r in rows: r.pop("_id", None)
    return {"items": rows}
