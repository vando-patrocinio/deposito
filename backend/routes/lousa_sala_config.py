"""Rotas de configuração da SALA + auto-distribuição da Isabella.

GET  /api/lousa/sala-config       Retorna estado do toggle.
POST /api/lousa/sala-config       Liga/desliga auto-distribuição.

Quando OFF (default): toda visita criada pela Isabella vai pra SALA.
Quando ON:           Isabella distribui direto para o técnico menos
                     sobrecarregado, sem passar pela SALA.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "lousa",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends

from core import DEMO_COMPANY_ID, get_current_user, require_role
from database import db


router = APIRouter(prefix="/api/lousa", tags=["lousa-sala-config"])


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


@router.get("/sala-config")
async def get_config(user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    doc = await db.settings.find_one({"id": cid},
                                            {"_id": 0,
                                             "isabella_auto_distribute": 1,
                                             "collab_smart_field_enabled": 1})
    return {"company_id": cid,
              "auto_distribute": bool((doc or {})
                                          .get("isabella_auto_distribute")),
              "collab_smart_field_enabled": bool((doc or {})
                  .get("collab_smart_field_enabled"))}


@router.post("/sala-config")
async def set_config(body: dict = Body(...),
                       user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    updates: Dict[str, Any] = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": user.get("email") or user.get("id"),
    }
    if "auto_distribute" in body:
        updates["isabella_auto_distribute"] = bool(body["auto_distribute"])
    if "collab_smart_field_enabled" in body:
        updates["collab_smart_field_enabled"] = bool(
            body["collab_smart_field_enabled"])
    await db.settings.update_one(
        {"id": cid}, {"$set": updates}, upsert=True)
    return {"ok": True, **{k: v for k, v in updates.items()
                              if k not in ("updated_at", "updated_by")}}


@router.get("/collab-app-config")
async def get_collab_app_config(user: dict = Depends(get_current_user)):
    """Endpoint PÚBLICO (qualquer user autenticado) para o app do
    colaborador consultar quais features estão habilitadas pela empresa.
    """
    cid = _cid(user)
    doc = await db.settings.find_one(
        {"id": cid}, {"_id": 0, "collab_smart_field_enabled": 1})
    return {"smart_field_enabled": bool(
        (doc or {}).get("collab_smart_field_enabled"))}
