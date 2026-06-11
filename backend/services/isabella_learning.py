"""ISABELLA LEARNING ENGINE — auto-ajuste de pesos por playbook.

Mantém para cada (kind, subkind, playbook) uma matriz:
  attempts | successes | failures | weight ∈ [0.05, 3.0] | confidence ∈ [0, 1]

Algoritmo (Thompson Sampling simplificado + smoothing):
  • Cada outcome `success` → reward(+) e attempts++
  • Cada outcome `failure` → penalty(-) e attempts++
  • weight = (success_rate * 2) ajustado por confidence (Wilson lower bound)
  • confidence = 1 - 1/sqrt(attempts + 1)  (cresce com volume)
  • Decay leve: a cada update, weight = 0.97 * weight + 0.03 * smoothed
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db

log = logging.getLogger("ponto.isabella_learning")

WEIGHT_FLOOR = 0.05
WEIGHT_CEIL = 3.0
DEFAULT_WEIGHT = 1.0


def _now():
    return datetime.now(timezone.utc).isoformat()


def _wilson_lower_bound(s: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    phat = s / n
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom)


def _key(kind: str, subkind: str, playbook: str) -> Dict[str, str]:
    return {"kind": kind or "_", "subkind": subkind or "_",
            "playbook": playbook or "_"}


async def ensure_indexes() -> None:
    try:
        await db.isabella_playbook_weights.create_index(
            [("company_id", 1), ("kind", 1), ("subkind", 1),
             ("playbook", 1)],
            unique=True, name="weight_pk")
        await db.isabella_playbook_weights.create_index(
            [("company_id", 1), ("kind", 1), ("weight", -1)])
    except Exception as e:  # noqa
        log.warning("[learning] ensure_indexes: %s", e)


async def record_attempt(*, company_id: str, kind: str, subkind: str,
                          playbook: str) -> None:
    """Conta uma tentativa (oportunidade aprovada/executada)."""
    k = _key(kind, subkind, playbook)
    await db.isabella_playbook_weights.update_one(
        {"company_id": company_id, **k},
        {"$inc": {"attempts": 1},
         "$setOnInsert": {"weight": DEFAULT_WEIGHT, "confidence": 0.0,
                            "created_at": _now()},
         "$set": {"updated_at": _now()}},
        upsert=True)


async def record_outcome(*, company_id: str, kind: str, subkind: str,
                          playbook: str, success: bool,
                          impact_brl: float = 0.0) -> Dict[str, Any]:
    """Atualiza pesos com base no outcome real."""
    k = _key(kind, subkind, playbook)
    inc = {"successes": 1, "roi_real_brl": float(impact_brl)} if success \
        else {"failures": 1}
    await db.isabella_playbook_weights.update_one(
        {"company_id": company_id, **k},
        {"$inc": inc,
         "$setOnInsert": {"weight": DEFAULT_WEIGHT, "confidence": 0.0,
                            "created_at": _now()},
         "$set": {"updated_at": _now()}},
        upsert=True)
    # Recalcula peso/confidence
    cur = await db.isabella_playbook_weights.find_one(
        {"company_id": company_id, **k}, {"_id": 0})
    attempts = int(cur.get("attempts") or 0)
    n_eval = int(cur.get("successes") or 0) + int(cur.get("failures") or 0)
    s = int(cur.get("successes") or 0)
    if n_eval >= 1:
        wilson = _wilson_lower_bound(s, n_eval)
        smoothed = max(WEIGHT_FLOOR, min(WEIGHT_CEIL, wilson * 2.5))
        prev = float(cur.get("weight") or DEFAULT_WEIGHT)
        new_w = round(0.7 * prev + 0.3 * smoothed, 4)
        new_w = max(WEIGHT_FLOOR, min(WEIGHT_CEIL, new_w))
    else:
        new_w = DEFAULT_WEIGHT
    confidence = round(1 - 1 / math.sqrt(max(n_eval, 0) + 1), 4)
    await db.isabella_playbook_weights.update_one(
        {"company_id": company_id, **k},
        {"$set": {"weight": new_w, "confidence": confidence,
                   "updated_at": _now()}})
    return {**k, "company_id": company_id, "weight": new_w,
            "confidence": confidence, "attempts": attempts,
            "successes": s, "failures": int(cur.get("failures") or 0)}


async def get_weight(company_id: str, kind: str, subkind: str,
                      playbook: str) -> float:
    cur = await db.isabella_playbook_weights.find_one(
        {"company_id": company_id, **_key(kind, subkind, playbook)},
        {"_id": 0, "weight": 1})
    if not cur:
        return DEFAULT_WEIGHT
    return float(cur.get("weight") or DEFAULT_WEIGHT)


async def recommend(*, company_id: str, kind: str,
                     candidates: List[Dict[str, Any]]
                     ) -> List[Dict[str, Any]]:
    """Reordena candidatos por (score base * weight aprendido).
    Espera candidatos com 'subkind', 'playbook', 'score' (0..100)."""
    if not candidates:
        return candidates
    keys = [{"subkind": c.get("subkind") or "_",
              "playbook": c.get("playbook") or "_"}
             for c in candidates]
    weights = await db.isabella_playbook_weights.find(
        {"company_id": company_id, "kind": kind,
         "$or": [{"subkind": k["subkind"], "playbook": k["playbook"]}
                  for k in keys]},
        {"_id": 0, "subkind": 1, "playbook": 1, "weight": 1}
    ).to_list(1000)
    wmap = {(w["subkind"], w["playbook"]): float(w.get("weight")
                                                    or DEFAULT_WEIGHT)
            for w in weights}
    enriched = []
    for c in candidates:
        w = wmap.get((c.get("subkind") or "_",
                        c.get("playbook") or "_"), DEFAULT_WEIGHT)
        enriched.append({**c, "weight": w,
                         "adjusted_score": float(c.get("score") or 0) * w})
    enriched.sort(key=lambda x: x["adjusted_score"], reverse=True)
    return enriched


async def top_playbooks(company_id: str, *, kind: Optional[str] = None,
                         limit: int = 20) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"company_id": company_id}
    if kind:
        q["kind"] = kind
    return await db.isabella_playbook_weights.find(q, {"_id": 0}) \
        .sort([("weight", -1), ("successes", -1)]).limit(limit) \
        .to_list(limit)
