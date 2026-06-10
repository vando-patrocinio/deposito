"""SHIELD ROUTES — endpoints corporativos de blindagem.
  /api/shield/health/snapshot
  /api/shield/audit-chain/{key}/verify
  /api/shield/audit-chain/{key}/append
  /api/shield/event-signing/sign|verify
  /api/shield/vault/access-log
  /api/shield/vault/rotate
  /api/shield/backup/now|verify|list|dr-drill
  /api/shield/observability/aggregate
  /api/shield/tribunal/opp/{id}|/campaign/{id}|/recent
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from core import get_current_user, is_super_admin
from services import (ai_tribunal, audit_chain, backup_service,
                        event_signing, health_center, observability,
                        secrets_vault, shield_daily_audit)
from services.rate_limit import get_limit, limiter

router = APIRouter(prefix="/api/shield", tags=["shield"])


def _require_admin(user: dict) -> None:
    role = (user.get("role") or "").lower()
    if not (is_super_admin(user)
            or role in ("administrador", "admin", "gestor")):
        raise HTTPException(403, "restrito")


def _require_super(user: dict) -> None:
    if not is_super_admin(user):
        raise HTTPException(403, "super admin only")


# Health -------------------------------------------------------
@router.get("/health/snapshot")
@limiter.limit(get_limit("isabella_read"))
async def health_snap(request: Request,
                       user: dict = Depends(get_current_user)):
    _require_admin(user)
    return await health_center.snapshot()


# Daily Audit --------------------------------------------------
@router.post("/daily-audit/run-now")
@limiter.limit(get_limit("isabella_write"))
async def daily_audit_run(request: Request,
                            user: dict = Depends(get_current_user)):
    _require_super(user)
    return await shield_daily_audit.run_audit()


@router.get("/daily-audit/history")
@limiter.limit(get_limit("isabella_read"))
async def daily_audit_history(request: Request, limit: int = 30,
                                  user: dict = Depends(get_current_user)):
    _require_admin(user)
    from database import db as _db
    items = await _db.shield_audit_history.find({}, {"_id": 0}) \
        .sort("ts", -1).limit(min(limit, 100)) \
        .to_list(min(limit, 100))
    return {"count": len(items), "items": items}


@router.get("/daily-audit/latest")
@limiter.limit(get_limit("isabella_read"))
async def daily_audit_latest(request: Request,
                                 user: dict = Depends(get_current_user)):
    _require_admin(user)
    from database import db as _db
    doc = await _db.shield_audit_history.find_one(
        {}, {"_id": 0}, sort=[("ts", -1)])
    if not doc:
        raise HTTPException(404, "no audit yet")
    return doc


# Audit chain --------------------------------------------------
@router.post("/audit-chain/{chain_key}/append")
@limiter.limit(get_limit("isabella_write"))
async def chain_append(chain_key: str, request: Request,
                         payload: Dict[str, Any] = Body(...),
                         action: str = Body(..., embed=True),
                         user: dict = Depends(get_current_user)):
    _require_admin(user)
    actor = user.get("email") or user.get("id")
    return await audit_chain.append(
        chain_key=chain_key, actor=actor,
        action=action, payload=payload)


@router.get("/audit-chain/{chain_key}/verify")
@limiter.limit(get_limit("isabella_read"))
async def chain_verify(chain_key: str, request: Request,
                         user: dict = Depends(get_current_user)):
    _require_admin(user)
    return await audit_chain.verify_chain(chain_key)


@router.get("/audit-chain/keys")
@limiter.limit(get_limit("isabella_read"))
async def chain_list(request: Request,
                       user: dict = Depends(get_current_user)):
    _require_admin(user)
    return {"keys": await audit_chain.chain_keys()}


# Event signing ------------------------------------------------
@router.post("/event-signing/sign")
@limiter.limit(get_limit("isabella_write"))
async def signing_sign(request: Request,
                         event_type: str = Body(..., embed=True),
                         company_id: Optional[str] = Body(None, embed=True),
                         payload: Dict[str, Any] = Body(...),
                         user: dict = Depends(get_current_user)):
    _require_admin(user)
    return event_signing.sign(payload, event_type=event_type,
                                company_id=company_id)


@router.post("/event-signing/verify")
@limiter.limit(get_limit("isabella_write"))
async def signing_verify(request: Request,
                           envelope: Dict[str, Any] = Body(...),
                           user: dict = Depends(get_current_user)):
    _require_admin(user)
    return event_signing.verify_signature(envelope)


@router.post("/event-signing/consume")
@limiter.limit(get_limit("isabella_write"))
async def signing_consume(request: Request,
                            envelope: Dict[str, Any] = Body(...),
                            user: dict = Depends(get_current_user)):
    _require_admin(user)
    return await event_signing.consume(envelope)


# Vault audit --------------------------------------------------
@router.get("/vault/access-log")
@limiter.limit(get_limit("isabella_read"))
async def vault_log(request: Request,
                      name: Optional[str] = None,
                      limit: int = 100,
                      user: dict = Depends(get_current_user)):
    _require_admin(user)
    return await secrets_vault.access_log(name, limit=limit)


@router.post("/vault/rotate")
@limiter.limit(get_limit("isabella_write"))
async def vault_rotate(request: Request,
                         name: str = Body(..., embed=True),
                         new_value: str = Body(..., embed=True),
                         scope: str = Body("global", embed=True),
                         user: dict = Depends(get_current_user)):
    _require_super(user)
    actor = user.get("email") or user.get("id")
    return await secrets_vault.rotate_secret(
        name, new_value=new_value, scope=scope, rotated_by=actor)


# Backup / DR --------------------------------------------------
@router.post("/backup/now")
@limiter.limit(get_limit("isabella_write"))
async def backup_now(request: Request,
                       user: dict = Depends(get_current_user)):
    _require_super(user)
    return await backup_service.backup_now()


@router.get("/backup/verify")
@limiter.limit(get_limit("isabella_read"))
async def backup_verify(request: Request,
                          user: dict = Depends(get_current_user)):
    _require_admin(user)
    return await backup_service.verify_last()


@router.get("/backup/list")
@limiter.limit(get_limit("isabella_read"))
async def backup_list(request: Request, limit: int = 20,
                        user: dict = Depends(get_current_user)):
    _require_admin(user)
    return await backup_service.list_backups(limit=limit)


@router.post("/backup/dr-drill")
@limiter.limit(get_limit("isabella_write"))
async def dr_drill(request: Request,
                     user: dict = Depends(get_current_user)):
    _require_super(user)
    return await backup_service.disaster_recovery_drill()


# Observability ------------------------------------------------
@router.get("/observability/aggregate")
@limiter.limit(get_limit("isabella_read"))
async def obs_agg(request: Request, minutes: int = 60,
                    user: dict = Depends(get_current_user)):
    _require_admin(user)
    return await observability.aggregate_window(minutes=minutes)


# AI Tribunal --------------------------------------------------
@router.get("/tribunal/opp/{opp_id}")
@limiter.limit(get_limit("isabella_read"))
async def tribunal_opp(opp_id: str, request: Request,
                         user: dict = Depends(get_current_user)):
    _require_admin(user)
    r = await ai_tribunal.explain_opportunity(opp_id)
    if not r:
        raise HTTPException(404, "opp não encontrada")
    return r


@router.get("/tribunal/campaign/{campaign_id}")
@limiter.limit(get_limit("isabella_read"))
async def tribunal_camp(campaign_id: str, request: Request,
                          user: dict = Depends(get_current_user)):
    _require_admin(user)
    r = await ai_tribunal.explain_campaign(campaign_id)
    if not r:
        raise HTTPException(404, "campanha não encontrada")
    return r


@router.get("/tribunal/recent")
@limiter.limit(get_limit("isabella_read"))
async def tribunal_recent(request: Request,
                            cid: Optional[str] = None,
                            limit: int = 50,
                            user: dict = Depends(get_current_user)):
    _require_admin(user)
    from routes.field_ops import _company_of
    company = cid if (cid and is_super_admin(user)) else _company_of(user)
    return {"company_id": company,
            "items": await ai_tribunal.list_recent_decisions(
                company, limit=limit)}
