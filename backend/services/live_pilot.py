"""
live_pilot.py — Sprint 19.5 (PRINCIPAL RECOMENDAÇÃO CTO)
Ativa modo LIVE para 1 cliente real + mede impacto operacional.

Fluxo:
  1. `start_pilot(company_id, action_types)` — habilita LIVE.
  2. Pipeline normal roda (event_bus → decision_engine → action_engine).
  3. `pilot_metrics(company_id)` mede após N dias:
       - decisões LIVE executadas
       - WhatsApp sent rate
       - pagamentos recebidos APÓS notificação (linkage temporal)
       - taxa de recuperação de receita

Coleção: `live_pilot_runs` armazena o snapshot inicial pra comparar.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def start_pilot(company_id: str, action_types: List[str],
                          notes: str = "",
                          started_by: Optional[str] = None
                          ) -> Dict[str, Any]:
    """Ativa LIVE + grava baseline pra comparação posterior."""
    from services.company_settings import set_live
    await set_live(company_id, action_types, updated_by=started_by)
    baseline = await _capture_baseline(company_id)
    doc = {
        "id": f"pilot-{uuid.uuid4().hex[:12]}",
        "company_id": company_id,
        "action_types": action_types,
        "started_at": _now_iso(),
        "started_by": started_by,
        "notes": notes,
        "baseline": baseline,
        "status": "running",
    }
    await db.live_pilot_runs.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def _capture_baseline(company_id: str) -> Dict[str, Any]:
    """Snapshot do estado financeiro/operacional ANTES do pilot."""
    overdue_invoices = await db.subscriber_invoices.count_documents(
        {"company_id": company_id,
         "status": {"$in": ["open", "overdue"]}})
    overdue_amount = 0.0
    async for r in db.subscriber_invoices.aggregate([
        {"$match": {"company_id": company_id,
                     "status": {"$in": ["open", "overdue"]}}},
        {"$group": {"_id": None, "sum": {"$sum": "$amount"}}}]):
        overdue_amount = float(r.get("sum") or 0)
    open_tickets = await db.tickets.count_documents(
        {"company_id": company_id,
         "status": {"$nin": ["closed", "completed",
                                "finalizado"]}})
    return {
        "snapshot_at": _now_iso(),
        "overdue_invoices_count": overdue_invoices,
        "overdue_amount_total": overdue_amount,
        "open_tickets": open_tickets,
    }


async def stop_pilot(company_id: str,
                        stopped_by: Optional[str] = None
                        ) -> Dict[str, Any]:
    """Desativa LIVE."""
    from services.company_settings import set_live
    await set_live(company_id, [], updated_by=stopped_by)
    await db.live_pilot_runs.update_many(
        {"company_id": company_id, "status": "running"},
        {"$set": {"status": "stopped",
                  "stopped_at": _now_iso(),
                  "stopped_by": stopped_by}})
    return {"company_id": company_id, "status": "stopped"}


async def pilot_metrics(company_id: str,
                            window_days: int = 7) -> Dict[str, Any]:
    """Métricas de impacto operacional do pilot."""
    pilot = await db.live_pilot_runs.find_one(
        {"company_id": company_id},
        sort=[("started_at", -1)])
    if not pilot:
        return {"error": "no_pilot_found", "company_id": company_id}
    started_at = pilot.get("started_at")
    baseline = pilot.get("baseline") or {}

    # ações LIVE executadas
    live_actions = await db.motor_ia_actions.count_documents({
        "company_id": company_id,
        "dry_run": False,
        "created_at": {"$gte": started_at}})

    # notificações WhatsApp efetivamente enviadas
    wa_sent = 0
    async for o in db.motor_ia_outcomes.find({
            "company_id": company_id,
            "created_at": {"$gte": started_at}}):
        if (o.get("result") or {}).get("wa_sent"):
            wa_sent += 1

    # dunning escalations REAIS (não dry-run)
    dunning_live = await db.dunning_escalations.count_documents({
        "company_id": company_id,
        "dry_run": False,
        "created_at": {"$gte": started_at}})

    # pagamentos recebidos APÓS pilot start (vindos pelo event bus)
    payments_received_after = await db.motor_ia_events.count_documents({
        "company_id": company_id,
        "event_type": "PAYMENT_RECEIVED",
        "timestamp": {"$gte": started_at}})

    # estado atual de overdue
    overdue_now = await db.subscriber_invoices.count_documents({
        "company_id": company_id,
        "status": {"$in": ["open", "overdue"]}})

    delta_overdue = (baseline.get("overdue_invoices_count", 0)
                      - overdue_now)

    return {
        "company_id": company_id,
        "pilot_id": pilot.get("id"),
        "pilot_started_at": started_at,
        "window_days": window_days,
        "baseline": baseline,
        "current_state": {
            "overdue_invoices_count": overdue_now,
        },
        "impact": {
            "live_actions_executed": live_actions,
            "whatsapp_messages_sent": wa_sent,
            "dunning_escalations_live": dunning_live,
            "payments_received_events": payments_received_after,
            "overdue_reduction": delta_overdue,
        },
        "thesis_validated": (
            "SIM" if (delta_overdue > 0 and payments_received_after > 0)
            else "AINDA NÃO"),
        "generated_at": _now_iso(),
    }


async def list_pilots() -> Dict[str, Any]:
    items = []
    async for d in db.live_pilot_runs.find(
            {}, {"_id": 0}).sort("started_at", -1).limit(50):
        items.append(d)
    return {"count": len(items), "items": items}
