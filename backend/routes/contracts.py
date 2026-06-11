"""routes/contracts.py — Contratos de assinantes + política de aging RADIUS.

Cada contrato vincula um Subscriber a um Plan, define a política de aging
(quantos dias após o vencimento aplicar redução/bloqueio) e expõe o estado
RADIUS atual (computado pelo worker `services.contracts_aging_worker`).

Estados RADIUS:
  - ATIVO            → cliente pagando, plano normal
  - GRACE            → vencido dentro da tolerância, sem ação ainda
  - REDUZIDO         → velocidade reduzida (perfil do plano)
  - WALLED_GARDEN    → só acessa portal de pagamento + bancos
  - SUSPENSO         → reject no RADIUS, sessão cortada
  - CANCELADO        → terminação definitiva (fim do contrato)

Endpoints:
  GET    /api/contracts                    — lista
  POST   /api/contracts                    — cria
  GET    /api/contracts/{id}               — detalhe
  PATCH  /api/contracts/{id}               — edita (aging, valor, plano)
  POST   /api/contracts/{id}/suspend       — força SUSPENSO + CoA
  POST   /api/contracts/{id}/reactivate    → restaura ATIVO + CoA
  POST   /api/contracts/{id}:apply-radius  — força recálculo + CoA agora
  POST   /api/contracts/aging/run-now      — dispara worker (gestor)
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "vendas-team",
    "domain": "comercial",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, get_current_user, is_super_admin
from database import db

logger = logging.getLogger("ponto.contracts")
router = APIRouter(prefix="/api/contracts", tags=["contracts"])


# Estados válidos
RADIUS_STATES = ("ATIVO", "GRACE", "REDUZIDO", "WALLED_GARDEN",
                  "SUSPENSO", "CANCELADO")


def _cid(user: dict) -> str:
    if is_super_admin(user):
        return (user.get("_active_company") or user.get("company_id")
                or DEMO_COMPANY_ID)
    return user.get("company_id") or DEMO_COMPANY_ID


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgingPolicy(BaseModel):
    """Quantos dias após o vencimento aplicar cada estado.
    `0` desabilita o estado correspondente (pula direto para o próximo)."""
    grace_days: int = Field(default=3, ge=0, le=30)
    reduce_days: int = Field(default=7, ge=0, le=60)
    wall_garden_days: int = Field(default=15, ge=0, le=90)
    suspend_days: int = Field(default=30, ge=0, le=180)
    enabled: bool = True


class ContractIn(BaseModel):
    subscriber_id: str
    plan_id: str
    contract_number: str = ""
    start_date: str = ""              # YYYY-MM-DD
    end_date: Optional[str] = None    # YYYY-MM-DD ou null
    monthly_value: float = 0.0
    due_day: int = Field(default=10, ge=1, le=31)
    aging_policy: AgingPolicy = Field(default_factory=AgingPolicy)
    notes: str = ""


class ContractPatch(BaseModel):
    plan_id: Optional[str] = None
    monthly_value: Optional[float] = None
    due_day: Optional[int] = None
    end_date: Optional[str] = None
    aging_policy: Optional[AgingPolicy] = None
    notes: Optional[str] = None


def _initial_state_doc(c: dict) -> dict:
    """Acrescenta campos default ao contract doc."""
    c.setdefault("radius_state", "ATIVO")
    c.setdefault("radius_state_at", _now_iso())
    c.setdefault("radius_state_reason", "Contrato criado")
    c.setdefault("status", "ativo")  # ativo | cancelado | encerrado
    return c


@router.get("")
async def list_contracts(
    status: str = Query(default="all"),
    search: str = "",
    limit: int = Query(default=200, ge=1, le=1000),
    user: dict = Depends(get_current_user),
):
    cid = _cid(user)
    q: Dict[str, Any] = {"company_id": cid}
    if status != "all":
        q["status"] = status
    if search:
        # Busca por contract_number, plan_name, subscriber_name (denorm)
        q["$or"] = [
            {"contract_number": {"$regex": search, "$options": "i"}},
            {"subscriber_name": {"$regex": search, "$options": "i"}},
            {"plan_name": {"$regex": search, "$options": "i"}},
        ]
    items = await db.contracts.find(q, {"_id": 0})\
        .sort("created_at", -1).limit(limit).to_list(limit)
    return {"items": items, "count": len(items)}


@router.post("")
async def create_contract(
    payload: ContractIn,
    user: dict = Depends(get_current_user),
):
    role = (user.get("role") or "").lower()
    if role not in ("gestor", "administrador") and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador.")
    cid = _cid(user)

    sub = await db.subscribers.find_one(
        {"id": payload.subscriber_id, "company_id": cid},
        {"_id": 0, "id": 1, "name": 1, "pppoe_user": 1, "status": 1})
    if not sub:
        raise HTTPException(404, "Assinante não encontrado")
    plan = await db.plans.find_one(
        {"id": payload.plan_id, "company_id": cid},
        {"_id": 0, "id": 1, "name": 1, "speed_down_mbps": 1,
         "speed_up_mbps": 1, "monthly_price": 1})
    if not plan:
        raise HTTPException(404, "Plano não encontrado")

    doc = _initial_state_doc({
        "id": f"ct-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "subscriber_id": sub["id"],
        "subscriber_name": sub.get("name"),
        "pppoe_user": sub.get("pppoe_user"),
        "plan_id": plan["id"],
        "plan_name": plan.get("name"),
        "contract_number": (
            payload.contract_number
            or f"C{datetime.now(timezone.utc).strftime('%Y%m%d')}-"
               f"{uuid.uuid4().hex[:6].upper()}"
        ),
        "start_date": payload.start_date
            or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "end_date": payload.end_date,
        "monthly_value": payload.monthly_value or plan.get("monthly_price", 0),
        "due_day": payload.due_day,
        "aging_policy": payload.aging_policy.model_dump(),
        "notes": payload.notes,
        "created_at": _now_iso(),
        "created_by": user.get("id"),
    })
    await db.contracts.insert_one(doc)
    # Garante que subscriber aponte para esse contrato
    await db.subscribers.update_one(
        {"id": sub["id"]},
        {"$set": {"active_contract_id": doc["id"]}},
    )
    doc.pop("_id", None)
    return doc


@router.get("/{cid_ct}")
async def get_contract(cid_ct: str, user: dict = Depends(get_current_user)):
    cid = _cid(user)
    c = await db.contracts.find_one(
        {"id": cid_ct, "company_id": cid}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Contrato não encontrado")
    return c


@router.patch("/{cid_ct}")
async def patch_contract(
    cid_ct: str,
    payload: ContractPatch,
    user: dict = Depends(get_current_user),
):
    role = (user.get("role") or "").lower()
    if role not in ("gestor", "administrador") and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador.")
    cid = _cid(user)
    c = await db.contracts.find_one(
        {"id": cid_ct, "company_id": cid}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Contrato não encontrado")

    update: Dict[str, Any] = {}
    if payload.plan_id and payload.plan_id != c.get("plan_id"):
        plan = await db.plans.find_one(
            {"id": payload.plan_id, "company_id": cid},
            {"_id": 0, "id": 1, "name": 1})
        if not plan:
            raise HTTPException(404, "Plano novo não encontrado")
        update["plan_id"] = plan["id"]
        update["plan_name"] = plan.get("name")
    if payload.monthly_value is not None:
        update["monthly_value"] = payload.monthly_value
    if payload.due_day is not None:
        update["due_day"] = payload.due_day
    if payload.end_date is not None:
        update["end_date"] = payload.end_date
    if payload.aging_policy is not None:
        update["aging_policy"] = payload.aging_policy.model_dump()
    if payload.notes is not None:
        update["notes"] = payload.notes
    update["updated_at"] = _now_iso()
    update["updated_by"] = user.get("id")

    await db.contracts.update_one({"id": cid_ct}, {"$set": update})
    return {"ok": True, "updated_keys": list(update.keys())}


@router.post("/{cid_ct}/suspend")
async def suspend_contract(
    cid_ct: str,
    payload: Dict[str, Any] = None,
    user: dict = Depends(get_current_user),
):
    """Força estado SUSPENSO + CoA Disconnect imediato."""
    payload = payload or {}
    return await _force_state(cid_ct, "SUSPENSO",
                               payload.get("reason") or "Suspenso manualmente",
                               user, send_coa=True)


@router.post("/{cid_ct}/reactivate")
async def reactivate_contract(
    cid_ct: str,
    payload: Dict[str, Any] = None,
    user: dict = Depends(get_current_user),
):
    """Restaura ATIVO + envia CoA pra reaplicar velocidade do plano."""
    payload = payload or {}
    return await _force_state(cid_ct, "ATIVO",
                               payload.get("reason") or "Reativado manualmente",
                               user, send_coa=True)


@router.post("/{cid_ct}/apply-radius")
async def apply_radius_now(
    cid_ct: str,
    user: dict = Depends(get_current_user),
):
    """Recalcula estado pelo worker (sem esperar 15min)."""
    from services.contracts_aging_worker import compute_state_for_contract
    cid = _cid(user)
    c = await db.contracts.find_one(
        {"id": cid_ct, "company_id": cid}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Contrato não encontrado")
    new_state, reason = await compute_state_for_contract(c)
    return await _force_state(cid_ct, new_state, reason, user, send_coa=True)


async def _force_state(
    cid_ct: str, new_state: str, reason: str,
    user: dict, send_coa: bool = False,
) -> dict:
    if new_state not in RADIUS_STATES:
        raise HTTPException(400, "Estado inválido")
    role = (user.get("role") or "").lower()
    if role not in ("gestor", "administrador") and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador.")
    cid = _cid(user)
    c = await db.contracts.find_one(
        {"id": cid_ct, "company_id": cid}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Contrato não encontrado")

    prev = c.get("radius_state")
    if prev == new_state:
        return {"ok": True, "no_change": True, "state": new_state}

    await db.contracts.update_one(
        {"id": cid_ct},
        {"$set": {
            "radius_state": new_state,
            "radius_state_at": _now_iso(),
            "radius_state_reason": reason,
            "updated_at": _now_iso(),
            "updated_by": user.get("id"),
        }},
    )
    # Log
    await db.contracts_log.insert_one({
        "id": f"ctlog-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "contract_id": cid_ct,
        "subscriber_id": c.get("subscriber_id"),
        "from_state": prev,
        "to_state": new_state,
        "reason": reason,
        "actor_id": user.get("id"),
        "actor_name": user.get("name") or user.get("email"),
        "at": _now_iso(),
    })

    coa_result = None
    if send_coa:
        # Dispara CoA Disconnect na(s) sessão(ões) ativa(s) desse usuário,
        # forçando reconexão e reaplicação de attributes pelo RADIUS
        coa_result = await _coa_for_subscriber(c)
    return {
        "ok": True, "state": new_state, "previous_state": prev,
        "coa": coa_result,
    }


async def _coa_for_subscriber(contract: dict) -> dict:
    """Dispara CoA Disconnect em todas as sessões ativas do PPPoE user."""
    pppoe = contract.get("pppoe_user")
    if not pppoe:
        return {"sent": 0, "reason": "sem pppoe_user"}
    sessions = await db.radius_sessions.find(
        {"company_id": contract["company_id"],
         "username": pppoe, "status": "active"},
        {"_id": 0}).to_list(20)
    if not sessions:
        return {"sent": 0, "reason": "nenhuma sessão ativa"}

    from routes.radius import _send_coa_disconnect
    sent_ok = 0
    for s in sessions:
        nas = await db.radius_nas.find_one(
            {"id": s.get("nas_id"),
             "company_id": contract["company_id"]}, {"_id": 0})
        if not nas:
            continue
        ok = await _send_coa_disconnect(nas, s)
        if ok:
            sent_ok += 1
            await db.radius_sessions.update_one(
                {"id": s["id"]},
                {"$set": {"pending_disconnect_at": _now_iso(),
                            "disconnected_by": "contracts_worker"}},
            )
    return {"sent": sent_ok, "total_sessions": len(sessions)}


@router.post("/aging/run-now")
async def run_aging_worker(user: dict = Depends(get_current_user)):
    role = (user.get("role") or "").lower()
    if role not in ("gestor", "administrador") and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador.")
    from services.contracts_aging_worker import run_once
    cid = _cid(user)
    r = await run_once(cid)
    return r


@router.get("/{cid_ct}/log")
async def contract_log(
    cid_ct: str,
    limit: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    cid = _cid(user)
    items = await db.contracts_log.find(
        {"contract_id": cid_ct, "company_id": cid}, {"_id": 0}
    ).sort("at", -1).limit(limit).to_list(limit)
    return {"items": items, "count": len(items)}
