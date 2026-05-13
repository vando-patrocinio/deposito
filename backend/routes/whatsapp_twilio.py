"""Canal Twilio WhatsApp Business — paralelo ao Baileys.

Twilio é um BSP oficial Meta — número sempre real (sem LID anônimo).

Endpoints:
- GET    /api/whatsapp-twilio/config             → status + credenciais mascaradas
- PUT    /api/whatsapp-twilio/config             → salva/atualiza credenciais
- POST   /api/whatsapp-twilio/send               → envia mensagem texto/media
- POST   /api/whatsapp-twilio/webhook            → recebe inbound (Twilio chama)
- POST   /api/whatsapp-twilio/test               → envia mensagem de teste
- GET    /api/whatsapp-twilio/messages           → lista últimas msgs do canal
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.whatsapp_twilio")
router = APIRouter(prefix="/api/whatsapp-twilio", tags=["whatsapp_twilio"])

TWILIO_BASE = "https://api.twilio.com/2010-04-01"


def _mask(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


async def _get_creds(company_id: str) -> Optional[dict]:
    return await db.whatsapp_twilio_creds.find_one(
        {"company_id": company_id}, {"_id": 0},
    )


def _e164(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return ""
    return "+" + digits


# ---------------------------------------------------------------------------
# Config — credenciais Twilio
# ---------------------------------------------------------------------------
class ConfigIn(BaseModel):
    account_sid: str = Field(..., min_length=10, max_length=80)
    auth_token: str = Field(..., min_length=10, max_length=120)
    from_number: str = Field(..., min_length=8, max_length=20)
    enabled: bool = True
    sandbox: bool = False


@router.get("/config")
async def get_config(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    creds = await _get_creds(cid)
    if not creds:
        return {
            "configured": False,
            "enabled": False,
            "account_sid": None,
            "from_number": None,
            "sandbox": False,
        }
    return {
        "configured": True,
        "enabled": creds.get("enabled", False),
        "account_sid": _mask(creds.get("account_sid")),
        "auth_token": _mask(creds.get("auth_token")),
        "from_number": creds.get("from_number"),
        "sandbox": creds.get("sandbox", False),
        "updated_at": creds.get("updated_at"),
        "webhook_url": _build_webhook_url(cid),
    }


@router.put("/config")
async def put_config(payload: ConfigIn,
                      user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    from_n = _e164(payload.from_number)
    if not from_n:
        raise HTTPException(400, "Número 'from' inválido — use formato +5521998176526.")
    doc = {
        "company_id": cid,
        "account_sid": payload.account_sid.strip(),
        "auth_token": payload.auth_token.strip(),
        "from_number": from_n,
        "enabled": payload.enabled,
        "sandbox": payload.sandbox,
        "updated_at": now_iso(),
        "updated_by": user.get("email"),
    }
    await db.whatsapp_twilio_creds.update_one(
        {"company_id": cid}, {"$set": doc}, upsert=True,
    )
    logger.info("[twilio] config salva por %s · from=%s · enabled=%s",
                user.get("email"), from_n, payload.enabled)
    return {
        "ok": True,
        "configured": True,
        "enabled": payload.enabled,
        "from_number": from_n,
        "webhook_url": _build_webhook_url(cid),
    }


def _build_webhook_url(cid: str) -> str:
    # URL pública para o cliente colar no Twilio Console.
    backend_url = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
    return f"{backend_url}/api/whatsapp-twilio/webhook?tenant={cid}"


# ---------------------------------------------------------------------------
# Status — saldo Twilio + saúde do canal
# ---------------------------------------------------------------------------
@router.get("/status")
async def status(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    creds = await _get_creds(cid)
    if not creds or not creds.get("enabled"):
        return {"status": "disabled", "balance": None}
    sid = creds["account_sid"]
    token = creds["auth_token"]
    try:
        async with httpx.AsyncClient(timeout=8.0,
                                      auth=(sid, token)) as cli:
            r = await cli.get(f"{TWILIO_BASE}/Accounts/{sid}/Balance.json")
            if r.status_code >= 400:
                return {
                    "status": "error",
                    "http_status": r.status_code,
                    "error": (r.text or "")[:300],
                }
            body = r.json()
            return {
                "status": "connected",
                "balance": body.get("balance"),
                "currency": body.get("currency"),
                "from_number": creds.get("from_number"),
                "checked_at": now_iso(),
            }
    except Exception as e:
        return {"status": "unreachable", "error": str(e)[:200]}


# ---------------------------------------------------------------------------
# Send — envia mensagem WhatsApp via Twilio
# ---------------------------------------------------------------------------
class SendIn(BaseModel):
    phone: str = Field(..., min_length=8, max_length=20)
    text: str = Field(..., min_length=1, max_length=4096)
    media_url: Optional[str] = Field(default=None, max_length=600)


async def send_via_twilio(cid: str, phone: str, text: str,
                            media_url: Optional[str] = None) -> dict:
    """Envia uma mensagem WhatsApp. Retorna {ok, message_sid, error}."""
    creds = await _get_creds(cid)
    if not creds or not creds.get("enabled"):
        return {"ok": False, "error": "Twilio não configurado/habilitado"}
    sid = creds["account_sid"]
    token = creds["auth_token"]
    from_n = creds["from_number"]
    to_n = _e164(phone)
    if not to_n:
        return {"ok": False, "error": "Telefone destino inválido"}
    payload = {
        "From": f"whatsapp:{from_n}",
        "To": f"whatsapp:{to_n}",
        "Body": text[:4096],
    }
    if media_url:
        payload["MediaUrl"] = media_url
    try:
        async with httpx.AsyncClient(timeout=15.0,
                                      auth=(sid, token)) as cli:
            r = await cli.post(
                f"{TWILIO_BASE}/Accounts/{sid}/Messages.json",
                data=payload,
            )
            if r.status_code >= 400:
                err = ""
                try:
                    err = r.json().get("message") or r.text
                except Exception:
                    err = r.text
                logger.warning("[twilio] send falhou %s: %s", r.status_code, err[:200])
                return {"ok": False, "error": (err or "")[:300],
                        "http_status": r.status_code}
            body = r.json()
            return {
                "ok": True,
                "message_sid": body.get("sid"),
                "status": body.get("status"),
                "to": to_n,
            }
    except Exception as e:
        logger.exception("[twilio] send exception")
        return {"ok": False, "error": str(e)[:300]}


@router.post("/send")
async def send(payload: SendIn,
                user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    result = await send_via_twilio(cid, payload.phone, payload.text,
                                     media_url=payload.media_url)
    if not result.get("ok"):
        raise HTTPException(502, result.get("error") or "Falha ao enviar")
    # Persiste no histórico unificado
    await db.aihub_wa_messages.insert_one({
        "id": f"wam-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "direction": "outbound",
        "channel": "twilio",
        "phone": _e164(payload.phone).lstrip("+"),
        "text": payload.text,
        "message_id": result.get("message_sid"),
        "delivery_status": result.get("status") or "queued",
        "created_at": now_iso(),
        "by_user_email": user.get("email"),
    })
    return result


@router.post("/test")
async def send_test(payload: SendIn,
                     user: dict = Depends(require_role("gestor"))):
    """Send teste — não persiste no histórico de conversas."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await send_via_twilio(cid, payload.phone,
                                   payload.text or "Teste SmartProv ✅",
                                   media_url=payload.media_url)


