"""lousa_finalize_trace — Onda B Bug #3 instrumentação.

Captura 6 fases do `public_finalize_ticket` em `lousa.py` para
identificar EXATAMENTE onde o flow quebra quando o stok_service não é
fechado.

Política CEO (18/06/2026):
  • NÃO usar try/except silencioso.
  • Cada fase grava em `lousa_finalize_trace` com timestamp + payload.
  • Trace é descartado após 7 dias (TTL).
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from database import db

logger = logging.getLogger("ponto.lousa_finalize_trace")

TRACE_COLL = "lousa_finalize_trace"

# Fases definidas pela auditoria (ordem importa):
PHASE_ENTRY = "01_entry"                    # request chegou no handler
PHASE_GUARDRAIL_DECISION = "02_guardrail"   # guardrail rodou ou foi skipado
PHASE_TICKET_UPDATED = "03_ticket_updated"  # tickets.update_one feito
PHASE_PRE_AUTO_CLOSE = "04_pre_auto_close"  # antes de chamar auto_close
PHASE_POST_AUTO_CLOSE = "05_post_auto_close"  # depois (com result)
PHASE_EXIT = "06_exit"                       # antes do return final


async def trace_phase(
    *,
    ticket_id: str,
    company_id: str,
    phase: str,
    outcome: str = "ok",
    details: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> None:
    """Registra uma fase do flow. NÃO usa try/except silencioso — se o
    insert falhar, raise para a stack chamadora detectar."""
    doc = {
        "ticket_id": ticket_id,
        "company_id": company_id,
        "phase": phase,
        "outcome": outcome,
        "details": details or {},
        "error": error,
        "ts": datetime.now(timezone.utc),
    }
    # NÃO captura exceções silenciosamente — CEO 18/06/2026
    await db[TRACE_COLL].insert_one(doc)


async def get_trace(ticket_id: str) -> list:
    """Retorna o trace ordenado de um ticket."""
    return [d async for d in
            db[TRACE_COLL].find({"ticket_id": ticket_id}, {"_id": 0})
                                    .sort("ts", 1)]


async def ensure_indexes() -> None:
    """Index pra busca + TTL de 7 dias (auto-purge)."""
    await db[TRACE_COLL].create_index(
        [("ticket_id", 1), ("ts", 1)], name="ticket_ts")
    await db[TRACE_COLL].create_index(
        [("company_id", 1), ("phase", 1), ("ts", -1)],
        name="company_phase")
    # TTL: descarta após 7 dias (604800s)
    try:
        await db[TRACE_COLL].create_index(
            "ts", expireAfterSeconds=604800, name="ts_ttl")
    except Exception as e:
        logger.info("[trace] TTL index já existe: %s", e)
