"""WA Reply Scheduler — fila persistente de debounce para WhatsApp Baileys.

PROBLEMA RESOLVIDO (P0 — 12-16 min de delay):
    O fluxo Baileys usava `asyncio.create_task` + dict in-memory
    (`_pending_tasks`) para debounce. A cada restart do backend (hot reload,
    deploy, ou crash), as tasks pendentes morriam silenciosamente e o
    cliente NUNCA recebia a resposta — até reenviar uma mensagem.

SOLUÇÃO:
    Persistência completa em MongoDB:
    - `wa_reply_pending`: 1 doc por (company_id, phone) com `debounce_until`.
    - Worker assíncrono polla a cada 500ms; processa quem chegou no prazo.
    - Restart do backend ⇒ na próxima inicialização o worker volta a
      processar TODOS os pending órfãos.
    - Métricas obrigatórias por request: `received_at`, `released_at`,
      `llm_start_at`, `llm_finish_at`, `send_start_at`, `send_finish_at`.

INSTRUMENTAÇÃO:
    Cada ciclo grava em `wa_reply_latency` (collection separada) os
    timestamps brutos + deltas. Permite enxergar exatamente onde
    se perde tempo (aggregator vs LLM vs Twilio/sidecar).
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "isabella",
    "criticality": "critical",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from database import db

logger = logging.getLogger("ponto.wa_reply_scheduler")

PENDING_COLL = "wa_reply_pending"
LATENCY_COLL = "wa_reply_latency"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _debounce_s() -> float:
    try:
        return max(0.5, float(os.environ.get("WA_REPLY_DEBOUNCE_S") or 2.0))
    except (TypeError, ValueError):
        return 2.0


def _poll_ms() -> int:
    try:
        return max(100, int(os.environ.get("WA_REPLY_POLL_MS") or 500))
    except (TypeError, ValueError):
        return 500


def _lock_ttl_s() -> int:
    try:
        return max(30, int(os.environ.get("WA_REPLY_LOCK_TTL_S") or 60))
    except (TypeError, ValueError):
        return 60


# ─── Indexes ────────────────────────────────────────────────────
async def ensure_indexes() -> None:
    try:
        await db[PENDING_COLL].create_index(
            [("company_id", 1), ("phone", 1)],
            unique=True, name="cid_phone_uq",
        )
        await db[PENDING_COLL].create_index(
            [("status", 1), ("debounce_until", 1)],
            name="status_due_idx",
        )
        # TTL: docs órfãos +1h após `received_at` são limpos
        await db[PENDING_COLL].create_index(
            "received_at", expireAfterSeconds=3600, name="pending_ttl",
        )
        # Latência: keep 30d
        await db[LATENCY_COLL].create_index(
            "created_at", expireAfterSeconds=30 * 86400, name="lat_ttl",
        )
        await db[LATENCY_COLL].create_index(
            [("company_id", 1), ("created_at", -1)], name="cid_ts_idx",
        )
    except Exception as e:
        logger.warning("[wa_reply_sched] indexes: %s", e)


# ─── Schedule (called by webhook) ───────────────────────────────
async def schedule(
    *,
    company_id: str,
    phone: str,
    user_text: str,
    subscriber_id: Optional[str],
    subscriber_ctx: Optional[str],
    inbound_was_voice: bool = False,
) -> Dict[str, Any]:
    """Agenda (ou re-agenda) uma resposta com debounce persistente.

    Cada chamada estende `debounce_until` em DEBOUNCE_S a partir de agora.
    Se o cliente seguir enviando msgs, o debounce continua deslizando.

    O texto é OVERWRITTEN com o último (mais recente) — o
    `_maybe_auto_reply` lê histórico do MongoDB então pega contexto completo.
    """
    now = _now()
    debounce_until = now + timedelta(seconds=_debounce_s())
    set_fields: Dict[str, Any] = {
        "company_id": company_id,
        "phone": phone,
        "user_text": (user_text or "")[:4000],
        "subscriber_id": subscriber_id,
        "subscriber_ctx": (subscriber_ctx or "")[:6000] or None,
        "inbound_was_voice": bool(inbound_was_voice),
        "debounce_until": debounce_until,
        "last_msg_at": now,
        "status": "pending",
        "locked_until": None,
    }
    set_on_insert: Dict[str, Any] = {
        "_id": f"wrp-{uuid.uuid4().hex[:12]}",
        "received_at": now,  # PRIMEIRA mensagem da janela
        "attempts": 0,
        "metrics": {},
    }
    doc = await db[PENDING_COLL].find_one_and_update(
        {"company_id": company_id, "phone": phone},
        {"$set": set_fields, "$setOnInsert": set_on_insert,
         "$inc": {"msg_count": 1}},
        upsert=True,
        return_document=True,  # AFTER
    )
    return doc


# ─── Worker ─────────────────────────────────────────────────────
_WORKER_TASK: Optional[asyncio.Task] = None
_HANDLER: Optional[Callable[..., Awaitable[Optional[str]]]] = None


def register_handler(
    fn: Callable[..., Awaitable[Optional[str]]],
) -> None:
    """Define o handler real que efetua o auto-reply (injetado pelo router
    para evitar import circular)."""
    global _HANDLER
    _HANDLER = fn


async def _claim_one() -> Optional[Dict[str, Any]]:
    """Tenta reservar 1 doc pronto para processar (atomic find_one_and_update)."""
    now = _now()
    lock_until = now + timedelta(seconds=_lock_ttl_s())
    doc = await db[PENDING_COLL].find_one_and_update(
        {
            "status": "pending",
            "debounce_until": {"$lte": now},
            "$or": [{"locked_until": None},
                     {"locked_until": {"$lte": now}}],
        },
        {"$set": {"status": "processing",
                   "locked_until": lock_until,
                   "picked_at": now},
         "$inc": {"attempts": 1}},
        sort=[("debounce_until", 1)],
        return_document=True,
    )
    return doc


async def _record_latency(doc: Dict[str, Any], metrics: Dict[str, Any],
                              outcome: str) -> None:
    try:
        rec = {
            "_id": f"wrl-{uuid.uuid4().hex[:12]}",
            "company_id": doc.get("company_id"),
            "phone": doc.get("phone"),
            "subscriber_id": doc.get("subscriber_id"),
            "msg_count": doc.get("msg_count", 1),
            "received_at": doc.get("received_at"),
            "outcome": outcome,
            "attempts": doc.get("attempts", 1),
            "metrics": metrics,
            "deltas_ms": _compute_deltas(metrics),
            "created_at": _now(),
        }
        await db[LATENCY_COLL].insert_one(rec)
    except Exception as e:
        logger.warning("[wa_reply_sched] record_latency: %s", e)


def _ms(a: Optional[datetime], b: Optional[datetime]) -> Optional[int]:
    if not a or not b:
        return None
    try:
        # Normaliza tzinfo: Motor pode devolver datetime naive (UTC)
        if a.tzinfo is None:
            a = a.replace(tzinfo=timezone.utc)
        if b.tzinfo is None:
            b = b.replace(tzinfo=timezone.utc)
        return int((b - a).total_seconds() * 1000)
    except Exception:
        return None


def _compute_deltas(m: Dict[str, Any]) -> Dict[str, Optional[int]]:
    """Calcula deltas em ms para observar onde se perde tempo."""
    rcv = m.get("received_at")
    rel = m.get("released_at")
    lst = m.get("llm_start_at")
    lfn = m.get("llm_finish_at")
    sst = m.get("send_start_at")
    sfn = m.get("send_finish_at")
    return {
        "received_to_released_ms": _ms(rcv, rel),
        "released_to_llm_start_ms": _ms(rel, lst),
        "llm_duration_ms": _ms(lst, lfn),
        "llm_to_send_start_ms": _ms(lfn, sst),
        "send_duration_ms": _ms(sst, sfn),
        "total_ms": _ms(rcv, sfn),
    }


async def _process_doc(doc: Dict[str, Any]) -> None:
    """Executa o handler real (auto-reply Isabella) com instrumentação."""
    if _HANDLER is None:
        logger.error("[wa_reply_sched] HANDLER não registrado — devolve doc")
        await db[PENDING_COLL].update_one(
            {"_id": doc["_id"]},
            {"$set": {"status": "pending", "locked_until": None,
                       "debounce_until": _now() + timedelta(seconds=1)}},
        )
        return
    metrics: Dict[str, Any] = {
        "received_at": doc.get("received_at"),
        "released_at": _now(),
    }
    outcome = "ok"
    try:
        metrics["llm_start_at"] = _now()
        try:
            await _HANDLER(
                cid=doc["company_id"],
                phone=doc["phone"],
                user_text=doc.get("user_text") or "",
                subscriber_id=doc.get("subscriber_id"),
                subscriber_ctx=doc.get("subscriber_ctx"),
                inbound_was_voice=bool(doc.get("inbound_was_voice")),
                metrics=metrics,  # handler preenche llm_finish_at, send_*
            )
            metrics.setdefault("llm_finish_at", _now())
            metrics.setdefault("send_finish_at", _now())
        except Exception as e:
            outcome = "handler_error"
            metrics["error"] = repr(e)[:300]
            logger.warning(
                "[wa_reply_sched] handler error phone=%s: %s",
                doc.get("phone"), e,
            )
        # Sucesso: remove o doc
        await db[PENDING_COLL].delete_one({"_id": doc["_id"]})
    except Exception as e:
        logger.exception("[wa_reply_sched] processo crash: %s", e)
        outcome = "crash"
        # Re-queue se attempts < 3
        attempts = doc.get("attempts", 1)
        if attempts < 3:
            await db[PENDING_COLL].update_one(
                {"_id": doc["_id"]},
                {"$set": {"status": "pending", "locked_until": None,
                           "debounce_until": _now() + timedelta(seconds=5)}},
            )
        else:
            await db[PENDING_COLL].delete_one({"_id": doc["_id"]})
    finally:
        await _record_latency(doc, metrics, outcome)


async def _worker_loop() -> None:
    """Loop principal. Resiste a restart, processa órfãos automaticamente."""
    poll_s = _poll_ms() / 1000.0
    logger.info("[wa_reply_sched] worker online (poll=%dms, debounce=%.1fs)",
                 _poll_ms(), _debounce_s())
    # Garante que docs em "processing" travados são liberados na partida
    try:
        cutoff = _now() - timedelta(seconds=_lock_ttl_s())
        res = await db[PENDING_COLL].update_many(
            {"status": "processing", "locked_until": {"$lte": cutoff}},
            {"$set": {"status": "pending", "locked_until": None}},
        )
        if res.modified_count:
            logger.info(
                "[wa_reply_sched] %d docs órfãos recuperados na partida",
                res.modified_count,
            )
    except Exception as e:
        logger.warning("[wa_reply_sched] recovery: %s", e)

    while True:
        try:
            doc = await _claim_one()
            if not doc:
                await asyncio.sleep(poll_s)
                continue
            # Processa em background — não bloqueia o loop pra próximo claim
            asyncio.create_task(_process_doc(doc))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("[wa_reply_sched] loop error: %s", e)
            await asyncio.sleep(1.0)


async def start_worker() -> None:
    global _WORKER_TASK
    if _WORKER_TASK and not _WORKER_TASK.done():
        return
    await ensure_indexes()
    _WORKER_TASK = asyncio.create_task(_worker_loop(), name="wa-reply-sched")


async def stop_worker() -> None:
    global _WORKER_TASK
    if _WORKER_TASK:
        _WORKER_TASK.cancel()
        _WORKER_TASK = None


# ─── Telemetria pública ─────────────────────────────────────────
async def latency_stats(*, company_id: Optional[str] = None,
                              hours: int = 24) -> Dict[str, Any]:
    """Estatísticas p50/p95/p99 dos últimos N horas para o painel."""
    cutoff = _now() - timedelta(hours=hours)
    match: Dict[str, Any] = {"created_at": {"$gte": cutoff}}
    if company_id:
        match["company_id"] = company_id
    pipeline = [
        {"$match": match},
        {"$group": {"_id": None,
                      "samples": {"$sum": 1},
                      "totals": {"$push": "$deltas_ms.total_ms"},
                      "llm": {"$push": "$deltas_ms.llm_duration_ms"},
                      "send": {"$push": "$deltas_ms.send_duration_ms"}}},
    ]
    row = await db[LATENCY_COLL].aggregate(pipeline).to_list(1)
    if not row:
        return {"samples": 0}
    r = row[0]

    def _pct(arr, p):
        arr = sorted(x for x in (arr or []) if isinstance(x, (int, float)))
        if not arr:
            return None
        i = max(0, min(len(arr) - 1, int(round(p * (len(arr) - 1)))))
        return arr[i]

    return {
        "samples": r.get("samples", 0),
        "total_ms": {
            "p50": _pct(r["totals"], 0.5),
            "p95": _pct(r["totals"], 0.95),
            "p99": _pct(r["totals"], 0.99),
        },
        "llm_ms": {
            "p50": _pct(r["llm"], 0.5),
            "p95": _pct(r["llm"], 0.95),
        },
        "send_ms": {
            "p50": _pct(r["send"], 0.5),
            "p95": _pct(r["send"], 0.95),
        },
    }