# ---------------------------------------------------------------------------
# Webhook — recebe mensagens inbound
# ---------------------------------------------------------------------------
def _validate_twilio_signature(auth_token: str, url: str,
                                  form: dict, signature: Optional[str]) -> bool:
    """Valida X-Twilio-Signature (HMAC-SHA1 da URL + form params ordenados)."""
    if not signature:
        return False
    # Compose string: url + concat de chave+valor das form params em ordem
    sorted_keys = sorted(form.keys())
    s = url + "".join(f"{k}{form[k]}" for k in sorted_keys)
    digest = hmac.new(auth_token.encode("utf-8"),
                       s.encode("utf-8"), hashlib.sha1).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


@router.post("/webhook")
async def webhook(request: Request):
    """Webhook chamado pela Twilio quando o número recebe uma mensagem."""
    # Pega tenant da query string
    cid = request.query_params.get("tenant") or DEMO_COMPANY_ID
    form_raw = await request.form()
    form = {k: str(v) for k, v in form_raw.items()}
    creds = await _get_creds(cid)
    if not creds:
        raise HTTPException(400, "Tenant não configurado para Twilio.")

    # Valida signature se possível
    sig = request.headers.get("X-Twilio-Signature")
    full_url = str(request.url)
    if sig and not _validate_twilio_signature(
            creds["auth_token"], full_url, form, sig):
        logger.warning("[twilio] signature inválida tenant=%s", cid)
        # Retorna 200 mas não processa — Twilio fica feliz
        return {"ok": False, "ignored": "invalid_signature"}

    # Extrai campos do payload Twilio
    from_jid = form.get("From", "")  # 'whatsapp:+5521998176526'
    to_jid = form.get("To", "")
    text = form.get("Body", "") or ""
    profile_name = form.get("ProfileName", "")
    message_sid = form.get("MessageSid", "")
    num_media = int(form.get("NumMedia", "0") or "0")
    media_urls = []
    for i in range(num_media):
        u = form.get(f"MediaUrl{i}")
        if u:
            media_urls.append(u)

    # Normaliza phone (sem o prefixo whatsapp:)
    phone_raw = from_jid.replace("whatsapp:", "").lstrip("+")
    phone = re.sub(r"\D", "", phone_raw)
    if not phone:
        return {"ok": False, "error": "phone vazio"}

    # Identifica subscriber (auto-link)
    subscriber_id = None
    subscriber_ctx = None
    try:
        from phone_normalizer import link_phone_to_subscriber
        link = await link_phone_to_subscriber(phone, cid)
        if link and link.get("subscriber_id"):
            subscriber_id = link["subscriber_id"]
            sub = await db.subscribers.find_one(
                {"id": subscriber_id, "company_id": cid},
                {"_id": 0, "name": 1, "plan_name": 1, "status": 1, "branch": 1},
            )
            if sub:
                parts = [f"Nome: {sub.get('name')}"]
                if sub.get("plan_name"):
                    parts.append(f"Plano: {sub['plan_name']}")
                if sub.get("status"):
                    parts.append(f"Status: {sub['status']}")
                subscriber_ctx = " · ".join(parts)
    except Exception:
        pass

    # Persiste inbound
    await db.aihub_wa_messages.insert_one({
        "id": f"wam-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "direction": "inbound",
        "channel": "twilio",
        "phone": phone,
        "jid": from_jid,
        "to_jid": to_jid,
        "text": text,
        "push_name": profile_name,
        "message_id": message_sid,
        "media_urls": media_urls,
        "subscriber_id": subscriber_id,
        "created_at": now_iso(),
    })
    logger.info("[twilio] inbound %s (%s): %s%s", phone, profile_name,
                text[:80], f" [{num_media} media]" if num_media else "")

    # Auto-reply (reusa a função do baileys, mas marca channel)
    try:
        from routes.whatsapp_baileys import _maybe_auto_reply
        # Adaptamos: chamar _maybe_auto_reply e ele tentará enviar via baileys
        # — mas como queremos Twilio, fazemos inline:
        reply = await _generate_and_send_twilio_reply(
            cid=cid, phone=phone, user_text=text,
            subscriber_id=subscriber_id, subscriber_ctx=subscriber_ctx,
        )
        if reply:
            return {"ok": True, "auto_reply_preview": reply[:80]}
    except Exception as e:
        logger.warning("[twilio] auto-reply falhou: %s", e)

    return {"ok": True}


