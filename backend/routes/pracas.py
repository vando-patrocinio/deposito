"""Endpoints de Praças (locais de trabalho). Feriados são gerenciados de
forma centralizada em /api/feriados — não há mais feriados por praça."""

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import decode_token
from core import (
    DEMO_COMPANY_ID,
    is_super_admin,
    now_iso,
    require_role,
    tenant_filter,
)
from database import db

logger = logging.getLogger("ponto")
router = APIRouter(prefix="/api", tags=["pracas"])


async def get_current_user_optional(request: Request) -> Optional[dict]:
    """Retorna user autenticado SE o token estiver presente; senão None.
    Usado em endpoints que aceitam chamada pública (PWA mobile)."""
    auth = (request.headers.get("Authorization") or "")
    if not auth.startswith("Bearer "):
        return None
    try:
        payload = decode_token(auth[7:])
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
        if not user:
            return None
        user["company_id"] = payload.get("company_id") or user.get("company_id") or DEMO_COMPANY_ID
        return user
    except Exception:
        return None


class PracaIn(BaseModel):
    name: str
    city: str
    state: str
    full_address: Optional[str] = None
    street: Optional[str] = None
    number: Optional[str] = None
    neighborhood: Optional[str] = None
    postal_code: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    # Identificação fiscal & branding (aparece no cabeçalho do espelho/romaneio)
    logo_url: Optional[str] = None
    cnpj: Optional[str] = None
    inscricao_estadual: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    site: Optional[str] = None
    # Filiais Atlaz que operam nesta praça (multi). Quando chamado Atlaz vem de
    # uma dessas filiais, ele é roteado para os técnicos desta praça.
    branch_codes: list = []


@router.get("/pracas")
async def list_pracas(user: dict = Depends(get_current_user_optional)):
    """Lista praças do tenant. Endpoint pode ser chamado sem auth (uso público em
    PWA mobile para popular dropdown). Sem auth → todas (legacy)."""
    q = tenant_filter(user) if user else {}
    return await db.pracas.find(q, {"_id": 0}).sort("name", 1).to_list(500)


@router.post("/pracas")
async def create_praca(payload: PracaIn, user: dict = Depends(require_role("gestor"))):
    pid = f"prc-{uuid.uuid4().hex[:10]}"
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = {
        "id": pid,
        "company_id": cid,
        "name": payload.name.strip(),
        "city": payload.city.strip(),
        "state": payload.state.strip().upper()[:2],
        "full_address": (payload.full_address or "").strip() or None,
        "street": payload.street, "number": payload.number,
        "neighborhood": payload.neighborhood, "postal_code": payload.postal_code,
        "lat": payload.lat, "lng": payload.lng,
        "logo_url": (payload.logo_url or "").strip() or None,
        "cnpj": (payload.cnpj or "").strip() or None,
        "inscricao_estadual": (payload.inscricao_estadual or "").strip() or None,
        "phone": (payload.phone or "").strip() or None,
        "email": (payload.email or "").strip() or None,
        "site": (payload.site or "").strip() or None,
        "branch_codes": [b.strip() for b in (payload.branch_codes or []) if b and b.strip()],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.pracas.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/pracas/{pid}")
async def update_praca(pid: str, payload: PracaIn, user: dict = Depends(require_role("gestor"))):
    if not is_super_admin(user):
        existing = await db.pracas.find_one({"id": pid}, {"company_id": 1})
        if not existing or existing.get("company_id") != user.get("company_id"):
            raise HTTPException(404, "Praça não encontrada")
    update = {
        "name": payload.name.strip(),
        "city": payload.city.strip(),
        "state": payload.state.strip().upper()[:2],
        "full_address": (payload.full_address or "").strip() or None,
        "street": payload.street, "number": payload.number,
        "neighborhood": payload.neighborhood, "postal_code": payload.postal_code,
        "lat": payload.lat, "lng": payload.lng,
        "logo_url": (payload.logo_url or "").strip() or None,
        "cnpj": (payload.cnpj or "").strip() or None,
        "inscricao_estadual": (payload.inscricao_estadual or "").strip() or None,
        "phone": (payload.phone or "").strip() or None,
        "email": (payload.email or "").strip() or None,
        "site": (payload.site or "").strip() or None,
        "branch_codes": [b.strip() for b in (payload.branch_codes or []) if b and b.strip()],
        "updated_at": now_iso(),
    }
    res = await db.pracas.update_one({"id": pid}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(404, "Praça não encontrada")
    return await db.pracas.find_one({"id": pid}, {"_id": 0})


@router.delete("/pracas/{pid}")
async def delete_praca(pid: str, user: dict = Depends(require_role("gestor"))):
    if not is_super_admin(user):
        existing = await db.pracas.find_one({"id": pid}, {"company_id": 1})
        if not existing or existing.get("company_id") != user.get("company_id"):
            raise HTTPException(404, "Praça não encontrada")
    used = await db.collaborators.count_documents({"praca_id": pid})
    if used > 0:
        raise HTTPException(400, f"Praça em uso por {used} colaborador(es). Reatribua antes de excluir.")
    res = await db.pracas.delete_one({"id": pid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Praça não encontrada")
    return {"ok": True}

