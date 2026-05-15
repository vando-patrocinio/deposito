"""Analytics financeiro — séries temporais agregadas para gráficos.

Agrega RECEBIMENTOS e DESPESAS por período configurável (dia/mês/ano).

RECEBIMENTOS = soma de:
  • `fin_cash_movements` type='income' (lançamentos manuais de receita)
  • `subscriber_invoices` com paid_date (faturas pagas via Atlaz)

DESPESAS = soma de:
  • `fin_cash_movements` type='expense' (inclui movimentações de bills pagas)

Também calcula:
  • Média mensal de cada série
  • Coeficiente de variação (regularidade): std/mean × 100
    - < 25% = regular
    - 25-50% = moderada
    - > 50% = irregular
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from core import DEMO_COMPANY_ID, require_role
from database import db
from routes.financeiro import require_finance

logger = logging.getLogger("ponto.financeiro_analytics")
router = APIRouter(prefix="/api/financeiro", tags=["financeiro"])


# ---------------------------------------------------------------------------
# Helpers de período
# ---------------------------------------------------------------------------
def _bucket_key(date_str: str, period: str) -> str:
    """Reduz uma data YYYY-MM-DD para a chave do bucket."""
    if not date_str:
        return ""
    s = date_str[:10]
    if period == "day":
        return s
    if period == "month":
        return s[:7]
    if period == "year":
        return s[:4]
    return s


def _range_for(range_: str) -> tuple[str, str]:
    """Mapeia range alias para (from_date, to_date) inclusivo."""
    today = datetime.now(timezone.utc).date()
    if range_ == "1d":
        # D+1 -> últimas 24h: hoje
        start = today
    elif range_ == "7d":
        start = today - timedelta(days=7)
    elif range_ == "30d":
        start = today - timedelta(days=30)
    elif range_ == "3m":
        start = today - timedelta(days=90)
    elif range_ == "6m":
        start = today - timedelta(days=180)
    elif range_ == "1y":
        start = today - timedelta(days=365)
    elif range_ == "all":
        start = today - timedelta(days=1825)  # 5y
    else:
        start = today - timedelta(days=30)
    return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Endpoint principal
# ---------------------------------------------------------------------------
@router.get("/analytics")
async def analytics(
    range_: str = Query("30d", alias="range",
                         pattern="^(1d|7d|30d|3m|6m|1y|all|custom)$"),
    period: str = Query("day", pattern="^(day|month|year)$"),
    from_date: Optional[str] = Query(None,
        pattern="^\\d{4}-\\d{2}-\\d{2}$",
        description="Data inicial YYYY-MM-DD (usado quando range=custom)"),
    to_date: Optional[str] = Query(None,
        pattern="^\\d{4}-\\d{2}-\\d{2}$",
        description="Data final YYYY-MM-DD (usado quando range=custom)"),
    user: dict = Depends(require_finance()),
):
    """Série de Recebimentos vs Despesas + médias + coeficiente de variação."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if range_ == "custom":
        if not from_date or not to_date:
            from fastapi import HTTPException
            raise HTTPException(400,
                "range=custom exige from_date e to_date no formato YYYY-MM-DD")
        if from_date > to_date:
            from fastapi import HTTPException
            raise HTTPException(400, "from_date deve ser <= to_date")
    else:
        from_date, to_date = _range_for(range_)

    # 1) Recebimentos = cash_movements income + subscriber_invoices pagas
    income_q = {"company_id": cid, "type": "income",
                  "date": {"$gte": from_date, "$lte": to_date}}
    expense_q = {"company_id": cid, "type": "expense",
                  "date": {"$gte": from_date, "$lte": to_date}}
    buckets: Dict[str, Dict[str, float]] = {}
    async for m in db.fin_cash_movements.find(
        income_q, {"_id": 0, "date": 1, "amount": 1},
    ):
        k = _bucket_key(m["date"], period)
        b = buckets.setdefault(k, {"income": 0.0, "expense": 0.0})
        b["income"] += float(m.get("amount") or 0)
    async for m in db.fin_cash_movements.find(
        expense_q, {"_id": 0, "date": 1, "amount": 1},
    ):
        k = _bucket_key(m["date"], period)
        b = buckets.setdefault(k, {"income": 0.0, "expense": 0.0})
        b["expense"] += float(m.get("amount") or 0)
    # 2) Faturas dos assinantes pagas (Atlaz)
    inv_q = {"company_id": cid, "paid_date": {"$ne": None,
              "$gte": from_date, "$lte": to_date}}
    async for inv in db.subscriber_invoices.find(
        inv_q, {"_id": 0, "paid_date": 1, "amount_paid": 1, "amount": 1},
    ):
        k = _bucket_key(inv["paid_date"], period)
        b = buckets.setdefault(k, {"income": 0.0, "expense": 0.0})
        b["income"] += float(inv.get("amount_paid") or inv.get("amount") or 0)

    # Gera lista contínua de buckets (preenche zeros pra gráfico não pular dias)
    series = _fill_continuous_buckets(from_date, to_date, period, buckets)

    # Métricas: média + std + CV
    income_vals = [b["income"] for b in series if b["income"] > 0]
    expense_vals = [b["expense"] for b in series if b["expense"] > 0]

    def metric(vals: List[float]) -> Dict[str, Any]:
        if not vals:
            return {"mean": 0, "std": 0, "cv_pct": 0,
                    "regularity": "sem_dados"}
        mean_ = statistics.mean(vals)
        std_ = statistics.pstdev(vals) if len(vals) > 1 else 0
        cv = (std_ / mean_ * 100) if mean_ else 0
        reg = ("regular" if cv < 25 else
               "moderada" if cv < 50 else "irregular")
        return {"mean": round(mean_, 2), "std": round(std_, 2),
                "cv_pct": round(cv, 1), "regularity": reg,
                "active_periods": len(vals)}

    return {
        "range": range_, "period": period,
        "from_date": from_date, "to_date": to_date,
        "series": series,
        "totals": {
            "income": round(sum(b["income"] for b in series), 2),
            "expense": round(sum(b["expense"] for b in series), 2),
            "net": round(sum(b["income"] - b["expense"] for b in series), 2),
        },
        "income_metrics": metric(income_vals),
        "expense_metrics": metric(expense_vals),
        "buckets": len(series),
    }


def _fill_continuous_buckets(from_date: str, to_date: str, period: str,
                              buckets: Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]:
    """Gera buckets contínuos no período, preenchendo zeros."""
    start = datetime.strptime(from_date, "%Y-%m-%d").date()
    end = datetime.strptime(to_date, "%Y-%m-%d").date()
    out: List[Dict[str, Any]] = []
    cur = start
    seen: set = set()
    while cur <= end:
        if period == "day":
            k = cur.strftime("%Y-%m-%d")
            cur += timedelta(days=1)
        elif period == "month":
            k = cur.strftime("%Y-%m")
            # next month
            year = cur.year + (cur.month // 12)
            month = (cur.month % 12) + 1
            try:
                cur = cur.replace(year=year, month=month, day=1)
            except ValueError:
                cur = cur.replace(year=year, month=month, day=1)
        elif period == "year":
            k = cur.strftime("%Y")
            cur = cur.replace(year=cur.year + 1, month=1, day=1)
        else:
            break
        if k in seen:
            continue
        seen.add(k)
        b = buckets.get(k, {"income": 0.0, "expense": 0.0})
        out.append({
            "period": k,
            "income": round(b["income"], 2),
            "expense": round(b["expense"], 2),
            "net": round(b["income"] - b["expense"], 2),
        })
    return out
