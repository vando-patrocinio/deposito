"""Helper de log para chamadas a módulos renomeados na Etapa 3.

Registra cada chamada legada em `deprecated_call_log` (uma vez por (origem,
destino) por processo) e dispara INFO no logger `ligo.deprecated_call`.

NÃO altera comportamento — apenas registra para o ranking semanal.
"""
from __future__ import annotations

import inspect
import logging
import os
import threading
from datetime import datetime, timezone

logger = logging.getLogger("ligo.deprecated_call")

_seen: set[tuple[str, str]] = set()
_lock = threading.Lock()
_DISABLED = os.environ.get("DEPRECATED_LOG_DISABLED", "false").lower() == "true"


def _caller_module() -> str:
    """Sobe ate 6 frames buscando o primeiro caller fora de services/_deprecated_logger.py."""
    try:
        frame = inspect.currentframe()
        depth = 0
        while frame is not None and depth < 8:
            mod = frame.f_globals.get("__name__", "")
            if mod and not mod.endswith("_deprecated_logger") and mod != __name__:
                return mod
            frame = frame.f_back
            depth += 1
    except Exception:
        pass
    return "unknown"


def log_deprecated(import_path_legacy: str, target_module: str,
                     symbol: str | None = None) -> None:
    """Logga chamada legada (idempotente por processo)."""
    if _DISABLED:
        return
    origem = _caller_module()
    key = (origem, import_path_legacy)
    with _lock:
        if key in _seen:
            return
        _seen.add(key)

    payload = {
        "origem": origem,
        "destino": target_module,
        "import_path_legacy": import_path_legacy,
        "symbol": symbol or "*",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    logger.info("[DEPRECATED_CALL] %s -> %s", import_path_legacy, target_module,
                extra=payload)

    # Persistência best-effort em background (não bloqueia o caller).
    try:
        import asyncio
        from database import db

        async def _persist():
            try:
                await db.deprecated_call_log.insert_one(payload)
            except Exception:
                pass

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_persist())
        except RuntimeError:
            # Nenhum loop ativo (import-time): silenciosamente ignora.
            pass
    except Exception:
        pass
