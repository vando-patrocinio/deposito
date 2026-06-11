"""Lousa TV — link público somente-leitura para exibir o Kanban em SmartTVs.

Fluxo:
- Admin chama `GET /api/lousa/tv-link` (autenticado, role=gestor) para obter
  o token público da empresa. Token é gerado on-demand e persistido em
  `db.company_settings` (campo `lousa_tv_token`).
- A SmartTV abre `?portal=lousa-tv&t=<token>` e o frontend usa
  `GET /api/lousa/public/tv-grid/{token}` para buscar a grade. Sem JWT.

Notas de segurança:
- Token é UUID4 (122 bits) → impossível adivinhar. URL pública mas
  difícil de descobrir.
- Endpoint só RETORNA dados, nunca aceita escrita.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "operacoes",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from core import DEMO_COMPANY_ID, require_role
from database import db
from routes.lousa import lousa_grid

logger = logging.getLogger("ponto")
router = APIRouter(prefix="/api", tags=["lousa-tv"])


async def _get_or_create_tv_token(company_id: str) -> str:
    cfg = await db.company_settings.find_one(
        {"company_id": company_id}, {"_id": 0, "lousa_tv_token": 1},
    )
    token = (cfg or {}).get("lousa_tv_token")
    if not token:
        token = uuid.uuid4().hex
        await db.company_settings.update_one(
            {"company_id": company_id},
            {"$set": {"lousa_tv_token": token},
             "$setOnInsert": {"company_id": company_id}},
            upsert=True,
        )
    return token


@router.get("/lousa/tv-link")
async def lousa_tv_link(user: dict = Depends(require_role("gestor"))):
    """Devolve o token público da TV da empresa (cria se não existir)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    token = await _get_or_create_tv_token(cid)
    return {"token": token, "company_id": cid}


@router.post("/lousa/tv-link/rotate")
async def lousa_tv_link_rotate(user: dict = Depends(require_role("gestor"))):
    """Gera um novo token (revoga o anterior)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    token = uuid.uuid4().hex
    await db.company_settings.update_one(
        {"company_id": cid},
        {"$set": {"lousa_tv_token": token},
         "$setOnInsert": {"company_id": cid}},
        upsert=True,
    )
    return {"token": token, "company_id": cid}


@router.get("/lousa/public/tv-grid/{tv_token}")
async def lousa_public_tv_grid(tv_token: str,
                                date_from: Optional[str] = None,
                                date_to: Optional[str] = None):
    """Retorna a grade da Lousa em modo somente-leitura via token público."""
    if not tv_token or len(tv_token) < 16:
        raise HTTPException(404, "Token inválido")
    cfg = await db.company_settings.find_one(
        {"lousa_tv_token": tv_token}, {"_id": 0, "company_id": 1},
    )
    if not cfg:
        raise HTTPException(404, "Token não encontrado ou revogado")
    cid = cfg.get("company_id") or DEMO_COMPANY_ID
    # Constrói um "user dict" mínimo pra reaproveitar lousa_grid sem
    # duplicar a lógica de montagem. role=gestor + company_id é suficiente.
    fake_user = {"company_id": cid, "role": "gestor", "id": "lousa-tv-public"}
    return await lousa_grid(user=fake_user, date_from=date_from, date_to=date_to)


@router.get("/lousa/public/tv-logs/{tv_token}")
async def lousa_public_tv_logs(tv_token: str, limit: int = 60):
    """iter215ai — Logs públicos da empresa via TV token. Usado pelo
    painel lateral 'Histórico de Ações' do LousaTvPanel."""
    if not tv_token or len(tv_token) < 16:
        raise HTTPException(404, "Token inválido")
    cfg = await db.company_settings.find_one(
        {"lousa_tv_token": tv_token}, {"_id": 0, "company_id": 1},
    )
    if not cfg:
        raise HTTPException(404, "Token não encontrado")
    cid = cfg.get("company_id") or DEMO_COMPANY_ID
    items = await db.ticket_logs.find(
        {"company_id": cid}, {"_id": 0}
    ).sort("at", -1).to_list(min(limit, 200))
    return {"items": items}
