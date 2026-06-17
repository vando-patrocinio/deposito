"""Routes para inspeção e disparo manual do WA Sidecar Watchdog.

Rotas:
    GET  /api/whatsapp-baileys/watchdog/status
        Snapshot do estado de cada sidecar + últimos eventos de
        recovery (do collection `wa_sidecar_watchdog_state` e
        `wa_sidecar_watchdog_events`).

    POST /api/whatsapp-baileys/watchdog/tick
        Dispara 1 ciclo manualmente (não espera scheduler). Útil para
        forçar reenvio assim que o usuário scaneou o QR. Resposta inclui
        o resumo retornado por `wa_sidecar_watchdog.tick()`.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends

from core import require_role
from services import wa_sidecar_watchdog

logger = logging.getLogger("wa.watchdog.routes")
router = APIRouter(prefix="/api/whatsapp-baileys/sidecar-watchdog",
                   tags=["wa-baileys-sidecar-watchdog"])


@router.get("/status")
async def watchdog_status(
    user: dict = Depends(require_role("gestor", "administrador",
                                       "auditor")),
) -> Dict[str, Any]:
    return await wa_sidecar_watchdog.status()


@router.post("/tick")
async def watchdog_tick(
    user: dict = Depends(require_role("gestor", "administrador")),
) -> Dict[str, Any]:
    """Dispara 1 ciclo manualmente. Útil pós-scan QR."""
    logger.info("[watchdog.routes] manual tick by user=%s",
                user.get("email") or user.get("id"))
    return await wa_sidecar_watchdog.tick()
