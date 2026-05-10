"""WhatsApp via Baileys (QR Code login) — proxy FastAPI ↔ Node sidecar.

O sidecar Node roda em 127.0.0.1:3002 (gerenciado pelo supervisor — ver
`/etc/supervisor/conf.d/supervisord_whatsapp.conf`). Aqui só expomos a
API REST para o frontend e processamos o webhook de mensagens recebidas.

Endpoints públicos (gestor):
- GET  /api/whatsapp-baileys/qr       → { qr, status, me, last_qr_at }
- GET  /api/whatsapp-baileys/status   → { connected, state, me }
- POST /api/whatsapp-baileys/send     → { phone, text }
- POST /api/whatsapp-baileys/logout

Webhook interno (chamado pelo sidecar):
- POST /api/whatsapp-baileys/inbound  → mensagem recebida do WhatsApp
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, EMERGENT_LLM_KEY, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.wa_baileys")
router = APIRouter(prefix="/api/whatsapp-baileys", tags=["whatsapp-baileys"])

SIDECAR_BASE = "http://127.0.0.1:3002"


async def _sidecar_get(path: str) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            r = await cli.get(f"{SIDECAR_BASE}{path}")
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        logger.warning("[wa-baileys] sidecar GET %s falhou: %s", path, e)
        raise HTTPException(503,
                            f"WhatsApp sidecar indisponível: {e}") from e


async def _sidecar_post(path: str, payload: Optional[dict] = None) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.post(f"{SIDECAR_BASE}{path}", json=payload or {})
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text}
            if r.status_code >= 400:
                detail = body.get("error") or body.get("raw") or f"HTTP {r.status_code}"
                raise HTTPException(r.status_code, detail)
            return body
    except httpx.HTTPError as e:
        logger.warning("[wa-baileys] sidecar POST %s falhou: %s", path, e)
        raise HTTPException(503,
                            f"WhatsApp sidecar indisponível: {e}") from e


# ---------------------------------------------------------------------------
# Endpoints públicos (auth: gestor)
# ---------------------------------------------------------------------------
@router.get("/qr")
async def get_qr(user: dict = Depends(require_role("gestor"))):
    """Retorna o QR code atual em data URL (PNG base64) + status da conexão."""
    return await _sidecar_get("/qr")


@router.get("/status")
async def get_status(user: dict = Depends(require_role("gestor"))):
    return await _sidecar_get("/status")


class SendIn(BaseModel):
    phone: str = Field(..., min_length=8, max_length=25)
    text: str = Field(..., min_length=1, max_length=4096)


@router.post("/send")
async def send_message(payload: SendIn,
                        user: dict = Depends(require_role("gestor"))):
    out = await _sidecar_post("/send", {"phone": payload.phone, "text": payload.text})
    # Loga envio no histórico
    cid = user.get("company_id") or DEMO_COMPANY_ID
    await db.aihub_wa_messages.insert_one({
        "id": f"wam-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "direction": "outbound",
        "phone": payload.phone,
        "text": payload.text,
        "message_id": out.get("message_id"),
        "created_at": now_iso(),
        "actor_user": user.get("email") or user.get("id"),
    })
    return out


@router.post("/logout")
async def logout(user: dict = Depends(require_role("gestor"))):
    """Desconecta o WhatsApp + apaga sessão (próximo conectar pede QR novo)."""
    return await _sidecar_post("/logout")


# ---------------------------------------------------------------------------
# Webhook interno — chamado pelo sidecar Node a cada msg recebida
# ---------------------------------------------------------------------------
class InboundIn(BaseModel):
    phone: str
    jid: str
    from_me: bool = False
    text: str = ""
    message_id: Optional[str] = None
    timestamp: Optional[Any] = None
    push_name: Optional[str] = None


@router.post("/inbound")
async def inbound_webhook(payload: InboundIn):
    """Processa mensagem recebida do WhatsApp.

    - Salva em `aihub_wa_messages` para histórico
    - Auto-link com Subscriber via `link_phone_to_subscriber`
    - **Se auto-reply estiver habilitado**: chama a Jerusa pra responder e
      envia de volta via sidecar `/send`. Session ID por número de telefone
      (memória multi-turno persistente por contato).

    Endpoint SEM auth — sidecar Node fala via localhost, então é safe.
    """
    if payload.from_me:
        return {"ok": True, "ignored": "from_me"}
    if not payload.text.strip():
        return {"ok": True, "ignored": "empty"}
    # Não responde em grupos (jid termina @g.us)
    if "@g.us" in (payload.jid or ""):
        is_group = True
    else:
        is_group = False

    cid = DEMO_COMPANY_ID  # multi-tenant TODO
    subscriber_id = None
    subscriber_ctx = None
    try:
        from phone_normalizer import link_phone_to_subscriber
        link = await link_phone_to_subscriber(payload.phone, cid)
        if link and link.get("subscriber_id"):
            subscriber_id = link["subscriber_id"]
            sub = await db.subscribers.find_one(
                {"id": subscriber_id, "company_id": cid},
                {"_id": 0, "name": 1, "external_code": 1, "plan_name": 1,
                 "status": 1, "branch": 1, "address": 1},
            )
            if sub:
                parts = [f"Nome: {sub.get('name')}"]
                if sub.get("plan_name"):
                    parts.append(f"Plano: {sub['plan_name']}")
                if sub.get("status"):
                    parts.append(f"Status: {sub['status']}")
                if sub.get("branch"):
                    parts.append(f"Filial: {sub['branch']}")
                if sub.get("address"):
                    parts.append(f"Endereço: {sub['address']}")
                if sub.get("external_code"):
                    parts.append(f"Cód: {sub['external_code']}")
                subscriber_ctx = " · ".join(parts)
    except Exception as e:
        logger.warning("[wa-baileys] auto-link falhou: %s", e)

    await db.aihub_wa_messages.insert_one({
        "id": f"wam-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "direction": "inbound",
        "phone": payload.phone,
        "jid": payload.jid,
        "text": payload.text,
        "push_name": payload.push_name,
        "message_id": payload.message_id,
        "wa_timestamp": payload.timestamp,
        "subscriber_id": subscriber_id,
        "created_at": now_iso(),
    })
    logger.info("[wa-baileys] inbound %s (%s): %s", payload.phone,
                payload.push_name, payload.text[:80])

    # --- Auto-reply (se habilitado) ---
    if not is_group:
        try:
            reply = await _maybe_auto_reply(
                cid=cid, phone=payload.phone,
                user_text=payload.text,
                subscriber_id=subscriber_id,
                subscriber_ctx=subscriber_ctx,
            )
            if reply:
                return {"ok": True, "subscriber_id": subscriber_id,
                        "auto_reply": reply[:120]}
        except Exception as e:
            logger.warning("[wa-baileys] auto-reply falhou: %s", e)

    return {"ok": True, "subscriber_id": subscriber_id}


async def _maybe_auto_reply(cid: str, phone: str, user_text: str,
                              subscriber_id: Optional[str],
                              subscriber_ctx: Optional[str]) -> Optional[str]:
    """Se auto-reply estiver habilitado, gera resposta com a Jerusa
    e envia via sidecar. Retorna o texto enviado (ou None se desligado)."""
    # 1. Lê config de auto-reply
    cfg = await db.aihub_settings.find_one(
        {"company_id": cid, "key": "whatsapp_auto_reply"}, {"_id": 0}
    )
    if not cfg or not cfg.get("enabled"):
        return None  # auto-reply desligado

    # 2. Carrega o agente (Jerusa por padrão, ou outro definido em cfg)
    agent_name = cfg.get("agent_name") or "Jerusa"
    agent = await db.aihub_agents.find_one(
        {"company_id": cid, "name": agent_name, "active": {"$ne": False}},
        {"_id": 0},
    )
    if not agent:
        # Cria Jerusa se ainda não existir (mesma lógica de voice.py)
        try:
            from routes.voice import _ensure_jerusa_agent
            agent = await _ensure_jerusa_agent(cid)
        except Exception:
            return None

    # 3. Monta prompt — herda personalidade/preços/situações + contexto do cliente
    sys_prompt = agent["system_prompt"]
    extra = []
    if agent.get("company_info"):
        extra.append(f"=== INFORMAÇÕES DA EMPRESA ===\n{agent['company_info']}")
    if agent.get("pricing_info"):
        extra.append(f"=== PREÇOS E VALORES ===\n{agent['pricing_info']}")
    if agent.get("priority_situations"):
        extra.append(f"=== SITUAÇÕES PRIORITÁRIAS ===\n{agent['priority_situations']}")
    if subscriber_ctx:
        extra.append(f"=== CLIENTE IDENTIFICADO ===\n{subscriber_ctx}\n\n"
                     "Use essas informações para personalizar — mas não recite "
                     "tudo, use só o que for relevante para a dúvida atual.")
    else:
        extra.append(
            "=== CLIENTE NÃO IDENTIFICADO ===\nVocê não conseguiu vincular este "
            "telefone a nenhum assinante cadastrado. Peça nome completo + CPF "
            "antes de prosseguir, sem ser invasivo. Se for venda nova, "
            "pergunte primeiro o endereço para confirmar cobertura."
        )
    extra.append(
        "=== CANAL: WHATSAPP TEXTO ===\nVocê está respondendo via WhatsApp "
        "(não voz). Use no máximo 4 frases curtas, com emojis sutis quando "
        "fizer sentido (✅, 📅, 📞). Quebra de linha entre frases para fácil "
        "leitura no celular. Nunca use formatação markdown (sem **, sem listas)."
    )
    sys_prompt += "\n\n" + "\n\n".join(extra)

    # 4. Chama LLM — session_id estável por telefone p/ continuar conversa
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except ImportError:
        return None
    if not EMERGENT_LLM_KEY:
        return None

    session_id = f"wa-{phone}"
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message=sys_prompt,
    ).with_model(agent["model_provider"], agent["model_name"])
    try:
        chat = chat.with_temperature(agent.get("temperature", 0.6))  # type: ignore
    except Exception:
        pass
    try:
        chat = chat.with_max_tokens(agent.get("max_tokens", 350))  # type: ignore
    except Exception:
        pass
    try:
        resp = await chat.send_message(UserMessage(text=user_text))
        reply_text = resp if isinstance(resp, str) else getattr(resp, "text", str(resp))
        reply_text = (reply_text or "").strip()
    except Exception as e:
        logger.warning("[wa-baileys] LLM falhou: %s", e)
        return None

    if not reply_text:
        return None

    # 5. Envia via sidecar
    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            send_r = await cli.post(f"{SIDECAR_BASE}/send",
                                     json={"phone": phone, "text": reply_text})
            send_body = send_r.json() if send_r.headers.get("content-type", "").startswith("application/json") else {}
    except Exception as e:
        logger.warning("[wa-baileys] sidecar /send falhou: %s", e)
        send_body = {"ok": False, "error": str(e)}

    # 6. Persiste resposta no histórico
    await db.aihub_wa_messages.insert_one({
        "id": f"wam-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "direction": "outbound",
        "phone": phone,
        "text": reply_text,
        "message_id": send_body.get("message_id"),
        "subscriber_id": subscriber_id,
        "agent_id": agent["id"],
        "agent_name": agent["name"],
        "session_id": session_id,
        "auto_reply": True,
        "created_at": now_iso(),
    })
    logger.info("[wa-baileys] auto-reply enviado para %s: %s", phone, reply_text[:80])
    return reply_text


# ---------------------------------------------------------------------------
# Auto-reply settings (toggle on/off)
# ---------------------------------------------------------------------------
class AutoReplySettingsIn(BaseModel):
    enabled: bool
    agent_name: Optional[str] = "Jerusa"


@router.get("/auto-reply")
async def get_auto_reply(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await db.aihub_settings.find_one(
        {"company_id": cid, "key": "whatsapp_auto_reply"}, {"_id": 0}
    ) or {"enabled": False, "agent_name": "Jerusa"}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "agent_name": cfg.get("agent_name", "Jerusa"),
        "updated_at": cfg.get("updated_at"),
        "updated_by": cfg.get("updated_by"),
    }


@router.put("/auto-reply")
async def set_auto_reply(payload: AutoReplySettingsIn,
                          user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    await db.aihub_settings.update_one(
        {"company_id": cid, "key": "whatsapp_auto_reply"},
        {"$set": {
            "company_id": cid,
            "key": "whatsapp_auto_reply",
            "enabled": payload.enabled,
            "agent_name": payload.agent_name or "Jerusa",
            "updated_at": now_iso(),
            "updated_by": user.get("email") or user.get("id"),
        }},
        upsert=True,
    )
    logger.info("[wa-baileys] auto-reply %s por %s",
                 "ATIVADO" if payload.enabled else "DESATIVADO",
                 user.get("email"))
    return {"ok": True, "enabled": payload.enabled,
            "agent_name": payload.agent_name or "Jerusa"}


# ---------------------------------------------------------------------------
# Histórico de mensagens (UI)
# ---------------------------------------------------------------------------
@router.get("/messages")
async def list_messages(limit: int = 50,
                          user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    docs = await db.aihub_wa_messages.find(
        {"company_id": cid},
        {"_id": 0},
    ).sort("created_at", -1).limit(min(limit, 500)).to_list(500)
    return {"items": docs, "count": len(docs)}
