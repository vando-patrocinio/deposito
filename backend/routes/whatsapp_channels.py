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
    set_provider_config,
    update_channel_runtime,
    VALID_PROVIDERS,
)
from services.whatsapp_evolution import EvolutionClient, EvolutionUnreachable
from services.whatsapp_provider_health import collect as collect_provider_health

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


class ChannelProviderPayload(BaseModel):
    """Configura provider + credenciais (CTO 15/06/2026)."""
    provider: str = Field(..., description="baileys | evolution")
    evolution_url: Optional[str] = None
    evolution_api_key: Optional[str] = None
    evolution_instance_name: Optional[str] = None


class ChannelMigratePayload(BaseModel):
    """Migração atômica de provider (CTO 15/06/2026): troca provider e
    opcionalmente desloga o provider anterior pra liberar a sessão.
    Histórico de conversas no Mongo NÃO é tocado (são keyed por phone, não provider).
    """
    target_provider: str = Field(..., description="baileys | evolution")
    evolution_url: Optional[str] = None
    evolution_api_key: Optional[str] = None
    evolution_instance_name: Optional[str] = None
    auto_logout_previous: bool = True


# --------------------------------------------------------------------------- #
# Provider-aware adapter
# --------------------------------------------------------------------------- #
def _is_evolution(channel: dict) -> bool:
    return (channel or {}).get("provider") == "evolution"


