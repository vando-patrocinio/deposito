"""Endpoints para Configurações > OS > Toggles de validação.

Permite ao admin/gestor ligar e desligar travas de validação no fluxo de
finalização da OS (Lousa). Os toggles ficam em
`aihub_settings.os_validation_toggles` por company.

Toggles disponíveis:
- `ipv6_test_required` (default: False, iter155 — desligado por padrão)
- `cto_photo_required` (default: False, iter166 — exige foto da CTO em instalação)
- `mac_validation_required` (default: False, iter166 — exige MAC casando com SmartOLT)

GET  /api/settings/os-validation-toggles
PUT  /api/settings/os-validation-toggles  { ipv6_test_required?, cto_photo_required?, mac_validation_required? }
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, get_current_user, is_super_admin, now_iso
from database import db

router = APIRouter()


DEFAULTS = {
    # iter155 — Teste IPv6 obrigatório DESLIGADO por padrão (pedido user).
    "ipv6_test_required": False,
    # iter166 — Foto da CTO obrigatória na finalização da OS (instalação/reparo/troca)
    "cto_photo_required": False,
    # iter166 — Validar MAC contra SmartOLT na instalação
    "mac_validation_required": False,
    # iter215z — Porta da CTO obrigatória em OS de instalação E reparo
    # (regra global pedida pelo user 2026-06). Bloqueia finalização se
    # cto_id ou cto_port_number ausentes. Default LIGADO.
    "cto_port_required": True,
    # iter215am — Em OS de retirada/troca, se o SN da ONT NÃO existe no
    # SmartOLT (equipamento não cadastrado), técnico DEVE fotografar o
    # equipamento e a IA (Claude 4.6) analisa a foto antes de finalizar.
    # Sempre registra movimento no estoque do colaborador. Default LIGADO.
    "sn_smartolt_or_photo_required": True,
}


class OsValidationTogglesIn(BaseModel):
    ipv6_test_required: bool | None = None
    cto_photo_required: bool | None = None
    mac_validation_required: bool | None = None
    cto_port_required: bool | None = None
    sn_smartolt_or_photo_required: bool | None = None


def _can_edit(user: Dict[str, Any]) -> bool:
    if is_super_admin(user):
        return True
    return user.get("role") in ("administrador", "gestor", "auditor")


async def _load(cid: str) -> Dict[str, Any]:
    doc = await db.aihub_settings.find_one(
        {"company_id": cid, "key": "os_validation_toggles"},
        {"_id": 0, "value": 1},
    )
    saved = (doc or {}).get("value") or {}
    return {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}


@router.get("/api/settings/os-validation-toggles")
async def get_os_validation_toggles(user: dict = Depends(get_current_user)):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _load(cid)


@router.get("/api/public/os-validation-toggles/{collab_id}")
async def get_os_validation_toggles_public(collab_id: str):
    """Versão pública (lida do app do colaborador sem JWT)."""
    coll = await db.collaborators.find_one(
        {"id": collab_id}, {"_id": 0, "company_id": 1},
    )
    cid = (coll or {}).get("company_id") or DEMO_COMPANY_ID
    return await _load(cid)


@router.put("/api/settings/os-validation-toggles")
async def update_os_validation_toggles(payload: OsValidationTogglesIn,
                                          user: dict = Depends(get_current_user)):
    if not _can_edit(user):
        raise HTTPException(403, "Permissão negada (admin/gestor apenas)")
    cid = user.get("company_id") or DEMO_COMPANY_ID
    current = await _load(cid)
    update = payload.model_dump(exclude_none=True)
    new_value = {**current, **update}
    await db.aihub_settings.update_one(
        {"company_id": cid, "key": "os_validation_toggles"},
        {"$set": {"value": new_value, "updated_at": now_iso(),
                    "updated_by": user.get("email")}},
        upsert=True,
    )
    return new_value
