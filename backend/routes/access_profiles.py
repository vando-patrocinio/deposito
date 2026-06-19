"""Endpoints REST de Perfis de Acesso (CTO 12/06/2026).

  GET    /api/access-profiles          → lista perfis do tenant
  POST   /api/access-profiles          → cria perfil
  GET    /api/access-profiles/{id}     → detalhe
  PUT    /api/access-profiles/{id}     → atualiza
  DELETE /api/access-profiles/{id}     → exclui (não-seed só)
  POST   /api/access-profiles/seed     → força criar os 4 padrão
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, is_super_admin, require_role
from services.exception_sanitizer import safe_detail  # SECURITY_LOCK ART.13
from services.access_profiles import (
    create_profile,
    delete_profile,
    get_profile,
    list_profiles,
    seed_default_profiles,
    update_profile,
    user_has_super_admin_profile,
)

router = APIRouter(prefix="/api/access-profiles", tags=["access-profiles"])


class ProfileIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=60)
    description: Optional[str] = None
    access_tags: List[str] = Field(default_factory=list)


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    access_tags: Optional[List[str]] = None


@router.get("")
async def list_(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    profiles = await list_profiles(cid)
    # CTO 12/06/2026 — Só Super Admin enxerga o perfil Super Admin.
    requester_is_super = is_super_admin(user) or await user_has_super_admin_profile(user)
    if not requester_is_super:
        profiles = [p for p in profiles if not p.get("is_super_admin_profile") and p.get("key") != "super_admin"]
    return profiles


@router.post("")
async def create_(payload: ProfileIn,
                    user: dict = Depends(require_role("auditor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    try:
        return await create_profile(
            cid, payload.name, payload.access_tags,
            description=payload.description,
            created_by=user.get("email") or "?",
        )
    except ValueError as e:
        raise HTTPException(400, safe_detail(400, e))


@router.get("/{profile_id}")
async def detail_(profile_id: str,
                    user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    p = await get_profile(profile_id, cid)
    if not p:
        raise HTTPException(404, "Perfil não encontrado")
    # CTO — Super Admin só visível para Super Admin (mesmo no detail).
    if p.get("is_super_admin_profile") or p.get("key") == "super_admin":
        requester_is_super = is_super_admin(user) or await user_has_super_admin_profile(user)
        if not requester_is_super:
            raise HTTPException(404, "Perfil não encontrado")
    return p


@router.put("/{profile_id}")
async def update_(profile_id: str, payload: ProfileUpdate,
                    user: dict = Depends(require_role("auditor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    try:
        return await update_profile(
            profile_id, cid,
            name=payload.name,
            description=payload.description,
            access_tags=payload.access_tags,
            updated_by=user.get("email") or "?",
        )
    except ValueError as e:
        raise HTTPException(400, safe_detail(400, e))


@router.delete("/{profile_id}")
async def delete_(profile_id: str,
                    user: dict = Depends(require_role("auditor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    try:
        return await delete_profile(profile_id, cid)
    except ValueError as e:
        raise HTTPException(400, safe_detail(400, e))


@router.post("/seed")
async def seed_(user: dict = Depends(require_role("auditor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await seed_default_profiles(cid)
