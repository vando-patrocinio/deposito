"""Canal Meta Oficial — Instagram DM + Facebook Messenger (Graph API).

Diferente do Twilio (que faz WhatsApp Business API) e do Baileys (WhatsApp Web não-oficial),
este módulo integra direto com a **Meta Graph API v20.0** pra:

- Instagram Direct Messages (Business Account)
- Facebook Messenger (Page conversations)

Single-tenant na primeira fase (1 conta Meta por empresa), arquitetura
preparada para multi-tenant futuro.

Endpoints:
- GET    /api/whatsapp-meta/config             → status + credenciais mascaradas
- PUT    /api/whatsapp-meta/config             → salva/atualiza credenciais
- POST   /api/whatsapp-meta/send               → envia mensagem texto/media
- GET    /api/whatsapp-meta/webhook            → handshake verificação Meta
- POST   /api/whatsapp-meta/webhook            → recebe inbound (Meta chama)
- GET    /api/whatsapp-meta/messages           → lista últimas msgs do canal
- POST   /api/whatsapp-meta/verify-token/rotate → rotaciona verify token
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.whatsapp_meta")
router = APIRouter(prefix="/api/whatsapp-meta", tags=["whatsapp_meta"])

GRAPH_BASE = "https://graph.facebook.com/v20.0"
IG_GRAPH_BASE = "https://graph.instagram.com/v20.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mask(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


async def _get_creds(company_id: str) -> Optional[dict]:
    return await db.whatsapp_meta_creds.find_one(
        {"company_id": company_id}, {"_id": 0},
    )


def _verify_signature(raw_body: bytes, signature_header: str, app_secret: str) -> bool:
    """Verifica X-Hub-Signature-256 (SHA256 HMAC) — anti-spoofing.

    Meta envia header `X-Hub-Signature-256: sha256=<hex>` calculado sobre o
    body bruto com o App Secret como chave. Usa `hmac.compare_digest` pra
    proteção contra timing attacks.
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    provided = signature_header.replace("sha256=", "", 1).strip()
    expected = hmac.new(
        app_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, provided)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class MetaConfigIn(BaseModel):
    app_id: Optional[str] = Field(None, max_length=64)
    app_secret: Optional[str] = Field(None, max_length=120)
    page_id: Optional[str] = Field(None, max_length=64)
    page_access_token: Optional[str] = Field(None, max_length=400)
    ig_business_account_id: Optional[str] = Field(None, max_length=64)
    business_id: Optional[str] = Field(None, max_length=64)
    enabled_messenger: Optional[bool] = None
    enabled_instagram: Optional[bool] = None


class MetaSendIn(BaseModel):
    platform: str = Field(..., pattern="^(messenger|instagram)$")
    recipient_id: str = Field(..., min_length=1, max_length=64)
    text: Optional[str] = Field(None, max_length=2000)
    attachment_url: Optional[str] = Field(None, max_length=2000)
    attachment_type: Optional[str] = Field(None, pattern="^(image|video|audio|file)$")


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------
@router.get("/config")
async def get_config(user: dict = Depends(require_role("administrador"))):
    """Retorna status + URLs do webhook (App Secret + tokens mascarados)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    creds = await _get_creds(cid) or {}
    # Se ainda não tem verify_token, NÃO gera aqui (gera só no PUT) pra não
    # criar entradas órfãs. Mas mostramos placeholder.
    public_base = (await db.platform_settings.find_one(
        {"_id": "branding"}, {"_id": 0, "public_base_url": 1}
    ) or {}).get("public_base_url") or ""
    # Fallback: usa REACT_APP_BACKEND_URL/PUBLIC_BASE_URL do environment
    if not public_base:
        import os
        public_base = (os.environ.get("PUBLIC_BASE_URL")
                         or os.environ.get("REACT_APP_BACKEND_URL")
                         or "")
    webhook_url = (
        f"{public_base.rstrip('/')}/api/whatsapp-meta/webhook"
        if public_base else "/api/whatsapp-meta/webhook"
    )
    return {
        "configured": bool(creds.get("page_access_token")),
        "app_id": creds.get("app_id") or "",
        "app_secret_masked": _mask(creds.get("app_secret")),
        "page_id": creds.get("page_id") or "",
        "page_access_token_masked": _mask(creds.get("page_access_token")),
        "ig_business_account_id": creds.get("ig_business_account_id") or "",
        "business_id": creds.get("business_id") or "",
        "verify_token": creds.get("verify_token") or "",
        "webhook_url": webhook_url,
        "enabled_messenger": bool(creds.get("enabled_messenger", False)),
        "enabled_instagram": bool(creds.get("enabled_instagram", False)),
        "updated_at": creds.get("updated_at"),
    }


@router.put("/config")
async def save_config(payload: MetaConfigIn,
                          user: dict = Depends(require_role("administrador"))):
    """Salva/atualiza credenciais Meta. Apenas campos não-vazios são gravados.

    Gera Verify Token aleatório seguro na primeira vez que salvar credenciais.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    existing = await _get_creds(cid) or {}
    update = {"company_id": cid, "updated_at": now_iso()}
    data = payload.model_dump(exclude_none=True)
    for k in ("app_id", "app_secret", "page_id", "page_access_token",
              "ig_business_account_id", "business_id",
              "enabled_messenger", "enabled_instagram"):
        if k in data:
            update[k] = data[k]
    # Gera verify token na primeira vez
    if not existing.get("verify_token"):
        update["verify_token"] = secrets.token_urlsafe(32)
    await db.whatsapp_meta_creds.update_one(
        {"company_id": cid},
        {"$set": update, "$setOnInsert": {"created_at": now_iso()}},
        upsert=True,
    )
    logger.info("[meta] creds atualizadas company=%s campos=%s", cid, list(data.keys()))
    return await get_config(user)


