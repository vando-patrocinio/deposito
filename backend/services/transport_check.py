"""
transport_check.py — Sprint Final V5.0
Audita disponibilidade real do canal WhatsApp em produção.
Decide se ação financeira pode ser executada ou deve ser marcada
como `blocked_transport` (sem culpa da IA).
"""
from __future__ import annotations
import os
import httpx
from datetime import datetime, timezone
from typing import Any, Dict

from database import db


async def wa_status(company_id: str) -> Dict[str, Any]:
    """Status do canal WhatsApp por empresa."""
    has_token = bool(os.environ.get("WA_SIDECAR_TOKEN"))
    has_url = bool(os.environ.get("BAILEYS_SIDECAR_URL"))
    has_phone = bool(os.environ.get("PRESIDENTE_IA_GESTOR_PHONE"))
    session = await db.wa_baileys_sessions.find_one(
        {"company_id": company_id})

    session_status = session.get("status") if session else None
    is_open = session_status == "open"

    # Probe HTTP no sidecar (se URL existe)
    sidecar_reachable = False
    sidecar_err = None
    url = os.environ.get("BAILEYS_SIDECAR_URL")
    if url:
        try:
            async with httpx.AsyncClient(timeout=3.0) as cli:
                r = await cli.get(f"{url}/health")
                sidecar_reachable = r.status_code == 200
        except Exception as e:  # noqa: BLE001
            sidecar_err = str(e)[:120]

    checks = {
        "WA_SIDECAR_TOKEN":         has_token,
        "BAILEYS_SIDECAR_URL":      has_url,
        "PRESIDENTE_IA_GESTOR_PHONE": has_phone,
        "session_status_open":      is_open,
        "sidecar_reachable":        sidecar_reachable,
    }
    blockers = [k for k, v in checks.items() if not v]
    can_send = len(blockers) == 0
    return {
        "company_id":        company_id,
        "checked_at":        datetime.now(timezone.utc).isoformat(),
        "can_send":          can_send,
        "session_status":    session_status,
        "sidecar_error":     sidecar_err,
        "checks":            checks,
        "blockers":          blockers,
        "status":            "OPEN" if can_send else "BLOCKED_TRANSPORT",
    }


async def is_wa_open(company_id: str) -> bool:
    s = await wa_status(company_id)
    return s["can_send"]
