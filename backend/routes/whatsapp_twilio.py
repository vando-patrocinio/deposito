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

import asyncio
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
from services.rate_limit import limiter, get_limit

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
    # Backend não tem REACT_APP_BACKEND_URL (essa é var só do frontend),
    # então tentamos primeiro PUBLIC_BACKEND_URL, depois APP_BASE_URL,
    # e como último fallback um placeholder claro pro usuário.
    base = (
        os.environ.get("PUBLIC_BACKEND_URL")
        or os.environ.get("APP_BASE_URL")
        or os.environ.get("REACT_APP_BACKEND_URL")
        or ""
    ).rstrip("/")
    if not base:
        base = "https://[SEU-DOMINIO]"
    return f"{base}/api/whatsapp-twilio/webhook?tenant={cid}"


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
@limiter.limit(get_limit("webhook_inbound"))
async def webhook(request: Request):
    """Webhook Twilio inbound — RESPONDE EM <300ms.

    Hot-path:
      1. Persiste inbound em aihub_wa_messages
      2. Cria/atualiza wa_conversations
      3. Agenda LLM + Twilio Send via asyncio.create_task (fire-and-forget)
      4. Retorna HTTP 200 imediatamente
    """
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

    # Idempotência: Twilio retransmite o mesmo MessageSid em retries.
    # Se já vimos esse SID, ignoramos para não duplicar inbound.
    if message_sid:
        dup = await db.aihub_wa_messages.find_one(
            {"company_id": cid, "channel": "twilio",
             "direction": "inbound", "message_id": message_sid},
            {"_id": 1},
        )
        if dup:
            return {"ok": True, "duplicate": True, "message_sid": message_sid}

    # Identifica subscriber (auto-link) — Operação Identificação Automática
    subscriber_id = None
    subscriber_ctx = None
    link_result: Optional[dict] = None
    try:
        from phone_normalizer import (link_phone_to_subscriber,
                                         normalize_brazilian_phone)
        link_result = await link_phone_to_subscriber(phone, cid)
        normalized = normalize_brazilian_phone(phone)
        if link_result and link_result.get("subscriber_id"):
            subscriber_id = link_result["subscriber_id"]
            sub = await db.subscribers.find_one(
                {"id": subscriber_id, "company_id": cid},
                {"_id": 0, "name": 1, "plan_name": 1, "status": 1,
                 "branch": 1, "address": 1, "monthly_value": 1},
            )
            if sub:
                parts = [f"Nome: {sub.get('name')}"]
                if sub.get("plan_name"):
                    parts.append(f"Plano: {sub['plan_name']}")
                if sub.get("status"):
                    parts.append(f"Status: {sub['status']}")
                if sub.get("address"):
                    parts.append(f"Endereço: {sub['address']}")
                subscriber_ctx = " · ".join(parts)
        # Persiste identidade na conversa (mesmo se conflict ou pending)
        try:
            from services.anti_cpf_guardian import update_conversation_identity
            history_msgs = []
            async for m in db.aihub_wa_messages.find(
                    {"company_id": cid, "phone": phone,
                     "direction": "inbound"},
                    {"_id": 0, "text": 1}).sort("created_at", -1).limit(20):
                history_msgs.append(m.get("text", ""))
            await update_conversation_identity(
                company_id=cid, phone=phone, link=link_result,
                normalized=normalized, history_inbound=history_msgs)
        except Exception as e:
            logger.warning("[twilio] update_conversation_identity: %s", e)
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

    # Cria/atualiza conversa (UI exibe + tracking de canal)
    try:
        await db.wa_conversations.update_one(
            {"company_id": cid, "phone": phone},
            {"$set": {
                "last_channel_id": "twilio",
                "last_channel_name": "Twilio WhatsApp",
                "last_inbound_at": now_iso(),
                "subscriber_id": subscriber_id,
            },
             "$setOnInsert": {
                 "company_id": cid,
                 "phone": phone,
                 "status": "open",
                 "assignee_role": "ai",
                 "created_at": now_iso(),
             }},
            upsert=True,
        )
    except Exception as e:
        logger.warning("[twilio] wa_conversations upsert falhou: %s", e)

    # Enfileira em isabella_queue (worker pool dedicado consome).
    # Webhook NUNCA chama LLM ou Twilio diretamente — só persiste e enfileira.
    try:
        from services.isabella_queue import enqueue_job
        await enqueue_job(
            cid=cid, phone=phone, user_text=text,
            subscriber_id=subscriber_id, subscriber_ctx=subscriber_ctx,
            channel="twilio", message_sid=message_sid,
        )
    except Exception as e:
        logger.warning("[twilio] enqueue falhou: %s", e)
    return {"ok": True, "queued": True, "message_sid": message_sid}


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

    # GUARDIÃO ANTI-CPF — Operação Identificação Automática
    # Resolve identidade real do telefone (mesma lógica do webhook).
    link_for_guard = None
    history_inbound: list[str] = []
    short_term_analysis: dict = {}
    try:
        from phone_normalizer import link_phone_to_subscriber
        link_for_guard = await link_phone_to_subscriber(phone, cid)
        async for m in db.aihub_wa_messages.find(
                {"company_id": cid, "phone": phone, "direction": "inbound"},
                {"_id": 0, "text": 1}).sort("created_at", -1).limit(20):
            history_inbound.append(m.get("text", ""))
        from services.anti_cpf_guardian import inject_identification_block
        sys_prompt += "\n\n" + inject_identification_block(
            link_for_guard, history_inbound=history_inbound)
    except Exception as e:
        logger.warning("[twilio] anti_cpf_guardian inject falhou: %s", e)

    # MEMÓRIA DE CURTO PRAZO — Operação Memória Obrigatória
    try:
        from services.short_term_memory_guard import (
            analyze_short_term_context, inject_memory_block,
        )
        short_term_analysis = await analyze_short_term_context(
            company_id=cid, phone=phone, user_text=user_text)
        mem_block = inject_memory_block(short_term_analysis)
        if mem_block:
            sys_prompt += "\n\n" + mem_block
    except Exception as e:
        logger.warning("[twilio] short_term_memory inject falhou: %s", e)

    # MEMÓRIA DE LONGO PRAZO — Operação Memória Total (15/30/60 dias)
    try:
        from services.long_term_memory import build_long_term_block
        lt_block = await build_long_term_block(
            company_id=cid, phone=phone, subscriber_id=subscriber_id)
        if lt_block:
            sys_prompt += "\n\n" + lt_block
    except Exception as e:
        logger.warning("[twilio] long_term_memory inject falhou: %s", e)
    # Memória de correções (Edit & Teach)
    try:
        from routes.ai_corrections import (fetch_recent_for_prompt,
                                              format_corrections_for_prompt)
        corr_block = format_corrections_for_prompt(
            await fetch_recent_for_prompt(cid, limit=12))
        if corr_block:
            sys_prompt += "\n\n" + corr_block
    except Exception:
        pass
    # Orquestração com outras IAs
    try:
        from services.ai_orchestrator import build_orchestrated_context
        orchestrated = await build_orchestrated_context(
            cid, phone, user_text, subscriber_id=subscriber_id
        )
        if orchestrated:
            sys_prompt += "\n\n" + orchestrated
    except Exception:
        pass
    # Histórico de conversa (janela 100, truncate por tokens)
    try:
        from services.ai_history import fetch_history_turns
        history_turns = await fetch_history_turns(cid, phone, limit=100,
                                                    token_budget=6000)
    except Exception:
        history_turns = []
    # Chama LLM
    try:
        from services.motor_ia import chat_completion
        chat_messages = [{"role": "system", "content": sys_prompt}]
        chat_messages.extend(history_turns)
        if not history_turns or history_turns[-1].get("content") != user_text:
            chat_messages.append({"role": "user", "content": user_text})
        result = await chat_completion(
            cid,
            messages=chat_messages,
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
    # AGENDA NA LOUSA — detecta confirmação de janela proposta pela Isabella
    # em turn anterior e cria OS automaticamente.
    try:
        from services.isabella_lousa_scheduler import (
            classify_intent, confirm_and_create_os, propose_window
        )
        user_low = (user_text or "").lower().strip()
        # Confirmação típica
        is_confirm = bool(re.match(r"^(sim|pode|ok|t[aá]\s+bom|combinado|"
                                    r"aceito|confirmo|isso|fechado)\b",
                                    user_low))
        if is_confirm and link_for_guard and link_for_guard.get("subscriber_id"):
            # Recupera última proposta de janela do mesmo phone (busca em
            # ai_evaluations.kind=ISABELLA_WINDOW_PROPOSED)
            last_prop = await db.ai_evaluations.find_one(
                {"company_id": cid, "phone": phone,
                 "kind": "ISABELLA_WINDOW_PROPOSED"},
                {"_id": 0}, sort=[("created_at", -1)])
            if last_prop and last_prop.get("proposal", {}).get("slot"):
                created = await confirm_and_create_os(
                    company_id=cid,
                    subscriber_id=link_for_guard["subscriber_id"],
                    phone=phone, user_text=user_text,
                    proposal=last_prop["proposal"],
                    confirmation_text=user_text)
                if created.get("customer_message"):
                    reply_text = created["customer_message"]
        # Se ainda não temos reply (primeira ocorrência) e intenção é reparo
        # com subscriber identificado, propõe janela e PERSISTE a proposta
        if (not reply_text or "PLANO_DE_ACAO" not in reply_text) \
                and link_for_guard and link_for_guard.get("subscriber_id"):
            intent = classify_intent(user_text)
            if intent in ("reparo", "instalacao", "retirada", "troca_equipamento"):
                prop = await propose_window(
                    cid, link_for_guard["subscriber_id"], user_text)
                if prop.get("slot") and prop.get("proposal_text"):
                    # Persiste proposta para o turn seguinte poder confirmar
                    try:
                        await db.ai_evaluations.insert_one({
                            "id": f"win-{uuid.uuid4().hex[:10]}",
                            "company_id": cid, "phone": phone,
                            "kind": "ISABELLA_WINDOW_PROPOSED",
                            "subscriber_id": link_for_guard["subscriber_id"],
                            "proposal": prop,
                            "user_text": user_text[:300],
                            "created_at": now_iso(),
                        })
                    except Exception:
                        pass
                    # Se a LLM já não propôs janela, anexa ao final
                    if "agendar" not in (reply_text or "").lower():
                        sub_name = (link_for_guard.get("subscriber_name") or "").split(" ")[0] or "cliente"
                        reply_text = (
                            f"{sub_name}, " + prop["proposal_text"]
                        )
    except Exception as e:
        logger.warning("[twilio] isabella_lousa_scheduler falhou: %s", e)
    try:
        from services.anti_cpf_guardian import rewrite_if_violates, detect_violations
        violations = detect_violations(reply_text)
        if violations and link_for_guard and link_for_guard.get("subscriber_id"):
            original = reply_text
            reply_text = rewrite_if_violates(reply_text, link_for_guard)
            logger.warning(
                "[twilio] anti_cpf_guardian REWROTE reply (violations=%s) "
                "phone=%s subscriber=%s", violations, phone,
                link_for_guard.get("subscriber_id"))
            try:
                await db.ai_evaluations.insert_one({
                    "id": f"anti-cpf-{uuid.uuid4().hex[:10]}",
                    "company_id": cid,
                    "phone": phone,
                    "subscriber_id": link_for_guard.get("subscriber_id"),
                    "kind": "ANTI_CPF_BLOCK",
                    "violations": violations,
                    "original_excerpt": original[:200],
                    "rewritten_excerpt": reply_text[:200],
                    "created_at": now_iso(),
                })
            except Exception:
                pass
    except Exception as e:
        logger.warning("[twilio] anti_cpf_guardian rewrite falhou: %s", e)
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
    # Isabella CEO Follow-up: registra outcome em ai_evaluations
    try:
        from services.isabella_ceo_followup import register_followup
        await register_followup(
            company_id=cid, subscriber_id=subscriber_id,
            phone=phone, user_text=user_text,
            isabella_reply=reply_text,
            context_used=orchestrated if 'orchestrated' in dir() else "",
        )
    except Exception as e:
        logger.warning("[twilio] register_followup falhou phone=%s: %s",
                        phone, e)
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
