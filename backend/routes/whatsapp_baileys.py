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
import os
import uuid
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, EMERGENT_LLM_KEY, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.wa_baileys")
router = APIRouter(prefix="/api/whatsapp-baileys", tags=["whatsapp-baileys"])

SIDECAR_BASE = "http://127.0.0.1:3002"
WA_INBOUND_TOKEN = os.environ.get("WA_INBOUND_TOKEN", "")


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
    """Envio manual de mensagem. Persistimos no histórico SEMPRE, mas o
    `delivery_status` reflete o que o sidecar Baileys realmente confirmou.

    Se o sidecar falhar (socket zumbi, timeout, desconectado), retornamos
    HTTP 502 com `delivery_status=failed` no doc — para o frontend mostrar
    erro pro usuário em vez de assumir entrega.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    send_ok = False
    send_error: Optional[str] = None
    out: Dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=20.0) as cli:
            r = await cli.post(f"{SIDECAR_BASE}/send",
                                json={"phone": payload.phone, "text": payload.text})
            try:
                out = r.json()
            except Exception:
                out = {"raw": r.text}
            if r.status_code < 400 and out.get("ok"):
                send_ok = True
            else:
                send_error = (out.get("error")
                              or f"HTTP {r.status_code}")
    except httpx.HTTPError as e:
        logger.warning("[wa-baileys] sidecar /send falhou: %s", e)
        send_error = str(e)

    await db.aihub_wa_messages.insert_one({
        "id": f"wam-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "direction": "outbound",
        "phone": payload.phone,
        "text": payload.text,
        "message_id": out.get("message_id"),
        "created_at": now_iso(),
        "actor_user": user.get("email") or user.get("id"),
        "sent_by_user_id": user.get("id"),
        "auto_reply": False,
        "delivery_status": "sent" if send_ok else "failed",
        "delivery_error": send_error,
    })
    if not send_ok:
        # Não engole: deixa o frontend mostrar toast vermelho.
        raise HTTPException(
            status_code=502,
            detail=f"WhatsApp não confirmou entrega: {send_error or 'erro desconhecido'}",
        )
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
async def inbound_webhook(payload: InboundIn,
                           x_wa_token: Optional[str] = Header(default=None)):
    """Processa mensagem recebida do WhatsApp.

    Segurança: validamos o header `X-WA-Token` contra `WA_INBOUND_TOKEN`
    do .env. O sidecar Node passa esse token. Se a env não estiver setada
    (dev), aceita sem validar (compat — log warning).
    """
    if WA_INBOUND_TOKEN:
        if not x_wa_token or x_wa_token != WA_INBOUND_TOKEN:
            logger.warning("[wa-baileys] inbound rejeitado: token inválido")
            raise HTTPException(401, "X-WA-Token inválido")
    else:
        logger.warning(
            "[wa-baileys] WA_INBOUND_TOKEN não configurado — endpoint aberto!"
        )
    if payload.from_me:
        return {"ok": True, "ignored": "from_me"}
    if not payload.text.strip():
        return {"ok": True, "ignored": "empty"}
    # Não responde em grupos (jid termina exatamente em @g.us)
    is_group = (payload.jid or "").endswith("@g.us")

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
    # 0. Se humano assumiu essa conversa, NÃO responde com IA
    conv = await db.wa_conversations.find_one(
        {"company_id": cid, "phone": phone}, {"_id": 0}
    )
    if conv and conv.get("assignee_role") == "human" and conv.get("status") != "closed":
        logger.info("[wa-baileys] auto-reply pulado — humano atendendo (%s)", phone)
        return None

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
    send_ok = False
    send_error: Optional[str] = None
    send_body: Dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            send_r = await cli.post(f"{SIDECAR_BASE}/send",
                                     json={"phone": phone, "text": reply_text})
            try:
                send_body = send_r.json()
            except Exception:
                send_body = {"raw": send_r.text}
            if send_r.status_code < 400 and send_body.get("ok"):
                send_ok = True
            else:
                send_error = (send_body.get("error")
                              or f"HTTP {send_r.status_code}")
    except Exception as e:
        logger.warning("[wa-baileys] sidecar /send falhou: %s", e)
        send_error = str(e)

    # 6. Persiste resposta no histórico (com delivery_status)
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
        "delivery_status": "sent" if send_ok else "failed",
        "delivery_error": send_error,
        "created_at": now_iso(),
    })
    if send_ok:
        logger.info("[wa-baileys] auto-reply enviado para %s: %s", phone, reply_text[:80])
    else:
        logger.warning("[wa-baileys] auto-reply gerado mas envio falhou (%s): %s",
                        send_error, reply_text[:80])
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


# ---------------------------------------------------------------------------
# Conversações (estilo FocusChat) — agrupa mensagens por telefone + buckets
# ---------------------------------------------------------------------------
from datetime import datetime, timezone, timedelta


def _bucket_for_conversation(conv: dict) -> str:
    """Decide o bucket FocusChat baseado nos atributos da conversa.

    Buckets:
    - "grupo": JID termina em @g.us
    - "automatico": atualmente sendo respondida pela IA (assigned_user_id == ISABELLA ou auto_reply ativo)
    - "manual": atribuída a um humano
    - "aguardando": sem resposta humana há mais de 5min (e sem auto-reply)
    - "fora_de_hora": chegou fora do horário comercial (8h-22h BRT)
    """
    if conv.get("is_group"):
        return "grupo"
    assignee_role = conv.get("assignee_role")
    if assignee_role == "ai":
        return "automatico"
    last_inbound = conv.get("last_inbound_at")
    if assignee_role == "human" and conv.get("assignee_user_id"):
        return "manual"
    # Sem atribuição — checa se está esperando
    if last_inbound:
        try:
            t = datetime.fromisoformat(last_inbound.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - t).total_seconds()
            hour_brt = (datetime.now(timezone.utc) - timedelta(hours=3)).hour
            if hour_brt < 8 or hour_brt >= 22:
                return "fora_de_hora"
            if age > 300:  # 5min
                return "aguardando"
        except Exception:
            pass
    return "aguardando"


@router.get("/conversations")
async def list_conversations(user: dict = Depends(require_role("gestor"))):
    """Agrega mensagens por telefone retornando conversas + buckets.

    REGRA MÁXIMA APLICADA AQUI:
    - Para CADA telefone retornado, se ainda não houver `subscriber_id`
      vinculado, tentamos `link_phone_to_subscriber` novamente (caso o
      cliente tenha sido cadastrado depois). Quando vinculamos, fazemos
      um `update_many` em `aihub_wa_messages` para gravar o vínculo
      retroativamente — assim toda mensagem antiga passa a estar linkada.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID

    # 1) Agrega últimas msgs por telefone
    pipeline = [
        {"$match": {"company_id": cid}},
        {"$sort": {"created_at": -1}},
        {"$group": {
            "_id": "$phone",
            "jid": {"$first": "$jid"},
            "last_text": {"$first": "$text"},
            "last_direction": {"$first": "$direction"},
            "last_message_at": {"$first": "$created_at"},
            "last_inbound_at": {"$first": {"$cond": [
                {"$eq": ["$direction", "inbound"]}, "$created_at", None
            ]}},
            "push_name": {"$first": "$push_name"},
            "subscriber_id": {"$first": "$subscriber_id"},
            "msg_count": {"$sum": 1},
        }},
        {"$sort": {"last_message_at": -1}},
        {"$limit": 200},
    ]
    rows = await db.aihub_wa_messages.aggregate(pipeline).to_list(200)

    # 2) Unread count por telefone — conta inbound após o último outbound
    unread_pipeline = [
        {"$match": {"company_id": cid, "direction": "inbound"}},
        {"$group": {"_id": "$phone", "inbound_ts": {"$push": "$created_at"}}},
    ]
    inbound_map = {r["_id"]: r["inbound_ts"]
                    async for r in db.aihub_wa_messages.aggregate(unread_pipeline)}
    last_out_pipeline = [
        {"$match": {"company_id": cid, "direction": "outbound"}},
        {"$group": {"_id": "$phone", "last_out_at": {"$max": "$created_at"}}},
    ]
    last_out_map = {r["_id"]: r["last_out_at"]
                     async for r in db.aihub_wa_messages.aggregate(last_out_pipeline)}

    # 3) Lê assignments persistidos (+ last_seen_at p/ unread mais preciso)
    convs_map = {}
    async for c in db.wa_conversations.find({"company_id": cid}, {"_id": 0}):
        convs_map[c["phone"]] = c

    # 4) REGRA MÁXIMA: re-tenta link nos telefones sem subscriber_id
    from phone_normalizer import link_phone_to_subscriber
    relinked = 0
    for r in rows:
        phone = r["_id"]
        jid = r.get("jid") or ""
        if jid.endswith("@g.us"):
            continue
        if r.get("subscriber_id"):
            continue
        try:
            link = await link_phone_to_subscriber(phone, cid)
        except Exception:
            link = None
        if link and link.get("subscriber_id"):
            r["subscriber_id"] = link["subscriber_id"]
            r["_link"] = link  # carrega branch/plan/status pra resposta
            # Retroativo: marca todas mensagens antigas com subscriber_id
            try:
                await db.aihub_wa_messages.update_many(
                    {"company_id": cid, "phone": phone,
                     "subscriber_id": {"$in": [None, ""]}},
                    {"$set": {"subscriber_id": link["subscriber_id"]}},
                )
                relinked += 1
            except Exception:
                pass
    if relinked:
        logger.info("[wa-baileys] auto-link retroativo: %d telefones vinculados", relinked)

    # 5) Resolve subscribers em batch (com branch/plan/status/external_code)
    subscriber_ids = {r.get("subscriber_id") for r in rows if r.get("subscriber_id")}
    subscribers = {}
    if subscriber_ids:
        async for s in db.subscribers.find(
            {"id": {"$in": list(subscriber_ids)}, "company_id": cid},
            {"_id": 0, "id": 1, "name": 1, "branch": 1, "plan_name": 1,
             "status": 1, "external_code": 1, "pppoe_user": 1},
        ):
            subscribers[s["id"]] = s

    # 6) Atendentes
    user_ids = {convs_map[k].get("assignee_user_id")
                 for k in convs_map if convs_map[k].get("assignee_user_id")}
    users_map = {}
    if user_ids:
        async for u in db.users.find(
            {"id": {"$in": list(user_ids)}},
            {"_id": 0, "id": 1, "name": 1, "avatar_url": 1, "google_picture": 1, "role": 1},
        ):
            users_map[u["id"]] = u

    # 7) Avatares WhatsApp em batch (do cache do sidecar — não-bloqueante)
    contact_avatars = {}
    try:
        non_group_phones = [r["_id"] for r in rows if not (r.get("jid") or "").endswith("@g.us")]
        if non_group_phones:
            async with httpx.AsyncClient(timeout=5.0) as cli:
                br = await cli.post(f"{SIDECAR_BASE}/contacts-bulk",
                                     json={"phones": non_group_phones})
                if br.status_code == 200:
                    body = br.json() or {}
                    contact_avatars = body.get("avatars") or {}
    except Exception:
        pass  # sidecar offline → sem avatares (frontend usa iniciais)

    items = []
    counts = {"automatico": 0, "aguardando": 0, "fora_de_hora": 0,
              "manual": 0, "grupo": 0}
    for r in rows:
        phone = r["_id"]
        jid = r.get("jid") or ""
        conv = convs_map.get(phone, {})
        is_group = jid.endswith("@g.us")
        assignee_user_id = conv.get("assignee_user_id")
        assignee_role = conv.get("assignee_role")
        if not assignee_role:
            assignee_role = "ai" if not is_group else None
        u = users_map.get(assignee_user_id or "")
        assignee_name = (u.get("name") if u else None) \
            or ("Isabella (IA)" if assignee_role == "ai" else None)
        assignee_avatar = (u.get("avatar_url") or u.get("google_picture")) if u else None

        # Unread: inbound após last outbound (ou todas se nunca houve outbound).
        # Refina com last_seen_at do operador (quando ele abriu a conversa).
        last_seen_at = conv.get("last_seen_at")
        last_out_at = last_out_map.get(phone)
        threshold = max(filter(None, [last_seen_at, last_out_at]), default=None)
        inbound_ts = inbound_map.get(phone, [])
        if threshold:
            unread = sum(1 for t in inbound_ts if t and t > threshold)
        else:
            unread = len(inbound_ts)

        sub = subscribers.get(r.get("subscriber_id") or "") or {}

        conv_view = {
            "phone": phone, "jid": jid, "is_group": is_group,
            "last_text": (r.get("last_text") or "")[:200],
            "last_direction": r.get("last_direction"),
            "last_message_at": r.get("last_message_at"),
            "last_inbound_at": r.get("last_inbound_at"),
            "push_name": r.get("push_name"),
            # Cliente identificado (REGRA MÁXIMA)
            "subscriber_id": r.get("subscriber_id"),
            "subscriber_name": sub.get("name"),
            "subscriber_branch": sub.get("branch"),
            "subscriber_plan": sub.get("plan_name"),
            "subscriber_status": sub.get("status"),
            "subscriber_external_code": sub.get("external_code"),
            "subscriber_pppoe": sub.get("pppoe_user"),
            # Avatar do WhatsApp do contato (do dispositivo)
            "contact_avatar": contact_avatars.get(phone),
            # Atendente atribuído
            "assignee_user_id": assignee_user_id,
            "assignee_name": assignee_name,
            "assignee_role": assignee_role,
            "assignee_avatar": assignee_avatar,
            # Status
            "unread": unread,
            "msg_count": r.get("msg_count", 0),
            "status": conv.get("status", "open"),
        }
        bucket = _bucket_for_conversation(conv_view)
        conv_view["bucket"] = bucket
        counts[bucket] = counts.get(bucket, 0) + 1
        items.append(conv_view)

    return {"buckets": counts, "items": items, "count": len(items)}


