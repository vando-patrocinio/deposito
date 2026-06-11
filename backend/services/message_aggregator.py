"""MESSAGE AGGREGATOR — debounce inbound burst em WhatsApp.

Quando o cliente envia múltiplas bolhas em rajada ("Oi", "Bom dia",
"Tudo bem?"), Isabella deve OUVIR todas antes de responder. Sem
debounce, ela responde 3 vezes ou ignora as 2 primeiras.

Mecânica:
  • Toda mensagem inbound vira um doc em `wa_aggregate_buffer`
    com `last_at` atualizado.
  • Worker chama `pop_ready(phone)` que só retorna se o silêncio
    do cliente já ultrapassou `WA_AGGREGATE_WINDOW_S` (default 6s).
  • Retorna lista de textos + ids; consumidor faz join.
  • Idempotente: se ninguém processar, a próxima chamada retorna o
    buffer completo.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db

log = logging.getLogger("ponto.aggregator")
COLL = "wa_aggregate_buffer"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _window_s() -> float:
    try:
        return float(os.environ.get("WA_AGGREGATE_WINDOW_S", "6"))
    except ValueError:
        return 6.0


def _max_burst() -> int:
    try:
        return int(os.environ.get("WA_AGGREGATE_MAX_MSGS", "10"))
    except ValueError:
        return 10


async def ensure_indexes() -> None:
    try:
        await db[COLL].create_index([("company_id", 1), ("phone", 1)],
                                       unique=True)
        await db[COLL].create_index("last_at")
        # TTL 1h — buffers antigos esquecidos são removidos
        await db[COLL].create_index("last_at", expireAfterSeconds=3600,
                                       name="agg_ttl")
    except Exception as e:
        log.warning("[agg] indexes: %s", e)


async def push(*, company_id: str, phone: str, message_sid: str,
                 text: str) -> Dict[str, Any]:
    """Adiciona msg ao buffer. Retorna doc atualizado."""
    now = _now()
    entry = {"sid": message_sid, "text": text[:1000], "at": now}
    doc = await db[COLL].find_one_and_update(
        {"company_id": company_id, "phone": phone},
        {
            "$push": {"messages": {"$each": [entry],
                                       "$slice": -_max_burst()}},
            "$set": {"last_at": now, "company_id": company_id,
                      "phone": phone},
            "$setOnInsert": {"first_at": now,
                              "id": f"agg-{uuid.uuid4().hex[:10]}"},
        },
        upsert=True,
        return_document=True)  # ReturnDocument.AFTER
    return doc


async def pop_ready(*, company_id: str, phone: str) -> Optional[Dict[str, Any]]:
    """Se o silêncio passou da janela, remove buffer e retorna textos.

    Retorna None se ainda há atividade recente (ainda ouvindo).
    Atomic via find_one_and_delete com filtro de timestamp.
    """
    cutoff = _now() - timedelta(seconds=_window_s())
    doc = await db[COLL].find_one_and_delete(
        {"company_id": company_id, "phone": phone,
         "last_at": {"$lte": cutoff}})
    if not doc:
        return None
    msgs = doc.get("messages") or []
    return {
        "id": doc.get("id"),
        "phone": phone,
        "company_id": company_id,
        "messages": msgs,
        "count": len(msgs),
        "first_at": doc.get("first_at"),
        "last_at": doc.get("last_at"),
        "joined_text": _join_messages([m["text"] for m in msgs]),
    }


async def peek(*, company_id: str, phone: str) -> Optional[Dict[str, Any]]:
    """Vê o estado atual sem remover. Útil pra debug."""
    return await db[COLL].find_one(
        {"company_id": company_id, "phone": phone}, {"_id": 0})


def _join_messages(texts: List[str]) -> str:
    """Junta múltiplas bolhas inbound em um único user_text coerente."""
    if not texts:
        return ""
    if len(texts) == 1:
        return texts[0].strip()
    # Remove duplicatas consecutivas ("oi"/"oi"/"oi" → "oi")
    deduped: List[str] = []
    for t in texts:
        t = (t or "").strip()
        if not t:
            continue
        if deduped and deduped[-1].lower() == t.lower():
            continue
        deduped.append(t)
    if len(deduped) == 1:
        return deduped[0]
    return " | ".join(deduped)


async def wait_for_quiet_window(*, company_id: str, phone: str,
                                    max_wait_s: float = 12.0) -> Optional[Dict[str, Any]]:
    """Espera ativa até pop_ready retornar (cliente ficou em silêncio).

    Útil pro worker chamar logo após enfileirar — ele dorme em chunks
    de 1s e checa se o cliente ficou quieto.
    """
    elapsed = 0.0
    step = min(1.0, _window_s() / 2.0)
    while elapsed <= max_wait_s:
        ready = await pop_ready(company_id=company_id, phone=phone)
        if ready:
            return ready
        await asyncio.sleep(step)
        elapsed += step
    # Timeout — força pop mesmo sem janela completa
    doc = await db[COLL].find_one_and_delete(
        {"company_id": company_id, "phone": phone})
    if not doc:
        return None
    msgs = doc.get("messages") or []
    return {
        "id": doc.get("id"),
        "phone": phone,
        "company_id": company_id,
        "messages": msgs,
        "count": len(msgs),
        "first_at": doc.get("first_at"),
        "last_at": doc.get("last_at"),
        "joined_text": _join_messages([m["text"] for m in msgs]),
        "forced": True,
    }
