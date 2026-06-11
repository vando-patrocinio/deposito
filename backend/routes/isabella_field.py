"""ISABELLA FIELD PRESIDENT — rotas oficiais (/api/field/isabella/*).

Mesma segurança da camada Smart Field Ops: JWT + vínculo de colaborador +
company_id + rate limit + auditoria. Nenhum sistema paralelo — apenas o
motor de decisão (services/isabella_field.py) sobre os dados reais.
"""

NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from core import get_current_user
from services import isabella_field as isa
from services.rate_limit import get_limit, limiter
from routes.field_ops import (_audit, _company_of, _is_privileged,
                              _owned_ticket, _resolve_collab)

logger = logging.getLogger("ponto.isabella_field_routes")
router = APIRouter(prefix="/api/field/isabella", tags=["isabella_field"])


@router.get("/briefing")
@limiter.limit(get_limit("field_read"))
async def isabella_briefing(request: Request, cid: Optional[str] = None,
                            user: dict = Depends(get_current_user)):
    """Briefing do dia: saudação, recomendação, rota, estoque, frota."""
    collab, read_only = await _resolve_collab(user, cid)
    company = _company_of(user)
    briefing = await isa.build_briefing(company, collab)
    briefing["read_only"] = read_only
    return briefing


@router.get("/route")
@limiter.limit(get_limit("field_read"))
async def isabella_route(request: Request, cid: Optional[str] = None,
                         user: dict = Depends(get_current_user)):
    """ROTA RECOMENDADA PELA ISABELLA (emite eventos route/priority)."""
    collab, read_only = await _resolve_collab(user, cid)
    company = _company_of(user)
    data = await isa.optimize_route(company, collab, emit=True)
    data["read_only"] = read_only
    return data


@router.get("/os/{ticket_id}/brief")
@limiter.limit(get_limit("field_read"))
async def isabella_os_brief(ticket_id: str, request: Request,
                            cid: Optional[str] = None,
                            user: dict = Depends(get_current_user)):
    """Instalação/Reparo/Retirada Inteligente — brief pré-visita."""
    collab, _ = await _resolve_collab(user, cid)
    company = _company_of(user)
    t = await _owned_ticket(ticket_id, collab, company)
    return await isa.os_brief(company, collab, t)


@router.get("/lousa-analysis")
@limiter.limit(get_limit("field_read"))
async def isabella_lousa_analysis(request: Request,
                                  user: dict = Depends(get_current_user)):
    """Isabella preside a Lousa: analisa e PERSISTE prioridade/risco/
    previsão em toda bolha pendente/aberta (tickets.isabella)."""
    if not _is_privileged(user):
        raise HTTPException(403, "Acesso restrito a gestor/administrador")
    company = _company_of(user)
    items = await isa.lousa_presidency(company)
    await _audit(company, "ISABELLA_LOUSA_PRESIDENCY", user,
                 user.get("collaborator_id") or "-", analyzed=len(items))
    return {"items": items, "count": len(items)}


@router.get("/president-summary")
@limiter.limit(get_limit("field_read"))
async def isabella_president_summary(request: Request,
                                     user: dict = Depends(get_current_user)):
    """Indicadores consolidados de campo para o Presidente IA."""
    if not _is_privileged(user):
        raise HTTPException(403, "Acesso restrito a gestor/administrador")
    company = _company_of(user)
    summary = await isa.president_summary(company)
    # Incident Commander — visão de incidentes p/ Presidente IA
    from services import isabella_incident as inc_svc
    open_incs = await __import__("database").db.isabella_incidents.find(
        {"company_id": company,
         "status": {"$in": ["predicted", "confirmed"]}},
        {"_id": 0, "evidence": 0}).sort("criticality_score", -1).to_list(50)
    summary["incidents"] = {
        "open": len(open_incs),
        "confirmed": sum(1 for i in open_incs if i["status"] == "confirmed"),
        "predicted": sum(1 for i in open_incs if i["status"] == "predicted"),
        "monthly_revenue_at_risk_brl": round(sum(
            (i.get("financial_impact") or {}).get(
                "monthly_revenue_at_risk_brl") or 0 for i in open_incs), 2),
        "clients_at_churn_risk": sum(
            (i.get("churn_risk") or {}).get("clients_at_risk") or 0
            for i in open_incs),
        "top": open_incs[:5],
    }
    return summary


