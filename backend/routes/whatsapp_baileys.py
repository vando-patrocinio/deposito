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
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta

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


class SystemEventIn(BaseModel):
    event: str
    code: Optional[int] = None
    name: Optional[str] = None
    retryCount: Optional[int] = None
    reason: Optional[str] = None
    ts: Optional[str] = None


@router.post("/system-event")
async def system_event(payload: SystemEventIn,
                         x_wa_token: Optional[str] = Header(default=None)):
    """Webhook interno chamado pelo sidecar em eventos críticos:
      - logged_out (sessão revogada)
      - connection_replaced (outra instância conectou)
      - possibly_banned (401/forbidden)
      - max_retries_exceeded (esgotou backoff)

    Persiste em `whatsapp_system_events` para a aba de Status mostrar,
    e gera notificação interna pra admin.
    """
    if WA_INBOUND_TOKEN and x_wa_token != WA_INBOUND_TOKEN:
        raise HTTPException(401, "X-WA-Token inválido")
    doc = {
        "id": f"wae-{uuid.uuid4().hex[:10]}",
        "company_id": DEMO_COMPANY_ID,
        "event": payload.event,
        "code": payload.code,
        "name": payload.name,
        "retry_count": payload.retryCount,
        "reason": payload.reason,
        "created_at": payload.ts or now_iso(),
        "acknowledged": False,
    }
    await db.whatsapp_system_events.insert_one(dict(doc))
    doc.pop("_id", None)
    logger.warning(
        "[wa-baileys][SYSTEM-EVENT] %s code=%s reason=%s",
        payload.event, payload.code, payload.reason,
    )
    return {"ok": True, "id": doc["id"]}


@router.get("/system-events")
async def list_system_events(user: dict = Depends(require_role("gestor"))):
    """Lista os últimos 50 eventos de sistema do WhatsApp."""
    docs = await db.whatsapp_system_events.find(
        {"company_id": DEMO_COMPANY_ID},
        {"_id": 0},
    ).sort("created_at", -1).limit(50).to_list(50)
    return {"events": docs}



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

        # --- Co-Pilot IA — dica interna para atendente humano ---
        # Só dispara quando a conversa está com humano (não-IA).
        # A IA de atendimento já tem injeção A2A própria via system_prompt.
        try:
            conv = await db.wa_conversations.find_one(
                {"company_id": cid, "phone": payload.phone},
                {"_id": 0, "assignee_role": 1, "status": 1},
            )
            if (conv and conv.get("assignee_role") == "human"
                    and conv.get("status") != "closed"):
                from services.copilot_ai import maybe_insert_copilot_hint
                await maybe_insert_copilot_hint(
                    company_id=cid,
                    phone=payload.phone,
                    last_inbound_text=payload.text,
                    last_inbound_id=payload.message_id,
                    subscriber_ctx=subscriber_ctx,
                )
        except Exception as e:
            logger.info("[wa-baileys] copilot skip: %s", e)

    return {"ok": True, "subscriber_id": subscriber_id}


