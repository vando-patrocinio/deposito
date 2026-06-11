"""Rotas do Presidente IA — Equipe Digital sob comando.

Endpoints:
  GET /api/presidente/agentes           Snapshot completo da equipe IA
  GET /api/presidente/organizacao       Organograma em árvore
  GET /api/presidente/agente/{id}       Detalhe individual de um agente
  POST /api/presidente/equipe/scan      Força rescan + audit chain
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "presidente",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging

from fastapi import APIRouter, Depends, HTTPException

from core import DEMO_COMPANY_ID, get_current_user
from rbac import audit_log as _audit, rate_limit, require_ai_access
from services import agent_registry as reg

log = logging.getLogger("ponto.presidente_agentes")
router = APIRouter(prefix="/api/presidente", tags=["presidente-equipe"])


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


@router.get("/agentes")
async def listar_agentes(
    user: dict = Depends(require_ai_access()),
    _: bool = Depends(rate_limit(30, 600, "presidente_agentes")),
):
    """Snapshot completo da equipe IA (produtividade + humanização +
    impacto financeiro + status offline/online)."""
    cid = _cid(user)
    snap = await reg.snapshot_all(cid)
    await _audit(user, "ia", "presidente_equipe_view", target=cid,
                    data={"team_size": snap["team_size"]})
    return snap


@router.get("/organizacao")
async def organograma(user: dict = Depends(get_current_user)):
    """Organograma estrutural (não exige dados em tempo real)."""
    return reg.organograma()


@router.get("/agente/{agent_id}")
async def detalhar_agente(
    agent_id: str,
    user: dict = Depends(require_ai_access()),
):
    """Detalhe operacional de um agente específico."""
    cid = _cid(user)
    try:
        return await reg.snapshot_agent(cid, agent_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/equipe/scan")
async def forcar_scan(
    user: dict = Depends(require_ai_access()),
    _: bool = Depends(rate_limit(5, 200, "presidente_equipe_scan")),
):
    """Força rescan da equipe + executa compliance auto-sync."""
    cid = _cid(user)
    from services import agent_compliance_scheduler as sched
    result = await sched.run_compliance_pass(cid)
    await _audit(user, "ia", "presidente_equipe_scan", target=cid,
                    data={"alerts": result.get("alerts_emitted", 0)})
    return result


@router.get("/receita-por-agente")
async def receita_por_agente(
    days: int = 30,
    user: dict = Depends(require_ai_access()),
    _: bool = Depends(rate_limit(30, 600, "presidente_revenue")),
):
    """Receita por agente nos últimos N dias.

    Retorna ranking ordenado por total_brl + agente do período.
    """
    from services import agent_revenue
    cid = _cid(user)
    return await agent_revenue.team_revenue(cid, days=max(1, min(days, 365)))


@router.get("/agente-do-mes")
async def agente_do_mes(
    user: dict = Depends(require_ai_access()),
):
    """O agente que mais entregou dinheiro nos últimos 30 dias."""
    from services import agent_revenue
    cid = _cid(user)
    snap = await agent_revenue.team_revenue(cid, days=30)
    return {
        "agent_of_period": snap["agent_of_period"],
        "team_total_brl": snap["team_total_brl"],
        "podium": snap["ranking"][:3],
        "window_days": 30,
    }
