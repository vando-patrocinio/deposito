"""admin_wa_sidecar.py — CTO 13/06/2026.

Endpoint admin pra reiniciar todos os sidecars Baileys sob demanda.
Útil quando o WhatsApp trava e o cron 03:00 UTC ainda não rodou.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from core import require_role
from services.wa_sidecar_health import restart_all_sidecars

log = logging.getLogger("admin_wa_sidecar")

router = APIRouter(prefix="/api/admin/wa-sidecar", tags=["admin-wa-sidecar"])


@router.post("/restart-all")
async def admin_restart_all_sidecars(
    user: dict = Depends(require_role("administrador")),
):
    """Reinicia todos os 4 sidecars de WhatsApp Baileys.

    Restrito a `administrador` (ou super-admin). Cada chamada é auditada
    em `db.wa_sidecar_restart_log`.
    """
    log.info("[admin] %s acionou restart de todos os sidecars",
              user.get("email"))
    try:
        result = await restart_all_sidecars()
    except Exception as e:  # noqa: BLE001
        log.exception("[admin] restart-all falhou: %s", e)
        raise HTTPException(500, f"Falha ao reiniciar sidecars: {e}")

    if not result.get("ok"):
        # Não é 500 — o endpoint conseguiu chamar; alguns sidecars falharam
        # individualmente. Cliente trata pelo `success_count` < `total`.
        log.warning("[admin] restart parcial: %s/%s OK",
                       result.get("success_count"), result.get("total"))

    return result


@router.get("/status")
async def admin_sidecar_status(
    user: dict = Depends(require_role("administrador")),
):
    """Diagnóstico rápido: status atual dos 4 sidecars via /health.

    Usa `base_url_for(channel_id)` — resolve URL via env (prod) ou
    localhost (preview).
    """
    import httpx
    from services.whatsapp_channels import CHANNEL_IDS, base_url_for, CHANNEL_PORTS
    status = []
    async with httpx.AsyncClient(timeout=5.0) as cx:
        for cid in CHANNEL_IDS:
            base = base_url_for(cid)
            try:
                r = await cx.get(f"{base}/health")
                body = r.json() if r.status_code == 200 else None
                status.append({
                    "channel_id": cid,
                    "port": CHANNEL_PORTS.get(cid),
                    "base_url": base,
                    "alive": r.status_code == 200,
                    "http_status": r.status_code,
                    "state": (body or {}).get("state"),
                    "uptime_s": (body or {}).get("uptime_s"),
                    "retry_count": (body or {}).get("retry_count"),
                })
            except Exception as e:  # noqa: BLE001
                status.append({
                    "channel_id": cid,
                    "port": CHANNEL_PORTS.get(cid),
                    "base_url": base,
                    "alive": False,
                    "error": str(e)[:200],
                })
    return {"sidecars": status}
