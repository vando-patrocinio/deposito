"""Endpoints PJ — config do consultor + listagem de leads.

Acesso: somente admin/owner (consistente com isabella_commanders).
"""

NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from core import get_current_user
from database import db
from services.rate_limit import get_limit, limiter
from services.pj_lead_router import (
    get_pj_config,
    upsert_pj_config,
)

router = APIRouter(prefix="/api/isabella/pj", tags=["isabella_pj"])


def _require_priv(user: Dict[str, Any]) -> None:
    role = (user or {}).get("role") or ""
    if (user or {}).get("is_super_admin"):
        return
    if role not in ("owner", "admin", "operator", "auditor"):
        raise HTTPException(403, "acesso restrito (admin/owner)")


def _company_or_param(user: Dict[str, Any], cid: Optional[str]) -> str:
    if cid:
        return cid
    out = (user or {}).get("company_id")
    if not out:
        raise HTTPException(400, "company_id ausente")
    return out


@router.get("/config")
@limiter.limit(get_limit("isabella_read"))
async def get_config(
    request: Request, cid: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_priv(user)
    company = _company_or_param(user, cid)
    return await get_pj_config(company_id=company)


@router.put("/config")
@limiter.limit(get_limit("isabella_write"))
async def put_config(
    request: Request,
    payload: dict = Body(...),
    cid: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    _require_priv(user)
    company = _company_or_param(user, cid)
    # Validação básica
    updates = {
        "ativo": bool(payload.get("ativo", True)),
        "consultor_nome": str(payload.get("consultor_nome", ""))[:120],
        "consultor_telefone": str(payload.get("consultor_telefone", ""))[:30],
        "consultor_whatsapp": str(payload.get("consultor_whatsapp", ""))[:30],
        "consultor_email": str(payload.get("consultor_email", ""))[:200],
        "sla_minutos": int(payload.get("sla_minutos", 15)),
    }
    if not (1 <= updates["sla_minutos"] <= 240):
        raise HTTPException(400, "sla_minutos fora do range 1-240")
    return await upsert_pj_config(company_id=company, updates=updates)


@router.get("/leads")
@limiter.limit(get_limit("isabella_read"))
async def list_leads(
    request: Request,
    status: Optional[str] = Query(None,
        description="Filtra por status (new, consultor_acionado, fechado, perdido)"),
    limit: int = Query(50, ge=1, le=500),
    cid: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_priv(user)
    company = _company_or_param(user, cid)
    q: Dict[str, Any] = {"company_id": company}
    if status:
        q["status"] = status
    cursor = db.pj_leads.find(q, {"_id": 1, "company_id": 1, "phone": 1,
                                    "status": 1, "razao_social": 1,
                                    "cnpj": 1, "responsavel_nome": 1,
                                    "consultor_nome": 1, "interesse": 1,
                                    "municipio": 1, "uf": 1,
                                    "created_at": 1, "updated_at": 1,
                                    "consultor_acionado_at": 1,
                                    "sla_target_at": 1}).sort(
        "created_at", -1,
    ).limit(limit)
    items = await cursor.to_list(limit)
    # Rename _id → id
    for it in items:
        it["id"] = it.pop("_id")
    return {"items": items, "n": len(items)}


@router.get("/leads/{lead_id}")
@limiter.limit(get_limit("isabella_read"))
async def get_lead(
    request: Request, lead_id: str,
    cid: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_priv(user)
    company = _company_or_param(user, cid)
    doc = await db.pj_leads.find_one(
        {"_id": lead_id, "company_id": company},
    )
    if not doc:
        raise HTTPException(404, "lead não encontrado")
    doc["id"] = doc.pop("_id")
    return doc


@router.post("/leads/{lead_id}/status")
@limiter.limit(get_limit("isabella_write"))
async def update_lead_status(
    request: Request, lead_id: str,
    new_status: str = Query(..., regex="^(new|consultor_acionado|fechado|perdido)$"),
    cid: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_priv(user)
    company = _company_or_param(user, cid)
    from datetime import datetime, timezone
    res = await db.pj_leads.update_one(
        {"_id": lead_id, "company_id": company},
        {"$set": {"status": new_status,
                   "updated_at": datetime.now(timezone.utc),
                   "updated_by": user.get("email")}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "lead não encontrado")
    return {"ok": True, "lead_id": lead_id, "new_status": new_status}
