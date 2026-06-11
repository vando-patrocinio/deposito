"""Mobile Health Events — telemetria leve do app do colaborador.

Recebe sinais do `LousaMobile.js` / `CollaboratorApp.js` quando algo
falha no carregamento (timeout, 403, 5xx do upstream). Persiste em
`mobile_health_events` pra auditoria + dashboard de saude do app.

Endpoint:
  POST /api/mobile/health-event   (auth: qualquer role logada,
                                    incluindo colaborador)

Body livre (validacao basica):
  {
    "kind": "lousa_load_failed" | "lousa_load_timeout" | "..." ,
    "collaborator_id": str,
    "status": int,
    "detail": str (<=300),
    "ua": str (<=200),
    "url": str (<=400),
    ... outros campos opcionais
  }
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "observability",
    "criticality": "low",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request

from core import DEMO_COMPANY_ID, get_current_user
from database import db

logger = logging.getLogger("ponto.mobile_health")
router = APIRouter(prefix="/api/mobile", tags=["mobile-health"])


VALID_KINDS = {
    "lousa_load_failed", "lousa_load_timeout",
    "ticket_action_failed", "clock_action_failed",
    "outbox_sync_failed", "generic",
}


@router.post("/health-event")
async def health_event(
    payload: Dict[str, Any],
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Registra evento de saude do app mobile. Best-effort, nao falha.

    Auth: qualquer user logado. Multi-tenant via user.company_id.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    kind = (payload.get("kind") or "generic").strip()[:60]
    if kind not in VALID_KINDS:
        kind = "generic"

    fwd = request.headers.get("x-forwarded-for") or ""
    client_ip = (fwd.split(",")[0].strip()
                  if fwd else (request.client.host if request.client else ""))

    doc = {
        "id": f"mhe-{uuid.uuid4().hex[:14]}",
        "company_id": cid,
        "user_id": user.get("id") or user.get("sub"),
        "user_email": user.get("email"),
        "user_role": user.get("role"),
        "collaborator_id": str(payload.get("collaborator_id") or "")[:60] or None,
        "kind": kind,
        "status": int(payload.get("status") or 0),
        "detail": str(payload.get("detail") or "")[:400],
        "ua": str(payload.get("ua") or "")[:300],
        "url": str(payload.get("url") or "")[:500],
        "ip": client_ip[:64],
        "extra": {k: v for k, v in payload.items() if k not in (
            "kind", "collaborator_id", "status", "detail", "ua", "url")},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await db.mobile_health_events.insert_one(doc)
    except Exception as e:
        logger.warning("[mobile_health] falha ao gravar: %s", e)
    # Log estruturado (cai no centralizador)
    logger.info(
        "[mobile_health] cid=%s user=%s kind=%s status=%s detail=%s",
        cid, user.get("email"), kind, doc["status"], doc["detail"][:120])
    return {"ok": True, "id": doc["id"]}
