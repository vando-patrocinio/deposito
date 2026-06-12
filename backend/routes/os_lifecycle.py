"""Endpoints REST do FSM Lifecycle (CTO P0 — 12/06/2026).

  GET  /api/os-lifecycle/catalog        → estados, work types, reasons, transitions
  GET  /api/os-lifecycle/audit          → distribuição por lifecycle_state + work_type
  POST /api/os-lifecycle/backfill       → migration idempotente (atribui campos novos)
  POST /api/os-lifecycle/auto-cancel-preventive → executa o TTL job manualmente
  POST /api/tickets/{ticket_id}/transition → transição explícita de estado
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Optional, List, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, is_super_admin, now_iso, require_role
from database import db
from services.os_lifecycle import (
    ALLOWED_TRANSITIONS,
    LIFECYCLE_STATES,
    REASON_CODES,
    WORK_TYPES,
    auto_cancel_stale_preventive,
    backfill_company,
    transition as do_transition,
)
from services.os_sla import compute_sla_breach, get_sla_minutes

logger = logging.getLogger("os_lifecycle_api")
router = APIRouter(prefix="/api", tags=["os-lifecycle"])


@router.get("/os-lifecycle/catalog")
async def lifecycle_catalog(_user: dict = Depends(require_role("gestor"))):
    """Retorna estados, work types, reasons e mapa de transições."""
    return {
        "lifecycle_states": LIFECYCLE_STATES,
        "work_types": WORK_TYPES,
        "reason_codes": REASON_CODES,
        "allowed_transitions": {k: sorted(v) for k, v in ALLOWED_TRANSITIONS.items()},
    }


@router.get("/os-lifecycle/audit")
async def lifecycle_audit(user: dict = Depends(require_role("auditor"))):
    """Audita a distribuição de tickets pelos novos campos."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    pipe = [
        {"$match": {"company_id": cid}},
        {"$group": {
            "_id": {
                "lifecycle": "$lifecycle_state",
                "work_type": "$work_type",
                "legacy_status": "$status",
                "legacy_type": "$type",
            },
            "count": {"$sum": 1},
        }},
    ]
    by_lifecycle: Counter = Counter()
    by_work_type: Counter = Counter()
    legacy_breakdown: List[dict] = []
    missing_lifecycle = 0
    missing_work_type = 0
    async for row in db.tickets.aggregate(pipe):
        k = row["_id"]
        lc = k.get("lifecycle") or "(none)"
        wt = k.get("work_type") or "(none)"
        if lc == "(none)":
            missing_lifecycle += row["count"]
        if wt == "(none)":
            missing_work_type += row["count"]
        by_lifecycle[lc] += row["count"]
        by_work_type[wt] += row["count"]
        legacy_breakdown.append({
            "lifecycle_state": k.get("lifecycle"),
            "work_type": k.get("work_type"),
            "legacy_status": k.get("legacy_status"),
            "legacy_type": k.get("legacy_type"),
            "count": row["count"],
        })
    total = sum(by_lifecycle.values())
    return {
        "company_id": cid,
        "total_tickets": total,
        "missing_lifecycle_state": missing_lifecycle,
        "missing_work_type": missing_work_type,
        "by_lifecycle_state": dict(by_lifecycle.most_common()),
        "by_work_type": dict(by_work_type.most_common()),
        "legacy_breakdown": sorted(legacy_breakdown,
                                      key=lambda x: -x["count"])[:50],
        "audited_at": now_iso(),
    }


@router.post("/os-lifecycle/backfill")
async def lifecycle_backfill(user: dict = Depends(require_role("auditor"))):
    """Backfill idempotente: popula lifecycle_state + work_type em TODOS os
    tickets do tenant (ou cluster inteiro se super_admin)."""
    if is_super_admin(user):
        # roda em todos os tenants
        tenants = await db.tickets.distinct("company_id")
        all_summary = {"by_tenant": {}, "totals": Counter()}
        for cid in tenants:
            if not cid:
                continue
            s = await backfill_company(db, cid)
            all_summary["by_tenant"][cid] = s
            for k in ("checked", "set_lifecycle", "set_worktype", "skipped"):
                all_summary["totals"][k] += s.get(k, 0)
        return {**all_summary, "totals": dict(all_summary["totals"]),
                 "performed_by": user.get("email"), "ran_at": now_iso()}
    cid = user.get("company_id") or DEMO_COMPANY_ID
    s = await backfill_company(db, cid)
    return {**s, "company_id": cid, "performed_by": user.get("email"),
             "ran_at": now_iso()}


class AutoCancelReq(BaseModel):
    days: int = 7


