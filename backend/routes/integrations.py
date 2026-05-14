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


async def _check_mongo() -> Dict[str, Any]:
    """Ping MongoDB pra confirmar que o backend ainda fala com o banco."""
    try:
        await db.command("ping")
        return {"node": "mongodb", "label": "MongoDB", "ok": True, "status": "online"}
    except Exception as e:
        return {"node": "mongodb", "label": "MongoDB", "ok": False, "status": "error",
                "error": str(e)[:120]}


async def _check_openrouter(cid: str) -> Dict[str, Any]:
    """Verifica se a LLM externa (OpenRouter) está acessível e com chave."""
    try:
        cfg = await db.motor_ia_config.find_one(
            {"company_id": cid}, {"_id": 0, "openrouter_api_key": 1,
                                      "atendimento_model": 1, "enabled": 1})
        if not cfg or not cfg.get("openrouter_api_key"):
            return {"node": "openrouter", "label": "OpenRouter (LLM)",
                    "ok": False, "status": "no_key"}
        return {"node": "openrouter", "label": "OpenRouter (LLM)",
                "ok": True, "status": "configured",
                "model": cfg.get("atendimento_model") or "default"}
    except Exception as e:
        return {"node": "openrouter", "label": "OpenRouter (LLM)",
                "ok": False, "status": "error", "error": str(e)[:120]}


async def _check_atlaz(cid: str) -> Dict[str, Any]:
    """Status da API Atlaz pra sync de assinantes."""
    cfg = await db.atlaz_config.find_one(
        {"company_id": cid}, {"_id": 0, "enabled": 1, "api_key": 1,
                                  "last_customer_sync_at": 1})
    if not cfg or not cfg.get("enabled") or not cfg.get("api_key"):
        return {"node": "atlaz", "label": "Atlaz API", "ok": False,
                "status": "not_configured"}
    return {"node": "atlaz", "label": "Atlaz API", "ok": True,
            "status": "configured",
            "last_sync_at": cfg.get("last_customer_sync_at")}


@router.get("/topology")
async def integrations_topology(
    user: dict = Depends(require_role("gestor"))):
    """Diagrama interativo: status em tempo real de todos os nós da
    arquitetura do chat WhatsApp.

    Retorna nodes + edges + stats das últimas 24h por canal.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    from datetime import datetime, timedelta, timezone

    # Stats das últimas 24h (mensagens inbound + outbound + ai/humano)
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    since_iso = since.isoformat()

    # Aggregation: total inbound, outbound, ai_reply (auto_reply=true)
    msg_stats = {"inbound_24h": 0, "outbound_24h": 0, "ai_replies_24h": 0,
                 "human_replies_24h": 0}
    cursor = db.aihub_wa_messages.aggregate([
        {"$match": {"company_id": cid, "created_at": {"$gte": since_iso}}},
        {"$group": {
            "_id": {"direction": "$direction", "auto_reply": "$auto_reply"},
            "count": {"$sum": 1},
        }},
    ])
    async for row in cursor:
        d = row["_id"].get("direction") or "inbound"
        is_ai = bool(row["_id"].get("auto_reply"))
        if d == "inbound":
            msg_stats["inbound_24h"] += row["count"]
        elif d == "outbound":
            msg_stats["outbound_24h"] += row["count"]
            if is_ai:
                msg_stats["ai_replies_24h"] += row["count"]
            else:
                msg_stats["human_replies_24h"] += row["count"]

    # Total de conversas ativas
    convs_active = await db.wa_conversations.count_documents({
        "company_id": cid,
        "$or": [{"status": "open"}, {"status": {"$exists": False}}],
    })

    # Checa todos os nós em paralelo
    bail, twi, mt, mongo, openr, atlaz = await asyncio.gather(
        _check_baileys(),
        _check_twilio(cid),
        _check_meta(cid),
        _check_mongo(),
        _check_openrouter(cid),
        _check_atlaz(cid),
    )

    nodes = [
        {"id": "client", "label": "Cliente WhatsApp", "kind": "endpoint",
         "ok": True, "status": "external"},
        {"id": "baileys", "label": "Sidecar Baileys", "kind": "channel",
         "ok": bail.get("connected"), "status": bail.get("status"),
         "needs_action": bail.get("needs_action")},
        {"id": "twilio", "label": "Twilio API", "kind": "channel",
         "ok": twi.get("connected"), "status": twi.get("status"),
         "needs_action": twi.get("needs_action")},
        {"id": "meta", "label": "Meta Cloud", "kind": "channel",
         "ok": mt.get("connected"), "status": mt.get("status"),
         "needs_action": mt.get("needs_action")},
        {"id": "backend", "label": "FastAPI Backend", "kind": "core",
         "ok": True, "status": "running"},
        {"id": "mongo", "label": mongo.get("label"), "kind": "storage",
         "ok": mongo.get("ok"), "status": mongo.get("status"),
         "error": mongo.get("error")},
        {"id": "orchestrator", "label": "AI Orchestrator", "kind": "ai",
         "ok": True, "status": "active"},
        {"id": "isabella", "label": "Isabella IA", "kind": "agent",
         "ok": openr.get("ok"), "status":
            "atendendo" if openr.get("ok") else "sem LLM"},
        {"id": "openrouter", "label": openr.get("label"), "kind": "ai",
         "ok": openr.get("ok"), "status": openr.get("status"),
         "model": openr.get("model")},
        {"id": "atlaz", "label": atlaz.get("label"), "kind": "data",
         "ok": atlaz.get("ok"), "status": atlaz.get("status"),
         "last_sync_at": atlaz.get("last_sync_at")},
    ]

    edges = [
        {"from": "client", "to": "baileys", "label": "WhatsApp Web",
         "active": bail.get("connected")},
        {"from": "client", "to": "twilio", "label": "Twilio API",
         "active": twi.get("connected")},
        {"from": "client", "to": "meta", "label": "Graph API",
         "active": mt.get("connected")},
        {"from": "baileys", "to": "backend", "label": "webhook",
         "active": bail.get("connected")},
        {"from": "twilio", "to": "backend", "label": "webhook",
         "active": twi.get("connected")},
        {"from": "meta", "to": "backend", "label": "webhook",
         "active": mt.get("connected")},
        {"from": "backend", "to": "mongo", "label": "persist",
         "active": mongo.get("ok")},
        {"from": "backend", "to": "orchestrator", "label": "if no human",
         "active": True},
        {"from": "orchestrator", "to": "isabella", "label": "contexto pronto",
         "active": True},
        {"from": "isabella", "to": "openrouter", "label": "LLM call",
         "active": openr.get("ok")},
        {"from": "orchestrator", "to": "atlaz", "label": "customer data",
         "active": atlaz.get("ok")},
        {"from": "mongo", "to": "atlaz", "label": "sync 22h", "active": atlaz.get("ok")},
    ]

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            **msg_stats,
            "conversations_active": convs_active,
            "ai_share_24h": round(
                100 * msg_stats["ai_replies_24h"]
                / max(1, msg_stats["ai_replies_24h"] + msg_stats["human_replies_24h"]),
                1,
            ),
        },
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/reconnect")
async def reconnect_dead_channels(user: dict = Depends(require_role("gestor"))):
    """Tenta religar todos os canais que estão desconectados:
    - Baileys: força regenerar QR (logout + sleep + get QR)
    - Twilio: só validação (não há "reconectar" — é API REST)
    - Meta: idem
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _reconnect_for_company(cid)


