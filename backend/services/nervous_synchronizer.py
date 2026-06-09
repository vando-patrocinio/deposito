"""
nervous_synchronizer.py — FASE 3 da Constituição V3.0
Sistema Nervoso 90% via SYNCHRONIZER POLLING.

Por que polling e não change streams?
  - Cluster Mongo atual é standalone (sem replica set).
  - Polling roda no APScheduler a cada 60s.

Por que não plugar emit_business em 50 rotas?
  - Invasivo. Risco alto de quebrar fluxos legados.
  - Coleções já têm `created_at`/`updated_at` → checkpoint-based scan
    cobre 100% dos eventos sem tocar uma linha das rotas.

Como funciona:
  1. Mantém em `nervous_checkpoints` o último `created_at` visto por
     (coleção, kind).
  2. Roda no scheduler de 1min: para cada (coleção, kind), busca docs
     novos desde o checkpoint, emite `emit_business(kind=...)` para cada,
     e atualiza o checkpoint.
  3. Idempotente. Pode rodar paralelamente em N pods (leader election
     já existe).

Mapeamento de coleções → eventos (FASE 3 Constituição):
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from database import db
from services.event_emitters import emit_business

log = logging.getLogger("nervous_sync")


# Cada entrada: collection → (ts_field, kind, filter_extra, payload_keys)
# Filtros calibrados conforme schemas REAIS observados em co-demo.
SYNC_PLAN: List[Dict[str, Any]] = [
    # ---- COMERCIAL ----
    {
        "collection": "sales_leads",
        "ts": "ts",
        "kind": "sale.created",
        "filter": {},
        "payload": ["id", "phone", "source", "status"],
        "severity": "media",
    },
    {
        "collection": "sales_leads",
        "ts": "updated_at",
        "kind": "sale.converted",
        "filter": {"status": {"$in": ["contacted", "installed", "won"]}},
        "payload": ["id", "phone", "source"],
        "severity": "alta",
    },
    # ---- INSTALAÇÕES ----
    # No co-demo, appointments traz "reason"="Instalação" + status="scheduled"
    {
        "collection": "appointments",
        "ts": "created_at",
        "kind": "install.scheduled",
        "filter": {"status": {"$in": ["scheduled", "agendado"]}},
        "payload": ["id", "subscriber_id", "subscriber_name", "date"],
    },
    # Tickets do tipo Instalação/instalacao traduzem para install.completed
    {
        "collection": "tickets",
        "ts": "closed_at",
        "kind": "install.completed",
        "filter": {"type": {"$in": ["Instalação", "instalacao"]},
                    "status": {"$in": ["encerrada", "finalizada"]}},
        "payload": ["id", "client_id", "type"],
        "severity": "alta",
    },
    {
        "collection": "tickets",
        "ts": "closed_at",
        "kind": "install.failed",
        "filter": {"type": {"$in": ["Instalação", "instalacao"]},
                    "outcome": {"$regex": "falh|cancel|fail", "$options": "i"}},
        "payload": ["id", "client_id", "outcome"],
        "severity": "alta",
    },
    # ---- FINANCEIRO ----
    {
        "collection": "subscriber_invoices",
        "ts": "created_at",
        "kind": "invoice.created",
        "filter": {},
        "payload": ["id", "subscriber_external_id", "amount", "due_date"],
    },
    {
        "collection": "subscriber_invoices",
        "ts": "paid_date",
        "kind": "invoice.paid",
        "filter": {"status": "paid"},
        "payload": ["id", "subscriber_external_id", "amount_paid"],
        "severity": "alta",
    },
    {
        "collection": "subscriber_invoices",
        "ts": "synced_at",
        "kind": "invoice.overdue",
        "filter": {"status": "overdue"},
        "payload": ["id", "subscriber_external_id", "amount", "due_date"],
        "severity": "alta",
    },
    # payment_transactions é a futura referência — vazia hoje no co-demo
    {
        "collection": "fin_cash_movements",
        "ts": "created_at",
        "kind": "payment.received",
        "filter": {"kind": {"$in": ["income", "in", "credit"]}},
        "payload": ["id", "amount", "category"],
        "severity": "alta",
    },
    # ---- ATENDIMENTO ----
    {
        "collection": "tickets",
        "ts": "opened_at",
        "kind": "ticket.opened",
        "filter": {},
        "payload": ["id", "client_id", "type", "priority"],
    },
    {
        "collection": "tickets",
        "ts": "closed_at",
        "kind": "ticket.closed",
        "filter": {"status": {"$in": ["encerrada", "finalizada",
                                          "closed", "completed"]}},
        "payload": ["id", "client_id"],
    },
    {
        "collection": "ticket_logs",
        "ts": "created_at",
        "kind": "ticket.reopened",
        "filter": {"action": {"$regex": "reopen|reabr", "$options": "i"}},
        "payload": ["ticket_id"],
    },
    # ---- WHATSAPP ----
    {
        "collection": "aihub_wa_messages",
        "ts": "created_at",
        "kind": "wa.inbound",
        "filter": {"direction": "inbound"},
        "payload": ["id", "subscriber_id", "phone"],
    },
    {
        "collection": "aihub_wa_messages",
        "ts": "created_at",
        "kind": "wa.outbound",
        "filter": {"direction": "outbound"},
        "payload": ["id", "subscriber_id", "phone"],
    },
    # ---- INDICAÇÕES ----
    {
        "collection": "referrals",
        "ts": "created_at",
        "kind": "referral.created",
        "filter": {},
        "payload": ["id", "owner_subscriber_id", "friend_name"],
    },
    {
        "collection": "referrals",
        "ts": "installed_at",
        "kind": "referral.converted",
        "filter": {"status": "installed"},
        "payload": ["id", "owner_subscriber_id"],
        "severity": "alta",
    },
    # ---- PARCEIROS ----
    {
        "collection": "parcerias_redemptions",
        "ts": "redeemed_at",
        "kind": "partner.redeemed",
        "filter": {},
        "payload": ["id", "partner_id", "client_id",
                     "reimbursement_value"],
    },
    # ---- ESTOQUE ----
    {
        "collection": "stok_history",
        "ts": "date",
        "kind": "equipment.assigned",
        "filter": {"type": {"$in": ["instalacao", "rede_lancamento",
                                       "entrada_ont"]}},
        "payload": ["id", "description", "user"],
    },
    {
        "collection": "stok_history",
        "ts": "date",
        "kind": "equipment.returned",
        "filter": {"type": {"$in": ["retirada", "rompimento",
                                       "entrada_insumo_reversao"]}},
        "payload": ["id", "description", "user"],
    },
    # ---- REDE ----
    {
        "collection": "smartolt_onus",
        "ts": "last_status_change",
        "kind": "onu.offline",
        "filter": {"status": {"$in": ["Offline", "LOS", "Power fail"]}},
        "payload": ["sn", "name", "olt_name", "status"],
        "severity": "alta",
    },
    {
        "collection": "smartolt_onus",
        "ts": "last_status_change",
        "kind": "onu.online",
        "filter": {"status": "Online"},
        "payload": ["sn", "name", "olt_name"],
    },
    {
        "collection": "signal_degradation_alerts",
        "ts": "created_at",
        "kind": "signal.degraded",
        "filter": {},
        "payload": ["id", "subscriber_id", "onu_sn", "delta_db"],
        "severity": "alta",
    },
    # ---- OPERAÇÕES (técnicos) ----
    {
        "collection": "clock_records",
        "ts": "created_at",
        "kind": "technician.started",
        "filter": {"type": {"$in": ["Entrada", "Início intervalo"]}},
        "payload": ["id", "collaborator_id"],
    },
    {
        "collection": "clock_records",
        "ts": "created_at",
        "kind": "technician.finished",
        "filter": {"type": {"$in": ["Saída", "Fim intervalo"]}},
        "payload": ["id", "collaborator_id"],
    },
    {
        "collection": "clock_records",
        "ts": "created_at",
        "kind": "technician.late",
        "filter": {"status": "Bloqueado",
                    "internal_block_reason": {"$regex": "atras|late",
                                                "$options": "i"}},
        "payload": ["id", "collaborator_id", "internal_block_reason"],
        "severity": "alta",
    },
    # ---- MISSÃO 100% (Operação 90% · Fase Nervoso) ----
    # Eventos plug-in sobre coleções já populadas. Filtros calibrados
    # em valores reais (não-vazios) para não ficar 0 forever.
    {
        "collection": "sales_leads",
        "ts": "updated_at",
        "kind": "sale.lost",
        "filter": {"status": {"$in":
            ["lost", "perdido", "invalid_no_phone", "invalid"]}},
        "payload": ["id", "phone", "status"],
        "severity": "alta",
    },
    {
        "collection": "smart_installs",
        "ts": "finished_at",
        "kind": "install.failed",
        "filter": {"first_time_complete": False},
        "payload": ["id", "ticket_id", "client_id"],
        "severity": "alta",
    },
    {
        "collection": "subscriber_invoices",
        "ts": "paid_date",
        "kind": "payment.received",
        "filter": {"status": "paid"},
        "payload": ["external_id", "amount_paid",
                     "subscriber_external_id"],
        "severity": "alta",
    },
    {
        "collection": "subscriber_invoices",
        "ts": "synced_at",
        "kind": "payment.overdue",
        "filter": {"status": "overdue"},
        "payload": ["external_id", "amount", "due_date",
                     "subscriber_external_id"],
        "severity": "alta",
    },
    {
        "collection": "ticket_logs",
        "ts": "created_at",
        "kind": "ticket.reopened",
        "filter": {"action": {"$in":
            ["reagendar", "reabrir", "reopened", "reaberto"]}},
        "payload": ["ticket_id", "action", "actor_name"],
    },
]


async def _get_checkpoint(coll: str, kind: str) -> Optional[str]:
    doc = await db.nervous_checkpoints.find_one(
        {"collection": coll, "kind": kind})
    return doc.get("last_ts") if doc else None


async def _set_checkpoint(coll: str, kind: str, ts: str) -> None:
    await db.nervous_checkpoints.update_one(
        {"collection": coll, "kind": kind},
        {"$set": {"collection": coll, "kind": kind,
                   "last_ts": ts,
                   "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )


async def _bootstrap_checkpoints() -> None:
    """Na primeira execução, marca checkpoint=now() para evitar dumping
    massivo de eventos históricos no Event Bus."""
    now_iso = datetime.now(timezone.utc).isoformat()
    for plan in SYNC_PLAN:
        if not await db.nervous_checkpoints.find_one(
                {"collection": plan["collection"], "kind": plan["kind"]}):
            await _set_checkpoint(plan["collection"], plan["kind"], now_iso)


async def run_synchronization(
    limit_per_kind: int = 200,
    bootstrap: bool = False,
) -> Dict[str, Any]:
    """Roda 1 ciclo. bootstrap=True marca checkpoints=now() sem emitir."""
    if bootstrap:
        await _bootstrap_checkpoints()
        return {"bootstrap": True,
                "checkpoints_seeded": len(SYNC_PLAN)}

    emitted_total = 0
    per_kind: Dict[str, int] = {}
    for plan in SYNC_PLAN:
        coll = plan["collection"]
        ts_field = plan["ts"]
        kind = plan["kind"]
        filt = dict(plan.get("filter") or {})
        last_ts = await _get_checkpoint(coll, kind)
        # Compose query
        q = {**filt, ts_field: {"$gt": last_ts}} if last_ts else filt
        # Cursor ordenado por ts asc, limit
        try:
            cur = db[coll].find(q).sort(ts_field, 1).limit(limit_per_kind)
        except Exception:
            continue
        emitted = 0
        max_ts = last_ts
        async for doc in cur:
            cid = doc.get("company_id")
            if not cid:
                continue  # tenant leak guard
            payload = {k: doc.get(k) for k in plan.get("payload", [])
                       if doc.get(k) is not None}
            try:
                await emit_business(
                    kind=kind,
                    company_id=cid,
                    payload=payload,
                    severity=plan.get("severity", "media"),
                    source="nervous_sync",
                )
                emitted += 1
                # Atualiza max_ts
                ts = doc.get(ts_field)
                if ts and (not max_ts or ts > max_ts):
                    max_ts = ts
            except Exception:
                pass
        if max_ts and max_ts != last_ts:
            await _set_checkpoint(coll, kind, max_ts)
        per_kind[kind] = emitted
        emitted_total += emitted

    return {
        "emitted_total": emitted_total,
        "per_kind": per_kind,
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }
