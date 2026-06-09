"""
motor_ia_intel.py — Endpoints REST do Motor IA pós-CTO audit
  - GET /api/motor-ia/leader          → quem é o líder do scheduler
  - GET /api/motor-ia/feedback         → stats por action_type
  - GET /api/motor-ia/learnings        → snapshots de aprendizado
  - GET /api/motor-ia/predictions      → últimas predições por kind
  - POST /api/motor-ia/predictions/run → roda predições ad-hoc (admin)
  - GET /api/motor-ia/llm-budget       → uso mensal do Estrategista
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Query

from rbac import require_roles

router = APIRouter(prefix="/api/motor-ia", tags=["motor-ia"])


@router.get("/leader")
async def get_leader(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
):
    """Sprint pós-audit — quem está executando os jobs autônomos."""
    from services.scheduler_lock import current_leader
    return await current_leader()


@router.get("/feedback")
async def get_feedback(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
    refresh: bool = Query(False, description="força recálculo"),
):
    """Sprint 10 — stats do feedback loop por action_type."""
    from services.feedback_loop import refresh_stats, get_stats
    if refresh:
        stats = await refresh_stats(force=True)
    else:
        stats = await get_stats()
    return {"stats": stats}


@router.get("/learnings")
async def get_learnings(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
    limit: int = Query(30, ge=1, le=200),
):
    """Sprint 12 — snapshots de aprendizado."""
    from services.learnings import list_learnings, latest_snapshot
    return {
        "latest": await latest_snapshot(),
        **(await list_learnings(limit=limit)),
    }


@router.get("/predictions")
async def get_predictions(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    """Sprint 11 — últimas predições (churn/revenue/ticket_demand)."""
    from services.predictions import latest_by_kind
    return {
        "churn": await latest_by_kind("churn"),
        "revenue": await latest_by_kind("revenue"),
        "ticket_demand": await latest_by_kind("ticket_demand"),
    }


@router.post("/predictions/run")
async def run_predictions(
    user: Dict[str, Any] = Depends(require_roles("administrador")),
):
    """Sprint 11 — força execução de predições agora (admin)."""
    from services.predictions import run_all_predictions
    return await run_all_predictions()


@router.get("/llm-budget")
async def get_llm_budget(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
):
    """P2 — uso mensal do Estrategista IA."""
    from services.llm_budget import get_status
    return await get_status()


# ─────────── Sprint 15 — feature flag LIVE por cliente ───────────
@router.get("/live-settings")
async def get_live_settings(
    user: Dict[str, Any] = Depends(require_roles("administrador")),
):
    from services.company_settings import list_all_live_settings
    return {"items": await list_all_live_settings()}


@router.post("/live-settings/{company_id}")
async def set_live_settings(
    company_id: str,
    body: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_roles("administrador")),
):
    from services.company_settings import set_live
    return await set_live(company_id,
                           body.get("live_actions") or [],
                           updated_by=user.get("id") or user.get("sub"))


# ─────────── Sprint 17 — auto-tuning de thresholds ───────────
@router.get("/thresholds")
async def get_thresholds(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
):
    from services.rule_thresholds import DEFAULTS, _refresh_cache
    cache = await _refresh_cache()
    return {"defaults": DEFAULTS, "current": cache}


@router.post("/thresholds/auto-tune")
async def run_auto_tune(
    user: Dict[str, Any] = Depends(require_roles("administrador")),
):
    from services.rule_thresholds import auto_tune
    return await auto_tune()


@router.post("/thresholds/{rule}")
async def set_threshold_route(
    rule: str,
    body: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_roles("administrador")),
):
    from services.rule_thresholds import set_threshold
    return await set_threshold(
        rule, body.get("thresholds") or {},
        updated_by=user.get("id") or "admin",
        reason=body.get("reason", "manual"))


# ─────────── Sprint 18 — ML real ───────────
@router.post("/ml/run")
async def run_ml_models(
    user: Dict[str, Any] = Depends(require_roles("administrador")),
):
    from services.ml_predictions import run_all_ml
    return await run_all_ml()


@router.get("/ml/churn")
async def get_churn_ml(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    """Última predição ML de churn (IsolationForest)."""
    doc = await __import__("database").db.motor_ia_predictions.find_one(
        {"kind": "churn_iforest"}, sort=[("generated_at", -1)])
    if doc:
        doc.pop("_id", None)
    return doc or {}


@router.get("/ml/ticket-forecast")
async def get_ticket_forecast(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    """Última previsão AR(2) de tickets."""
    doc = await __import__("database").db.motor_ia_predictions.find_one(
        {"kind": "ticket_arima"}, sort=[("generated_at", -1)])
    if doc:
        doc.pop("_id", None)
    return doc or {}


# ─────────── Sprint 19.5 — LIVE Pilot ───────────
@router.post("/pilot/start")
async def pilot_start(
    body: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_roles("administrador")),
):
    from services.live_pilot import start_pilot
    co = body.get("company_id")
    actions = body.get("action_types") or ["escalate_dunning"]
    if not co:
        return {"error": "company_id obrigatório"}
    return await start_pilot(
        co, actions, notes=body.get("notes", ""),
        started_by=user.get("id") or user.get("email"))


@router.post("/pilot/stop/{company_id}")
async def pilot_stop(
    company_id: str,
    user: Dict[str, Any] = Depends(require_roles("administrador")),
):
    from services.live_pilot import stop_pilot
    return await stop_pilot(
        company_id, stopped_by=user.get("id") or user.get("email"))


@router.get("/pilot/metrics/{company_id}")
async def pilot_metrics_route(
    company_id: str,
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
):
    from services.live_pilot import pilot_metrics
    return await pilot_metrics(company_id)


@router.get("/pilot/list")
async def pilot_list(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
):
    from services.live_pilot import list_pilots
    return await list_pilots()


# ─────────── Sprint 20 — Validation Harness ───────────
@router.post("/predictions/validate")
async def predictions_validate(
    user: Dict[str, Any] = Depends(require_roles("administrador")),
):
    from services.predictions_validation import run_validation_cycle
    return await run_validation_cycle()


@router.get("/predictions/accuracy")
async def predictions_accuracy(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor")),
):
    from services.predictions_validation import accuracy_summary
    return await accuracy_summary()
