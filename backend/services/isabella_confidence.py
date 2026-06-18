"""Isabella Confidence Score V15.2.

ARQUITETURA CTO 18/02/2026:
  4 sub-scores compõem o ISABELLA INDEX:

  1. Trust Score (40%)        — "Posso confiar no que ela fala?"
     Base: % de outbounds com evidence_id consumido + ausência de correções.

  2. Relationship Score (20%) — "Ela conhece o cliente?"
     Base: uso de memória + reconhecimento de VIP + follow-up de promessas.

  3. Resolution Score (20%)   — "Ela resolve?"
     Base: outcome=resolveu/vendeu/reteve em ai_evaluations.

  4. Promise Score (20%)      — "Ela cumpre o que promete?"
     Base: promises resolved / created + tempo médio de cumprimento.

ISABELLA INDEX = média ponderada dos 4 sub-scores.

REGRA DE CORREÇÕES (peso na Trust):
  • factual_error (0-2h, severity=high) → -100% peso (penaliza forte)
  • state_changed (2-24h, severity=none) → 0% (não é erro)
  • delayed_resolution (1-7d, severity=low) → -25% peso (mínimo)

Sinais usados (zero coleta nova — tudo já existe):
  • `isabella_factual_claims` (Trust)
  • `customer_memory.hit_count` (Relationship)
  • `customer_promises.status` (Promise)
  • `ai_evaluations.outcome` (Resolution)
  • `ai_evaluations.nps_motivo` contém "frustração" (Trust — correções)
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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from database import db

logger = logging.getLogger("ponto.isabella_confidence")

# Pesos das sub-scores no ISABELLA INDEX
WEIGHTS = {
    "trust": 0.40,
    "relationship": 0.20,
    "resolution": 0.20,
    "promise": 0.20,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cutoff_iso(hours: int) -> str:
    return (_now() - timedelta(hours=hours)).isoformat()


def _safe_pct(num: float, den: float) -> float:
    if not den:
        return 0.0
    return round(num / den * 100.0, 1)


# ── 1. TRUST SCORE ───────────────────────────────────────────
async def trust_score(*, company_id: str, hours: int = 24) -> Dict[str, Any]:
    """Trust = afirmações com evidência consumida − correções ponderadas."""
    cutoff = _cutoff_iso(hours)

    # Factual claims auditados + consumidos
    claims_total = await db.isabella_factual_claims.count_documents({
        "company_id": company_id,
        "audited_at": {"$gte": cutoff},
    })
    claims_passed = await db.isabella_factual_claims.count_documents({
        "company_id": company_id,
        "audited_at": {"$gte": cutoff},
        "audit_passed": True,
    })
    claims_consumed = await db.isabella_factual_claims.count_documents({
        "company_id": company_id,
        "audited_at": {"$gte": cutoff},
        "consumed_by": {"$ne": None},
    })

    # Outbounds totais da Isabella no período
    outbounds = await db.aihub_wa_messages.count_documents({
        "company_id": company_id,
        "direction": "outbound",
        "created_at": {"$gte": cutoff},
        "auto_reply": True,
    })

    # Correções: ai_evaluations com nps_motivo contendo "frustração" ou
    # tags com "factual_error" — sinal de que cliente corrigiu a Isabella.
    # 3 níveis (factual=2h, state=2-24h, delayed=1-7d):
    cutoff_2h = _cutoff_iso(2)
    cutoff_7d = _cutoff_iso(24 * 7)
    factual_errors_2h = await db.ai_evaluations.count_documents({
        "company_id": company_id,
        "created_at": {"$gte": cutoff_2h},
        "nps_motivo": {"$regex": "frustra|errado|nao\\s+era", "$options": "i"},
    })
    delayed_corrections_7d = await db.ai_evaluations.count_documents({
        "company_id": company_id,
        "created_at": {"$gte": cutoff_7d, "$lt": cutoff_2h},
        "nps_motivo": {"$regex": "frustra|errado|nao\\s+era", "$options": "i"},
    })

    # Score: base = taxa de outbounds com claim consumido
    base_pct = _safe_pct(claims_consumed, outbounds) if outbounds else 0.0
    # Penaliza correções (peso 100% para 2h, 25% para 7d)
    penalty_factual = factual_errors_2h * 1.0
    penalty_delayed = delayed_corrections_7d * 0.25
    penalty_pct = _safe_pct(
        penalty_factual + penalty_delayed,
        max(outbounds, 1),
    )
    score = max(0.0, min(100.0, base_pct - penalty_pct))

    # Se cliente é novo (zero outbound), o trust default é 100 (sem dado)
    if outbounds == 0:
        score = 100.0

    return {
        "score": round(score, 1),
        "outbounds": outbounds,
        "claims_total": claims_total,
        "claims_passed": claims_passed,
        "claims_consumed": claims_consumed,
        "base_evidence_pct": base_pct,
        "factual_errors_2h": factual_errors_2h,
        "delayed_corrections_7d": delayed_corrections_7d,
        "penalty_pct": round(penalty_pct, 1),
    }


# ── 2. RELATIONSHIP SCORE ────────────────────────────────────
async def relationship_score(*, company_id: str,
                                   hours: int = 24) -> Dict[str, Any]:
    """Relationship = uso de memória + follow-up de promessas + VIP."""
    cutoff_dt = _now() - timedelta(hours=hours)

    # Memórias disponíveis vs usadas (hit_count > 0)
    mem_total = await db.customer_memory.count_documents({
        "company_id": company_id,
        "expires_at": {"$gte": _now()},
    })
    mem_used = await db.customer_memory.count_documents({
        "company_id": company_id,
        "expires_at": {"$gte": _now()},
        "hit_count": {"$gt": 0},
    })
    mem_recalled = await db.customer_timeline.count_documents({
        "company_id": company_id,
        "ts": {"$gte": cutoff_dt},
        "kind": {"$in": ["memory_recalled", "promise_recalled"]},
    })

    # Score = (taxa de memórias usadas) com piso de 50 se há recalls
    used_pct = _safe_pct(mem_used, mem_total) if mem_total else 0.0
    recall_bonus = min(20.0, mem_recalled * 0.5)
    score = min(100.0, used_pct + recall_bonus)
    # Sem dados → assume neutro
    if mem_total == 0:
        score = 70.0 if mem_recalled > 0 else 0.0

    return {
        "score": round(score, 1),
        "memories_available": mem_total,
        "memories_used": mem_used,
        "memory_recalls_window": mem_recalled,
        "used_pct": used_pct,
    }


# ── 3. RESOLUTION SCORE ──────────────────────────────────────
async def resolution_score(*, company_id: str,
                                 hours: int = 24) -> Dict[str, Any]:
    """Resolution = outcomes positivos / total de turnos da Isabella."""
    cutoff = _cutoff_iso(hours)
    total = await db.ai_evaluations.count_documents({
        "company_id": company_id,
        "created_at": {"$gte": cutoff},
        "kind": "ISABELLA_TURN",
    })
    resolved = await db.ai_evaluations.count_documents({
        "company_id": company_id,
        "created_at": {"$gte": cutoff},
        "kind": "ISABELLA_TURN",
        "outcome": {"$in": ["resolveu", "vendeu", "reteve",
                              "agendou", "avisou_proativo"]},
    })
    transferred = await db.ai_evaluations.count_documents({
        "company_id": company_id,
        "created_at": {"$gte": cutoff},
        "kind": "ISABELLA_HANDOFF",  # se existir
    })
    pct = _safe_pct(resolved, total) if total else 0.0
    # Penaliza transferências
    if total > 0:
        pct = max(0.0, pct - _safe_pct(transferred, total) * 0.3)
    score = pct if total else 70.0  # neutro se sem dados

    return {
        "score": round(score, 1),
        "turns_total": total,
        "resolved": resolved,
        "transferred_to_human": transferred,
        "resolved_pct": pct,
    }


# ── 4. PROMISE SCORE ─────────────────────────────────────────
async def promise_score(*, company_id: str,
                              hours: int = 24) -> Dict[str, Any]:
    """Promise = promises resolved / created na janela + tempo médio."""
    cutoff_dt = _now() - timedelta(hours=hours)
    created = await db.customer_promises.count_documents({
        "company_id": company_id,
        "created_at": {"$gte": cutoff_dt},
    })
    resolved = await db.customer_promises.count_documents({
        "company_id": company_id,
        "created_at": {"$gte": cutoff_dt},
        "status": "resolved",
    })
    open_count = await db.customer_promises.count_documents({
        "company_id": company_id,
        "status": "pending",
    })
    overdue = await db.customer_promises.count_documents({
        "company_id": company_id,
        "status": "pending",
        "due_at": {"$lt": _now()},
    })

    pct = _safe_pct(resolved, created) if created else 0.0
    # Penaliza overdue (cada overdue tira 5 pts até -30)
    penalty = min(30.0, overdue * 5.0)
    score = max(0.0, pct - penalty) if created else (
        100.0 if open_count == 0 else max(0.0, 100.0 - penalty))

    return {
        "score": round(score, 1),
        "created_window": created,
        "resolved_window": resolved,
        "currently_open": open_count,
        "overdue": overdue,
        "resolved_pct": pct,
    }


# ── ISABELLA INDEX ───────────────────────────────────────────
async def isabella_index(*, company_id: str,
                                hours: int = 24) -> Dict[str, Any]:
    """Composite score — média ponderada das 4 sub-scores."""
    trust = await trust_score(company_id=company_id, hours=hours)
    rel = await relationship_score(company_id=company_id, hours=hours)
    res = await resolution_score(company_id=company_id, hours=hours)
    prom = await promise_score(company_id=company_id, hours=hours)

    index = (
        trust["score"] * WEIGHTS["trust"]
        + rel["score"] * WEIGHTS["relationship"]
        + res["score"] * WEIGHTS["resolution"]
        + prom["score"] * WEIGHTS["promise"]
    )

    color = ("green" if index >= 95 else
             "amber" if index >= 90 else "red")

    return {
        "company_id": company_id,
        "window_hours": hours,
        "isabella_index": round(index, 1),
        "color": color,
        "weights": WEIGHTS,
        "scores": {
            "trust": trust,
            "relationship": rel,
            "resolution": res,
            "promise": prom,
        },
        "generated_at": _now().isoformat(),
    }


# ─── Index history (TTL 90d) ─────────────────────────────────
ISABELLA_INDEX_SNAPSHOTS = "isabella_index_snapshots"
AUTONOMY_SNAPSHOTS = "isabella_autonomy_snapshots"
AUTONOMY_ALARMS = "isabella_autonomy_alarms"


async def ensure_indexes() -> None:
    try:
        await db[ISABELLA_INDEX_SNAPSHOTS].create_index(
            [("company_id", 1), ("ts", -1)], name="cid_ts_idx")
        await db[ISABELLA_INDEX_SNAPSHOTS].create_index(
            "ts", expireAfterSeconds=90 * 86400, name="ttl_idx")
        await db[AUTONOMY_SNAPSHOTS].create_index(
            [("company_id", 1), ("ts", -1)], name="aut_cid_ts_idx")
        await db[AUTONOMY_SNAPSHOTS].create_index(
            "ts", expireAfterSeconds=90 * 86400, name="aut_ttl")
        await db[AUTONOMY_ALARMS].create_index(
            [("company_id", 1), ("triggered_at", -1)],
            name="alarm_cid_ts_idx")
    except Exception as e:
        logger.warning("[isabella_confidence] indexes: %s", e)


async def snapshot_isabella_index(*, company_id: str) -> Dict[str, Any]:
    """Salva snapshot do ISABELLA INDEX 24h (chamado pelo scheduler)."""
    r = await isabella_index(company_id=company_id, hours=24)
    await db[ISABELLA_INDEX_SNAPSHOTS].insert_one({
        "company_id": company_id,
        "ts": _now(),
        "isabella_index": r["isabella_index"],
        "color": r["color"],
        "scores": {k: v["score"] for k, v in r["scores"].items()},
    })
    return r


# ─── ALARME AUTONOMY ─────────────────────────────────────────
async def snapshot_autonomy(*, company_id: str) -> Dict[str, Any]:
    """Salva snapshot do AUTONOMY INDEX para detectar quedas."""
    from services.opportunity_executor_health import autonomy_index
    ai = await autonomy_index(company_id=company_id, hours=24)
    doc = {
        "company_id": company_id,
        "ts": _now(),
        "autonomy_index_pct": ai["autonomy_index_pct"],
        "elegiveis": ai["elegiveis_autonomas"],
        "executadas": ai["executadas_com_sucesso"],
    }
    await db[AUTONOMY_SNAPSHOTS].insert_one(doc)
    # Verifica alarme: snapshot há 24h atrás
    cutoff_24h = _now() - timedelta(hours=24)
    prev = await db[AUTONOMY_SNAPSHOTS].find_one(
        {"company_id": company_id, "ts": {"$lte": cutoff_24h}},
        sort=[("ts", -1)],
    )
    if prev:
        delta_pp = ai["autonomy_index_pct"] - prev["autonomy_index_pct"]
        if delta_pp <= -5.0:
            # Dispara alarme
            await db[AUTONOMY_ALARMS].insert_one({
                "company_id": company_id,
                "triggered_at": _now(),
                "current_pct": ai["autonomy_index_pct"],
                "previous_pct": prev["autonomy_index_pct"],
                "delta_pp": delta_pp,
                "severity": "high" if delta_pp <= -10 else "medium",
                "resolved": False,
            })
            logger.warning(
                "[autonomy_alarm] company=%s drop=%.1fpp (%.1f → %.1f)",
                company_id, delta_pp, prev["autonomy_index_pct"],
                ai["autonomy_index_pct"],
            )
            doc["alarm_triggered"] = True
            doc["delta_pp"] = delta_pp
    return doc


async def autonomy_alarms(*, company_id: str, hours: int = 168
                                ) -> Dict[str, Any]:
    """Lista alarmes recentes (default: últimos 7d)."""
    cutoff = _now() - timedelta(hours=hours)
    cursor = db[AUTONOMY_ALARMS].find(
        {"company_id": company_id, "triggered_at": {"$gte": cutoff}},
        {"_id": 0},
    ).sort("triggered_at", -1).limit(50)
    items = await cursor.to_list(50)
    return {"company_id": company_id, "items": items, "n": len(items)}


# ─── Scheduler hooks ─────────────────────────────────────────
def register_scheduler(scheduler) -> None:
    async def _hourly_snapshot():
        try:
            # Multi-tenant: itera companies ativas (subscribers > 0)
            companies = await db.subscribers.distinct("company_id")
            for cid in companies[:30]:  # cap conservador
                if not cid:
                    continue
                try:
                    await snapshot_isabella_index(company_id=cid)
                    await snapshot_autonomy(company_id=cid)
                except Exception as e:
                    logger.warning(
                        "[confidence.snapshot] cid=%s skip: %s", cid, e)
        except Exception as e:
            logger.exception("[confidence.snapshot] crash: %s", e)

    scheduler.add_job(
        _hourly_snapshot, "interval", hours=1,
        id="isabella_confidence_snapshot",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    logger.info("[isabella_confidence] hourly snapshot registered")
