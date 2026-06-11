"""NERVOUS AUTODISCOVERY + SCORE + SUSTAINED COVERAGE — Fases 4/5/7/8.

Roda diariamente via APScheduler (Fase 4). A cada execução:
  1. Escaneia todos os módulos backend (autodiscovery)
  2. Registra/atualiza `nervous_module_registry` com metadata declarado
  3. Calcula score 0-100 por módulo (Fase 5)
  4. Atualiza `nervous_coverage_history` com snapshot (Fase 7)
  5. Detecta REGRESSÕES (queda de score) e abre opp no Conselho IA
  6. API expõe pro Presidente IA (Fase 8)

Score (0-100):
  +30 — tem NERVOUS_METADATA declarado e válido
  +30 — se criticality ∈ {critical,high} → emits_events=True
  +20 — chama emit_event no código (coerente com metadata)
  +20 — eventos REAIS emitidos nas últimas 24h (motor_ia_events)

Cobertura sustentada (Fase 7):
  - Snapshot diário em `nervous_coverage_history`
  - "Sustained" = score>=80 por 30 dias consecutivos
"""
from __future__ import annotations

import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apscheduler.triggers.cron import CronTrigger

from database import db
from scripts.nervous_linter import lint
from services.nervous_contract import infer_criticality

log = logging.getLogger("ponto.nervous_auto")
REGISTRY_COLL = "nervous_module_registry"
HISTORY_COLL = "nervous_coverage_history"
SCORE_COLL = "nervous_module_scores"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _module_id(file_path: str) -> str:
    """Gera id estável a partir do caminho relativo."""
    return file_path.replace("/", ".").replace(".py", "")


async def _events_emitted_recently(file_path: str,
                                       window_h: int = 24) -> int:
    """Conta eventos cuja source corresponda ao módulo nas últimas N horas."""
    # source convention: nome do arquivo sem .py (módulo lógico)
    module_name = Path(file_path).stem
    cutoff = (_now() - timedelta(hours=window_h)).isoformat()
    return await db.motor_ia_events.count_documents({
        "source": {"$regex": module_name, "$options": "i"},
        "timestamp": {"$gte": cutoff},
    })


def _compute_score(*, has_metadata: bool, metadata: dict | None,
                     criticality: str, calls_emit: bool,
                     events_24h: int) -> int:
    score = 0
    if has_metadata and metadata and not _has_errors(metadata):
        score += 30
    if (metadata and metadata.get("emits_events")
            and criticality in {"critical", "high"}):
        score += 30
    if calls_emit:
        score += 20
    if events_24h > 0:
        score += 20
    return min(score, 100)


def _has_errors(metadata: dict) -> bool:
    from services.nervous_contract import validate_dict
    return bool(validate_dict(metadata))


