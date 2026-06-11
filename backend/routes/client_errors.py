"""
client_errors.py — Recebe crashes do ErrorBoundary do frontend (iter211ac).

Quando um componente React crashar com erro fatal, o ErrorBoundary envia
um POST aqui com detalhes (stack, component_stack, URL, user-agent).
Gravamos em `db.client_errors` pra investigar mais tarde.

Endpoint aberto (sem auth) propositadamente — usuários sem login podem
crashar a tela (ex: rota pública /rede-publica). Mas há rate limit
simples por IP pra evitar spam.
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

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Depends, Query
from pydantic import BaseModel, Field

from database import db
from core import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/client-errors", tags=["client-errors"])


class ClientErrorPayload(BaseModel):
    boundary: str = Field(default="unknown", max_length=80)
    message: str = Field(default="", max_length=2000)
    stack: str = Field(default="", max_length=8000)
    component_stack: str = Field(default="", max_length=4000)
    url: str = Field(default="", max_length=500)
    user_agent: str = Field(default="", max_length=500)
    ts: str = Field(default="")


# Rate limit em memória: max 30 reqs por IP/min
_RATE: dict = {}
_RATE_LIMIT = 30
_RATE_WINDOW = 60.0


def _allow(ip: str) -> bool:
    now = time.time()
    bucket = _RATE.get(ip, [])
    bucket = [t for t in bucket if t > now - _RATE_WINDOW]
    if len(bucket) >= _RATE_LIMIT:
        _RATE[ip] = bucket
        return False
    bucket.append(now)
    _RATE[ip] = bucket
    return True


@router.post("/log")
async def log_client_error(payload: ClientErrorPayload, request: Request):
    ip = (request.client.host if request.client else "unknown") or "unknown"
    if not _allow(ip):
        return {"ok": False, "rate_limited": True}
    doc = {
        "boundary": payload.boundary,
        "message": payload.message[:500],  # truncar pra index ser leve
        "stack": payload.stack,
        "component_stack": payload.component_stack,
        "url": payload.url,
        "user_agent": payload.user_agent,
        "client_ts": payload.ts,
        "server_ts": datetime.now(timezone.utc).isoformat(),
        "ip": ip,
    }
    try:
        await db.client_errors.insert_one(doc)
        logger.warning("[client-error] %s @ %s: %s",
                       payload.boundary, payload.url, payload.message[:120])
    except Exception as e:
        logger.exception("[client-error] failed to persist: %s", e)
    return {"ok": True}


# ============================================================
# Painel admin — lista e estatísticas dos crashes (iter211ag)
# ============================================================

def _is_manager(user: dict) -> bool:
    roles = user.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    if user.get("is_super_admin"):
        return True
    return any(r in {"gestor", "auditor", "admin", "super_admin"} for r in roles)


@router.get("/list")
async def list_client_errors(
    boundary: str | None = Query(default=None, max_length=80),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    user: dict = Depends(get_current_user),
):
    """Lista os crashes do frontend mais recentes (apenas gestor/auditor/admin).

    Filtros:
      • boundary: nome do ErrorBoundary (ex: "lousa-mobile", "bubble-tkt-abc")
      • q:        substring (case-insensitive) procurada em message/url
    """
    if not _is_manager(user):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Acesso negado")
    flt: dict = {}
    if boundary:
        flt["boundary"] = boundary
    if q:
        flt["$or"] = [
            {"message": {"$regex": q, "$options": "i"}},
            {"url": {"$regex": q, "$options": "i"}},
        ]
    cur = db.client_errors.find(flt, {"_id": 0}).sort("server_ts", -1).limit(limit)
    items = await cur.to_list(limit)
    return {"items": items, "count": len(items)}


@router.get("/summary")
async def summary_client_errors(
    days: int = Query(default=7, ge=1, le=90),
    user: dict = Depends(get_current_user),
):
    """Agrega contagens por boundary nos últimos N dias (default 7)."""
    if not _is_manager(user):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Acesso negado")
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    pipeline = [
        {"$match": {"server_ts": {"$gte": cutoff}}},
        {"$group": {
            "_id": "$boundary",
            "n": {"$sum": 1},
            "last_ts": {"$max": "$server_ts"},
            "last_msg": {"$last": "$message"},
        }},
        {"$sort": {"n": -1}},
        {"$limit": 50},
    ]
    out = []
    async for row in db.client_errors.aggregate(pipeline):
        out.append({
            "boundary": row["_id"],
            "count": row["n"],
            "last_ts": row.get("last_ts"),
            "last_msg": row.get("last_msg") or "",
        })
    total = await db.client_errors.count_documents({"server_ts": {"$gte": cutoff}})
    return {"days": days, "total": total, "by_boundary": out}


@router.delete("/clear")
async def clear_client_errors(
    boundary: str | None = Query(default=None, max_length=80),
    user: dict = Depends(get_current_user),
):
    """Limpa logs (todos ou de um boundary específico). Apenas super_admin."""
    if not user.get("is_super_admin"):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Apenas super admin")
    flt = {"boundary": boundary} if boundary else {}
    r = await db.client_errors.delete_many(flt)
    return {"ok": True, "deleted": r.deleted_count}
