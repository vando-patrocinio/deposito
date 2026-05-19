"""Relatórios Financeiros — KPIs agregados (DRE, Aging, Top Categorias, etc).

Endpoints servem o painel de Relatórios do Financeiro.
Todos requerem role administrador/financeiro/auditor.

Convenções:
  - Períodos no formato YYYY-MM-DD
  - RECEITAS = fin_cash_movements (type=income) + subscriber_invoices (pagas)
  - DESPESAS = fin_cash_movements (type=expense)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from core import DEMO_COMPANY_ID
from database import db
from routes.financeiro import require_finance

logger = logging.getLogger("ponto.financeiro_reports")
router = APIRouter(prefix="/api/financeiro/reports", tags=["financeiro-reports"])


def _today_str() -> str:
    return datetime.now(timezone.utc).date().strftime("%Y-%m-%d")


def _resolve_period(month: Optional[str], year: Optional[int]) -> tuple[str, str, str]:
    """Devolve (from_date, to_date, label) baseado em month=YYYY-MM ou year=YYYY.
    Se nenhum for fornecido, usa o mês corrente.
    """
    today = datetime.now(timezone.utc).date()
    if year:
        return (f"{year}-01-01", f"{year}-12-31", str(year))
    if month:
        try:
            y, m = map(int, month.split("-"))
        except (ValueError, AttributeError):
            y, m = today.year, today.month
    else:
        y, m = today.year, today.month
    nm_year = y + (m // 12)
    nm_month = (m % 12) + 1
    last_day = (datetime(nm_year, nm_month, 1).date() - timedelta(days=1))
    return (f"{y:04d}-{m:02d}-01", last_day.strftime("%Y-%m-%d"),
            f"{y:04d}-{m:02d}")


# ===========================================================================
# DRE — Demonstração do Resultado do Exercício (versão simplificada)
# ===========================================================================
@router.get("/dre")
async def dre(
    month: Optional[str] = Query(None,
        pattern="^\\d{4}-\\d{2}$",
        description="Mês YYYY-MM (default: mês corrente)"),
    year: Optional[int] = Query(None, ge=2020, le=2100,
        description="Se informado, gera DRE anual (sobrepõe `month`)"),
    user: dict = Depends(require_finance()),
):
    """DRE simplificado: receitas, despesas por categoria, lucro/prejuízo.

    Estrutura:
      Receitas Brutas
      (-) Despesas Operacionais (por categoria)
      = Resultado Líquido
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    from_date, to_date, label = _resolve_period(month, year)

    # Carrega categorias pra mostrar nome/cor
    cat_map: Dict[str, Dict[str, Any]] = {}
    async for c in db.fin_categories.find(
        {"company_id": cid}, {"_id": 0, "id": 1, "name": 1, "kind": 1, "color": 1},
    ):
        cat_map[c["id"]] = c

    # Receitas: cash_movements income + invoices pagas
    income_total = 0.0
    income_by_cat: Dict[str, float] = {}
    async for m in db.fin_cash_movements.find(
        {"company_id": cid, "type": "income",
            "date": {"$gte": from_date, "$lte": to_date}},
        {"_id": 0, "amount": 1, "category_id": 1},
    ):
        v = float(m.get("amount") or 0)
        income_total += v
        cid_ = m.get("category_id") or "_uncategorized"
        income_by_cat[cid_] = income_by_cat.get(cid_, 0) + v

    invoices_total = 0.0
    async for inv in db.subscriber_invoices.find(
        {"company_id": cid, "paid_date": {"$ne": None,
            "$gte": from_date, "$lte": to_date}},
        {"_id": 0, "amount_paid": 1, "amount": 1},
    ):
        invoices_total += float(inv.get("amount_paid") or inv.get("amount") or 0)

    # Despesas
    expense_total = 0.0
    expense_by_cat: Dict[str, float] = {}
    async for m in db.fin_cash_movements.find(
        {"company_id": cid, "type": "expense",
            "date": {"$gte": from_date, "$lte": to_date}},
        {"_id": 0, "amount": 1, "category_id": 1},
    ):
        v = float(m.get("amount") or 0)
        expense_total += v
        cid_ = m.get("category_id") or "_uncategorized"
        expense_by_cat[cid_] = expense_by_cat.get(cid_, 0) + v

    def _expand(by_cat: Dict[str, float]) -> List[Dict[str, Any]]:
        items = []
        for k, v in sorted(by_cat.items(), key=lambda x: -x[1]):
            cat = cat_map.get(k)
            items.append({
                "category_id": k,
                "name": cat.get("name") if cat else "Sem categoria",
                "color": cat.get("color") if cat else None,
                "amount": round(v, 2),
            })
        return items

    revenue = round(income_total + invoices_total, 2)
    expenses = round(expense_total, 2)
    net = round(revenue - expenses, 2)
    margin_pct = (net / revenue * 100) if revenue > 0 else 0

    return {
        "period": {"from": from_date, "to": to_date, "label": label},
        "revenue": {
            "total": revenue,
            "movements_income": round(income_total, 2),
            "subscriber_invoices_paid": round(invoices_total, 2),
            "by_category": _expand(income_by_cat),
        },
        "expenses": {
            "total": expenses,
            "by_category": _expand(expense_by_cat),
        },
        "net": net,
        "margin_pct": round(margin_pct, 2),
        "status": "positive" if net > 0 else "negative" if net < 0 else "neutral",
    }


