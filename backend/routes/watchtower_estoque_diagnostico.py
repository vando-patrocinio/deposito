"""Watchtower Estoque · Diagnóstico (Onda C P1) — EKG da Lousa Mobile.

Endpoint dedicado para visão operacional/saúde do fluxo de fechamento de OS.
Lê apenas (READ-ONLY) collections de telemetria:

  • `lousa_finalize_trace`        — 6-phase trace (Onda B Bug #3)
  • `late_close_runs`             — Worker pós-fechamento (Onda B)
  • `stok_reconcile_runs`         — Cron diário órfãs (Onda B)
  • `auto_ont_swap_events`        — Auto-detect troca (Onda C Bug #6)
  • `auto_close_legacy_observability` — sunset legacy auto_close

Retorna pacote único `GET /api/watchtower/estoque/diagnostico`:
  - phases: {phase, ok, error, not_ok, total, last_error?}
  - latency_ms_p50/p95 (entry→exit por ticket nas últimas 24h)
  - late_close: last_run + 7d aggregate
  - reconcile: last_run + 7d aggregate
  - swap_pending: count + top 5 técnicos
  - recent_errors: últimas 20 fases com error != null

Sem cache — sempre fresco (operacional).
"""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from core import DEMO_COMPANY_ID, require_role
from database import db

logger = logging.getLogger("watchtower.estoque.diagnostico")

router = APIRouter(
    prefix="/api/watchtower/estoque",
    tags=["watchtower_estoque_diagnostico"],
)

