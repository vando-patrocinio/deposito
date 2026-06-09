"""
auto_tuning.py — FASE 10 V5.0
Auto-ajuste de thresholds com base em ROI observado.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from database import db


async def tune_thresholds(company_id: str,
                          window_days: int = 14) -> Dict[str, Any]:
    """Ajusta o threshold de execução por kind de ação baseado no
    accuracy histórico (actual/expected)."""
    cutoff = (datetime.now(timezone.utc)
              - timedelta(days=window_days)).isoformat()
    pipe = [
        {"$match": {"company_id": company_id,
                     "started_at": {"$gte": cutoff},
                     "status": "complete"}},
        {"$group": {
            "_id": "$action_kind",
            "n": {"$sum": 1},
            "expected": {"$sum": "$expected_BRL"},
            "actual": {"$sum": "$actual_BRL"},
        }},
    ]
    rows = await db.motor_ia_autonomous_cycles.aggregate(pipe).to_list(50)
    adjustments = []
    for r in rows:
        kind = r["_id"] or "unknown"
        n = r["n"]
        exp = r["expected"]
        act = r["actual"]
        roi = (act / exp) if exp > 0 else 0.0
        # Política simples:
        #   ROI < 0.5 → +0.05 threshold (mais conservador)
        #   ROI > 1.0 → -0.05 threshold (mais agressivo)
        adj = 0.0
        if exp > 0:
            if roi < 0.5: adj = 0.05
            elif roi > 1.0: adj = -0.05
        adjustments.append({
            "kind": kind, "cycles": n,
            "expected_BRL": round(exp, 2),
            "actual_BRL": round(act, 2),
            "roi": round(roi, 3),
            "threshold_adjustment": adj,
        })
        await db.motor_ia_tuning_log.insert_one({
            "company_id": company_id, "kind": kind,
            "cycles": n, "expected_BRL": exp, "actual_BRL": act,
            "roi": roi, "threshold_adjustment": adj,
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "window_days": window_days,
        })
    return {"company_id": company_id, "window_days": window_days,
             "tunings": adjustments,
             "applied_at": datetime.now(timezone.utc).isoformat()}
