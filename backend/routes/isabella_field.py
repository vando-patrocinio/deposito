"""ISABELLA FIELD PRESIDENT — rotas oficiais (/api/field/isabella/*).

Mesma segurança da camada Smart Field Ops: JWT + vínculo de colaborador +
company_id + rate limit + auditoria. Nenhum sistema paralelo — apenas o
motor de decisão (services/isabella_field.py) sobre os dados reais.
"""
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
    return await isa.president_summary(company)
