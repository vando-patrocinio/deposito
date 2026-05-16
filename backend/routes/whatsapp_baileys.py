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

import base64
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, EMERGENT_LLM_KEY, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.wa_baileys")
router = APIRouter(prefix="/api/whatsapp-baileys", tags=["whatsapp-baileys"])

SIDECAR_BASE = "http://127.0.0.1:3002"
WA_INBOUND_TOKEN = os.environ.get("WA_INBOUND_TOKEN", "")

# Diretório onde áudios outbound enviados pela atendente são persistidos
# (servidos via /api/whatsapp-baileys/audio/{msg_id})
WA_AUDIO_DIR = Path(os.environ.get("WA_AUDIO_DIR", "/app/backend/uploads/wa_audio"))
WA_AUDIO_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helper: quebra a resposta da IA em múltiplas bolhas
# ---------------------------------------------------------------------------
def _split_ai_reply(text: str, max_chunks: int = 6,
                     min_chunk_chars: int = 12) -> List[str]:
    """Quebra a resposta da IA em chunks que viram bolhas separadas no
    WhatsApp.

    Regras:
    1. Separa por linhas em branco (`\\n\\n`) ou marcador explícito `---`.
    2. Junta chunks micro (< min_chunk_chars) no chunk seguinte para
       evitar bolhas de 1-2 palavras.
    3. Cap em `max_chunks`: o excedente é concatenado no último chunk
       (assim a IA não consegue 'flood' o cliente).
    4. Quebras de linha simples (`\\n`) DENTRO de um chunk são preservadas
       (ex.: lista de bullets).
    5. Se a resposta for curta ou inteira numa linha só, devolve [text].
    """
    if not text:
        return []
    raw = text.replace("\r\n", "\n").strip()
    # Separador explícito `---` em linha sozinha vira "\n\n" pra unificar
    raw = re.sub(r"\n\s*---+\s*\n", "\n\n", raw)
    parts = re.split(r"\n{2,}", raw)
    # Limpa e remove vazios
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return []
    # Junta micros (< min_chunk_chars) com o próximo
    merged: List[str] = []
    buf = ""
    for p in parts:
        if len(p) < min_chunk_chars and not buf:
            buf = p
            continue
        if buf:
            merged.append((buf + "\n\n" + p).strip())
            buf = ""
        else:
            merged.append(p)
    if buf:
        if merged:
            merged[-1] = (merged[-1] + "\n\n" + buf).strip()
        else:
            merged.append(buf)
    # Cap em max_chunks (overflow junta no último)
    if len(merged) > max_chunks:
        head = merged[: max_chunks - 1]
        tail = "\n\n".join(merged[max_chunks - 1:])
        merged = head + [tail]
    return merged


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


@router.post("/qr/refresh")
async def refresh_qr(user: dict = Depends(require_role("gestor"))):
    """Força a geração de um QR novo. Tenta primeiro /qr/refresh no sidecar;
    se não existir, faz logout + delay curto e retorna o /qr atual.
    """
    # 1) Tenta endpoint específico no sidecar (Baileys >= 6.7)
    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(f"{SIDECAR_BASE}/qr/refresh")
            if r.status_code < 400:
                return await _sidecar_get("/qr")
    except Exception as e:
        logger.info("[wa-baileys] /qr/refresh sidecar não disponível: %s", e)

    # 2) Fallback: logout + aguarda + busca novo QR
    try:
        await _sidecar_post("/logout")
    except Exception as e:
        logger.info("[wa-baileys] /logout falhou: %s", e)
    # pequeno delay para a sessão zerar e o sidecar gerar QR novo
    import asyncio as _asyncio
    await _asyncio.sleep(1.2)
    return await _sidecar_get("/qr")


@router.get("/status")
async def get_status(user: dict = Depends(require_role("gestor"))):
    return await _sidecar_get("/status")


class SendIn(BaseModel):
    phone: str = Field(..., min_length=8, max_length=25)
    text: str = Field(..., min_length=1, max_length=4096)


class SendAudioIn(BaseModel):
    phone: str = Field(..., min_length=8, max_length=25)
    audio_b64: str = Field(..., min_length=100, max_length=8 * 1024 * 1024)
    mimetype: Optional[str] = "audio/ogg; codecs=opus"
    duration_sec: Optional[float] = None


@router.post("/send-audio")
async def send_audio(payload: SendAudioIn,
                        user: dict = Depends(require_role("gestor"))):
    """Envia áudio gravado pelo navegador (MediaRecorder API) como voice note
    PTT no WhatsApp. Aceita base64 (default webm/opus do Chrome).

    Persiste mensagem outbound com `text="🎤 Áudio (Xs)"` e flag `media_type`.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    send_ok = False
    send_error: Optional[str] = None
    out: Dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=45.0) as cli:
            r = await cli.post(
                f"{SIDECAR_BASE}/send-audio",
                json={
                    "phone": payload.phone,
                    "audio_b64": payload.audio_b64,
                    "mimetype": payload.mimetype,
                },
            )
            try:
                out = r.json()
            except Exception:
                out = {"raw": r.text}
            if r.status_code < 400 and out.get("ok"):
                send_ok = True
            else:
                send_error = (out.get("error") or f"HTTP {r.status_code}")
    except httpx.HTTPError as e:
        logger.warning("[wa-baileys] sidecar /send-audio falhou: %s", e)
        send_error = str(e)

    dur_s = int(payload.duration_sec or 0)
    label = f"🎤 Áudio{f' ({dur_s}s)' if dur_s else ''}"

    # Persiste o arquivo no disco para playback inline no chat
    msg_id = f"wam-{uuid.uuid4().hex[:10]}"
    audio_url: Optional[str] = None
    try:
        # Detecta extensão pelo mimetype (webm/ogg/mp3/m4a/wav)
        mime = (payload.mimetype or "").lower()
        if "ogg" in mime:
            ext = "ogg"
        elif "mpeg" in mime or "mp3" in mime:
            ext = "mp3"
        elif "mp4" in mime or "m4a" in mime:
            ext = "m4a"
        elif "wav" in mime:
            ext = "wav"
        else:
            ext = "webm"
        audio_bytes = base64.b64decode(payload.audio_b64)
        out_path = WA_AUDIO_DIR / f"{msg_id}.{ext}"
        out_path.write_bytes(audio_bytes)
        audio_url = f"/api/whatsapp-baileys/audio/{msg_id}.{ext}"
    except Exception as e:
        logger.warning("[wa-baileys] save audio failed: %s", e)

    await db.aihub_wa_messages.insert_one({
        "id": msg_id,
        "company_id": cid,
        "direction": "outbound",
        "phone": payload.phone,
        "text": label,
        "media_type": "audio",
        "media_mimetype": payload.mimetype,
        "media_duration_sec": dur_s,
        "media_url": audio_url,
        "channel": "baileys",
        "message_id": out.get("message_id"),
        "created_at": now_iso(),
        "actor_user": user.get("email") or user.get("id"),
        "sent_by_user_id": user.get("id"),
        "auto_reply": False,
        "delivery_status": "sent" if send_ok else "failed",
        "delivery_error": send_error,
    })
    if not send_ok:
        raise HTTPException(
            status_code=502,
            detail=f"WhatsApp não enviou o áudio: {send_error or 'erro desconhecido'}",
        )
    return {"ok": True, "message_id": out.get("message_id"), "media_url": audio_url}


@router.get("/audio/{filename}")
async def get_audio_file(
    filename: str,
    t: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Serve o arquivo de áudio salvo pelo /send-audio para playback inline.

    Aceita token via Authorization Bearer ou via query param `?t=<token>`
    (necessário pra `<audio src=...>` que não envia headers).
    """
    # Sanitiza filename: msg_id.ext
    if not re.match(r"^wam-[a-f0-9]+\.(webm|ogg|mp3|m4a|wav)$", filename):
        raise HTTPException(400, "filename inválido")

    # Valida token (Bearer header OU query param)
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif t:
        token = t
    if not token:
        raise HTTPException(401, "Token requerido")
    try:
        from auth import decode_token
        decode_token(token)
    except Exception:
        raise HTTPException(401, "Token inválido")

    path = WA_AUDIO_DIR / filename
    if not path.exists():
        raise HTTPException(404, "Áudio não encontrado")
    ext = path.suffix.lstrip(".")
    media_type = {
        "webm": "audio/webm",
        "ogg": "audio/ogg",
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "wav": "audio/wav",
    }.get(ext, "audio/webm")
    return FileResponse(path, media_type=media_type)


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
        "channel": "baileys",
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


