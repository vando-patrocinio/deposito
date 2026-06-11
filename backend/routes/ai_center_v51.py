"""Rotas REST V5.0 (Sprint 1+2) e V5.1 reagrupadas."""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from database import db
from core import require_role
from services import alvaro_v5, failure_risk, ops_v51

router = APIRouter(prefix="/api/ai-center", tags=["alvaro-v5-v51"])


def _co(user) -> str:
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid:
        raise HTTPException(400, "company_id ausente.")
    return cid


# ─────── ALVARO V5 — Sprint 1 ───────
class TriageIn(BaseModel):
    subscriber_id: str = Field(..., min_length=1)
    complaint: str = Field(..., min_length=1, max_length=2000)


@router.post("/alvaro-v5/triage")
async def triage(body: TriageIn, persist: bool = Query(False),
                 user=Depends(require_role("administrador",
                                            "auditor", "gestor"))):
    cid = _co(user)
    out = await alvaro_v5.triage(body.subscriber_id, body.complaint,
                                 company_id=cid)
    if persist and out.get("decision"):
        await alvaro_v5.persist_v5_decision(out["decision"])
    return out


@router.get("/alvaro-v5/consult-network/{subscriber_id}")
async def consult_network(subscriber_id: str,
                          user=Depends(require_role("administrador",
                                                     "auditor", "gestor"))):
    return await alvaro_v5.consult_network(subscriber_id,
                                           company_id=_co(user))


@router.get("/alvaro-v5/recurrence/list")
async def recurrence_list(
    classification: Optional[str] = Query(
        None, pattern="^(BAIXO|MEDIO|ALTO|CRITICO)$"),
    min_score: int = Query(0, ge=0, le=100),
    limit: int = Query(100, ge=1, le=1000),
    user=Depends(require_role("administrador", "auditor", "gestor"))):
    cid = _co(user)
    q: dict = {"company_id": cid}
    if classification:
        q["classification"] = classification
    if min_score > 0:
        q["score"] = {"$gte": min_score}
    items = []
    async for d in db.motor_ia_recurrence_scores.find(q).sort(
            "score", -1).limit(limit):
        d.pop("_id", None)
        items.append(d)
    return {"items": items, "count": len(items)}


@router.get("/alvaro-v5/recurrence/{subscriber_id}")
async def recurrence_one(subscriber_id: str,
                         recompute: bool = Query(False),
                         user=Depends(require_role("administrador",
                                                    "auditor", "gestor"))):
    cid = _co(user)
    if recompute:
        return await alvaro_v5.compute_recurrence_score(
            subscriber_id, company_id=cid, persist=True)
    doc = await db.motor_ia_recurrence_scores.find_one(
        {"subscriber_id": subscriber_id, "company_id": cid})
    if not doc:
        return await alvaro_v5.compute_recurrence_score(
            subscriber_id, company_id=cid, persist=True)
    doc.pop("_id", None)
    return doc


@router.post("/alvaro-v5/recurrence/batch")
async def recurrence_batch(limit: int = Query(500, ge=1, le=5000),
                           user=Depends(require_role("administrador"))):
    return await alvaro_v5.recompute_recurrence_batch(_co(user),
                                                     limit=limit)


# ─────── FAILURE RISK — Sprint 2 + V5.1 ───────
@router.get("/failure-risk/list")
async def fr_list(
    classification: Optional[str] = Query(
        None, pattern="^(BAIXO|MEDIO|ALTO|CRITICO)$"),
    min_score: int = Query(0, ge=0, le=100),
    limit: int = Query(100, ge=1, le=1000),
    user=Depends(require_role("administrador", "auditor", "gestor"))):
    cid = _co(user)
    q: dict = {"company_id": cid}
    if classification:
        q["classification"] = classification
    if min_score > 0:
        q["score"] = {"$gte": min_score}
    items = []
    async for d in db.motor_ia_failure_risk_scores.find(q).sort(
            "score", -1).limit(limit):
        d.pop("_id", None)
        items.append(d)
    return {"items": items, "count": len(items)}


