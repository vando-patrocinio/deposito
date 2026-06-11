"""
company_settings.py — Sprint 15
Feature flags por empresa: ativa PRESIDENTE_IA_LIVE em ações específicas
para uma `company_id`, sem precisar mudar env global.

Schema da collection `company_settings`:
{
  "_id": "<company_id>",
  "presidente_ia": {
    "live_actions": ["escalate_dunning", "notify_manager"],
    "updated_at": "...",
    "updated_by": "<user_id>"
  }
}

API:
    await is_live(company_id, "escalate_dunning")
    await set_live(company_id, ["escalate_dunning"])  # admin
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
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from database import db


def _global_live() -> bool:
    """Feature flag global PRESIDENTE_IA_LIVE=1 ainda funciona como
    override total (todas as ações LIVE)."""
    return os.environ.get("PRESIDENTE_IA_LIVE", "0") == "1"


async def is_live(company_id: Optional[str],
                    action_type: str) -> bool:
    """True se a ação deve ser executada em modo LIVE para esta empresa."""
    if _global_live():
        return True
    if not company_id:
        return False
    doc = await db.company_settings.find_one({"_id": company_id})
    if not doc:
        return False
    cfg = (doc.get("presidente_ia") or {})
    live_actions = cfg.get("live_actions") or []
    return action_type in live_actions


async def set_live(company_id: str, action_types: Iterable[str],
                     updated_by: Optional[str] = None) -> dict:
    """Define quais action_types rodam em LIVE para esta empresa."""
    lst = sorted(set(action_types))
    await db.company_settings.update_one(
        {"_id": company_id},
        {"$set": {
            "presidente_ia.live_actions": lst,
            "presidente_ia.updated_at":
                datetime.now(timezone.utc).isoformat(),
            "presidente_ia.updated_by": updated_by,
        }},
        upsert=True)
    return {"company_id": company_id, "live_actions": lst}


async def get_live_actions(company_id: str) -> List[str]:
    doc = await db.company_settings.find_one({"_id": company_id})
    if not doc:
        return []
    return ((doc.get("presidente_ia") or {}).get("live_actions") or [])


async def list_all_live_settings() -> List[dict]:
    out = []
    async for d in db.company_settings.find(
            {"presidente_ia.live_actions": {"$exists": True,
                                                  "$ne": []}}):
        out.append({
            "company_id": d.get("_id"),
            "live_actions":
                (d.get("presidente_ia") or {}).get("live_actions"),
            "updated_at":
                (d.get("presidente_ia") or {}).get("updated_at"),
        })
    return out
