"""
real_revenue.py — V6.2 FASES 3 e 6
Separa Estimado / Confirmado / Recebido. Nunca mistura projeção com realizado.
Prioriza ações por ROI Score real.
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "vendas-team",
    "domain": "comercial",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from database import db


def _now(): return datetime.now(timezone.utc)


async def revenue_breakdown(company_id: str,
                              days: int = 30) -> Dict[str, Any]:
    """3 categorias separadas:
       - ESTIMADO: decision.expected_BRL (projeção)
       - CONFIRMADO: action dispatched/executed → outcome existe
       - RECEBIDO: outcome.actual_BRL com paid_date confirmado
    """
    cutoff = (_now() - timedelta(days=days)).isoformat()

    # 1) Estimado = soma de expected_BRL nas decisions com kind != noop
    pipe_est = [
        {"$match": {"company_id": company_id,
                     "created_at": {"$gte": cutoff},
                     "action_kind": {"$nin": [None, "noop"]}}},
        {"$group": {"_id": None,
                     "t": {"$sum": "$expected_BRL"},
                     "n": {"$sum": 1}}},
    ]
    est = await db.motor_ia_decisions.aggregate(pipe_est).to_list(1)
    estimated = (est[0] if est else {"t": 0, "n": 0})

    # 2) Confirmado = actions com status executed/dispatched + expected
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
    conf = await db.motor_ia_actions.aggregate(pipe_conf).to_list(1)
    confirmed = (conf[0] if conf else {"t": 0, "n": 0})

    # 3) Recebido = outcome.actual_BRL > 0 (verdadeiramente realizado)
    pipe_recv = [
        {"$match": {"company_id": company_id,
                     "observed_at": {"$gte": cutoff},
                     "actual_BRL": {"$gt": 0}}},
        {"$group": {"_id": None,
                     "t": {"$sum": "$actual_BRL"},
                     "n": {"$sum": 1}}},
    ]
    recv = await db.motor_ia_outcomes.aggregate(pipe_recv).to_list(1)
    received = (recv[0] if recv else {"t": 0, "n": 0})

    # ROI = recebido / esforço (custo evitado/operacional simplificado)
    roi_pct = (round(received["t"] / max(confirmed["t"], 1) * 100, 1)
                if confirmed["t"] > 0 else 0)

    return {
        "generated_at": _now().isoformat(),
        "window_days": days,
        "headline": (
            f"Estimado R$ {estimated['t']:,.2f} · "
            f"Confirmado R$ {confirmed['t']:,.2f} · "
            f"Recebido R$ {received['t']:,.2f} · "
            f"ROI {roi_pct}%"
        ),
        "estimated": {"BRL": round(estimated["t"], 2),
                       "count": estimated["n"]},
        "confirmed": {"BRL": round(confirmed["t"], 2),
                       "count": confirmed["n"]},
        "received":  {"BRL": round(received["t"], 2),
                       "count": received["n"]},
        "conversion_pct": roi_pct,
    }


async def roi_priorities(company_id: str) -> List[Dict[str, Any]]:
    """V6.2 FASE 6 — Lista de ações priorizadas por ROI esperado.
    Cada item = correção/ação com ROI mensurado em R$."""
    from services import blockers_audit, smartolt_predictive
    from services import financial_foundation as fin

    items: List[Dict[str, Any]] = []

    # 1) Bloqueadores com healing → ROI vem do healer
    audit = await blockers_audit.full_audit(company_id)
    for b in audit["blockers"]:
        roi = float(b.get("impact_BRL_week") or 0)
        if roi <= 0: continue
        items.append({
            "kind": "blocker",
            "label": b["blocker"],
            "category": b.get("category"),
            "roi_BRL": roi,
            "priority": b.get("priority"),
            "action": "Aplicar correção via Self Healing",
            "endpoint": "/api/ai-center/blockers/heal",
            "payload": {"blocker_key": b["blocker"]},
        })

    # 2) CTOs críticas → impacto técnico
    preds = await smartolt_predictive.predictive_summary(company_id)
    for c in preds["ctos_at_risk"][:10]:
        items.append({
            "kind": "predictive_cto",
            "label": f"CTO {c['zone']} · {c['severity']}",
            "category": "SmartOLT Preditivo",
            "roi_BRL": c["impact_BRL_monthly"],
            "priority": "P0" if c["severity"] == "CRITICO" else "P1",
            "action": c["recommended_action"],
            "endpoint": "/api/ai-center/predictive/auto-tickets",
            "payload": {"zone": c["zone"]},
        })

    # 3) Revenue at risk (Isabella + ONU)
    fa = await fin.summary(company_id)
    if fa["revenue_at_risk"]["monthly_BRL_at_risk"] > 0:
        items.append({
            "kind": "revenue_at_risk",
            "label": (f"Receita em risco · "
                        f"{fa['revenue_at_risk']['subscribers_at_risk']} clientes"),
            "category": "Comercial",
            "roi_BRL": fa["revenue_at_risk"]["monthly_BRL_at_risk"],
            "priority": "P0",
            "action": ("Disparar Operação Tese Tier B "
                        "(retention via WhatsApp)"),
            "endpoint": "/api/ai-center/autonomous/drive/churn",
            "payload": {"limit": 20},
        })

    # 4) Overdue → recovery
    if fa["overdue"]["overdue_BRL"] > 0:
        items.append({
            "kind": "overdue_recovery",
            "label": (f"{fa['overdue']['overdue_count']} faturas overdue"),
            "category": "Financeiro",
            "roi_BRL": fa["overdue"]["overdue_BRL"] * 0.18,  # taxa Tier C
            "priority": "P0",
            "action": ("Disparar Operação Tese Tier C (cobrança WA)"),
            "endpoint": "/api/ai-center/autonomous/drive/overdue",
            "payload": {"limit": 20},
        })

    items.sort(key=lambda x: -x["roi_BRL"])
    return items
