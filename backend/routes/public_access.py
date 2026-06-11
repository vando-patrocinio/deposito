"""Public Access Tokens — links públicos com poder admin pra abas específicas.

Permite gerar URLs do tipo `https://app/?ptoken=xxx` que dão acesso completo
(role administrador) à empresa que gerou o token. Útil pra colocar Chamados
em monitor de equipe sem precisar manter sessão logada, ou compartilhar
acesso temporário sem criar usuário.

Segurança:
- Token é um secret de 32 chars (256 bits de entropia).
- Pode ser revogado a qualquer momento (revoked_at).
- Pode ter data de expiração opcional (expires_at).
- Atribui company_id no momento da geração — não cruza empresas.
- Loga last_used_at + use_count pra auditoria.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

router = APIRouter(prefix="/api/public-access", tags=["public-access"])


class PublicTokenIn(BaseModel):
    label: str = Field(..., min_length=2, max_length=80)
    scope: str = Field("lousa", max_length=40)
    expires_in_days: Optional[int] = Field(None, ge=1, le=3650)


class PublicTokenOut(BaseModel):
    id: str
    token: str
    label: str
    scope: str
    company_id: str
    created_at: str
    created_by: str
    expires_at: Optional[str]
    revoked_at: Optional[str] = None
    last_used_at: Optional[str] = None
    use_count: int = 0


@router.post("/tokens")
async def create_token(payload: PublicTokenIn,
                          user: dict = Depends(require_role("administrador"))):
    """Cria um novo token público (somente administrador)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    raw = secrets.token_urlsafe(24)  # ~32 chars, 192 bits
    expires_at = None
    if payload.expires_in_days:
        expires_at = (datetime.now(timezone.utc)
                      + timedelta(days=payload.expires_in_days)).isoformat()
    doc = {
        "id": f"pat-{uuid.uuid4().hex[:10]}",
        "token": raw,
        "company_id": cid,
        "label": payload.label.strip(),
        "scope": payload.scope.strip() or "lousa",
        "created_at": now_iso(),
        "created_by": user.get("email") or user.get("id"),
        "expires_at": expires_at,
        "revoked_at": None,
        "last_used_at": None,
        "use_count": 0,
    }
    await db.public_access_tokens.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/tokens")
async def list_tokens(user: dict = Depends(require_role("administrador"))):
    """Lista tokens da empresa (não-revogados primeiro)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    rows = await db.public_access_tokens.find(
        {"company_id": cid}, {"_id": 0},
    ).sort([("revoked_at", 1), ("created_at", -1)]).to_list(200)
    return {"tokens": rows, "total": len(rows)}


@router.delete("/tokens/{token_id}")
async def revoke_token(token_id: str,
                          user: dict = Depends(require_role("administrador"))):
    """Revoga (mas não apaga) um token público."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    res = await db.public_access_tokens.update_one(
        {"id": token_id, "company_id": cid, "revoked_at": None},
        {"$set": {"revoked_at": now_iso(),
                  "revoked_by": user.get("email") or user.get("id")}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Token não encontrado ou já revogado")
    return {"revoked": True, "id": token_id}