@router.post("/verify-token/rotate")
async def rotate_verify_token(user: dict = Depends(require_role("administrador"))):
    """Gera um novo verify token (invalida o webhook atual no Meta)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    new_token = secrets.token_urlsafe(32)
    await db.whatsapp_meta_creds.update_one(
        {"company_id": cid},
        {"$set": {"verify_token": new_token, "updated_at": now_iso()}},
        upsert=True,
    )
    return {"verify_token": new_token}


# ---------------------------------------------------------------------------
# Webhook — verificação + recepção de mensagens
# ---------------------------------------------------------------------------
@router.get("/webhook")
async def webhook_verify(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
):
    """Handshake da Meta — devolve `hub.challenge` se o verify_token bater.

    Meta chama isto UMA vez quando você configura o webhook no Dashboard.
    """
    # Busca por TODAS as companies (single-tenant na fase 1, mas
    # multi-tenant-ready). Aceita o primeiro match — em multi-tenant teríamos
    # subdomínio/path com company_id pra distinguir.
    if hub_mode != "subscribe":
        raise HTTPException(400, "hub.mode inválido")
    if not hub_verify_token:
        raise HTTPException(400, "hub.verify_token ausente")
    creds = await db.whatsapp_meta_creds.find_one(
        {"verify_token": hub_verify_token}, {"_id": 0}
    )
    if not creds:
        logger.warning("[meta] webhook verify falhou — token desconhecido")
        raise HTTPException(403, "verify_token não bate")
    logger.info("[meta] webhook verificado com sucesso (company=%s)",
                creds.get("company_id"))
    return PlainTextResponse(hub_challenge or "")


@router.post("/webhook")
async def webhook_receive(request: Request):
    """Recebe eventos POST do Meta (mensagens, deliveries, reads).

    1. Lê body bruto pra calcular assinatura SHA256 HMAC.
    2. Identifica a company pela object_id (page_id ou ig_business_account_id).
    3. Valida assinatura com o App Secret da company.
    4. Persiste a mensagem em `aihub_wa_messages` (mesma coleção do
       Baileys/Twilio pra UI unificada) com `channel='meta'`.
    """
    raw = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")
    # Parse JSON (mesmo se sig falhar — precisa do object_id pra identificar)
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        logger.warning("[meta] webhook body inválido")
        return {"ok": False, "reason": "invalid_body"}

    obj_type = payload.get("object", "")  # "page" (messenger) | "instagram"
    entries = payload.get("entry", []) or []
    if not entries:
        return {"ok": True, "ignored": "no_entries"}

    # Identifica company pelo entry.id (Page ID ou IG Account ID)
    entry_id = str(entries[0].get("id") or "")
    creds = None
    if entry_id:
        creds = await db.whatsapp_meta_creds.find_one(
            {"$or": [
                {"page_id": entry_id},
                {"ig_business_account_id": entry_id},
            ]},
            {"_id": 0},
        )
    if not creds:
        logger.warning("[meta] webhook recebido mas sem creds match entry_id=%s", entry_id)
        return {"ok": False, "reason": "unknown_account"}

    # Valida assinatura
    app_secret = creds.get("app_secret") or ""
    if not _verify_signature(raw, sig, app_secret):
        logger.warning("[meta] assinatura inválida company=%s",
                       creds.get("company_id"))
        raise HTTPException(403, "signature invalid")

    cid = creds.get("company_id") or DEMO_COMPANY_ID

    # Loop pelos eventos e persiste
    saved = 0
    for entry in entries:
        # Messenger: entry.messaging[]
        for evt in entry.get("messaging", []) or []:
            if await _persist_messenger_event(cid, entry, evt):
                saved += 1
        # Instagram: entry.changes[].value (messages)
        for change in entry.get("changes", []) or []:
            if change.get("field") != "messages":
                continue
            val = change.get("value") or {}
            if await _persist_instagram_event(cid, entry, val):
                saved += 1
    logger.info("[meta] webhook %s entries=%d salvos=%d company=%s",
                obj_type, len(entries), saved, cid)
    return {"ok": True, "saved": saved}


async def _persist_messenger_event(cid: str, entry: dict, evt: dict) -> bool:
    """Salva 1 evento Messenger em `aihub_wa_messages`."""
    sender = (evt.get("sender") or {}).get("id")
    ts = evt.get("timestamp")
    msg = evt.get("message") or {}
    if msg.get("is_echo"):
        # Echo = mensagem que a Page enviou; ignoramos pra não duplicar.
        return False
    text = (msg.get("text") or "").strip()
    mid = msg.get("mid") or f"meta-{uuid.uuid4().hex[:12]}"
    attachments = []
    for att in msg.get("attachments") or []:
        attachments.append({
            "type": att.get("type"),
            "url": (att.get("payload") or {}).get("url"),
        })
    if not text and not attachments:
        return False
    # phone = ID do PSID (Page-Scoped User ID). Não é phone real, mas usamos
    # como identificador único da conversa, igual fazemos com WhatsApp.
    pseudo_phone = f"fb:{sender}"
    doc = {
        "id": mid,
        "company_id": cid,
        "channel": "meta_messenger",
        "platform": "messenger",
        "phone": pseudo_phone,
        "external_id": sender,
        "direction": "inbound",
        "text": text,
        "attachments": attachments,
        "meta_message_id": mid,
        "page_id": (entry.get("id") or ""),
        "created_at": now_iso(),
        "ts_epoch": ts,
    }
    try:
        await db.aihub_wa_messages.update_one(
            {"id": mid, "company_id": cid},
            {"$setOnInsert": doc},
            upsert=True,
        )
        # Garante conversa
        await db.wa_conversations.update_one(
            {"company_id": cid, "phone": pseudo_phone},
            {"$set": {"last_message_at": now_iso(), "channel": "meta_messenger",
                       "platform": "messenger"},
             "$setOnInsert": {"company_id": cid, "phone": pseudo_phone,
                                "status": "open", "assignee_role": "ai",
                                "created_at": now_iso()}},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.warning("[meta.messenger] erro persistir: %s", e)
        return False


async def _persist_instagram_event(cid: str, entry: dict, val: dict) -> bool:
    """Salva 1 evento Instagram DM em `aihub_wa_messages`."""
    from_id = ((val.get("from") or {}).get("id"))
    mid = val.get("id") or f"meta-{uuid.uuid4().hex[:12]}"
    text = (val.get("message") or val.get("text") or "").strip()
    attachments = []
    for att in val.get("attachments") or []:
        media = att.get("media") or {}
        url = (media.get("image") or media.get("video") or {}).get("url") \
            if isinstance(media.get("image"), dict) else media.get("url")
        attachments.append({"type": att.get("type"), "url": url})
    if not text and not attachments:
        return False
    pseudo_phone = f"ig:{from_id}"
    doc = {
        "id": mid,
        "company_id": cid,
        "channel": "meta_instagram",
        "platform": "instagram",
        "phone": pseudo_phone,
        "external_id": from_id,
        "direction": "inbound",
        "text": text,
        "attachments": attachments,
        "meta_message_id": mid,
        "ig_account_id": (entry.get("id") or ""),
        "created_at": now_iso(),
    }
    try:
        await db.aihub_wa_messages.update_one(
            {"id": mid, "company_id": cid},
            {"$setOnInsert": doc},
            upsert=True,
        )
        await db.wa_conversations.update_one(
            {"company_id": cid, "phone": pseudo_phone},
            {"$set": {"last_message_at": now_iso(), "channel": "meta_instagram",
                       "platform": "instagram"},
             "$setOnInsert": {"company_id": cid, "phone": pseudo_phone,
                                "status": "open", "assignee_role": "ai",
                                "created_at": now_iso()}},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.warning("[meta.instagram] erro persistir: %s", e)
        return False


# ---------------------------------------------------------------------------
# Send — envia mensagem para PSID/IGSID
# ---------------------------------------------------------------------------
@router.post("/send")
async def send_message(payload: MetaSendIn,
                          user: dict = Depends(require_role("auditor"))):
    """Envia mensagem via Meta Graph API.

    - Messenger: POST {GRAPH_BASE}/{page_id}/messages
    - Instagram: POST {GRAPH_BASE}/{ig_business_account_id}/messages
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    creds = await _get_creds(cid)
    if not creds:
        raise HTTPException(400, "Canal Meta não configurado.")
    token = creds.get("page_access_token")
    if not token:
        raise HTTPException(400, "Page Access Token ausente.")
    if payload.platform == "messenger":
        if not creds.get("enabled_messenger"):
            raise HTTPException(400, "Messenger desabilitado nesta empresa.")
        account_id = creds.get("page_id")
        base = GRAPH_BASE
    else:  # instagram
        if not creds.get("enabled_instagram"):
            raise HTTPException(400, "Instagram desabilitado nesta empresa.")
        account_id = creds.get("ig_business_account_id") or creds.get("page_id")
        base = GRAPH_BASE  # Use Graph API for IG Business messaging
    if not account_id:
        raise HTTPException(400, "ID da conta não configurado.")

    # Monta corpo
    body: dict = {"recipient": {"id": payload.recipient_id}}
    if payload.text:
        body["message"] = {"text": payload.text}
    elif payload.attachment_url and payload.attachment_type:
        body["message"] = {
            "attachment": {
                "type": payload.attachment_type,
                "payload": {"url": payload.attachment_url, "is_reusable": True},
            }
        }
    else:
        raise HTTPException(400, "Forneça `text` OU (attachment_url + attachment_type).")

    url = f"{base}/{account_id}/messages"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, params={"access_token": token}, json=body)
        try:
            resp_data = r.json()
        except Exception:
            resp_data = {"raw": r.text}
        if r.status_code >= 400:
            err = (resp_data.get("error") or {}).get("message") or str(resp_data)
            logger.warning("[meta.send] %s falhou: %s", payload.platform, err)
            raise HTTPException(r.status_code, f"Meta API: {err}")

    mid = resp_data.get("message_id") or f"meta-{uuid.uuid4().hex[:12]}"
    pseudo_phone = ("fb:" if payload.platform == "messenger" else "ig:") + payload.recipient_id
    # Persiste outbound
    await db.aihub_wa_messages.insert_one({
        "id": mid,
        "company_id": cid,
        "channel": f"meta_{payload.platform}",
        "platform": payload.platform,
        "phone": pseudo_phone,
        "external_id": payload.recipient_id,
        "direction": "outbound",
        "text": payload.text or f"[{payload.attachment_type}]",
        "attachments": ([{"type": payload.attachment_type,
                            "url": payload.attachment_url}]
                          if payload.attachment_url else []),
        "meta_message_id": mid,
        "sent_by_user_id": user.get("id"),
        "auto_reply": False,
        "created_at": now_iso(),
    })
    return {"ok": True, "message_id": mid}


# ---------------------------------------------------------------------------
# Lista de mensagens do canal Meta (debug)
# ---------------------------------------------------------------------------
@router.get("/messages")
async def list_messages(limit: int = 50,
                          platform: Optional[str] = None,
                          user: dict = Depends(require_role("auditor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: dict = {"company_id": cid, "channel": {"$in": ["meta_messenger",
                                                          "meta_instagram"]}}
    if platform in ("messenger", "instagram"):
        q["platform"] = platform
    docs = await db.aihub_wa_messages.find(
        q, {"_id": 0},
    ).sort("created_at", -1).limit(min(limit, 200)).to_list(200)
    return {"items": docs, "count": len(docs)}
