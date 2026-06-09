"""
public_smartprov.py — FASE 9 (V5.0 Prioridade Nº 4)
Endpoint público SEM auth para a landing /smartprov-ai-center.
Demonstra valor em < 60 segundos.

⚠️ Saneamento: nada de PII (nome/CPF/email/telefone).
Só agregados financeiros e técnicos com `company_id` único do "showcase".
"""
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter

from database import db
from services import financial_foundation as fin
from services import smartolt_twin
from services import multitenant_audit as mt

# Empresa-vitrine (default = co-demo)
import os
SHOWCASE_COMPANY = os.environ.get("PUBLIC_SHOWCASE_COMPANY", "co-demo")

router = APIRouter(prefix="/api/public/smartprov-ai-center",
                    tags=["public-landing"])


@router.get("/kpis")
async def public_kpis():
    """Snapshot ao vivo dos KPIs vendáveis (60s pitch)."""
    co = SHOWCASE_COMPANY
    f = await fin.summary(co)
    cto = await smartolt_twin.cto_health(co)
    onu_pipe = [
        {"$match": {"company_id": co,
                     "smartolt_onu_zone": {"$nin": [None, ""]}}},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "online": {"$sum": {"$cond": [
                {"$eq": ["$smartolt_onu_status", "Online"]}, 1, 0]}},
            "offline": {"$sum": {"$cond": [
                {"$in": ["$smartolt_onu_status",
                          ["Offline", "LOS", "Power fail"]]}, 1, 0]}},
        }},
    ]
    onu_doc = await db.subscribers.aggregate(onu_pipe).to_list(1)
    onu = (onu_doc[0] if onu_doc else
           {"total": 0, "online": 0, "offline": 0})
    onu_health_pct = (round(onu["online"] / max(onu["total"], 1) * 100, 1)
                       if onu["total"] else 0)
    audit = await mt.audit_orphans()

    # Sistema Nervoso 24h
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    events_24h = await db.motor_ia_events.count_documents({
        "company_id": co, "created_at": {"$gte": cutoff}})
    decisions_24h = await db.motor_ia_decisions.count_documents({
        "company_id": co, "created_at": {"$gte": cutoff}})
    actions_24h = await db.motor_ia_actions.count_documents({
        "company_id": co, "created_at": {"$gte": cutoff}})

    # Isabella scores
    high_churn = await db.motor_ia_subscriber_scores.count_documents({
        "company_id": co, "churn_score": {"$gte": 0.7}})
    high_upgrade = await db.motor_ia_subscriber_scores.count_documents({
        "company_id": co, "upgrade_score": {"$gte": 0.7}})
    high_buy = await db.motor_ia_subscriber_scores.count_documents({
        "company_id": co, "buy_score": {"$gte": 0.7}})

    # CTOs criticas
    cto_crit = len([c for c in cto if c.get("score", 100) < 70])

    return {
        "showcase": "SmartProv AI OS · Demonstração ao vivo",
        "generated_at": datetime.now(timezone.utc).isoformat(),

        "headline": f["headline"],

        "financial": {
            "mrr_BRL": f["mrr"]["mrr_BRL"],
            "arr_BRL": f["arr"]["arr_BRL"],
            "ltv_BRL": f["ltv"]["ltv_BRL"],
            "active_subscribers": f["mrr"]["active_subscribers"],
            "avg_ticket_BRL": f["mrr"]["avg_ticket"],
            "revenue_at_risk_BRL": f["revenue_at_risk"]["monthly_BRL_at_risk"],
            "subscribers_at_risk": f["revenue_at_risk"]["subscribers_at_risk"],
            "overdue_BRL": f["overdue"]["overdue_BRL"],
            "overdue_count": f["overdue"]["overdue_count"],
            "collected_mtd_BRL": f["collected_mtd"]["collected_MTD_BRL"],
            "ia_attribution_BRL": f["ia_attribution"]["total_BRL"],
        },

        "network": {
            "ctos_total": len(cto),
            "ctos_critical": cto_crit,
            "onus_total": onu.get("total", 0),
            "onus_online": onu.get("online", 0),
            "onus_offline": onu.get("offline", 0),
            "onu_health_pct": onu_health_pct,
        },

        "nervous_system_24h": {
            "events": events_24h,
            "decisions": decisions_24h,
            "actions": actions_24h,
        },

        "isabella_engine": {
            "high_churn_risk": high_churn,
            "high_upgrade_potential": high_upgrade,
            "high_buy_intent": high_buy,
        },

        "governance": {
            "multitenant_orphans": audit["summary"]["total_orphans"],
            "multitenant_status": audit["summary"]["status"],
            "data_coverage_pct": round(100 - audit["summary"]["orphan_pct"], 2),
        },

        "modules_active": [
            "RevenueOps IA", "Isabella Revenue Engine",
            "Álvaro Diretor de Operações", "SmartOLT Digital Twin",
            "Knowledge Graph (IA Explicável)", "Sistema Nervoso",
            "Operação Tese (recuperação WhatsApp)",
            "Multi-Tenant Blindado", "Financial Foundation",
        ],

        "executive_actions": f["executive_actions"],
    }


@router.get("/health")
async def public_health():
    return {"status": "ok",
             "service": "smartprov-ai-center-landing"}
