"""
financial_foundation.py — FASE 11 (V5.0 / Prioridade Nº 1)
Calcula MRR, ARR, LTV, revenue_at_risk, churn_cost — base canônica.
Sob demanda, sem duplicar dado.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from database import db

ACTIVE_STATUS = {"ATIVO", "active", "ativo"}


def _now(): return datetime.now(timezone.utc)


async def mrr(company_id: str) -> Dict[str, Any]:
    """Monthly Recurring Revenue = soma plan_price dos ATIVOS."""
    pipe = [
        {"$match": {"company_id": company_id,
                     "status": {"$in": list(ACTIVE_STATUS)},
                     "plan_price": {"$gt": 0}}},
        {"$group": {"_id": None,
                     "total": {"$sum": "$plan_price"},
                     "count": {"$sum": 1},
                     "avg": {"$avg": "$plan_price"}}},
    ]
    r = await db.subscribers.aggregate(pipe).to_list(1)
    if not r:
        return {"mrr_BRL": 0.0, "active_subscribers": 0, "avg_ticket": 0.0}
    d = r[0]
    return {
        "mrr_BRL": round(d["total"], 2),
        "active_subscribers": d["count"],
        "avg_ticket": round(d["avg"], 2),
    }


async def arr(company_id: str) -> Dict[str, Any]:
    m = await mrr(company_id)
    return {**m, "arr_BRL": round(m["mrr_BRL"] * 12, 2)}


async def ltv(company_id: str) -> Dict[str, Any]:
    """Lifetime Value: ticket × tenure médio (meses) × margem 0.75."""
    # tenure médio = idade média dos subscribers ATIVOS (em meses)
    pipe = [
        {"$match": {"company_id": company_id,
                     "status": {"$in": list(ACTIVE_STATUS)},
                     "activation_date": {"$nin": [None, ""]}}},
        {"$project": {"activation_date": 1}},
        {"$limit": 5000},
    ]
    months = []
    now = _now()
    async for s in db.subscribers.aggregate(pipe):
        try:
            d = s["activation_date"]
            if isinstance(d, str):
                d = datetime.fromisoformat(d.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            months.append(max((now - d).days / 30.0, 1))
        except Exception:
            continue
    avg_tenure = round(sum(months) / max(len(months), 1), 1) if months else 24.0
    m = await mrr(company_id)
    ticket = m["avg_ticket"]
    ltv_v = round(ticket * avg_tenure * 0.75, 2)
    return {
        "ltv_BRL": ltv_v,
        "avg_tenure_months": avg_tenure,
        "avg_ticket": ticket,
        "margin_assumption": 0.75,
    }


async def revenue_at_risk(company_id: str) -> Dict[str, Any]:
    """Subscribers com churn_score >= 0.7 ou ONU offline + soma do plan_price."""
    # 1) via Isabella scores
    risk_subs = await db.motor_ia_subscriber_scores.find(
        {"company_id": company_id, "churn_score": {"$gte": 0.7}},
        {"subscriber_id": 1, "churn_score": 1}
    ).limit(5000).to_list(5000)
    risk_ids = [r["subscriber_id"] for r in risk_subs]
    # 2) ONU offline (degradação técnica → risco financeiro)
    cur = db.subscribers.find(
        {"company_id": company_id,
         "smartolt_onu_status": {"$in": ["Offline", "LOS", "Power fail"]}},
        {"id": 1, "plan_price": 1}
    ).limit(5000)
    onu_risk_ids = []
    async for s in cur:
        onu_risk_ids.append(s["id"])
    all_ids = list(set(risk_ids + onu_risk_ids))
    if not all_ids:
        return {"monthly_BRL_at_risk": 0.0, "yearly_BRL_at_risk": 0.0,
                "subscribers_at_risk": 0, "sources": {
                    "isabella_churn_high": 0, "onu_degraded": 0}}
    rows = await db.subscribers.find(
        {"company_id": company_id, "id": {"$in": all_ids}},
        {"plan_price": 1}).to_list(len(all_ids))
    total = sum((r.get("plan_price") or 0) for r in rows)
    return {
        "monthly_BRL_at_risk": round(total, 2),
        "yearly_BRL_at_risk": round(total * 12, 2),
        "subscribers_at_risk": len(rows),
        "sources": {
            "isabella_churn_high": len(risk_ids),
            "onu_degraded": len(onu_risk_ids),
        },
    }


async def churn_cost(company_id: str, days: int = 90) -> Dict[str, Any]:
    """Custo do churn = subscribers cancelados nos últimos N dias ×
    plan_price × tenure_meses (perda real de LTV)."""
    cutoff = (_now() - timedelta(days=days)).isoformat()
    cur = db.subscribers.find(
        {"company_id": company_id,
         "status": {"$in": ["INATIVO", "inactive", "CANCELADO", "cancelled"]},
         "cancellation_date": {"$gte": cutoff}},
        {"plan_price": 1, "activation_date": 1, "cancellation_date": 1}
    ).limit(2000)
    lost_mrr = 0.0
    lost_ltv = 0.0
    count = 0
    now = _now()
    async for s in cur:
        count += 1
        price = float(s.get("plan_price") or 0)
        lost_mrr += price
        # tenure até cancelamento
        try:
            act = s.get("activation_date")
            can = s.get("cancellation_date") or now.isoformat()
            if isinstance(act, str):
                act = datetime.fromisoformat(act.replace("Z", "+00:00"))
            if isinstance(can, str):
                can = datetime.fromisoformat(can.replace("Z", "+00:00"))
            if act and act.tzinfo is None:
                act = act.replace(tzinfo=timezone.utc)
            if can and can.tzinfo is None:
                can = can.replace(tzinfo=timezone.utc)
            tenure_m = max((can - act).days / 30.0, 1) if act else 12
        except Exception:
            tenure_m = 12
        lost_ltv += price * tenure_m * 0.75
    return {
        "period_days": days,
        "churned_count": count,
        "monthly_revenue_lost_BRL": round(lost_mrr, 2),
        "ltv_lost_BRL": round(lost_ltv, 2),
        "yearly_run_rate_lost_BRL": round(lost_mrr * 12, 2),
    }


async def overdue_summary(company_id: str) -> Dict[str, Any]:
    """Faturas overdue agregadas — receita represada."""
    pipe = [
        {"$match": {"company_id": company_id, "status": "overdue"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"},
                     "count": {"$sum": 1}}},
    ]
    r = await db.subscriber_invoices.aggregate(pipe).to_list(1)
    if not r:
        return {"overdue_BRL": 0.0, "overdue_count": 0}
    return {"overdue_BRL": round(r[0]["total"], 2),
            "overdue_count": r[0]["count"]}


async def revenue_collected_mtd(company_id: str) -> Dict[str, Any]:
    """Receita coletada no mês atual (paid in current month)."""
    now = _now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0,
                               microsecond=0).date().isoformat()
    pipe = [
        {"$match": {"company_id": company_id, "status": "paid",
                     "paid_date": {"$gte": month_start}}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"},
                     "count": {"$sum": 1}}},
    ]
    r = await db.subscriber_invoices.aggregate(pipe).to_list(1)
    if not r:
        return {"collected_MTD_BRL": 0.0, "invoices_paid_MTD": 0}
    return {"collected_MTD_BRL": round(r[0]["total"], 2),
            "invoices_paid_MTD": r[0]["count"]}


async def summary(company_id: str) -> Dict[str, Any]:
    """Painel financeiro executivo unificado."""
    m = await mrr(company_id)
    a = await arr(company_id)
    lv = await ltv(company_id)
    rar = await revenue_at_risk(company_id)
    cc = await churn_cost(company_id)
    od = await overdue_summary(company_id)
    coll = await revenue_collected_mtd(company_id)

    # ROI da IA (RevenueOps attribution)
    from services import revenue_attribution as rev
    ia_total = await rev.summary(company_id)

    # Receita protegida = MRR - revenue_at_risk
    protected = max(m["mrr_BRL"] - rar["monthly_BRL_at_risk"], 0)
    return {
        "company_id": company_id,
        "generated_at": _now().isoformat(),
        "headline": (
            f"MRR R$ {m['mrr_BRL']:,.0f} · "
            f"ARR R$ {a['arr_BRL']:,.0f} · "
            f"Em risco R$ {rar['monthly_BRL_at_risk']:,.0f}/mês · "
            f"Coletado MTD R$ {coll['collected_MTD_BRL']:,.0f}"
        ),
        "mrr": m,
        "arr": a,
        "ltv": lv,
        "revenue_at_risk": rar,
        "churn_cost_90d": cc,
        "overdue": od,
        "collected_mtd": coll,
        "revenue_protected_BRL": round(protected, 2),
        "ia_attribution": {
            "total_BRL": ia_total.get("_total_BRL", 0),
            "events": ia_total.get("_total_events", 0),
        },
        "executive_actions": _generate_actions(
            m, rar, cc, od, ia_total.get("_total_BRL", 0)),
    }


def _generate_actions(m, rar, cc, od, ia_total) -> List[Dict[str, Any]]:
    """V5.0: toda tela termina com 'próxima ação'."""
    out = []
    if rar["monthly_BRL_at_risk"] > 0:
        out.append({
            "priority": "ALTA",
            "problem": (f"R$ {rar['monthly_BRL_at_risk']:,.2f}/mês em risco "
                          f"({rar['subscribers_at_risk']} clientes)"),
            "action": ("Disparar Operação Tese sobre Tier B (churn score "
                        ">=0.7) + visita preventiva nas ONUs degradadas"),
            "expected_BRL": round(rar["monthly_BRL_at_risk"] * 0.4, 2),
        })
    if od["overdue_BRL"] > 0:
        out.append({
            "priority": "ALTA",
            "problem": (f"R$ {od['overdue_BRL']:,.2f} em "
                          f"{od['overdue_count']} faturas overdue"),
            "action": ("Operação Tese sobre Tier C (blindados) — recuperação "
                        "automática WhatsApp"),
            "expected_BRL": round(od["overdue_BRL"] * 0.18, 2),
        })
    if cc["monthly_revenue_lost_BRL"] > 0:
        out.append({
            "priority": "MEDIA",
            "problem": (f"R$ {cc['monthly_revenue_lost_BRL']:,.2f}/mês "
                          f"perdidos com {cc['churned_count']} churns 90d"),
            "action": ("Win-back automático: campanha 70% desconto 3 meses "
                        "via WA para últimos cancelados"),
            "expected_BRL": round(cc["monthly_revenue_lost_BRL"] * 0.15, 2),
        })
    if ia_total > 0:
        out.append({
            "priority": "INFO",
            "problem": f"IA gerou/recuperou R$ {ia_total:,.2f}",
            "action": "Manter Operação Tese e RevenueOps no ar",
            "expected_BRL": 0,
        })
    return out
