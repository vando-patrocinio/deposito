"""ai_center_multitenant.py — FASE 8 endpoints."""
from __future__ import annotations
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