# ===========================================================================
# Aging Payable — contas a pagar agrupadas por faixas de vencimento
# ===========================================================================
@router.get("/aging-payable")
async def aging_payable(user: dict = Depends(require_finance())):
    """Aging de contas a pagar (não pagas) por faixa de atraso/proximidade.

    Buckets:
      • a_vencer_30:    vencimento dentro de 30 dias
      • a_vencer_60:    31-60 dias
      • a_vencer_90:    61-90 dias
      • a_vencer_mais:  > 90 dias
      • vencido_30:     vencido até 30 dias
      • vencido_60:     vencido 31-60 dias
      • vencido_90:     vencido 61-90 dias
      • vencido_mais:   vencido > 90 dias
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    today = datetime.now(timezone.utc).date()

    buckets = {
        "vencido_mais": {"label": "Vencido > 90 dias", "count": 0, "total": 0.0},
        "vencido_90":   {"label": "Vencido 61-90", "count": 0, "total": 0.0},
        "vencido_60":   {"label": "Vencido 31-60", "count": 0, "total": 0.0},
        "vencido_30":   {"label": "Vencido até 30", "count": 0, "total": 0.0},
        "a_vencer_30":  {"label": "A vencer ≤30 dias", "count": 0, "total": 0.0},
        "a_vencer_60":  {"label": "A vencer 31-60", "count": 0, "total": 0.0},
        "a_vencer_90":  {"label": "A vencer 61-90", "count": 0, "total": 0.0},
        "a_vencer_mais": {"label": "A vencer > 90 dias", "count": 0, "total": 0.0},
    }

    async for b in db.fin_bills_payable.find(
        {"company_id": cid, "status": {"$in": ["pending", "overdue"]}},
        {"_id": 0, "amount": 1, "due_date": 1},
    ):
        try:
            due = datetime.strptime(b["due_date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        diff = (due - today).days
        amt = float(b.get("amount") or 0)
        if diff < -90:
            key = "vencido_mais"
        elif diff < -60:
            key = "vencido_90"
        elif diff < -30:
            key = "vencido_60"
        elif diff < 0:
            key = "vencido_30"
        elif diff <= 30:
            key = "a_vencer_30"
        elif diff <= 60:
            key = "a_vencer_60"
        elif diff <= 90:
            key = "a_vencer_90"
        else:
            key = "a_vencer_mais"
        buckets[key]["count"] += 1
        buckets[key]["total"] = round(buckets[key]["total"] + amt, 2)

    overdue_total = sum(
        b["total"] for k, b in buckets.items() if k.startswith("vencido")
    )
    upcoming_total = sum(
        b["total"] for k, b in buckets.items() if k.startswith("a_vencer")
    )

    return {
        "buckets": [{"key": k, **v} for k, v in buckets.items()],
        "summary": {
            "overdue_total": round(overdue_total, 2),
            "upcoming_total": round(upcoming_total, 2),
            "grand_total": round(overdue_total + upcoming_total, 2),
        },
        "today": today.strftime("%Y-%m-%d"),
    }


# ===========================================================================
# Top fornecedores e categorias (no período)
# ===========================================================================
@router.get("/top-suppliers")
async def top_suppliers(
    limit: int = Query(10, ge=1, le=50),
    month: Optional[str] = Query(None, pattern="^\\d{4}-\\d{2}$"),
    year: Optional[int] = Query(None, ge=2020, le=2100),
    user: dict = Depends(require_finance()),
):
    """Top fornecedores por valor de despesa no período."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    from_date, to_date, _ = _resolve_period(month, year)

    # Resolve nomes de fornecedores
    sup_map: Dict[str, str] = {}
    async for s in db.fin_suppliers.find(
        {"company_id": cid}, {"_id": 0, "id": 1, "name": 1},
    ):
        sup_map[s["id"]] = s["name"]

    totals: Dict[str, Dict[str, Any]] = {}
    # bills (pagas + pendentes) atribuídas a fornecedor
    async for bill in db.fin_bills_payable.find(
        {"company_id": cid,
          "due_date": {"$gte": from_date, "$lte": to_date},
          "supplier_id": {"$ne": None}},
        {"_id": 0, "amount": 1, "supplier_id": 1, "status": 1},
    ):
        sid = bill["supplier_id"]
        t = totals.setdefault(sid, {"total": 0.0, "count": 0, "paid": 0, "pending": 0})
        t["total"] = round(t["total"] + float(bill.get("amount") or 0), 2)
        t["count"] += 1
        if bill.get("status") == "paid":
            t["paid"] += 1
        else:
            t["pending"] += 1

    rows = sorted(
        [{"supplier_id": k, "supplier_name": sup_map.get(k, "?"), **v}
            for k, v in totals.items()],
        key=lambda x: -x["total"],
    )[:limit]

    return {
        "period": {"from": from_date, "to": to_date},
        "rows": rows,
        "total": round(sum(r["total"] for r in rows), 2),
    }


