"""Opportunity Executor — Pipeline Health (B.4).

Métricas operacionais do pipeline B (Commanders → Executor → Outcome):

  Funil:  Criadas → Elegíveis → Aprovadas → Executadas → Sucesso
  ROI:    valor recuperado / receita gerada / clientes retidos
  AUTONOMY INDEX: % de opps elegíveis que foram executadas com sucesso
                  (exclui block_subscriber, quarantine_release, expand_coverage)

KPI exposto em 3 painéis (Console Isabella, Presidente IA, Watchtower).
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
from typing import Any, Dict, List, Optional

from database import db

logger = logging.getLogger("ponto.executor_health")

OPP_COLL = "isabella_commander_opportunities"
AUDIT_COLL = "opportunity_executor_audit"

# Tipos que NUNCA entram em "autonomous" (sempre exigem humano)
NON_AUTONOMOUS_TYPES = {
    "block_subscriber", "quarantine_release", "expand_coverage",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_cutoff(hours: int) -> str:
    return (_now() - timedelta(hours=hours)).isoformat()


async def funnel_stats(*, company_id: str, hours: int = 24) -> Dict[str, Any]:
    """Funil completo: criadas → elegíveis → aprovadas → executadas → sucesso."""
    cutoff = _iso_cutoff(hours)
    base = {"company_id": company_id, "created_at": {"$gte": cutoff}}

    criadas = await db[OPP_COLL].count_documents(base)

    # Elegíveis = não-manual + não exige approval explícita
    elegiveis = await db[OPP_COLL].count_documents({
        **base,
        "recommended_action.type": {"$nin": list(NON_AUTONOMOUS_TYPES)},
        "recommended_action.requires_approval": {"$ne": True},
    })

    aprovadas = await db[OPP_COLL].count_documents({
        **base, "status": "approved",
    })

    executadas = await db[OPP_COLL].count_documents({
        **base,
        "$or": [
            {"status": "executed"},
            {"executed_at": {"$exists": True, "$ne": None}},
        ],
    })

    sucesso = await db[OPP_COLL].count_documents({
        **base, "status": "executed",
        "execution_result.ok": True,
    })

    falhadas = await db[OPP_COLL].count_documents({
        **base, "status": "execution_failed",
    })

    ignoradas = await db[OPP_COLL].count_documents({
        **base, "status": "dismissed",
    })

    expiradas = await db[OPP_COLL].count_documents({
        **base, "status": "expired",
    })

    return {
        "criadas": criadas,
        "elegiveis": elegiveis,
        "aprovadas": aprovadas,
        "executadas": executadas,
        "sucesso": sucesso,
        "falhadas": falhadas,
        "ignoradas": ignoradas,
        "expiradas": expiradas,
    }


async def autonomy_index(*, company_id: str, hours: int = 24) -> Dict[str, Any]:
    """AUTONOMY INDEX — % de opps elegíveis (autônomas) que foram
    executadas com sucesso.

    Fórmula: (executadas_com_sucesso_AUTONOMOUS) / (elegíveis_AUTONOMOUS)

    Exclui block_subscriber, quarantine_release, expand_coverage.
    """
    cutoff = _iso_cutoff(hours)
    base = {
        "company_id": company_id,
        "created_at": {"$gte": cutoff},
        "recommended_action.type": {"$nin": list(NON_AUTONOMOUS_TYPES)},
    }
    elegiveis = await db[OPP_COLL].count_documents({
        **base,
        "recommended_action.requires_approval": {"$ne": True},
    })
    executadas_ok = await db[OPP_COLL].count_documents({
        **base, "status": "executed", "execution_result.ok": True,
    })
    pct = (executadas_ok / elegiveis * 100.0) if elegiveis else 0.0
    return {
        "elegiveis_autonomas": elegiveis,
        "executadas_com_sucesso": executadas_ok,
        "autonomy_index_pct": round(pct, 1),
    }


async def by_action_type(*, company_id: str, hours: int = 24
                              ) -> List[Dict[str, Any]]:
    """Breakdown por action_type com taxa de sucesso e latência média."""
    cutoff = _iso_cutoff(hours)
    pipeline = [
        {"$match": {"company_id": company_id,
                      "created_at": {"$gte": cutoff}}},
        {"$group": {
            "_id": "$recommended_action.type",
            "total": {"$sum": 1},
            "executed": {"$sum": {"$cond": [
                {"$eq": ["$status", "executed"]}, 1, 0]}},
            "failed": {"$sum": {"$cond": [
                {"$eq": ["$status", "execution_failed"]}, 1, 0]}},
            "pending": {"$sum": {"$cond": [
                {"$eq": ["$status", "pending"]}, 1, 0]}},
            "approved": {"$sum": {"$cond": [
                {"$eq": ["$status", "approved"]}, 1, 0]}},
            "expired": {"$sum": {"$cond": [
                {"$eq": ["$status", "expired"]}, 1, 0]}},
        }},
        {"$sort": {"total": -1}},
    ]
    rows: List[Dict[str, Any]] = []
    async for r in db[OPP_COLL].aggregate(pipeline):
        atype = r["_id"] or "unknown"
        total = r["total"]
        executed = r["executed"]
        rows.append({
            "action_type": atype,
            "total": total,
            "executed": executed,
            "failed": r["failed"],
            "pending": r["pending"],
            "approved": r["approved"],
            "expired": r["expired"],
            "success_rate_pct": round(
                (executed / total * 100.0) if total else 0.0, 1),
            "is_autonomous": atype not in NON_AUTONOMOUS_TYPES,
        })
    return rows


async def roi_stats(*, company_id: str, hours: int = 24) -> Dict[str, Any]:
    """ROI: soma de impact_brl das opps EXECUTADAS com sucesso, por kind."""
    cutoff = _iso_cutoff(hours)
    pipeline = [
        {"$match": {"company_id": company_id,
                      "created_at": {"$gte": cutoff},
                      "status": "executed",
                      "execution_result.ok": True}},
        {"$group": {
            "_id": "$kind",
            "n": {"$sum": 1},
            "impact_brl_total": {"$sum": {"$ifNull": ["$impact_brl", 0]}},
        }},
        {"$sort": {"impact_brl_total": -1}},
    ]
    rows: List[Dict[str, Any]] = []
    total_impact = 0.0
    async for r in db[OPP_COLL].aggregate(pipeline):
        impact = float(r.get("impact_brl_total") or 0)
        rows.append({
            "kind": r["_id"] or "unknown",
            "executadas": r["n"],
            "impact_brl_total": round(impact, 2),
        })
        total_impact += impact
    return {
        "by_kind": rows,
        "impact_brl_total": round(total_impact, 2),
    }


async def executor_health(*, company_id: str, hours: int = 24
                                ) -> Dict[str, Any]:
    """Stats do `opportunity_executor_audit`: produção vs dry_run."""
    cutoff = _iso_cutoff(hours)
    base = {"company_id": company_id, "created_at": {"$gte": cutoff}}
    total = await db[AUDIT_COLL].count_documents(base)
    dry = await db[AUDIT_COLL].count_documents(
        {**base, "dry_run": True})
    real = total - dry
    real_ok = await db[AUDIT_COLL].count_documents(
        {**base, "dry_run": {"$ne": True}, "result_ok": True})
    real_fail = await db[AUDIT_COLL].count_documents(
        {**base, "dry_run": {"$ne": True}, "result_ok": False})
    return {
        "audit_total": total,
        "dry_run": dry,
        "real_execution": real,
        "real_success": real_ok,
        "real_failed": real_fail,
        "success_rate_pct": round(
            (real_ok / real * 100.0) if real else 0.0, 1),
    }


async def pipeline_overview(*, company_id: str,
                                  hours: int = 24) -> Dict[str, Any]:
    """Snapshot completo para o painel B.4 Pipeline Health."""
    funnel = await funnel_stats(company_id=company_id, hours=hours)
    autonomy = await autonomy_index(company_id=company_id, hours=hours)
    by_type = await by_action_type(company_id=company_id, hours=hours)
    roi = await roi_stats(company_id=company_id, hours=hours)
    health = await executor_health(company_id=company_id, hours=hours)
    # Conversion rates do funil
    funnel["conversion_pct"] = {
        "criadas_to_elegiveis": _safe_pct(
            funnel["elegiveis"], funnel["criadas"]),
        "elegiveis_to_executadas": _safe_pct(
            funnel["executadas"], funnel["elegiveis"]),
        "executadas_to_sucesso": _safe_pct(
            funnel["sucesso"], funnel["executadas"]),
    }
    return {
        "company_id": company_id,
        "window_hours": hours,
        "funnel": funnel,
        "autonomy_index": autonomy,
        "by_action_type": by_type,
        "roi": roi,
        "executor_audit": health,
        "generated_at": _now().isoformat(),
    }


def _safe_pct(num: float, den: float) -> float:
    if not den:
        return 0.0
    return round(num / den * 100.0, 1)
