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
