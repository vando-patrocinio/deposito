"""
multitenant_audit.py — FASE 8 service
Audita orfandade e leak risk em runtime (chamada via endpoint).
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

from datetime import datetime, timezone
from typing import Any, Dict, List

from database import db

BUSINESS_COLLECTIONS = [
    "subscribers", "tickets", "appointments", "subscriber_invoices",
    "sales_leads", "collaborators", "users",
    "motor_ia_subscriber_scores", "motor_ia_revenue_attribution",
    "motor_ia_daily_briefings", "motor_ia_isabella_journeys",
    "motor_ia_knowledge_graph", "motor_ia_actions", "motor_ia_decisions",
    "motor_ia_events", "motor_ia_outcomes", "motor_ia_alerts",
    "audit_log", "smartolt_onus", "smartolt_olts", "ctos",
    "subscriber_consumption",
]

_ORPHAN_FILTER = {"$or": [
    {"company_id": {"$exists": False}},
    {"company_id": None},
    {"company_id": ""},
]}


async def audit_orphans() -> Dict[str, Any]:
    """Cobertura company_id em coleções de negócio."""
    cols = set(await db.list_collection_names())
    details: List[Dict[str, Any]] = []
    total_docs = total_orph = 0
    for col in BUSINESS_COLLECTIONS:
        if col not in cols:
            continue
        total = await db[col].estimated_document_count()
        if total == 0:
            continue
        orph = await db[col].count_documents(_ORPHAN_FILTER)
        total_docs += total
        total_orph += orph
        details.append({
            "collection": col, "total": total, "orphan": orph,
            "orphan_pct": round(orph / max(total, 1) * 100, 2),
            "status": ("CLEAN" if orph == 0 else
                       "WARNING" if orph / max(total, 1) < 0.05 else
                       "CRITICAL"),
        })
    details.sort(key=lambda x: -x["orphan_pct"])
    return {
        "summary": {
            "collections_scanned": len(details),
            "total_docs": total_docs,
            "total_orphans": total_orph,
            "orphan_pct": round(total_orph / max(total_docs, 1) * 100, 4),
            "status": ("BLINDADO" if total_orph == 0 else
                       "ATENCAO" if total_orph < 50 else "CRITICO"),
        },
        "details": details,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def tenants_distribution() -> Dict[str, Any]:
    """Distribuição de docs por company_id (top 10)."""
    pipe = [
        {"$group": {"_id": "$company_id", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": 20},
    ]
    out = []
    async for r in db.subscribers.aggregate(pipe):
        out.append({"company_id": r["_id"] or "<NULL>", "subscribers": r["n"]})
    return {"items": out, "total_tenants": len(out)}


async def leak_risk_scan(limit: int = 2000) -> Dict[str, Any]:
    """Verifica se há refs cruzadas: ex. ticket de company A referencia
    subscriber de company B."""
    issues: List[Dict[str, Any]] = []
    sample = await db.tickets.find(
        {"client_id": {"$nin": [None, ""]}}, {"id": 1, "company_id": 1,
                                                "client_id": 1}
    ).sort("_id", -1).limit(limit).to_list(limit)
    checked = 0
    for tk in sample:
        sub = await db.subscribers.find_one(
            {"id": tk["client_id"]}, {"company_id": 1})
        if not sub:
            continue
        checked += 1
        if sub.get("company_id") and tk.get("company_id") and \
                sub["company_id"] != tk["company_id"]:
            issues.append({
                "kind": "cross_tenant_ticket",
                "ticket_id": tk.get("id"),
                "ticket_company": tk["company_id"],
                "subscriber_company": sub["company_id"],
            })
    return {
        "checked": checked,
        "cross_tenant_refs": len(issues),
        "issues": issues[:20],
        "status": ("CLEAN" if not issues else "VAZAMENTO"),
    }


async def full_audit() -> Dict[str, Any]:
    o = await audit_orphans()
    t = await tenants_distribution()
    leak = await leak_risk_scan()
    return {
        "headline": (
            f"{o['summary']['total_orphans']} órfão(s) · "
            f"{leak['cross_tenant_refs']} ref(s) cruzada(s) · "
            f"Status: {o['summary']['status']}/{leak['status']}"
        ),
        "orphans": o,
        "tenants": t,
        "leak_risk": leak,
    }
