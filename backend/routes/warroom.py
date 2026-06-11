"""
warroom.py — Sprint 7 / iter226
Rotas da Sala de Guerra do Presidente IA.
"""
from __future__ import annotations


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

router = APIRouter(prefix="/api/presidente-ia", tags=["warroom"])


@router.get("/warroom")
async def warroom(user: Dict[str, Any] = Depends(
    require_roles("administrador", "auditor"))):
    """Snapshot completo para a Sala de Guerra."""
    from services.executive_health import compute_executive_score
    from services.data_quality import run_scan
    from services.audit_alerts import scan_security_alerts
    from database import db

    exec_h = await compute_executive_score()
    dq = await run_scan()
    alerts = await scan_security_alerts()

    # ações executadas / decisões hoje
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    decisions = await db.motor_ia_decisions.count_documents(
        {"created_at": {"$gte": today}})
    actions = await db.motor_ia_actions.count_documents(
        {"created_at": {"$gte": today}})

    return {
        "executive": exec_h,
        "data_quality": dq,
        "critical_alerts": alerts,
        "decisions_today": decisions,
        "actions_today": actions,
    }


@router.get("/data-quality")
async def data_quality(user: Dict[str, Any] = Depends(
    require_roles("administrador", "auditor", "gestor"))):
    from services.data_quality import run_scan
    return await run_scan()


@router.get("/executive-health")
async def executive_health(user: Dict[str, Any] = Depends(
    require_roles("administrador", "auditor", "gestor"))):
    from services.executive_health import compute_executive_score
    return await compute_executive_score()


@router.post("/scheduler/run-now")
async def run_now(user: Dict[str, Any] = Depends(
    require_roles("administrador"))):
    """Força execução imediata dos 3 ticks (debug)."""
    from services import executive_scheduler as sch
    await sch._tick_1min()
    await sch._tick_5min()
    await sch._tick_1h()
    return {"ok": True}


# ─────────────────── Sprint 8 — Decision + Action ───────────────────
# Nota: /decisions e /actions já existem em presidente_ia.py.
# Aqui só expomos o endpoint de execução do ciclo.

@router.post("/decision-cycle/run")
async def run_decision_cycle_now(
    user: Dict[str, Any] = Depends(
        require_roles("administrador"))):
    """Roda ciclo decisão→ação imediatamente. Útil para debug."""
    from services.decision_engine import run_decision_cycle
    from services.action_engine import execute_pending
    d = await run_decision_cycle()
    a = await execute_pending()
    return {"decision_cycle": d, "action_execution": a}


# ─────────────────── Sprint 9 — Estrategista IA ───────────────────
@router.get("/strategist/report")
async def strategist_report(
    period: str = "daily",
    force: bool = False,
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor"))):
    """Gera/recupera relatório do Estrategista IA.
    period: daily | weekly | monthly. force=true ignora cache."""
    from services.estrategista_ia import generate_report
    if period not in ("daily", "weekly", "monthly"):
        from fastapi import HTTPException
        raise HTTPException(400, "period inválido")
    return await generate_report(period=period, force=force)


@router.get("/strategist/reports/history")
async def strategist_history(
    limit: int = 10,
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor"))):
    """Histórico dos últimos relatórios gerados."""
    from database import db
    cur = db.motor_ia_memory.find(
        {"kind": "estrategista_report"},
        {"_id": 0, "context": 0},
    ).sort("created_at", -1).limit(min(max(limit, 1), 100))
    items = []
    async for it in cur:
        items.append(it)
    return {"items": items, "count": len(items)}
