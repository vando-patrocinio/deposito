"""
reconcile_worker.py — Sprint final V5.0
Atualiza outcomes assíncronos dias depois da ação.
Monitora pagamentos, tickets resolvidos, retenção.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from database import db


def _now(): return datetime.now(timezone.utc)


async def reconcile_outcome(action_id: str) -> Dict[str, Any]:
    """Re-observa outcome para uma ação específica."""
    action = await db.motor_ia_actions.find_one({"action_id": action_id})
    if not action:
        return {"ok": False, "reason": "action not found"}
    decision = await db.motor_ia_decisions.find_one(
        {"decision_id": action["decision_id"]})
    if not decision:
        return {"ok": False, "reason": "decision not found"}
    outcome = await db.motor_ia_outcomes.find_one(
        {"action_id": action_id})
    if not outcome:
        return {"ok": False, "reason": "outcome not found"}

    co = action["company_id"]
    sid = (action.get("payload") or {}).get("subscriber_id")
    new_actual = float(outcome.get("actual_BRL") or 0)
    notes: List[str] = list(outcome.get("notes") or [])
    after = action.get("created_at")

    if sid:
        sub = await db.subscribers.find_one({"id": sid}, {"document": 1,
                                                            "status": 1})
        if sub and sub.get("document"):
            agg = await db.subscriber_invoices.aggregate([
                {"$match": {"company_id": co,
                              "subscriber_document": sub["document"],
                              "status": "paid",
                              "paid_date": {"$gte": after}}},
                {"$group": {"_id": None, "t": {"$sum": "$amount"}}},
            ]).to_list(1)
            paid_after = float(agg[0]["t"]) if agg else 0.0
            if paid_after > new_actual:
                new_actual = paid_after
                notes.append(f"reconcile: paid_after={paid_after:.2f}")

        # Cliente continua ATIVO após X dias = retenção bem-sucedida
        if action.get("kind") == "retention_campaign" and sub:
            days_since = (
                _now() - datetime.fromisoformat(after.replace("Z", "+00:00"))
                .astimezone(timezone.utc)).days
            if days_since >= 3 and sub.get("status") == "ATIVO":
                if "retention_confirmed" not in str(notes):
                    notes.append(
                        f"reconcile: retention_confirmed ({days_since}d)")
                    new_actual += float(decision.get("expected_BRL") or 0)

        # Ticket preventivo encerrado
        if action.get("kind") == "preventive_ticket":
            tk_id = (action.get("result") or {}).get("ticket_id")
            if tk_id:
                tk = await db.tickets.find_one(
                    {"id": tk_id}, {"status": 1})
                if tk and tk.get("status") in ("fechada", "resolvida",
                                                  "closed"):
                    notes.append("reconcile: preventive_ticket_resolved")
                    new_actual += float(decision.get("expected_BRL") or 0)

    # Atualiza outcome + decision_quality
    expected = float(decision.get("expected_BRL") or 0)
    accuracy = (min(new_actual / expected, 1.0) * 100
                 if expected > 0 else (100.0 if new_actual >= 0 else 0.0))
    await db.motor_ia_outcomes.update_one(
        {"outcome_id": outcome["outcome_id"]},
        {"$set": {"actual_BRL": round(new_actual, 2),
                   "notes": notes,
                   "reconciled_at": _now().isoformat()}})
    await db.motor_ia_decision_quality.update_one(
        {"decision_id": decision["decision_id"]},
        {"$set": {"actual_brl": round(new_actual, 2),
                   "accuracy_pct": round(accuracy, 2),
                   "reconciled_at": _now().isoformat()}})
    await db.motor_ia_autonomous_cycles.update_one(
        {"action_id": action_id},
        {"$set": {"actual_BRL": round(new_actual, 2)}})
    return {"ok": True, "action_id": action_id,
             "actual_BRL": round(new_actual, 2),
             "accuracy_pct": round(accuracy, 2)}


async def reconcile_all_recent(company_id: str | None = None,
                                  hours: int = 168) -> Dict[str, Any]:
    """Reconcilia ações executadas nas últimas N horas (default 7d)."""
    cutoff = (_now() - timedelta(hours=hours)).isoformat()
    q: Dict[str, Any] = {
        "created_at": {"$gte": cutoff},
        "status": {"$in": ["executed", "dispatched"]},
    }
    if company_id: q["company_id"] = company_id
    actions = await db.motor_ia_actions.find(
        q, {"action_id": 1}).limit(2000).to_list(2000)
    results = []
    for a in actions:
        r = await reconcile_outcome(a["action_id"])
        if r.get("ok"):
            results.append(r)
    return {"reconciled": len(results), "hours_window": hours,
             "details": results[:50]}
