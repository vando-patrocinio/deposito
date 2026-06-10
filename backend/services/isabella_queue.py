"""Isabella Queue — fila persistente em MongoDB.

Após OPERAÇÃO SEPARAR WORKER ISABELLA:
- O webhook HTTP só importa daqui: `enqueue_job` (síncrono, rápido).
- O processo separado `/app/backend/workers/isabella_queue_worker.py` importa
  `start_workers` / `stop_workers` para drenar a fila.

Coleção: `isabella_queue`
Estados: queued → processing → done | failed
Métricas: `isabella_queue_metrics` (snapshot a cada 5s) +
          `isabella_queue_metrics_counters` (contadores incrementais)
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
METRICS_SNAP_COLL = "isabella_queue_metrics"
METRICS_CTR_COLL = "isabella_queue_metrics_counters"
COUNTER_DOC_ID = "global"

# ─── Config via env ─────────────────────────────────────────────
def _pool_size() -> int:
    try:
        return max(1, int(os.environ.get("ISABELLA_WORKER_CONCURRENCY")
                          or os.environ.get("ISABELLA_QUEUE_WORKERS")
                          or 10))
    except (TypeError, ValueError):
        return 10


def _poll_ms() -> int:
    try:
        return max(10, int(os.environ.get("ISABELLA_WORKER_POLL_MS") or 100))
    except (TypeError, ValueError):
        return 100


def _max_retries() -> int:
    try:
        return max(0, int(os.environ.get("ISABELLA_WORKER_MAX_RETRIES")
                          or os.environ.get("ISABELLA_QUEUE_MAX_RETRIES")
                          or 3))
    except (TypeError, ValueError):
        return 3


def _llm_timeout_s() -> float:
    try:
        return max(1.0, float(os.environ.get("ISABELLA_LLM_TIMEOUT_S") or 6.0))
    except (TypeError, ValueError):
        return 6.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── Indexes & recovery ─────────────────────────────────────────
async def ensure_indexes() -> None:
    try:
        await db[QUEUE_COLL].create_index(
            [("status", 1), ("created_at", 1)], name="status_created_idx")
        await db[QUEUE_COLL].create_index(
            "expires_at", name="ttl_idx", expireAfterSeconds=0)
        logger.info("[isabella_queue] indexes garantidos")
    except Exception as e:
        logger.warning("[isabella_queue] ensure_indexes falhou: %s", e)


async def recover_orphans() -> int:
    cutoff = _now() - timedelta(minutes=5)
    res = await db[QUEUE_COLL].update_many(
        {"status": "processing", "picked_at": {"$lt": cutoff}},
        {"$set": {"status": "queued"}},
    )
    return res.modified_count or 0


# ─── Métricas — counters atômicos ───────────────────────────────
async def _bump(field: str, value: int = 1) -> None:
    try:
        await db[METRICS_CTR_COLL].update_one(
            {"_id": COUNTER_DOC_ID},
            {"$inc": {field: value},
             "$set": {"updated_at": _now()}},
            upsert=True,
        )
    except Exception:
        pass


# ─── API pública: enqueue ───────────────────────────────────────
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
    job_id = f"job-{uuid.uuid4().hex[:14]}"
    await db[QUEUE_COLL].insert_one({
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
    })
    await _bump("jobs_created")
    return job_id


# ─── Fallback rápido quando LLM demora ──────────────────────────
FALLBACK_TEXT = ("Recebi sua mensagem. Já estou verificando e te respondo "
                  "em instantes.")


async def _send_fallback_and_log(*, cid: str, phone: str,
                                  subscriber_id: Optional[str]) -> None:
    """Quando LLM excede ISABELLA_LLM_TIMEOUT_S, enviamos um canned safe."""
    from routes.whatsapp_twilio import send_via_twilio
    from core import now_iso
    try:
        sent = await send_via_twilio(cid, phone, FALLBACK_TEXT,
                                      media_urls=None)
        await db.aihub_wa_messages.insert_one({
            "id": f"wam-{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "direction": "outbound",
            "channel": "twilio",
            "phone": phone,
            "text": FALLBACK_TEXT,
            "agent_id": "fallback-canned",
            "agent_name": "fallback",
            "subscriber_id": subscriber_id,
            "delivery_status": sent.get("status") if sent else "unknown",
            "message_id": sent.get("sid") if sent else None,
            "llm_timeout_fallback": True,
            "created_at": now_iso(),
        })
        await _bump("llm_timeout_count")
        await _bump("twilio_send_count")
    except Exception as e:
        await _bump("twilio_error_count")
        logger.warning("[isabella_queue] fallback send falhou: %s", e)


# ─── Processamento de 1 job ─────────────────────────────────────
async def _process_one_job(job: Dict[str, Any]) -> None:
    job_id = job["_id"]
    t0 = _now()
    timeout_s = _llm_timeout_s()
    try:
        if job.get("channel", "twilio") != "twilio":
            raise RuntimeError(f"channel não suportado: {job.get('channel')}")

        # Import lazy para não puxar FastAPI no worker
        from routes.whatsapp_twilio import _generate_and_send_twilio_reply

        try:
            await asyncio.wait_for(
                _generate_and_send_twilio_reply(
                    cid=job["company_id"],
                    phone=job["phone"],
                    user_text=job["user_text"],
                    subscriber_id=job.get("subscriber_id"),
                    subscriber_ctx=job.get("subscriber_ctx"),
                ),
                timeout=timeout_s,
            )
            await _bump("twilio_send_count")
        except asyncio.TimeoutError:
            logger.warning(
                "[isabella_queue] job=%s LLM timeout %.1fs → fallback canned",
                job_id, timeout_s)
            # Spawn fallback em paralelo; main task original pode continuar
            # rodando em background e completará a outbound real depois.
            asyncio.create_task(_send_fallback_and_log(
                cid=job["company_id"],
                phone=job["phone"],
                subscriber_id=job.get("subscriber_id"),
            ))

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
        await _bump("jobs_completed")
        await _bump("processing_ms_total", latency_ms)

    except Exception as e:  # noqa: BLE001
        attempts = (job.get("attempts") or 0) + 1
        max_r = _max_retries()
        err_text = repr(e)[:300]
        if attempts < max_r:
            backoff_s = min(30, 2 ** attempts)
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
            await _bump("jobs_failed")
            logger.error("[isabella_queue] job=%s FAILED após %d: %s",
                          job_id, attempts, err_text)


# ─── Worker loop ────────────────────────────────────────────────
async def _worker_loop(worker_id: int) -> None:
    poll_ms = _poll_ms()
    backoff_idle = poll_ms / 1000.0
    logger.info("[isabella_queue] worker #%d online (poll=%dms)",
                 worker_id, poll_ms)
    while True:
        try:
            now = _now()
            job = await db[QUEUE_COLL].find_one_and_update(
                {"status": "queued", "created_at": {"$lte": now}},
                {"$set": {
                    "status": "processing", "picked_at": now,
                    "picked_by": f"worker-{worker_id}",
                }},
                sort=[("created_at", 1)],
            )
            if not job:
                await asyncio.sleep(backoff_idle)
                backoff_idle = min(2.0, backoff_idle * 1.5)
                continue
            backoff_idle = poll_ms / 1000.0
            await _process_one_job(job)
        except asyncio.CancelledError:
            logger.info("[isabella_queue] worker #%d cancelado", worker_id)
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("[isabella_queue] worker #%d crash: %s",
                             worker_id, e)
            await asyncio.sleep(1.0)


# ─── Snapshot periódico de métricas ─────────────────────────────
async def _metrics_loop() -> None:
    """A cada 5s, snapshot da fila em isabella_queue_metrics."""
    import statistics
    while True:
        try:
            await asyncio.sleep(5.0)
            agg = await db[QUEUE_COLL].aggregate([
                {"$group": {"_id": "$status", "n": {"$sum": 1}}},
            ]).to_list(20)
            by_status = {r["_id"]: r["n"] for r in agg}
            # Latência p95/avg dos últimos 200 jobs done
            recent = await db[QUEUE_COLL].find(
                {"status": "done", "latency_ms": {"$exists": True}},
                {"latency_ms": 1, "_id": 0},
            ).sort("done_at", -1).limit(200).to_list(200)
            lats = [r["latency_ms"] for r in recent]
            avg_ms = round(sum(lats)/len(lats), 1) if lats else 0
            p95_ms = (round(statistics.quantiles(lats, n=20)[18], 1)
                      if len(lats) >= 20 else max(lats, default=0))
            counters = await db[METRICS_CTR_COLL].find_one(
                {"_id": COUNTER_DOC_ID}, {"_id": 0}) or {}
            snap = {
                "ts": _now(),
                "queue_depth": by_status.get("queued", 0),
                "jobs_processing": by_status.get("processing", 0),
                "jobs_done": by_status.get("done", 0),
                "jobs_failed": by_status.get("failed", 0),
                "avg_processing_ms": avg_ms,
                "p95_processing_ms": p95_ms,
                "counters": counters,
            }
            await db[METRICS_SNAP_COLL].insert_one(snap)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("[isabella_queue] metrics loop falha: %s", e)


# ─── Pool management ────────────────────────────────────────────
_WORKER_TASKS: list[asyncio.Task] = []
_METRICS_TASK: Optional[asyncio.Task] = None


async def start_workers() -> None:
    """Inicia pool. Pode ser chamado do server.py OU do entrypoint standalone."""
    global _METRICS_TASK
    if _WORKER_TASKS:
        logger.warning("[isabella_queue] pool já iniciado, ignorando")
        return
    await ensure_indexes()
    recovered = await recover_orphans()
    if recovered:
        logger.info("[isabella_queue] %d jobs órfãos recuperados", recovered)
    n = _pool_size()
    for i in range(n):
        t = asyncio.create_task(_worker_loop(i + 1),
                                 name=f"isabella-worker-{i+1}")
        _WORKER_TASKS.append(t)
    _METRICS_TASK = asyncio.create_task(_metrics_loop(), name="isabella-metrics")
    logger.info("[isabella_queue] pool=%d workers + 1 metrics loop iniciado", n)


async def stop_workers() -> None:
    global _METRICS_TASK
    for t in _WORKER_TASKS:
        t.cancel()
    _WORKER_TASKS.clear()
    if _METRICS_TASK:
        _METRICS_TASK.cancel()
        _METRICS_TASK = None


# ─── Telemetria (read-only) ─────────────────────────────────────
async def stats() -> Dict[str, Any]:
    pipe = [{"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    by_status = {r["_id"]: r["n"] async for r in db[QUEUE_COLL].aggregate(pipe)}
    counters = await db[METRICS_CTR_COLL].find_one(
        {"_id": COUNTER_DOC_ID}, {"_id": 0}) or {}
    return {
        "pool_size": _pool_size(),
        "by_status": by_status,
        "counters": counters,
        "ts": _now().isoformat(),
    }
