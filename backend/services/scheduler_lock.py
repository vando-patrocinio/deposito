"""
scheduler_lock.py — Leader election distribuído via MongoDB
Garante que apenas um worker (entre N réplicas) executa os jobs
do APScheduler em produção.

Modo de uso (em executive_scheduler):
    from services.scheduler_lock import try_acquire_leader, renew_leader

A lock vive em `scheduler_locks`:
    { _id: "executive_scheduler", holder: <uuid>,
      acquired_at: ISO, expires_at: ISO }

Heartbeat: o leader renova `expires_at` a cada 30s. Se cair, qualquer
worker pode reassumir após o expires_at vencer.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from database import db

log = logging.getLogger("scheduler_lock")

LOCK_ID = os.environ.get("SCHEDULER_LOCK_ID", "executive_scheduler")
LOCK_TTL_SECONDS = int(os.environ.get("SCHEDULER_LOCK_TTL", "60"))
RENEW_EVERY_SECONDS = int(os.environ.get("SCHEDULER_RENEW", "20"))

_holder_id: Optional[str] = None


def _hostname() -> str:
    return f"{socket.gethostname()}-pid{os.getpid()}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def try_acquire_leader() -> bool:
    """Tenta virar leader. True = adquirido (ou já era). False = outro worker."""
    global _holder_id
    if _holder_id is None:
        _holder_id = f"{_hostname()}-{uuid.uuid4().hex[:8]}"
    now = _now()
    expires = now + timedelta(seconds=LOCK_TTL_SECONDS)
    # upsert atômico: só sobe se não existe ou já expirou
    try:
        await db.scheduler_locks.update_one(
            {
                "_id": LOCK_ID,
                "$or": [
                    {"holder": _holder_id},
                    {"expires_at": {"$lte": now.isoformat()}},
                ],
            },
            {"$set": {
                "holder": _holder_id,
                "host": _hostname(),
                "acquired_at": now.isoformat(),
                "expires_at": expires.isoformat(),
            }},
            upsert=True,
        )
    except Exception as e:  # pode dar DuplicateKeyError se outro
        # processo upsertou no mesmo nanossegundo — ok
        log.debug("[scheduler_lock] upsert collision: %s", e)
    # verifica se nós somos o holder
    doc = await db.scheduler_locks.find_one({"_id": LOCK_ID})
    if doc and doc.get("holder") == _holder_id:
        return True
    return False


async def renew_leader() -> bool:
    """Renova o lock se ainda for nosso. Retorna True se ok."""
    global _holder_id
    if _holder_id is None:
        return await try_acquire_leader()
    now = _now()
    expires = now + timedelta(seconds=LOCK_TTL_SECONDS)
    r = await db.scheduler_locks.update_one(
        {"_id": LOCK_ID, "holder": _holder_id},
        {"$set": {"expires_at": expires.isoformat()}},
    )
    return bool(r.modified_count or r.matched_count)


async def release_leader() -> None:
    """Libera o lock no shutdown limpo."""
    global _holder_id
    if _holder_id is None:
        return
    try:
        await db.scheduler_locks.delete_one(
            {"_id": LOCK_ID, "holder": _holder_id})
    except Exception:
        pass
    _holder_id = None


async def current_leader() -> dict:
    doc = await db.scheduler_locks.find_one({"_id": LOCK_ID}) or {}
    holder = doc.get("holder")
    return {
        "lock_id": LOCK_ID,
        "holder": holder,
        "host": doc.get("host"),
        "expires_at": doc.get("expires_at"),
        "is_me": bool(holder and _holder_id and holder == _holder_id),
        "my_holder_id": _holder_id,
    }