async def _fetch_human_few_shots(cid: str, limit: int = 3) -> List[Dict[str, Any]]:
    """Busca pares (cliente perguntou → atendente humano respondeu) das conversas
    avaliadas com CSAT alto (>=8). Usado como few-shot examples no system_prompt
    da IA pra ela aprender padrões que conquistaram clientes.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    top_evals = await db.aihub_evaluations.find(
        {"company_id": cid, "csat_score": {"$gte": 8},
         "evaluated_at": {"$gte": cutoff}},
        {"_id": 0, "phone": 1, "csat_score": 1, "evaluated_at": 1},
    ).sort("evaluated_at", -1).limit(20).to_list(20)
    examples: List[Dict[str, Any]] = []
    seen_phones = set()
    for ev in top_evals:
        ph = ev.get("phone")
        if not ph or ph in seen_phones:
            continue
        msgs = await db.aihub_wa_messages.find(
            {"company_id": cid, "phone": ph,
             "$or": [{"direction": "inbound"},
                       {"direction": "outbound", "auto_reply": {"$ne": True},
                        "sent_by_user_id": {"$nin": [None, ""]}}]},
            {"_id": 0, "direction": 1, "text": 1, "created_at": 1,
             "auto_reply": 1},
        ).sort("created_at", 1).to_list(60)
        # Pega o primeiro par inbound→outbound(human) coerente
        for i, m in enumerate(msgs[:-1]):
            if m.get("direction") == "inbound":
                nxt = msgs[i + 1]
                if nxt.get("direction") == "outbound" and not nxt.get("auto_reply"):
                    q = (m.get("text") or "").strip()
                    a = (nxt.get("text") or "").strip()
                    if 5 <= len(q) <= 280 and 5 <= len(a) <= 600:
                        examples.append({"q": q, "a": a,
                                            "csat": ev.get("csat_score")})
                        seen_phones.add(ph)
                        break
        if len(examples) >= limit:
            break
    return examples


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
        # CLIENTE NÃO IDENTIFICADO POR TELEFONE — aciona fluxo CPF
        try:
            from services.cpf_identifier import handle_unidentified_inbound
            ident_sub, instruction = await handle_unidentified_inbound(
                cid, phone, user_text)
            if ident_sub:
                # Acabou de identificar! Monta contexto inline pra esta resposta
                parts = [f"Nome: {ident_sub.get('name')}"]
                if ident_sub.get("plan_name"):
                    parts.append(f"Plano: {ident_sub['plan_name']}")
                if ident_sub.get("status"):
                    parts.append(f"Status: {ident_sub['status']}")
                if ident_sub.get("external_code"):
                    parts.append(f"Cód: {ident_sub['external_code']}")
                if ident_sub.get("branch"):
                    parts.append(f"Filial: {ident_sub['branch']}")
                extra.append("=== CLIENTE RECÉM-IDENTIFICADO POR CPF ===\n"
                              + " · ".join(parts))
            extra.append(instruction["directive"])
        except Exception as e:
            logger.info("[wa-baileys] cpf identifier skip: %s", e)
            extra.append(
                "=== CLIENTE NÃO IDENTIFICADO ===\nVocê não conseguiu vincular este "
                "telefone a nenhum assinante cadastrado. Peça o CPF do titular "
                "antes de prosseguir, sem ser invasivo."
            )
    extra.append(
        "=== CANAL: WHATSAPP TEXTO ===\nVocê está respondendo via WhatsApp "
        "(não voz). Use no máximo 4 frases curtas, com emojis sutis quando "
        "fizer sentido (✅, 📅, 📞). Quebra de linha entre frases para fácil "
        "leitura no celular. Nunca use formatação markdown (sem **, sem listas)."
    )

    # 3a. CONTEXTO DE OUTAGE (Agent-to-Agent) — SmartOLT AI detecta panes
    # de rede e marca clientes afetados. Se este telefone está em outage
    # ativo, IA de atendimento informa proativamente em vez de fazer o
    # cliente passar pelos checklists óbvios.
    try:
        from services.smartolt_ai import get_outage_for_phone
        outage = await get_outage_for_phone(cid, phone)
        if outage:
            from datetime import datetime as _dt, timezone as _tz
            duration_min = 0
            try:
                fdt = _dt.fromisoformat(outage["first_detected_at"])
                duration_min = int((_dt.now(_tz.utc) - fdt).total_seconds() / 60)
            except Exception:
                pass
            extra.append(
                "=== ALERTA DE PANE DE REDE (CONFIRMADO) ===\n"
                f"O cliente está em REGIÃO COM PANE ATIVA:\n"
                f"- OLT: {outage.get('olt_name')} · Placa {outage.get('board')} · Porta {outage.get('port')}\n"
                f"- {outage.get('los_count')} de {outage.get('total_count')} clientes off-line ({outage.get('severity_pct')}%)\n"
                f"- Detectado há ~{duration_min} min\n\n"
                "AÇÃO OBRIGATÓRIA: avise o cliente PROATIVAMENTE que existe uma "
                "pane confirmada na região dele, que a equipe técnica já foi "
                "notificada e que o serviço deve voltar em breve. NÃO peça pra "
                "ele reiniciar o equipamento — não vai resolver. NÃO mande criar "
                "chamado individual. Em vez disso, ofereça avisar por WhatsApp "
                "quando a rede normalizar."
            )
    except Exception as e:
        logger.info("[wa-baileys] outage check skip: %s", e)

    # 3b. Few-shot — exemplos de atendentes humanos com CSAT alto (>=8) dos
    # últimos 30 dias. Ensina padrão de tom e estrutura sem replicar erros.
    try:
        shots = await _fetch_human_few_shots(cid, limit=3)
        if shots:
            lines = ["=== EXEMPLOS DE ATENDIMENTOS BEM AVALIADOS (CSAT ≥ 8) ==="]
            lines.append("Estes são exemplos REAIS de atendentes humanos da nossa equipe "
                          "que conquistaram nota alta. Aprenda o tom, mas NÃO copie "
                          "literalmente — adapte ao contexto da conversa atual.")
            for i, s in enumerate(shots, 1):
                lines.append(f"\n— Exemplo {i} (CSAT {s['csat']}):")
                lines.append(f"Cliente: {s['q']}")
                lines.append(f"Atendente: {s['a']}")
            extra.append("\n".join(lines))
    except Exception as e:
        logger.info("[wa-baileys] few-shot skip: %s", e)
    sys_prompt += "\n\n" + "\n\n".join(extra)

    # 4. Chama LLM via Motor IA (OpenRouter)
    try:
        from services.motor_ia import chat_completion
    except ImportError:
        return None
    try:
        result = await chat_completion(
            cid,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_text},
            ],
            temperature=agent.get("temperature", 0.6),
            max_tokens=agent.get("max_tokens", 350),
            purpose="atendimento",
            agent="isabella_whatsapp",
        )
        reply_text = (result.get("content") or "").strip()
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
        "session_id": f"wa-{phone}",
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
class InstanceSettingsIn(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=40)


@router.get("/instance")
async def get_instance_settings(user: dict = Depends(require_role("gestor"))):
    """Retorna nome customizado da instância WhatsApp (default: 'Ligo')."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await db.aihub_settings.find_one(
        {"company_id": cid, "key": "whatsapp_instance"}, {"_id": 0}
    ) or {}
    return {
        "display_name": cfg.get("display_name") or "Ligo",
        "updated_at": cfg.get("updated_at"),
        "updated_by": cfg.get("updated_by"),
    }


