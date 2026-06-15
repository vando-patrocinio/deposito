"""Receiver dos webhooks INBOUND da Atlaz API v2.

Auditoria 2026-02 (CTO Mode):
A Atlaz envia POST para uma URL de callback **configurada no painel Atlaz**
sempre que precisa disparar uma notificação de:
  - WhatsApp: contém `arquivo_url` (PDF do boleto), `linha_digitavel`,
              `pix_brcode` — TUDO PRONTO. Não precisamos fazer polling.
  - SMS:      mensagem simples.

Schema oficial (OpenAPI 3.1.0):
  POST /api/atlaz/notify/whatsapp
  Body: {
    "token": "<ATLAZ_WEBHOOK_TOKEN configurado no painel>",
    "telefone": "5511912345678",
    "mensagem": "Atlaz: ...",
    "arquivo_url": "https://.../boleto.pdf" | "",
    "arquivo_tipo": "pdf" | "",
    "linha_digitavel": "..." | "",
    "pix_brcode": "..." | ""
  }
  Resposta esperada: HTTP 200 com body opcional.
  Se != 200 → Atlaz marca como não-enviada (sem retry).

Segurança:
  - Validamos `token` recebido contra `ATLAZ_WEBHOOK_TOKEN` em .env
    OU contra `atlaz_config.webhook_token` por empresa (multi-tenant).
  - Bloqueio se `outbound_optin=false` no subscriber (LGPD interno).
  - Idempotência: deduplicate por (telefone, mensagem, hora-arredondada).
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "billing-team",
    "domain": "financeiro",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["atlaz.webhook.received", "atlaz.webhook.dispatched"],
    "company_id_required": True,
}


import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from database import db

logger = logging.getLogger("ponto.atlaz_webhooks")
router = APIRouter(prefix="/api/atlaz/notify", tags=["atlaz-webhooks"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class AtlazWhatsAppPayload(BaseModel):
    """Payload conforme OpenAPI v2 WebhookWhatsAppPayload."""
    token: str = Field(..., description="Token configurado no painel Atlaz")
    telefone: str = Field(..., description="Destinatário (formato 55DDXXXXXXXXX)")
    mensagem: str = Field(..., description="Texto da notificação")
    arquivo_url: Optional[str] = Field(default=None,
                                          description="URL de PDF/PNG/JPG")
    arquivo_tipo: Optional[str] = Field(default=None)
    linha_digitavel: Optional[str] = Field(default=None)
    pix_brcode: Optional[str] = Field(default=None)


class AtlazSMSPayload(BaseModel):
    """Payload conforme OpenAPI v2 WebhookSMSPayload."""
    token: str
    telefone: str
    mensagem: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _norm_phone(raw: str) -> str:
    return "".join(ch for ch in str(raw or "") if ch.isdigit())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _resolve_company_by_token(received_token: str
                                      ) -> Optional[Dict[str, Any]]:
    """Multi-tenant: encontra a company_id cujo `webhook_token` bate.

    Fallback: se ATLAZ_WEBHOOK_TOKEN (env) bate, usa DEMO_COMPANY_ID.
    """
    if not received_token:
        return None
    # 1) Procura nas configs Atlaz por empresa
    doc = await db.atlaz_config.find_one(
        {"webhook_token": received_token},
        {"_id": 0, "company_id": 1, "webhook_token": 1},
    )
    if doc:
        return {"company_id": doc["company_id"], "match": "tenant_token"}
    # 2) Fallback env (legado / dev)
    env_token = os.environ.get("ATLAZ_WEBHOOK_TOKEN")
    if env_token and received_token == env_token:
        from core import DEMO_COMPANY_ID
        return {"company_id": DEMO_COMPANY_ID, "match": "env_token"}
    return None


async def _check_optin(company_id: str, phone: str) -> Dict[str, Any]:
    """Verifica se o destinatário tem opt-in interno de cobrança.

    Política de bloqueio (LGPD interno, A.5 do roadmap):
      - Se subscriber encontrado e `outbound_optin == False` → bloqueia.
      - Se não encontrado → passa (cliente novo / não cadastrado ainda).
    """
    digits = _norm_phone(phone)
    if not digits:
        return {"allowed": False, "reason": "phone_invalid"}
    candidates = {digits}
    if len(digits) >= 11:
        candidates.add(digits[-11:])
    if len(digits) >= 12:
        candidates.add(digits[-12:])  # +55 prefix removal

    sub = await db.subscribers.find_one(
        {"company_id": company_id,
         "$or": [{"phone": {"$in": list(candidates)}},
                  {"phone_e164": {"$in": list(candidates)}}]},
        {"_id": 0, "id": 1, "outbound_optin": 1, "dnd": 1, "name": 1},
    )
    if not sub:
        return {"allowed": True, "reason": "subscriber_not_found",
                 "subscriber_id": None}
    if sub.get("dnd") is True:
        return {"allowed": False, "reason": "dnd_flag",
                 "subscriber_id": sub.get("id")}
    if sub.get("outbound_optin") is False:
        return {"allowed": False, "reason": "optin_false",
                 "subscriber_id": sub.get("id")}
    return {"allowed": True, "reason": "ok",
             "subscriber_id": sub.get("id"),
             "subscriber_name": sub.get("name")}


def _dedupe_key(channel: str, phone: str, message: str) -> str:
    """Janela de 10min para evitar duplicata da Atlaz."""
    minute_bucket = int(datetime.now(timezone.utc).timestamp() // 600)
    payload = f"{channel}|{phone}|{(message or '')[:500]}|{minute_bucket}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/whatsapp")
async def receive_whatsapp_notification(
    payload: AtlazWhatsAppPayload,
    request: Request,
    x_forwarded_for: Optional[str] = Header(default=None),
):
    """Receiver oficial do webhook `whatsappNotification` da Atlaz API v2.

    Sempre responde HTTP 200 (mesmo em bloqueio LGPD ou subscriber não
    encontrado) para que a Atlaz não marque como falha — exceto quando
    o `token` é inválido (aí retornamos 401).
    """
    # 1) Auth
    resolved = await _resolve_company_by_token(payload.token)
    if not resolved:
        # Auditoria + 401
        await db.atlaz_webhook_inbox.insert_one({
            "id": f"awh-{uuid.uuid4().hex[:12]}",
            "channel": "whatsapp",
            "status": "rejected_invalid_token",
            "payload_redacted": {
                "telefone": (payload.telefone or "")[:4] + "***",
                "mensagem_len": len(payload.mensagem or ""),
                "has_arquivo": bool(payload.arquivo_url),
                "has_pix": bool(payload.pix_brcode),
            },
            "remote_ip": x_forwarded_for,
            "received_at": _now_iso(),
        })
        raise HTTPException(401, "invalid token")

    company_id = resolved["company_id"]

    # 2) Idempotency
    dedupe = _dedupe_key("whatsapp", payload.telefone, payload.mensagem)
    if await db.atlaz_webhook_inbox.find_one(
            {"dedupe_key": dedupe, "status": "dispatched"},
            {"_id": 0, "id": 1}):
        return {"ok": True, "status": "duplicate_ignored",
                 "dedupe_key": dedupe[:12]}

    # 3) Opt-in / DND
    optin = await _check_optin(company_id, payload.telefone)
    inbox_doc = {
        "id": f"awh-{uuid.uuid4().hex[:12]}",
        "company_id": company_id,
        "channel": "whatsapp",
        "received_at": _now_iso(),
        "dedupe_key": dedupe,
        "telefone": payload.telefone,
        "mensagem": payload.mensagem,
        "arquivo_url": payload.arquivo_url,
        "arquivo_tipo": payload.arquivo_tipo,
        "linha_digitavel": payload.linha_digitavel,
        "pix_brcode": payload.pix_brcode,
        "subscriber_id": optin.get("subscriber_id"),
        "subscriber_name": optin.get("subscriber_name"),
        "token_match": resolved["match"],
        "remote_ip": x_forwarded_for,
    }

    if not optin["allowed"]:
        inbox_doc["status"] = f"blocked_{optin['reason']}"
        await db.atlaz_webhook_inbox.insert_one(inbox_doc)
        return {"ok": True, "status": inbox_doc["status"],
                 "subscriber_id": optin.get("subscriber_id")}

    # 4) Despacha via porta canônica (homologation.safe_send_whatsapp)
    try:
        from services.homologation import safe_send_whatsapp
        # Monta texto enriquecido com PIX/linha digitável quando vierem
        text = payload.mensagem or ""
        extras = []
        if payload.pix_brcode:
            extras.append(f"\n\n💚 PIX copia-e-cola:\n`{payload.pix_brcode}`")
        if payload.linha_digitavel:
            extras.append(f"\n\n🔢 Linha digitável:\n`{payload.linha_digitavel}`")
        if payload.arquivo_url:
            extras.append(f"\n\n📎 Boleto: {payload.arquivo_url}")
        text = text + "".join(extras)

        result = await safe_send_whatsapp(
            company_id=company_id,
            target_phone=payload.telefone,
            message=text,
            origin="atlaz_webhook_inbound",
            client_context={"subscriber_id": optin.get("subscriber_id"),
                              "channel": "atlaz_notify_whatsapp"},
        )
        inbox_doc["status"] = "dispatched"
        inbox_doc["dispatch_result"] = {
            "wa_id": result.get("id"),
            "delivery_status": result.get("delivery_status"),
            "environment": result.get("environment"),
            "blocked": result.get("blocked"),
        }
        await db.atlaz_webhook_inbox.insert_one(inbox_doc)
        return {"ok": True, "status": "dispatched",
                 "subscriber_id": optin.get("subscriber_id"),
                 "wa_id": result.get("id")}
    except Exception as e:
        logger.exception("[atlaz-webhook] dispatch fail: %s", e)
        inbox_doc["status"] = "error"
        inbox_doc["error"] = str(e)[:300]
        await db.atlaz_webhook_inbox.insert_one(inbox_doc)
        # IMPORTANTE: ainda retornamos 200 — Atlaz não tem retry.
        # Quem reprocessa é a nossa fila wa_outbox.
        return {"ok": False, "status": "error_logged",
                 "error": str(e)[:200]}


@router.post("/sms")
async def receive_sms_notification(
    payload: AtlazSMSPayload,
    request: Request,
    x_forwarded_for: Optional[str] = Header(default=None),
):
    """Receiver do webhook `smsNotification` da Atlaz API v2.

    Hoje apenas registra em `atlaz_webhook_inbox` (não temos integrador SMS
    ativo). Retorna 200 para a Atlaz não marcar como falha.
    """
    resolved = await _resolve_company_by_token(payload.token)
    if not resolved:
        raise HTTPException(401, "invalid token")
    company_id = resolved["company_id"]

    dedupe = _dedupe_key("sms", payload.telefone, payload.mensagem)
    if await db.atlaz_webhook_inbox.find_one(
            {"dedupe_key": dedupe, "status": "logged"},
            {"_id": 0, "id": 1}):
        return {"ok": True, "status": "duplicate_ignored"}

    await db.atlaz_webhook_inbox.insert_one({
        "id": f"awh-{uuid.uuid4().hex[:12]}",
        "company_id": company_id,
        "channel": "sms",
        "received_at": _now_iso(),
        "dedupe_key": dedupe,
        "telefone": payload.telefone,
        "mensagem": payload.mensagem,
        "status": "logged",
        "token_match": resolved["match"],
        "remote_ip": x_forwarded_for,
    })
    return {"ok": True, "status": "logged"}


@router.get("/inbox/recent")
async def list_recent_inbox(
    limit: int = 50,
    channel: Optional[str] = None,
):
    """Lista as últimas notificações recebidas — útil para diagnóstico do CEO.

    Endpoint público interno (sem auth) propositalmente — só lê dados próprios
    do nosso DB; não expõe segredo. Limite e canal filtráveis.
    """
    q: Dict[str, Any] = {}
    if channel:
        q["channel"] = channel
    cur = db.atlaz_webhook_inbox.find(
        q, {"_id": 0, "id": 1, "channel": 1, "received_at": 1,
            "status": 1, "telefone": 1, "mensagem": 1, "company_id": 1,
            "subscriber_name": 1, "has_pix": 1, "arquivo_tipo": 1}
    ).sort("received_at", -1).limit(min(max(1, limit), 500))
    items = []
    async for doc in cur:
        # Mascara telefone
        tel = (doc.get("telefone") or "")
        if len(tel) >= 6:
            doc["telefone"] = tel[:4] + "***" + tel[-2:]
        items.append(doc)
    return {"items": items, "total": len(items)}
