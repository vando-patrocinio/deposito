"""NERVOUS FOUNDATION API — Fase 8 (Presidente IA aware).

Endpoints que o Presidente IA consome diariamente:
  GET /api/nervous/coverage              — snapshot mais recente
  GET /api/nervous/coverage/sustained    — cobertura sustentada 30d (P0)
  GET /api/nervous/silent                — módulos críticos sem metadata
  GET /api/nervous/regressions           — quedas de score detectadas
  GET /api/nervous/module/{module_id}    — score detalhado de um módulo
  GET /api/nervous/history?days=30       — série temporal
  POST /api/nervous/discover/run-now     — força rodada de autodiscovery

Tudo super-admin only (impacto plataforma).
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from fastapi import APIRouter, Depends, HTTPException, Request

from core import get_current_user
from database import db
from services.rate_limit import get_limit, limiter

router = APIRouter(prefix="/api/nervous", tags=["nervous"])


def _require_super(user: dict) -> None:
    if not ((user or {}).get("is_super_admin")
            or (user or {}).get("role") == "super_admin"):
        raise HTTPException(403, "super_admin only")


def _require_admin(user: dict) -> None:
    if (user or {}).get("is_super_admin"):
        return
    role = (user or {}).get("role") or ""
    if role not in {"super_admin", "admin", "gestor", "auditor"}:
        raise HTTPException(403, "admin only")


@router.get("/coverage")
@limiter.limit(get_limit("isabella_read"))
async def get_coverage(request: Request,
                          user: dict = Depends(get_current_user)):
    _require_admin(user)
    doc = await db.nervous_coverage_history.find_one(
        {}, {"_id": 0}, sort=[("ts", -1)])
    if not doc:
        raise HTTPException(404, "nenhum snapshot ainda — rode discover_now")
    return doc


@router.get("/coverage/sustained")
@limiter.limit(get_limit("isabella_read"))
async def get_sustained(request: Request,
                           user: dict = Depends(get_current_user)):
    _require_admin(user)
    from services.nervous_autodiscovery import _calc_sustained_coverage
    pct = await _calc_sustained_coverage()
    latest = await db.nervous_coverage_history.find_one(
        {}, {"_id": 0, "coverage_pct": 1, "ts": 1}, sort=[("ts", -1)])
    return {
        "sustained_30d_pct": pct,
        "current_pct": (latest or {}).get("coverage_pct"),
        "is_sustained_100": pct >= 100.0,
        "is_sustained_80": pct >= 80.0,
        "explanation": ("Sustained = pior cobertura nas últimas 30 medições. "
                          "Se cair 1 dia, o número quebra. Por isso a meta "
                          "real é manter, não atingir."),
    }


@router.get("/silent")
@limiter.limit(get_limit("isabella_read"))
async def get_silent(request: Request,
                       user: dict = Depends(get_current_user)):
    _require_admin(user)
    items = await db.nervous_module_registry.find(
        {"has_metadata": False},
        {"_id": 0, "module": 1, "criticality": 1, "score": 1,
         "events_24h": 1, "first_seen_at": 1}
    ).sort("criticality", 1).to_list(500)
    return {
        "count": len(items),
        "by_criticality": {
            c: sum(1 for it in items if it.get("criticality") == c)
            for c in ("critical", "high", "medium", "low")
        },
        "items": items,
    }


@router.get("/regressions")
@limiter.limit(get_limit("isabella_read"))
async def get_regressions(request: Request, days: int = 7,
                             user: dict = Depends(get_current_user)):
    _require_admin(user)
    from datetime import datetime, timedelta, timezone
    cut = (datetime.now(timezone.utc)
            - timedelta(days=min(days, 30))).isoformat()
    cur = db.nervous_coverage_history.find(
        {"ts": {"$gte": cut}}, {"_id": 0, "regressions": 1, "ts": 1})
    all_regs = []
    async for d in cur:
        for r in d.get("regressions", []):
            r["detected_at"] = d.get("ts")
            all_regs.append(r)
    return {"count": len(all_regs), "items": all_regs}


@router.get("/module/{module_path:path}")
@limiter.limit(get_limit("isabella_read"))
async def get_module(request: Request, module_path: str,
                       user: dict = Depends(get_current_user)):
    _require_admin(user)
    doc = await db.nervous_module_registry.find_one(
        {"module": module_path}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "módulo não encontrado")
    # Adiciona últimos 10 scores históricos
    history = await db.nervous_module_scores.find(
        {"module": module_path}, {"_id": 0, "score": 1, "ts": 1}
    ).sort("ts", -1).limit(10).to_list(10)
    doc["score_history"] = history
    return doc


@router.get("/history")
@limiter.limit(get_limit("isabella_read"))
async def get_history(request: Request, days: int = 30,
                        user: dict = Depends(get_current_user)):
    _require_admin(user)
    from datetime import datetime, timedelta, timezone
    cut = (datetime.now(timezone.utc)
            - timedelta(days=min(days, 90))).isoformat()
    items = await db.nervous_coverage_history.find(
        {"ts": {"$gte": cut}},
        {"_id": 0, "ts": 1, "coverage_pct": 1, "average_score": 1,
         "metadata_coverage_pct": 1, "silent_critical_count": 1,
         "by_criticality": 1}
    ).sort("ts", -1).to_list(200)
    return {"count": len(items), "items": items}


@router.post("/discover/run-now")
@limiter.limit(get_limit("isabella_write"))
async def discover_now(request: Request,
                          user: dict = Depends(get_current_user)):
    _require_super(user)
    from services.nervous_autodiscovery import discover_and_score
    return await discover_and_score()


# ─── Orphan Watcher + Quarantine ───────────────────────────────
@router.post("/orphan/scan-now")
@limiter.limit(get_limit("isabella_write"))
async def orphan_scan(request: Request,
                         user: dict = Depends(get_current_user)):
    _require_super(user)
    from services.orphan_event_watcher import scan_orphans
    return await scan_orphans(window_minutes=10)


@router.get("/quarantine")
@limiter.limit(get_limit("isabella_read"))
async def quarantine_list(request: Request,
                              user: dict = Depends(get_current_user)):
    _require_admin(user)
    from services.orphan_event_watcher import quarantined_list, orphan_status_24h
    return {"active": await quarantined_list(),
              "status_24h": await orphan_status_24h()}


@router.post("/quarantine/{source}/release")
@limiter.limit(get_limit("isabella_write"))
async def quarantine_release(request: Request, source: str,
                                 justificativa: str = "",
                                 user: dict = Depends(get_current_user)):
    _require_super(user)
    if not justificativa or len(justificativa) < 10:
        raise HTTPException(400, "justificativa é obrigatória (≥10 chars)")
    from services.orphan_event_watcher import release_source
    return await release_source(
        source=source, justificativa=justificativa,
        released_by=(user.get("email") or user.get("id") or "?"))


@router.get("/presidente/brief")
@limiter.limit(get_limit("isabella_read"))
async def presidente_brief(request: Request,
                              user: dict = Depends(get_current_user)):
    """Resumo executivo pro Presidente IA — Fase 8.
    1 chamada, retorna tudo que ele precisa contar no daily brief."""
    _require_admin(user)
    from services.nervous_autodiscovery import _calc_sustained_coverage
    latest = await db.nervous_coverage_history.find_one(
        {}, {"_id": 0}, sort=[("ts", -1)])
    sustained = await _calc_sustained_coverage()
    silent_crit_n = (latest or {}).get("silent_critical_count", 0)
    new_mods = len((latest or {}).get("new_modules_detected", []))
    regressions = (latest or {}).get("regressions", [])
    return {
        "today_coverage_pct": (latest or {}).get("coverage_pct"),
        "today_avg_score": (latest or {}).get("average_score"),
        "sustained_30d_pct": sustained,
        "silent_critical_count": silent_crit_n,
        "new_modules_detected_today": new_mods,
        "regressions_count": len(regressions),
        "by_criticality_ok_pct": (latest or {}).get("by_criticality"),
        "risk_level": _risk_level((latest or {}).get("coverage_pct") or 0,
                                     silent_crit_n, len(regressions)),
        "ts": (latest or {}).get("ts"),
        "narrative": _build_narrative(latest, sustained),
    }


def _risk_level(cov: float, silent_n: int, reg_n: int) -> str:
    if silent_n > 0 or reg_n > 0 or cov < 60:
        return "VERMELHO"
    if cov < 80:
        return "AMARELO"
    return "VERDE"


def _build_narrative(latest: dict, sustained: float) -> str:
    if not latest:
        return ("Sistema Nervoso ainda sem snapshot — rode "
                  "POST /api/nervous/discover/run-now.")
    cov = latest.get("coverage_pct", 0)
    silent_crit = latest.get("silent_critical_count", 0)
    new = len(latest.get("new_modules_detected", []))
    regs = len(latest.get("regressions", []))
    lines = [
        f"Cobertura nervosa hoje: {cov}% (avg score {latest.get('average_score')})."
    ]
    if sustained > 0:
        lines.append(f"Sustained 30d: {sustained}% (pior medição da janela).")
    if silent_crit > 0:
        lines.append(f"🚨 {silent_crit} módulo(s) CRÍTICO(s) sem metadata.")
    if regs:
        lines.append(f"🔴 {regs} regressão(ões) detectada(s) — score caiu.")
    if new:
        lines.append(f"🆕 {new} módulo(s) novo(s) detectado(s).")
    by = latest.get("by_criticality") or {}
    if by:
        lines.append(
            f"Por criticidade OK: critical {by.get('critical')}% · "
            f"high {by.get('high')}% · medium {by.get('medium')}%")
    return " ".join(lines)
