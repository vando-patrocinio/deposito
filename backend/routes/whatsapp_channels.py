"""REST endpoints for managing the 4 WhatsApp channels (multi-number).

Cada empresa pode ter até 4 sidecars Baileys conectados simultaneamente.
A UI usa estes endpoints pra listar, renomear, gerar QR, escolher número
padrão de outbound, ver status e desconectar cada canal individualmente.

Os endpoints `/channels/{id}/qr|status|send|logout` são proxies finos pro
sidecar correspondente — selecionando a porta via `whatsapp_channels.base_url_for`.
Mantemos os endpoints legacy `/api/whatsapp-baileys/*` apontando pro canal-1
pra não quebrar fluxos que ainda não passam `channel_id`.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "whatsapp",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, require_role
from database import db
from services.wa.sidecar import SIDECAR_TOKEN, _sidecar_headers
from services.whatsapp_channels import (
    CHANNEL_IDS,
    base_url_for,
    get_channel,
    list_channels,
    rename_channel,
    set_default_outbound,
    update_channel_runtime,
)

logger = logging.getLogger("ponto.wa_channels")
router = APIRouter(prefix="/api/whatsapp-channels", tags=["whatsapp-channels"])


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class ChannelRenamePayload(BaseModel):
    channel_name: str = Field(..., min_length=1, max_length=40)


class ChannelSendPayload(BaseModel):
    phone: str
    text: str


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _validate_channel_id(channel_id: str) -> None:
    if channel_id not in CHANNEL_IDS:
        raise HTTPException(400, f"channel_id inválido. Use um de: {CHANNEL_IDS}")


async def _proxy_get(channel_id: str, path: str) -> dict:
    url = base_url_for(channel_id) + path
    async with httpx.AsyncClient(timeout=15.0) as cli:
        r = await cli.get(url, headers=_sidecar_headers())
        r.raise_for_status()
        return r.json()


async def _proxy_post(channel_id: str, path: str, payload: dict) -> dict:
    url = base_url_for(channel_id) + path
    async with httpx.AsyncClient(timeout=20.0) as cli:
        r = await cli.post(url, json=payload, headers=_sidecar_headers())
        r.raise_for_status()
        return r.json() if r.content else {"ok": True}


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.get("")
async def list_all_channels(user=Depends(require_role(
    "administrador", "gestor", "auditor",
))):
    """Lista os 4 canais com status atualizado em paralelo (live polling)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    channels = await list_channels(db, cid)

    # Faz status check paralelo em todos os sidecars
    async def _fetch_status(ch: dict) -> dict:
        ch = dict(ch)
        try:
            url = base_url_for(ch["id"]) + "/status"
            async with httpx.AsyncClient(timeout=4.0) as cli:
                r = await cli.get(url, headers=_sidecar_headers())
                if r.status_code == 200:
                    sd = r.json() or {}
                    ch["live_state"] = sd.get("state")
                    ch["live_connected"] = bool(sd.get("connected"))
                    me_obj = sd.get("me") or {}
                    me_id = (me_obj.get("id") or "").split(":")[0]
                    if me_id:
                        ch["phone_number"] = me_id
                        await update_channel_runtime(
                            db, cid, ch["id"],
                            phone_number=me_id, status=sd.get("state"),
                        )
                    else:
                        await update_channel_runtime(
                            db, cid, ch["id"], status=sd.get("state"),
                        )
        except Exception as e:
            ch["live_state"] = "unreachable"
            ch["live_connected"] = False
            ch["live_error"] = str(e)[:120]
        return ch

    import asyncio
    enriched = await asyncio.gather(*[_fetch_status(c) for c in channels])
    return {"channels": enriched}


@router.patch("/{channel_id}")
async def patch_channel(
    channel_id: str,
    payload: ChannelRenamePayload,
    user=Depends(require_role("administrador", "gestor", "auditor")),
):
    """Renomeia o canal (alias customizado mostrado na UI/conversas)."""
    _validate_channel_id(channel_id)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    updated = await rename_channel(db, cid, channel_id, payload.channel_name)
    if not updated:
        raise HTTPException(404, "Canal não encontrado")
    return updated


@router.post("/{channel_id}/set-default-outbound")
async def make_default_outbound(
    channel_id: str,
    user=Depends(require_role("administrador", "gestor", "auditor")),
):
    """Marca este canal como padrão para envios proativos (mass msg, IA)."""
    _validate_channel_id(channel_id)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    updated = await set_default_outbound(db, cid, channel_id)
    if not updated:
        raise HTTPException(404, "Canal não encontrado")
    return updated


@router.get("/{channel_id}/qr")
async def channel_qr(
    channel_id: str,
    user=Depends(require_role("administrador", "gestor", "auditor")),
):
    _validate_channel_id(channel_id)
    try:
        return await _proxy_get(channel_id, "/qr")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Sidecar do {channel_id} inacessível: {e}")


@router.get("/{channel_id}/status")
async def channel_status(
    channel_id: str,
    user=Depends(require_role("administrador", "gestor", "auditor")),
):
    _validate_channel_id(channel_id)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    try:
        data = await _proxy_get(channel_id, "/status")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Sidecar inacessível: {e}")
    # Atualiza cache de phone/status
    me_obj = (data or {}).get("me") or {}
    me_id = (me_obj.get("id") or "").split(":")[0]
    await update_channel_runtime(
        db, cid, channel_id,
        phone_number=me_id or None,
        status=(data or {}).get("state"),
    )
    return data


@router.post("/{channel_id}/send")
async def channel_send(
    channel_id: str,
    payload: ChannelSendPayload,
    user=Depends(require_role("administrador", "gestor", "auditor")),
):
    """Envio outbound direto pelo canal escolhido (debug / disparo manual)."""
    _validate_channel_id(channel_id)
    try:
        return await _proxy_post(channel_id, "/send",
                                  {"phone": payload.phone, "text": payload.text})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Sidecar inacessível: {e}")


@router.post("/{channel_id}/logout")
async def channel_logout(
    channel_id: str,
    user=Depends(require_role("administrador", "gestor", "auditor")),
):
    """Desconecta o número e limpa a auth state Mongo do canal."""
    _validate_channel_id(channel_id)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    try:
        result = await _proxy_post(channel_id, "/logout", {})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Sidecar inacessível: {e}")
    # Limpa cache de phone
    await update_channel_runtime(
        db, cid, channel_id,
        phone_number=None, status="disconnected",
    )
    await db["whatsapp_channels"].update_one(
        {"company_id": cid, "id": channel_id},
        {"$set": {"phone_number": None}},
    )
    return result
