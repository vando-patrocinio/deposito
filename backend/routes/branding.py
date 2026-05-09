"""Branding da empresa — logo + dados que entram no cabeçalho do romaneio.

Uma config por `company_id`. Logo é armazenada como base64 (data URL). Endpoint
público serve a logo descriptografada para uso em PDFs.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.branding")
router = APIRouter(prefix="/api/branding", tags=["branding"])


class CompanyBranding(BaseModel):
    company_id: str = DEMO_COMPANY_ID
    company_name: str = ""
    cnpj: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    logo_data_url: Optional[str] = None  # "data:image/png;base64,...."
    default_asset_values_brl: dict = Field(default_factory=lambda: {
        "uniforme": 80.0, "epi": 150.0, "ferramenta": 200.0,
        "veiculo": 10000.0, "eletronico": 500.0, "outro": 100.0,
    })
    romaneio_footer: Optional[str] = Field(
        default=("Declaro ter recebido os itens listados acima em perfeito estado e me "
                 "responsabilizo por sua guarda, conservação e devolução em caso de "
                 "desligamento, sob pena das medidas cabíveis.")
    )
    updated_at: Optional[str] = None


class CompanyBrandingUpdate(BaseModel):
    company_name: Optional[str] = None
    cnpj: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    logo_data_url: Optional[str] = None
    default_asset_values_brl: Optional[dict] = None
    romaneio_footer: Optional[str] = None


async def get_branding(company_id: str) -> CompanyBranding:
    raw = await db.company_branding.find_one({"company_id": company_id}, {"_id": 0})
    if not raw:
        cfg = CompanyBranding(company_id=company_id)
        await db.company_branding.insert_one(cfg.model_dump())
        return cfg
    try:
        return CompanyBranding(**raw)
    except Exception as e:
        logger.warning("[branding] config corrompida, recriando: %s", e)
        cfg = CompanyBranding(company_id=company_id)
        await db.company_branding.update_one(
            {"company_id": company_id}, {"$set": cfg.model_dump()}, upsert=True)
        return cfg


@router.get("/settings")
async def get_settings(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return (await get_branding(cid)).model_dump()


@router.put("/settings")
async def put_settings(payload: CompanyBrandingUpdate,
                       user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cur = await get_branding(cid)
    update = payload.model_dump(exclude_unset=True)
    if "logo_data_url" in update and update["logo_data_url"] is not None:
        if update["logo_data_url"] and not update["logo_data_url"].startswith("data:image/"):
            raise HTTPException(400, "logo_data_url deve ser data URL (data:image/...).")
        # Tamanho máximo: ~2 MB de base64 (~1.5 MB de imagem real).
        if update["logo_data_url"] and len(update["logo_data_url"]) > 2_500_000:
            raise HTTPException(400, "Logo muito grande (max ~1.5 MB).")
    new = CompanyBranding(**{**cur.model_dump(), **update, "updated_at": now_iso()})
    await db.company_branding.update_one(
        {"company_id": cid}, {"$set": new.model_dump()}, upsert=True)
    return new.model_dump()


@router.get("/public")
async def public_branding():
    """Endpoint público — usado pelo app do colaborador (mobile sem auth) para
    montar o cabeçalho do romaneio assinado pelo colaborador.
    Retorna apenas dados não sensíveis."""
    cfg = await get_branding(DEMO_COMPANY_ID)
    d = cfg.model_dump()
    return {
        "company_name": d.get("company_name"),
        "address": d.get("address"),
        "city": d.get("city"),
        "state": d.get("state"),
        "phone": d.get("phone"),
        "logo_data_url": d.get("logo_data_url"),
        "romaneio_footer": d.get("romaneio_footer"),
    }