class SendImageIn(BaseModel):
    phone: str = Field(..., min_length=8, max_length=25)
    image_data_url: str = Field(..., min_length=20)
    caption: str = Field(default="", max_length=1024)


@router.post("/send-image")
async def send_image(payload: SendImageIn,
                       user: dict = Depends(require_role("gestor"))):
    """Envia uma imagem (data URL base64) via Baileys. Se o sidecar não
    suportar `/send-image`, ainda persiste no histórico como rascunho local
    para o gestor pelo menos manter o registro.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if not payload.image_data_url.startswith("data:image/"):
        raise HTTPException(400, "image_data_url precisa começar com 'data:image/'")
    send_ok = False
    send_error: Optional[str] = None
    out: Dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=30.0) as cli:
            r = await cli.post(f"{SIDECAR_BASE}/send-image",
                                json={"phone": payload.phone,
                                      "image_data_url": payload.image_data_url,
                                      "caption": payload.caption})
            try:
                out = r.json()
            except Exception:
                out = {"raw": r.text}
            if r.status_code == 404:
                send_error = "sidecar não suporta /send-image (atualize o serviço Baileys)"
            elif r.status_code < 400 and out.get("ok"):
                send_ok = True
            else:
                send_error = out.get("error") or f"HTTP {r.status_code}"
    except httpx.HTTPError as e:
        logger.warning("[wa-baileys] sidecar /send-image falhou: %s", e)
        send_error = str(e)

    await db.aihub_wa_messages.insert_one({
        "id": f"wam-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "direction": "outbound",
        "phone": payload.phone,
        "text": payload.caption or "[imagem]",
        "channel": "baileys",
        "media_type": "image",
        "media_data_url": payload.image_data_url[:200000],
        "message_id": out.get("message_id"),
        "created_at": now_iso(),
        "actor_user": user.get("email") or user.get("id"),
        "sent_by_user_id": user.get("id"),
        "auto_reply": False,
        "delivery_status": "sent" if send_ok else "failed",
        "delivery_error": send_error,
    })
    if not send_ok:
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
    # WhatsApp LID privacy (2025+)
    is_lid: bool = False
    lid: Optional[str] = None
    sender_pn: Optional[str] = None
    # Áudio inbound (PTT/voice note) — opcional, anexado pelo sidecar
    audio_b64: Optional[str] = None
    audio_mimetype: Optional[str] = None
    audio_duration_sec: Optional[int] = None
    audio_is_ptt: bool = False


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


# ---------------------------------------------------------------------------
# LID manual link — WhatsApp privacidade (jid@lid → telefone real)
# ---------------------------------------------------------------------------
class LidLinkIn(BaseModel):
    lid: str = Field(..., min_length=5, max_length=40)
    phone: str = Field(..., min_length=8, max_length=20)


@router.post("/lid-link")
async def lid_link(payload: LidLinkIn,
                    user: dict = Depends(require_role("gestor"))):
    """Vincula manualmente um LID (jid anônimo @lid) a um telefone real.

    Quando o cliente envia msg com privacidade LID ativada, o sidecar
    persiste a conversa usando o número LID (ex.: `169410773958706`)
    porque o telefone real fica oculto. Este endpoint permite ao gestor
    informar o telefone correto:
      1. Cria/atualiza wa_lid_map (LID → phone).
      2. Migra mensagens/conversas anteriores do LID para o novo phone.
      3. Mensagens futuras com o mesmo LID resolvem automaticamente.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    lid_raw = re.sub(r"\D", "", payload.lid)
    phone_raw = re.sub(r"\D", "", payload.phone)
    if not lid_raw or not phone_raw:
        raise HTTPException(400, "LID ou telefone inválido (apenas dígitos).")

    # 1. Cria mapping
    await db.wa_lid_map.update_one(
        {"company_id": cid, "lid": lid_raw},
        {"$set": {"phone": phone_raw, "source": "manual",
                  "linked_by_user_id": user.get("id"),
                  "linked_by_email": user.get("email"),
                  "linked_at": now_iso()}},
        upsert=True,
    )

    # 2. Migra mensagens existentes (phone == LID) para o novo phone
    msgs_result = await db.aihub_wa_messages.update_many(
        {"company_id": cid, "phone": lid_raw},
        {"$set": {"phone": phone_raw, "phone_is_lid": False,
                   "lid": lid_raw}},
    )
    # 3. Migra/merge a conversa
    old_conv = await db.wa_conversations.find_one(
        {"company_id": cid, "phone": lid_raw}, {"_id": 0},
    )
    if old_conv:
        await db.wa_conversations.delete_one(
            {"company_id": cid, "phone": lid_raw},
        )
        # Merge: campos do lid_conv aplicam só se não existirem na phone_conv
        merge_doc = {k: v for k, v in old_conv.items()
                      if k not in ("_id", "company_id", "phone")}
        merge_doc["phone_is_lid"] = False
        merge_doc["lid"] = lid_raw
        merge_doc["lid_linked_at"] = now_iso()
        await db.wa_conversations.update_one(
            {"company_id": cid, "phone": phone_raw},
            {"$set": merge_doc},
            upsert=True,
        )

    # 4. Auto-link com subscriber (se houver)
    subscriber_id = None
    try:
        from phone_normalizer import link_phone_to_subscriber
        link = await link_phone_to_subscriber(phone_raw, cid)
        if link:
            subscriber_id = link.get("subscriber_id")
    except Exception:
        pass

    logger.info("[wa-baileys] LID %s vinculado a %s (msgs migradas=%d) por %s",
                lid_raw, phone_raw, msgs_result.modified_count,
                user.get("email"))
    return {
        "ok": True,
        "lid": lid_raw,
        "phone": phone_raw,
        "messages_migrated": msgs_result.modified_count,
        "subscriber_id": subscriber_id,
    }


