"""
v7_1_backfill.py — V7.1 G1 (Action→Cash via invoices)

Cruza `subscriber_invoices.status=paid` com `motor_ia_outcomes` para
fechar o ciclo sem depender de Baileys/Asaas/PIX externos.

Join chain:
  invoice.subscriber_external_id  →  subscribers.external_code
  subscribers.id                  →  motor_ia_outcomes.subscriber_id

Tagged `revenue_source = "invoice_backfill_v7_1"` para auditoria.
NÃO toca outcomes com environment=homolog.
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

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from database import db

ISO = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731


async def backfill_action_to_cash(
    company_id: str, window_days: int = 90, dry_run: bool = False,
) -> Dict[str, Any]:
    """G1 — fecha outcomes a partir de invoices PAGAS. Idempotente."""
    cutoff = (datetime.now(timezone.utc)
              - timedelta(days=window_days)).isoformat()
    from services import company_v6 as v6

    # 1) Pega invoices PAGAS na janela
    inv_q = {"company_id": company_id, "status": "paid"}
    invoices = await db.subscriber_invoices.find(inv_q).to_list(10000)

    matched = skipped_no_sub = skipped_no_outcome = errors = 0
    already_received = 0
    total_BRL = 0.0
    audit: List[Dict[str, Any]] = []

    for inv in invoices:
        ext_id = inv.get("subscriber_external_id")
        if not ext_id:
            skipped_no_sub += 1
            continue
        sub = await db.subscribers.find_one(
            {"company_id": company_id, "external_code": ext_id})
        if not sub:
            skipped_no_sub += 1
            continue
        sid = sub.get("id")
        amount = float(inv.get("amount_paid") or inv.get("amount") or 0)
        if amount <= 0:
            continue
        # 2) Acha outcome aberto desse subscriber com expected próximo
        oc = await db.motor_ia_outcomes.find_one({
            "company_id": company_id, "subscriber_id": sid,
            "environment": {"$ne": "homolog"},
            "status": {"$ne": "revenue_received"},
            "expected_BRL": {"$gt": 0},
        }, sort=[("observed_at", -1)])
        if not oc:
            skipped_no_outcome += 1
            continue
        exp = float(oc.get("expected_BRL") or 0)
        if exp <= 0 or not (0.5 <= (amount / exp) <= 2.0):
            skipped_no_outcome += 1
            continue
        if dry_run:
            matched += 1
            total_BRL += amount
            audit.append({"invoice_id": inv.get("id"),
                          "outcome_id": oc.get("id"),
                          "subscriber_id": sid,
                          "amount_BRL": amount,
                          "would_mark": True})
            continue
        try:
            r = await v6.mark_revenue_received(
                company_id, oc["id"], amount,
                source="invoice_backfill_v7_1",
                payment_ref=inv.get("id") or inv.get("external_id"))
            if "error" in r:
                errors += 1
                continue
            matched += 1
            total_BRL += amount
            audit.append({"invoice_id": inv.get("id"),
                          "outcome_id": oc["id"],
                          "subscriber_id": sid,
                          "amount_BRL": amount,
                          "marked": True})
        except Exception:
            errors += 1

    return {
        "company_id": company_id,
        "window_days": window_days,
        "dry_run": dry_run,
        "invoices_paid_total": len(invoices),
        "outcomes_marked_received": matched,
        "total_recovered_BRL": round(total_BRL, 2),
        "skipped_no_subscriber_match": skipped_no_sub,
        "skipped_no_outcome_match": skipped_no_outcome,
        "already_received": already_received,
        "errors": errors,
        "audit_sample": audit[:20],
        "generated_at": ISO(),
    }
