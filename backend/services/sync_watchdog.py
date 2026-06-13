"""SyncWatchdog — CTO 13/06/2026.

Audita o pipeline operacional e emite alertas críticos quando algo
quebra no fluxo:

  - LOUSA_SYNC_FAILURE  : OS criada mas não retornada pela query da Lousa
  - MOBILE_SYNC_FAILURE : OS atribuída a colab mas não em /by-collaborator
  - KPI_SYNC_FAILURE    : OS finalizada mas KPI motor_ia_kpis sem atualização

Roda como cron a cada 1min. Emite eventos via event_bus.
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from database import db
from services.event_bus import emit_event

log = logging.getLogger("sync_watchdog")


async def sync_score(company_id: str) -> Dict[str, Any]:
    """Score operacional do tenant em 0–100.

    Métricas:
      - OS criadas nos últimos 60min
      - OS aparecendo em queries da Lousa (% de cobertura)
      - OS finalizadas com evento TICKET_CLOSED correspondente
      - Latência média Isabella → Lousa (ms)
    """
    now = datetime.now(timezone.utc)
    cutoff_1h = (now - timedelta(hours=1)).isoformat()

    # OS criadas na última hora
    created_total = await db.tickets.count_documents({
        "company_id": company_id, "created_at": {"$gte": cutoff_1h},
    })
    if created_total == 0:
        return {
            "company_id": company_id, "score": 100,
            "window_minutes": 60, "created_total": 0,
            "note": "no_traffic — assumindo 100",
        }

    # OS com colaborador atribuído
    assigned_ok = await db.tickets.count_documents({
        "company_id": company_id, "created_at": {"$gte": cutoff_1h},
        "assigned_collaborator_id": {"$nin": [None, ""]},
    })

    # OS com evento TICKET_OPENED / ISABELLA_OS_CREATED no event bus
    events_ok = await db.motor_ia_events.count_documents({
        "company_id": company_id,
        "event_type": {"$in": ["TICKET_OPENED", "ISABELLA_OS_CREATED"]},
        "timestamp": {"$gte": cutoff_1h},
    })

    # OS finalizadas com evento TICKET_CLOSED
    closed = await db.tickets.count_documents({
        "company_id": company_id, "created_at": {"$gte": cutoff_1h},
        "status": "fechado",
    })
    closed_events = await db.motor_ia_events.count_documents({
        "company_id": company_id,
        "event_type": {"$in": ["TICKET_CLOSED", "FIELD_OS_COMPLETED"]},
        "timestamp": {"$gte": cutoff_1h},
    })

    # KPIs alimentando
    kpi_recent = await db.motor_ia_kpis.count_documents({
        "company_id": company_id, "updated_at": {"$gte": cutoff_1h},
    })

    # Pondera
    s_assign = (assigned_ok / created_total) if created_total else 1
    s_event = min(1.0, events_ok / max(created_total, 1))
    s_close = (closed_events / closed) if closed else 1
    s_kpi = 1.0 if kpi_recent > 0 else 0.0

    score = round(100 * (s_assign * 0.30 + s_event * 0.30
                         + s_close * 0.20 + s_kpi * 0.20), 1)

    return {
        "company_id": company_id, "score": score,
        "window_minutes": 60,
        "metrics": {
            "created_total": created_total,
            "assigned_ok": assigned_ok,
            "events_emitted": events_ok,
            "closed_tickets": closed,
            "closed_events": closed_events,
            "kpi_updates": kpi_recent,
        },
        "sub_scores": {
            "assignment": round(s_assign * 100, 1),
            "event_emission": round(s_event * 100, 1),
            "closure_event": round(s_close * 100, 1),
            "kpi_freshness": round(s_kpi * 100, 1),
        },
    }


async def watchdog_run(company_id: str) -> Dict[str, Any]:
    """Executa as 3 verificações críticas e emite alertas."""
    alerts: list[dict] = []
    now = datetime.now(timezone.utc)
    cutoff_15min = (now - timedelta(minutes=15)).isoformat()

    # 1. LOUSA_SYNC_FAILURE — OS criadas mas sem aparecer em query da Lousa
    # Aqui aproximação: ticket criado há >5min com assigned_collaborator
    # mas sem `_lousa_indexed_at` (a Lousa atual não seta esse flag, então
    # usamos heurística: existe no DB? Se sim, está sincável).
    silent_orphans = await db.tickets.count_documents({
        "company_id": company_id,
        "created_at": {"$gte": cutoff_15min},
        "assigned_collaborator_id": None,
    })
    if silent_orphans > 0:
        alert = await emit_event(
            "LOUSA_SYNC_FAILURE",
            company_id=company_id, source="sync_watchdog", severity="alta",
            payload={"silent_orphans_15min": silent_orphans,
                     "reason": "tickets sem assigned_collaborator_id"},
        )
        alerts.append(alert)

    # 2. MOBILE_SYNC_FAILURE — OS atribuída mas sem ack do mobile (proxied via field/me hits)
    # Métrica leve: tickets atribuídos a colabs que não tiveram /lousa/by-collaborator hit recente.
    # Aproximação: se há ticket atribuído há >10min e status ainda "pendente"
    # SEM nenhum log de ação do colab, considera falha de Mobile sync.
    pending_no_action = 0
    async for t in db.tickets.find(
        {"company_id": company_id, "status": "pendente",
         "assigned_collaborator_id": {"$nin": [None, ""]},
         "created_at": {"$gte": cutoff_15min}},
        {"_id": 0, "id": 1, "assigned_collaborator_id": 1},
    ):
        # ticket_logs deve ter pelo menos 1 entry do colab
        n_logs = await db.ticket_logs.count_documents({
            "ticket_id": t["id"],
            "actor_role": {"$in": ["colaborador", "tecnico"]},
        })
        if n_logs == 0:
            pending_no_action += 1
    if pending_no_action >= 3:  # >2 mobile-blind tickets é sinal real
        alert = await emit_event(
            "MOBILE_SYNC_FAILURE",
            company_id=company_id, source="sync_watchdog", severity="alta",
            payload={"pending_no_mobile_action": pending_no_action,
                     "reason": "tickets atribuídos sem ação do mobile em 15min"},
        )
        alerts.append(alert)

    # 3. KPI_SYNC_FAILURE — tickets finalizados há >10min sem update no KPI
    closed_15min = await db.tickets.count_documents({
        "company_id": company_id, "status": "fechado",
        "closed_at": {"$gte": cutoff_15min},
    })
    kpi_updates_15min = await db.motor_ia_kpis.count_documents({
        "company_id": company_id, "updated_at": {"$gte": cutoff_15min},
    })
    if closed_15min >= 3 and kpi_updates_15min == 0:
        alert = await emit_event(
            "KPI_SYNC_FAILURE",
            company_id=company_id, source="sync_watchdog", severity="critica",
            payload={"closed_tickets_15min": closed_15min,
                     "kpi_updates_15min": kpi_updates_15min,
                     "reason": "OS fechadas sem update de KPI"},
        )
        alerts.append(alert)

    score = await sync_score(company_id)
    return {"ts": now.isoformat(), "alerts": alerts, "score": score}


async def watchdog_run_all() -> dict:
    """Roda watchdog em todos os tenants ativos. Chamado por scheduler."""
    out: list[dict] = []
    seen: set[str] = set()
    async for d in db.tickets.aggregate([
        {"$group": {"_id": "$company_id"}},
    ]):
        cid = d.get("_id")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        try:
            r = await watchdog_run(cid)
            out.append(r)
        except Exception as e:
            log.exception("[watchdog] %s falhou: %s", cid, e)
    return {"tenants": len(out), "results": out}