@router.get("/lid-map")
async def list_lid_mappings(user: dict = Depends(require_role("gestor"))):
    """Lista todos os mapeamentos LID→phone cadastrados."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    items = await db.wa_lid_map.find(
        {"company_id": cid}, {"_id": 0},
    ).sort("linked_at", -1).limit(200).to_list(200)
    return {"items": items, "total": len(items)}



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
    # Tem áudio? trate como mensagem válida mesmo sem texto.
    has_audio = bool(payload.audio_b64)
    if not payload.text.strip() and not has_audio:
        return {"ok": True, "ignored": "empty"}
    # Não responde em grupos (jid termina exatamente em @g.us)
    is_group = (payload.jid or "").endswith("@g.us")

    cid = DEMO_COMPANY_ID  # multi-tenant TODO

    # === LID resolution (WhatsApp privacy) ===
    # Quando o WhatsApp envia mensagem com privacidade LID, o jid vem como
    # `<lid>@lid` e o número real fica oculto. Tentamos resolver via:
    #   1. sender_pn (Baileys 6.7+ expõe em alguns casos)
    #   2. Mapeamento manual persistido em `wa_lid_map` (gestor vincula)
    # Se NADA resolve, mantemos o LID como identificador, mas marcamos a
    # conversa com `phone_is_lid=true` pra UI destacar e oferecer vínculo.
    effective_phone = payload.phone
    if payload.is_lid and payload.lid:
        if payload.sender_pn:
            effective_phone = payload.sender_pn
            # Persiste o mapping para futuras mensagens
            try:
                await db.wa_lid_map.update_one(
                    {"company_id": cid, "lid": payload.lid},
                    {"$set": {"phone": payload.sender_pn, "source": "sender_pn",
                              "linked_at": now_iso()}},
                    upsert=True,
                )
            except Exception:
                pass
        else:
            # Tenta resolver via mapping manual já cadastrado
            try:
                m = await db.wa_lid_map.find_one(
                    {"company_id": cid, "lid": payload.lid},
                    {"_id": 0, "phone": 1},
                )
                if m and m.get("phone"):
                    effective_phone = m["phone"]
            except Exception:
                pass

    subscriber_id = None
    subscriber_ctx = None
    try:
        from phone_normalizer import link_phone_to_subscriber
        link = await link_phone_to_subscriber(effective_phone, cid)
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

    # Persiste áudio inbound em disco (se veio do sidecar) e gera URL servida.
    media_type = None
    media_url = None
    media_duration_sec = None
    msg_id = f"wam-{uuid.uuid4().hex[:10]}"
    if has_audio:
        try:
            import base64
            mime = (payload.audio_mimetype or "audio/ogg").lower()
            if "webm" in mime:
                ext = "webm"
            elif "mp4" in mime or "m4a" in mime:
                ext = "m4a"
            elif "mpeg" in mime or "mp3" in mime:
                ext = "mp3"
            elif "wav" in mime:
                ext = "wav"
            else:
                ext = "ogg"
            WA_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            out_path = WA_AUDIO_DIR / f"{msg_id}.{ext}"
            out_path.write_bytes(base64.b64decode(payload.audio_b64))
            media_type = "audio"
            media_url = f"/api/whatsapp-baileys/audio/{msg_id}.{ext}"
            media_duration_sec = payload.audio_duration_sec
        except Exception as e:
            logger.warning("[wa-baileys] save inbound audio failed: %s", e)

    inbound_doc = {
        "id": msg_id,
        "company_id": cid,
        "direction": "inbound",
        "phone": effective_phone,
        "jid": payload.jid,
        "text": payload.text or (
            f"🎤 Áudio ({media_duration_sec}s)" if has_audio and media_duration_sec
            else ("🎤 Áudio" if has_audio else "")
        ),
        "channel": "baileys",
        "push_name": payload.push_name,
        "message_id": payload.message_id,
        "wa_timestamp": payload.timestamp,
        "subscriber_id": subscriber_id,
        "phone_is_lid": payload.is_lid and effective_phone == payload.lid,
        "lid": payload.lid,
        "created_at": now_iso(),
    }
    if media_type:
        inbound_doc["media_type"] = media_type
        inbound_doc["media_url"] = media_url
        inbound_doc["media_duration_sec"] = media_duration_sec
        inbound_doc["media_mimetype"] = payload.audio_mimetype
        inbound_doc["media_is_ptt"] = payload.audio_is_ptt
    await db.aihub_wa_messages.insert_one(inbound_doc)
    # Atualiza conv com flag LID quando aplicável
    if payload.is_lid:
        await db.wa_conversations.update_one(
            {"company_id": cid, "phone": effective_phone},
            {"$set": {
                "phone_is_lid": effective_phone == payload.lid,
                "lid": payload.lid,
            }},
            upsert=True,
        )
    logger.info("[wa-baileys] inbound %s%s (%s): %s",
                effective_phone,
                f" [LID={payload.lid}]" if payload.is_lid else "",
                payload.push_name, payload.text[:80])

    # --- Manager Assistant — gestor manda comando, IA executa ---
    # Intercepta ANTES do auto-reply para que mensagens do gestor não passem
    # pela IA de atendimento ao cliente.
    if not is_group:
        try:
            from services.manager_assistant import handle_manager_message
            mgr_reply = await handle_manager_message(
                cid, effective_phone, payload.text)
            if mgr_reply:
                # Envia resposta de volta via sidecar (usa JID original)
                try:
                    async with httpx.AsyncClient(timeout=12.0) as cli:
                        await cli.post(
                            f"{SIDECAR_BASE}/send",
                            json={"phone": payload.jid or effective_phone,
                                  "text": mgr_reply},
                        )
                except Exception as e:
                    logger.warning("[wa-baileys] manager reply send fail: %s", e)
                # Persistimos como outbound também
                await db.aihub_wa_messages.insert_one({
                    "id": f"wam-{uuid.uuid4().hex[:10]}",
                    "company_id": cid,
                    "direction": "outbound",
                    "phone": effective_phone,
                    "text": mgr_reply,
                    "created_at": now_iso(),
                    "metadata": {"manager_assistant": True},
                })
                return {"ok": True, "manager_assistant": True}
        except Exception as e:
            logger.warning("[wa-baileys] manager assistant falhou: %s", e)

    # --- Auto-reply (se habilitado) ---
    if not is_group:
        try:
            reply = await _maybe_auto_reply(
                cid=cid, phone=effective_phone,
                user_text=payload.text,
                subscriber_id=subscriber_id,
                subscriber_ctx=subscriber_ctx,
            )
            if reply:
                return {"ok": True, "subscriber_id": subscriber_id,
                        "phone": effective_phone, "lid": payload.lid,
                        "auto_reply": reply[:120]}
        except Exception as e:
            logger.warning("[wa-baileys] auto-reply falhou: %s", e)

        # --- Co-Pilot IA — dica interna para atendente humano ---
        # Só dispara quando a conversa está com humano (não-IA).
        # A IA de atendimento já tem injeção A2A própria via system_prompt.
        # NÃO dispara se acabou de ter um handover (< 30s) — geralmente
        # o cliente ainda não respondeu nada relevante após o "Olá, aqui é
        # o atendente". Evita gerar insights sobre o "Olá" automático.
        try:
            conv = await db.wa_conversations.find_one(
                {"company_id": cid, "phone": effective_phone},
                {"_id": 0, "assignee_role": 1, "status": 1, "handover_msg_at": 1},
            )
            recent_handover = False
            if conv and conv.get("handover_msg_at"):
                try:
                    t = datetime.fromisoformat(
                        conv["handover_msg_at"].replace("Z", "+00:00"))
                    age_s = (datetime.now(timezone.utc) - t).total_seconds()
                    recent_handover = age_s < 30  # 30 segundos
                except Exception:
                    pass
            if (conv and conv.get("assignee_role") == "human"
                    and conv.get("status") != "closed"
                    and not recent_handover):
                from services.copilot_ai import maybe_insert_copilot_hint
                await maybe_insert_copilot_hint(
                    company_id=cid,
                    phone=effective_phone,
                    last_inbound_text=payload.text,
                    last_inbound_id=payload.message_id,
                    subscriber_ctx=subscriber_ctx,
                )
        except Exception as e:
            logger.info("[wa-baileys] copilot skip: %s", e)

    return {"ok": True, "subscriber_id": subscriber_id,
            "phone": effective_phone, "lid": payload.lid}


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


async def _persist_ai_failure(cid: str, phone: str, subscriber_id: Optional[str],
                                reason_code: str, reason_msg: str,
                                user_text: str = "",
                                agent: Optional[dict] = None) -> None:
    """Persiste uma falha do auto-reply IA. Substitui o antigo `return None`
    silencioso. Cada falha vira um registro outbound com `delivery_status`
    iniciado por 'failed_' para que o frontend possa destacar."""
    doc = {
        "id": f"wam-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "direction": "outbound",
        "phone": phone,
        "text": "",  # nada foi enviado
        "channel": "baileys",
        "subscriber_id": subscriber_id,
        "session_id": f"wa-{phone}",
        "auto_reply": True,
        "delivery_status": f"failed_{reason_code}",
        "delivery_error": reason_msg[:300],
        "user_text_snapshot": (user_text or "")[:240],
        "created_at": now_iso(),
    }
    if agent:
        doc["agent_id"] = agent.get("id")
        doc["agent_name"] = agent.get("name")
    try:
        await db.aihub_wa_messages.insert_one(doc)
    except Exception as e:
        logger.warning("[wa-baileys] falha ao persistir failure: %s", e)
    # Dispara system_event se acumular ≥3 falhas em 24h (recurso já existente)
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        n = await db.aihub_wa_messages.count_documents({
            "company_id": cid, "direction": "outbound",
            "auto_reply": True,
            "delivery_status": {"$regex": "^failed_"},
            "created_at": {"$gte": cutoff},
        })
        if n >= 3:
            await db.wa_system_events.insert_one({
                "id": f"sys-{uuid.uuid4().hex[:10]}",
                "company_id": cid,
                "kind": "ai_attendant_unhealthy",
                "text": f"IA com {n} falha(s) nas últimas 24h · {reason_code}",
                "data": {"reason_code": reason_code, "failures_24h": n,
                         "last_reason": reason_msg[:120]},
                "created_at": now_iso(),
            })
    except Exception as e:
        logger.info("[wa-baileys] system_event ai_unhealthy skip: %s", e)


async def _maybe_auto_reply(cid: str, phone: str, user_text: str,
                              subscriber_id: Optional[str],
                              subscriber_ctx: Optional[str]) -> Optional[str]:
    """Se auto-reply estiver habilitado, gera resposta com a Jerusa
    e envia via sidecar. Retorna o texto enviado (ou None se desligado).

    Cada caminho de falha persiste um registro com `delivery_status`
    `failed_*` para que o gestor enxergue o problema no painel.
    """
    # 0. Se humano assumiu essa conversa, NÃO responde com IA — exceto
    # quando o atendente está INATIVO há > 30min (conversa órfã).
    # Nesse caso devolvemos para a IA automaticamente e seguimos.
    conv = await db.wa_conversations.find_one(
        {"company_id": cid, "phone": phone}, {"_id": 0}
    )
    if conv and conv.get("assignee_role") == "human" and conv.get("status") != "closed":
        # Verifica última msg outbound DO HUMANO atendente (ignora handover automatic).
        last_human_msg = await db.aihub_wa_messages.find_one(
            {"company_id": cid, "phone": phone,
             "direction": "outbound", "auto_reply": {"$ne": True},
             "is_handover_message": {"$ne": True}},
            {"_id": 0, "created_at": 1}, sort=[("created_at", -1)]
        )
        # Janela de "abandono": 30 minutos sem msg humana
        IDLE_LIMIT_MIN = 30
        idle_too_long = False
        try:
            from datetime import datetime, timezone, timedelta
            ref_iso = (last_human_msg or {}).get("created_at") \
                       or conv.get("assignee_assigned_at") \
                       or conv.get("updated_at")
            if ref_iso:
                ref_dt = datetime.fromisoformat(ref_iso.replace("Z", "+00:00"))
                idle_too_long = (datetime.now(timezone.utc) - ref_dt) \
                                  > timedelta(minutes=IDLE_LIMIT_MIN)
        except Exception:
            idle_too_long = False

        if idle_too_long:
            # AUTO-RELEASE — atendente abandonou. Devolve pra IA.
            await db.wa_conversations.update_one(
                {"company_id": cid, "phone": phone},
                {"$set": {
                    "assignee_role": "ai",
                    "assignee_user_id": None,
                    "auto_released_at": now_iso(),
                    "auto_release_reason": f"humano inativo há >{IDLE_LIMIT_MIN}min",
                    "updated_at": now_iso(),
                }},
            )
            logger.info(
                "[wa-baileys] AUTO-RELEASE — atendente inativo há >%dmin, "
                "devolvendo %s pra IA", IDLE_LIMIT_MIN, phone
            )
            # Continua o fluxo — IA responde normalmente abaixo.
            conv = None
        else:
            logger.info(
                "[wa-baileys] auto-reply pulado — humano atendendo (%s)", phone
            )
            return None  # NÃO é falha — humano assumiu intencionalmente

    # 1. Lê config de auto-reply
    cfg = await db.aihub_settings.find_one(
        {"company_id": cid, "key": "whatsapp_auto_reply"}, {"_id": 0}
    )
    if not cfg or not cfg.get("enabled"):
        await _persist_ai_failure(
            cid, phone, subscriber_id,
            reason_code="disabled",
            reason_msg=("Auto-reply do WhatsApp está DESLIGADO em "
                        "Atendimento IA → WhatsApp. Cliente mandou mensagem "
                        "mas a Isabela não responde até ser reativada."),
            user_text=user_text,
        )
        return None

    # 2. Carrega o agente (Jerusa por padrão, ou outro definido em cfg)
    agent_name = cfg.get("agent_name") or "Jerusa"
    default_agent = await db.aihub_agents.find_one(
        {"company_id": cid, "name": agent_name, "active": {"$ne": False}},
        {"_id": 0},
    )
    if not default_agent:
        # Cria Jerusa se ainda não existir (mesma lógica de voice.py)
        try:
            from routes.voice import _ensure_jerusa_agent
            default_agent = await _ensure_jerusa_agent(cid)
        except Exception as e:
            await _persist_ai_failure(
                cid, phone, subscriber_id,
                reason_code="no_agent",
                reason_msg=(f"Agente '{agent_name}' não cadastrado/desativado "
                            f"e bootstrap falhou: {e}"),
                user_text=user_text,
            )
            return None
        if not default_agent:
            await _persist_ai_failure(
                cid, phone, subscriber_id,
                reason_code="no_agent",
                reason_msg=(f"Agente '{agent_name}' não cadastrado nem "
                            "criado automaticamente."),
                user_text=user_text,
            )
            return None

    # 2b. Roteador IA — se houver múltiplos agentes ativos, escolhe o melhor
    # baseado em routing_intent. Em conversas existentes, mantém o agente
    # escolhido anteriormente (consistência).
    try:
        from services.routing import pick_agent_for_message
        agent = await pick_agent_for_message(cid, phone, user_text,
                                              default_agent=default_agent)
    except Exception as e:
        logger.info("[wa-baileys] routing fallback (%s)", e)
        agent = default_agent
    if not agent:
        agent = default_agent

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
                # CRÍTICO: atualiza o subscriber_id local pra que o bloco
                # 3a-bis (check_connection) saiba que o cliente está agora
                # identificado e possa rodar a verificação técnica NA MESMA
                # resposta — sem obrigar o cliente a repetir a reclamação.
                subscriber_id = ident_sub.get("id")
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

    # 3a-bis. VERIFICAÇÃO PROATIVA DA CONEXÃO DO CLIENTE — Quando o cliente
    # reclamar de problema/defeito/internet caiu E o cliente está identificado,
    # consultamos o SmartOLT em tempo real e injetamos o status REAL (Online /
    # Offline / LOS / Power fail + sinal RX/TX). A IA responde a VERDADE — sem
    # alucinação. Quando NÃO identificado, a IA pede CPF primeiro (já tratado
    # no bloco 3 — handle_unidentified_inbound).
    #
    # Rastreamos também se o cliente FALOU de problema nas últimas 5 mensagens
    # do histórico — se o cliente reclamou ANTES, mandou o CPF, e a IA acabou
    # de identificar AGORA, queremos rodar o check_connection JÁ NA MESMA
    # RESPOSTA (em vez de obrigar o cliente a repetir a reclamação).
    try:
        from services.subscriber_connection import (
            is_problem_intent, check_connection_for_phone, format_for_prompt,
        )
        cur_msg_has_problem = is_problem_intent(user_text)

        # Se a msg atual já tem o intent: usa direto.
        # Senão, e se o cliente acabou de ser identificado por CPF, olhamos as
        # últimas 5 inbound dele pra ver se reclamou de defeito.
        should_run_check = cur_msg_has_problem
        had_recent_problem = False
        if not cur_msg_has_problem and subscriber_id:
            # Cliente já identificado nesta resposta — talvez veio do fluxo CPF
            recent = db.aihub_wa_messages.find(
                {"company_id": cid, "phone": phone, "direction": "inbound"},
                {"_id": 0, "text": 1, "created_at": 1}
            ).sort([("created_at", -1)]).limit(5)
            async for m in recent:
                t = m.get("text") or ""
                if is_problem_intent(t):
                    had_recent_problem = True
                    should_run_check = True
                    break

        if should_run_check and subscriber_id:
            # Cliente IDENTIFICADO → verifica de verdade.
            # Passa subscriber_id direto pra suportar caso recém-CPF-identificado
            # (em que subscriber_phones ainda não foi atualizado).
            conn_info = await check_connection_for_phone(
                cid, phone, subscriber_id=subscriber_id
            )
            extra.append(format_for_prompt(conn_info))
            conn_info["subscriber_id"] = subscriber_id

            # AÇÃO REAL — estratégia diferenciada por status:
            #   - LOS / Offline: TENTAR REBOOT REMOTO PRIMEIRO. Se OK, peça
            #     pro cliente aguardar 2min. Só abre ticket se NÃO conseguiu
            #     rebootar (problema físico) ou se já foi reiniciado
            #     recentemente.
            #   - Power fail: NÃO é problema nosso (queda de luz no cliente).
            #     Ofereça agendamento de visita técnica.
            status_l = (conn_info.get("status") or "").strip().lower()
            try:
                from services.subscriber_connection import (
                    REBOOT_FIRST_STATUSES, try_reboot_onu, ensure_repair_ticket,
                    format_ticket_for_prompt, format_reboot_for_prompt,
                    format_power_fail_offer_for_prompt,
                )
                if conn_info.get("found") and status_l in REBOOT_FIRST_STATUSES:
                    # Tenta reboot remoto. Se OK e é a primeira vez agora,
                    # NÃO abre ticket — espera o cliente confirmar se voltou.
                    reboot_info = await try_reboot_onu(cid, conn_info, phone)
                    if reboot_info.get("action") == "rebooted":
                        # Reset bem-sucedido — instrui IA a aguardar feedback
                        extra.append(format_reboot_for_prompt(reboot_info))
                    elif reboot_info.get("action") == "skipped_recent":
                        # Já tentou recentemente — abre ticket
                        extra.append(format_reboot_for_prompt(reboot_info))
                        ticket_info = await ensure_repair_ticket(
                            cid, conn_info, phone, user_text
                        )
                        if ticket_info:
                            extra.append(format_ticket_for_prompt(ticket_info))
                    else:
                        # Reboot falhou (SmartOLT desabilitado/erro) — abre ticket
                        ticket_info = await ensure_repair_ticket(
                            cid, conn_info, phone, user_text
                        )
                        if ticket_info:
                            extra.append(format_ticket_for_prompt(ticket_info))
                elif conn_info.get("found") and status_l in {"power fail", "powerfail"}:
                    # Cliente sem energia — instrui IA a oferecer agendamento
                    # E cria ticket com priority=padrao (não é prioridade pq
                    # problema é do lado do cliente, não da rede). Isso evita
                    # mentira: a IA promete agendar, e o ticket REALMENTE existe
                    # no Kanban pra o atendente confirmar.
                    extra.append(format_power_fail_offer_for_prompt())
                    ticket_info = await ensure_repair_ticket(
                        cid, conn_info, phone, user_text
                    )
                    if ticket_info:
                        extra.append(format_ticket_for_prompt(ticket_info))
            except Exception as e:
                logger.info("[wa-baileys] auto-action skip: %s", e)

            logger.info(
                "[wa-baileys] connection check phone=%s sub=%s found=%s connected=%s "
                "status=%s (cur_intent=%s recent_intent=%s)",
                phone, subscriber_id, conn_info.get("found"),
                conn_info.get("connected"), conn_info.get("status"),
                cur_msg_has_problem, had_recent_problem
            )
        elif cur_msg_has_problem and not subscriber_id:
            # NÃO IDENTIFICADO + reclamou de problema → NÃO inventa.
            # Instrui a IA a explicar que vai verificar APÓS receber o CPF.
            extra.append(
                "=== RECLAMAÇÃO DE PROBLEMA SEM IDENTIFICAÇÃO ===\n"
                "O cliente está reclamando de problema/defeito na conexão, "
                "MAS este telefone NÃO está vinculado a nenhum assinante. "
                "AÇÃO OBRIGATÓRIA:\n"
                "1. NÃO INVENTE o status da conexão dele. NÃO diga 'verifiquei "
                "   e está online' nem 'parece estar tudo bem' — você NÃO "
                "   verificou nada e seria mentira.\n"
                "2. Reconheça o problema com empatia.\n"
                "3. Diga que pra fazer a verificação técnica em tempo real você "
                "   precisa do CPF do titular (segurança).\n"
                "4. PROMETA: 'Assim que confirmar seu CPF, eu verifico aqui "
                "   mesmo a qualidade do seu sinal e te respondo com a verdade.'\n"
                "5. Peça o CPF de forma natural (sem ser robótico)."
            )
            logger.info(
                "[wa-baileys] problem intent but unidentified phone=%s — "
                "instructed AI to request CPF first", phone
            )
    except Exception as e:
        logger.info("[wa-baileys] connection check skip: %s", e)

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
    # 3c. Memória de correções — exemplos do que NÃO fazer (Edit & Teach)
    try:
        from routes.ai_corrections import (fetch_recent_for_prompt,
                                              format_corrections_for_prompt)
        corr_items = await fetch_recent_for_prompt(cid, limit=12)
        corr_block = format_corrections_for_prompt(corr_items)
        if corr_block:
            extra.append(corr_block)
    except Exception as e:
        logger.info("[wa-baileys] corrections injection skip: %s", e)

    # 3e. Orquestração com outras IAs (Motor IA / Coach / Avaliador) —
    # consulta serviços auxiliares pra IA responder INFORMADA, não genérica.
    try:
        from services.ai_orchestrator import build_orchestrated_context
        orchestrated = await build_orchestrated_context(
            cid, phone, user_text, subscriber_id=subscriber_id
        )
        if orchestrated:
            extra.append(orchestrated)
    except Exception as e:
        logger.info("[wa-baileys] orchestrator skip: %s", e)

    # 3f. Briefing da Disparo IA — se este cliente recebeu campanha ativa
    # nos últimos 14d, injeta o briefing específico da campanha pra Isabella
    # seguir o tom/objeções/escalada definidos pela Disparo IA.
    try:
        from services.disparo_briefing import fetch_disparo_briefing_for_phone
        disparo_block = await fetch_disparo_briefing_for_phone(cid, phone)
        if disparo_block:
            extra.append(disparo_block)
            logger.info(
                "[wa-baileys] disparo_ia briefing injetado p/ phone=%s", phone,
            )
    except Exception as e:
        logger.info("[wa-baileys] disparo briefing skip: %s", e)

    sys_prompt += "\n\n" + "\n\n".join(extra)

    # 3d. Histórico de conversa (janela 100, truncate por tokens)
    try:
        from services.ai_history import fetch_history_turns
        history_turns = await fetch_history_turns(cid, phone, limit=100,
                                                    token_budget=6000)
    except Exception as e:
        logger.info("[wa-baileys] history fetch skip: %s", e)
        history_turns = []

    # 4. Chama LLM via Motor IA (OpenRouter)
    try:
        from services.motor_ia import chat_completion
    except ImportError as e:
        await _persist_ai_failure(
            cid, phone, subscriber_id, agent=agent,
            reason_code="motor_ia_unavailable",
            reason_msg=f"services.motor_ia indisponível: {e}",
            user_text=user_text,
        )
        return None
    try:
        # Monta lista de mensagens: system → histórico → user atual (se ainda não estiver no histórico)
        chat_messages = [{"role": "system", "content": sys_prompt}]
        chat_messages.extend(history_turns)
        # Se o último turn do histórico não for o user_text atual, adiciona
        if not history_turns or history_turns[-1].get("content") != user_text:
            chat_messages.append({"role": "user", "content": user_text})

        # 🟢 Marca a IA como "digitando..." (TTL de 45s) — frontend exibe
        # "Isabella digitando..." enquanto este flag estiver no futuro.
        try:
            await db.wa_conversations.update_one(
                {"company_id": cid, "phone": phone},
                {"$set": {
                    "ai_typing_until": (datetime.now(timezone.utc)
                                          + timedelta(seconds=45)).isoformat(),
                    "ai_typing_agent": agent.get("name") or "Isabella IA",
                }},
                upsert=True,
            )
        except Exception:
            pass

        result = await chat_completion(
            cid,
            messages=chat_messages,
            temperature=agent.get("temperature", 0.6),
            max_tokens=agent.get("max_tokens", 350),
            purpose="atendimento",
            agent="isabella_whatsapp",
        )
        reply_text = (result.get("content") or "").strip()
    except Exception as e:
        # Limpa flag de digitando em caso de erro
        try:
            await db.wa_conversations.update_one(
                {"company_id": cid, "phone": phone},
                {"$unset": {"ai_typing_until": "", "ai_typing_agent": ""}},
            )
        except Exception:
            pass
        await _persist_ai_failure(
            cid, phone, subscriber_id, agent=agent,
            reason_code="llm_error",
            reason_msg=f"Motor IA falhou ({type(e).__name__}): {e}",
            user_text=user_text,
        )
        return None

    if not reply_text:
        # Limpa flag de digitando
        try:
            await db.wa_conversations.update_one(
                {"company_id": cid, "phone": phone},
                {"$unset": {"ai_typing_until": "", "ai_typing_agent": ""}},
            )
        except Exception:
            pass
        await _persist_ai_failure(
            cid, phone, subscriber_id, agent=agent,
            reason_code="empty_reply",
            reason_msg="LLM retornou resposta vazia — possível bloqueio de "
                        "safety, prompt incompleto ou modelo confuso.",
            user_text=user_text,
        )
        return None

    # 5. Quebra a resposta da IA em múltiplas bolhas (paragraphs separados por
    # "\n\n" ou marcador explícito "---") para enviar como mensagens distintas.
    # Mantém a sensação de "ela mandou 3 mensagens" em vez de um parágrafo
    # gigante numa bolha só. Cap de 6 chunks pra evitar spam — overflow vira
    # 1 último chunk com o restante.
    chunks = _split_ai_reply(reply_text, max_chunks=6)

    # 6. Envia cada chunk via sidecar (sequencial, pequeno delay entre eles).
    import asyncio as _asyncio
    any_sent = False
    last_send_error: Optional[str] = None
    for idx, chunk in enumerate(chunks):
        send_ok = False
        send_error: Optional[str] = None
        send_body: Dict[str, Any] = {}
        try:
            async with httpx.AsyncClient(timeout=15.0) as cli:
                send_r = await cli.post(f"{SIDECAR_BASE}/send",
                                         json={"phone": phone, "text": chunk})
                try:
                    send_body = send_r.json()
                except Exception:
                    send_body = {"raw": send_r.text}
                if send_r.status_code < 400 and send_body.get("ok"):
                    send_ok = True
                    any_sent = True
                else:
                    send_error = (send_body.get("error")
                                  or f"HTTP {send_r.status_code}")
                    last_send_error = send_error
        except Exception as e:
            logger.warning("[wa-baileys] sidecar /send falhou: %s", e)
            send_error = str(e)
            last_send_error = send_error

        # Persiste cada bolha como linha separada (assim o chat mostra 1 bolha
        # por mensagem, idêntico ao que o cliente recebe no WhatsApp).
        await db.aihub_wa_messages.insert_one({
            "id": f"wam-{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "direction": "outbound",
            "phone": phone,
            "text": chunk,
            "channel": "baileys",
            "message_id": send_body.get("message_id"),
            "subscriber_id": subscriber_id,
            "agent_id": agent["id"],
            "agent_name": agent["name"],
            "session_id": f"wa-{phone}",
            "auto_reply": True,
            "chunk_index": idx,
            "chunk_total": len(chunks),
            "delivery_status": "sent" if send_ok else "failed_sidecar",
            "delivery_error": send_error,
            "created_at": now_iso(),
        })
        # Pequeno delay entre bolhas pra não saturar o sidecar/WhatsApp e
        # gerar uma cadência mais "humana".
        if idx < len(chunks) - 1 and send_ok:
            await _asyncio.sleep(0.6)

    send_ok = any_sent
    send_error = last_send_error
    if send_ok:
        logger.info("[wa-baileys] auto-reply enviado em %d bolha(s) para %s: %s",
                     len(chunks), phone, reply_text[:80])
    else:
        logger.warning("[wa-baileys] auto-reply gerado mas envio falhou (%s): %s",
                        send_error, reply_text[:80])
        # Registra system_event se acumular falhas de sidecar
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            n = await db.aihub_wa_messages.count_documents({
                "company_id": cid, "direction": "outbound",
                "delivery_status": {"$regex": "^failed_"},
                "created_at": {"$gte": cutoff},
            })
            if n >= 3:
                await db.wa_system_events.insert_one({
                    "id": f"sys-{uuid.uuid4().hex[:10]}",
                    "company_id": cid,
                    "kind": "ai_attendant_unhealthy",
                    "text": f"IA com {n} falha(s) de envio (sidecar) em 24h",
                    "data": {"reason_code": "sidecar", "failures_24h": n,
                             "last_reason": (send_error or "")[:120]},
                    "created_at": now_iso(),
                })
        except Exception as e:
            logger.info("[wa-baileys] sidecar event skip: %s", e)
    # 🔵 Limpa flag de "Isabella digitando..." após o envio (sucesso ou falha).
    try:
        await db.wa_conversations.update_one(
            {"company_id": cid, "phone": phone},
            {"$unset": {"ai_typing_until": "", "ai_typing_agent": ""}},
        )
    except Exception:
        pass
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
# AI Health — diagnóstico do Atendimento IA (Isabela/Jerusa)
# ---------------------------------------------------------------------------
@router.get("/ai-health")
async def ai_health(user: dict = Depends(require_role("gestor"))):
    """Diagnóstico completo da Isabela: por que ela responde ou não.

    Retorna `status` global (healthy | degraded | down) + razões objetivas
    para que o gestor enxergue exatamente onde o atendimento IA falha.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    cutoff_1h = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    # 1. Auto-reply config
    cfg = await db.aihub_settings.find_one(
        {"company_id": cid, "key": "whatsapp_auto_reply"}, {"_id": 0}
    ) or {"enabled": False, "agent_name": "Jerusa"}
    auto_reply_enabled = bool(cfg.get("enabled", False))
    agent_name = cfg.get("agent_name") or "Jerusa"

    # 2. Agente ativo
    agent = await db.aihub_agents.find_one(
        {"company_id": cid, "name": agent_name, "active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1, "model": 1, "active": 1},
    )
    agent_active = bool(agent)

    # 3. Motor IA configurado
    motor_cfg = await db.motor_ia_config.find_one(
        {"company_id": cid}, {"_id": 0, "enabled": 1, "openrouter_api_key": 1,
                              "default_text_model": 1}
    ) or {}
    motor_ia_configured = bool(motor_cfg.get("enabled")
                                and motor_cfg.get("openrouter_api_key"))

    # 4. Sidecar status (WhatsApp connected?)
    sidecar_status = "unknown"
    sidecar_error: Optional[str] = None
    try:
        async with httpx.AsyncClient(timeout=4.0) as cli:
            r = await cli.get(f"{SIDECAR_BASE}/status")
            if r.status_code < 400:
                body = r.json()
                sidecar_status = ("connected" if body.get("connected")
                                  else (body.get("state") or "disconnected"))
            else:
                sidecar_status = f"http_{r.status_code}"
                sidecar_error = (r.text or "")[:200]
    except Exception as e:
        sidecar_status = "unreachable"
        sidecar_error = str(e)[:200]

    # 5. Sucesso/falha últimas 24h
    last_ok = await db.aihub_wa_messages.find_one(
        {"company_id": cid, "direction": "outbound",
         "delivery_status": "sent", "auto_reply": True},
        {"_id": 0, "created_at": 1, "phone": 1, "text": 1},
        sort=[("created_at", -1)],
    )
    last_fail = await db.aihub_wa_messages.find_one(
        {"company_id": cid, "direction": "outbound",
         "delivery_status": {"$regex": "^failed_"}, "auto_reply": True},
        {"_id": 0, "created_at": 1, "phone": 1, "delivery_status": 1,
         "delivery_error": 1},
        sort=[("created_at", -1)],
    )
    failures_24h = await db.aihub_wa_messages.count_documents({
        "company_id": cid, "direction": "outbound",
        "delivery_status": {"$regex": "^failed_"}, "auto_reply": True,
        "created_at": {"$gte": cutoff_24h},
    })
    failures_1h = await db.aihub_wa_messages.count_documents({
        "company_id": cid, "direction": "outbound",
        "delivery_status": {"$regex": "^failed_"}, "auto_reply": True,
        "created_at": {"$gte": cutoff_1h},
    })
    ok_24h = await db.aihub_wa_messages.count_documents({
        "company_id": cid, "direction": "outbound",
        "delivery_status": "sent", "auto_reply": True,
        "created_at": {"$gte": cutoff_24h},
    })

    # 6. Razões e status overall
    reasons: List[Dict[str, str]] = []
    if not auto_reply_enabled:
        reasons.append({"code": "auto_reply_off", "severity": "high",
                         "message": "Auto-reply do WhatsApp está DESLIGADO. "
                                    "Cliente manda mensagem mas a IA não responde."})
    if not agent_active:
        reasons.append({"code": "no_agent", "severity": "high",
                         "message": f"Agente '{agent_name}' não cadastrado ou desativado."})
    if not motor_ia_configured:
        reasons.append({"code": "no_motor_ia", "severity": "high",
                         "message": "Motor IA (OpenRouter) não configurado em "
                                    "Sistema → Motor IA."})
    if sidecar_status not in ("connected", "open"):
        reasons.append({"code": "sidecar_down", "severity": "high",
                         "message": f"WhatsApp sidecar não conectado (status={sidecar_status}). "
                                    f"{(sidecar_error or '')[:120]}"})
    if failures_1h >= 3:
        reasons.append({"code": "high_recent_failures", "severity": "high",
                         "message": f"{failures_1h} falha(s) na última hora."})
    elif failures_24h >= 3:
        reasons.append({"code": "elevated_failures", "severity": "medium",
                         "message": f"{failures_24h} falha(s) nas últimas 24h."})

    if any(r["severity"] == "high" for r in reasons):
        status = "down"
    elif reasons:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "auto_reply_enabled": auto_reply_enabled,
        "agent_name": agent_name,
        "agent_active": agent_active,
        "agent_model": (agent or {}).get("model"),
        "motor_ia_configured": motor_ia_configured,
        "motor_ia_model": motor_cfg.get("default_text_model"),
        "sidecar_status": sidecar_status,
        "sidecar_error": sidecar_error,
        "stats_24h": {"sent": ok_24h, "failed": failures_24h, "failed_1h": failures_1h},
        "last_ok": last_ok and {
            "at": last_ok.get("created_at"), "phone": last_ok.get("phone"),
            "preview": (last_ok.get("text") or "")[:80],
        },
        "last_fail": last_fail and {
            "at": last_fail.get("created_at"), "phone": last_fail.get("phone"),
            "status": last_fail.get("delivery_status"),
            "error": (last_fail.get("delivery_error") or "")[:160],
        },
        "reasons": reasons,
        "checked_at": now_iso(),
    }


