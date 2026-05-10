"""Planos comerciais do provedor (ISP) — CRUD usado em Clientes.

Cada plano tem velocidade, valor mensal e percentual de acréscimo anual de
inflação (reajuste contratual). É referenciado por `plan_id` no subscriber.

Coleção: `plans` — {id, company_id, name, speed_label, speed_down_mbps,
                     speed_up_mbps, monthly_price, annual_adjustment_pct,
                     description, active, created_at, updated_at}.
"""
from __future__ import annotations

import logging
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.plans")
router = APIRouter(prefix="/api/plans", tags=["plans"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class PlanIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    speed_label: Optional[str] = Field(default=None, max_length=40)
    speed_down_mbps: Optional[int] = Field(default=None, ge=1, le=100000)
    speed_up_mbps: Optional[int] = Field(default=None, ge=1, le=100000)
    monthly_price: float = Field(..., ge=0)
    annual_adjustment_pct: float = Field(default=0, ge=0, le=100)
    description: Optional[str] = Field(default=None, max_length=600)
    active: bool = True


class PlanUpdate(BaseModel):
    name: Optional[str] = None
    speed_label: Optional[str] = None
    speed_down_mbps: Optional[int] = None
    speed_up_mbps: Optional[int] = None
    monthly_price: Optional[float] = None
    annual_adjustment_pct: Optional[float] = None
    description: Optional[str] = None
    active: Optional[bool] = None


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


def _derive_speed_label(payload_dict: dict) -> Optional[str]:
    """Se o usuário não informou label, deriva de speed_down_mbps."""
    label = payload_dict.get("speed_label")
    if label:
        return label
    mb = payload_dict.get("speed_down_mbps")
    if mb:
        if mb >= 1000 and mb % 1000 == 0:
            return f"{mb // 1000} Giga"
        return f"{mb} Mega"
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("")
async def list_plans(
    active: Optional[bool] = None,
    user: dict = Depends(require_role("gestor")),
):
    cid = _cid(user)
    flt: Dict = {"company_id": cid}
    if active is not None:
        flt["active"] = active
    rows = await db.plans.find(flt, {"_id": 0}).sort("monthly_price", 1).to_list(500)
    return {"items": rows, "count": len(rows)}


@router.post("")
async def create_plan(payload: PlanIn,
                       user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    # Não permite nome duplicado por empresa
    existing = await db.plans.find_one(
        {"company_id": cid, "name": payload.name})
    if existing:
        raise HTTPException(409, f"Já existe plano com nome '{payload.name}'.")
    doc = payload.model_dump()
    doc["speed_label"] = _derive_speed_label(doc)
    doc.update({
        "id": f"plan-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": user.get("email") or user.get("id"),
    })
    await db.plans.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.get("/{plan_id}")
async def get_plan(plan_id: str,
                    user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    p = await db.plans.find_one(
        {"company_id": cid, "id": plan_id}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Plano não encontrado.")
    return p


@router.put("/{plan_id}")
async def update_plan(plan_id: str, payload: PlanUpdate,
                       user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    p = await db.plans.find_one(
        {"company_id": cid, "id": plan_id}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Plano não encontrado.")
    update_fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "name" in update_fields and update_fields["name"] != p.get("name"):
        existing = await db.plans.find_one(
            {"company_id": cid, "name": update_fields["name"],
             "id": {"$ne": plan_id}})
        if existing:
            raise HTTPException(409, "Já existe outro plano com esse nome.")
    if "speed_down_mbps" in update_fields and not update_fields.get("speed_label"):
        update_fields["speed_label"] = _derive_speed_label(update_fields)
    update_fields["updated_at"] = now_iso()
    update_fields["updated_by"] = user.get("email") or user.get("id")
    await db.plans.update_one(
        {"company_id": cid, "id": plan_id}, {"$set": update_fields})
    p2 = await db.plans.find_one(
        {"company_id": cid, "id": plan_id}, {"_id": 0})
    return p2


@router.delete("/{plan_id}")
async def delete_plan(plan_id: str,
                       user: dict = Depends(require_role("administrador"))):
    cid = _cid(user)
    # Bloqueia exclusão se há assinantes usando o plano
    using = await db.subscribers.count_documents(
        {"company_id": cid, "plan_id": plan_id})
    if using > 0:
        raise HTTPException(409,
                            f"{using} assinante(s) usam esse plano. "
                            "Inative o plano ou migre-os antes de excluir.")
    result = await db.plans.delete_one(
        {"company_id": cid, "id": plan_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Plano não encontrado.")
    return {"ok": True, "deleted_id": plan_id}


# ---------------------------------------------------------------------------
# Helper: hidrata plano dentro de subscriber (usado por subscribers.py)
# ---------------------------------------------------------------------------
async def get_plan_dict(company_id: str, plan_id: Optional[str]) -> Optional[dict]:
    if not plan_id:
        return None
    return await db.plans.find_one(
        {"company_id": company_id, "id": plan_id}, {"_id": 0})
