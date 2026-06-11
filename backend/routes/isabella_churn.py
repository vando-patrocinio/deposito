"""Rota admin do conversor Isabella churn → SALA."""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "retention",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from fastapi import APIRouter, Depends

from core import require_role
from database import db
from services.isabella_churn_to_sala import (
    CHURN_THRESHOLD, MAX_PER_RUN, run_churn_to_sala,
)

router = APIRouter(prefix="/api/admin/isabella-churn", tags=["isabella-churn"])


@router.get("/status")
async def status(_: dict = Depends(require_role("auditor"))):
    """Último relatório + estatísticas atuais."""
    last = await db.isabella_churn_runs.find_one(
        {}, {"_id": 0}, sort=[("executed_at", -1)],
    )
    candidates_now = await db.subscribers.count_documents({
        "churn_score": {"$gte": CHURN_THRESHOLD},
        "status": {"$in": ["ATIVO", "ATIVA", "ATIVADO", "active"]},
    })
    retention_open = await db.tickets.count_documents({
        "category": "RETENTION",
        "status": {"$nin": ["closed", "cancelado", "encerrado"]},
    })
    return {
        "candidates_now": candidates_now,
        "retention_tickets_open": retention_open,
        "config": {
            "threshold": CHURN_THRESHOLD,
            "max_per_run": MAX_PER_RUN,
        },
        "last_report": last,
    }


@router.post("/run-now")
async def run_now(_: dict = Depends(require_role("auditor"))):
    """Dispara o job imediatamente (não espera o cron)."""
    return await run_churn_to_sala()


@router.get("/history")
async def history(limit: int = 20, _: dict = Depends(require_role("auditor"))):
    rows = await db.isabella_churn_runs.find({}, {"_id": 0}).sort(
        "executed_at", -1
    ).to_list(int(limit))
    return {"history": rows, "count": len(rows)}