class MarkSeenIn(BaseModel):
    last_seen_at: Optional[str] = None  # opcional, default = agora


@router.post("/conversations/{phone}/mark-seen")
async def mark_conversation_seen(phone: str, payload: MarkSeenIn = MarkSeenIn(),
                                    user: dict = Depends(require_role("gestor"))):
    """Marca conversa como visualizada pelo operador (zera badge unread)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    seen_at = payload.last_seen_at or now_iso()
    await db.wa_conversations.update_one(
        {"company_id": cid, "phone": phone},
        {"$set": {
            "company_id": cid, "phone": phone,
            "last_seen_at": seen_at,
            "last_seen_by": user.get("email") or user.get("id"),
        }},
        upsert=True,
    )
    return {"ok": True, "phone": phone, "last_seen_at": seen_at}


@router.get("/conversations/{phone}/messages")
async def get_conversation_messages(phone: str, limit: int = 100,
                                       user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    docs = await db.aihub_wa_messages.find(
        {"company_id": cid, "phone": phone},
        {"_id": 0},
    ).sort("created_at", 1).limit(min(limit, 500)).to_list(500)
    return {"items": docs, "phone": phone, "count": len(docs)}


class AssignIn(BaseModel):
    assignee_user_id: Optional[str] = None    # None = remove atribuição (volta IA)
    assignee_role: Optional[str] = "human"     # "human" | "ai" | None


@router.put("/conversations/{phone}/assign")
async def assign_conversation(phone: str, payload: AssignIn,
                                user: dict = Depends(require_role("gestor"))):
    """Atribui ou desatribui uma conversa a um usuário.

    Casos:
    - assignee_user_id=<usr-id>, role=human → "Assumir" pelo operador
    - assignee_user_id=None, role=ai → "Devolver para IA"
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    role = payload.assignee_role or ("human" if payload.assignee_user_id else "ai")
    if payload.assignee_user_id:
        u = await db.users.find_one(
            {"id": payload.assignee_user_id, "company_id": cid},
            {"_id": 0, "id": 1, "name": 1, "role": 1},
        )
        if not u:
            raise HTTPException(404, "Usuário não encontrado nesta empresa.")
    await db.wa_conversations.update_one(
        {"company_id": cid, "phone": phone},
        {"$set": {
            "company_id": cid, "phone": phone,
            "assignee_user_id": payload.assignee_user_id,
            "assignee_role": role,
            "updated_at": now_iso(),
            "updated_by": user.get("email") or user.get("id"),
        }},
        upsert=True,
    )
    return {"ok": True, "phone": phone, "assignee_role": role,
            "assignee_user_id": payload.assignee_user_id}