async def _generate_and_send_twilio_reply(
        cid: str, phone: str, user_text: str,
        subscriber_id: Optional[str], subscriber_ctx: Optional[str]) -> Optional[str]:
    """Gera resposta IA + envia via Twilio. Reusa o agente/roteamento atual."""
    # Verifica auto-reply
    cfg = await db.aihub_settings.find_one(
        {"company_id": cid, "key": "whatsapp_auto_reply"}, {"_id": 0},
    )
    if not cfg or not cfg.get("enabled"):
        return None
    # Pega agente via roteamento
    try:
        from services.routing import pick_agent_for_message
        agent = await pick_agent_for_message(cid, phone, user_text)
    except Exception:
        agent_name = cfg.get("agent_name") or "Isabella"
        agent = await db.aihub_agents.find_one(
            {"company_id": cid, "name": agent_name, "active": {"$ne": False}},
            {"_id": 0},
        )
    if not agent:
        return None
    # Monta system prompt
    sys_prompt = agent.get("system_prompt", "")
    if subscriber_ctx:
        sys_prompt += f"\n\n[Dados do cliente]\n{subscriber_ctx}"
    # Chama LLM
    try:
        from services.motor_ia import chat_completion
        result = await chat_completion(
            cid,
            messages=[{"role": "system", "content": sys_prompt},
                       {"role": "user", "content": user_text}],
            temperature=agent.get("temperature", 0.6),
            max_tokens=agent.get("max_tokens", 700),
            purpose="atendimento", agent="isabella_twilio",
        )
        reply_text = (result.get("content") or "").strip()
    except Exception as e:
        logger.warning("[twilio] LLM falhou: %s", e)
        return None
    if not reply_text:
        return None
    # Envia via Twilio
    send_result = await send_via_twilio(cid, phone, reply_text)
    # Persiste outbound
    await db.aihub_wa_messages.insert_one({
        "id": f"wam-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "direction": "outbound",
        "channel": "twilio",
        "phone": phone,
        "text": reply_text,
        "agent_id": agent.get("id"),
        "agent_name": agent.get("name"),
        "auto_reply": True,
        "delivery_status": (send_result.get("status")
                            if send_result.get("ok") else "failed_twilio"),
        "delivery_error": send_result.get("error"),
        "message_id": send_result.get("message_sid"),
        "subscriber_id": subscriber_id,
        "created_at": now_iso(),
    })
    return reply_text


# ---------------------------------------------------------------------------
# Mensagens (debug + UI) — só do canal Twilio
# ---------------------------------------------------------------------------
@router.get("/messages")
async def list_twilio_messages(limit: int = 50,
                                  user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    items = await db.aihub_wa_messages.find(
        {"company_id": cid, "channel": "twilio"},
        {"_id": 0},
    ).sort("created_at", -1).limit(limit).to_list(limit)
    return {"items": items, "count": len(items)}
