"""Migração 02/2026 — Unificação OpenRouter key.

Remove o campo legado `api_key` da coleção `motor_ia_config` (era um
segundo openrouter key sem consumidores, criava risco de fallback
silencioso quando o key principal esgotava).

Fonte de verdade ÚNICA: `motor_ia_config.openrouter_api_key`.

Roda 1x no startup; idempotente.
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

import logging
from typing import Any, Dict

from database import db

log = logging.getLogger("ponto.openrouter_unify")


async def run_once() -> Dict[str, Any]:
    cur = db.motor_ia_config.find(
        {"api_key": {"$exists": True}},
        {"_id": 0, "company_id": 1, "api_key": 1,
         "openrouter_api_key": 1})
    docs = await cur.to_list(500)
    cleaned = 0
    salvaged = 0
    for d in docs:
        api_legacy = d.get("api_key") or ""
        api_main = d.get("openrouter_api_key") or ""
        update: Dict[str, Any] = {}
        if not api_main and api_legacy.startswith("sk-or-"):
            # Salvaguarda: se só existir o legacy, promove ele
            update["openrouter_api_key"] = api_legacy
            salvaged += 1
        # Sempre remove o legacy
        await db.motor_ia_config.update_one(
            {"company_id": d["company_id"]},
            {"$unset": {"api_key": ""},
             **({"$set": update} if update else {})})
        cleaned += 1
    log.info("[openrouter_unify] cleaned=%d salvaged=%d", cleaned, salvaged)
    return {"cleaned": cleaned, "salvaged": salvaged}