PHASES = [
    ("01_entry", "01 · Entry"),
    ("02_guardrail", "02 · Guardrail"),
    ("03_ticket_updated", "03 · Ticket Updated"),
    ("04_pre_auto_close", "04 · Pre Auto-Close"),
    ("05_post_auto_close", "05 · Post Auto-Close"),
    ("06_exit", "06 · Exit"),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────── 6-PHASE AGGREGATIONS ────────────────────────────

async def _agg_phases(cid: str, since: datetime) -> List[Dict[str, Any]]:
    """Agrupa lousa_finalize_trace por fase e outcome nas últimas 24h."""
    pipeline = [
        {"$match": {"company_id": cid, "ts": {"$gte": since}}},
        {"$group": {
            "_id": {"phase": "$phase", "outcome": "$outcome"},
            "n": {"$sum": 1},
        }},
    ]
    rows = await db.lousa_finalize_trace.aggregate(pipeline).to_list(60)
    agg: Dict[str, Dict[str, int]] = {p: {"ok": 0, "error": 0, "not_ok": 0}
                                         for p, _ in PHASES}
    for r in rows:
        ph = (r["_id"].get("phase") or "")
        outcome = (r["_id"].get("outcome") or "ok").lower()
        if ph not in agg:
            continue
        if outcome not in ("ok", "error", "not_ok"):
            outcome = "ok"
        agg[ph][outcome] += int(r.get("n") or 0)

    # Último erro por fase (texto + ticket_id + ts)
    last_errors: Dict[str, Dict[str, Any]] = {}
    cur = db.lousa_finalize_trace.find(
        {"company_id": cid, "ts": {"$gte": since}, "error": {"$ne": None}},
        {"_id": 0, "phase": 1, "error": 1, "ticket_id": 1, "ts": 1},
    ).sort("ts", -1).limit(60)
    async for d in cur:
        ph = d.get("phase")
        if ph and ph in agg and ph not in last_errors:
            last_errors[ph] = {
                "ticket_id": d.get("ticket_id"),
                "error": (d.get("error") or "")[:300],
                "ts": (d.get("ts").isoformat()
                        if isinstance(d.get("ts"), datetime) else d.get("ts")),
            }

    out: List[Dict[str, Any]] = []
    for ph, label in PHASES:
        c = agg[ph]
        total = c["ok"] + c["error"] + c["not_ok"]
        success_rate = round((c["ok"] / total * 100), 1) if total else None
        out.append({
            "phase": ph,
            "label": label,
            "ok": c["ok"],
            "error": c["error"],
            "not_ok": c["not_ok"],
            "total": total,
            "success_rate_pct": success_rate,
            "last_error": last_errors.get(ph),
        })
    return out


async def _agg_latency(cid: str, since: datetime) -> Dict[str, Any]:
    """Latência por ticket: ts(06_exit) - ts(01_entry). Calcula p50/p95."""
    # Coleta entry+exit por ticket
    cur = db.lousa_finalize_trace.find(
        {"company_id": cid, "ts": {"$gte": since},
         "phase": {"$in": ["01_entry", "06_exit"]}},
        {"_id": 0, "ticket_id": 1, "phase": 1, "ts": 1},
    )
    bucket: Dict[str, Dict[str, datetime]] = defaultdict(dict)
    async for d in cur:
        tid = d.get("ticket_id")
        if not tid:
            continue
        ts = d.get("ts")
        if not isinstance(ts, datetime):
            continue
        if d.get("phase") == "01_entry":
            # primeiro entry vence (caso 2 retries)
            bucket[tid].setdefault("entry", ts)
        elif d.get("phase") == "06_exit":
            # último exit vence (caso retry tenha sucesso)
            bucket[tid]["exit"] = ts

    durations_ms: List[float] = []
    for tid, kv in bucket.items():
        e, x = kv.get("entry"), kv.get("exit")
        if e and x and x >= e:
            durations_ms.append((x - e).total_seconds() * 1000)
    if not durations_ms:
        return {"samples": 0, "p50_ms": None, "p95_ms": None,
                "max_ms": None, "completed_pct": None}
    durations_ms.sort()
    p50 = statistics.median(durations_ms)
    # p95 via interpolation
    idx = int(0.95 * (len(durations_ms) - 1))
    p95 = durations_ms[idx]
    completed = sum(1 for kv in bucket.values()
                    if kv.get("entry") and kv.get("exit"))
    completed_pct = (round(completed / len(bucket) * 100, 1)
                     if bucket else None)
    return {
        "samples": len(durations_ms),
        "p50_ms": round(p50, 1),
        "p95_ms": round(p95, 1),
        "max_ms": round(max(durations_ms), 1),
        "completed_pct": completed_pct,
        "started_count": len(bucket),
    }


# ─────────────────────── WORKERS ─────────────────────────────────────────

async def _agg_late_close(cid: Optional[str], since: datetime) -> Dict[str, Any]:
    """Sumário do late_close_worker."""
    # Filtra por company_filter exato OU global (None significa "todas")
    match_company = ({} if not cid else
                     {"$or": [{"company_filter": cid},
                              {"company_filter": None}]})
    # Últimas 7d
    runs = await db.late_close_runs.find(
        {**match_company, "started_at": {"$gte": since}},
        {"_id": 0},
    ).sort("started_at", -1).to_list(200)
    last = runs[0] if runs else None
    total_closed = sum(r.get("closed_ok", 0) for r in runs)
    total_failed = sum(r.get("closed_failed", 0) for r in runs)
    total_candidates = sum(r.get("candidates_found", 0) for r in runs)
    return {
        "runs_7d": len(runs),
        "total_candidates_7d": total_candidates,
        "total_closed_ok_7d": total_closed,
        "total_closed_failed_7d": total_failed,
        "last_run": ({
            "started_at": _iso(last.get("started_at")),
            "finished_at": _iso(last.get("finished_at")),
            "duration_ms": last.get("duration_ms"),
            "candidates_found": last.get("candidates_found"),
            "closed_ok": last.get("closed_ok"),
            "closed_failed": last.get("closed_failed"),
            "company_filter": last.get("company_filter"),
            "dry_run": last.get("dry_run"),
        } if last else None),
    }


async def _agg_reconcile(since: datetime) -> Dict[str, Any]:
    """Sumário do stok_reconcile_job (não tem company_id por design — global)."""
    runs = await db.stok_reconcile_runs.find(
        {"started_at": {"$gte": since}},
        {"_id": 0},
    ).sort("started_at", -1).to_list(50)
    last = runs[0] if runs else None
    total_orphans = sum(r.get("total_orphan_marked", 0) for r in runs)
    total_scanned = sum(r.get("total_scanned", 0) for r in runs)
    return {
        "runs_7d": len(runs),
        "total_scanned_7d": total_scanned,
        "total_orphan_marked_7d": total_orphans,
        "last_run": ({
            "started_at": _iso(last.get("started_at")),
            "total_scanned": last.get("total_scanned"),
            "total_orphan_marked": last.get("total_orphan_marked"),
            "total_valid": last.get("total_valid"),
            "alerts_raised_count": len(last.get("alerts_raised", []) or []),
        } if last else None),
    }


# ─────────────────────── ONT SWAP PENDING ────────────────────────────────

async def _agg_swap_pending(cid: str) -> Dict[str, Any]:
    """Eventos AUTO_ONT_SWAP_DETECTED que ainda estão pending_confirmation."""
    base_match = {"company_id": cid, "status": "pending_confirmation"}
    total = await db.auto_ont_swap_events.count_documents(base_match)
    # Top 5 técnicos
    pipeline = [
        {"$match": base_match},
        {"$group": {"_id": "$technician_id", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": 5},
    ]
    by_tech_rows = await db.auto_ont_swap_events.aggregate(pipeline).to_list(10)
    # Resolve nomes
    tech_ids = [r["_id"] for r in by_tech_rows if r.get("_id")]
    tech_docs = {}
    if tech_ids:
        async for c in db.collaborators.find(
                {"id": {"$in": tech_ids}}, {"_id": 0, "id": 1, "name": 1}):
            tech_docs[c["id"]] = c.get("name")
    top_techs = [{
        "technician_id": r["_id"],
        "technician_name": tech_docs.get(r["_id"], "—"),
        "pending_count": r["n"],
    } for r in by_tech_rows]
    # Últimos 10 eventos
    last_cur = db.auto_ont_swap_events.find(
        base_match,
        {"_id": 0, "id": 1, "ticket_id": 1, "ont_anterior": 1,
         "ont_atual": 1, "technician_id": 1, "detected_at": 1,
         "ticket_type": 1},
    ).sort("detected_at", -1).limit(10)
    last_events = []
    async for d in last_cur:
        last_events.append({
            **d,
            "technician_name": tech_docs.get(d.get("technician_id"), "—"),
        })
    return {
        "total_pending": total,
        "top_techs": top_techs,
        "last_events": last_events,
    }


# ─────────────────────── RECENT ERRORS ───────────────────────────────────

async def _recent_errors(cid: str, since: datetime, limit: int = 20) -> List[Dict[str, Any]]:
    """Últimos N traces com `error != None` — flat, ordenado desc."""
    cur = db.lousa_finalize_trace.find(
        {"company_id": cid, "ts": {"$gte": since}, "error": {"$ne": None}},
        {"_id": 0, "phase": 1, "error": 1, "ticket_id": 1, "ts": 1,
         "outcome": 1, "details": 1},
    ).sort("ts", -1).limit(limit)
    out = []
    async for d in cur:
        out.append({
            "phase": d.get("phase"),
            "outcome": d.get("outcome"),
            "ticket_id": d.get("ticket_id"),
            "error": (d.get("error") or "")[:400],
            "ts": _iso(d.get("ts")),
            "result_reason": (d.get("details") or {}).get("result_reason"),
        })
    return out


# ─────────────────────── HELPERS ─────────────────────────────────────────

def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


# ─────────────────────── ENDPOINT ────────────────────────────────────────

@router.get("/diagnostico")
async def watchtower_estoque_diagnostico(
    user: dict = Depends(require_role("gestor", "administrador", "auditor")),
    window_hours: int = Query(24, ge=1, le=168,
                              description="Janela de análise (1-168h)"),
) -> Dict[str, Any]:
    """EKG da Lousa Mobile — saúde do fluxo de fechamento de OS.

    Cobertura:
      - 6-phase trace (success / error / not_ok / latency).
      - late_close_worker stats (últimas 7d).
      - stok_reconcile_job stats (últimas 7d).
      - auto_ont_swap_events pending_confirmation.
      - Últimos 20 erros com traceback.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    since = _now() - timedelta(hours=window_hours)
    since_7d = _now() - timedelta(days=7)

    import asyncio
    (phases, latency, late_close, reconcile, swap_pending,
     recent_errors) = await asyncio.gather(
        _agg_phases(cid, since),
        _agg_latency(cid, since),
        _agg_late_close(cid, since_7d),
        _agg_reconcile(since_7d),
        _agg_swap_pending(cid),
        _recent_errors(cid, since, limit=20),
        return_exceptions=False,
    )

    return {
        "company_id": cid,
        "generated_at": _now().isoformat(),
        "window_hours": window_hours,
        "phases": phases,
        "latency": latency,
        "late_close": late_close,
        "reconcile": reconcile,
        "swap_pending": swap_pending,
        "recent_errors": recent_errors,
    }