def _evolution_client(channel: dict) -> EvolutionClient:
    """Constrói EvolutionClient a partir do doc do canal. Levanta 400 se faltar config.

    Aceita os 2 nomes de campo que aparecem na DB (legado + novo):
      - instance: `evolution_instance` (legado · doc atual) OU
                  `evolution_instance_name` (schema novo)
    """
    instance = (
        channel.get("evolution_instance_name")
        or channel.get("evolution_instance")
        or ""
    )
    try:
        return EvolutionClient(
            base_url=channel.get("evolution_url") or "",
            api_key=channel.get("evolution_api_key") or "",
            instance_name=instance,
            basic_auth=channel.get("evolution_basic_auth") or None,
        )
    except ValueError as e:
        raise HTTPException(400, f"Canal mal configurado para Evolution: {e}")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _validate_channel_id(channel_id: str) -> None:
    """Aceita os 4 slots Baileys (channel-1..4) E qualquer id de canal
    Evolution (`wac-evolution-*`). Outros IDs viram 400.

    CTO 16/02/2026 — antes só aceitava channel-1..4 e quebrava com
    AxiosError quando o front mandava o id Evolution.
    """
    if channel_id in CHANNEL_IDS:
        return
    if channel_id.startswith("wac-evolution"):
        return
    raise HTTPException(
        400,
        f"channel_id inválido. Use um de: {CHANNEL_IDS} ou um id Evolution "
        "(wac-evolution-*).",
    )


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
    """Lista os canais com status em paralelo.

    Resposta:
      - `channels`: SOMENTE os 4 slots Baileys (channel-1..4).
                    Esses são o grid principal da UI. Falhas em outros
                    providers NÃO contaminam essa lista.
      - `external_channels`: canais externos (Evolution API, futuros
                              providers). Renderizados separadamente.

    CTO 16/02/2026 — separação física entre Baileys e Evolution pra que
    um provider quebrado nunca trave/polua a UI do outro.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    all_chs = await list_channels(db, cid)

    # ----- Status Baileys (sidecar) — isolado -----
    async def _fetch_baileys_status(ch: dict) -> dict:
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

    # ----- Status Evolution — isolado, NUNCA bloqueia Baileys -----
    async def _fetch_evolution_status(ch: dict) -> dict:
        ch = dict(ch)
        try:
            evo = _evolution_client(ch)
            async with httpx.AsyncClient(timeout=4.0) as cli:
                r = await cli.get(
                    f"{evo.base_url}/instance/connectionState/{evo.instance_name}",
                    headers=evo.headers,
                )
                if r.status_code == 200:
                    try:
                        data = r.json()
                        inst = data.get("instance") or data
                        ch["live_state"] = inst.get("state")
                        ch["live_connected"] = inst.get("state") == "open"
                    except Exception:
                        ch["live_state"] = "unreachable"
                        ch["live_connected"] = False
                        ch["live_error"] = "Evolution devolveu non-JSON"
                elif r.status_code == 401:
                    ch["live_state"] = "auth_required"
                    ch["live_connected"] = False
                    ch["live_error"] = (
                        "Proxy externo exige Basic Auth — configure "
                        "evolution_basic_auth no canal"
                    )
                else:
                    ch["live_state"] = "unreachable"
                    ch["live_connected"] = False
                    ch["live_error"] = f"HTTP {r.status_code}"
        except HTTPException as he:
            ch["live_state"] = "config_invalid"
            ch["live_connected"] = False
            ch["live_error"] = str(he.detail)[:140]
        except Exception as e:
            ch["live_state"] = "unreachable"
            ch["live_connected"] = False
            ch["live_error"] = str(e)[:140]
        return ch

    # Separa os docs pelo provider
    baileys_docs = [c for c in all_chs if c.get("provider") != "evolution"
                    and str(c.get("id") or "").startswith("channel-")]
    evolution_docs = [c for c in all_chs if c.get("provider") == "evolution"]

    import asyncio
    baileys_enriched, evolution_enriched = await asyncio.gather(
        asyncio.gather(*[_fetch_baileys_status(c) for c in baileys_docs]) if baileys_docs else asyncio.sleep(0, result=[]),
        asyncio.gather(*[_fetch_evolution_status(c) for c in evolution_docs]) if evolution_docs else asyncio.sleep(0, result=[]),
    )

    def _mask(arr):
        for ch in arr:
            if ch.get("evolution_api_key"):
                tail = ch["evolution_api_key"][-4:] if len(ch["evolution_api_key"]) >= 4 else ""
                ch["evolution_api_key_masked"] = f"***{tail}"
                ch.pop("evolution_api_key", None)
            # Nunca vaza basic_auth no GET
            if ch.get("evolution_basic_auth"):
                ch["evolution_basic_auth_configured"] = True
                ch.pop("evolution_basic_auth", None)
        return arr

    return {
        "channels": _mask(list(baileys_enriched)),
        "external_channels": _mask(list(evolution_enriched)),
    }


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


@router.get("/evolution/defaults")
async def evolution_defaults(
    user=Depends(require_role("administrador", "gestor", "auditor")),
):
    """Retorna os defaults Evolution configurados no servidor (env vars).

    Usado pelo frontend pra auto-preencher o modal de provider quando o
    operador seleciona "Evolution API" — evita pedir URL/API-key manual
    quando o container Evolution já está provisionado no backend.

    Só é exposto a usuários com role admin/gestor/auditor (mesma proteção
    do PATCH /provider) — a API key NÃO é segredo pra esse público (eles
    já podem gravar ela manualmente via PATCH).
    """
    import os
    url = (os.environ.get("EVOLUTION_URL") or "").rstrip("/")
    key = os.environ.get("EVOLUTION_API_KEY") or ""
    return {
        "evolution_url": url or None,
        "evolution_api_key": key or None,
        "has_defaults": bool(url and key),
    }


@router.patch("/{channel_id}/provider")
async def patch_provider(
    channel_id: str,
    payload: ChannelProviderPayload,
    user=Depends(require_role("administrador", "gestor", "auditor")),
):
    """Configura o provider do canal: 'baileys' (sidecar interno) ou
    'evolution' (Evolution API externa). Para evolution exige url+api_key+instance.
    """
    _validate_channel_id(channel_id)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    try:
        updated = await set_provider_config(
            db, cid, channel_id,
            provider=payload.provider,
            evolution_url=payload.evolution_url,
            evolution_api_key=payload.evolution_api_key,
            evolution_instance_name=payload.evolution_instance_name,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not updated:
        raise HTTPException(404, "Canal não encontrado")
    safe = dict(updated)
    if safe.get("evolution_api_key"):
        safe["evolution_api_key_masked"] = "***" + (safe["evolution_api_key"][-4:] or "")
        safe.pop("evolution_api_key", None)
    return safe


@router.get("/{channel_id}/provider-health")
async def channel_provider_health(
    channel_id: str,
    days: int = 7,
    user=Depends(require_role("administrador", "gestor", "auditor")),
):
    """Snapshot de saúde do provider atual + status do alternativo, c/ recomendação.

    Dados agregados:
    - total_sent / success_rate / latency p50+p95 (wa_dispatch_metrics)
    - crash_count_7d (wa_sidecar_restart_log, só Baileys)
    - última event do sistema (wa_system_events)

    Recomendação automática: stay | configure_alt | consider_migrate.
    """
    _validate_channel_id(channel_id)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    ch = await get_channel(db, cid, channel_id)
    if not ch:
        raise HTTPException(404, "Canal não encontrado")
    return await collect_provider_health(db, cid, ch, days=days)


@router.post("/{channel_id}/migrate")
async def migrate_provider(
    channel_id: str,
    payload: ChannelMigratePayload,
    user=Depends(require_role("administrador", "gestor", "auditor")),
):
    """Migração atômica de provider: opcionalmente desloga o provider antigo
    (libera sessão Baileys ou instance Evolution) ANTES de aplicar o novo.

    Histórico de conversas NÃO é tocado (é keyed por phone, não por provider).
    Retorna {ok, old_provider, new_provider, previous_logout, channel}.
    """
    _validate_channel_id(channel_id)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    ch = await get_channel(db, cid, channel_id)
    if not ch:
        raise HTTPException(404, "Canal não encontrado")

    old_provider = ch.get("provider") or "baileys"
    if payload.target_provider == old_provider:
        raise HTTPException(400, f"Canal já está em provider='{old_provider}'")

    # Step 1: logout do provider antigo (best-effort, não falha a migration)
    previous_logout: dict = {"attempted": False}
    if payload.auto_logout_previous:
        previous_logout["attempted"] = True
        try:
            if _is_evolution(ch):
                evo = _evolution_client(ch)
                previous_logout["result"] = await evo.logout()
            else:
                previous_logout["result"] = await _proxy_post(channel_id, "/logout", {})
            previous_logout["ok"] = True
        except (httpx.HTTPError, HTTPException) as e:
            previous_logout["ok"] = False
            previous_logout["error"] = str(e)[:200]

    # Step 2: aplica nova config (validada por set_provider_config)
    try:
        updated = await set_provider_config(
            db, cid, channel_id,
            provider=payload.target_provider,
            evolution_url=payload.evolution_url,
            evolution_api_key=payload.evolution_api_key,
            evolution_instance_name=payload.evolution_instance_name,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Step 3: limpa cache de phone/status (canal precisa reconectar)
    await update_channel_runtime(
        db, cid, channel_id,
        phone_number=None, status="migrated",
    )
    await db["whatsapp_channels"].update_one(
        {"company_id": cid, "id": channel_id},
        {"$set": {"phone_number": None}},
    )

    # Mascara api_key na resposta
    safe = dict(updated or {})
    if safe.get("evolution_api_key"):
        safe["evolution_api_key_masked"] = "***" + (safe["evolution_api_key"][-4:] or "")
        safe.pop("evolution_api_key", None)

    return {
        "ok": True,
        "old_provider": old_provider,
        "new_provider": payload.target_provider,
        "previous_logout": previous_logout,
        "channel": safe,
        "note": ("Histórico de conversas preservado. Conecte o novo provider "
                 "via QR (canal-1 /qr) pra restaurar a sessão."),
    }


@router.get("/{channel_id}/qr")
async def channel_qr(
    channel_id: str,
    user=Depends(require_role("administrador", "gestor", "auditor")),
):
    _validate_channel_id(channel_id)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    ch = await get_channel(db, cid, channel_id)
    if _is_evolution(ch):
        try:
            evo = _evolution_client(ch)
            # Cria instance se não existir; webhook ainda não configurado aqui.
            await evo.create_instance(webhook_url=None)
            return await evo.get_qr()
        except EvolutionUnreachable as e:
            # Cloudflare engole 5xx → devolve 200 com payload de erro pra UI
            # mostrar a mensagem no card sem virar "Bad gateway".
            return {"qr_base64": None, "error": str(e), "state": "unreachable"}
        except httpx.HTTPStatusError as e:
            sc = e.response.status_code
            body = e.response.text[:160].replace("\n", " ")
            return {
                "qr_base64": None,
                "state": "unreachable",
                "error": (
                    f"Evolution respondeu HTTP {sc}. "
                    "Provavelmente Basic Auth no proxy. Body: "
                    f"'{body}…'"
                ),
            }
        except httpx.HTTPError as e:
            return {"qr_base64": None, "state": "unreachable",
                    "error": f"Evolution API inacessível: {e}"}
    # Baileys (default)
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
    ch = await get_channel(db, cid, channel_id)
    if _is_evolution(ch):
        try:
            evo = _evolution_client(ch)
            data = await evo.status()
            await update_channel_runtime(
                db, cid, channel_id,
                phone_number=None, status=data.get("state"),
            )
            return data
        except EvolutionUnreachable as e:
            return {"state": "unreachable", "connected": False,
                    "error": str(e)}
        except httpx.HTTPStatusError as e:
            return {
                "state": "unreachable", "connected": False,
                "error": (
                    f"Evolution respondeu HTTP {e.response.status_code} "
                    "(provavelmente Basic Auth no proxy externo)."
                ),
            }
        except httpx.HTTPError as e:
            return {"state": "unreachable", "connected": False,
                    "error": f"Evolution API inacessível: {e}"}
    # Baileys (default)
    try:
        data = await _proxy_get(channel_id, "/status")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Sidecar inacessível: {e}")
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
    cid = user.get("company_id") or DEMO_COMPANY_ID
    ch = await get_channel(db, cid, channel_id)
    if _is_evolution(ch):
        try:
            evo = _evolution_client(ch)
            return await evo.send_text(payload.phone, payload.text)
        except httpx.HTTPError as e:
            raise HTTPException(502, f"Evolution API inacessível: {e}")
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
    """Desconecta o número e limpa a auth state do canal."""
    _validate_channel_id(channel_id)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    ch = await get_channel(db, cid, channel_id)
    if _is_evolution(ch):
        try:
            evo = _evolution_client(ch)
            result = await evo.logout()
        except EvolutionUnreachable as e:
            return {"ok": False, "error": str(e)}
        except httpx.HTTPStatusError as e:
            return {
                "ok": False,
                "error": (
                    f"Evolution respondeu HTTP {e.response.status_code} "
                    "(provavelmente Basic Auth no proxy externo)."
                ),
            }
        except httpx.HTTPError as e:
            return {"ok": False, "error": f"Evolution API inacessível: {e}"}
    else:
        try:
            result = await _proxy_post(channel_id, "/logout", {})
        except httpx.HTTPError as e:
            raise HTTPException(502, f"Sidecar inacessível: {e}")
    await update_channel_runtime(
        db, cid, channel_id,
        phone_number=None, status="disconnected",
    )
    await db["whatsapp_channels"].update_one(
        {"company_id": cid, "id": channel_id},
        {"$set": {"phone_number": None}},
    )
    return result