async def _reconnect_for_company(cid: str) -> Dict[str, Any]:
    """Core do reconnect, separado pra ser usado tanto pelo endpoint
    quanto pelo cron job."""
    actions: list[Dict[str, Any]] = []

    # Baileys — sempre tenta, mesmo se sidecar parece down
    bail = await _check_baileys()
    if bail.get("needs_action"):
        try:
            async with httpx.AsyncClient(timeout=12.0) as cli:
                try:
                    r = await cli.post(f"{SIDECAR_BASE}/qr/refresh")
                    if r.status_code >= 400:
                        raise Exception(f"refresh HTTP {r.status_code}")
                except Exception:
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

    tw = await _check_twilio(cid)
    if tw.get("needs_action"):
        actions.append({"channel": "twilio", "action": "validate",
                          "result": tw.get("status")})
    mt = await _check_meta(cid)
    if mt.get("needs_action"):
        actions.append({"channel": "meta", "action": "validate",
                          "result": mt.get("status")})

    return {"actions": actions, "checked_at_seconds": 0}


async def auto_reconnect_job() -> None:
    """Cron interno: roda a cada 2 min e tenta religar canais mortos
    de TODOS os tenants com algum canal configurado.
    Falha silenciosa por tenant — não derruba o scheduler.
    """
    logger.info("[integrations] auto_reconnect_job iniciando")
    # Coleção de tenants únicos com algum canal configurado
    tenant_ids = set()
    async for cfg in db.whatsapp_twilio_creds.find(
        {"enabled": True}, {"_id": 0, "company_id": 1}
    ):
        tenant_ids.add(cfg.get("company_id") or DEMO_COMPANY_ID)
    async for cfg in db.whatsapp_meta_creds.find(
        {"enabled": True}, {"_id": 0, "company_id": 1}
    ):
        tenant_ids.add(cfg.get("company_id") or DEMO_COMPANY_ID)
    # Garantia mínima: sempre tenta o DEMO_COMPANY_ID (Baileys global)
    tenant_ids.add(DEMO_COMPANY_ID)

    for cid in tenant_ids:
        try:
            res = await _reconnect_for_company(cid)
            if res.get("actions"):
                logger.info("[integrations] auto_reconnect cid=%s actions=%s",
                            cid, res["actions"])
        except Exception as e:
            logger.exception("[integrations] auto_reconnect FALHOU cid=%s: %s", cid, e)
    logger.info("[integrations] auto_reconnect_job concluído (%d tenants)", len(tenant_ids))