# ---------------------------------------------------------------------------
# Routing Dashboard — estatísticas multi-agente
# ---------------------------------------------------------------------------
@router.get("/routing-stats")
async def routing_stats(days: int = 7, user: dict = Depends(require_role("gestor"))):
    """Estatísticas de roteamento por agente nos últimos N dias.

    - Conta respostas outbound auto-reply agrupadas por `agent_name`
    - Distribuição percentual (qual agente está respondendo mais)
    - Top routing_reason (single_agent / keyword / llm / fallback)
    - Conversas com handoff humano (status=closed e human_assignee_id present)
    - Taxa de falhas por agente
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Por agente: total respostas, sucessos, falhas
    pipeline_agents = [
        {"$match": {
            "company_id": cid, "direction": "outbound",
            "auto_reply": True, "created_at": {"$gte": cutoff},
            "agent_name": {"$ne": None},
        }},
        {"$group": {
            "_id": "$agent_name",
            "total": {"$sum": 1},
            "sent": {"$sum": {"$cond": [{"$eq": ["$delivery_status", "sent"]}, 1, 0]}},
            "failed": {"$sum": {"$cond": [
                {"$regexMatch": {"input": {"$ifNull": ["$delivery_status", ""]},
                                  "regex": "^failed_"}}, 1, 0]}},
            "last_at": {"$max": "$created_at"},
        }},
        {"$sort": {"total": -1}},
    ]
    by_agent_raw = []
    async for r in db.aihub_wa_messages.aggregate(pipeline_agents):
        by_agent_raw.append({
            "agent_name": r["_id"],
            "total": r["total"],
            "sent": r["sent"],
            "failed": r["failed"],
            "last_at": r.get("last_at"),
        })
    total_all = sum(a["total"] for a in by_agent_raw) or 1
    by_agent = [{
        **a,
        "pct": round(100 * a["total"] / total_all, 1),
        "success_rate": round(100 * a["sent"] / a["total"], 1) if a["total"] else 0,
    } for a in by_agent_raw]

    # Distribuição de motivos de roteamento
    reasons_pipeline = [
        {"$match": {"company_id": cid, "routed_at": {"$gte": cutoff},
                     "routed_reason": {"$ne": None}}},
        {"$group": {"_id": "$routed_reason", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    by_reason = []
    async for r in db.wa_conversations.aggregate(reasons_pipeline):
        by_reason.append({"reason": r["_id"], "count": r["count"]})

    # Total conversas roteadas no período
    total_routed = await db.wa_conversations.count_documents({
        "company_id": cid,
        "routed_at": {"$gte": cutoff},
    })

    # Handoffs para humano (assignee_role=human nas conversas ativas)
    human_handoffs = await db.wa_conversations.count_documents({
        "company_id": cid,
        "assignee_role": "human",
        "last_inbound_at": {"$gte": cutoff},
    })

    # Lista de agentes cadastrados com routing_intent (para o gestor visualizar
    # quais estão configurados)
    agents_meta = []
    async for a in db.aihub_agents.find(
        {"company_id": cid},
        {"_id": 0, "id": 1, "name": 1, "active": 1, "routing_intent": 1, "model_name": 1},
    ):
        agents_meta.append({
            "id": a["id"], "name": a["name"],
            "active": a.get("active", True),
            "model_name": a.get("model_name"),
            "routing_intent": (a.get("routing_intent") or "")[:200],
            "has_routing_intent": bool((a.get("routing_intent") or "").strip()),
        })

    return {
        "period_days": days,
        "total_responses": total_all if by_agent_raw else 0,
        "total_routed_conversations": total_routed,
        "human_handoffs": human_handoffs,
        "by_agent": by_agent,
        "by_reason": by_reason,
        "agents_meta": agents_meta,
        "checked_at": now_iso(),
    }


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


class WallpaperIn(BaseModel):
    image_data_url: Optional[str] = Field(None, max_length=8_000_000)


@router.get("/wallpaper")
async def get_wallpaper(user: dict = Depends(require_role("gestor"))):
    """Retorna o papel de parede customizado do chat WhatsApp da empresa.

    Se nenhum estiver setado, retorna `image_data_url=None` e o frontend
    cai no default estático `/wa-wallpaper-ligo.png`.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await db.aihub_settings.find_one(
        {"company_id": cid, "key": "wa_chat_wallpaper"}, {"_id": 0}
    ) or {}
    return {
        "image_data_url": cfg.get("image_data_url"),
        "updated_at": cfg.get("updated_at"),
        "updated_by": cfg.get("updated_by"),
    }


