"""
rule_thresholds.py — Sprint 17 (Auto-tuning)
Thresholds das regras agora vêm de banco e podem ser ajustados
automaticamente baseado em outcomes.

Schema da collection `rule_thresholds`:
{
  "_id": "<rule_name>",         # ex: "collective_outage"
  "thresholds": { "min_offline_count": 5, "window_min": 10 },
  "updated_at": "...",
  "updated_by": "auto_tuning" | "<user_id>",
  "history": [ {when, before, after, reason} ]
}

Cache TTL 5min para perf.

Auto-tuning: se uma regra dispara MUITO (false positive proxy:
factor caiu abaixo de 0.7), aumenta o threshold; se dispara pouco
(zero outcomes por 7 dias), reduz threshold.
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

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict

from database import db


DEFAULTS: Dict[str, Dict[str, Any]] = {
    "collective_outage": {"min_offline_count": 5, "window_min": 10},
    "rbac_abuse":        {"min_denied_count": 3, "window_min": 60},
    "ticket_recurring":  {"min_tickets": 3},
}

CACHE_TTL_S = 300
_cache: Dict[str, Dict[str, Any]] = {}
_cache_at: float = 0.0
_lock = asyncio.Lock()


async def _refresh_cache() -> Dict[str, Dict[str, Any]]:
    global _cache, _cache_at
    async with _lock:
        now = time.time()
        if (now - _cache_at) < CACHE_TTL_S and _cache:
            return _cache
        out = dict(DEFAULTS)
        try:
            async for d in db.rule_thresholds.find({}):
                rule = d.get("_id")
                if rule and isinstance(d.get("thresholds"), dict):
                    out[rule] = {**out.get(rule, {}),
                                 **d["thresholds"]}
        except Exception:
            pass
        _cache = out
        _cache_at = now
        return out


async def get(rule: str, key: str, fallback=None):
    cache = await _refresh_cache()
    return (cache.get(rule) or {}).get(key, fallback)


async def get_all(rule: str) -> Dict[str, Any]:
    cache = await _refresh_cache()
    return dict(cache.get(rule) or DEFAULTS.get(rule) or {})


async def set_threshold(rule: str, thresholds: Dict[str, Any],
                          updated_by: str = "auto_tuning",
                          reason: str = "") -> Dict[str, Any]:
    """Persiste thresholds + invalida cache."""
    global _cache_at
    now = datetime.now(timezone.utc).isoformat()
    existing = await db.rule_thresholds.find_one({"_id": rule}) or {}
    history_entry = {
        "when": now,
        "before": existing.get("thresholds", {}),
        "after": thresholds,
        "reason": reason,
        "updated_by": updated_by,
    }
    await db.rule_thresholds.update_one(
        {"_id": rule},
        {"$set": {"thresholds": thresholds,
                  "updated_at": now,
                  "updated_by": updated_by},
         "$push": {"history": {"$each": [history_entry],
                                "$slice": -20}}},
        upsert=True)
    _cache_at = 0
    return {"rule": rule, "thresholds": thresholds,
            "reason": reason}


async def auto_tune() -> Dict[str, Any]:
    """Roda heurística de auto-tuning de thresholds baseada em
    feedback_loop.factor:
      - factor < 0.7 → regra produz lixo → aumenta threshold em +1
      - factor == 1.20 estável + 7 dias sem falha → reduz threshold em -1
        (mais sensível)
    """
    from services.feedback_loop import refresh_stats
    stats = await refresh_stats(force=False)
    decisions = []

    # mapping rough action_type → rule_name (precisa rever caso a caso)
    map_to_rule = {
        "open_incident": "collective_outage",
        "notify_manager": "rbac_abuse",
        "create_retention_opportunity": "ticket_recurring",
    }
    for action_type, info in stats.items():
        rule = map_to_rule.get(action_type)
        if not rule:
            continue
        factor = info.get("factor", 1.0)
        current = await get_all(rule)
        if factor < 0.7:
            # aumenta threshold do primeiro número config
            for k, v in list(current.items()):
                if isinstance(v, (int, float)) and "count" in k:
                    new = current.copy()
                    new[k] = v + 1
                    await set_threshold(
                        rule, new,
                        updated_by="auto_tuning",
                        reason=f"factor {factor} < 0.7 (excesso "
                                f"de falsos positivos)")
                    decisions.append({"rule": rule, "action": "increase",
                                      "key": k, "before": v,
                                      "after": v + 1,
                                      "factor": factor})
                    break
        elif factor >= 1.20 and info.get("total", 0) >= 20:
            for k, v in list(current.items()):
                if isinstance(v, (int, float)) and "count" in k and v > 2:
                    new = current.copy()
                    new[k] = v - 1
                    await set_threshold(
                        rule, new,
                        updated_by="auto_tuning",
                        reason=(f"factor {factor} estável + "
                                  f"{info.get('total')} amostras (regra "
                                  f"pode ser mais sensível)"))
                    decisions.append({"rule": rule, "action": "decrease",
                                      "key": k, "before": v,
                                      "after": v - 1,
                                      "factor": factor})
                    break
    return {"adjustments": decisions, "ran_at":
              datetime.now(timezone.utc).isoformat()}