# ===========================================================================
# KPI summary — cabeçalho da aba Relatórios
# ===========================================================================
@router.get("/kpis")
async def kpis(
    month: Optional[str] = Query(None, pattern="^\\d{4}-\\d{2}$"),
    user: dict = Depends(require_finance()),
):
    """KPI panel — saldo, receita/despesa do mês, faturas pendentes, etc."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    from_date, to_date, label = _resolve_period(month, None)

    # Saldo agregado
    total_balance = 0.0
    async for ca in db.fin_cash_accounts.find(
        {"company_id": cid, "active": True},
        {"_id": 0, "current_balance": 1},
    ):
        total_balance += float(ca.get("current_balance") or 0)

    # Receita do mês
    income = 0.0
    async for m in db.fin_cash_movements.find(
        {"company_id": cid, "type": "income",
            "date": {"$gte": from_date, "$lte": to_date}},
        {"_id": 0, "amount": 1},
    ):
        income += float(m.get("amount") or 0)
    async for inv in db.subscriber_invoices.find(
        {"company_id": cid, "paid_date": {"$ne": None,
            "$gte": from_date, "$lte": to_date}},
        {"_id": 0, "amount_paid": 1, "amount": 1},
    ):
        income += float(inv.get("amount_paid") or inv.get("amount") or 0)

    # Despesa do mês
    expense = 0.0
    async for m in db.fin_cash_movements.find(
        {"company_id": cid, "type": "expense",
            "date": {"$gte": from_date, "$lte": to_date}},
        {"_id": 0, "amount": 1},
    ):
        expense += float(m.get("amount") or 0)

    # Bills pendentes/vencidas
    pending_count = await db.fin_bills_payable.count_documents(
        {"company_id": cid, "status": "pending"},
    )
    pending_total = 0.0
    async for b in db.fin_bills_payable.find(
        {"company_id": cid, "status": "pending"},
        {"_id": 0, "amount": 1},
    ):
        pending_total += float(b.get("amount") or 0)

    overdue_count = await db.fin_bills_payable.count_documents(
        {"company_id": cid, "status": "overdue"},
    )
    overdue_total = 0.0
    async for b in db.fin_bills_payable.find(
        {"company_id": cid, "status": "overdue"},
        {"_id": 0, "amount": 1},
    ):
        overdue_total += float(b.get("amount") or 0)

    net = round(income - expense, 2)
    return {
        "period": {"from": from_date, "to": to_date, "label": label},
        "total_balance": round(total_balance, 2),
        "income_month": round(income, 2),
        "expense_month": round(expense, 2),
        "net_month": net,
        "margin_pct": round((net / income * 100) if income > 0 else 0, 2),
        "pending": {"count": pending_count, "total": round(pending_total, 2)},
        "overdue": {"count": overdue_count, "total": round(overdue_total, 2)},
    }
