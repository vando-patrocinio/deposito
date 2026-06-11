"""
learnings.py — Sprint 12
Persistência de aprendizado contínuo do Motor IA.

Toda vez que o feedback_loop calcula novas stats de success_rate por
action_type, geramos um doc em `motor_ia_learnings` com:

  {
    id, kind: "feedback_snapshot",
    generated_at, stats: { action_type → {success_rate, factor, total} },
    deltas: { action_type → {factor_before, factor_after, delta} },
  }

Permite:
  - Auditar quando o sistema mudou o "comportamento" das regras.
  - Recomendar action humana se um action_type colapsar (queda > 30%).
  - Reverter aprendizados em caso de regressão.
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
from typing import Any, Dict

from database import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def record_learning_snapshot(stats: Dict[str, Dict[str, float]]
                                        ) -> Dict[str, Any]:
    """Grava snapshot atual e calcula deltas vs último snapshot.

    Chamado pelo `feedback_loop.refresh_stats()`.
    """
    last = await db.motor_ia_learnings.find_one(
        {"kind": "feedback_snapshot"},
        sort=[("generated_at", -1)])
    prev_stats = (last or {}).get("stats") or {}

    deltas: Dict[str, Dict[str, float]] = {}
    alerts = []
    for action_type, s in stats.items():
        before = (prev_stats.get(action_type) or {}).get("factor", 1.0)
        after = s.get("factor", 1.0)
        delta = round(after - before, 3)
        deltas[action_type] = {
            "factor_before": before,
            "factor_after": after,
            "delta": delta,
            "success_rate": s.get("success_rate"),
            "total": s.get("total"),
        }
        if delta <= -0.30:
            alerts.append({
                "action_type": action_type,
                "kind": "factor_collapse",
                "message": (
                    f"factor caiu de {before} para {after} — "
                    f"success_rate {s.get('success_rate')}"),
            })

    doc = {
        "id": f"lrn-{uuid.uuid4().hex[:12]}",
        "kind": "feedback_snapshot",
        "generated_at": _now(),
        "stats": stats,
        "deltas": deltas,
        "alerts": alerts,
    }
    try:
        await db.motor_ia_learnings.insert_one(dict(doc))
    except Exception:
        pass
    doc.pop("_id", None)
    # se houve alertas, emite evento no event_bus
    if alerts:
        try:
            from services.event_bus import emit_event
            for a in alerts:
                await emit_event(
                    "AI_LEARNING_ALERT",
                    source="learnings",
                    severity="alta",
                    payload=a,
                )
        except Exception:
            pass
    return doc


async def list_learnings(limit: int = 30) -> Dict[str, Any]:
    """Lista snapshots recentes (para o painel CTO)."""
    items = []
    async for d in db.motor_ia_learnings.find(
            {}, {"_id": 0}).sort("generated_at", -1).limit(limit):
        items.append(d)
    return {"count": len(items), "items": items}


async def latest_snapshot() -> Dict[str, Any]:
    doc = await db.motor_ia_learnings.find_one(
        {"kind": "feedback_snapshot"},
        sort=[("generated_at", -1)])
    if doc:
        doc.pop("_id", None)
    return doc or {}
