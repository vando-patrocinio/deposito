"""
ai_center_autonomous.py — FASE 10 V5.0
Endpoints do Autonomous Engine.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Body
from typing import List

from rbac import require_roles
from services import autonomous_engine as eng
from services import auto_tuning

router = APIRouter(prefix="/api/ai-center/autonomous",
                    tags=["ai-center-autonomous"])


def _co(user):
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid: raise HTTPException(400, "company_id ausente")
    return cid


@router.post("/run-cycle")
async def post_run_cycle(event: dict = Body(...),
                          user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    event["company_id"] = event.get("company_id") or _co(user)
    return await eng.run_cycle(event)


@router.post("/drive/overdue")
async def drive_overdue(limit: int = 5,
                         user=Depends(require_roles(
                             "administrador", "auditor", "gestor"))):
    return {"cycles": await eng.drive_from_overdue(_co(user), limit)}


@router.post("/drive/churn")
async def drive_churn(limit: int = 5,
                       user=Depends(require_roles(
                           "administrador", "auditor", "gestor"))):
    return {"cycles": await eng.drive_from_isabella_churn(_co(user), limit)}


@router.post("/drive/onu-degraded")
async def drive_onu(limit: int = 5,
                     user=Depends(require_roles(
                         "administrador", "auditor", "gestor"))):
    return {"cycles": await eng.drive_from_onu_degraded(_co(user), limit)}


@router.post("/drive/isabella-retention")
async def drive_retention(limit: int = 5,
                            user=Depends(require_roles(
                                "administrador", "auditor", "gestor"))):
    return {"cycles": await eng.drive_from_isabella_retention(
        _co(user), limit)}


@router.post("/drive/isabella-referral")
async def drive_referral(limit: int = 5,
                           user=Depends(require_roles(
                               "administrador", "auditor", "gestor"))):
    return {"cycles": await eng.drive_from_isabella_referral(
        _co(user), limit)}


@router.post("/drive/isabella-collection")
async def drive_collection(limit: int = 5,
                             user=Depends(require_roles(
                                 "administrador", "auditor", "gestor"))):
    return {"cycles": await eng.drive_from_isabella_collection(
        _co(user), limit)}


@router.get("/autonomy-score")
async def get_score(days: int = 1,
                     user=Depends(require_roles(
                         "administrador", "auditor", "gestor"))):
    return await eng.compute_autonomy_score(_co(user), days)


@router.get("/daily-briefing")
async def get_briefing(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return await eng.daily_briefing(_co(user))


@router.get("/cycles")
async def get_cycles(limit: int = 50, status: str | None = None,
                      user=Depends(require_roles(
                          "administrador", "auditor", "gestor"))):
    from database import db
    q = {"company_id": _co(user)}
    if status: q["status"] = status
    rows = await db.motor_ia_autonomous_cycles.find(q).sort(
        "started_at", -1).limit(limit).to_list(limit)
    for r in rows: r.pop("_id", None)
    return {"items": rows, "count": len(rows)}


@router.get("/cycle/{cycle_id}")
async def get_cycle_detail(cycle_id: str,
                            user=Depends(require_roles(
                                "administrador", "auditor", "gestor"))):
    from database import db
    co = _co(user)
    cycle = await db.motor_ia_autonomous_cycles.find_one(
        {"cycle_id": cycle_id, "company_id": co})
    if not cycle:
        raise HTTPException(404, "cycle não encontrado")
    cycle.pop("_id", None)
    out = {"cycle": cycle}
    for col, key in [("motor_ia_analysis", "analysis_id"),
                       ("motor_ia_decisions", "decision_id"),
                       ("motor_ia_actions", "action_id"),
                       ("motor_ia_outcomes", "outcome_id"),
                       ("motor_ia_learnings", "learning_id")]:
        doc = await __import__("database").db[col].find_one(
            {key: cycle.get(key)})
        if doc:
            doc.pop("_id", None)
            out[col.replace("motor_ia_", "")] = doc
    return out


@router.post("/tune")
async def post_tune(window_days: int = 14,
                     user=Depends(require_roles(
                         "administrador", "auditor"))):
    return await auto_tuning.tune_thresholds(_co(user), window_days)


@router.get("/summary")
async def get_summary(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    """Resumo executivo do Autonomous Center."""
    from database import db
    from datetime import datetime, timezone
    co = _co(user)
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0).isoformat()

    cycles_today = await db.motor_ia_autonomous_cycles.count_documents({
        "company_id": co, "started_at": {"$gte": today}})
    actions_today = await db.motor_ia_actions.count_documents({
        "company_id": co, "created_at": {"$gte": today}})
    decisions_today = await db.motor_ia_decisions.count_documents({
        "company_id": co, "created_at": {"$gte": today}})
    learnings_today = await db.motor_ia_learnings.count_documents({
        "company_id": co, "created_at": {"$gte": today}})

    # Receita gerada/recuperada hoje
    pipe = [{"$match": {"company_id": co,
                          "observed_at": {"$gte": today}}},
             {"$group": {"_id": None,
                          "actual": {"$sum": "$actual_BRL"},
                          "expected": {"$sum": "$expected_BRL"}}}]
    r = await db.motor_ia_outcomes.aggregate(pipe).to_list(1)
    actual = float(r[0]["actual"]) if r else 0.0
    expected = float(r[0]["expected"]) if r else 0.0

    score = await eng.compute_autonomy_score(co, days=1)
    tuning_count = await db.motor_ia_tuning_log.count_documents({
        "company_id": co, "applied_at": {"$gte": today}})

    # Status do transporte (sprint final)
    from services import transport_check as tx
    transport = await tx.wa_status(co)

    # Bloqueios reais
    blocked_today = await db.motor_ia_actions.count_documents({
        "company_id": co, "created_at": {"$gte": today},
        "status": {"$in": ["blocked_transport", "blocked_data",
                            "queued_no_credentials"]}})

    # Recommend-only (confidence < 0.6)
    recommend_only_today = await db.motor_ia_actions.count_documents({
        "company_id": co, "created_at": {"$gte": today},
        "status": "recommend_only"})

    return {
        "today": datetime.now(timezone.utc).date().isoformat(),
        "autonomy_score": score,
        "cycles_today": cycles_today,
        "decisions_today": decisions_today,
        "actions_today": actions_today,
        "learnings_today": learnings_today,
        "blocked_today": blocked_today,
        "recommend_only_today": recommend_only_today,
        "revenue_generated_BRL": round(actual, 2),
        "revenue_protected_BRL": round(expected, 2),
        "revenue_lost_BRL": round(max(expected - actual, 0), 2),
        "auto_tunings_today": tuning_count,
        "transport": transport,
    }


@router.get("/transport-check")
async def get_transport_check(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    from services import transport_check as tx
    return await tx.wa_status(_co(user))


@router.post("/reconcile")
async def post_reconcile(hours: int = 168,
                          user=Depends(require_roles(
                              "administrador", "auditor"))):
    from services import reconcile_worker as rec
    return await rec.reconcile_all_recent(_co(user), hours=hours)


@router.post("/briefing/dispatch")
async def post_briefing_dispatch(
        slot: str = "07h",
        user=Depends(require_roles("administrador", "auditor"))):
    from services import briefing_dispatcher as bd
    return await bd.dispatch(_co(user), slot=slot)


@router.get("/scheduler/status")
async def get_scheduler_status(user=Depends(
    require_roles("administrador", "auditor"))):
    """Status real do scheduler global (jobs com prefixo autonomy_)."""
    try:
        from server import scheduler as _global_sch
        running = _global_sch.running
        jobs = []
        for j in _global_sch.get_jobs():
            if j.id.startswith("autonomy_"):
                jobs.append({
                    "id": j.id,
                    "next_run": str(j.next_run_time),
                    "trigger": str(j.trigger),
                })
        return {"running": running, "jobs": jobs}
    except Exception as e:  # noqa: BLE001
        return {"running": False, "jobs": [], "error": str(e)}


@router.post("/scheduler/start")
async def post_scheduler_start(user=Depends(
    require_roles("administrador", "auditor"))):
    return {"message": "Scheduler global gerenciado pelo server.py "
                       "(auto-start no boot). Use AUTONOMY_SCHEDULER_DISABLED "
                       "para controlar via env."}


@router.post("/scheduler/stop")
async def post_scheduler_stop(user=Depends(
    require_roles("administrador", "auditor"))):
    """Pausa jobs autonomy_*."""
    from server import scheduler as _global_sch
    paused = []
    for j in _global_sch.get_jobs():
        if j.id.startswith("autonomy_"):
            j.pause()
            paused.append(j.id)
    return {"paused": paused}