class FinalizeIn(BaseModel):
    outcome: Optional[str] = "resolved"   # resolved | escalated | abandoned


@router.put("/conversations/{phone}/finalize")
async def finalize_conversation(phone: str, payload: FinalizeIn,
                                  user: dict = Depends(require_role("gestor"))):
    """Marca conversa como finalizada (para limpar a fila Em Andamento)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    await db.wa_conversations.update_one(
        {"company_id": cid, "phone": phone},
        {"$set": {
            "company_id": cid, "phone": phone,
            "status": "closed",
            "outcome": payload.outcome,
            "closed_at": now_iso(),
            "closed_by": user.get("email") or user.get("id"),
        }},
        upsert=True,
    )
    return {"ok": True, "phone": phone, "status": "closed"}


@router.get("/attendants")
async def list_attendants(user: dict = Depends(require_role("gestor"))):
    """Lista usuários que podem ser atendentes (todos da empresa) + Isabella IA."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    docs = await db.users.find(
        {"company_id": cid, "active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1, "role": 1, "email": 1,
         "avatar_url": 1, "google_picture": 1, "is_ai_agent": 1},
    ).sort("name", 1).to_list(200)
    # Garante Isabella sempre presente (e com flag is_ai_agent=True)
    iso = next((d for d in docs if d.get("email") == "isabella@ia.local"), None)
    if iso:
        # Backfill flag para registros antigos
        if not iso.get("is_ai_agent"):
            await db.users.update_one(
                {"id": iso["id"]},
                {"$set": {"is_ai_agent": True, "updated_at": now_iso()}},
            )
            iso["is_ai_agent"] = True
    else:
        # Cria sob demanda
        from passlib.context import CryptContext
        try:
            pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
            iso_pw = pwd_ctx.hash("isabella-ia-readonly")
        except Exception:
            iso_pw = "isabella-ia-readonly"
        iso_doc = {
            "id": f"usr-isabella-{cid}",
            "email": "isabella@ia.local",
            "name": "Isabella (IA)",
            "role": "gestor",
            "password_hash": iso_pw,
            "company_id": cid,
            "active": True,
            "is_ai_agent": True,
            "avatar_url": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        try:
            await db.users.insert_one(iso_doc)
        except Exception:
            pass
        iso_doc.pop("_id", None)
        iso_doc.pop("password_hash", None)
        docs.append(iso_doc)
    return {"items": docs}


# ---------------------------------------------------------------------------
# Contact profile (avatar + presença) — proxy do sidecar
# ---------------------------------------------------------------------------
@router.get("/contact/{phone}")
async def get_contact(phone: str,
                        user: dict = Depends(require_role("gestor"))):
    """Avatar WhatsApp + presença online/offline do contato."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.get(f"{SIDECAR_BASE}/contact-profile",
                              params={"phone": phone})
            return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e), "avatar": None, "presence": "unknown"}


@router.post("/contact/{phone}/subscribe-presence")
async def subscribe_presence(phone: str,
                              user: dict = Depends(require_role("gestor"))):
    """Pede ao Baileys pra começar a receber updates de presença desse contato."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            r = await cli.post(f"{SIDECAR_BASE}/presence-subscribe",
                                json={"phone": phone})
            return r.json()
    except Exception as e:
        raise HTTPException(503, f"Sidecar indisponível: {e}")


