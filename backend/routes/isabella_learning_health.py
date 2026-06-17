"""Isabella Learning Health — KPIs do learning loop (CEO P0 17/02/2026).

Endpoints:
    GET  /api/isabella/learning-health
        Retorna os 5 KPIs operacionais que medem se a Isabella está
        aprendendo de verdade:
          - opportunities_created_24h
          - opportunities_acted_24h
          - outcomes_recorded_24h
          - outcomes_classified_24h
          - learning_loop_closure_pct (= classified / created)

    POST /api/isabella/learning-health/reconcile
        Dispara reconciliação manual: varre opps `expired` sem outcome
        e classifica em batch. Aceita `?limit=200&kinds=dunning,churn`.

    GET  /api/isabella/learning-health/playbooks
        Top playbooks por peso (pra o gestor ver o que está aprendendo).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from core import require_role
from database import db
from services import isabella_learning, isabella_outcome_recorder
from services import opportunity_executor

router = APIRouter(prefix="/api/isabella/learning-health",
                   tags=["isabella-learning-health"])


def _company_of(user: Dict[str, Any]) -> str:
    return user.get("company_id") or "co-demo"


def _iso_24h_ago() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()


@router.get("")
async def health(
    user: Dict[str, Any] = Depends(
        require_role("gestor", "administrador", "auditor")),
) -> Dict[str, Any]:
    cid = _company_of(user)
    since = _iso_24h_ago()

    created_24h = await db.isabella_commander_opportunities.count_documents(
        {"company_id": cid, "created_at": {"$gte": since}})
    acted_24h = await db.isabella_commander_opportunities.count_documents(
        {"company_id": cid, "created_at": {"$gte": since},
         "status": {"$in": ["approved", "executed", "dismissed"]}})

    outcomes_24h = await db.isabella_outcomes.count_documents(
        {"company_id": cid, "created_at": {"$gte": since}})
    classified_24h = await db.isabella_outcomes.count_documents(
        {"company_id": cid, "created_at": {"$gte": since},
         "outcome": {"$in": ["success", "failure", "partial"]}})

    # LLC: outcomes classificados nas últimas 24h vs **outcomes recordáveis**
    # (opps expired/created nas últimas 24h). Cap em 100% pra evitar
    # distorção quando processamos backlog antigo no mesmo dia.
    denom_acted = await db.isabella_commander_opportunities.count_documents(
        {"company_id": cid,
         "$or": [{"created_at": {"$gte": since}},
                  {"updated_at": {"$gte": since}}]})
    raw_pct = (classified_24h / denom_acted * 100.0) if denom_acted > 0 \
        else 0.0
    llc_pct = round(min(100.0, raw_pct), 2)

    # Por kind (top 5)
    pipe = [
        {"$match": {"company_id": cid, "created_at": {"$gte": since}}},
        {"$group": {"_id": "$kind", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    by_kind = await db.isabella_commander_opportunities.aggregate(
        pipe).to_list(5)

    # Total pesos ativos (motor)
    weights_total = await db.isabella_playbook_weights.count_documents(
        {"company_id": cid})
    weights_with_data = await db.isabella_playbook_weights.count_documents(
        {"company_id": cid,
         "$or": [{"successes": {"$gt": 0}}, {"failures": {"$gt": 0}}]})

    # Snapshot persistido (para timeline histórica)
    snap = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "company_id": cid,
        "opportunities_created_24h": created_24h,
        "opportunities_acted_24h": acted_24h,
        "outcomes_recorded_24h": outcomes_24h,
        "outcomes_classified_24h": classified_24h,
        "learning_loop_closure_pct": llc_pct,
    }
    await db.isabella_learning_health.insert_one(snap)

    return {
        "ok": True,
        **{k: v for k, v in snap.items() if k != "_id"},
        "by_kind_24h": [{"kind": x["_id"] or "unknown",
                          "count": x["count"]} for x in by_kind],
        "playbook_weights_total": weights_total,
        "playbook_weights_with_data": weights_with_data,
        "kpi_target_llc_pct": 40.0,
        "status": ("green" if llc_pct >= 40
                   else "yellow" if llc_pct >= 5 else "red"),
    }


@router.post("/reconcile")
async def reconcile(
    limit: int = Query(100, ge=1, le=500),
    kinds: Optional[str] = Query(None,
                                   description="Lista CSV de kinds"),
    user: Dict[str, Any] = Depends(
        require_role("gestor", "administrador")),
) -> Dict[str, Any]:
    cid = _company_of(user)
    only = [k.strip() for k in kinds.split(",")] if kinds else None
    summary = await isabella_outcome_recorder.reconcile_batch(
        company_id=cid, limit=limit, only_kinds=only)
    return {"ok": True, "summary": summary,
            "limit": limit, "kinds_filter": only}


@router.get("/playbooks")
async def playbooks(
    kind: Optional[str] = Query(None),
    user: Dict[str, Any] = Depends(
        require_role("gestor", "administrador", "auditor")),
) -> Dict[str, Any]:
    cid = _company_of(user)
    rows = await isabella_learning.top_playbooks(cid, kind=kind, limit=30)
    return {"ok": True, "company_id": cid, "kind_filter": kind,
            "items": rows}


@router.get("/recent-outcomes")
async def recent_outcomes(
    limit: int = Query(20, ge=1, le=100),
    outcome: Optional[str] = Query(None,
                                     description="success|failure|partial|unknown"),
    user: Dict[str, Any] = Depends(
        require_role("gestor", "administrador", "auditor")),
) -> Dict[str, Any]:
    cid = _company_of(user)
    q: Dict[str, Any] = {"company_id": cid}
    if outcome:
        q["outcome"] = outcome
    docs = await db.isabella_outcomes.find(q, {"_id": 0}) \
        .sort("created_at", -1).limit(limit).to_list(limit)
    return {"ok": True, "items": docs}


# ═════════════ FACTUAL CLAIMS · CEO ORDEM 17/02 ═════════════


@router.get("/factual-claims/stats")
async def factual_claims_stats(
    user: Dict[str, Any] = Depends(
        require_role("gestor", "administrador", "auditor")),
) -> Dict[str, Any]:
    """Trust rate da Isabella nas últimas 24h: % de claims que passaram
    em todas as 3 conferências (audit_passed=True)."""
    from services import isabella_factual_claims as _fc
    return {"ok": True, **(await _fc.stats_24h(_company_of(user)))}


@router.get("/factual-claims")
async def factual_claims_recent(
    domain: Optional[str] = Query(
        None, description="financial|technical|cadastro|estoque"),
    passed: Optional[bool] = Query(
        None, description="filtra por audit_passed"),
    limit: int = Query(50, ge=1, le=200),
    user: Dict[str, Any] = Depends(
        require_role("gestor", "administrador", "auditor")),
) -> Dict[str, Any]:
    """Lista claims recentes da Isabella. Cada doc traz `checks`,
    `warnings`, `evidence` para auditoria ponto-a-ponto."""
    from services import isabella_factual_claims as _fc
    items = await _fc.recent(company_id=_company_of(user),
                              domain=domain, passed=passed, limit=limit)
    return {"ok": True, "items": items, "count": len(items)}


# ═════════════ SPRINT B — Pipeline & Execution ═════════════


@router.get("/pipeline")
async def pipeline_state(
    user: Dict[str, Any] = Depends(
        require_role("gestor", "administrador", "auditor")),
) -> Dict[str, Any]:
    """Snapshot do funil commander → executor. Por status + por type."""
    cid = _company_of(user)
    since = _iso_24h_ago()
    # Status global
    pipe = [
        {"$match": {"company_id": cid}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ]
    rows = await db.isabella_commander_opportunities.aggregate(
        pipe).to_list(20)
    by_status = {r["_id"] or "<none>": r["n"] for r in rows}
    # 24h
    pipe24 = [
        {"$match": {"company_id": cid, "created_at": {"$gte": since}}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ]
    rows24 = await db.isabella_commander_opportunities.aggregate(
        pipe24).to_list(20)
    by_status_24h = {r["_id"] or "<none>": r["n"] for r in rows24}
    # Executions 24h
    n_exec_24h = await db.opportunity_executor_audit.count_documents(
        {"company_id": cid, "created_at": {"$gte": since}})
    n_exec_ok_24h = await db.opportunity_executor_audit.count_documents(
        {"company_id": cid, "created_at": {"$gte": since},
         "result_ok": True})
    n_awaiting = await db.isabella_commander_opportunities.count_documents(
        {"company_id": cid, "status": "pending",
         "awaiting_approval_since": {"$exists": True}})
    return {
        "ok": True,
        "all_time_by_status": by_status,
        "last_24h_by_status": by_status_24h,
        "executions_24h": n_exec_24h,
        "executions_ok_24h": n_exec_ok_24h,
        "exec_success_rate_24h": round(
            (n_exec_ok_24h / n_exec_24h * 100.0) if n_exec_24h else 0.0,
            2),
        "awaiting_approval": n_awaiting,
        "dry_run": opportunity_executor._is_dry_run(),
    }


@router.post("/execute")
async def trigger_execute(
    opp_id: Optional[str] = Query(None,
                                    description="Executa 1 opp específica"),
    limit: int = Query(5, ge=1, le=50,
                         description="Cap pra drenagem batch"),
    user: Dict[str, Any] = Depends(
        require_role("gestor", "administrador")),
) -> Dict[str, Any]:
    cid = _company_of(user)
    if opp_id:
        opp = await db.isabella_commander_opportunities.find_one(
            {"id": opp_id, "company_id": cid}, {"_id": 0})
        if not opp:
            return {"ok": False, "reason": "opp_not_found",
                    "opp_id": opp_id}
        r = await opportunity_executor.execute_opportunity(opp)
        return {"ok": True, "opp_id": opp_id, "result": r}
    r = await opportunity_executor.drain_pending(
        company_id=cid, limit=limit)
    return r


@router.post("/approve")
async def approve_opportunity(
    opp_id: str = Query(..., description="opp a aprovar"),
    execute_now: bool = Query(True,
                                description="Executa imediatamente após approve"),
    user: Dict[str, Any] = Depends(
        require_role("gestor", "administrador")),
) -> Dict[str, Any]:
    cid = _company_of(user)
    now = datetime.now(timezone.utc).isoformat()
    upd = await db.isabella_commander_opportunities.update_one(
        {"id": opp_id, "company_id": cid,
         "status": {"$nin": ["executed", "dismissed"]}},
        {"$set": {"status": "approved", "approved_at": now,
                   "approved_by": user.get("email") or user.get("id")}})
    if not upd.modified_count:
        return {"ok": False, "reason": "opp_not_found_or_already_handled"}
    if not execute_now:
        return {"ok": True, "approved": True, "executed": False}
    opp = await db.isabella_commander_opportunities.find_one(
        {"id": opp_id, "company_id": cid}, {"_id": 0})
    r = await opportunity_executor.execute_opportunity(opp)
    return {"ok": True, "approved": True, "executed": r.get("ok"),
            "result": r}
