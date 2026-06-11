"""
smartprov_score.py — V8.0 PRIORIDADE 9
Indicador único: SMARTPROV SCORE (0-100).
  30% Receita | 20% Retenção | 20% Automação | 15% DQ | 15% Rede
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

from datetime import datetime, timezone, timedelta
from typing import Any, Dict

from database import db


def _now(): return datetime.now(timezone.utc)


def _classify(score: float) -> str:
    if score <= 40: return "CRITICO"
    if score <= 60: return "ATENCAO"
    if score <= 80: return "BOM"
    if score <= 95: return "EXCELENTE"
    return "REFERENCIA"


async def _revenue_health(company_id: str) -> float:
    """Receita: % Recebido vs MRR teórico (últimos 30d)."""
    from services import financial_foundation as fin
    from services import cash_operation as cash
    fa = await fin.summary(company_id)
    kpi = await cash.kpi_money_generated(company_id)
    received = kpi["30d"]["received"]["BRL"]
    mrr = fa["mrr"]["mrr_BRL"]
    # Score = min(received / mrr, 1.0) × 100; pondera se MRR>0
    if mrr <= 0:
        return 0.0
    return round(min(received / mrr, 1.0) * 100, 1)


async def _retention_health(company_id: str) -> float:
    """Retenção = 1 - churn_rate (90d)."""
    total = await db.subscribers.count_documents(
        {"company_id": company_id})
    cutoff = (_now() - timedelta(days=90)).isoformat()
    churned = await db.subscribers.count_documents({
        "company_id": company_id,
        "cancellation_date": {"$gte": cutoff},
        "status": {"$in": ["INATIVO", "CANCELADO"]}})
    if total <= 0: return 0.0
    churn_rate = churned / total
    return round(max(0, (1 - churn_rate * 4)) * 100, 1)


async def _automation_health(company_id: str) -> float:
    """Autonomia = autonomy score do engine."""
    from services import autonomous_engine as eng
    s = await eng.compute_autonomy_score(company_id, days=1)
    return float(s["score"])


async def _data_quality_health(company_id: str) -> float:
    """DQ = % subscribers ATIVO completos (phone+plan_price+zone)."""
    total = await db.subscribers.count_documents(
        {"company_id": company_id, "status": "ATIVO"})
    if total <= 0: return 0.0
    complete = await db.subscribers.count_documents({
        "company_id": company_id, "status": "ATIVO",
        "phone": {"$nin": [None, ""]},
        "plan_price": {"$gt": 0},
        "smartolt_onu_zone": {"$nin": [None, ""]}})
    return round(complete / total * 100, 1)


async def _network_health(company_id: str) -> float:
    """Rede = % ONUs Online sobre total."""
    pipe = [
        {"$match": {"company_id": company_id,
                     "smartolt_onu_status": {"$nin": [None, ""]}}},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "online": {"$sum": {"$cond": [
                {"$eq": ["$smartolt_onu_status", "Online"]}, 1, 0]}},
        }},
    ]
    r = await db.subscribers.aggregate(pipe).to_list(1)
    if not r or r[0]["total"] == 0: return 0.0
    return round(r[0]["online"] / r[0]["total"] * 100, 1)


WEIGHTS = {
    "revenue": 0.30,
    "retention": 0.20,
    "automation": 0.20,
    "data_quality": 0.15,
    "network": 0.15,
}


async def compute(company_id: str) -> Dict[str, Any]:
    rev = await _revenue_health(company_id)
    ret = await _retention_health(company_id)
    aut = await _automation_health(company_id)
    dq  = await _data_quality_health(company_id)
    net = await _network_health(company_id)
    score = round(
        rev * WEIGHTS["revenue"]
        + ret * WEIGHTS["retention"]
        + aut * WEIGHTS["automation"]
        + dq  * WEIGHTS["data_quality"]
        + net * WEIGHTS["network"], 1)
    cls = _classify(score)
    # Bottleneck = ingrediente mais fraco ponderado
    parts = {"revenue": rev, "retention": ret, "automation": aut,
              "data_quality": dq, "network": net}
    bottleneck = min(parts.items(), key=lambda x: x[1])
    return {
        "generated_at": _now().isoformat(),
        "company_id": company_id,
        "score": score,
        "classification": cls,
        "components": parts,
        "weights": WEIGHTS,
        "bottleneck": {"name": bottleneck[0], "value": bottleneck[1]},
        "headline": (
            f"SmartProv Score: {score} ({cls}) · "
            f"Gargalo: {bottleneck[0]} ({bottleneck[1]}%)"
        ),
    }
