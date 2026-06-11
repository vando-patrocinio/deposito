"""ai_center_multitenant.py — FASE 8 endpoints."""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from fastapi import APIRouter, Depends, HTTPException

from rbac import require_roles
from services import multitenant_audit as mt

router = APIRouter(prefix="/api/ai-center/multitenant",
                    tags=["ai-center-multitenant"])


@router.get("/audit")
async def get_full_audit(user=Depends(
    require_roles("administrador", "auditor"))):
    return await mt.full_audit()


@router.get("/orphans")
async def get_orphans(user=Depends(
    require_roles("administrador", "auditor"))):
    return await mt.audit_orphans()


@router.get("/tenants")
async def get_tenants(user=Depends(
    require_roles("administrador", "auditor"))):
    return await mt.tenants_distribution()


@router.get("/leak-risk")
async def get_leak(user=Depends(
    require_roles("administrador", "auditor"))):
    return await mt.leak_risk_scan()


@router.get("/companies")
async def list_companies(user=Depends(
    require_roles("administrador", "auditor"))):
    """Fase D — Lista TODOS os tenants reais cadastrados em `companies`,
    independente de terem subscribers. Útil para ver tenants recém-criados
    (ex: co-pilot-1) que ainda estão em onboarding."""
    from database import db
    from datetime import datetime, timezone

    cursor = db.companies.find({}, {"_id": 0})
    items = await cursor.to_list(200)
    enriched = []
    for c in items:
        cid = c.get("id") or c.get("company_id")
        if not cid:
            continue
        subs_count = await db.subscribers.count_documents(
            {"company_id": cid})
        invoices_count = await db.subscriber_invoices.count_documents(
            {"company_id": cid})
        enriched.append({
            "id": cid,
            "name": c.get("name") or c.get("display_name") or cid,
            "subscribers_count": subs_count,
            "invoices_count": invoices_count,
            "is_seed": cid == "co-demo",
            "status": ("ACTIVE" if subs_count > 0 else "ONBOARDING"),
        })
    return {
        "items": sorted(enriched,
                          key=lambda x: x["subscribers_count"],
                          reverse=True),
        "total": len(enriched),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
