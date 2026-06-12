"""WhatsApp Test Mode — controle UI do HOMOLOG_MODE.

Permite ao admin/gestor ligar e desligar o "modo teste" do WhatsApp via
painel de Configurações (sem precisar restart com env var).

Quando LIGADO: todas as mensagens outbound são REDIRECIONADAS para o
`test_phone` definido aqui. Clientes reais NÃO recebem nada.

Setting fica em `aihub_settings` com `key="wa_test_mode"` por company:
    { enabled: bool, test_phone: str, updated_at, updated_by }

Default failsafe: `enabled=True`, `test_phone="5521998176526"` (alinhado
com TEST_PHONE legado em `services/homologation.py`).

GET  /api/settings/wa-test-mode
PUT  /api/settings/wa-test-mode   { enabled?, test_phone? }
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, get_current_user, is_super_admin, now_iso
from database import db

router = APIRouter()

# Default failsafe: alinhado com TEST_PHONE legado em homologation.py
DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "test_phone": "5521998176526",
}


def _can_edit(user: Dict[str, Any]) -> bool:
    if is_super_admin(user):
        return True
    return user.get("role") in ("administrador", "gestor", "auditor")


def _norm_phone(raw: str) -> str:
    """Normaliza phone — só dígitos, prefixo país 55."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if digits.startswith("0"):
        digits = digits.lstrip("0")
    if len(digits) <= 11 and not digits.startswith("55"):
        digits = "55" + digits
    return digits


class WaTestModeIn(BaseModel):
    enabled: Optional[bool] = None
    test_phone: Optional[str] = Field(default=None, max_length=20)


async def load_settings(cid: str) -> Dict[str, Any]:
    """Lê settings com merge sobre defaults. Usado tanto pela rota quanto
    pelo `services/homologation.py` (via cache)."""
    doc = await db.aihub_settings.find_one(
        {"company_id": cid, "key": "wa_test_mode"},
        {"_id": 0, "value": 1},
    )
    saved = (doc or {}).get("value") or {}
    merged = {
        "enabled": bool(saved["enabled"]) if "enabled" in saved
                    else DEFAULTS["enabled"],
        "test_phone": _norm_phone(saved.get("test_phone")
                                    or DEFAULTS["test_phone"]),
    }
    return merged


@router.get("/api/settings/wa-test-mode")
async def get_wa_test_mode(user: dict = Depends(get_current_user)):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    s = await load_settings(cid)
    return {
        **s,
        "test_phone_display": _format_display(s["test_phone"]),
        "defaults": DEFAULTS,
    }


@router.put("/api/settings/wa-test-mode")
async def update_wa_test_mode(payload: WaTestModeIn,
                                user: dict = Depends(get_current_user)):
    if not _can_edit(user):
        raise HTTPException(403, "Permissão negada (admin/gestor apenas)")
    cid = user.get("company_id") or DEMO_COMPANY_ID
    current = await load_settings(cid)
    update = payload.model_dump(exclude_none=True)
    if "test_phone" in update:
        norm = _norm_phone(update["test_phone"])
        if len(norm) < 12 or len(norm) > 13:
            raise HTTPException(
                400, "Telefone inválido — formato esperado: 55DDD9XXXXXXXX")
        update["test_phone"] = norm
    new_value = {**current, **update}
    await db.aihub_settings.update_one(
        {"company_id": cid, "key": "wa_test_mode"},
        {"$set": {
            "value": new_value, "updated_at": now_iso(),
            "updated_by": user.get("email"),
        }},
        upsert=True,
    )
    # Invalida cache do homologation.py
    try:
        from services import homologation as _homo
        _homo._invalidate_settings_cache(cid)
    except Exception:
        pass
    return {
        **new_value,
        "test_phone_display": _format_display(new_value["test_phone"]),
    }


def _format_display(phone: str) -> str:
    """Formata 5521998176526 → (21) 99817-6526."""
    p = _norm_phone(phone)
    if len(p) == 13 and p.startswith("55"):
        return f"({p[2:4]}) {p[4:9]}-{p[9:]}"
    if len(p) == 12 and p.startswith("55"):
        return f"({p[2:4]}) {p[4:8]}-{p[8:]}"
    return p
