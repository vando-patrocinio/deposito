"""sprint5_onda1 — Recuperação de Rastreabilidade (CEO mandate 19/02/2026)

Endpoints:
  GET  /api/sprint5/onda1/status              — métricas atuais
  GET  /api/sprint5/onda1/preview             — dry-run backfill
  POST /api/sprint5/onda1/backfill-orphans    — aplica backfill
  GET  /api/sprint5/onda1/certidao            — certidão markdown
  GET  /api/sprint5/onda1/audit-log           — trilha por batch
"""

NERVOUS_METADATA = {
    "owner": "infra-team",
    "domain": "patrimonio",
    "criticality": "critical",
    "emits_events": True,
    "event_types": ["sprint5.onda1.backfill"],
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core import require_role
from database import db
from services.stok_history_writer import backfill_orphan_events

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sprint5/onda1", tags=["sprint5", "onda1"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_company(user: dict) -> str:
    cid = user.get("company_id")
    if not cid:
        raise HTTPException(400, "Usuário sem company_id")
    return cid


async def _compute_status(cid: str) -> Dict[str, Any]:
    total = await db.stok_history.count_documents({"company_id": cid})
    with_ticket = await db.stok_history.count_documents(
        {"company_id": cid,
         "ticket_id": {"$exists": True, "$nin": [None, ""]}})
    with_service = await db.stok_history.count_documents(
        {"company_id": cid,
         "service_id": {"$exists": True, "$nin": [None, ""]}})
    with_collab = await db.stok_history.count_documents(
        {"company_id": cid,
         "collaborator_id": {"$exists": True, "$nin": [None, ""]}})
    with_sub = await db.stok_history.count_documents(
        {"company_id": cid,
         "subscriber_id": {"$exists": True, "$nin": [None, ""]}})
    with_type = await db.stok_history.count_documents(
        {"company_id": cid,
         "event_type": {"$exists": True, "$nin": [None, ""]}})
    with_ts = await db.stok_history.count_documents(
        {"company_id": cid,
         "event_timestamp": {"$exists": True, "$nin": [None, ""]}})

    full_5of5 = await db.stok_history.count_documents({
        "company_id": cid,
        "ticket_id": {"$exists": True, "$nin": [None, ""]},
        "service_id": {"$exists": True, "$nin": [None, ""]},
        "collaborator_id": {"$exists": True, "$nin": [None, ""]},
        "subscriber_id": {"$exists": True, "$nin": [None, ""]},
        "event_type": {"$exists": True, "$nin": [None, ""]},
    })

    # CEO 19/02/2026 — cobertura efetiva considera eventos NON-OS como OK
    # (compras/transferências não exigem ticket_id por natureza).
    non_os_ok = await db.stok_history.count_documents({
        "company_id": cid,
        "traceability_status": "non_os_required",
        "event_type": {"$exists": True, "$nin": [None, ""]},
        "event_timestamp": {"$exists": True, "$nin": [None, ""]},
    })
    partial_with_service = await db.stok_history.count_documents({
        "company_id": cid,
        "traceability_status": {"$in": ["partial", "partial_os_not_found"]},
        "service_id": {"$exists": True, "$nin": [None, ""]},
    })
    traceable_effective = full_5of5 + non_os_ok + partial_with_service

    def pct(n):
        return round((n / total * 100.0), 2) if total else 0.0

    return {
        "company_id": cid,
        "total_events": total,
        "with_ticket_id": with_ticket,
        "with_service_id": with_service,
        "with_collaborator_id": with_collab,
        "with_subscriber_id": with_sub,
        "with_event_type": with_type,
        "with_event_timestamp": with_ts,
        "fully_traceable_5of5": full_5of5,
        "non_os_ok": non_os_ok,
        "partial_with_service": partial_with_service,
        "traceable_effective": traceable_effective,
        "coverage_ticket_pct": pct(with_ticket),
        "coverage_service_pct": pct(with_service),
        "coverage_collab_pct": pct(with_collab),
        "coverage_subscriber_pct": pct(with_sub),
        "coverage_event_type_pct": pct(with_type),
        "coverage_full_5of5_pct": pct(full_5of5),
        "coverage_effective_pct": pct(traceable_effective),
        "gate_95pct": pct(traceable_effective) >= 95.0,
        "computed_at": _now_iso(),
    }


async def _audit(batch_id: str, cid: str, action: str,
                 target: str, payload: dict, user: dict) -> None:
    try:
        await db.sprint5_audit_log.insert_one({
            "id": f"o1a-{uuid.uuid4().hex[:14]}",
            "batch_id": batch_id,
            "company_id": cid,
            "wave": "sprint5_onda1",
            "action": action,
            "target": target,
            "payload": payload,
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "created_at": _now_iso(),
        })
    except Exception as e:
        logger.warning("[onda1.audit] %s", e)


@router.get("/status")
async def status(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    return await _compute_status(cid)


@router.get("/preview")
async def preview(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    batch_id = f"o1b-preview-{uuid.uuid4().hex[:10]}"
    before = await _compute_status(cid)
    plan = await backfill_orphan_events(
        db, cid, batch_id=batch_id, dry_run=True)
    return {
        "mode": "preview",
        "before": before,
        "plan": plan,
        "computed_at": _now_iso(),
    }


@router.post("/backfill-orphans")
async def backfill(
    dry_run: bool = Query(False),
    user: dict = Depends(require_role("administrador", "gestor")),
):
    cid = _user_company(user)
    batch_id = f"o1b-{uuid.uuid4().hex[:14]}"
    before = await _compute_status(cid)
    result = await backfill_orphan_events(
        db, cid, batch_id=batch_id, dry_run=dry_run)
    after = await _compute_status(cid)

    if not dry_run:
        await _audit(
            batch_id, cid, "backfill.completed",
            f"stok_history/{batch_id}",
            {"before": before, "after": after, "result": result},
            user,
        )
    return {
        "batch_id": batch_id,
        "dry_run": dry_run,
        "mode": "preview" if dry_run else "applied",
        "before": {
            "total": before["total_events"],
            "coverage_full_5of5_pct": before["coverage_full_5of5_pct"],
        },
        "after": {
            "total": after["total_events"],
            "coverage_full_5of5_pct": after["coverage_full_5of5_pct"],
        },
        "result": result,
        "completed_at": _now_iso(),
    }


@router.get("/audit-log")
async def audit_log(
    batch_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    q: Dict[str, Any] = {"company_id": cid, "wave": "sprint5_onda1"}
    if batch_id:
        q["batch_id"] = batch_id
    items = await db.sprint5_audit_log.find(
        q, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(
        length=limit)
    return {"items": items, "count": len(items)}


@router.get("/certidao")
async def certidao(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    """Retorna certidão em formato dict (JSON) com os números atuais."""
    cid = _user_company(user)
    st = await _compute_status(cid)
    # último batch aplicado
    last_batch = await db.sprint5_audit_log.find_one(
        {"company_id": cid, "wave": "sprint5_onda1",
         "action": "backfill.completed"},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    return {
        "certidao_type": "SPRINT5_ONDA1",
        "company_id": cid,
        "metrics": st,
        "last_backfill_batch": last_batch,
        "gate_95pct_atingido": st["gate_95pct"],
        "issued_at": _now_iso(),
    }
