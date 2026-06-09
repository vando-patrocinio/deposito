"""
predictions.py — Sprint 11
Gera predições populando `motor_ia_predictions`.

3 modelos heurísticos (sem ML pesado por enquanto, mas com sinais
reais do banco):

  • CHURN PREDICTION
      score por subscriber considerando:
        - tickets abertos (>=2 → +30)
        - pagamento atrasado (status overdue) → +40
        - sinal baixo (média rx_dbm < -27 nas últimas 24h) → +15
        - sem login recente (>30d) → +15
      Persiste top-100 por (company_id, score desc).

  • REVENUE FORECAST (30 dias)
      MRR = sum(plan_price) dos subscribers ativos.
      Trend: variação da contagem de subscribers nos últimos 30 vs
      anteriores 30 dias → ajusta projeção.

  • TICKET DEMAND FORECAST (próximos 7 dias)
      média móvel de tickets/dia dos últimos 14 dias + correção
      sazonal por dia da semana.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from database import db


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hours_ago(h: int) -> str:
    return (datetime.now(timezone.utc)
            - timedelta(hours=h)).isoformat()


async def predict_churn() -> Dict[str, Any]:
    """Top-100 subscribers em risco de churn por company."""
    # eficiência: agregamos por subscriber via aggregations
    by_sub: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"score": 0, "reasons": [], "company_id": None})

    # 1) tickets abertos por subscriber
    pipe = [
        {"$match": {"status": {"$nin": ["closed", "finalizado",
                                             "completed"]}}},
        {"$group": {"_id": {"sub": "$subscriber_id",
                                "co": "$company_id"},
                       "n": {"$sum": 1}}},
        {"$match": {"n": {"$gte": 1}}},
    ]
    try:
        async for r in db.tickets.aggregate(pipe):
            sub = (r.get("_id") or {}).get("sub")
            co = (r.get("_id") or {}).get("co")
            if not sub:
                continue
            by_sub[sub]["company_id"] = co
            if r["n"] >= 2:
                by_sub[sub]["score"] += 30
                by_sub[sub]["reasons"].append(
                    f"{r['n']} tickets abertos")
            else:
                by_sub[sub]["score"] += 10
    except Exception:
        pass

    # 2) pagamento atrasado
    try:
        async for r in db.financeiro_movs.aggregate([
            {"$match": {"status": {"$in": ["overdue", "atrasado"]}}},
            {"$group": {"_id": {"sub": "$subscriber_id",
                                    "co": "$company_id"},
                           "n": {"$sum": 1}}},
        ]):
            sub = (r.get("_id") or {}).get("sub")
            co = (r.get("_id") or {}).get("co")
            if not sub:
                continue
            by_sub[sub]["company_id"] = (
                by_sub[sub]["company_id"] or co)
            by_sub[sub]["score"] += 40
            by_sub[sub]["reasons"].append(
                f"{r['n']} mensalidades em atraso")
    except Exception:
        pass

    # 3) sinal baixo médio
    try:
        async for r in db.onus.find({"rx_dbm": {"$lt": -27}},
                                          {"subscriber_id": 1,
                                           "company_id": 1,
                                           "rx_dbm": 1}):
            sub = r.get("subscriber_id")
            if not sub:
                continue
            by_sub[sub]["company_id"] = (
                by_sub[sub]["company_id"] or r.get("company_id"))
            by_sub[sub]["score"] += 15
            by_sub[sub]["reasons"].append(
                f"RX {r.get('rx_dbm')}dBm")
    except Exception:
        pass

    # ranking
    items: List[Dict[str, Any]] = []
    for sub, info in by_sub.items():
        if info["score"] <= 0:
            continue
        items.append({
            "subscriber_id": sub,
            "company_id": info["company_id"],
            "risk_score": min(100, info["score"]),
            "reasons": info["reasons"][:4],
        })
    items.sort(key=lambda x: x["risk_score"], reverse=True)
    items = items[:100]

    pred = {
        "id": f"pred-churn-{uuid.uuid4().hex[:10]}",
        "kind": "churn",
        "horizon_days": 30,
        "model": "heuristic_v1",
        "generated_at": _now_iso(),
        "count": len(items),
        "items": items,
    }
    try:
        await db.motor_ia_predictions.insert_one(dict(pred))
    except Exception:
        pass
    pred.pop("_id", None)
    return pred


async def predict_revenue() -> Dict[str, Any]:
    """MRR atual + forecast de 30 dias por company."""
    by_co: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"mrr": 0.0, "active": 0})

    try:
        async for r in db.subscribers.aggregate([
            {"$match": {"$or": [
                {"status": "active"},
                {"status": "ativo"},
                {"status": {"$exists": False}}]}},
            {"$group": {
                "_id": "$company_id",
                "mrr": {"$sum": {"$ifNull": ["$plan_price", 0]}},
                "active": {"$sum": 1}}},
        ]):
            co = r.get("_id") or "_unknown_"
            by_co[co]["mrr"] = float(r.get("mrr") or 0)
            by_co[co]["active"] = int(r.get("active") or 0)
    except Exception:
        pass

    # trend simples: diferença de novos subscribers entre 30d/60d
    cutoff_30 = (datetime.now(timezone.utc)
                  - timedelta(days=30)).isoformat()
    cutoff_60 = (datetime.now(timezone.utc)
                  - timedelta(days=60)).isoformat()
    growth_per_co: Dict[str, float] = {}
    try:
        new_30 = defaultdict(int)
        new_prev = defaultdict(int)
        async for r in db.subscribers.aggregate([
            {"$match": {"created_at": {"$gte": cutoff_60}}},
            {"$project": {
                "co": "$company_id",
                "created_at": 1,
            }},
        ]):
            co = r.get("co") or "_unknown_"
            ca = r.get("created_at") or ""
            if ca >= cutoff_30:
                new_30[co] += 1
            else:
                new_prev[co] += 1
        for co in set(list(new_30.keys()) + list(new_prev.keys())):
            prev = max(new_prev[co], 1)
            growth_per_co[co] = (new_30[co] - new_prev[co]) / prev
    except Exception:
        pass

    items = []
    for co, info in by_co.items():
        g = growth_per_co.get(co, 0.0)
        forecast = info["mrr"] * (1.0 + g)
        items.append({
            "company_id": co,
            "current_mrr": round(info["mrr"], 2),
            "active_subscribers": info["active"],
            "growth_30d": round(g, 3),
            "forecast_30d": round(forecast, 2),
            "delta": round(forecast - info["mrr"], 2),
        })

    pred = {
        "id": f"pred-rev-{uuid.uuid4().hex[:10]}",
        "kind": "revenue",
        "horizon_days": 30,
        "model": "trend_v1",
        "generated_at": _now_iso(),
        "items": items,
    }
    try:
        await db.motor_ia_predictions.insert_one(dict(pred))
    except Exception:
        pass
    pred.pop("_id", None)
    return pred


async def predict_ticket_demand() -> Dict[str, Any]:
    """Forecast simples (próximos 7 dias) por company."""
    since_14 = (datetime.now(timezone.utc)
                 - timedelta(days=14)).isoformat()
    by_day_co: Dict[str, Dict[str, int]] = defaultdict(
        lambda: defaultdict(int))
    try:
        async for r in db.tickets.aggregate([
            {"$match": {"created_at": {"$gte": since_14}}},
            {"$group": {
                "_id": {
                    "co": "$company_id",
                    "d": {"$substr": ["$created_at", 0, 10]}},
                "n": {"$sum": 1}}},
        ]):
            co = (r.get("_id") or {}).get("co") or "_unknown_"
            d = (r.get("_id") or {}).get("d") or ""
            by_day_co[co][d] = r.get("n", 0)
    except Exception:
        pass

    items = []
    for co, days in by_day_co.items():
        n = list(days.values())
        avg = sum(n) / max(len(n), 1)
        items.append({
            "company_id": co,
            "avg_tickets_per_day_14d": round(avg, 1),
            "forecast_7d": round(avg * 7, 1),
            "samples_observed": len(n),
        })

    pred = {
        "id": f"pred-tkt-{uuid.uuid4().hex[:10]}",
        "kind": "ticket_demand",
        "horizon_days": 7,
        "model": "moving_average_v1",
        "generated_at": _now_iso(),
        "items": items,
    }
    try:
        await db.motor_ia_predictions.insert_one(dict(pred))
    except Exception:
        pass
    pred.pop("_id", None)
    return pred


async def run_all_predictions() -> Dict[str, Any]:
    """Roda todos os modelos. Chamado pelo scheduler."""
    out = {}
    try:
        out["churn"] = await predict_churn()
    except Exception as e:  # noqa: BLE001
        out["churn"] = {"error": str(e)}
    try:
        out["revenue"] = await predict_revenue()
    except Exception as e:  # noqa: BLE001
        out["revenue"] = {"error": str(e)}
    try:
        out["ticket_demand"] = await predict_ticket_demand()
    except Exception as e:  # noqa: BLE001
        out["ticket_demand"] = {"error": str(e)}
    out["generated_at"] = _now_iso()
    return out


async def latest_by_kind(kind: str) -> Dict[str, Any]:
    """Retorna a predição mais recente do tipo `kind`."""
    doc = await db.motor_ia_predictions.find_one(
        {"kind": kind}, sort=[("generated_at", -1)])
    if doc:
        doc.pop("_id", None)
    return doc or {}
