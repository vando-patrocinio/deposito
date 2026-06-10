"""Endpoints PRESIDENTE FINANCEIRO + IDENTIDADE 360°."""
from __future__ import annotations
from fastapi import APIRouter, Depends
from typing import Optional

from core import require_role
from services import presidente_financeiro as pf
from services import identity_360 as id360

router = APIRouter(prefix="/api/colosso/financeiro", tags=["colosso-financeiro"])


@router.post("/run-attribution")
async def run_attribution(window_days: int = 30,
                            user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id")
    return await pf.run_attribution_cycle(cid, window_days=window_days)


id_router = APIRouter(prefix="/api/identity-360", tags=["identity-360"])


@id_router.get("/{phone}")
async def get_identity(phone: str,
                          user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id")
    res = await id360.identity_360(cid, phone)
    res["isabella_block"] = id360.format_for_isabella(res)
    return res