@router.put("/wallpaper")
async def set_wallpaper(payload: WallpaperIn,
                          user: dict = Depends(require_role("gestor"))):
    """Salva (ou limpa, se `image_data_url=None`) o papel de parede do chat
    WhatsApp da empresa. Limite: 8 MB em data URL base64."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    url = payload.image_data_url
    if url and not url.startswith("data:image/"):
        raise HTTPException(400, "image_data_url deve ser data:image/...")
    await db.aihub_settings.update_one(
        {"company_id": cid, "key": "wa_chat_wallpaper"},
        {"$set": {
            "company_id": cid,
            "key": "wa_chat_wallpaper",
            "image_data_url": url,
            "updated_at": now_iso(),
            "updated_by": user.get("email") or user.get("id"),
        }},
        upsert=True,
    )
    logger.info("[wa-baileys] wallpaper %s por %s",
                 "removido" if not url else "atualizado",
                 user.get("email"))
    return {"ok": True}



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


async def _bucket_for_conversation(conv: dict, company_id: str = "") -> str:
    """Decide o bucket FocusChat baseado nos atributos da conversa.

    Buckets:
    - "grupo": JID termina em @g.us
    - "automatico": atualmente sendo respondida pela IA
    - "manual": atribuída a um humano
    - "aguardando": sem resposta humana há mais de 5min (e sem auto-reply)
    - "fora_de_hora": chegou fora do horário comercial configurado
    """
    if conv.get("is_group"):
        return "grupo"
    assignee_role = conv.get("assignee_role")
    if assignee_role == "ai":
        return "automatico"
    last_inbound = conv.get("last_inbound_at")
    if assignee_role == "human" and conv.get("assignee_user_id"):
        return "manual"
    if last_inbound:
        try:
            t = datetime.fromisoformat(last_inbound.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - t).total_seconds()
            # Tenta usar a configuração de business hours (cache simples)
            if company_id:
                try:
                    from routes.whatsapp_config import is_outside_business_hours
                    if await is_outside_business_hours(company_id):
                        return "fora_de_hora"
                except Exception:
                    # fallback ao default 8h-22h BRT
                    hour_brt = (datetime.now(timezone.utc) - timedelta(hours=3)).hour
                    if hour_brt < 8 or hour_brt >= 22:
                        return "fora_de_hora"
            else:
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
            "last_channel": {"$first": "$channel"},
            "last_inbound_at": {"$first": {"$cond": [
                {"$eq": ["$direction", "inbound"]}, "$created_at", None
            ]}},
            "push_name": {"$first": "$push_name"},
            "subscriber_id": {"$first": "$subscriber_id"},
            "msg_count": {"$sum": 1},
            "channels_used": {"$addToSet": "$channel"},
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
        {"$sort": {"created_at": -1}},
        {"$group": {"_id": "$phone",
                     "last_out_at": {"$first": "$created_at"},
                     "last_out_status": {"$first": "$delivery_status"},
                     "last_out_error": {"$first": "$delivery_error"}}},
    ]
    last_out_map: Dict[str, Dict[str, Any]] = {}
    async for r in db.aihub_wa_messages.aggregate(last_out_pipeline):
        last_out_map[r["_id"]] = {
            "at": r.get("last_out_at"),
            "status": r.get("last_out_status"),
            "error": r.get("last_out_error"),
        }

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
        last_out_info = last_out_map.get(phone) or {}
        last_out_at = last_out_info.get("at")
        last_out_status = last_out_info.get("status")
        last_out_error = last_out_info.get("error")
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
            # Última resposta IA — para exibir chip de falha na lista
            "last_outbound_status": last_out_status,
            "last_outbound_error": last_out_error,
            # WhatsApp LID privacy
            "phone_is_lid": conv.get("phone_is_lid", False),
            "lid": conv.get("lid"),
            "lid_linked_at": conv.get("lid_linked_at"),
            # Canal de origem (Baileys / Twilio / Meta) — quando o mesmo
            # telefone fala por canais diferentes, o gestor/IA precisa saber
            "last_channel": r.get("last_channel") or "baileys",
            "channels_used": [c for c in (r.get("channels_used") or []) if c],
            # 🟢 Indicador "Isabella digitando..." (TTL — frontend compara com now)
            "ai_typing_until": conv.get("ai_typing_until"),
            "ai_typing_agent": conv.get("ai_typing_agent"),
        }
        bucket = await _bucket_for_conversation(conv_view, cid)
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
async def get_conversation_messages(phone: str, limit: int = 500,
                                       user: dict = Depends(require_role("gestor"))):
    """Retorna as últimas N mensagens da conversa em ordem cronológica
    crescente (mais antigas primeiro → mais recentes embaixo).

    Bug fix iter75: antes usava `sort(+1).limit(N)` que pegava as N MAIS
    ANTIGAS e travava o chat na primeira página quando havia muitas
    mensagens. Agora pega as N MAIS RECENTES via `sort(-1).limit(N)` e
    inverte pro frontend exibir em ordem natural.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    capped = max(1, min(limit, 1000))
    docs = await db.aihub_wa_messages.find(
        {"company_id": cid, "phone": phone},
        {"_id": 0},
    ).sort("created_at", -1).limit(capped).to_list(capped)
    docs.reverse()
    return {"items": docs, "phone": phone, "count": len(docs)}


