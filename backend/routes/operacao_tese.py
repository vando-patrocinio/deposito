"""
operacao_tese.py — Endpoints REST da Operação Tese Validada.
"""

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from typing import Any, Dict

from fastapi import APIRouter, Depends

from rbac import require_roles

router = APIRouter(prefix="/api/operacao-tese", tags=["operacao-tese"])


@router.get("/pre-flight/{company_id}")
async def route_pre_flight(
    company_id: str,
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
):
    from services.operacao_tese import pre_flight_check
    return await pre_flight_check(company_id)


@router.post("/start")
async def route_start(
    body: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_roles("administrador")),
):
    from services.operacao_tese import start_operation
    return await start_operation(
        company_id=body["company_id"],
        dry_run=body.get("dry_run", True),
        max_messages=int(body.get("max_messages", 20)),
        started_by=user.get("id") or user.get("email"))


@router.get("/monitor/{op_id}")
async def route_monitor(
    op_id: str,
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
):
    from services.operacao_tese import monitor_panel
    return await monitor_panel(op_id)


@router.get("/report/{op_id}")
async def route_report(
    op_id: str,
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
):
    from services.operacao_tese import daily_report
    return await daily_report(op_id)


@router.get("/success/{op_id}")
async def route_success(
    op_id: str,
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
):
    from services.operacao_tese import success_criteria
    return await success_criteria(op_id)


@router.post("/stop/{op_id}")
async def route_stop(
    op_id: str,
    user: Dict[str, Any] = Depends(require_roles("administrador")),
):
    from services.operacao_tese import stop_operation
    return await stop_operation(
        op_id, stopped_by=user.get("id") or user.get("email"))
