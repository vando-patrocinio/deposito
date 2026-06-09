"""
generate_cto_report.py — Auditoria CTO da Sprint 7
Sistema Nervoso Corporativo (Event Bus + Schedulers + Decision/Action + Estrategista)

Coleta evidências REAIS do MongoDB local e devolve um JSON com 13 blocos
respondendo às perguntas do CTO. Não loga nada inventado. Quando uma
coleção/coluna não existir, retorna explicitamente "missing".

Uso:
    cd /app/backend && python scripts/generate_cto_report.py
    cd /app/backend && python scripts/generate_cto_report.py --seed   # popula
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# garante import do projeto
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import db  # noqa: E402


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hours_ago(h: int) -> str:
    return _iso(_now() - timedelta(hours=h))


def _safe(fn):
    """Decora coroutine para nunca explodir o relatório."""
    async def wrapper(*a, **kw):
        try:
            return await fn(*a, **kw)
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {e}",
                    "trace": traceback.format_exc(limit=2)}
    return wrapper


# ───────────────────────────────────────────────────────────────────────
# Perguntas
# ───────────────────────────────────────────────────────────────────────
@_safe
async def q1_event_bus_real() -> dict:
    """1. O event bus é real? Quantos eventos foram registrados e quais
    são os índices da coleção motor_ia_events?"""
    total = await db.motor_ia_events.count_documents({})
    last24 = await db.motor_ia_events.count_documents(
        {"timestamp": {"$gte": _hours_ago(24)}})
    last7d = await db.motor_ia_events.count_documents(
        {"timestamp": {"$gte": _hours_ago(24 * 7)}})
    consumed = await db.motor_ia_events.count_documents({"consumed": True})
    pending = await db.motor_ia_events.count_documents({"consumed": False})

    sample = []
    async for d in db.motor_ia_events.find({}, {"_id": 0}).sort(
            "timestamp", -1).limit(3):
        sample.append(d)

    idx_info = []
    try:
        async for idx in db.motor_ia_events.list_indexes():
            idx_info.append({
                "name": idx.get("name"),
                "key": list((idx.get("key") or {}).items()),
                "unique": idx.get("unique", False),
            })
    except Exception as e:  # noqa: BLE001
        idx_info = [{"error": str(e)}]

    return {
        "total_events": total,
        "last_24h": last24,
        "last_7d": last7d,
        "consumed": consumed,
        "pending": pending,
        "indexes": idx_info,
        "indexes_count": len(idx_info),
        "sample_recent": sample,
    }


@_safe
async def q2_event_types_distribution() -> dict:
    """2. Quais tipos de eventos foram capturados e em qual frequência?"""
    pipe = [
        {"$group": {"_id": "$event_type", "n": {"$sum": 1},
                      "last": {"$max": "$timestamp"}}},
        {"$sort": {"n": -1}},
        {"$limit": 30},
    ]
    by_type = []
    async for r in db.motor_ia_events.aggregate(pipe):
        by_type.append({
            "event_type": r.get("_id") or "<null>",
            "count": r["n"],
            "last_seen": r.get("last"),
        })
    pipe2 = [
        {"$group": {"_id": "$severity", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
    ]
    by_sev = []
    async for r in db.motor_ia_events.aggregate(pipe2):
        by_sev.append({"severity": r.get("_id") or "<null>",
                       "count": r["n"]})
    pipe3 = [
        {"$group": {"_id": "$source", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": 15},
    ]
    by_source = []
    async for r in db.motor_ia_events.aggregate(pipe3):
        by_source.append({"source": r.get("_id") or "<null>",
                          "count": r["n"]})
    return {
        "by_event_type": by_type,
        "by_severity": by_sev,
        "by_source": by_source,
        "distinct_types": len(by_type),
    }


@_safe
async def q3_memoria_collections() -> dict:
    """3. As 7 coleções de memória existem? Quantos docs em cada uma?
    Têm índices?"""
    cols = [
        "motor_ia_events", "motor_ia_memory", "motor_ia_insights",
        "motor_ia_predictions", "motor_ia_decisions",
        "motor_ia_actions", "motor_ia_outcomes", "motor_ia_learnings",
    ]
    existing = set(await db.list_collection_names())
    out = []
    for c in cols:
        info = {"name": c, "exists": c in existing}
        if info["exists"]:
            info["count"] = await db[c].estimated_document_count()
            info["recent_count_24h"] = await db[c].count_documents(
                {"$or": [
                    {"timestamp": {"$gte": _hours_ago(24)}},
                    {"created_at": {"$gte": _hours_ago(24)}},
                ]})
            idxs = []
            try:
                async for i in db[c].list_indexes():
                    idxs.append(i.get("name"))
            except Exception:
                idxs = ["<list_indexes failed>"]
            info["indexes"] = idxs
        out.append(info)
    return {"collections": out,
            "total_collections_in_db": len(existing)}


@_safe
async def q4_data_quality_evidence() -> dict:
    """4. O Data Quality Scan roda? Qual o score atual e quais issues
    reais ele encontrou?"""
    last_scans = []
    async for d in db.motor_ia_insights.find(
            {"kind": "data_quality_scan"}, {"_id": 0}
    ).sort("created_at", -1).limit(3):
        last_scans.append({
            "id": d.get("id"),
            "score": d.get("score"),
            "status": d.get("status"),
            "generated_at": d.get("generated_at"),
            "issues_count": len(d.get("issues") or []),
            "worst_issues": sorted(
                d.get("issues") or [],
                key=lambda i: i.get("pct_clean", 100))[:5],
        })
    # roda um scan ao vivo agora para comprovar
    live = {"error": "not_run"}
    try:
        from services.data_quality import run_scan
        t0 = time.time()
        live_full = await run_scan()
        elapsed_ms = int((time.time() - t0) * 1000)
        live = {
            "score": live_full.get("score"),
            "status": live_full.get("status"),
            "issues_count": len(live_full.get("issues") or []),
            "worst_issues": sorted(
                live_full.get("issues") or [],
                key=lambda i: i.get("pct_clean", 100))[:5],
            "elapsed_ms": elapsed_ms,
        }
    except Exception as e:  # noqa: BLE001
        live = {"error": str(e)}
    return {"recent_scans": last_scans, "live_run_now": live}


@_safe
async def q5_security_detectors() -> dict:
    """5. Os detectores de segurança disparam? Mostre alertas reais."""
    from services.audit_alerts import scan_security_alerts
    alerts = await scan_security_alerts()
    # contagens base nas últimas 24h
    by_cat = {}
    for cat in ("export", "destructive", "rbac_blocked",
                 "impersonate"):
        by_cat[cat] = await db.audit_log.count_documents(
            {"category": cat, "created_at": {"$gte": _hours_ago(24)}})
    by_cat_7d = {}
    for cat in ("export", "destructive", "rbac_blocked",
                 "impersonate"):
        by_cat_7d[cat] = await db.audit_log.count_documents(
            {"category": cat,
             "created_at": {"$gte": _hours_ago(24 * 7)}})
    return {
        "live_alerts_count": len(alerts),
        "live_alerts_sample": alerts[:5],
        "audit_log_last_24h_by_category": by_cat,
        "audit_log_last_7d_by_category": by_cat_7d,
    }


@_safe
async def q6_decision_engine() -> dict:
    """6. O Decision Engine produz decisões? Quais regras dispararam
    e quais sem decisão?"""
    total = await db.motor_ia_decisions.count_documents({})
    last24 = await db.motor_ia_decisions.count_documents(
        {"created_at": {"$gte": _hours_ago(24)}})
    executed = await db.motor_ia_decisions.count_documents(
        {"executed": True})
    pending = await db.motor_ia_decisions.count_documents(
        {"executed": False})
    pipe = [
        {"$group": {"_id": "$action_type", "n": {"$sum": 1},
                      "avg_conf": {"$avg": "$confidence"}}},
        {"$sort": {"n": -1}},
    ]
    by_type = []
    async for r in db.motor_ia_decisions.aggregate(pipe):
        by_type.append({
            "action_type": r.get("_id") or "<null>",
            "count": r["n"],
            "avg_confidence": round(r.get("avg_conf") or 0, 3),
        })
    sample = []
    async for d in db.motor_ia_decisions.find({}, {"_id": 0}).sort(
            "created_at", -1).limit(3):
        sample.append({
            "id": d.get("id"),
            "title": d.get("title"),
            "action_type": d.get("action_type"),
            "confidence": d.get("confidence"),
            "executed": d.get("executed"),
            "reasoning": (d.get("reasoning") or "")[:240],
            "trigger_event_id": d.get("trigger_event_id"),
        })
    # roda um ciclo agora
    cycle = {"error": "not_run"}
    try:
        from services.decision_engine import run_decision_cycle
        t0 = time.time()
        c = await run_decision_cycle()
        c["elapsed_ms"] = int((time.time() - t0) * 1000)
        cycle = c
    except Exception as e:  # noqa: BLE001
        cycle = {"error": str(e)}
    return {
        "total_decisions": total,
        "last_24h": last24,
        "executed": executed,
        "pending": pending,
        "by_action_type": by_type,
        "sample_recent": sample,
        "live_cycle_now": cycle,
    }


@_safe
async def q7_action_engine() -> dict:
    """7. O Action Engine executa? Qual é o modo (live x dry-run) e
    qual a taxa de sucesso?"""
    total = await db.motor_ia_actions.count_documents({})
    by_status = {}
    for s in ("done", "failed", "running"):
        by_status[s] = await db.motor_ia_actions.count_documents(
            {"status": s})
    by_type = []
    pipe = [
        {"$group": {"_id": "$action_type", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
    ]
    async for r in db.motor_ia_actions.aggregate(pipe):
        by_type.append({"action_type": r.get("_id") or "<null>",
                        "count": r["n"]})
    dry_runs = await db.motor_ia_actions.count_documents(
        {"dry_run": True})
    live = await db.motor_ia_actions.count_documents(
        {"dry_run": False})

    out_ok = await db.motor_ia_outcomes.count_documents({"ok": True})
    out_fail = await db.motor_ia_outcomes.count_documents({"ok": False})
    out_total = await db.motor_ia_outcomes.count_documents({})

    sample_outcomes = []
    async for o in db.motor_ia_outcomes.find({}, {"_id": 0}).sort(
            "created_at", -1).limit(3):
        sample_outcomes.append({
            "id": o.get("id"),
            "decision_id": o.get("decision_id"),
            "ok": o.get("ok"),
            "error": (o.get("error") or None),
        })

    # executa pending now
    exec_run = {"error": "not_run"}
    try:
        from services.action_engine import execute_pending
        t0 = time.time()
        e = await execute_pending()
        e["elapsed_ms"] = int((time.time() - t0) * 1000)
        exec_run = e
    except Exception as e:  # noqa: BLE001
        exec_run = {"error": str(e)}

    success_rate = round(100.0 * out_ok / max(out_total, 1), 1)

    return {
        "total_actions": total,
        "by_status": by_status,
        "by_action_type": by_type,
        "dry_run_count": dry_runs,
        "live_count": live,
        "live_mode_env": os.environ.get("PRESIDENTE_IA_LIVE", "0"),
        "outcomes_total": out_total,
        "outcomes_ok": out_ok,
        "outcomes_fail": out_fail,
        "success_rate_pct": success_rate,
        "sample_outcomes": sample_outcomes,
        "live_execute_now": exec_run,
    }


@_safe
async def q8_scheduler_evidence() -> dict:
    """8. O APScheduler está rodando de verdade? Como provar?"""
    # Tenta importar o scheduler instanciado
    from services import executive_scheduler as es
    sch = getattr(es, "_scheduler", None)
    jobs = []
    running = False
    try:
        if sch is not None:
            running = bool(sch.running)
            for j in sch.get_jobs():
                jobs.append({
                    "id": j.id,
                    "next_run_time": (str(j.next_run_time)
                                        if j.next_run_time else None),
                    "trigger": str(j.trigger),
                    "max_instances": j.max_instances,
                    "coalesce": j.coalesce,
                })
    except Exception as e:  # noqa: BLE001
        jobs = [{"error": str(e)}]

    # Evidência indireta: insights periódicos
    last_health = None
    async for d in db.motor_ia_insights.find(
            {"kind": "executive_health"}, {"_id": 0}
    ).sort("created_at", -1).limit(1):
        last_health = {"score": d.get("overall_score"),
                       "status": d.get("status"),
                       "generated_at": d.get("generated_at")}
    last_dq = None
    async for d in db.motor_ia_insights.find(
            {"kind": "data_quality_scan"}, {"_id": 0}
    ).sort("created_at", -1).limit(1):
        last_dq = {"score": d.get("score"),
                   "status": d.get("status"),
                   "generated_at": d.get("generated_at")}

    # PID/uptime do processo backend (proxy)
    proc_info = {
        "pid": os.getpid(),
        "process_started_at": _iso(
            datetime.fromtimestamp(
                os.path.getmtime("/proc/self"),
                tz=timezone.utc)
            if os.path.exists("/proc/self") else _now()),
    }

    return {
        "scheduler_instance_present": sch is not None,
        "scheduler_running": running,
        "jobs": jobs,
        "last_executive_health_insight": last_health,
        "last_data_quality_insight": last_dq,
        "process": proc_info,
        "note": ("Esse script roda fora do worker FastAPI, portanto o "
                  "scheduler reportado aqui é uma NOVA instância — a "
                  "evidência forte de execução real está nos insights "
                  "periódicos persistidos."),
    }


@_safe
async def q9_estrategista_ia() -> dict:
    """9. O Estrategista IA (Claude) gera relatórios? Mostre um."""
    recent = []
    async for r in db.motor_ia_memory.find(
            {"kind": "estrategista_report"}, {"_id": 0}
    ).sort("created_at", -1).limit(3):
        recent.append({
            "id": r.get("id"),
            "period": r.get("period"),
            "title": r.get("title"),
            "llm_used": r.get("llm_used"),
            "error": r.get("error"),
            "created_at": r.get("created_at"),
            "text_preview": (r.get("text") or "")[:600],
            "metrics": (r.get("context") or {}).get("metrics"),
        })

    # gera daily ao vivo se nada existir
    live = {"error": "not_run"}
    try:
        from services.estrategista_ia import generate_report
        t0 = time.time()
        rpt = await generate_report("daily", force=False)
        live = {
            "period": rpt.get("period"),
            "llm_used": rpt.get("llm_used"),
            "error": rpt.get("error"),
            "cached": rpt.get("cached", False),
            "text_preview": (rpt.get("text") or "")[:600],
            "elapsed_ms": int((time.time() - t0) * 1000),
        }
    except Exception as e:  # noqa: BLE001
        live = {"error": str(e)}

    return {"recent_reports": recent,
            "live_generate_now": live,
            "emergent_key_present": bool(
                os.environ.get("EMERGENT_LLM_KEY")
                or os.environ.get("ANTHROPIC_API_KEY"))}


@_safe
async def q10_performance_metrics() -> dict:
    """10. Performance: o pipeline aguenta carga? Quanto leva?"""
    # microbenchmark: 200 inserts no event bus + decision cycle
    from services.event_bus import emit_event, EventType
    t0 = time.time()
    n = 200
    for i in range(n):
        await emit_event(
            EventType.CLIENT_OFFLINE,
            company_id="benchmark",
            source="cto_benchmark",
            severity="alta",
            payload={"cto_id": f"BENCH-CTO-{i % 5}",
                     "subscriber_id": f"sub-{i}"})
    t_emit = time.time() - t0
    emit_per_sec = round(n / t_emit, 1) if t_emit else 0

    t0 = time.time()
    from services.decision_engine import run_decision_cycle
    dc = await run_decision_cycle(limit_events=n + 50)
    t_dc = time.time() - t0

    t0 = time.time()
    from services.action_engine import execute_pending
    ae = await execute_pending(limit=50)
    t_ae = time.time() - t0

    # limpeza dos eventos de benchmark
    await db.motor_ia_events.delete_many({"company_id": "benchmark"})
    await db.motor_ia_decisions.delete_many({"company_id": "benchmark"})
    await db.motor_ia_actions.delete_many({"company_id": "benchmark"})
    await db.incidents.delete_many({"company_id": "benchmark"})

    return {
        "emit_count": n,
        "emit_elapsed_ms": int(t_emit * 1000),
        "emit_throughput_per_sec": emit_per_sec,
        "decision_cycle_elapsed_ms": int(t_dc * 1000),
        "decision_cycle_result": dc,
        "action_engine_elapsed_ms": int(t_ae * 1000),
        "action_engine_result": ae,
    }


@_safe
async def q11_tenant_isolation() -> dict:
    """11. Multi-tenant: o sistema isola company_id?"""
    # events sem company_id
    with_company = await db.motor_ia_events.count_documents(
        {"company_id": {"$nin": [None, ""]}})
    without_company = await db.motor_ia_events.count_documents(
        {"$or": [{"company_id": None}, {"company_id": ""}]})
    distinct_companies = await db.motor_ia_events.distinct("company_id")

    # decisões e ações
    dec_with = await db.motor_ia_decisions.count_documents(
        {"company_id": {"$nin": [None, ""]}})
    dec_without = await db.motor_ia_decisions.count_documents(
        {"$or": [{"company_id": None}, {"company_id": ""}]})
    act_with = await db.motor_ia_actions.count_documents(
        {"company_id": {"$nin": [None, ""]}})
    act_without = await db.motor_ia_actions.count_documents(
        {"$or": [{"company_id": None}, {"company_id": ""}]})

    return {
        "events_with_company_id": with_company,
        "events_without_company_id": without_company,
        "distinct_company_ids": [c for c in distinct_companies
                                   if c][:10],
        "distinct_company_count": len([c for c in distinct_companies
                                          if c]),
        "decisions_with_company_id": dec_with,
        "decisions_without_company_id": dec_without,
        "actions_with_company_id": act_with,
        "actions_without_company_id": act_without,
        "coverage_pct_events": round(
            100.0 * with_company / max(with_company + without_company, 1),
            1),
    }


@_safe
async def q12_audit_chain_integrity() -> dict:
    """12. A cadeia de hash do audit_log está íntegra?"""
    total = await db.audit_log.count_documents({})
    with_hash = await db.audit_log.count_documents(
        {"hash": {"$nin": [None, ""]}})
    with_prev = await db.audit_log.count_documents(
        {"prev_hash": {"$nin": [None, ""]}})

    # verifica integridade dos últimos 50 elos
    chain_check = {"checked": 0, "ok": 0, "broken": 0,
                   "first_break": None}
    try:
        cur = db.audit_log.find({}, {"_id": 0}).sort(
            "created_at", -1).limit(50)
        prev = None
        items = []
        async for d in cur:
            items.append(d)
        items.reverse()  # cronológico
        for i, d in enumerate(items):
            chain_check["checked"] += 1
            if prev is not None:
                if d.get("prev_hash") != prev.get("hash"):
                    chain_check["broken"] += 1
                    if chain_check["first_break"] is None:
                        chain_check["first_break"] = {
                            "index": i,
                            "expected_prev_hash": prev.get("hash"),
                            "actual_prev_hash": d.get("prev_hash"),
                            "id": d.get("id"),
                            "created_at": d.get("created_at"),
                        }
                else:
                    chain_check["ok"] += 1
            prev = d
    except Exception as e:  # noqa: BLE001
        chain_check["error"] = str(e)

    return {
        "audit_log_total": total,
        "with_hash": with_hash,
        "with_prev_hash": with_prev,
        "hash_coverage_pct": round(100.0 * with_hash
                                       / max(total, 1), 1),
        "last_50_chain_check": chain_check,
    }


@_safe
async def q13_observability() -> dict:
    """13. Observabilidade: o sistema permite debugar incidentes?"""
    # Correlation IDs presentes em eventos
    with_corr = await db.motor_ia_events.count_documents(
        {"correlation_id": {"$nin": [None, ""]}})
    total = await db.motor_ia_events.count_documents({})

    # Decisões com trigger_event_id (rastreabilidade)
    dec_total = await db.motor_ia_decisions.count_documents({})
    dec_with_trigger = await db.motor_ia_decisions.count_documents(
        {"trigger_event_id": {"$nin": [None, ""]}})

    # Outcomes com erro detalhado
    out_total = await db.motor_ia_outcomes.count_documents({})
    out_fail = await db.motor_ia_outcomes.count_documents({"ok": False})
    out_fail_with_error = await db.motor_ia_outcomes.count_documents(
        {"ok": False, "error": {"$nin": [None, ""]}})

    # Reasoning preenchido nas decisões
    dec_with_reasoning = await db.motor_ia_decisions.count_documents(
        {"reasoning": {"$nin": [None, ""]}})

    return {
        "events_correlation_id_pct": round(
            100.0 * with_corr / max(total, 1), 1),
        "decisions_with_trigger_event_pct": round(
            100.0 * dec_with_trigger / max(dec_total, 1), 1),
        "decisions_with_reasoning_pct": round(
            100.0 * dec_with_reasoning / max(dec_total, 1), 1),
        "outcomes_total": out_total,
        "outcomes_failures": out_fail,
        "outcomes_failures_with_error_msg": out_fail_with_error,
        "outcomes_error_traceability_pct": round(
            100.0 * out_fail_with_error / max(out_fail, 1), 1)
            if out_fail else None,
    }


# ───────────────────────────────────────────────────────────────────────
# Seed opcional (para provar pipeline ponta a ponta)
# ───────────────────────────────────────────────────────────────────────
async def seed_demo_load():
    """Emite eventos representativos para o pipeline processar."""
    from services.event_bus import emit_event, EventType
    co = "demo-cto-audit"
    # 6 clientes offline no mesmo CTO → dispara collective_outage
    for i in range(6):
        await emit_event(EventType.CLIENT_OFFLINE,
                          company_id=co, source="smartolt",
                          severity="alta",
                          payload={"cto_id": "CTO-DEMO-01",
                                   "subscriber_id": f"demo-sub-{i}"})
    # 4 churn risk
    for i in range(4):
        await emit_event(EventType.CLIENT_CHURN_RISK,
                          company_id=co, source="churn_scheduler",
                          severity="media",
                          payload={"subscriber_id": f"demo-churn-{i}",
                                   "reason": "multi_open_tickets"})
    # 3 RBAC denied do mesmo user
    for _ in range(3):
        await emit_event(EventType.RBAC_DENIED,
                          company_id=co, user_id="demo-user-attack",
                          source="rbac", severity="alta",
                          payload={"endpoint": "/api/admin/users"})
    # 2 payment overdue
    for i in range(2):
        await emit_event(EventType.PAYMENT_OVERDUE,
                          company_id=co, source="financeiro",
                          severity="media",
                          payload={"subscriber_id": f"demo-pay-{i}"})
    # roda ciclos
    from services.decision_engine import run_decision_cycle
    from services.action_engine import execute_pending
    await run_decision_cycle()
    await execute_pending()
    return {"seeded": True, "company_id": co}


# ───────────────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────────────
async def main(seed: bool, out_path: str):
    if seed:
        seed_result = await seed_demo_load()
    else:
        seed_result = {"seeded": False}

    report = {
        "report_id": f"cto-audit-{uuid.uuid4().hex[:10]}",
        "generated_at": _iso(_now()),
        "mongo_db": os.environ.get("DB_NAME"),
        "seed": seed_result,
        "q1_event_bus_real": await q1_event_bus_real(),
        "q2_event_types_distribution": await q2_event_types_distribution(),
        "q3_memoria_collections": await q3_memoria_collections(),
        "q4_data_quality_evidence": await q4_data_quality_evidence(),
        "q5_security_detectors": await q5_security_detectors(),
        "q6_decision_engine": await q6_decision_engine(),
        "q7_action_engine": await q7_action_engine(),
        "q8_scheduler_evidence": await q8_scheduler_evidence(),
        "q9_estrategista_ia": await q9_estrategista_ia(),
        "q10_performance_metrics": await q10_performance_metrics(),
        "q11_tenant_isolation": await q11_tenant_isolation(),
        "q12_audit_chain_integrity": await q12_audit_chain_integrity(),
        "q13_observability": await q13_observability(),
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(
        json.dumps(report, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8")
    print(f"[ok] report saved -> {out_path}")
    print(json.dumps({k: (v if not isinstance(v, dict)
                         else {kk: (vv if not isinstance(vv, (dict, list))
                                       else "...")
                               for kk, vv in v.items()})
                      for k, v in report.items()},
                     indent=2, default=str, ensure_ascii=False)[:4000])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true",
                     help="popula eventos de demo antes de coletar")
    ap.add_argument("--out", default="/app/backend/scripts/_cto_report.json")
    args = ap.parse_args()
    asyncio.run(main(args.seed, args.out))
