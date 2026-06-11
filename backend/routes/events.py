"""SSE (Server-Sent Events) — push real-time para gestores/admins.

Quando uma notificação é criada (via `_create_notification` em lousa.py),
ela é também publicada nesse hub. Frontends de gestor/admin abrem uma
conexão `EventSource` em `/api/events/stream` para receber updates ao vivo.

Eventos emitidos:
  • `notification` — payload = a notificação completa (mesmo shape de /api/notifications)
  • `ping` — heartbeat a cada 25s para manter a conexão viva atrás de proxies

Multi-tenant: cada conexão é "subscrita" no company_id do usuário; eventos
de outras empresas não vazam.

Multi-worker: este hub é por-processo. Em deploy com múltiplos workers, um
event criado num worker NÃO chegará em conexões abertas em outro worker —
para isso, usar Redis Pub/Sub. Para um único processo (caso atual), funciona
nativamente.
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

import asyncio
import json
import logging
from typing import Any, Dict, Set

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from auth import decode_token
from core import DEMO_COMPANY_ID

logger = logging.getLogger("ponto.events")
router = APIRouter(prefix="/api/events", tags=["events"])


# -------------------------------------------------------------------------
# Hub: dict[company_id] -> set[asyncio.Queue]
# -------------------------------------------------------------------------
_subscribers: Dict[str, Set[asyncio.Queue]] = {}
_lock = asyncio.Lock()


async def _add_subscriber(company_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    async with _lock:
        _subscribers.setdefault(company_id, set()).add(q)
    return q


async def _remove_subscriber(company_id: str, q: asyncio.Queue) -> None:
    async with _lock:
        if company_id in _subscribers:
            _subscribers[company_id].discard(q)
            if not _subscribers[company_id]:
                _subscribers.pop(company_id, None)


async def publish_event(company_id: str, event: str, data: Dict[str, Any]) -> int:
    """Publica um evento para todos os subscribers da empresa.

    Best-effort: se a fila do subscriber está cheia, dropa silenciosamente
    (cliente lento — não trava o publisher).
    Retorna o número de subscribers que receberam.
    """
    delivered = 0
    async with _lock:
        targets = list(_subscribers.get(company_id, ()))
    for q in targets:
        try:
            q.put_nowait({"event": event, "data": data})
            delivered += 1
        except asyncio.QueueFull:
            logger.warning("[events] queue cheia para subscriber em %s — dropando", company_id)
    return delivered


@router.get("/stream")
async def stream_events(request: Request, token: str = Query(default="")):
    """Endpoint SSE — abre stream para o frontend.

    EventSource não permite headers customizados, então o token JWT vem
    via querystring (`?token=...`). Tentamos também o header Authorization
    como fallback para uso via curl/Postman.
    """
    if not token:
        auth_h = request.headers.get("authorization", "")
        if auth_h.lower().startswith("bearer "):
            token = auth_h.split(" ", 1)[1]

    real_user = None
    if token:
        try:
            payload = decode_token(token)
            real_user = {
                "id": payload.get("sub"),
                "role": payload.get("role"),
                "company_id": payload.get("company_id"),
                "email": payload.get("email"),
            }
        except Exception as e:
            logger.warning("[events] token inválido: %s", e)

    if not real_user or real_user.get("role") not in ("gestor", "administrador", "auditor"):
        raise HTTPException(status_code=401, detail="Token inválido ou perfil não autorizado")

    company_id = real_user.get("company_id") or DEMO_COMPANY_ID
    q = await _add_subscriber(company_id)

    async def _gen():
        try:
            yield {"event": "connected", "data": json.dumps({
                "company_id": company_id, "user": real_user.get("email"),
            })}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25.0)
                    yield {"event": msg["event"], "data": json.dumps(msg["data"], default=str)}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        except asyncio.CancelledError:
            pass
        finally:
            await _remove_subscriber(company_id, q)

    return EventSourceResponse(_gen())


@router.get("/stats")
async def events_stats(request: Request):
    """Útil para debug — quantas conexões abertas por empresa. Auth simples via Bearer."""
    auth_h = request.headers.get("authorization", "")
    token = auth_h.split(" ", 1)[1] if auth_h.lower().startswith("bearer ") else ""
    try:
        payload = decode_token(token)
        if payload.get("role") not in ("administrador", "auditor"):
            raise HTTPException(403, "apenas admin")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "token inválido")
    async with _lock:
        return {
            "companies": {cid: len(qs) for cid, qs in _subscribers.items()},
            "total_subscribers": sum(len(qs) for qs in _subscribers.values()),
        }