# ---------------------------------------------------------------------------
# Customer profile completo — agrega Subscriber + sinal SmartOLT (se houver)
# ---------------------------------------------------------------------------
@router.get("/customer-profile/{phone}")
async def customer_profile(phone: str,
                              user: dict = Depends(require_role("gestor"))):
    """Retorna perfil completo do cliente para popup do chat:
    - WhatsApp: avatar, presença
    - Subscriber: nome, plano, status, débitos, endereço
    - SmartOLT: sinal RX/TX, status ONT (se vinculado)
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID

    # 1. WhatsApp profile
    wa = {"avatar": None, "presence": "unknown"}
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            r = await cli.get(f"{SIDECAR_BASE}/contact-profile",
                              params={"phone": phone})
            if r.status_code == 200:
                wa_data = r.json()
                wa["avatar"] = wa_data.get("avatar")
                wa["presence"] = wa_data.get("presence") or "unknown"
                wa["last_seen"] = wa_data.get("last_seen")
    except Exception:
        pass

    # 2. Subscriber via phone normalization
    subscriber = None
    try:
        from phone_normalizer import link_phone_to_subscriber
        link = await link_phone_to_subscriber(phone, cid)
        if link and link.get("subscriber_id"):
            s = await db.subscribers.find_one(
                {"id": link["subscriber_id"], "company_id": cid},
                {"_id": 0},
            )
            if s:
                subscriber = s
    except Exception as e:
        logger.warning("[wa-baileys.profile] subscriber lookup falhou: %s", e)

    # 3. SmartOLT (sinal RX/TX) — se subscriber tem pppoe_user
    olt_signal = None
    if subscriber and subscriber.get("pppoe_user"):
        try:
            from routes.smartolt import resolve_signal_for_ticket
            fake_ticket = {
                "company_id": cid,
                "client_snapshot": {"pppoe_user": subscriber.get("pppoe_user")},
            }
            olt_signal = await resolve_signal_for_ticket(fake_ticket)
        except Exception as e:
            logger.info("[wa-baileys.profile] olt lookup skip: %s", e)

    return {
        "phone": phone,
        "whatsapp": wa,
        "subscriber": subscriber,
        "olt_signal": olt_signal,
    }