async def discover_and_score() -> Dict[str, Any]:
    """Rotina principal — chamada pelo scheduler."""
    report = lint()
    snapshot_id = f"nerv-{_now().strftime('%Y%m%d-%H%M%S')}"
    total = report["total_files"]
    BACKEND = Path("/app/backend")

    # Re-scan files para detalhar metadata
    files = sorted(set(
        [v["file"] for v in report["violations"]]
        + [f"{d}/{Path(f).name}" for d in [] for f in []]  # placeholder
    ))
    # melhor: rescan diretamente via filesystem
    from scripts.nervous_linter import _extract_metadata, _scan_files, _calls_emit_event
    all_files = _scan_files()

    score_docs: List[Dict[str, Any]] = []
    silent_critical: List[str] = []
    new_modules: List[str] = []
    sum_scores = 0
    declared = 0
    crit_buckets: Dict[str, Dict[str, int]] = {
        c: {"total": 0, "ok": 0, "events_24h_total": 0}
        for c in ("critical", "high", "medium", "low")
    }

    for f in all_files:
        rel = str(f.relative_to(BACKEND))
        md, _err = _extract_metadata(f)
        calls = _calls_emit_event(f)
        inferred = infer_criticality(rel)
        criticality = (md.get("criticality") if md else None) or inferred
        evt_n = await _events_emitted_recently(rel, window_h=24)
        score = _compute_score(
            has_metadata=md is not None, metadata=md,
            criticality=criticality, calls_emit=calls, events_24h=evt_n)
        if md:
            declared += 1
        sum_scores += score
        if criticality == "critical" and not md:
            silent_critical.append(rel)
        # detecta novo módulo (não está no registry ainda)
        existing = await db[REGISTRY_COLL].find_one(
            {"module": rel}, {"_id": 0, "first_seen_at": 1})
        if not existing:
            new_modules.append(rel)
        # upsert registry
        await db[REGISTRY_COLL].update_one(
            {"module": rel},
            {
                "$set": {
                    "module": rel, "owner": (md or {}).get("owner"),
                    "domain": (md or {}).get("domain"),
                    "criticality": criticality,
                    "emits_events": (md or {}).get("emits_events", False),
                    "event_types": (md or {}).get("event_types") or [],
                    "has_metadata": md is not None,
                    "calls_emit_in_code": calls,
                    "events_24h": evt_n,
                    "score": score,
                    "last_seen_at": _now().isoformat(),
                },
                "$setOnInsert": {"first_seen_at": _now().isoformat()},
            }, upsert=True)
        # score history (para regressão)
        score_docs.append({
            "id": f"sc-{uuid.uuid4().hex[:10]}",
            "snapshot_id": snapshot_id,
            "module": rel, "score": score,
            "criticality": criticality,
            "has_metadata": md is not None,
            "events_24h": evt_n,
            "ts": _now().isoformat(),
        })
        b = crit_buckets[criticality]
        b["total"] += 1
        if score >= 80:
            b["ok"] += 1
        b["events_24h_total"] += evt_n

    if score_docs:
        await db[SCORE_COLL].insert_many(score_docs)

    # ─── REGRESSÕES (Fase 7) ──────────────────────────────────────
    # módulo cujo score caiu >=20 vs snapshot anterior
    regressions: List[Dict[str, Any]] = []
    prior_cursor = db[SCORE_COLL].aggregate([
        {"$match": {"snapshot_id": {"$ne": snapshot_id}}},
        {"$sort": {"ts": -1}},
        {"$group": {"_id": "$module",
                      "last_score": {"$first": "$score"},
                      "last_ts": {"$first": "$ts"}}},
    ])
    prior_map = {r["_id"]: r async for r in prior_cursor}
    for sd in score_docs:
        p = prior_map.get(sd["module"])
        if p and (p["last_score"] - sd["score"]) >= 20:
            regressions.append({
                "module": sd["module"],
                "before": p["last_score"], "after": sd["score"],
                "drop": p["last_score"] - sd["score"],
            })
    # Abre opp no Conselho se houver regressão crítica
    for r in regressions:
        if r["drop"] >= 30:
            try:
                await db.isabella_commander_opportunities.insert_one({
                    "id": f"opp-nerv-{uuid.uuid4().hex[:10]}",
                    "company_id": "co-demo",
                    "kind": "nervous_regression",
                    "subkind": "score_drop",
                    "score": 90, "probability": 1.0, "status": "pending",
                    "target_label": f"Regressão nervosa em {r['module']}",
                    "evidence": r,
                    "reason_codes": ["nervous_score_dropped_30+"],
                    "recommended_action": {
                        "type": "review_module",
                        "message": (f"Score caiu de {r['before']} pra "
                                     f"{r['after']}. Verificar se algum dev "
                                     "removeu emit_event ou alterou metadata."),
                    },
                    "created_at": _now().isoformat(),
                })
            except Exception as e:
                log.warning("[nervous_auto] opp regression failed: %s", e)

    # ─── SNAPSHOT COBERTURA ───────────────────────────────────────
    coverage_pct = round(sum_scores / max(total * 100, 1) * 100, 2)
    by_crit: Dict[str, float] = {}
    for k, b in crit_buckets.items():
        if b["total"]:
            by_crit[k] = round(b["ok"] / b["total"] * 100, 2)
        else:
            by_crit[k] = 0.0

    snap = {
        "id": snapshot_id, "ts": _now().isoformat(),
        "total_modules": total,
        "declared_metadata": declared,
        "metadata_coverage_pct": round(declared / max(total, 1) * 100, 2),
        "average_score": round(sum_scores / max(total, 1), 2),
        "coverage_pct": coverage_pct,
        "by_criticality": by_crit,
        "silent_critical_modules": silent_critical,
        "silent_critical_count": len(silent_critical),
        "new_modules_detected": new_modules,
        "regressions": regressions,
    }
    await db[HISTORY_COLL].insert_one(dict(snap))

    # ─── COBERTURA SUSTENTADA (Fase 7) ────────────────────────────
    sustained = await _calc_sustained_coverage()
    snap["sustained_30d_coverage_pct"] = sustained
    log.info("[nervous_auto] snapshot=%s cov=%s avg=%s critical_ok=%s "
              "regressions=%d new=%d",
              snapshot_id, coverage_pct, snap["average_score"],
              by_crit.get("critical"), len(regressions), len(new_modules))
    return snap


async def _calc_sustained_coverage() -> float:
    """Menor cobertura nos últimos 30 snapshots diários.
    Sustained = mínimo (a corrente é tão forte quanto o elo mais fraco)."""
    cut = (_now() - timedelta(days=30)).isoformat()
    cur = db[HISTORY_COLL].find(
        {"ts": {"$gte": cut}}, {"_id": 0, "coverage_pct": 1, "ts": 1}
    ).sort("ts", -1).limit(30)
    pcts = [d["coverage_pct"] async for d in cur if "coverage_pct" in d]
    if len(pcts) < 30:
        return 0.0  # ainda não tem histórico suficiente
    return min(pcts)


async def ensure_indexes() -> None:
    try:
        await db[REGISTRY_COLL].create_index("module", unique=True)
        await db[REGISTRY_COLL].create_index("criticality")
        await db[REGISTRY_COLL].create_index("score")
        await db[HISTORY_COLL].create_index([("ts", -1)])
        await db[SCORE_COLL].create_index([("module", 1), ("ts", -1)])
        await db[SCORE_COLL].create_index([("snapshot_id", 1)])
    except Exception as e:
        log.warning("[nervous_auto] indexes: %s", e)


async def daily_job():
    try:
        await discover_and_score()
    except Exception as e:
        log.error("[nervous_auto] daily_job crashed: %r", e)


def register_scheduler(scheduler) -> None:
    scheduler.add_job(
        daily_job,
        CronTrigger(hour=5, minute=0),  # 05:00 UTC depois do shield audit
        id="nervous_autodiscovery",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    log.info("[startup] nervous_autodiscovery registered (05:00 UTC)")