@router.post("/os-lifecycle/auto-cancel-preventive")
async def lifecycle_auto_cancel(payload: AutoCancelReq,
                                 user: dict = Depends(require_role("auditor"))):
    """Cancela preventivas em ready_for_dispatch/assigned há mais de N dias."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    r = await auto_cancel_stale_preventive(db, cid, days=payload.days)
    return {**r, "company_id": cid, "performed_by": user.get("email"),
             "ran_at": now_iso()}


class TransitionReq(BaseModel):
    to_state: str
    reason_code: Optional[str] = None
    notes: Optional[str] = None
    force: bool = False


@router.post("/tickets/{ticket_id}/transition")
async def transition_ticket(ticket_id: str, payload: TransitionReq,
                              user: dict = Depends(require_role("gestor"))):
    """Transita o estado do ticket usando a state machine canônica."""
    if payload.force and not is_super_admin(user):
        raise HTTPException(403, "Apenas super admin pode usar force=true")
    try:
        r = await do_transition(
            db, ticket_id,
            to_state=payload.to_state,
            reason_code=payload.reason_code,
            notes=payload.notes,
            actor={"id": user.get("id"),
                    "name": user.get("name"),
                    "email": user.get("email")},
            force=payload.force,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return r


# =====================================================================
# Health Dashboard — "OSs travadas por estado"
# =====================================================================
@router.get("/os-lifecycle/health")
async def lifecycle_health(user: dict = Depends(require_role("gestor"))):
    """Dashboard de saúde do fluxo: distribuição por estado, idade média,
    breach de SLA, gargalo identificado."""
    cid = user.get("company_id") or DEMO_COMPANY_ID

    # Pega TODOS os tickets ativos (não terminais) do tenant
    active_states = ["draft", "ready_for_dispatch", "assigned", "accepted",
                       "en_route", "in_progress", "pending"]
    cursor = db.tickets.find(
        {"company_id": cid, "lifecycle_state": {"$in": active_states}},
        {"_id": 0, "id": 1, "lifecycle_state": 1, "work_type": 1,
          "lifecycle_reason_code": 1, "lifecycle_updated_at": 1,
          "created_at": 1, "assigned_collaborator_id": 1,
          "atlaz_protocolo": 1, "atlaz_assunto": 1, "description": 1},
    )

    from collections import Counter, defaultdict
    by_state: Counter = Counter()
    by_state_breach: Counter = Counter()
    by_state_warning: Counter = Counter()
    by_state_age: Dict[str, list] = defaultdict(list)
    by_work_type: Counter = Counter()
    breach_tickets: List[dict] = []

    async for t in cursor:
        ls = t.get("lifecycle_state")
        wt = t.get("work_type") or "(none)"
        by_state[ls] += 1
        by_work_type[wt] += 1
        sla = compute_sla_breach(t)
        if sla.get("consumed_minutes") is not None:
            by_state_age[ls].append(sla["consumed_minutes"])
        if sla.get("breach"):
            by_state_breach[ls] += 1
            if len(breach_tickets) < 30:
                breach_tickets.append({
                    "ticket_id": t.get("id"),
                    "lifecycle_state": ls,
                    "work_type": wt,
                    "reason_code": t.get("lifecycle_reason_code"),
                    "atlaz_protocolo": t.get("atlaz_protocolo"),
                    "consumed_minutes": sla["consumed_minutes"],
                    "sla_minutes": sla["sla_minutes"],
                    "percent_used": sla["percent_used"],
                })
        elif sla.get("warning"):
            by_state_warning[ls] += 1

    # Estatísticas por estado
    state_stats = []
    for state_def in LIFECYCLE_STATES:
        k = state_def["key"]
        if k not in active_states:
            continue
        ages = by_state_age.get(k, [])
        avg_age = int(sum(ages) / len(ages)) if ages else 0
        max_age = max(ages) if ages else 0
        state_stats.append({
            "state": k,
            "label": state_def["label"],
            "color": state_def["color"],
            "count": by_state.get(k, 0),
            "breach_count": by_state_breach.get(k, 0),
            "warning_count": by_state_warning.get(k, 0),
            "avg_age_minutes": avg_age,
            "max_age_minutes": max_age,
        })

    # Gargalo: estado com maior count*age (= mais OSs presas há mais tempo)
    gargalo = max(state_stats,
                    key=lambda s: s["count"] * s["avg_age_minutes"],
                    default=None)

    total_active = sum(by_state.values())
    total_breach = sum(by_state_breach.values())

    return {
        "company_id": cid,
        "total_active_tickets": total_active,
        "total_breach": total_breach,
        "breach_percent": round(total_breach / total_active * 100, 1) if total_active else 0,
        "state_stats": state_stats,
        "by_work_type": dict(by_work_type.most_common()),
        "gargalo": {
            "state": gargalo["state"],
            "label": gargalo["label"],
            "count": gargalo["count"],
            "avg_age_minutes": gargalo["avg_age_minutes"],
        } if gargalo else None,
        "breach_tickets": breach_tickets,
        "audited_at": now_iso(),
    }


@router.get("/tickets/{ticket_id}/lifecycle-timeline")
async def lifecycle_timeline(ticket_id: str,
                              user: dict = Depends(require_role("gestor"))):
    """Retorna o histórico de transições + SLA atual do ticket."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    t = await db.tickets.find_one(
        {"id": ticket_id, "company_id": cid},
        {"_id": 0, "id": 1, "lifecycle_state": 1, "work_type": 1,
         "lifecycle_reason_code": 1, "lifecycle_updated_at": 1,
         "lifecycle_history": 1, "status": 1, "type": 1, "created_at": 1},
    )
    if not t:
        raise HTTPException(404, "Ticket não encontrado")
    sla = compute_sla_breach(t)
    return {
        "ticket": t,
        "history": t.get("lifecycle_history") or [],
        "sla": sla,
    }
