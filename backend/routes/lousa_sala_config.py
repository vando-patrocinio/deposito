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

from fastapi import APIRouter, Body, Depends

from core import DEMO_COMPANY_ID, require_role
from database import db


router = APIRouter(prefix="/api/lousa", tags=["lousa-sala-config"])


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


@router.get("/sala-config")
async def get_config(user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    doc = await db.settings.find_one({"id": cid},
                                            {"_id": 0,
                                             "isabella_auto_distribute": 1})
    return {"company_id": cid,
              "auto_distribute": bool((doc or {})
                                          .get("isabella_auto_distribute"))}


@router.post("/sala-config")
async def set_config(body: dict = Body(...),
                       user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    val = bool(body.get("auto_distribute"))
    await db.settings.update_one(
        {"id": cid},
        {"$set": {
            "isabella_auto_distribute": val,
            "isabella_auto_distribute_changed_at":
                datetime.now(timezone.utc).isoformat(),
            "isabella_auto_distribute_changed_by":
                user.get("email") or user.get("id"),
        }},
        upsert=True,
    )
    return {"ok": True, "auto_distribute": val}
