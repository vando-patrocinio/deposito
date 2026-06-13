"""wa_sidecar_health.py — CTO 13/06/2026 (v2).

Gestão proativa dos sidecars Baileys.

v2 (13/06/2026) — Atualizado para ARQUITETURA DUAL:
  - PREVIEW: sidecars rodam no MESMO container (supervisor, localhost:3002-3005)
  - PRODUÇÃO: sidecars rodam em containers SEPARADOS (Railway/Render/Fly.io),
    URLs resolvidas via env vars WA_SIDECAR_URL_CH1..CH4.

Estratégias:
  - PREVIEW: chama `POST /reload` no sidecar (mantém sessão, reconecta socket)
  - PRODUÇÃO: chama `POST /reload` no sidecar via URL externa (idem)

Vantagem: o endpoint `/reload` do sidecar funciona em AMBOS os ambientes,
sem precisar SSH ou Railway API.

Fallback: se `/reload` falhar (sidecar totalmente down), o supervisor (preview)
ou a plataforma (prod, via HEALTHCHECK do Dockerfile) auto-restarta.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List

import httpx

from services.whatsapp_channels import CHANNEL_IDS, base_url_for

log = logging.getLogger("wa_sidecar_health")


async def _reload_one(channel_id: str) -> Dict:
    """Chama `POST /reload` no sidecar de um canal."""
    base = base_url_for(channel_id)
    started = datetime.now(timezone.utc).isoformat()
    try:
        async with httpx.AsyncClient(timeout=15.0) as cx:
            r = await cx.post(f"{base}/reload")
            body = r.json() if r.headers.get("content-type", "").startswith(
                "application/json"
            ) else {"raw": r.text[:200]}
            return {
                "channel_id": channel_id,
                "base_url": base,
                "http_status": r.status_code,
                "ok": r.status_code == 200 and (body.get("ok") is True),
                "response": body,
                "started_at": started,
            }
    except httpx.RequestError as e:
        return {
            "channel_id": channel_id,
            "base_url": base,
            "http_status": None,
            "ok": False,
            "error": f"network: {str(e)[:200]}",
            "started_at": started,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "channel_id": channel_id,
            "base_url": base,
            "http_status": None,
            "ok": False,
            "error": str(e)[:200],
            "started_at": started,
        }


async def restart_all_sidecars() -> Dict:
    """Reinicia os 4 sidecars Baileys via /reload (in-process reconnect).

    Usado pelo cron diário (03:00 UTC) e pelo endpoint admin manual.
    Funciona tanto no preview (localhost) quanto em produção (Railway/Render).
    """
    started = datetime.now(timezone.utc).isoformat()
    log.info("[wa-sidecar-health] restart_all_sidecars iniciando (%d canais)",
              len(CHANNEL_IDS))

    # paraleliza pra não bloquear (4 sidecars, cada um 1-3s)
    tasks = [_reload_one(cid) for cid in CHANNEL_IDS]
    results: List[Dict] = await asyncio.gather(*tasks)

    success_count = sum(1 for r in results if r.get("ok"))
    finished = datetime.now(timezone.utc).isoformat()
    log.info("[wa-sidecar-health] restart_all_sidecars done: %d/%d OK",
              success_count, len(results))

    # Audit log
    try:
        from database import db
        await db.wa_sidecar_restart_log.insert_one({
            "started_at": started,
            "finished_at": finished,
            "success_count": success_count,
            "total": len(results),
            "results": results,
        })
    except Exception as e:  # noqa: BLE001
        log.warning("[wa-sidecar-health] audit log falhou: %s", e)

    return {
        "ok": success_count == len(results),
        "success_count": success_count,
        "total": len(results),
        "started_at": started,
        "finished_at": finished,
        "results": results,
    }


async def scheduled_daily_restart() -> None:
    """Job APScheduler — invocado todo dia às 03:00 UTC.

    Faz restart preventivo dos sidecars Baileys. Roda em UM worker (leader).
    """
    try:
        from services.scheduler_lock import is_leader
        if not await is_leader():
            return
    except Exception:
        pass

    log.info("[wa-sidecar-health] cron diário 03:00 UTC — executando")
    try:
        await restart_all_sidecars()
    except Exception as e:  # noqa: BLE001
        log.exception("[wa-sidecar-health] scheduled restart falhou: %s", e)
