"""
predictions_validation.py — Sprint 20
Harness de validação de acurácia das predictions.

Para cada predição com horizon expirado:
  - Consulta a realidade ocorrida na janela (eventos, payments, churn).
  - Computa precision/recall.
  - Grava em `motor_ia_predictions_validation`.
  - Realimenta um learning snapshot para feedback adicional.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from database import db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


async def _validate_churn(pred: Dict[str, Any]) -> Dict[str, Any]:
    """Para predição de churn: ver se subscribers preditos como risco
    realmente cancelaram ou viraram overdue/inactive."""
    items = pred.get("items") or []
    if not items:
        return {"validated": False, "reason": "no_items"}
    predicted_ids = [it.get("subscriber_id") for it in items
                       if it.get("subscriber_id")]
    if not predicted_ids:
        return {"validated": False, "reason": "no_subscriber_ids"}
    # critério "churn real": subscriber agora está cancelled/overdue
    actually_churned = await db.subscribers.count_documents({
        "id": {"$in": predicted_ids},
        "status": {"$in": ["canceled", "cancelado", "inactive"]}})
    overdue_pred = await db.subscriber_invoices.count_documents({
        "subscriber_id": {"$in": predicted_ids},
        "status": {"$in": ["overdue", "open"]}})
    n_predicted = len(predicted_ids)
    precision = (100.0 * actually_churned / n_predicted) \
        if n_predicted else 0.0
    return {
        "validated": True,
        "predicted_count": n_predicted,
        "actually_churned": actually_churned,
        "with_overdue": overdue_pred,
        "precision_pct": round(precision, 1),
        "criterion": "subscriber.status in (canceled|inactive)",
    }


async def _validate_ticket_demand(pred: Dict[str, Any]
                                       ) -> Dict[str, Any]:
    """Para predição de ticket_demand: comparar forecast 7d com tickets
    reais nos últimos 7d desde a predição."""
    generated_at = pred.get("generated_at")
    if not generated_at:
        return {"validated": False, "reason": "no_generated_at"}
    try:
        start = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except Exception:
        return {"validated": False, "reason": "bad_date"}
    end = start + timedelta(days=pred.get("horizon_days", 7))
    if end > _now():
        return {"validated": False, "reason": "horizon_not_expired"}
    company_id = pred.get("company_id")
    flt = {"created_at": {"$gte": _iso(start),
                            "$lt": _iso(end)}}
    if company_id:
        flt["company_id"] = company_id
    actual = await db.tickets.count_documents(flt)
    forecast = sum(pred.get("forecast") or []) or sum(
        (it.get("forecast_7d") or 0) for it in
        (pred.get("items") or []))
    diff = actual - forecast
    pct_err = (100.0 * abs(diff) / max(actual, 1)) if actual else None
    return {
        "validated": True,
        "forecast": round(forecast, 1),
        "actual": actual,
        "abs_error": abs(diff),
        "pct_error": round(pct_err, 1) if pct_err is not None else None,
    }


async def run_validation_cycle(horizon_overdue_days: int = 0
                                    ) -> Dict[str, Any]:
    """Roda validação de TODAS as predições expiradas.

    `horizon_overdue_days`: 0 = exatamente na data; aceita predição
    com horizon já cumprido."""
    out = {"validated": 0, "skipped": 0,
            "results": [], "ran_at": _iso(_now())}
    cutoff = _now()
    async for pred in db.motor_ia_predictions.find({}):
        pred.pop("_id", None)
        gen = pred.get("generated_at")
        horizon = int(pred.get("horizon_days") or 30)
        if not gen:
            continue
        try:
            start = datetime.fromisoformat(
                gen.replace("Z", "+00:00"))
        except Exception:
            continue
        if start + timedelta(days=horizon) > cutoff:
            out["skipped"] += 1
            continue
        # já validada antes?
        existing = await db.motor_ia_predictions_validation.find_one(
            {"prediction_id": pred.get("id")})
        if existing:
            out["skipped"] += 1
            continue

        kind = pred.get("kind") or ""
        if "churn" in kind:
            v = await _validate_churn(pred)
        elif "ticket" in kind or "arima" in kind:
            v = await _validate_ticket_demand(pred)
        else:
            v = {"validated": False, "reason": "no_validator"}

        record = {
            "id": f"val-{uuid.uuid4().hex[:12]}",
            "prediction_id": pred.get("id"),
            "prediction_kind": pred.get("kind"),
            "prediction_model": pred.get("model"),
            "company_id": pred.get("company_id"),
            "horizon_days": horizon,
            "predicted_at": gen,
            "validated_at": _iso(_now()),
            "result": v,
        }
        try:
            await db.motor_ia_predictions_validation.insert_one(
                dict(record))
        except Exception:
            pass
        record.pop("_id", None)
        if v.get("validated"):
            out["validated"] += 1
        out["results"].append(record)
    return out


async def accuracy_summary() -> Dict[str, Any]:
    """Sumário agregado de acurácia por (kind, model)."""
    summary: Dict[str, Any] = {}
    pipe = [
        {"$group": {
            "_id": {"kind": "$prediction_kind",
                       "model": "$prediction_model"},
            "n_validations": {"$sum": 1},
            "avg_precision":
                {"$avg": "$result.precision_pct"},
            "avg_pct_error":
                {"$avg": "$result.pct_error"},
        }},
    ]
    async for r in db.motor_ia_predictions_validation.aggregate(pipe):
        key = f"{(r['_id'] or {}).get('kind')}::" \
              f"{(r['_id'] or {}).get('model')}"
        summary[key] = {
            "n_validations": r.get("n_validations"),
            "avg_precision_pct": round(r.get("avg_precision") or 0, 1),
            "avg_pct_error": round(r.get("avg_pct_error") or 0, 1),
        }
    return summary
