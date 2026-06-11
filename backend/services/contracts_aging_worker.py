"""services/contracts_aging_worker.py — Recalcula estado RADIUS dos contratos
com base em invoices vencidas (aging) e dispara CoA Disconnect quando muda.

Roda a cada 15min em background (via lifespan).
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

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Tuple

from database import db

logger = logging.getLogger("ponto.contracts_aging")

WORKER_INTERVAL_SEC = 900  # 15min


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


async def _max_overdue_days(contract: dict) -> int:
    """Retorna o maior aging (em dias) entre as invoices em aberto.
    Procura invoices da empresa+subscriber em diversas coleções possíveis
    (billing, invoices, faturas). Best-effort.
    """
    sub_id = contract.get("subscriber_id")
    cid = contract.get("company_id")
    today = _now().date()
    max_days = 0
    for coll_name in ("invoices", "billing_invoices", "faturas",
                      "subscriber_invoices"):
        try:
            coll = db[coll_name]
            async for inv in coll.find(
                {"company_id": cid,
                 "$or": [{"subscriber_id": sub_id},
                         {"customer_id": sub_id},
                         {"client_id": sub_id}],
                 "status": {"$in": ["open", "pending", "vencida",
                                     "em_aberto", "atrasada", "OVERDUE"]}},
                {"_id": 0, "due_date": 1, "status": 1, "amount": 1},
            ):
                due = inv.get("due_date")
                if not due:
                    continue
                try:
                    if isinstance(due, str):
                        ddate = datetime.fromisoformat(
                            due.replace("Z", "+00:00")).date()
                    else:
                        ddate = due.date() if hasattr(due, "date") else None
                    if not ddate or ddate >= today:
                        continue
                    days = (today - ddate).days
                    if days > max_days:
                        max_days = days
                except (ValueError, TypeError):
                    continue
        except Exception:
            continue
    return max_days


async def compute_state_for_contract(contract: dict) -> Tuple[str, str]:
    """Retorna (novo_estado, motivo)."""
    if contract.get("status") in ("cancelado", "encerrado"):
        return "CANCELADO", "Contrato encerrado/cancelado"

    policy = contract.get("aging_policy") or {}
    if not policy.get("enabled", True):
        return "ATIVO", "Aging desabilitado"

    overdue = await _max_overdue_days(contract)
    if overdue <= 0:
        return "ATIVO", "Em dia"

    grace = policy.get("grace_days", 3)
    reduce_ = policy.get("reduce_days", 7)
    wg = policy.get("wall_garden_days", 15)
    suspend = policy.get("suspend_days", 30)

    if overdue >= suspend > 0:
        return "SUSPENSO", f"Vencido há {overdue} dias (suspende a partir de {suspend}d)"
    if overdue >= wg > 0:
        return "WALLED_GARDEN", f"Vencido há {overdue} dias (wall garden a partir de {wg}d)"
    if overdue >= reduce_ > 0:
        return "REDUZIDO", f"Vencido há {overdue} dias (reduzido a partir de {reduce_}d)"
    if overdue >= grace > 0:
        return "GRACE", f"Vencido há {overdue} dias (tolerância até {reduce_ or wg or suspend}d)"
    return "ATIVO", f"Vencido há {overdue} dias (dentro da tolerância)"


async def _apply_state_change(contract: dict, new_state: str,
                                reason: str) -> bool:
    """Persiste mudança de estado + dispara CoA. Retorna True se houve mudança."""
    prev = contract.get("radius_state") or "ATIVO"
    if prev == new_state:
        # Atualiza só o motivo se relevante
        await db.contracts.update_one(
            {"id": contract["id"]},
            {"$set": {"radius_state_reason": reason}},
        )
        return False
    await db.contracts.update_one(
        {"id": contract["id"]},
        {"$set": {
            "radius_state": new_state,
            "radius_state_at": _now_iso(),
            "radius_state_reason": reason,
        }},
    )
    await db.contracts_log.insert_one({
        "id": f"ctlog-{uuid.uuid4().hex[:10]}",
        "company_id": contract["company_id"],
        "contract_id": contract["id"],
        "subscriber_id": contract.get("subscriber_id"),
        "from_state": prev,
        "to_state": new_state,
        "reason": reason,
        "actor_id": "aging_worker",
        "actor_name": "Aging Worker",
        "at": _now_iso(),
    })
    # CoA Disconnect: força a próxima auth com novo perfil
    try:
        from routes.contracts import _coa_for_subscriber
        coa = await _coa_for_subscriber(contract)
        logger.info("[aging] %s %s→%s · coa=%s",
                    contract["id"], prev, new_state, coa)
    except Exception as e:
        logger.warning("[aging] coa err %s: %s", contract["id"], e)
    return True


async def run_once(company_id: str = None) -> dict:
    """Roda uma vez. Se company_id passado, limita ao escopo."""
    q = {"status": {"$ne": "cancelado"}}
    if company_id:
        q["company_id"] = company_id
    changed = 0
    inspected = 0
    by_state = {}
    cursor = db.contracts.find(q, {"_id": 0})
    async for c in cursor:
        inspected += 1
        try:
            new_state, reason = await compute_state_for_contract(c)
            by_state[new_state] = by_state.get(new_state, 0) + 1
            if await _apply_state_change(c, new_state, reason):
                changed += 1
        except Exception as e:
            logger.exception("[aging] erro contrato %s: %s", c.get("id"), e)
    logger.info("[aging] inspected=%d changed=%d by_state=%s",
                inspected, changed, by_state)
    return {"inspected": inspected, "changed": changed,
            "by_state": by_state, "at": _now_iso()}


async def worker_loop():
    """Loop infinito chamado pelo lifespan."""
    logger.info("[aging] worker iniciado (interval=%ds)", WORKER_INTERVAL_SEC)
    # Espera 30s antes da primeira execução pra app subir
    await asyncio.sleep(30)
    while True:
        try:
            await run_once()
        except Exception as e:
            logger.exception("[aging] loop err: %s", e)
        await asyncio.sleep(WORKER_INTERVAL_SEC)
