"""sala_orphan_health.py — rota admin do health check de órfãos."""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "sala_routing",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from fastapi import APIRouter, Depends

from core import require_role
from database import db
from services.sala_orphan_health import run_orphan_health_check

router = APIRouter(prefix="/api/admin/sala-orphan-health", tags=["sala-orphan-health"])


@router.get("/status")
async def get_status(_: dict = Depends(require_role("auditor"))):
    """Último relatório + contagem atual."""
    last = await db.sala_orphan_health.find_one({}, {"_id": 0}, sort=[("executed_at", -1)])
    current = await db.tickets.count_documents({
        "$or": [
            {"assigned_collaborator_id": None},
            {"assigned_collaborator_id": {"$exists": False}},
            {"assigned_collaborator_id": ""},
        ],
        "status": {"$ne": "closed"},
    })
    return {"last_report": last, "current_orphans": current}


@router.post("/run-now")
async def run_now(_: dict = Depends(require_role("auditor"))):
    """Dispara o health check imediatamente (não espera o cron)."""
    return await run_orphan_health_check()


@router.get("/history")
async def history(limit: int = 20, _: dict = Depends(require_role("auditor"))):
    rows = await db.sala_orphan_health.find({}, {"_id": 0}).sort("executed_at", -1).to_list(int(limit))
    return {"history": rows, "count": len(rows)}
