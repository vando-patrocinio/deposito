"""
feedback_loop.py — Sprint 10
Feedback Loop: usa motor_ia_outcomes para ajustar dinamicamente o
confidence das regras do decision_engine.

Conceito:
  - Cada `action_type` tem um histórico de outcomes (ok/falha).
  - Calculamos a success_rate(action_type, window=30d).
  - `effective_confidence = base_confidence * adjustment_factor`,
    onde adjustment_factor ∈ [0.5, 1.2]:
      success_rate >= 0.95 → 1.20 (boost)
      0.80–0.95           → 1.00 (neutro)
      0.50–0.80           → 0.85
      < 0.50              → 0.50 (penaliza forte)
  - O ajuste fica em cache (TTL 5min) para não derrubar perf.
  - Cada recálculo gera um doc em `motor_ia_learnings` (Sprint 12).
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Dict

from database import db


WINDOW_DAYS = 30
MIN_SAMPLE = 5   # abaixo disso, mantém base
CACHE_TTL_S = 300

_cache: Dict[str, Dict[str, float]] = {}
_cache_at: float = 0.0
_lock = asyncio.Lock()


def _factor_for(success_rate: float) -> float:
    if success_rate >= 0.95:
        return 1.20
    if success_rate >= 0.80:
        return 1.00
    if success_rate >= 0.50:
        return 0.85
    return 0.50


async def _compute_all() -> Dict[str, Dict[str, float]]:
    """Computa stats por action_type a partir de motor_ia_outcomes
    join motor_ia_actions (para pegar action_type)."""
    since = (datetime.now(timezone.utc)
             - timedelta(days=WINDOW_DAYS)).isoformat()
    pipe = [
        {"$match": {"created_at": {"$gte": since}}},
        {"$lookup": {
            "from": "motor_ia_actions",
            "localField": "action_id",
            "foreignField": "id",
            "as": "act",
        }},
        {"$unwind": {"path": "$act",
                       "preserveNullAndEmptyArrays": True}},
        {"$group": {
            "_id": "$act.action_type",
            "total": {"$sum": 1},
            "ok": {"$sum": {"$cond": ["$ok", 1, 0]}},
        }},
    ]
    out: Dict[str, Dict[str, float]] = {}
    async for r in db.motor_ia_outcomes.aggregate(pipe):
        action_type = r.get("_id")
        if not action_type:
            continue
        total = int(r.get("total") or 0)
        ok = int(r.get("ok") or 0)
        if total < MIN_SAMPLE:
            success_rate = 0.85  # default ainda neutro
            factor = 1.0
        else:
            success_rate = ok / total
            factor = _factor_for(success_rate)
        out[action_type] = {
            "success_rate": round(success_rate, 3),
            "factor": factor,
            "total": total,
            "ok": ok,
        }
    return out


async def refresh_stats(force: bool = False) -> Dict[str, Dict[str, float]]:
    """Atualiza cache + grava snapshot em motor_ia_learnings."""
    global _cache, _cache_at
    async with _lock:
        now = time.time()
        if not force and (now - _cache_at) < CACHE_TTL_S and _cache:
            return _cache
        stats = await _compute_all()
        _cache = stats
        _cache_at = now
        # Sprint 12: registra learning snapshot
        try:
            from services.learnings import record_learning_snapshot
            await record_learning_snapshot(stats)
        except Exception:
            pass
        return stats


async def get_factor(action_type: str) -> float:
    """Retorna fator de ajuste para um action_type. Cacheado."""
    stats = await refresh_stats()
    return float(stats.get(action_type, {}).get("factor", 1.0))


async def get_stats() -> Dict[str, Dict[str, float]]:
    """Snapshot atual (para painel / auditoria)."""
    return await refresh_stats()


async def adjust_confidence(action_type: str, base: float) -> float:
    """Aplica fator de feedback à confidence base."""
    factor = await get_factor(action_type)
    adjusted = base * factor
    # clamp em [0.05, 0.99]
    return max(0.05, min(0.99, round(adjusted, 3)))