@router.delete("/conversations/{phone}")
async def reset_conversation(phone: str,
                                user: dict = Depends(require_role("gestor"))):
    """Reseta UMA conversa específica — apaga TODAS as mensagens (inbound +
    outbound + notas internas + coaching IA) e reseta o estado da conversa
    (assignee, badges). Útil pra testes da IA: começa do zero sem afetar
    outras conversas.

    Mantém: o registro do contato (db.wa_conversations) — mas zera last_msg,
    last_msg_at e unread_count. Mantém também os logs de auditoria (db.logs).
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID

    res_msgs = await db.aihub_wa_messages.delete_many(
        {"company_id": cid, "phone": phone}
    )
    res_coach = await db.coachings.delete_many(
        {"company_id": cid, "phone": phone}
    )
    res_eval = await db.ai_evaluations.delete_many(
        {"company_id": cid, "phone": phone}
    )

    # Reseta o estado da conversa — mantém o contato pra não perder o profile
    await db.wa_conversations.update_one(
        {"company_id": cid, "phone": phone},
        {"$set": {
            "last_msg": None,
            "last_msg_at": None,
            "last_msg_direction": None,
            "unread_count": 0,
            "assignee_user_id": None,
            "assignee_name": None,
            "assignee_role": "ai",
            "status": "open",
            "reset_at": now_iso(),
            "reset_by": user.get("email") or user.get("id"),
        }},
    )

    logger.info("[wa-baileys] conversation reset: phone=%s by=%s msgs=%d",
                phone, user.get("email"), res_msgs.deleted_count)
    return {
        "ok": True,
        "phone": phone,
        "messages_deleted": res_msgs.deleted_count,
        "coachings_deleted": res_coach.deleted_count,
        "evaluations_deleted": res_eval.deleted_count,
    }


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
            "assignee_assigned_at": now_iso(),
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
