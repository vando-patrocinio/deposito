"""
memory_cleanup.py — Pós-CTO audit P2
Cleanup de coleções `motor_ia_*` antigas.

MongoDB TTL nativo precisaria de campo Date, mas nosso schema é
ISO-string. Então fazemos cleanup determinístico baseado em retenção
configurável.
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

import os
from datetime import datetime, timedelta, timezone
from typing import Dict

from database import db


RETENTION_DAYS = {
    "motor_ia_events":     int(os.environ.get("RET_EVENTS_DAYS", "60")),
    "motor_ia_actions":    int(os.environ.get("RET_ACTIONS_DAYS", "90")),
    "motor_ia_outcomes":   int(os.environ.get("RET_OUTCOMES_DAYS", "90")),
    "motor_ia_insights":   int(os.environ.get("RET_INSIGHTS_DAYS", "180")),
    "motor_ia_predictions": int(os.environ.get("RET_PRED_DAYS", "180")),
    "motor_ia_memory":     int(os.environ.get("RET_MEMORY_DAYS", "30")),
}

DATE_FIELD = {
    "motor_ia_events": "timestamp",
}


async def cleanup_old_memory() -> Dict[str, int]:
    """Apaga docs mais antigos que a retenção configurada.
    Retorna dict {coleção: docs_apagados}."""
    out: Dict[str, int] = {}
    total = 0
    for coll, days in RETENTION_DAYS.items():
        if days <= 0:
            continue
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=days)).isoformat()
        field = DATE_FIELD.get(coll, "created_at")
        try:
            r = await db[coll].delete_many({field: {"$lt": cutoff}})
            if r.deleted_count:
                out[coll] = r.deleted_count
                total += r.deleted_count
        except Exception:
            pass
    out["deleted_total"] = total
    return out