@router.put("/instance")
async def set_instance_settings(payload: InstanceSettingsIn,
                                  user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    name = payload.display_name.strip()
    await db.aihub_settings.update_one(
        {"company_id": cid, "key": "whatsapp_instance"},
        {"$set": {
            "company_id": cid,
            "key": "whatsapp_instance",
            "display_name": name,
            "updated_at": now_iso(),
            "updated_by": user.get("email") or user.get("id"),
        }},
        upsert=True,
    )
    logger.info("[wa-baileys] instância renomeada para '%s' por %s",
                 name, user.get("email"))
    return {"ok": True, "display_name": name}


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

    # 1) Agrega últimas msgs por telefone — EXCLUI notas internas (co-piloto)
    # da última mensagem visível, mas elas continuam contando em msg_count.
    pipeline = [
        {"$match": {"company_id": cid,
                      "direction": {"$ne": "internal"}}},
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
        # REGRA: conversas finalizadas não aparecem na lista até receber nova
        # mensagem inbound. Comparamos created_at da última inbound com
        # closed_at — se inbound mais nova, reabriu sozinha; senão, oculta.
        if conv.get("status") == "closed":
            closed_at = conv.get("closed_at") or ""
            last_inbound = r.get("last_inbound_at") or ""
            if last_inbound <= closed_at:
                continue
            # Nova inbound → reabre automaticamente
            await db.wa_conversations.update_one(
                {"company_id": cid, "phone": phone},
                {"$set": {"status": "open", "reopened_at": now_iso()}},
            )
            conv["status"] = "open"
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

    REGRA MÁXIMA: quando role transita ai → human (atendente está assumindo),
    enviamos AUTOMATICAMENTE uma mensagem ao cliente avisando que o atendimento
    especializado tomou a conversa. Best-effort: falha na entrega não bloqueia
    a atribuição (apenas registra `handover_msg_status=failed`).
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    role = payload.assignee_role or ("human" if payload.assignee_user_id else "ai")
    assignee_name = None
    if payload.assignee_user_id:
        u = await db.users.find_one(
            {"id": payload.assignee_user_id, "company_id": cid},
            {"_id": 0, "id": 1, "name": 1, "role": 1},
        )
        if not u:
            raise HTTPException(404, "Usuário não encontrado nesta empresa.")
        assignee_name = u.get("name")

    # Detecta transição IA → humano para disparar mensagem de handover
    prev = await db.wa_conversations.find_one(
        {"company_id": cid, "phone": phone},
        {"_id": 0, "assignee_role": 1},
    )
    prev_role = (prev or {}).get("assignee_role") or "ai"
    is_human_takeover = (role == "human"
                          and prev_role != "human"
                          and payload.assignee_user_id)

    handover_status: Optional[str] = None
    if is_human_takeover:
        first_name = (assignee_name or "").split()[0] if assignee_name else "um atendente"
        handover_text = (
            f"Olá! 👋 Aqui é o {first_name}, atendente especializado. "
            f"Vou continuar seu atendimento a partir de agora. "
            f"Pode me contar o que está acontecendo?"
        )
        try:
            async with httpx.AsyncClient(timeout=15.0) as cli:
                send_r = await cli.post(f"{SIDECAR_BASE}/send",
                                          json={"phone": phone, "text": handover_text})
                send_body: Dict[str, Any] = {}
                try:
                    send_body = send_r.json()
                except Exception:
                    send_body = {"raw": send_r.text}
                ok = send_r.status_code < 400 and send_body.get("ok")
                handover_status = "sent" if ok else "failed"
                # Loga mensagem no histórico do chat (igual /send manual)
                await db.aihub_wa_messages.insert_one({
                    "id": f"wam-{uuid.uuid4().hex[:10]}",
                    "company_id": cid,
                    "direction": "outbound",
                    "phone": phone,
                    "text": handover_text,
                    "message_id": send_body.get("message_id"),
                    "created_at": now_iso(),
                    "actor_user": user.get("email") or user.get("id"),
                    "sent_by_user_id": payload.assignee_user_id,
                    "auto_reply": False,
                    "is_handover_message": True,
                    "delivery_status": "sent" if ok else "failed",
                    "delivery_error": (send_body.get("error") if not ok else None),
                })
        except Exception as e:
            logger.warning("[wa-baileys] handover msg falhou para %s: %s", phone, e)
            handover_status = "failed"

    await db.wa_conversations.update_one(
        {"company_id": cid, "phone": phone},
        {"$set": {
            "company_id": cid, "phone": phone,
            "assignee_user_id": payload.assignee_user_id,
            "assignee_role": role,
            "status": "open",   # garante reabertura ao assumir
            "updated_at": now_iso(),
            "updated_by": user.get("email") or user.get("id"),
            **({"handover_msg_at": now_iso(),
                "handover_msg_status": handover_status}
                if handover_status else {}),
        }},
        upsert=True,
    )
    return {"ok": True, "phone": phone, "assignee_role": role,
            "assignee_user_id": payload.assignee_user_id,
            "handover_message_sent": handover_status == "sent",
            "handover_status": handover_status}


class FinalizeIn(BaseModel):
    outcome: Optional[str] = "resolved"   # resolved | escalated | abandoned


@router.put("/conversations/{phone}/finalize")
async def finalize_conversation(phone: str, payload: FinalizeIn,
                                  user: dict = Depends(require_role("gestor"))):
    """Marca conversa como finalizada (sai da fila Em Andamento).

    Também limpa atribuição (volta a IA como dono padrão) e registra fechamento.
    Conversa só reaparece na lista quando o cliente mandar nova mensagem.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    now = now_iso()
    await db.wa_conversations.update_one(
        {"company_id": cid, "phone": phone},
        {"$set": {
            "company_id": cid, "phone": phone,
            "status": "closed",
            "outcome": payload.outcome,
            "closed_at": now,
            "closed_by": user.get("email") or user.get("id"),
            "closed_by_user_id": user.get("id"),
            # Reset atribuição: ao receber nova msg, IA volta a responder
            "assignee_user_id": None,
            "assignee_role": "ai",
            "last_seen_at": now,
        }},
        upsert=True,
    )
    return {"ok": True, "phone": phone, "status": "closed",
            "closed_at": now}


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
    - Subscriber: nome, plano, status, débitos, endereço completo
    - SmartOLT: OLT, porta, VLAN, SN, fabricante, sinal RX/TX, status ONT
    - Histórico: chamados nos últimos 90 dias (lousa tickets)
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
    address = None
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
                # Endereço primário (ou primeiro disponível)
                addr = await db.subscriber_addresses.find_one(
                    {"subscriber_id": s["id"], "company_id": cid,
                     "is_primary": True},
                    {"_id": 0},
                ) or await db.subscriber_addresses.find_one(
                    {"subscriber_id": s["id"], "company_id": cid},
                    {"_id": 0},
                )
                if addr:
                    address = addr
    except Exception as e:
        logger.warning("[wa-baileys.profile] subscriber lookup falhou: %s", e)

    # 3. SmartOLT (sinal + topologia) — se subscriber tem pppoe_user
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

    # 4. Histórico de chamados (últimos 90 dias) — busca por phone OU pppoe_user
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    cutoff = (_dt.now(_tz.utc) - _td(days=90)).isoformat()
    tickets_query: Dict[str, Any] = {
        "company_id": cid,
        "created_at": {"$gte": cutoff},
    }
    or_clauses = [{"client_snapshot.phone": phone}]
    if subscriber and subscriber.get("pppoe_user"):
        or_clauses.append({"client_snapshot.pppoe_user": subscriber["pppoe_user"]})
    if len(or_clauses) > 1:
        tickets_query["$or"] = or_clauses
    else:
        tickets_query.update(or_clauses[0])
    try:
        recent = await db.tickets.find(
            tickets_query,
            {"_id": 0, "id": 1, "type": 1, "priority": 1, "status": 1,
             "scheduled_time": 1, "created_at": 1, "closed_at": 1,
             "outcome": 1, "client_snapshot.relato": 1,
             "assigned_collaborator_id": 1},
        ).sort("created_at", -1).limit(50).to_list(50)
    except Exception as e:
        logger.warning("[wa-baileys.profile] tickets lookup falhou: %s", e)
        recent = []
    open_count = sum(1 for t in recent
                      if t.get("status") in ("pendente", "aberta", "aguardando_atendimento"))

    return {
        "phone": phone,
        "whatsapp": wa,
        "subscriber": subscriber,
        "address": address,
        "olt_signal": olt_signal,
        "tickets_90d": recent,
        "tickets_count_90d": len(recent),
        "tickets_open": open_count,
    }