# ===========================================================================
# ISABELLA INCIDENT COMMANDER — detecção preditiva de incidentes coletivos
# ===========================================================================
@router.post("/incidents/scan")
@limiter.limit(get_limit("field_action"))
async def isabella_incidents_scan(request: Request,
                                  user: dict = Depends(get_current_user)):
    """Varredura completa das 8 regras de detecção (também roda automática
    a cada 15 min no worker)."""
    if not _is_privileged(user):
        raise HTTPException(403, "Acesso restrito a gestor/administrador")
    company = _company_of(user)
    from services.isabella_incident import detect_company
    result = await detect_company(company)
    await _audit(company, "ISABELLA_INCIDENT_SCAN", user,
                 user.get("collaborator_id") or "-",
                 new=len(result["new_incidents"]),
                 updated=len(result["updated_incidents"]))
    return result


@router.get("/incidents")
@limiter.limit(get_limit("field_read"))
async def isabella_incidents_list(request: Request, status: str = "open",
                                  user: dict = Depends(get_current_user)):
    if not _is_privileged(user):
        raise HTTPException(403, "Acesso restrito a gestor/administrador")
    company = _company_of(user)
    from database import db
    q = {"company_id": company}
    if status == "open":
        q["status"] = {"$in": ["predicted", "confirmed"]}
    items = await db.isabella_incidents.find(
        q, {"_id": 0, "evidence": 0}).sort(
        [("criticality_score", -1), ("created_at", -1)]).to_list(100)
    return {"items": items, "count": len(items)}


@router.post("/incidents/{incident_id}/confirm")
@limiter.limit(get_limit("field_action"))
async def isabella_incident_confirm(incident_id: str, request: Request,
                                    user: dict = Depends(get_current_user)):
    if not _is_privileged(user):
        raise HTTPException(403, "Acesso restrito a gestor/administrador")
    company = _company_of(user)
    from database import db
    from services.event_bus import EventType, emit_event
    inc = await db.isabella_incidents.find_one(
        {"id": incident_id, "company_id": company}, {"_id": 0, "evidence": 0})
    if not inc:
        raise HTTPException(404, "Incidente não encontrado")
    await db.isabella_incidents.update_one(
        {"id": incident_id},
        {"$set": {"status": "confirmed", "confirmed_by": user.get("email"),
                  "updated_at": __import__("core").now_iso()}})
    await emit_event(EventType.INCIDENT_CONFIRMED, company_id=company,
                     source="isabella_incident", severity="alta",
                     payload={"incident_id": incident_id,
                              "kind": inc["kind"], "scope": inc["scope"],
                              "confirmed_by": user.get("email")})
    await _audit(company, "ISABELLA_INCIDENT_CONFIRMED", user,
                 user.get("collaborator_id") or "-", incident_id=incident_id)
    return {"ok": True, "status": "confirmed"}


@router.post("/incidents/{incident_id}/resolve")
@limiter.limit(get_limit("field_action"))
async def isabella_incident_resolve(incident_id: str, request: Request,
                                    user: dict = Depends(get_current_user)):
    if not _is_privileged(user):
        raise HTTPException(403, "Acesso restrito a gestor/administrador")
    company = _company_of(user)
    from database import db
    res = await db.isabella_incidents.update_one(
        {"id": incident_id, "company_id": company},
        {"$set": {"status": "resolved", "resolved_by": user.get("email"),
                  "resolved_at": __import__("core").now_iso(),
                  "updated_at": __import__("core").now_iso()}})
    if not res.matched_count:
        raise HTTPException(404, "Incidente não encontrado")
    await _audit(company, "ISABELLA_INCIDENT_RESOLVED", user,
                 user.get("collaborator_id") or "-", incident_id=incident_id)
    return {"ok": True, "status": "resolved"}


@router.get("/incidents/network-feed")
@limiter.limit(get_limit("field_read"))
async def isabella_network_feed(request: Request,
                                user: dict = Depends(get_current_user)):
    """Feed para a Rede IA: CTOs/regiões/ONUs suspeitas + tendência."""
    if not _is_privileged(user):
        raise HTTPException(403, "Acesso restrito a gestor/administrador")
    company = _company_of(user)
    from services.isabella_incident import network_feed
    return await network_feed(company)