@router.get("/failure-risk/distribution")
async def fr_distribution(
        user=Depends(require_role("administrador", "auditor", "gestor"))):
    return await failure_risk.distribution(_co(user))


@router.get("/failure-risk/metrics")
async def fr_metrics(
        window_days: int = Query(30, ge=1, le=365),
        user=Depends(require_role("administrador",
                                   "auditor", "gestor"))):
    return await failure_risk.phase_h_metrics(_co(user),
                                              window_days=window_days)


@router.post("/failure-risk/drive")
async def fr_drive(limit: int = Query(200, ge=1, le=5000),
                   only_changed: bool = Query(False),
                   user=Depends(require_role("administrador"))):
    return await failure_risk.drive_from_failure_risk(
        _co(user), limit=limit, only_changed=only_changed)


@router.get("/failure-risk/{subscriber_id}")
async def fr_one(subscriber_id: str,
                 recompute: bool = Query(False),
                 user=Depends(require_role("administrador",
                                            "auditor", "gestor"))):
    cid = _co(user)
    if recompute:
        return await failure_risk.compute_failure_risk(
            subscriber_id, company_id=cid, persist=True)
    doc = await db.motor_ia_failure_risk_scores.find_one(
        {"subscriber_id": subscriber_id, "company_id": cid})
    if not doc:
        return await failure_risk.compute_failure_risk(
            subscriber_id, company_id=cid, persist=True)
    doc.pop("_id", None)
    return doc


# ─────── V5.1 OPS ───────
@router.get("/v51/go-live-checklist")
async def go_live(user=Depends(require_role("administrador",
                                             "auditor", "gestor"))):
    return await ops_v51.go_live_checklist(_co(user))


@router.get("/v51/technician-score/{tech_id}")
async def tech_score(tech_id: str,
                     window_days: int = Query(30, ge=1, le=365),
                     user=Depends(require_role("administrador",
                                                "auditor", "gestor"))):
    return await ops_v51.technician_score(_co(user), tech_id,
                                          window_days=window_days)


@router.get("/v51/technician-ranking")
async def tech_ranking(window_days: int = Query(30, ge=1, le=365),
                       limit: int = Query(50, ge=1, le=200),
                       user=Depends(require_role("administrador",
                                                  "auditor", "gestor"))):
    items = await ops_v51.technician_ranking(_co(user),
                                             window_days=window_days,
                                             limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/v51/ops-kpis")
async def kpis(window_days: int = Query(30, ge=1, le=365),
               user=Depends(require_role("administrador",
                                          "auditor", "gestor"))):
    return await ops_v51.ops_kpis(_co(user),
                                  window_days=window_days)


@router.get("/v51/cto-ranking")
async def cto_rank(window_days: int = Query(30, ge=1, le=365),
                   user=Depends(require_role("administrador",
                                              "auditor", "gestor"))):
    return {"items": await ops_v51.cto_ranking(_co(user),
                                               window_days=window_days)}


@router.get("/v51/region-ranking")
async def region_rank(window_days: int = Query(30, ge=1, le=365),
                      user=Depends(require_role("administrador",
                                                 "auditor", "gestor"))):
    return {"items": await ops_v51.region_ranking(
        _co(user), window_days=window_days)}


@router.get("/v51/vlan-ranking")
async def vlan_rank(user=Depends(require_role("administrador",
                                               "auditor", "gestor"))):
    return {"items": await ops_v51.vlan_ranking(_co(user))}


@router.get("/v51/command-center")
async def command_center(window_days: int = Query(30, ge=1, le=365),
                         user=Depends(require_role("administrador",
                                                    "auditor", "gestor"))):
    return await ops_v51.command_center_summary(
        _co(user), window_days=window_days)


@router.get("/v51/smart-field-ops/status")
async def sfo_status(user=Depends(require_role("administrador"))):
    return await ops_v51.smart_field_ops_status(_co(user))
