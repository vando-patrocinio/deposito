"""Endpoints de Reajuste Anual de Planos (subaba do Financeiro).

UI: lista clientes com reajuste devido/próximo, permite aplicar individual ou em lote.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core import require_role
from database import db
from services.inflation import (
    SGS_CODES, get_index, refresh_index_cache,
)
from services.readjustment import (
    apply_all_due, apply_readjustment, calculate_readjustment_preview,
    list_due_subscribers,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/financeiro/reajuste", tags=["reajuste"])


@router.get("/indices")
async def list_indices(user: dict = Depends(require_role("gestor"))):
    """Lista todos os índices oficiais disponíveis com seus valores atuais."""
    out = []
    for name in SGS_CODES.keys():
        doc = await get_index(name, auto_refresh=False)
        out.append({
            "name": name,
            "accumulated_12m": (doc or {}).get("accumulated_12m"),
            "last_period": (doc or {}).get("last_period"),
            "updated_at": (doc or {}).get("updated_at"),
        })
    return {"items": out}


@router.post("/indices/{name}/refresh")
async def refresh_index(name: str,
                        user: dict = Depends(require_role("gestor"))):
    """Força atualização de um índice da API do BCB."""
    name = name.upper()
    if name not in SGS_CODES:
        raise HTTPException(404, f"Índice desconhecido: {name}")
    doc = await refresh_index_cache(name)
    return {
        "ok": True, "name": name,
        "accumulated_12m": doc.get("accumulated_12m"),
        "last_period": doc.get("last_period"),
    }


@router.get("/due")
async def list_due(
    horizon_days: int = Query(30, ge=0, le=365),
    user: dict = Depends(require_role("gestor")),
):
    """Lista clientes com reajuste devido ou que vence em N dias."""
    cid = user.get("company_id") or "co-demo"
    items = await list_due_subscribers(cid, horizon_days=horizon_days)
    # Separa vencidos vs futuros
    due_now = [i for i in items if i.get("is_due")]
    upcoming = [i for i in items if not i.get("is_due")]
    return {
        "total": len(items),
        "due_now": due_now,
        "upcoming": upcoming,
        "horizon_days": horizon_days,
    }


@router.get("/preview/{subscriber_id}")
async def preview_for_subscriber(
    subscriber_id: str,
    index_name: Optional[str] = None,
    user: dict = Depends(require_role("gestor")),
):
    """Mostra projeção de reajuste pra UM cliente (sem aplicar)."""
    cid = user.get("company_id") or "co-demo"
    sub = await db.subscribers.find_one(
        {"id": subscriber_id, "company_id": cid}, {"_id": 0},
    )
    if not sub:
        raise HTTPException(404, "Assinante não encontrado")
    preview = await calculate_readjustment_preview(sub, index_name)
    if not preview:
        raise HTTPException(400, "Sem dados suficientes "
                                  "(installation_date ou plan_price ausentes)")
    return preview


@router.post("/apply/{subscriber_id}")
async def apply_single(
    subscriber_id: str,
    force: bool = False,
    user: dict = Depends(require_role("administrador")),
):
    """Aplica reajuste em UM cliente. `force=true` ignora regra de 12 meses."""
    cid = user.get("company_id") or "co-demo"
    sub = await db.subscribers.find_one(
        {"id": subscriber_id, "company_id": cid}, {"_id": 0},
    )
    if not sub:
        raise HTTPException(404, "Assinante não encontrado")
    result = await apply_readjustment(sub, actor=user.get("email", "admin"),
                                       force=force)
    return result


@router.post("/apply-all-due")
async def apply_all(user: dict = Depends(require_role("administrador"))):
    """Aplica reajuste em TODOS os clientes vencidos (ação de lote)."""
    cid = user.get("company_id") or "co-demo"
    summary = await apply_all_due(cid, actor=user.get("email", "admin-batch"))
    return summary


@router.get("/history/{subscriber_id}")
async def history(
    subscriber_id: str,
    user: dict = Depends(require_role("gestor")),
):
    """Histórico de reajustes de um cliente."""
    cid = user.get("company_id") or "co-demo"
    items = await db.subscriber_readjustments.find(
        {"subscriber_id": subscriber_id, "company_id": cid},
        {"_id": 0},
    ).sort("applied_at", -1).to_list(50)
    return {"items": items}
