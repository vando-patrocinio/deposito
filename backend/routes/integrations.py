"""Health-check + auto-reconnect dos canais WhatsApp.

Endpoint: GET /api/integrations/health
Endpoint: POST /api/integrations/reconnect

Verifica os 3 canais (Baileys / Twilio / Meta Cloud) e tenta religar
qualquer um que esteja morto.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Depends

from core import DEMO_COMPANY_ID, require_role
from database import db

logger = logging.getLogger("ponto.integrations")
router = APIRouter(prefix="/api/integrations", tags=["integrations"])


SIDECAR_BASE = os.environ.get("WA_SIDECAR_URL", "http://localhost:8002")


async def _check_baileys() -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=6.0) as cli:
            r = await cli.get(f"{SIDECAR_BASE}/qr")
            d = r.json() if r.status_code < 400 else {}
            connected = (d.get("status") or "").lower() == "connected"
            return {
                "channel": "baileys",
                "label": "WhatsApp Baileys (não-oficial)",
                "available": True,
                "connected": connected,
                "status": d.get("status") or "unknown",
                "needs_action": (not connected),
            }
    except Exception as e:
        return {
            "channel": "baileys",
            "label": "WhatsApp Baileys (não-oficial)",
            "available": False,
            "connected": False,
            "status": "sidecar_down",
            "error": str(e),
            "needs_action": True,
        }


async def _check_twilio(company_id: str) -> Dict[str, Any]:
    cfg = await db.whatsapp_twilio_creds.find_one(
        {"company_id": company_id}, {"_id": 0}) or {}
    enabled = bool(cfg.get("enabled"))
    has_sid = bool(cfg.get("account_sid"))
    has_token = bool(cfg.get("auth_token"))
    has_from = bool(cfg.get("from_number"))
    ready = enabled and has_sid and has_token and has_from
    return {
        "channel": "twilio",
        "label": "WhatsApp Twilio (oficial)",
        "available": ready,
        "connected": ready,
        "status": "configured" if ready else (
            "disabled" if not enabled else "missing_credentials"),
        "needs_action": not ready and enabled,
    }


async def _check_meta(company_id: str) -> Dict[str, Any]:
    cfg = await db.whatsapp_meta_creds.find_one(
        {"company_id": company_id}, {"_id": 0}) or {}
    enabled = bool(cfg.get("enabled"))
    has_token = bool(cfg.get("token") or cfg.get("access_token"))
    has_phone_id = bool(cfg.get("phone_id"))
    has_waba = bool(cfg.get("waba_id"))
    ready = enabled and has_token and has_phone_id
    return {
        "channel": "meta",
        "label": "WhatsApp Meta Cloud (oficial)",
        "available": ready,
        "connected": ready,
        "status": "configured" if ready else (
            "disabled" if not enabled else "missing_credentials"),
        "needs_action": not ready and enabled,
        "has_waba": has_waba,
    }


@router.get("/health")
async def integrations_health(user: dict = Depends(require_role("gestor"))):
    """Status de todos os canais."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    results = await asyncio.gather(
        _check_baileys(),
        _check_twilio(cid),
        _check_meta(cid),
        return_exceptions=False,
    )
    return {
        "channels": list(results),
        "any_needs_action": any(c.get("needs_action") for c in results),
        "any_connected": any(c.get("connected") for c in results),
    }


@router.post("/reconnect")
async def reconnect_dead_channels(user: dict = Depends(require_role("gestor"))):
    """Tenta religar todos os canais que estão desconectados:
    - Baileys: força regenerar QR (logout + sleep + get QR)
    - Twilio: só validação (não há "reconectar" — é API REST)
    - Meta: idem
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    actions = []

    # Baileys — sempre tenta, mesmo se sidecar parece down
    # (pode ter voltado entre health-check e reconnect)
    bail = await _check_baileys()
    if bail.get("needs_action"):
        try:
            async with httpx.AsyncClient(timeout=12.0) as cli:
                # Tenta /qr/refresh dedicado
                try:
                    r = await cli.post(f"{SIDECAR_BASE}/qr/refresh")
                    if r.status_code >= 400:
                        raise Exception(f"refresh HTTP {r.status_code}")
                except Exception:
                    # Fallback: logout
                    try:
                        await cli.post(f"{SIDECAR_BASE}/logout")
                    except Exception:
                        pass
            await asyncio.sleep(1.2)
            new_state = await _check_baileys()
            actions.append({
                "channel": "baileys",
                "action": "regenerated_qr",
                "result": "ok" if new_state.get("available") else "sidecar_unreachable",
                "new_status": new_state.get("status"),
            })
        except Exception as e:
            actions.append({
                "channel": "baileys", "action": "regenerate_qr",
                "result": "error", "error": str(e),
            })

    # Twilio + Meta — só re-validar
    tw = await _check_twilio(cid)
    if tw.get("needs_action"):
        actions.append({"channel": "twilio", "action": "validate",
                          "result": tw.get("status")})
    mt = await _check_meta(cid)
    if mt.get("needs_action"):
        actions.append({"channel": "meta", "action": "validate",
                          "result": mt.get("status")})

    return {"actions": actions, "checked_at_seconds": 0}
