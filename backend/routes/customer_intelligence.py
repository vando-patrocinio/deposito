"""Customer Intelligence — endpoint público (auth-gated).

Feature flag: CUSTOMER_INTELLIGENCE_ENABLED.
Quando false, retorna 503 explícito.
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "universo_ligo",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import time
from fastapi import APIRouter, Depends, HTTPException

from core import get_current_user
from services import customer_intelligence as ci

log = logging.getLogger("ponto.routes.customer_intelligence")
router = APIRouter(prefix="/api/customer-intelligence",
                   tags=["customer_intelligence"])


@router.get("/{subscriber_id}")
async def get_intelligence(subscriber_id: str,
                           user: dict = Depends(get_current_user)):
    if not ci.FF_ENABLED:
        raise HTTPException(503, "customer_intelligence disabled (feature flag off)")
    started = time.time()
    payload = await ci.build_intelligence(subscriber_id)
    elapsed_ms = int((time.time() - started) * 1000)
    if isinstance(payload, dict) and payload.get("error"):
        if payload["error"] == "subscriber_not_found":
            raise HTTPException(404, "subscriber not found")
        if payload["error"] == "synthetic_tenant_blocked":
            raise HTTPException(403, "synthetic tenant blocked")
    payload["_meta"] = {"elapsed_ms": elapsed_ms}
    return payload


@router.post("/{subscriber_id}/invalidate")
async def invalidate(subscriber_id: str,
                     user: dict = Depends(get_current_user)):
    """Invalida cache do subscriber (chamado por hooks de evento ou admin)."""
    role = (user.get("role") or "").lower()
    if role not in ("administrador", "auditor", "diretor"):
        raise HTTPException(403, "admin only")
    ci.invalidate(subscriber_id)
    return {"ok": True, "subscriber_id": subscriber_id}
