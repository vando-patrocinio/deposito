"""OPERAÇÃO COLOSSO — endpoints REST.

Reuso 100% de serviços existentes. Prefix `/api/colosso/*`.
Sem dashboard novo — endpoints servem o painel da Lousa atual.
"""
from __future__ import annotations
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from core import require_role
from services import lousa_coo, smart_field_v2, truck_roll_guard

router = APIRouter(prefix="/api/colosso", tags=["colosso"])


@router.get("/daily-directive")
async def daily_directive(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id")
    return await lousa_coo.daily_directive(cid)


@router.post("/enforce-preventive-ratio")
async def enforce_preventive(dry_run: bool = False,
                                user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id")
    return await lousa_coo.enforce_preventive_ratio(cid, dry_run=dry_run)


@router.get("/plan-field-day")
async def plan_field_day(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id")
    return await lousa_coo.plan_field_day(cid)


@router.post("/compute-technician-scores")
async def compute_tech_scores(window_days: int = 30,
                                 user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id")
    return await lousa_coo.compute_technician_scores(cid, window_days=window_days)


@router.post("/operational-council")
async def operational_council(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id")
    return await lousa_coo.operational_council_weekly(cid)


@router.post("/os/{ticket_id}/learning")
async def os_learning(ticket_id: str,
                          user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id")
    return await lousa_coo.register_os_learning(ticket_id, cid)


@router.post("/alvaro/command-loop")
async def alvaro_command(max_actions: int = 20,
                            user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id")
    return await lousa_coo.alvaro_command_loop(cid, max_actions=max_actions)


@router.get("/truck-roll/{subscriber_id}")
async def truck_roll(subscriber_id: str,
                        user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id")
    res = await truck_roll_guard.evaluate(cid, subscriber_id)
    if res.get("decision") == "UNKNOWN":
        raise HTTPException(404, "subscriber não encontrado")
    return res


@router.get("/os/{ticket_id}/context")
async def os_context(ticket_id: str,
                        user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id")
    res = await smart_field_v2.os_context_for_technician(cid, ticket_id)
    if "error" in res:
        raise HTTPException(404, res["error"])
    return res


@router.get("/stock/health")
async def stock_health(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id")
    return await smart_field_v2.stock_health(cid)


@router.post("/stock/transition")
async def stock_transition(payload: Dict[str, Any],
                              user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id")
    eq = payload.get("equipment_id") or payload.get("id")
    stage = payload.get("stage")
    if not eq or not stage:
        raise HTTPException(400, "equipment_id e stage são obrigatórios")
    return await smart_field_v2.track_equipment_stage(
        company_id=cid, equipment_id=eq, stage=stage,
        serial=payload.get("serial"),
        technician_id=payload.get("technician_id"),
        subscriber_id=payload.get("subscriber_id"),
        cost_brl=payload.get("cost_brl"),
        notes=payload.get("notes"))
