"""scheduler_v51.py — APScheduler job 30min (Fase 3).

drive_from_failure_risk com delta analysis para evitar reprocessamento.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger("ops.scheduler_v51")


async def run_failure_risk_cycle(company_ids=None):
    """Roda failure_risk drive com only_changed=True (delta)."""
    from database import db
    from services import failure_risk
    if company_ids is None:
        company_ids = await db.subscribers.distinct("company_id")
    out = {}
    for cid in company_ids:
        if not cid:
            continue
        try:
            r = await failure_risk.drive_from_failure_risk(
                cid, limit=200, only_changed=True)
            out[cid] = r
        except Exception as e:  # noqa: BLE001
            logger.warning("V5.1 scheduler err co=%s: %r", cid, e)
            out[cid] = {"error": str(e)}
    logger.info("V5.1 scheduler tick: %d companies processed", len(out))
    return out


def start_scheduler(scheduler) -> None:
    """Registra o job no APScheduler global. Idempotente."""
    job_id = "v51_failure_risk_drive_30min"
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass

    # AsyncIOScheduler suporta coroutines nativamente — passar direto
    # evita o "Future attached to a different loop" do executor de thread.
    scheduler.add_job(run_failure_risk_cycle, "interval", minutes=30,
                      id=job_id, max_instances=1,
                      coalesce=True, replace_existing=True)
    logger.info("V5.1 scheduler job registered (30min).")
