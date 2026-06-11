"""
autonomy_scheduler.py — Sprint final V5.0
APScheduler que dispara:
  - a cada 30min: drive/overdue + drive/churn + drive/onu-degraded
  - 07h: briefing executivo
  - 12h: alerta operacional
  - 18h: fechamento executivo
  - a cada 4h: reconcile_all_recent
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import os
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

log = logging.getLogger("autonomy_scheduler")
_scheduler: AsyncIOScheduler | None = None


def _company_id() -> str:
    return os.environ.get("AUTONOMY_DEFAULT_COMPANY", "co-demo")


async def _run_drives() -> Any:
    from services import autonomous_engine as eng
    co = _company_id()
    try:
        a = await eng.drive_from_overdue(co, limit=5)
        b = await eng.drive_from_isabella_churn(co, limit=5)
        c = await eng.drive_from_onu_degraded(co, limit=5)
        log.info("[scheduler] drives ok: ov=%d churn=%d onu=%d",
                  len(a), len(b), len(c))
    except Exception as e:  # noqa: BLE001
        log.warning("[scheduler] drives fail: %s", e)


async def _run_reconcile() -> Any:
    from services import reconcile_worker as rec
    try:
        r = await rec.reconcile_all_recent(_company_id(), hours=168)
        log.info("[scheduler] reconcile ok: %d", r.get("reconciled", 0))
    except Exception as e:  # noqa: BLE001
        log.warning("[scheduler] reconcile fail: %s", e)


async def _dispatch_briefing(slot: str) -> Any:
    from services import briefing_dispatcher as bd
    try:
        r = await bd.dispatch(_company_id(), slot=slot)
        log.info("[scheduler] briefing %s status=%s",
                  slot, r.get("delivery_status"))
    except Exception as e:  # noqa: BLE001
        log.warning("[scheduler] briefing %s fail: %s", slot, e)


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    if os.environ.get("AUTONOMY_SCHEDULER_DISABLED", "0") == "1":
        log.info("[scheduler] disabled by env")
        return
    _scheduler = AsyncIOScheduler(
        timezone="America/Sao_Paulo",
        # P0.4 A4 — Hardening idêntico ao scheduler principal (server.py).
        # Sem alterar horários nem frequência dos jobs.
        job_defaults={
            "misfire_grace_time": 3600,
            "coalesce": True,
            "max_instances": 1,
        },
    )
    # Drives a cada 30 minutos
    _scheduler.add_job(_run_drives, IntervalTrigger(minutes=30),
                        id="drives_30m", replace_existing=True,
                        max_instances=1)
    # Reconcile a cada 4h
    _scheduler.add_job(_run_reconcile, IntervalTrigger(hours=4),
                        id="reconcile_4h", replace_existing=True,
                        max_instances=1)
    # Briefings 07/12/18
    _scheduler.add_job(_dispatch_briefing,
                        CronTrigger(hour=7, minute=0),
                        kwargs={"slot": "07h"},
                        id="briefing_07h", replace_existing=True)
    _scheduler.add_job(_dispatch_briefing,
                        CronTrigger(hour=12, minute=0),
                        kwargs={"slot": "12h"},
                        id="briefing_12h", replace_existing=True)
    _scheduler.add_job(_dispatch_briefing,
                        CronTrigger(hour=18, minute=0),
                        kwargs={"slot": "18h"},
                        id="briefing_18h", replace_existing=True)
    _scheduler.start()
    log.info("[scheduler] STARTED: drives/30m, reconcile/4h, "
              "briefings 07/12/18")


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def status() -> dict:
    if _scheduler is None:
        return {"running": False, "jobs": []}
    return {
        "running": _scheduler.running,
        "jobs": [
            {"id": j.id, "next_run": str(j.next_run_time),
              "trigger": str(j.trigger)}
            for j in _scheduler.get_jobs()
        ],
    }
