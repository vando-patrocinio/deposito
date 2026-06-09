"""
ml_predictions.py — Sprint 18 (ML real)
Substitui (gradualmente) as heurísticas de predictions.py por modelos
estatísticos reais:

  • churn_iforest  — IsolationForest para anomalia comportamental
  • ticket_arima   — AR simples (numpy linear) para forecast de demanda

Falha graciosamente quando não há sklearn/numpy ou dados suficientes
(retorna {error}). NUNCA quebra o scheduler.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from database import db


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def churn_iforest(company_id: str = None, max_subs: int = 5000
                              ) -> Dict[str, Any]:
    """Roda IsolationForest sobre features básicas dos subscribers.

    Features: [tickets_abertos, dias_desde_ultimo_pagto,
               rx_dbm_medio_24h_inverted, valor_plano].
    Outliers (score < threshold) viram top_risk.
    """
    try:
        import numpy as np
        from sklearn.ensemble import IsolationForest
    except ImportError as e:
        return {"error": f"sklearn não disponível: {e}"}

    flt = {"company_id": company_id} if company_id else {}
    subs: List[Dict[str, Any]] = []
    async for s in db.subscribers.find(flt, {
            "id": 1, "company_id": 1, "plan_price": 1,
            "last_payment_at": 1}).limit(max_subs):
        subs.append(s)
    if len(subs) < 30:
        return {"error": "insuficiente",
                "samples": len(subs)}

    # build feature vector
    feats = []
    sub_ids = []
    for s in subs:
        sid = s.get("id")
        if not sid:
            continue
        # tickets abertos
        tk = await db.tickets.count_documents(
            {"subscriber_id": sid,
             "status": {"$nin": ["closed", "completed",
                                    "finalizado"]}})
        # rx_dbm médio nas últimas 24h
        rx_avg = 0.0
        n_rx = 0
        async for o in db.onus.find(
                {"subscriber_id": sid, "rx_dbm": {"$ne": None}}):
            rx_avg += float(o.get("rx_dbm") or 0)
            n_rx += 1
        rx_inv = -(rx_avg / n_rx) if n_rx else 30.0  # bom default
        # valor do plano
        price = float(s.get("plan_price") or 0)
        # tempo sem pagamento (days)
        lp = s.get("last_payment_at")
        try:
            if isinstance(lp, str):
                lp_dt = datetime.fromisoformat(
                    lp.replace("Z", "+00:00"))
            elif isinstance(lp, datetime):
                lp_dt = lp
            else:
                lp_dt = None
        except Exception:
            lp_dt = None
        days_since_pay = ((datetime.now(timezone.utc) - lp_dt).days
                            if lp_dt else 90)
        feats.append([tk, days_since_pay, rx_inv, price])
        sub_ids.append(sid)

    if len(feats) < 30:
        return {"error": "features_insuficientes",
                "samples": len(feats)}

    X = np.array(feats, dtype=float)
    model = IsolationForest(contamination=0.10, random_state=42,
                              n_estimators=80)
    model.fit(X)
    scores = model.score_samples(X)  # mais baixo = mais anômalo

    ranked = sorted(zip(sub_ids, scores), key=lambda t: t[1])[:50]
    items = [{"subscriber_id": sid,
              "anomaly_score": round(float(sc), 4),
              "risk_pct": round(float(100 * (1 - (sc - scores.min())
                                              / max(scores.max()
                                                       - scores.min(),
                                                       0.01))), 1)}
             for sid, sc in ranked]

    pred = {
        "id": f"pred-ifc-{uuid.uuid4().hex[:10]}",
        "kind": "churn_iforest",
        "model": "IsolationForest_v1",
        "horizon_days": 30,
        "samples_observed": len(feats),
        "company_id": company_id,
        "items": items,
        "feature_names": ["tickets_open", "days_since_payment",
                           "rx_dbm_inverted", "plan_price"],
        "generated_at": _now_iso(),
    }
    try:
        await db.motor_ia_predictions.insert_one(dict(pred))
    except Exception:
        pass
    pred.pop("_id", None)
    return pred


async def ticket_arima(company_id: str = None,
                          horizon_days: int = 7) -> Dict[str, Any]:
    """AR(p=2) simples: forecast a partir da série diária de tickets."""
    try:
        import numpy as np
    except ImportError:
        return {"error": "numpy não disponível"}

    since = (datetime.now(timezone.utc)
              - timedelta(days=30)).isoformat()
    match = {"created_at": {"$gte": since}}
    if company_id:
        match["company_id"] = company_id

    by_day: Dict[str, int] = defaultdict(int)
    async for r in db.tickets.aggregate([
        {"$match": match},
        {"$group": {
            "_id": {"$substr": ["$created_at", 0, 10]},
            "n": {"$sum": 1}}}]):
        by_day[r["_id"]] = r["n"]
    days = sorted(by_day.keys())
    series = [by_day[d] for d in days]
    if len(series) < 7:
        return {"error": "serie_curta", "samples": len(series)}

    x = np.array(series, dtype=float)
    # AR(2): y_t ≈ a*y_{t-1} + b*y_{t-2} + c
    A = np.stack([x[1:-1], x[:-2], np.ones(len(x) - 2)], axis=1)
    y = x[2:]
    try:
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    except Exception:
        return {"error": "fit_falhou"}
    a, b, c = float(coef[0]), float(coef[1]), float(coef[2])
    yhat = list(x)
    for _ in range(horizon_days):
        yhat.append(a * yhat[-1] + b * yhat[-2] + c)
    forecast = yhat[-horizon_days:]
    pred = {
        "id": f"pred-ar-{uuid.uuid4().hex[:10]}",
        "kind": "ticket_arima",
        "model": "AR2_v1",
        "horizon_days": horizon_days,
        "company_id": company_id,
        "coef_a": round(a, 3),
        "coef_b": round(b, 3),
        "coef_c": round(c, 3),
        "history_tail_7d": series[-7:],
        "forecast": [round(v, 1) for v in forecast],
        "forecast_total": round(sum(forecast), 1),
        "generated_at": _now_iso(),
    }
    try:
        await db.motor_ia_predictions.insert_one(dict(pred))
    except Exception:
        pass
    pred.pop("_id", None)
    return pred


async def run_all_ml() -> Dict[str, Any]:
    """Roda todos os modelos ML por company."""
    try:
        companies = await db.subscribers.distinct("company_id")
    except Exception:
        companies = []
    companies = [c for c in companies if c] or [None]
    out: Dict[str, Any] = {"companies": []}
    for co in companies:
        c = {"company_id": co}
        try:
            c["churn_iforest"] = await churn_iforest(company_id=co)
        except Exception as e:  # noqa: BLE001
            c["churn_iforest"] = {"error": str(e)}
        try:
            c["ticket_arima"] = await ticket_arima(company_id=co)
        except Exception as e:  # noqa: BLE001
            c["ticket_arima"] = {"error": str(e)}
        out["companies"].append(c)
    out["generated_at"] = _now_iso()
    return out
