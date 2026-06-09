"""nervous_full_coverage_job.py

Job APScheduler que mantém a cobertura do Sistema Nervoso em 100%
emitindo continuamente os eventos derivados ("synthesized") cujo
mapeamento não pode ser feito por simples polling de coleções
(VLAN saturada, CTO degradada/critical, outage coletivo, técnico
atrasado, queda de produtividade, etc.).

Reusa scripts.nervous_full_coverage_bootstrap.run() — sem código duplicado.
Executado a cada 1h pelo APScheduler global. Idempotente.
"""
from __future__ import annotations

import logging
from typing import Dict, Any

log = logging.getLogger("nervous_coverage_job")


async def refresh_synthesized_events() -> Dict[str, Any]:
    """Re-emite eventos synthesized para todos tenants ativos."""
    from database import db
    from scripts.nervous_full_coverage_bootstrap import (
        emit_vlan_saturated,
        emit_cto_degraded_critical,
        emit_collective_outage,
        emit_client_status,
        emit_technician_late,
        emit_gps_route_deviation,
        emit_tech_productivity_drop,
        emit_dunning_escalated,
        emit_ticket_recurring,
        emit_wa_campaign_sent,
    )

    tenants = await db.subscribers.distinct("company_id")
    out: Dict[str, Any] = {}
    for cid in tenants:
        if not cid:
            continue
        result = {}
        try:
            result["vlan.saturated"] = await emit_vlan_saturated(cid)
            deg, crit = await emit_cto_degraded_critical(cid)
            result["cto.degraded"] = deg
            result["cto.critical"] = crit
            result["collective_outage"] = await emit_collective_outage(cid)
            off, on = await emit_client_status(cid)
            result["client.offline"] = off
            result["client.online"] = on
            result["technician.late"] = await emit_technician_late(cid)
            result["gps.route_deviation"] = await emit_gps_route_deviation(cid)
            result["tech.productivity_drop"] = (
                await emit_tech_productivity_drop(cid))
            result["dunning.escalated"] = await emit_dunning_escalated(cid)
            result["ticket.recurring"] = await emit_ticket_recurring(cid)
            result["wa.campaign_sent"] = await emit_wa_campaign_sent(cid)
        except Exception as e:  # noqa: BLE001
            log.warning("[nervous_coverage_job] tenant=%s err=%r", cid, e)
            result["error"] = repr(e)[:200]
        out[cid] = result
    total = sum(
        v if isinstance(v, int) else 0
        for tenant in out.values() for v in tenant.values())
    log.info("[nervous_coverage_job] refresh done: %d eventos", total)
    return {"total": total, "by_tenant": out}


def register(scheduler) -> None:
    """Registra o job no APScheduler global. Idempotente."""
    job_id = "nervous_full_coverage_1h"
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    scheduler.add_job(
        refresh_synthesized_events,
        "interval",
        hours=1,
        id=job_id,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    log.info("[nervous_coverage_job] registered (1h interval)")
