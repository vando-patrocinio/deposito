"""
executive_scheduler.py — Sprint 7 / iter226 + pós-CTO leader election
Scheduler autônomo do Presidente IA. APScheduler-based COM
leader-election distribuído (services/scheduler_lock.py).

Roda continuamente em background:
  - 1 min: detectores de segurança (mass_export, mass_delete,
              rbac_abuse, impersonate, collective_outage)
  - 5 min: detectores de negócio (churn_risk, sales_opportunities)
  - 60 min: executive_health_check, data_quality_scan, retention,
              cleanup_old_memory, audit_chain_verify

  - 30 s   : renova lock do leader

Em N workers, APENAS o leader executa os ticks.
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

log = logging.getLogger("presidente_ia.scheduler")

_scheduler = None


async def _renew_lock() -> bool:
    from services.scheduler_lock import renew_leader, try_acquire_leader
    ok = await renew_leader()
    if not ok:
        ok = await try_acquire_leader()
    return ok


async def _is_leader() -> bool:
    from services.scheduler_lock import try_acquire_leader
    return await try_acquire_leader()


async def _tick_1min() -> None:
    """Detectores de segurança + outage coletivo (somente leader)."""
    if not await _is_leader():
        return
    try:
        from services.audit_alerts import scan_security_alerts
        alerts = await scan_security_alerts()
        if alerts:
            log.info("[scheduler] %d alertas de segurança",
                       len(alerts))
    except Exception as e:
        log.exception("scheduler 1min: %s", e)
    # FASE 3 Constituição V3.0 — Sistema Nervoso: sync polling
    try:
        from services.nervous_synchronizer import run_synchronization
        r = await run_synchronization()
        if r.get("emitted_total"):
            log.info("[scheduler] nervous_sync emitiu %d eventos: %s",
                       r["emitted_total"], r.get("per_kind"))
    except Exception as e:
        log.exception("scheduler 1min nervous_sync: %s", e)
    # FASE 7 — Álvaro daily briefings (3x/dia)
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        hour_str = now.strftime("%H")
        if hour_str in ("07", "12", "18") and now.minute == 0:
            from services.alvaro_director import daily_briefing
            from database import db as _db
            companies = await _db.companies.distinct("id")
            kind = {"07": "07h", "12": "12h", "18": "18h"}[hour_str]
            for cid in companies:
                if cid:
                    await daily_briefing(cid, kind=kind)
            log.info("[scheduler] alvaro briefings %s gerados", kind)
    except Exception as e:
        log.exception("scheduler alvaro briefing: %s", e)


async def _tick_5min() -> None:
    """Detectores de negócio + ciclo decisão+ação."""
    if not await _is_leader():
        return
    try:
        from services.executive_health import detect_churn_risk
        await detect_churn_risk()
    except Exception as e:
        log.exception("scheduler 5min churn: %s", e)
    try:
        from services.decision_engine import run_decision_cycle
        from services.action_engine import execute_pending
        d = await run_decision_cycle()
        a = await execute_pending()
        if d["decisions_created"] or a["executed"]:
            log.info("[scheduler] %d decisões / %d ações "
                       "executadas (live=%s)",
                       d["decisions_created"], a["executed"],
                       a["live_mode"])
    except Exception as e:
        log.exception("scheduler 5min decision_engine: %s", e)


async def _tick_1h() -> None:
    """Health check executivo + data quality + retention +
    cleanup memory + audit chain verify + feedback loop snapshot."""
    if not await _is_leader():
        return
    try:
        from services.data_quality import run_scan_all_tenants
        from services.executive_health import (
            compute_executive_score_all_tenants,
        )
        await run_scan_all_tenants()
        await compute_executive_score_all_tenants()
    except Exception as e:
        log.exception("scheduler 1h scan: %s", e)
    try:
        from services.lgpd_chain import apply_retention_now, verify_chain
        deleted = await apply_retention_now()
        if deleted:
            log.info("[scheduler] retention apagou: %s", deleted)
        chk = await verify_chain(limit=5000)
        if chk.get("broken_count"):
            log.warning("[scheduler] AUDIT CHAIN BROKEN: %d quebras",
                          chk["broken_count"])
    except Exception as e:
        log.exception("scheduler 1h retention/chain: %s", e)
    try:
        from services.memory_cleanup import cleanup_old_memory
        c = await cleanup_old_memory()
        if c.get("deleted_total"):
            log.info("[scheduler] cleanup_old_memory: %s", c)
    except Exception as e:
        log.exception("scheduler 1h cleanup: %s", e)
    # Sprint 10/12 — feedback loop snapshot
    try:
        from services.feedback_loop import refresh_stats
        stats = await refresh_stats(force=True)
        if stats:
            log.info("[scheduler] feedback_loop: %d action_types",
                       len(stats))
    except Exception as e:
        log.exception("scheduler 1h feedback_loop: %s", e)


async def _tick_6h() -> None:
    """Sprint 11 — predictions (churn/revenue/ticket_demand)."""
    if not await _is_leader():
        return
    try:
        from services.predictions import run_all_predictions
        out = await run_all_predictions()
        log.info("[scheduler] predictions geradas: churn=%s rev=%s "
                   "tkt=%s",
                   (out.get("churn") or {}).get("count"),
                   len((out.get("revenue") or {}).get("items") or []),
                   len((out.get("ticket_demand") or {})
                         .get("items") or []))
    except Exception as e:
        log.exception("scheduler 6h predictions: %s", e)


def start_scheduler() -> None:
    """Inicializa APScheduler. Idempotente.

    Em N workers, todos chamam start_scheduler — o leader-election
    via Mongo lock (`scheduler_lock.py`) garante que só UM executa
    os jobs por vez.
    """
    global _scheduler
    if _scheduler is not None:
        return
    if os.environ.get("SKIP_STARTUP_JOBS"):
        log.info("[scheduler] SKIP_STARTUP_JOBS=1 — não inicia")
        return
    if os.environ.get("DISABLE_EXEC_SCHEDULER"):
        log.info("[scheduler] DISABLE_EXEC_SCHEDULER=1 — desativado")
        return
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        sch = AsyncIOScheduler(timezone="UTC")
        # renovação de lock a cada 20s
        sch.add_job(_renew_lock, "interval", seconds=20,
                       id="renew_lock", max_instances=1, coalesce=True)
        sch.add_job(_tick_1min, "interval", minutes=1,
                       id="exec_1min", max_instances=1, coalesce=True)
        sch.add_job(_tick_5min, "interval", minutes=5,
                       id="exec_5min", max_instances=1, coalesce=True)
        sch.add_job(_tick_1h, "interval", hours=1,
                       id="exec_1h", max_instances=1, coalesce=True)
        sch.add_job(_tick_6h, "interval", hours=6,
                       id="exec_6h_predictions",
                       max_instances=1, coalesce=True)
        sch.start()
        _scheduler = sch
        log.info("[scheduler] Executivo digital ATIVO "
                  "(20s renew, 1min/5min/1h/6h jobs) — "
                  "leader-election ON, predictions ON")
    except Exception as e:
        log.exception("[scheduler] falha ao iniciar: %s", e)
