"""CTO fix 12/06/2026 — Election loop resilience (Atlaz sync órfão).

Bug: try_acquire_leader era chamado UMA vez no startup. Restart sujo
deixava lock zumbi → todos workers FOLLOWER permanentes → Atlaz sync
e demais background jobs órfãos até o próximo deploy.

Cobertura:
  1) try_acquire_leader vira leader quando lock anterior expirou.
  2) try_acquire_leader é idempotente (renova) para o próprio holder.
  3) release_leader remove o lock somente do holder atual.
  4) Worker B vence depois que o lock do Worker A expira (cenário do bug).
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _run(coro_factory):
    """Cria novo Motor client por test (evita event loop closed)."""
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import database as dm
        dm.db = db
        from services import scheduler_lock as sl
        importlib.reload(sl)
        await db.scheduler_locks.delete_many({"_id": sl.LOCK_ID})
        try:
            return await coro_factory(db, sl)
        finally:
            await db.scheduler_locks.delete_many({"_id": sl.LOCK_ID})
            c.close()
    return asyncio.new_event_loop().run_until_complete(_wrap())


def test_acquire_when_lock_expired():
    async def _t(db, sl):
        await db.scheduler_locks.update_one(
            {"_id": sl.LOCK_ID},
            {"$set": {
                "holder": "zombie-pid-99999",
                "host": "zombie",
                "acquired_at": (datetime.now(timezone.utc)
                                - timedelta(minutes=5)).isoformat(),
                "expires_at": (datetime.now(timezone.utc)
                               - timedelta(seconds=1)).isoformat(),
            }},
            upsert=True,
        )
        sl._holder_id = None
        ok = await sl.try_acquire_leader()
        assert ok is True, "deveria reassumir lock expirado"
        doc = await db.scheduler_locks.find_one({"_id": sl.LOCK_ID})
        assert doc["holder"] == sl._holder_id
    _run(_t)


def test_renew_is_idempotent_for_holder():
    async def _t(db, sl):
        sl._holder_id = None
        await sl.try_acquire_leader()
        first = await db.scheduler_locks.find_one({"_id": sl.LOCK_ID})
        # pequena pausa para garantir diff em expires_at
        await asyncio.sleep(0.05)
        ok = await sl.try_acquire_leader()
        assert ok is True
        second = await db.scheduler_locks.find_one({"_id": sl.LOCK_ID})
        assert first["holder"] == second["holder"]
        assert second["expires_at"] >= first["expires_at"]
    _run(_t)


def test_release_leader_clears_own_lock_only():
    async def _t(db, sl):
        await db.scheduler_locks.update_one(
            {"_id": sl.LOCK_ID},
            {"$set": {
                "holder": "other-worker-xyz",
                "host": "other",
                "acquired_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": (datetime.now(timezone.utc)
                               + timedelta(seconds=60)).isoformat(),
            }},
            upsert=True,
        )
        sl._holder_id = "my-id-not-leader"
        await sl.release_leader()
        doc = await db.scheduler_locks.find_one({"_id": sl.LOCK_ID})
        assert doc is not None, "lock alheio não pode ser apagado"
        assert doc["holder"] == "other-worker-xyz"
    _run(_t)


def test_worker_b_takes_over_after_a_dies():
    """Cenário do bug Atlaz: A pega lock, morre sem release; B assume
    automaticamente após TTL expirar (sem precisar de deploy)."""
    async def _t(db, sl):
        sl._holder_id = None
        await sl.try_acquire_leader()
        holder_a = sl._holder_id
        assert holder_a is not None

        # A "morre" — força expires_at no passado
        await db.scheduler_locks.update_one(
            {"_id": sl.LOCK_ID},
            {"$set": {"expires_at": (datetime.now(timezone.utc)
                                       - timedelta(seconds=1)).isoformat()}},
        )

        sl._holder_id = None  # novo worker B
        ok = await sl.try_acquire_leader()
        assert ok is True
        doc = await db.scheduler_locks.find_one({"_id": sl.LOCK_ID})
        assert doc["holder"] == sl._holder_id
        assert doc["holder"] != holder_a
    _run(_t)
