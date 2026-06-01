"""Endpoints para Configurações > Mensagens > Template de Retirada.

GET  /api/settings/retirada-template
PUT  /api/settings/retirada-template  { template: str }
POST /api/settings/retirada-template/reset  (volta ao padrão)
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, get_current_user, is_super_admin
from services.retirada_workflow import (
    DEFAULT_TEMPLATE,
    get_template,
    set_template,
)

router = APIRouter()


class TemplateIn(BaseModel):
    template: str = Field(min_length=10, max_length=4000)


def _can_edit(user: Dict[str, Any]) -> bool:
    if is_super_admin(user):
        return True
    return user.get("role") in ("administrador", "gestor")


@router.get("/api/settings/retirada-template")
async def get_retirada_template(user: dict = Depends(get_current_user)):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    tpl = await get_template(cid)
    return {
        "template": tpl,
        "default_template": DEFAULT_TEMPLATE,
        "is_default": tpl == DEFAULT_TEMPLATE,
        "variables": [
            "{cliente}", "{endereco}", "{equipamento}",
            "{sn}", "{data}", "{tecnico}", "{empresa}",
        ],
    }


@router.put("/api/settings/retirada-template")
async def update_retirada_template(payload: TemplateIn,
                                       user: dict = Depends(get_current_user)):
    if not _can_edit(user):
        raise HTTPException(403, "Permissão negada (admin/gestor apenas)")
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # Verifica que pelo menos UMA variável foi usada — evita templates vazios
    has_var = any(v in payload.template for v in (
        "{cliente}", "{endereco}", "{equipamento}",
        "{sn}", "{data}", "{tecnico}", "{empresa}",
    ))
    if not has_var:
        raise HTTPException(
            400, "Template precisa usar pelo menos uma variável (ex: {cliente})",
        )
    await set_template(cid, payload.template)
    return {"ok": True, "template": payload.template}


@router.post("/api/settings/retirada-template/reset")
async def reset_retirada_template(user: dict = Depends(get_current_user)):
    if not _can_edit(user):
        raise HTTPException(403, "Permissão negada (admin/gestor apenas)")
    cid = user.get("company_id") or DEMO_COMPANY_ID
    await set_template(cid, DEFAULT_TEMPLATE)
    return {"ok": True, "template": DEFAULT_TEMPLATE}
