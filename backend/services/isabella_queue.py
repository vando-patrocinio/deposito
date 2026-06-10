"""Isabella Queue — fila persistente em MongoDB + worker pool dedicado.

Arquitetura empresarial pós-Operação Eliminar Gargalo Twilio:

Webhook Twilio NUNCA chama LLM nem Twilio.
Webhook apenas:
  1. valida
  2. persiste inbound (aihub_wa_messages)
  3. upserta wa_conversations
  4. enqueue_job() → INSERT em isabella_queue
  5. retorna HTTP 200 (<100ms)

Worker pool (iniciado no @app.on_event("startup")):
  - N workers concorrentes (env ISABELLA_QUEUE_WORKERS, default 25)
  - Cada worker faz find_one_and_update atômico para claim de job
  - Estados do job: queued → processing → done | failed
  - Worker invoca _generate_and_send_twilio_reply (LLM + Twilio + INSERT outbound)
  - Backoff exponencial em retry; max 3 tentativas

Coleção: isabella_queue
  Indexes:
    - {status:1, created_at:1}  → claim em ordem
    - {created_at:1} TTL 7 dias → garbage collect

Métricas (opcional, em isabella_queue_metrics):
  - depth, throughput, latência média, taxa de sucesso
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from database import db

logger = logging.getLogger("isabella_queue")

QUEUE_COLL = "isabella_queue"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pool_size() -> int:
    try:
        return max(1, int(os.environ.get("ISABELLA_QUEUE_WORKERS") or 25))
    except (TypeError, ValueError):
        return 25


def _max_retries() -> int:
    try:
        return max(0, int(os.environ.get("ISABELLA_QUEUE_MAX_RETRIES") or 3))
    except (TypeError, ValueError):
        return 3


# ─── Indexes ──────────────────────────────────────────────────────
async def ensure_indexes() -> None:
    try:
        await db[QUEUE_COLL].create_index(
            [("status", 1), ("created_at", 1)],
            name="status_created_idx",
        )
        # TTL: jobs done/failed expiram em 7 dias para não inchar a coleção
        await db[QUEUE_COLL].create_index(
            "expires_at",
            name="ttl_idx",
            expireAfterSeconds=0,
        )
        logger.info("[isabella_queue] indexes garantidos")
    except Exception as e:
        logger.warning("[isabella_queue] ensure_indexes falhou: %s", e)


# ─── API: Enqueue ─────────────────────────────────────────────────
async def enqueue_job(
    *,
    cid: str,
    phone: str,
    user_text: str,
    subscriber_id: Optional[str],
    subscriber_ctx: Optional[str],
    channel: str = "twilio",
    message_sid: Optional[str] = None,
) -> str:
    """Insere job na fila e retorna job_id. NÃO bloqueia."""
    job_id = f"job-{uuid.uuid4().hex[:14]}"
    doc = {
        "_id": job_id,
        "status": "queued",
        "channel": channel,
        "company_id": cid,
        "phone": phone,
        "user_text": user_text,
        "subscriber_id": subscriber_id,
        "subscriber_ctx": subscriber_ctx,
        "message_sid": message_sid,
        "attempts": 0,
        "created_at": _now(),
        "picked_at": None,
        "done_at": None,
        "error": None,
    }
    await db[QUEUE_COLL].insert_one(doc)
    return job_id


# ─── Worker ───────────────────────────────────────────────────────
async def _process_one_job(job: Dict[str, Any]) -> None:
    """Processa 1 job: chama LLM + envia Twilio + atualiza ledger."""
    job_id = job["_id"]
    t0 = _now()
    try:
        if job.get("channel", "twilio") == "twilio":
            # Import lazy para evitar ciclo no startup
            from routes.whatsapp_twilio import _generate_and_send_twilio_reply
            await _generate_and_send_twilio_reply(
                cid=job["company_id"],
                phone=job["phone"],
                user_text=job["user_text"],
                subscriber_id=job.get("subscriber_id"),
                subscriber_ctx=job.get("subscriber_ctx"),
            )
        else:
            raise RuntimeError(f"channel não suportado: {job.get('channel')}")

        latency_ms = int((_now() - t0).total_seconds() * 1000)
        await db[QUEUE_COLL].update_one(
            {"_id": job_id},
            {"$set": {
                "status": "done",
                "done_at": _now(),
                "latency_ms": latency_ms,
                "expires_at": _now() + timedelta(days=7),
            }},
        )
    except Exception as e:  # noqa: BLE001
        attempts = (job.get("attempts") or 0) + 1
        max_r = _max_retries()
        err_text = repr(e)[:300]
        if attempts < max_r:
            # Retry: volta a queued com backoff em created_at
            backoff_s = min(60, 2 ** attempts)
            await db[QUEUE_COLL].update_one(
                {"_id": job_id},
                {"$set": {
                    "status": "queued",
                    "attempts": attempts,
                    "last_error": err_text,
                    "created_at": _now() + timedelta(seconds=backoff_s),
                }},
            )
            logger.warning("[isabella_queue] job=%s retry %d/%d em %ds: %s",
                            job_id, attempts, max_r, backoff_s, err_text)
        else:
            await db[QUEUE_COLL].update_one(
                {"_id": job_id},
                {"$set": {
                    "status": "failed",
                    "attempts": attempts,
                    "error": err_text,
                    "done_at": _now(),
                    "expires_at": _now() + timedelta(days=7),
                }},
            )
            logger.error("[isabella_queue] job=%s FAILED após %d tentativas: %s",
                          job_id, attempts, err_text)


async def _worker_loop(worker_id: int) -> None:
    """Loop infinito de 1 worker. Claims job e processa."""
    logger.info("[isabella_queue] worker #%d online", worker_id)
    backoff_idle = 0.1
    while True:
        try:
            # Claim atômico: pega o job mais antigo em status=queued
            # cujo created_at já passou (suporta backoff).
            now = _now()
            job = await db[QUEUE_COLL].find_one_and_update(
                {"status": "queued", "created_at": {"$lte": now}},
                {"$set": {
                    "status": "processing",
                    "picked_at": now,
                    "picked_by": f"worker-{worker_id}",
                }},
                sort=[("created_at", 1)],
            )
            if not job:
                await asyncio.sleep(backoff_idle)
                # Aumenta backoff levemente quando ocioso (até 1s)
                backoff_idle = min(1.0, backoff_idle * 1.5)
                continue
            backoff_idle = 0.1
            await _process_one_job(job)
        except asyncio.CancelledError:
            logger.info("[isabella_queue] worker #%d cancelado", worker_id)
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("[isabella_queue] worker #%d crash: %s", worker_id, e)
            await asyncio.sleep(1.0)


# ─── Pool management ──────────────────────────────────────────────
_WORKER_TASKS: list[asyncio.Task] = []


async def start_workers() -> None:
    """Inicia o pool. Chamado no @app.on_event('startup')."""
    if _WORKER_TASKS:
        logger.warning("[isabella_queue] pool já iniciado, ignorando")
        return
    await ensure_indexes()
    # Recovery: jobs em 'processing' há > 5min provavelmente caíram em restart.
    # Volta para queued.
    cutoff = _now() - timedelta(minutes=5)
    recovered = await db[QUEUE_COLL].update_many(
        {"status": "processing", "picked_at": {"$lt": cutoff}},
        {"$set": {"status": "queued"}},
    )
    if recovered.modified_count:
        logger.info("[isabella_queue] %d jobs recuperados de 'processing' órfão",
                     recovered.modified_count)
    n = _pool_size()
    for i in range(n):
        t = asyncio.create_task(_worker_loop(i + 1), name=f"isabella-worker-{i+1}")
        _WORKER_TASKS.append(t)
    logger.info("[isabella_queue] pool de %d workers iniciado", n)


async def stop_workers() -> None:
    """Para o pool. Chamado no @app.on_event('shutdown')."""
    for t in _WORKER_TASKS:
        t.cancel()
    _WORKER_TASKS.clear()


# ─── Telemetria (para debug; não cria endpoint novo) ───────────────
async def stats() -> Dict[str, Any]:
    pipe = [
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ]
    by_status = {r["_id"]: r["n"] async for r in db[QUEUE_COLL].aggregate(pipe)}
    return {
        "pool_size": _pool_size(),
        "by_status": by_status,
        "ts": _now().isoformat(),
    }
