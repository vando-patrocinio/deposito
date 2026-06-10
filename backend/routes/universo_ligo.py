"""UNIVERSO LIGO + ISABELLA EXPERIENCE — endpoints HTTP.

Tudo em `/api/universo-ligo/*` e `/api/experience/*`.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from core import get_current_user
from services import isabella_experience as exp
from services import universo_ligo as ul
from services.rate_limit import get_limit, limiter
from routes.field_ops import _company_of, _is_privileged

log = logging.getLogger("ponto.universo_ligo_routes")
router = APIRouter(tags=["universo_ligo"])


def _company(user: dict, cid: Optional[str]) -> str:
    if cid and _is_privileged(user):
        return cid
    return _company_of(user)


def _actor(user: dict) -> str:
    return user.get("email") or user.get("id") or "unknown"


def _role(user: dict) -> str:
    return (user.get("role") or "").lower()


# ---------------------------------------------------------------------------
# Universo Ligo — score, identify, painel
# ---------------------------------------------------------------------------
@router.get("/api/universo-ligo/identify")
@limiter.limit(get_limit("isabella_read"))
async def identify(request: Request,
                     phone: Optional[str] = None,
                     subscriber_id: Optional[str] = None,
                     document: Optional[str] = None,
                     external_code: Optional[str] = None,
                     cid: Optional[str] = None,
                     user: dict = Depends(get_current_user)):
    company = _company(user, cid)
    r = await ul.identify(company_id=company, phone=phone,
                            subscriber_id=subscriber_id,
                            document=document,
                            external_code=external_code)
    if not r:
        raise HTTPException(404, "assinante não encontrado")
    return r


@router.get("/api/universo-ligo/score/{subscriber_id}")
@limiter.limit(get_limit("isabella_read"))
async def score(subscriber_id: str, request: Request,
                  force: bool = False,
                  cid: Optional[str] = None,
                  user: dict = Depends(get_current_user)):
    company = _company(user, cid)
    return await ul.get_or_compute(company, subscriber_id, force=force)


@router.get("/api/universo-ligo/levels")
@limiter.limit(get_limit("isabella_read"))
async def levels(request: Request):
    return {"levels": ul.LEVELS}


@router.get("/api/universo-ligo/panel")
@limiter.limit(get_limit("isabella_read"))
async def panel(request: Request, cid: Optional[str] = None,
                  user: dict = Depends(get_current_user)):
    company = _company(user, cid)
    return await ul.panel_summary(company)


@router.post("/api/universo-ligo/refresh-all")
@limiter.limit(get_limit("isabella_write"))
async def refresh_all(request: Request, cid: Optional[str] = None,
                        user: dict = Depends(get_current_user)):
    if not _is_privileged(user):
        raise HTTPException(403, "restrito")
    company = _company(user, cid)
    return await ul.refresh_all(company)


@router.get("/api/universo-ligo/history/{subscriber_id}")
@limiter.limit(get_limit("isabella_read"))
async def history(subscriber_id: str, request: Request,
                    cid: Optional[str] = None,
                    user: dict = Depends(get_current_user)):
    from database import db
    company = _company(user, cid)
    return await db.universo_ligo_history.find(
        {"company_id": company, "subscriber_id": subscriber_id},
        {"_id": 0}).sort("changed_at", -1).limit(50).to_list(50)


# ---------------------------------------------------------------------------
# Experience Commander — campanhas
# ---------------------------------------------------------------------------
@router.post("/api/experience/scan")
@limiter.limit(get_limit("isabella_write"))
async def experience_scan(request: Request, cid: Optional[str] = None,
                            user: dict = Depends(get_current_user)):
    if not _is_privileged(user):
        raise HTTPException(403, "restrito")
    company = _company(user, cid)
    return await exp.scan_company(company)


@router.get("/api/experience/campaigns")
@limiter.limit(get_limit("isabella_read"))
async def campaigns_list(request: Request,
                           status: Optional[str] = None,
                           limit: int = 100,
                           cid: Optional[str] = None,
                           user: dict = Depends(get_current_user)):
    company = _company(user, cid)
    return {"company_id": company,
            "items": await exp.list_campaigns(company, status=status,
                                                  limit=limit)}


@router.get("/api/experience/campaigns/{campaign_id}")
@limiter.limit(get_limit("isabella_read"))
async def campaign_get(campaign_id: str, request: Request,
                         cid: Optional[str] = None,
                         user: dict = Depends(get_current_user)):
    from database import db
    company = _company(user, cid)
    doc = await db.experience_campaigns.find_one(
        {"id": campaign_id, "company_id": company}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "campanha não encontrada")
    return doc


@router.post("/api/experience/campaigns/{campaign_id}/approve")
@limiter.limit(get_limit("isabella_write"))
async def campaign_approve(campaign_id: str, request: Request,
                              notes: Optional[str] = Body(None, embed=True),
                              cid: Optional[str] = None,
                              user: dict = Depends(get_current_user)):
    if not _is_privileged(user):
        raise HTTPException(403, "restrito")
    company = _company(user, cid)
    try:
        return await exp.approve_campaign(
            campaign_id=campaign_id, company_id=company,
            actor=_actor(user), actor_role=_role(user), notes=notes)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/experience/campaigns/{campaign_id}/cancel")
@limiter.limit(get_limit("isabella_write"))
async def campaign_cancel(campaign_id: str, request: Request,
                             reason: Optional[str] = Body(None, embed=True),
                             cid: Optional[str] = None,
                             user: dict = Depends(get_current_user)):
    if not _is_privileged(user):
        raise HTTPException(403, "restrito")
    company = _company(user, cid)
    try:
        return await exp.cancel_campaign(
            campaign_id=campaign_id, company_id=company,
            actor=_actor(user), reason=reason)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/api/experience/campaigns/{campaign_id}/execute")
@limiter.limit(get_limit("isabella_write"))
async def campaign_execute(campaign_id: str, request: Request,
                              cid: Optional[str] = None,
                              user: dict = Depends(get_current_user)):
    if not _is_privileged(user):
        raise HTTPException(403, "restrito")
    company = _company(user, cid)
    try:
        return await exp.execute_campaign(
            campaign_id=campaign_id, company_id=company,
            actor=_actor(user))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/experience/campaigns/{campaign_id}/council-review")
@limiter.limit(get_limit("isabella_write"))
async def campaign_council(campaign_id: str, request: Request,
                              cid: Optional[str] = None,
                              user: dict = Depends(get_current_user)):
    if not _is_privileged(user):
        raise HTTPException(403, "restrito")
    company = _company(user, cid)
    try:
        return await exp.council_review(campaign_id, company)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/api/experience/audit/{campaign_id}")
@limiter.limit(get_limit("isabella_read"))
async def campaign_audit(campaign_id: str, request: Request,
                            cid: Optional[str] = None,
                            user: dict = Depends(get_current_user)):
    from database import db
    return await db.experience_campaigns_audit.find(
        {"campaign_id": campaign_id}, {"_id": 0}
    ).sort("at", -1).limit(200).to_list(200)


@router.get("/api/experience/templates")
@limiter.limit(get_limit("isabella_read"))
async def list_templates(request: Request,
                            user: dict = Depends(get_current_user)):
    return {"templates": [{"id": k, "preview": v[:200]}
                            for k, v in exp.TEMPLATES.items()]}
