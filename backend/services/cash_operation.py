"""
cash_operation.py — V7.1 OPERAÇÃO CAIXA
KPI supremo: DINHEIRO RECEBIDO PELA IA.
Tudo o resto é meio. O caixa é o fim.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from database import db


def _now(): return datetime.now(timezone.utc)
def _iso(): return _now().isoformat()


def _periods() -> Dict[str, str]:
    now = _now()
    return {
        "today":  now.replace(hour=0, minute=0, second=0,
                               microsecond=0).isoformat(),
        "7d":     (now - timedelta(days=7)).isoformat(),
        "30d":    (now - timedelta(days=30)).isoformat(),
        "12m":    (now - timedelta(days=365)).isoformat(),
    }


async def _sum(col, match: Dict, field: str) -> Dict[str, Any]:
    pipe = [{"$match": match},
             {"$group": {"_id": None,
                          "t": {"$sum": f"${field}"},
                          "n": {"$sum": 1}}}]
    r = await db[col].aggregate(pipe).to_list(1)
    return {"BRL": round(float(r[0]["t"]) if r else 0, 2),
             "count": int(r[0]["n"]) if r else 0}


async def kpi_money_generated(company_id: str) -> Dict[str, Any]:
    """V7.1 FASE 7 — KPI supremo por período. Sempre separa
    Estimado/Confirmado/Recebido."""
    P = _periods()
    out = {}
    for label, cutoff in P.items():
        # Estimado = decisions com action_kind != noop
        est = await _sum("motor_ia_decisions",
                          {"company_id": company_id,
                            "created_at": {"$gte": cutoff},
                            "action_kind": {"$nin": [None, "noop"]}},
                          "expected_BRL")
        # Confirmado = actions executed/dispatched (lookup decisões)
        pipe_conf = [
            {"$match": {"company_id": company_id,
                         "created_at": {"$gte": cutoff},
                         "status": {"$in": ["executed", "dispatched"]}}},
            {"$lookup": {"from": "motor_ia_decisions",
                           "localField": "decision_id",
                           "foreignField": "decision_id", "as": "d"}},
            {"$unwind": "$d"},
            {"$group": {"_id": None,
                         "t": {"$sum": "$d.expected_BRL"},
                         "n": {"$sum": 1}}},
        ]
        conf_r = await db.motor_ia_actions.aggregate(
            pipe_conf).to_list(1)
        conf = {"BRL": round(float(conf_r[0]["t"]) if conf_r else 0, 2),
                "count": int(conf_r[0]["n"]) if conf_r else 0}
        # Recebido = outcomes com actual > 0
        recv = await _sum("motor_ia_outcomes",
                           {"company_id": company_id,
                             "observed_at": {"$gte": cutoff},
                             "actual_BRL": {"$gt": 0}},
                           "actual_BRL")
        out[label] = {"estimated": est, "confirmed": conf,
                       "received": recv,
                       "conversion_pct": round(
                           recv["BRL"] / max(conf["BRL"], 1) * 100, 1)
                       if conf["BRL"] > 0 else 0}
    return out


async def war_room(company_id: str) -> Dict[str, Any]:
    """V7.1 FASE 1 — OPERAÇÃO CAIXA painel único."""
    from services import financial_foundation as fin
    fa = await fin.summary(company_id)
    kpi = await kpi_money_generated(company_id)

    # Receita perdida = decisions completas com outcome 0 + churns 90d
    cutoff = (_now() - timedelta(days=7)).isoformat()
    lost_pipe = [
        {"$match": {"company_id": company_id,
                     "observed_at": {"$gte": cutoff},
                     "actual_BRL": {"$lte": 0}}},
        {"$lookup": {"from": "motor_ia_decisions",
                       "localField": "decision_id",
                       "foreignField": "decision_id", "as": "d"}},
        {"$unwind": "$d"},
        {"$group": {"_id": None,
                     "t": {"$sum": "$d.expected_BRL"},
                     "n": {"$sum": 1}}},
    ]
    lost = await db.motor_ia_outcomes.aggregate(lost_pipe).to_list(1)
    lost_BRL = float(lost[0]["t"]) if lost else 0

    headline = (
        f"Risco R$ {fa['revenue_at_risk']['monthly_BRL_at_risk']:,.0f} · "
        f"Recuperável R$ {fa['overdue']['overdue_BRL']:,.0f} · "
        f"Confirmado/30d R$ {kpi['30d']['confirmed']['BRL']:,.0f} · "
        f"Recebido/30d R$ {kpi['30d']['received']['BRL']:,.0f} · "
        f"Perdido/7d R$ {lost_BRL:,.0f}"
    )

    return {
        "generated_at": _iso(),
        "company_id": company_id,
        "headline": headline,
        "revenue_at_risk_BRL":   fa["revenue_at_risk"][
            "monthly_BRL_at_risk"],
        "revenue_recoverable_BRL": fa["overdue"]["overdue_BRL"],
        "revenue_estimated_30d":  kpi["30d"]["estimated"]["BRL"],
        "revenue_confirmed_30d":  kpi["30d"]["confirmed"]["BRL"],
        "revenue_received_30d":   kpi["30d"]["received"]["BRL"],
        "revenue_lost_7d_BRL":    round(lost_BRL, 2),
        "kpi_by_period": kpi,
    }


# ===== FASE 2 — Action-to-Cash pipeline ===== #

ACTION_STAGES = [
    "created",      # action criada
    "sent",         # WA enviado
    "delivered",    # entregue
    "read",         # lido
    "replied",      # respondeu
    "negotiated",   # houve negociação
    "paid",         # pagou
    "received",     # dinheiro caiu no caixa
]


async def action_to_cash(company_id: str,
                          days: int = 30) -> Dict[str, Any]:
    """V7.1 FASE 2 — Funil A2C completo."""
    cutoff = (_now() - timedelta(days=days)).isoformat()

    actions = await db.motor_ia_actions.find(
        {"company_id": company_id,
          "created_at": {"$gte": cutoff}}
    ).to_list(2000)

    funnel = {s: 0 for s in ACTION_STAGES}
    funnel["created"] = len(actions)

    # Stages observados: status = dispatched → sent; status = executed → "sent" (ticket)
    for a in actions:
        st = a.get("status")
        if st in ("dispatched", "executed"):
            funnel["sent"] += 1

    # entrega / leitura / resposta — vir de wa_messages se existir
    for stage_field, mongo_field in [
        ("delivered", "delivered_at"),
        ("read", "read_at"),
        ("replied", "replied_at"),
    ]:
        pipe = [
            {"$match": {"company_id": company_id,
                         "created_at": {"$gte": cutoff},
                         mongo_field: {"$exists": True,
                                        "$nin": [None, ""]}}},
            {"$count": "n"},
        ]
        r = await db.wa_messages.aggregate(pipe).to_list(1)
        funnel[stage_field] = int(r[0]["n"]) if r else 0

    # Pagamento + Recebido = invoices paid após ação
    paid_pipe = [
        {"$match": {"company_id": company_id,
                     "status": "paid",
                     "paid_date": {"$gte": cutoff}}},
        {"$count": "n"},
    ]
    paid_r = await db.subscriber_invoices.aggregate(
        paid_pipe).to_list(1)
    funnel["paid"] = int(paid_r[0]["n"]) if paid_r else 0
    funnel["received"] = funnel["paid"]  # se paid_date está setado, recebido

    # taxa de conversão
    rates = {}
    for i in range(1, len(ACTION_STAGES)):
        prev = funnel[ACTION_STAGES[i - 1]]
        cur = funnel[ACTION_STAGES[i]]
        rates[ACTION_STAGES[i]] = round(cur / max(prev, 1) * 100, 1)

    return {"funnel": funnel, "conversion_rates_pct": rates,
             "window_days": days}


# ===== FASE 3 — Rastreabilidade ===== #

async def revenue_attribution_by(company_id: str,
                                   group_by: str = "action_kind",
                                   days: int = 30) -> Dict[str, Any]:
    """V7.1 FASE 3 — Quem gerou dinheiro?
    group_by: action_kind | template_id | playbook | technician_id"""
    cutoff = (_now() - timedelta(days=days)).isoformat()
    pipe = [
        {"$match": {"company_id": company_id,
                     "observed_at": {"$gte": cutoff},
                     "actual_BRL": {"$gt": 0}}},
        {"$lookup": {"from": "motor_ia_decisions",
                       "localField": "decision_id",
                       "foreignField": "decision_id", "as": "d"}},
        {"$unwind": "$d"},
        {"$lookup": {"from": "motor_ia_actions",
                       "localField": "action_id",
                       "foreignField": "action_id", "as": "a"}},
        {"$unwind": "$a"},
        {"$group": {
            "_id": (f"$d.{group_by}" if group_by == "action_kind"
                     else (f"$a.{group_by}" if group_by == "template_id"
                            or group_by == "playbook"
                            else f"$a.payload.{group_by}")),
            "actual_BRL": {"$sum": "$actual_BRL"},
            "expected_BRL": {"$sum": "$d.expected_BRL"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"actual_BRL": -1}},
        {"$limit": 50},
    ]
    rows = await db.motor_ia_outcomes.aggregate(pipe).to_list(50)
    items = [{
        "key": (r["_id"] or "—"),
        "actual_BRL": round(r["actual_BRL"], 2),
        "expected_BRL": round(r["expected_BRL"], 2),
        "events": r["count"],
        "roi_pct": round(r["actual_BRL"] / max(r["expected_BRL"], 1) * 100, 1),
    } for r in rows]
    return {"group_by": group_by, "items": items,
             "window_days": days}


# ===== FASE 4 — GO LIVE Controller ===== #

async def go_live_status(company_id: str) -> Dict[str, Any]:
    """V7.1 FASE 4 — VERDE ou BLOQUEADO. Sem meio termo."""
    from services import transport_check as tx
    tr = await tx.wa_status(company_id)
    state = "VERDE" if tr["can_send"] else "BLOQUEADO"
    return {
        "state":             state,
        "can_send":          tr["can_send"],
        "checks":            tr["checks"],
        "blockers":          tr["blockers"],
        "session_status":    tr.get("session_status"),
        "sidecar_error":     tr.get("sidecar_error"),
        "checked_at":        tr.get("checked_at"),
        "next_step":         (
            "✓ Operação Tese ATIVA · ações financeiras serão executadas"
            if tr["can_send"] else
            "Configurar credenciais no backend/.env "
            "+ scan QR Baileys → status=open"),
    }


# ===== FASE 6 — Top 10 ações financeiras priorizadas ===== #

async def top_money_actions(company_id: str,
                              top_n: int = 10) -> Dict[str, Any]:
    """V7.1 FASE 6 — 'O que preciso fazer hoje para colocar
    mais dinheiro no caixa?' — Top 10 por ROI."""
    from services import real_revenue
    prio = await real_revenue.roi_priorities(company_id)
    return {"items": prio[:top_n], "count": min(len(prio), top_n),
             "total_BRL": round(sum(i["roi_BRL"] for i in prio[:top_n]), 2)}
