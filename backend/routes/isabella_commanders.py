"""ISABELLA COMMANDERS — rotas unificadas dos 5 Commanders + pipeline de
oportunidades + Conselho Executivo + Mass-notify Incident.

Filosofia: tudo em `/api/isabella/*`. Cada Commander tem um endpoint de
scan (admin/gestor) + a listagem é única em `/opportunities`.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from core import get_current_user, is_super_admin
from services.event_bus import EventType, emit_event
from services.isabella_opportunities import (
    expire_old, get_opportunity, kpis, list_opportunities, update_status)
from services import (isabella_churn, isabella_dunning, isabella_revenue,
                       isabella_twin, isabella_expansion, isabella_conselho)
from services import isabella_incident
from services.rate_limit import get_limit, limiter
from routes.field_ops import _company_of, _is_privileged

log = logging.getLogger("ponto.isabella_commanders")
router = APIRouter(prefix="/api/isabella", tags=["isabella_commanders"])


def _require_priv(user: dict) -> None:
    if not _is_privileged(user):
        raise HTTPException(403, "Acesso restrito a gestores/administradores.")


def _company_or_param(user: dict, cid: Optional[str]) -> str:
    if cid and (is_super_admin(user) or _is_privileged(user)):
        return cid
    return _company_of(user)


# ---------------------------------------------------------------------------
# Opportunities (lista, KPIs, approve/dismiss)
# ---------------------------------------------------------------------------
@router.get("/opportunities")
@limiter.limit(get_limit("isabella_read"))
async def list_opps(request: Request,
                     kind: Optional[str] = None,
                     subkind: Optional[str] = None,
                     status: str = "pending",
                     limit: int = 100,
                     cid: Optional[str] = None,
                     user: dict = Depends(get_current_user)):
    company = _company_or_param(user, cid)
    return {"company_id": company,
            "items": await list_opportunities(company_id=company,
                                                  kind=kind, subkind=subkind,
                                                  status=status,
                                                  limit=min(limit, 500))}


@router.get("/opportunities/kpis")
@limiter.limit(get_limit("isabella_read"))
async def opps_kpis(request: Request, cid: Optional[str] = None,
                     user: dict = Depends(get_current_user)):
    company = _company_or_param(user, cid)
    return {"company_id": company, "kpis": await kpis(company)}


@router.get("/opportunities/{opp_id}")
@limiter.limit(get_limit("isabella_read"))
async def get_opp(opp_id: str, request: Request,
                   cid: Optional[str] = None,
                   user: dict = Depends(get_current_user)):
    company = _company_or_param(user, cid)
    opp = await get_opportunity(opp_id, company)
    if not opp:
        raise HTTPException(404, "oportunidade não encontrada")
    return opp


@router.post("/opportunities/{opp_id}/approve")
@limiter.limit(get_limit("isabella_write"))
async def approve_opp(opp_id: str, request: Request,
                       cid: Optional[str] = None,
                       notes: Optional[str] = Body(None, embed=True),
                       user: dict = Depends(get_current_user)):
    """1-clique: aprova oportunidade. Não EXECUTA aqui (a execução é feita
    pelo workflow de campo / disparo / smartolt no fluxo correspondente)."""
    _require_priv(user)
    company = _company_or_param(user, cid)
    opp = await get_opportunity(opp_id, company)
    if not opp:
        raise HTTPException(404, "oportunidade não encontrada")
    if opp.get("status") not in ("pending",):
        raise HTTPException(409, f"status atual: {opp.get('status')}")
    actor = user.get("email") or user.get("id")
    updated = await update_status(opp_id, company, status="approved",
                                    actor=actor)
    await emit_event(EventType.OPPORTUNITY_APPROVED,
                      company_id=company, source="isabella_commanders",
                      severity="media",
                      payload={"opp_id": opp_id, "kind": opp.get("kind"),
                                "actor": actor})
    return updated


@router.post("/opportunities/{opp_id}/dismiss")
@limiter.limit(get_limit("isabella_write"))
async def dismiss_opp(opp_id: str, request: Request,
                       cid: Optional[str] = None,
                       reason: Optional[str] = Body(None, embed=True),
                       user: dict = Depends(get_current_user)):
    _require_priv(user)
    company = _company_or_param(user, cid)
    actor = user.get("email") or user.get("id")
    updated = await update_status(opp_id, company, status="dismissed",
                                    actor=actor, notes=reason)
    await emit_event(EventType.OPPORTUNITY_DISMISSED,
                      company_id=company, source="isabella_commanders",
                      severity="baixa",
                      payload={"opp_id": opp_id, "actor": actor,
                                "reason": reason})
    return updated


@router.post("/opportunities/{opp_id}/executed")
@limiter.limit(get_limit("isabella_write"))
async def mark_executed(opp_id: str, request: Request,
                          cid: Optional[str] = None,
                          result: Optional[Dict[str, Any]] = Body(None, embed=True),
                          user: dict = Depends(get_current_user)):
    """Marca como executada (ex: disparo WA realizado, OS criada)."""
    _require_priv(user)
    company = _company_or_param(user, cid)
    actor = user.get("email") or user.get("id")
    updated = await update_status(opp_id, company, status="executed",
                                    actor=actor, result=result)
    await emit_event(EventType.OPPORTUNITY_EXECUTED,
                      company_id=company, source="isabella_commanders",
                      severity="media",
                      payload={"opp_id": opp_id, "actor": actor,
                                "result": result or {}})
    return updated


@router.post("/opportunities/expire")
@limiter.limit(get_limit("isabella_write"))
async def expire_endpoint(request: Request,
                            user: dict = Depends(get_current_user)):
    _require_priv(user)
    n = await expire_old()
    return {"expired": n}


# ---------------------------------------------------------------------------
# Commanders — scans
# ---------------------------------------------------------------------------
@router.post("/churn/scan")
@limiter.limit(get_limit("isabella_write"))
async def churn_scan(request: Request, cid: Optional[str] = None,
                      user: dict = Depends(get_current_user)):
    _require_priv(user)
    company = _company_or_param(user, cid)
    return await isabella_churn.scan_company(company)


@router.post("/dunning/scan")
@limiter.limit(get_limit("isabella_write"))
async def dunning_scan(request: Request, cid: Optional[str] = None,
                        user: dict = Depends(get_current_user)):
    _require_priv(user)
    company = _company_or_param(user, cid)
    return await isabella_dunning.scan_company(company)


@router.post("/revenue/scan")
@limiter.limit(get_limit("isabella_write"))
async def revenue_scan(request: Request, cid: Optional[str] = None,
                        user: dict = Depends(get_current_user)):
    _require_priv(user)
    company = _company_or_param(user, cid)
    return await isabella_revenue.scan_company(company)


@router.post("/twin/scan")
@limiter.limit(get_limit("isabella_write"))
async def twin_scan(request: Request, cid: Optional[str] = None,
                     user: dict = Depends(get_current_user)):
    _require_priv(user)
    company = _company_or_param(user, cid)
    return await isabella_twin.scan_company(company)


@router.post("/expansion/scan")
@limiter.limit(get_limit("isabella_write"))
async def expansion_scan(request: Request, cid: Optional[str] = None,
                          user: dict = Depends(get_current_user)):
    _require_priv(user)
    company = _company_or_param(user, cid)
    return await isabella_expansion.scan_company(company)


@router.post("/all/scan")
@limiter.limit(get_limit("isabella_write"))
async def all_scan(request: Request, cid: Optional[str] = None,
                    user: dict = Depends(get_current_user)):
    """Roda os 5 Commanders + Conselho em sequência (operação manual)."""
    _require_priv(user)
    company = _company_or_param(user, cid)
    out = {
        "churn": await isabella_churn.scan_company(company),
        "dunning": await isabella_dunning.scan_company(company),
        "revenue": await isabella_revenue.scan_company(company),
        "twin": await isabella_twin.scan_company(company),
        "expansion": await isabella_expansion.scan_company(company),
    }
    out["council"] = await isabella_conselho.hold_meeting(company)
    return out


# ---------------------------------------------------------------------------
# Conselho
# ---------------------------------------------------------------------------
@router.post("/council/hold")
@limiter.limit(get_limit("isabella_write"))
async def council_hold(request: Request, cid: Optional[str] = None,
                        user: dict = Depends(get_current_user)):
    _require_priv(user)
    company = _company_or_param(user, cid)
    return await isabella_conselho.hold_meeting(company)


@router.get("/council/latest")
@limiter.limit(get_limit("isabella_read"))
async def council_latest(request: Request, cid: Optional[str] = None,
                          user: dict = Depends(get_current_user)):
    from database import db
    company = _company_or_param(user, cid)
    doc = await db.isabella_council_minutes.find_one(
        {"company_id": company}, {"_id": 0},
        sort=[("held_at", -1)])
    if not doc:
        raise HTTPException(404, "nenhuma reunião registrada")
    return doc


@router.get("/council/history")
@limiter.limit(get_limit("isabella_read"))
async def council_history(request: Request,
                            cid: Optional[str] = None, limit: int = 20,
                            user: dict = Depends(get_current_user)):
    from database import db
    company = _company_or_param(user, cid)
    return await db.isabella_council_minutes.find(
        {"company_id": company}, {"_id": 0,
                                     "top_opportunities": 0}
    ).sort("held_at", -1).limit(min(limit, 100)).to_list(min(limit, 100))


# ---------------------------------------------------------------------------
# Incident — Mass Notify (fechamento da fase 7 do plano CTO)
# ---------------------------------------------------------------------------
@router.post("/incidents/{incident_id}/notify")
@limiter.limit(get_limit("isabella_write"))
async def incident_mass_notify(incident_id: str, request: Request,
                                phase: str = Body("update", embed=True),
                                custom_text: Optional[str] = Body(None, embed=True),
                                cid: Optional[str] = None,
                                user: dict = Depends(get_current_user)):
    """Dispara mensagem WhatsApp em massa aos clientes do incidente.
    phases: opened|update|resolved|custom."""
    _require_priv(user)
    company = _company_or_param(user, cid)
    actor = user.get("email") or user.get("id")
    if phase not in ("opened", "update", "resolved", "custom"):
        raise HTTPException(400, "phase inválido")
    if phase == "custom" and not (custom_text or "").strip():
        raise HTTPException(400, "custom_text obrigatório para phase=custom")
    return await isabella_incident.mass_notify_incident(
        company, incident_id, phase=phase,
        custom_text=custom_text, actor=actor)
