"""wa_sidecar_health.py — CTO 13/06/2026.

Gestão proativa dos sidecars Baileys (whatsapp-service / -2 / -3 / -4).

Motivo: o WhatsApp Baileys frequentemente acumula memory leak / sessão
corrompida após 24h+ rodando, levando a um loop "connecting" sem
estabilizar. O supervisor tenta autorestart mas, depois de N falhas,
desiste e os 4 sidecars ficam down até intervenção manual.

Este módulo:
  1) Restart proativo diário às 03:00 UTC (fora do horário comercial BR)
  2) Endpoint admin manual: POST /api/admin/wa-sidecar/restart-all
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
from datetime import datetime, timezone
from typing import Dict, List

log = logging.getLogger("wa_sidecar_health")

SIDECAR_SUPERVISOR_PROGRAMS: List[str] = [
    "whatsapp-service",
    "whatsapp-service-2",
    "whatsapp-service-3",
    "whatsapp-service-4",
]


async def _run_supervisorctl(action: str, program: str) -> Dict[str, str]:
    """Executa `supervisorctl <action> <program>` async."""
    cmd = ["sudo", "-n", "supervisorctl", action, program]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        ok = proc.returncode == 0
        return {
            "program": program,
            "action": action,
            "ok": ok,
            "exit_code": proc.returncode,
            "stdout": stdout.decode(errors="ignore")[:500],
            "stderr": stderr.decode(errors="ignore")[:500],
        }
    except asyncio.TimeoutError:
        return {
            "program": program,
            "action": action,
            "ok": False,
            "exit_code": -1,
            "stderr": "timeout after 30s",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "program": program,
            "action": action,
            "ok": False,
            "exit_code": -1,
            "stderr": str(e)[:500],
        }


async def restart_all_sidecars() -> Dict:
    """Reinicia os 4 sidecars Baileys via supervisorctl. Retorna o resumo.

    Usado pelo cron diário (03:00 UTC) e pelo endpoint admin manual.
    """
    started = datetime.now(timezone.utc).isoformat()
    log.info("[wa-sidecar-health] restart_all_sidecars iniciando")
    results: List[Dict] = []
    for prog in SIDECAR_SUPERVISOR_PROGRAMS:
        r = await _run_supervisorctl("restart", prog)
        results.append(r)
        log.info(
            "[wa-sidecar-health] restart %s ok=%s exit=%s",
            prog, r.get("ok"), r.get("exit_code"),
        )

    success_count = sum(1 for r in results if r.get("ok"))
    finished = datetime.now(timezone.utc).isoformat()

    # Audit log Mongo (best-effort)
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
        # Só o leader executa
        from services.scheduler_lock import is_leader
        if not await is_leader():
            return
    except Exception:
        # Se módulo de leader não estiver disponível, executa mesmo assim
        pass

    log.info("[wa-sidecar-health] cron diário 03:00 UTC — executando")
    try:
        await restart_all_sidecars()
    except Exception as e:  # noqa: BLE001
        log.exception("[wa-sidecar-health] scheduled restart falhou: %s", e)
