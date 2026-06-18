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


NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "whatsapp",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["subscriber.created", "wa.message.persisted"],
    "company_id_required": True,
}

import asyncio
import base64
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, EMERGENT_LLM_KEY, now_iso, require_role, get_current_user
from database import db

logger = logging.getLogger("ponto.wa_baileys")
router = APIRouter(prefix="/api/whatsapp-baileys", tags=["whatsapp-baileys"])

# Helpers do sidecar Baileys (Node.js) — extraídos para services/wa/sidecar.py
# em iter106. Re-exportados aqui pra compatibilidade com imports externos
# (routes/disparo_boleto.py, routes/disparo_promo.py, routes/plans.py,
#  routes/mass_messaging.py, routes/whatsapp_twilio.py).
from services.wa.sidecar import (  # noqa: E402
    SIDECAR_BASE, SIDECAR_TOKEN, WA_INBOUND_TOKEN,
    _sidecar_headers, _sidecar_get, _sidecar_post, _sidecar_post_silent,
)
from services.wa.text_utils import _split_ai_reply  # noqa: E402

# Diretório onde áudios outbound enviados pela atendente são persistidos
# (servidos via /api/whatsapp-baileys/audio/{msg_id})
WA_AUDIO_DIR = Path(os.environ.get("WA_AUDIO_DIR", "/app/backend/uploads/wa_audio"))
WA_AUDIO_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers do sidecar e processamento de texto agora vivem em services/wa/
# Re-exports estão no topo do arquivo pra manter backward compat.
# ---------------------------------------------------------------------------


async def _deliver_boleto_with_pdf(cid: str, phone: str,
                                      subscriber_id: Optional[str],
                                      boleto_full: Dict[str, Any]) -> None:
    """Envia o texto resumido + 1 PDF anexo por fatura aberta.

    Se é apenas pedido de CPF (`is_request=True`) ou se não há faturas,
    envia só o texto.
    """
    text = boleto_full.get("text") or ""
    invoices = boleto_full.get("invoices") or []
    subscriber = boleto_full.get("subscriber") or {}
    is_request = bool(boleto_full.get("is_request"))

    # Sempre envia o texto primeiro
    sent_text = await _sidecar_post_silent("/send", {"phone": phone, "text": text})
    await db.aihub_wa_messages.insert_one({
        "company_id": cid, "phone": phone, "jid": f"{phone}@s.whatsapp.net",
        "direction": "outbound", "text": text,
        "subscriber_id": subscriber_id,
        "auto_reply": True, "agent": "boleto_flow",
        "delivery_status": "sent" if sent_text.get("ok") else "failed_send",
        "external_id": (sent_text or {}).get("message_id"),
        "created_at": now_iso(),
    })
    try:
        from services.event_bus import emit_event
        await emit_event(
            "wa.message.persisted",
            company_id=cid,
            source="whatsapp_baileys",
            payload={},
        )
    except Exception:
        pass

    if is_request or not invoices:
        return

    # Envia 1 PDF por fatura (limite de 3 pra não floodar)
    from services.boleto_pdf import build_boleto_pdf, _resolve_logo
    import base64
    cust_name = subscriber.get("name") or subscriber.get("customer_name")
    logo_bytes = await _resolve_logo(cid)
    for inv in invoices[:3]:
        try:
            pdf_bytes = build_boleto_pdf(
                inv, customer_name=cust_name, logo_bytes=logo_bytes,
            )
            b64 = base64.b64encode(pdf_bytes).decode("ascii")
            due = inv.get("due_date") or "fatura"
            due_short = str(due)[:10]
            fname = f"Boleto Ligo Fibra {due_short}.pdf"
            sent_doc = await _sidecar_post_silent("/send-document", {
                "phone": phone,
                "document_b64": b64,
                "filename": fname,
                "mimetype": "application/pdf",
            })
            await db.aihub_wa_messages.insert_one({
                "company_id": cid, "phone": phone,
                "jid": f"{phone}@s.whatsapp.net",
                "direction": "outbound",
                "text": f"📎 {fname}",
                "subscriber_id": subscriber_id,
                "auto_reply": True, "agent": "boleto_flow",
                "metadata": {"type": "document", "filename": fname,
                              "size_bytes": len(pdf_bytes)},
                "delivery_status": "sent" if sent_doc.get("ok") else "failed_send",
                "delivery_error": (sent_doc or {}).get("error"),
                "external_id": (sent_doc or {}).get("message_id"),
                "created_at": now_iso(),
            })
            try:
                from services.event_bus import emit_event
                await emit_event(
                    "wa.message.persisted",
                    company_id=company_id,
                    source="whatsapp_baileys",
                    payload={},
                )
            except Exception:
                pass
            if not sent_doc.get("ok"):
                logger.warning("[wa-baileys] boleto pdf falhou: %s",
                               sent_doc.get("error"))
        except Exception as e:
            logger.warning("[wa-baileys] gerar/enviar PDF do boleto falhou: %s", e)


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
        async with httpx.AsyncClient(headers=_sidecar_headers(), timeout=15) as cli:
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


@router.post("/reload")
async def reload_sidecar(user: dict = Depends(require_role("gestor"))):
    """Força o sidecar a reiniciar o socket Baileys SEM perder a sessão.

    Útil quando o socket trava: `state=connected` mas para de receber/enviar
    mensagens. NÃO requer novo QR Code.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    try:
        async with httpx.AsyncClient(headers=_sidecar_headers(),
                                         timeout=10.0) as cli:
            r = await cli.post(f"{SIDECAR_BASE}/reload", json={})
            out = r.json() if r.status_code == 200 else {"raw": r.text}
        await db.wa_system_events.insert_one({
            "company_id": cid,
            "type": "reload_manual",
            "triggered_by": user.get("email"),
            "result": out,
            "created_at": now_iso(),
        })
        return {"ok": True, "sidecar_response": out}
    except Exception as e:
        logger.exception("[wa-baileys] reload failed")
        raise HTTPException(500, f"Falha ao reload: {e}")


class SendIn(BaseModel):
    phone: str = Field(..., min_length=8, max_length=25)
    text: str = Field(..., min_length=1, max_length=4096)
    polished_by_ai: bool = Field(default=False)


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
        # P0.4 A1 — Roteado via gateway (HOMOLOG + Kill Switch + Audit)
        from services.wa.sidecar import _sidecar_post_silent
        out = await _sidecar_post_silent("/send-audio", {
            "phone": payload.phone,
            "audio_b64": payload.audio_b64,
            "mimetype": payload.mimetype,
            "company_id": cid,
        }) or {}
        if out.get("blocked_by_gateway"):
            send_error = "blocked by gateway (HOMOLOG/KillSwitch/Whitelist)"
        elif out.get("ok"):
            send_ok = True
        else:
            send_error = out.get("error") or out.get("status") or "send failed"
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
    try:
        from services.event_bus import emit_event
        await emit_event(
            "wa.message.persisted",
            company_id=cid,
            source="whatsapp_baileys",
            payload={},
        )
    except Exception:
        pass
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



WA_MEDIA_ROOT = Path("/app/storage/wa_media")

MIME_BY_EXT = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp",
    "mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm",
    "3gp": "video/3gpp",
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "txt": "text/plain", "csv": "text/csv",
}


@router.get("/media/{kind}/{filename}")
async def get_inbound_media(kind: str, filename: str,
                              authorization: Optional[str] = Header(default=None),
                              t: Optional[str] = None):
    """Serve arquivos de mídia inbound (imagem, vídeo, documento, sticker)."""
    if kind not in ("image", "video", "document", "sticker"):
        raise HTTPException(404, "Tipo inválido")
    # Mesmo schema de auth do endpoint /audio
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

    safe_name = filename.replace("..", "").replace("/", "")
    path = WA_MEDIA_ROOT / kind / safe_name
    if not path.exists():
        raise HTTPException(404, "Arquivo não encontrado")
    ext = path.suffix.lstrip(".").lower()
    mime = MIME_BY_EXT.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=mime, filename=safe_name)



@router.post("/send")
async def send_message(payload: SendIn,
                        user: dict = Depends(require_role("gestor"))):
    """Envio manual de mensagem. Persistimos no histórico SEMPRE, mas o
    `delivery_status` reflete o que o sidecar Baileys realmente confirmou.

    iter183 — Toda msg enviada pelo painel manual (atendente humano) é
    prefixada com "Atendente Ligo {primeiro_nome}: " para identificar quem
    está falando. Aparece no WhatsApp do cliente E no histórico do gestor.

    Se o sidecar falhar (socket zumbi, timeout, desconectado), retornamos
    HTTP 502 com `delivery_status=failed` no doc — para o frontend mostrar
    erro pro usuário em vez de assumir entrega.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    first_name = ((user.get("name") or "").strip().split() or [""])[0]
    if first_name:
        text_to_send = f"Atendente Ligo {first_name}: {payload.text}"
    else:
        text_to_send = payload.text
    send_ok = False
    send_error: Optional[str] = None
    out: Dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(headers=_sidecar_headers(), timeout=20.0) as cli:
            r = await cli.post(f"{SIDECAR_BASE}/send",
                                json={"phone": payload.phone, "text": text_to_send})
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
        "text": text_to_send,
        "channel": "baileys",
        "message_id": out.get("message_id"),
        "created_at": now_iso(),
        "actor_user": user.get("email") or user.get("id"),
        "sent_by_user_id": user.get("id"),
        "sent_by_user_name": user.get("name"),
        "agent_tag": "atendente_ligo",
        "auto_reply": False,
        "polished_by_ai": bool(payload.polished_by_ai),
        "delivery_status": "sent" if send_ok else "failed",
        "delivery_error": send_error,
    })
    try:
        from services.event_bus import emit_event
        await emit_event(
            "wa.message.persisted",
            company_id=cid,
            source="whatsapp_baileys",
            payload={},
        )
    except Exception:
        pass
    try:
        from services.event_bus import emit_event
        await emit_event(
            "wa.message.persisted",
            company_id=cid,
            source="whatsapp_baileys",
            payload={},
        )
    except Exception:
        pass
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


class PolishTextIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@router.post("/polish-text")
async def polish_text(payload: PolishTextIn,
                        _user: dict = Depends(require_role("gestor"))):
    """Recebe um rascunho do atendente e devolve uma versão polida em
    português (gramática, pontuação, fluência). Mantém o sentido original e
    o tom; NÃO inventa fatos nem muda intenção. Usado pelo botão azul
    "Enviar com IA" no composer do WhatsApp.
    """
    raw = (payload.text or "").strip()
    if not raw:
        raise HTTPException(400, "Texto vazio.")
    if not EMERGENT_LLM_KEY:
        raise HTTPException(503, "Motor IA indisponível (chave ausente).")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"polish-{uuid.uuid4().hex[:8]}",
            system_message=(
                "Você é um revisor de português brasileiro para mensagens "
                "de WhatsApp de atendimento ao cliente. Receba um rascunho "
                "do atendente e devolva APENAS o texto reescrito em "
                "português correto, claro, cordial e direto. Regras:\n"
                "1) NÃO mude o sentido nem a intenção da mensagem.\n"
                "2) NÃO invente informações, datas, valores, nomes ou "
                "fatos que não estejam no rascunho.\n"
                "3) Corrija ortografia, pontuação, acentuação e concordância.\n"
                "4) Mantenha o tom (formal/informal) o mais próximo do original.\n"
                "5) Pode usar 1-2 emojis sutis se ajudar a deixar acolhedor, "
                "mas só se o original já for casual.\n"
                "6) NÃO acrescente saudações ou despedidas que não estejam "
                "no rascunho.\n"
                "7) Devolva APENAS a mensagem final, sem prefixos como "
                "'Versão polida:' nem aspas em volta."
            ),
        ).with_model("openai", "gpt-5-mini")
        out = await chat.send_message(UserMessage(text=raw))
        polished = str(out).strip().strip('"').strip("'")
        # Salva-guarda: se a IA devolver vazio ou muito longo, devolve original
        if not polished or len(polished) > 4000:
            polished = raw
    except Exception as e:
        logger.warning("[wa-baileys] polish-text falhou: %s", e)
        raise HTTPException(502, f"Falha ao polir texto: {e}")
    return {"original": raw, "polished": polished}


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
        # P0.4 A2 — Roteado via gateway (HOMOLOG + Kill Switch + Audit)
        from services.wa.sidecar import _sidecar_post_silent
        out = await _sidecar_post_silent("/send-image", {
            "phone": payload.phone,
            "image_data_url": payload.image_data_url,
            "caption": payload.caption,
            "company_id": cid,
        }) or {}
        if out.get("blocked_by_gateway"):
            send_error = "blocked by gateway (HOMOLOG/KillSwitch/Whitelist)"
        elif out.get("ok"):
            send_ok = True
        else:
            send_error = (out.get("error") or out.get("status")
                          or "sidecar não suporta /send-image (atualize o serviço Baileys)")
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
    try:
        from services.event_bus import emit_event
        await emit_event(
            "wa.message.persisted",
            company_id=cid,
            source="whatsapp_baileys",
            payload={},
        )
    except Exception:
        pass
    try:
        from services.event_bus import emit_event
        await emit_event(
            "wa.message.persisted",
            company_id=cid,
            source="whatsapp_baileys",
            payload={},
        )
    except Exception:
        pass
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
    # Mídia geral inbound (imagem/vídeo/documento/sticker)
    media_b64: Optional[str] = None
    media_mimetype: Optional[str] = None
    media_filename: Optional[str] = None
    media_kind: Optional[str] = None       # "image" | "video" | "document" | "sticker"
    media_size_bytes: Optional[int] = None
    # Multi-canal: identifica qual sidecar/número recebeu a mensagem.
    # Fallback "channel-1" mantém compatibilidade com sidecars antigos.
    channel_id: Optional[str] = None


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

    Detecção de DUPLICATE SESSION: quando vemos 3+ logged_out (code 401) em
    janela de 10min, marcamos a empresa como `wa_duplicate_session_suspect`
    e emitimos um evento `duplicate_session_suspected` (consumido pela UI).
    Esse padrão é o sintoma típico de 2 sidecars usando a mesma credencial.
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

    # --- Notifica admins se o evento for crítico ---
    CRITICAL_EVENTS = {"logged_out", "connection_replaced", "banned",
                       "qr_required", "auth_failure"}
    if payload.event in CRITICAL_EVENTS:
        try:
            reason_msg = {
                "logged_out": "WhatsApp deslogou (sessão expirou ou outro dispositivo conectou). Re-pareie o QR Code.",
                "connection_replaced": "Outro dispositivo assumiu a sessão. Verifique se há outra instância rodando.",
                "banned": "🚫 Conta bloqueada pelo WhatsApp. Use outro número.",
                "qr_required": "QR Code necessário — vá em Atendimento IA → Configuração para escanear.",
                "auth_failure": "Falha de autenticação. Re-pareie o QR Code.",
            }.get(payload.event, payload.reason or payload.event)
            await _notify_admins_baileys_down(DEMO_COMPANY_ID, reason_msg)
        except Exception as e:
            logger.info("[wa-baileys] notify admins skip: %s", e)

    # --- Detecção de sessão duplicada ---
    # Pattern: 3+ logged_out (ou connection_replaced) em janela curta = outra
    # instância está fighting pelo mesmo número. Avisa a UI/admin.
    if payload.event in {"logged_out", "connection_replaced"}:
        try:
            from datetime import datetime, timedelta, timezone
            window_start = (
                datetime.now(timezone.utc) - timedelta(minutes=10)
            ).isoformat()
            recent = await db.whatsapp_system_events.count_documents({
                "company_id": DEMO_COMPANY_ID,
                "event": {"$in": ["logged_out", "connection_replaced"]},
                "created_at": {"$gte": window_start},
            })
            if recent >= 3:
                # Verifica se já emitimos esse alerta na janela atual
                already = await db.whatsapp_system_events.find_one({
                    "company_id": DEMO_COMPANY_ID,
                    "event": "duplicate_session_suspected",
                    "created_at": {"$gte": window_start},
                }, {"_id": 0, "id": 1})
                if not already:
                    await db.whatsapp_system_events.insert_one({
                        "id": f"wae-{uuid.uuid4().hex[:10]}",
                        "company_id": DEMO_COMPANY_ID,
                        "event": "duplicate_session_suspected",
                        "code": None,
                        "name": "duplicate_session_suspected",
                        "retry_count": None,
                        "reason": (
                            f"{recent} eventos de logged_out/connection_replaced "
                            "em janela de 10min — provável conflito de sessão "
                            "(2+ sidecars usando o mesmo número)."
                        ),
                        "created_at": now_iso(),
                        "acknowledged": False,
                    })
                    logger.error(
                        "[wa-baileys][ALERTA] Sessão WhatsApp duplicada suspeita: "
                        "%s eventos em 10min — verificar se há mais de um sidecar "
                        "rodando com a mesma credencial.", recent
                    )
        except Exception as e:
            logger.warning("[wa-baileys] dup-session detect skip: %s", e)

    return {"ok": True, "id": doc["id"]}


@router.get("/system-events")
async def list_system_events(user: dict = Depends(require_role("gestor"))):
    """Lista os últimos 50 eventos de sistema do WhatsApp."""
    docs = await db.whatsapp_system_events.find(
        {"company_id": DEMO_COMPANY_ID},
        {"_id": 0},
    ).sort("created_at", -1).limit(50).to_list(50)
    return {"events": docs}


class InboundCallIn(BaseModel):
    phone: str
    jid: Optional[str] = None
    call_id: Optional[str] = None
    is_video: bool = False
    is_group: bool = False
    timestamp: Optional[str] = None


@router.post("/inbound-call")
async def inbound_call(payload: InboundCallIn,
                        x_wa_token: Optional[str] = Header(default=None)):
    """📞 Webhook do sidecar quando alguém LIGA pra Isabella (voz/vídeo).

    Sidecar já rejeitou a chamada. Aqui:
      1. Registramos em wa_messages (aparece como "📞 Tentativa de chamada")
      2. Disparamos resposta amigável pro cliente mandar áudio/texto
    """
    if WA_INBOUND_TOKEN and x_wa_token != WA_INBOUND_TOKEN:
        raise HTTPException(401, "X-WA-Token inválido")

    cid = DEMO_COMPANY_ID
    phone = (payload.phone or "").replace("+", "").replace(" ", "")
    call_type = "vídeo" if payload.is_video else "voz"

    msg_id = f"call-{uuid.uuid4().hex[:10]}"
    await db.aihub_wa_messages.insert_one({
        "id": msg_id,
        "company_id": cid,
        "direction": "inbound",
        "phone": phone,
        "jid": payload.jid,
        "text": f"📞 Tentativa de chamada de {call_type} (rejeitada)",
        "channel": "baileys",
        "media_type": "call",
        "call_meta": {
            "is_video": payload.is_video,
            "is_group": payload.is_group,
            "call_id": payload.call_id,
        },
        "wa_timestamp": payload.timestamp,
        "created_at": now_iso(),
    })
    try:
        from services.event_bus import emit_event
        await emit_event(
            "wa.message.persisted",
            company_id=cid,
            source="whatsapp_baileys",
            payload={},
        )
    except Exception:
        pass

    response_text = (
        "Oi! 😊 Aqui eu não consigo atender chamada, mas se você me "
        "mandar um *áudio* 🎤 ou *texto*, eu respondo na hora!\n\n"
        "Pode me contar o que está precisando? 💙"
    )
    try:
        await _sidecar_post("/send", {"phone": phone, "text": response_text})
        await db.aihub_wa_messages.insert_one({
            "id": f"auto-call-reply-{uuid.uuid4().hex[:8]}",
            "company_id": cid,
            "direction": "outbound",
            "phone": phone,
            "text": response_text,
            "channel": "baileys",
            "auto_generated": True,
            "auto_reason": "call_rejected_auto_response",
            "created_at": now_iso(),
        })
        try:
            from services.event_bus import emit_event
            await emit_event(
                "wa.message.persisted",
                company_id=company_id,
                source="whatsapp_baileys",
                payload={},
            )
        except Exception:
            pass
    except Exception as e:
        logger.warning("[inbound-call] envio de resposta falhou: %s", e)

    logger.info("[inbound-call] %s ligação de %s rejeitada · resposta enviada",
                phone, call_type)
    return {"ok": True, "id": msg_id}




@router.post("/conversation/{phone}/reset-context")
async def reset_conversation_context(
    phone: str,
    user: dict = Depends(require_role("gestor")),
):
    """Zera o contexto da Isabella IA para esta conversa.

    Não apaga mensagens do banco (preserva auditoria). Apenas marca
    `context_reset_at = now` em `wa_conversations` — o `fetch_history_turns`
    passa a filtrar `created_at > context_reset_at`, fazendo a IA enxergar
    a conversa como se fosse o início.

    Também limpa flags de estado: `assignee_role`, `sales_completed_at`,
    `handoff_at` — pra que o roteamento volte ao default (Isabella IA).

    Uso: testar saudação personalizada V6.51, kill-switch, fluxos V6.70
    sem precisar criar phones de teste novos.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    now = now_iso()
    res = await db.wa_conversations.update_one(
        {"company_id": cid, "phone": phone},
        {"$set": {
            "context_reset_at": now,
            "context_reset_by": user.get("email") or user.get("id"),
            "assignee_role": None,
            "assignee_user_id": None,
            "sales_completed_at": None,
            "sales_completion_reason": None,
            "handoff_at": None,
            "handoff_reason": None,
            "updated_at": now,
        }},
        upsert=True,
    )
    logger.info(
        "[wa-baileys] context reset: company=%s phone=%s by=%s",
        cid, phone, user.get("email"),
    )
    return {
        "ok": True,
        "phone": phone,
        "context_reset_at": now,
        "matched": int(res.matched_count),
        "modified": int(res.modified_count),
    }


@router.get("/health-overview")
async def health_overview(
    days: int = 7, user: dict = Depends(require_role("gestor")),
):
    """Painel "Saúde do WhatsApp" — agrega sidecar + delivery + latência IA + alertas.

    Retorna:
      - sidecar: { ok, state, uptime_s, retry_count, queue_size, last_send_at }
      - delivery: { outbound_total, delivered, failed, pending, delivery_pct }
      - isabella_latency: { samples, p50_s, p95_s, p99_s, avg_s }
      - alerts: { duplicate_session, los_cluster, logged_out, connection_replaced }
        + lista dos 20 eventos relevantes recentes
    """
    from datetime import datetime, timedelta, timezone
    cid = user.get("company_id") or DEMO_COMPANY_ID
    days = max(1, min(int(days or 7), 90))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # 1. Sidecar /health (real-time)
    sidecar_info: Dict[str, Any] = {"ok": False, "error": None}
    try:
        sidecar_info = await _sidecar_get("/health")
        sidecar_info["ok"] = bool(sidecar_info.get("ok", True))
    except Exception as e:
        sidecar_info = {"ok": False, "error": str(e)[:200]}

    # 2. Delivery — outbound stats da janela
    base = {"company_id": cid, "direction": "outbound",
            "created_at": {"$gte": since}}
    out_total = await db.aihub_wa_messages.count_documents(base)
    # delivered: sent_ok != False (default True quando salvo)
    delivered = await db.aihub_wa_messages.count_documents({
        **base,
        "$or": [{"sent_ok": True}, {"sent_ok": {"$exists": False}}],
    })
    failed = await db.aihub_wa_messages.count_documents({
        **base, "sent_ok": False,
    })
    pending = max(0, out_total - delivered - failed)
    delivery_pct = round(100.0 * delivered / out_total, 1) if out_total else 0.0

    # 3. Latência da Isabella — diff entre inbound mais recente e a resposta
    # auto_reply correspondente para o mesmo phone (janela 5min).
    # Single pass: coleta (timestamp_out, diff_s) e calcula percentis +
    # bucketiza por hora UTC pra série temporal.
    samples_raw: list = []  # lista de (out_dt, diff_s)
    try:
        ai_outs = db.aihub_wa_messages.find(
            {**base, "auto_reply": True},
            {"_id": 0, "phone": 1, "created_at": 1},
        ).sort([("created_at", -1)]).limit(2000)
        async for o in ai_outs:
            phone = o.get("phone")
            out_ts = o.get("created_at")
            if not phone or not out_ts:
                continue
            try:
                out_dt = datetime.fromisoformat(out_ts.replace("Z", "+00:00"))
            except Exception:
                continue
            five_min_before = (out_dt - timedelta(minutes=5)).isoformat()
            inb = await db.aihub_wa_messages.find_one({
                "company_id": cid, "phone": phone, "direction": "inbound",
                "created_at": {"$lt": out_ts, "$gte": five_min_before},
            }, {"_id": 0, "created_at": 1}, sort=[("created_at", -1)])
            if not inb:
                continue
            try:
                in_dt = datetime.fromisoformat(
                    inb["created_at"].replace("Z", "+00:00"))
                diff = (out_dt - in_dt).total_seconds()
                if 0 < diff <= 300:
                    samples_raw.append((out_dt, diff))
            except Exception:
                continue
    except Exception as e:
        logger.info("[wa-baileys] latency calc skip: %s", e)

    latencies_s = [d for (_, d) in samples_raw]

    def _pct(arr: list, p: float) -> float:
        if not arr:
            return 0.0
        s = sorted(arr)
        idx = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
        return round(s[idx], 2)

    samples = len(latencies_s)
    latency = {
        "samples": samples,
        "avg_s": round(sum(latencies_s) / samples, 2) if samples else 0.0,
        "p50_s": _pct(latencies_s, 50),
        "p95_s": _pct(latencies_s, 95),
        "p99_s": _pct(latencies_s, 99),
    }

    # 3b. Série temporal de latência — bucketiza por hora UTC (single-pass)
    bucket: Dict[str, list] = {}
    for out_dt, diff in samples_raw:
        hour_key = out_dt.strftime("%Y-%m-%dT%H:00")
        bucket.setdefault(hour_key, []).append(diff)

    latency_series = []
    for hour in sorted(bucket.keys()):
        arr = bucket[hour]
        latency_series.append({
            "hour": hour,
            "count": len(arr),
            "p50_s": _pct(arr, 50),
            "p95_s": _pct(arr, 95),
            "p99_s": _pct(arr, 99),
        })
    latency["series"] = latency_series

    # 4. Alertas — counts de eventos críticos + lista
    alert_events = {"duplicate_session_suspected", "los_cluster_alert",
                    "logged_out", "connection_replaced",
                    "possibly_banned", "max_retries_exceeded",
                    "circuit_breaker_open"}
    pipeline = [
        {"$match": {"company_id": cid, "created_at": {"$gte": since},
                    "event": {"$in": list(alert_events)}}},
        {"$group": {"_id": "$event", "count": {"$sum": 1}}},
    ]
    grouped = await db.whatsapp_system_events.aggregate(pipeline).to_list(20)
    alerts_count = {a: 0 for a in alert_events}
    for g in grouped:
        alerts_count[g["_id"]] = int(g.get("count", 0))

    recent_events = await db.whatsapp_system_events.find(
        {"company_id": cid, "created_at": {"$gte": since},
         "event": {"$in": list(alert_events)}},
        {"_id": 0},
    ).sort([("created_at", -1)]).limit(20).to_list(20)

    return {
        "days": days,
        "since": since,
        "sidecar": sidecar_info,
        "delivery": {
            "outbound_total": out_total,
            "delivered": delivered,
            "failed": failed,
            "pending": pending,
            "delivery_pct": delivery_pct,
        },
        "isabella_latency": latency,
        "alerts": {
            "counts": alerts_count,
            "recent": recent_events,
        },
    }


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
                           background_tasks: BackgroundTasks,
                           x_wa_token: Optional[str] = Header(default=None)):
    """Processa mensagem recebida do WhatsApp.

    Segurança: validamos o header `X-WA-Token` contra `WA_INBOUND_TOKEN`
    do .env. O sidecar Node passa esse token. Se a env não estiver setada
    (dev), aceita sem validar (compat — log warning).
    """
    if WA_INBOUND_TOKEN:
        if not x_wa_token or x_wa_token != WA_INBOUND_TOKEN:
            recv = (x_wa_token or "")
            recv_prefix = recv[:12] + "…" + recv[-4:] if len(recv) > 16 else recv
            expected_prefix = (
                WA_INBOUND_TOKEN[:12] + "…" + WA_INBOUND_TOKEN[-4:]
                if len(WA_INBOUND_TOKEN) > 16 else WA_INBOUND_TOKEN
            )
            logger.warning(
                "[wa-baileys] inbound rejeitado — recebido='%s' esperado='%s'",
                recv_prefix, expected_prefix,
            )
            raise HTTPException(401, "X-WA-Token inválido")
    else:
        logger.warning(
            "[wa-baileys] WA_INBOUND_TOKEN não configurado — endpoint aberto!"
        )
    if payload.from_me:
        return {"ok": True, "ignored": "from_me"}
    # Sprint 19 — emit wa.inbound (best-effort)
    # Multi-tenant guard: NUNCA emite sem company_id resolvido.
    _cid_for_event = (getattr(payload, "company_id", None)
                        or getattr(payload, "cid", None))
    if not _cid_for_event:
        # tenta resolver via canal/jid
        try:
            ch = await db.aihub_channels.find_one(
                {"id": getattr(payload, "channel_id", None)},
                {"_id": 0, "company_id": 1})
            if ch:
                _cid_for_event = ch.get("company_id")
        except Exception:
            pass
    if _cid_for_event:
        try:
            from services.event_emitters import emit_business
            await emit_business(
                kind="wa.inbound", company_id=_cid_for_event,
                payload={"jid": payload.jid,
                          "from_phone": getattr(payload, "from_phone", None),
                          "text_preview": (
                                getattr(payload, "text", "") or "")[:80]},
                severity="baixa", source="whatsapp_baileys.inbound")
        except Exception:
            pass
    # Ignora Status/Broadcast/Newsletters do WhatsApp — não são conversas reais
    # e o WhatsApp bloqueia respostas para esses JIDs (causa "FALHOU" na UI).
    jid_norm = (payload.jid or "").lower()
    if (
        jid_norm == "status@broadcast"
        or jid_norm.endswith("@broadcast")
        or jid_norm.endswith("@newsletter")
        or (payload.phone or "").lower() == "status"
    ):
        return {"ok": True, "ignored": "broadcast_or_status"}
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

    # iter216b — WiFi Hotspot anti-bloqueio: se a msg contém código de
    # liberação WIFI-XXXXXX, libera a sessão pendente desse phone.
    try:
        from routes.wifi_hotspot import try_unlock_session_from_whatsapp
        await try_unlock_session_from_whatsapp(
            effective_phone, payload.text or "")
    except Exception as e:
        logger.warning("[wa-baileys] wifi unlock check falhou: %s", e)

    subscriber_id = None
    subscriber_ctx = None
    # Quando o phone está vinculado a 2+ subscribers, a IA NÃO pode chamar
    # ninguém pelo nome (risco de vazar dados de outro cliente). Marca pra
    # injetar diretiva específica no prompt mais abaixo.
    subscriber_conflict_count = 0
    try:
        from phone_normalizer import link_phone_to_subscriber
        link = await link_phone_to_subscriber(effective_phone, cid)
        if link and link.get("conflict"):
            subscriber_conflict_count = link.get("conflict_count") or 0
            logger.warning(
                "[wa-baileys] phone=%s tem %d cadastros — IA não vai usar "
                "nome próprio até cliente confirmar CPF.",
                effective_phone, subscriber_conflict_count,
            )
        elif link and link.get("subscriber_id"):
            subscriber_id = link["subscriber_id"]

        # 🆕 Phone DESCONHECIDO — tag + tenta auto-link via CPF/CNPJ no texto
        if not subscriber_id:
            try:
                from services.subscriber_phone_linker import (
                    tag_unknown_phone, try_auto_link_phone,
                )
                # 1. Marca como "Identificação pendente" pra UI exibir badge
                await tag_unknown_phone(cid, effective_phone)
                # 2. Tenta auto-link se cliente mandou CPF/CNPJ/nome agora
                linked = await try_auto_link_phone(cid, effective_phone, payload.text)
                if linked:
                    subscriber_id = linked["subscriber_id"]
                    logger.info(
                        "[wa-baileys] auto-linked phone=%s → subscriber=%s via %s",
                        effective_phone, subscriber_id,
                        linked.get("matched_by"),
                    )
            except Exception as e:
                logger.warning("[wa-baileys] auto-link skip: %s", e)

        if subscriber_id:
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

    # === Mídia inbound: imagem / vídeo / documento / sticker ===
    has_media_file = bool(payload.media_b64 and payload.media_kind)
    if has_media_file and not media_type:
        try:
            from pathlib import Path as _Path
            kind = payload.media_kind
            # Diretórios separados por tipo
            base_dir = _Path("/app/storage/wa_media") / kind
            base_dir.mkdir(parents=True, exist_ok=True)
            # Extensão: usa filename do sidecar (preserva ".pdf", ".docx" etc.)
            orig = payload.media_filename or f"{kind}-{msg_id}"
            ext = orig.rsplit(".", 1)[-1].lower() if "." in orig else ""
            # Sanitização leve
            safe_name = f"{msg_id}.{ext}" if ext else msg_id
            out_path = base_dir / safe_name
            out_path.write_bytes(base64.b64decode(payload.media_b64))
            media_type = kind
            media_url = f"/api/whatsapp-baileys/media/{kind}/{safe_name}"
            logger.info("[wa-baileys] 📎 %s recebido: %s (%s bytes)",
                        kind, orig, payload.media_size_bytes)
        except Exception as e:
            logger.warning("[wa-baileys] save inbound media failed: %s", e)

    # 👁️ ANÁLISE VISUAL AUTOMÁTICA (Gemini Vision) — se for imagem/PDF
    # e não tiver texto/caption do cliente, Isabella "vê" o conteúdo.
    vision_summary = None
    if (has_media_file and not (payload.text or "").strip()
            and payload.media_kind in ("image", "document", "sticker")):
        try:
            from services.media_analysis import analyze_media
            vision_summary = await analyze_media(
                payload.media_b64,
                payload.media_mimetype or "image/jpeg",
                payload.media_kind,
                company_id=cid,
                agent="isabella_vision",
            )
            if vision_summary:
                logger.info("[wa-baileys] 👁️ visão: %s",
                            vision_summary[:150])
        except Exception as e:
            logger.warning("[wa-baileys] vision falhou: %s", e)

    # 🎤 TRANSCRIÇÃO AUTOMÁTICA: se inbound for áudio sem texto, transcreve
    # via Whisper antes do LLM ver a mensagem. Isabella passa a "entender"
    # voice notes em vez de ver só "🎤 Áudio (5s)".
    transcript = None
    if has_audio and not (payload.text or "").strip() and payload.audio_b64:
        try:
            from services.motor_ia import transcribe_audio
            audio_bytes = base64.b64decode(payload.audio_b64)
            transcript = await transcribe_audio(cid, audio_bytes,
                                                  filename=f"audio.{ext}")
            transcript = (transcript or "").strip()
            if transcript:
                logger.info("[wa-baileys] 🎤 transcrito (%ss): %s",
                            media_duration_sec, transcript[:120])
        except Exception as e:
            logger.warning("[wa-baileys] transcribe falhou: %s", e)
            transcript = None

    # Resolve channel_id (multi-número) — fallback channel-1 pra compat
    channel_id = payload.channel_id or "channel-1"
    channel_name = None
    try:
        from services.whatsapp_channels import get_channel as _get_ch
        ch_doc = await _get_ch(db, cid, channel_id)
        if ch_doc:
            channel_name = ch_doc.get("channel_name")
    except Exception:
        pass

    inbound_doc = {
        "id": msg_id,
        "company_id": cid,
        "direction": "inbound",
        "phone": effective_phone,
        "jid": payload.jid,
        "text": payload.text or transcript or vision_summary or (
            f"🎤 Áudio ({media_duration_sec}s)" if has_audio and media_duration_sec
            else "🎤 Áudio" if has_audio
            else f"📎 {payload.media_kind.title()}: {payload.media_filename}"
                 if has_media_file and payload.media_kind
            else ""
        ),
        "channel": "baileys",
        "channel_id": channel_id,
        "channel_name": channel_name,
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
        inbound_doc["media_mimetype"] = payload.audio_mimetype or payload.media_mimetype
        inbound_doc["media_is_ptt"] = payload.audio_is_ptt
        if transcript:
            inbound_doc["transcript"] = transcript
            inbound_doc["transcript_engine"] = "whisper-1"
        if has_media_file:
            inbound_doc["media_filename"] = payload.media_filename
            inbound_doc["media_size_bytes"] = payload.media_size_bytes
        if vision_summary:
            inbound_doc["vision_summary"] = vision_summary
            inbound_doc["vision_engine"] = "gemini-2.5-flash"
    await db.aihub_wa_messages.insert_one(inbound_doc)
    # Isabella V14 — Oráculo de Memória Relacional: captura acontecimentos
    # relevantes do user_text (regex L1 + Claude L2 quando ambíguo).
    try:
        if not is_group and (payload.text or transcript):
            from services.customer_memory import capture_from_inbound
            asyncio.create_task(capture_from_inbound(
                company_id=cid, phone=effective_phone,
                subscriber_id=subscriber_id,
                user_text=(payload.text or transcript or ""),
                source_msg_id=payload.message_id,
            ))
    except Exception as _e:
        logger.debug("[wa-baileys] customer_memory capture skip: %s", _e)
    # Marca o último canal por onde o cliente falou (UI mostra badge)
    try:
        await db.wa_conversations.update_one(
            {"company_id": cid, "phone": effective_phone},
            {"$set": {
                "last_channel_id": channel_id,
                "last_channel_name": channel_name,
            }},
            upsert=True,
        )
    except Exception:
        pass
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

    # === FAST RETURN: a partir daqui, IA roda em background ===
    # O sidecar Baileys tem timeout de 15s. Auto-reply LLM pode demorar
    # mais que isso, causando timeout + retries no sidecar. Solução:
    # despachar processamento pesado para BackgroundTasks e retornar 200
    # imediatamente — o sidecar não fica esperando, msgs não se perdem.
    if not is_group:
        # Determinar o texto que a Isabella vai "ler":
        # 1. Texto do cliente (caption ou mensagem direta)
        # 2. OU transcrição de voice note
        # 3. OU análise visual com prefixo [VISÃO_AUTO: ...]
        # 4. Fallback: se cliente mandou mídia sem caption/voz E o Vision
        #    falhou (budget, timeout etc), enviamos uma "pista" pra Isabella
        #    pedir descrição em vez de ficar muda.
        ai_input = (payload.text or "").strip()
        if not ai_input and transcript:
            ai_input = transcript
        if not ai_input and vision_summary:
            ai_input = f"[VISÃO_AUTO: {vision_summary}]"
        if not ai_input and has_media_file and payload.media_kind in (
            "image", "document",
        ):
            ai_input = (
                f"[CLIENTE_ENVIOU_{payload.media_kind.upper()}_SEM_DESCRICAO: "
                "não consegui analisar o conteúdo automaticamente — peça "
                "gentilmente ao cliente que descreva o que é a foto/arquivo "
                "ou diga o problema em texto. Não invente o conteúdo da imagem.]"
            )
        background_tasks.add_task(
            _process_inbound_ai_pipeline,
            cid=cid,
            effective_phone=effective_phone,
            payload_jid=payload.jid,
            payload_text=ai_input,
            payload_message_id=payload.message_id,
            subscriber_id=subscriber_id,
            subscriber_ctx=subscriber_ctx,
            inbound_was_voice=bool(transcript),
        )

    # iter217a — Propaganda Pré-Atendimento: dispara ANTES do agente
    # se for cliente cadastrado, 1ª msg em 24h, e houver promo ativa.
    # Roda em background — não bloqueia o sidecar.
    if subscriber_id and not is_group:
        try:
            from services.pre_attendance_promo import (
                try_dispatch_pre_attendance_promo, mark_reply,
            )
            # Marca resposta a um disparo anterior (se houver)
            background_tasks.add_task(mark_reply, cid, effective_phone)
            # Tenta novo disparo (cooldown 24h aplica)
            background_tasks.add_task(
                try_dispatch_pre_attendance_promo,
                cid, subscriber_id, effective_phone)
        except Exception as e:
            logger.warning("[wa-baileys] pre-attendance hook skip: %s", e)

    return {"ok": True, "queued": True, "subscriber_id": subscriber_id,
            "phone": effective_phone, "lid": payload.lid}


async def _process_inbound_ai_pipeline(
    *,
    cid: str,
    effective_phone: str,
    payload_jid: Optional[str],
    payload_text: str,
    payload_message_id: Optional[str],
    subscriber_id: Optional[str],
    subscriber_ctx: Optional[str],
    inbound_was_voice: bool = False,
) -> None:
    """Pipeline assíncrono de processamento de mensagem inbound:
      1. Manager Assistant (gestor manda comando)
      2. Auto-reply Isabella (cliente)
      3. Co-pilot IA (dica pro atendente humano)
    Executado em BackgroundTasks pra não bloquear a resposta do webhook.
    """
    # --- Manager Assistant — gestor manda comando, IA executa ---
    try:
        from services.manager_assistant import handle_manager_message
        mgr_reply = await handle_manager_message(
            cid, effective_phone, payload_text)
        if mgr_reply:
            try:
                async with httpx.AsyncClient(headers=_sidecar_headers(), timeout=12.0) as cli:
                    await cli.post(
                        f"{SIDECAR_BASE}/send",
                        json={"phone": payload_jid or effective_phone,
                              "text": mgr_reply},
                    )
            except Exception as e:
                logger.warning("[wa-baileys] manager reply send fail: %s", e)
            await db.aihub_wa_messages.insert_one({
                "id": f"wam-{uuid.uuid4().hex[:10]}",
                "company_id": cid,
                "direction": "outbound",
                "phone": effective_phone,
                "text": mgr_reply,
                "created_at": now_iso(),
                "metadata": {"manager_assistant": True},
            })
            try:
                from services.event_bus import emit_event
                await emit_event(
                    "wa.message.persisted",
                    company_id=cid,
                    source="whatsapp_baileys",
                    payload={},
                )
            except Exception:
                pass
            return
    except Exception as e:
        logger.warning("[wa-baileys] manager assistant falhou: %s", e)

    # --- Auto-reply (se habilitado) ---
    # Se o cliente mandou voice note (foi transcrito), retorna áudio TTS
    # na 1ª bolha pra UX "conversação falada"
    # DEBOUNCE: aguarda 2s antes de processar pra coalescer múltiplas msgs
    # rápidas do mesmo cliente (ex: "4" + "Estudo" no mesmo segundo).
    # Se outra msg chegar antes desse delay, cancela este timer e o próximo
    # processa tudo de uma vez (lendo o histórico completo).
    try:
        await _schedule_debounced_auto_reply(
            cid=cid, phone=effective_phone,
            user_text=payload_text,
            subscriber_id=subscriber_id,
            subscriber_ctx=subscriber_ctx,
            inbound_was_voice=inbound_was_voice,
        )
    except Exception as e:
        logger.warning("[wa-baileys] auto-reply falhou: %s", e)

    # --- Co-Pilot IA — dica interna para atendente humano ---
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
                recent_handover = age_s < 30
            except Exception:
                pass
        if (conv and conv.get("assignee_role") == "human"
                and conv.get("status") != "closed"
                and not recent_handover):
            from services.copilot_ai import maybe_insert_copilot_hint
            await maybe_insert_copilot_hint(
                company_id=cid,
                phone=effective_phone,
                last_inbound_text=payload_text,
                last_inbound_id=payload_message_id,
                subscriber_ctx=subscriber_ctx,
            )
    except Exception as e:
        logger.info("[wa-baileys] copilot skip: %s", e)


async def _legacy_inbound_ai_inline_DEPRECATED(payload, is_group, cid, effective_phone, subscriber_id, subscriber_ctx):
    """Versão antiga (inline) mantida só pra referência — não chamar."""
    if False:
        pass


# ---------------------------------------------------------------------------
# Helpers extraídos para services/wa/ai_helpers.py em iter106.
# Re-export pra compat com central_ia (que importa _fetch_human_few_shots
# direto deste módulo) e outras chamadas internas.
# ---------------------------------------------------------------------------
from services.wa.ai_helpers import (  # noqa: E402
    fetch_human_few_shots as _fetch_human_few_shots,
    persist_ai_failure as _persist_ai_failure,
)


# ---------------------------------------------------------------------------
# Debounce + Lock por phone — evita 2 respostas concorrentes quando o
# cliente envia mensagens rapidamente em sequência (ex: "4" + "Estudo").
#
# Estratégia:
#   1. _pending_tasks[phone] guarda o Task atualmente agendado pra um phone.
#   2. Quando nova msg chega, cancela o task anterior (se existir) e agenda
#      novo com sleep(DEBOUNCE_S). O LAST msg ganha — _maybe_auto_reply lê
#      o histórico completo do banco e responde com contexto unificado.
#   3. _phone_locks[phone] garante que duas execuções não se sobreponham
#      caso o debounce falhe (race condition em alto volume).
# ---------------------------------------------------------------------------
DEBOUNCE_SECONDS = 2.0
_pending_tasks: Dict[str, asyncio.Task] = {}
_phone_locks: Dict[str, asyncio.Lock] = {}


def _get_phone_lock(phone: str) -> asyncio.Lock:
    lock = _phone_locks.get(phone)
    if lock is None:
        lock = asyncio.Lock()
        _phone_locks[phone] = lock
    return lock


async def _schedule_debounced_auto_reply(
    cid: str, phone: str, user_text: str,
    subscriber_id: Optional[str],
    subscriber_ctx: Optional[str],
    inbound_was_voice: bool = False,
) -> None:
    """Agenda o auto-reply via scheduler PERSISTENTE em MongoDB.

    FIX P0 (Vando case): antes, o debounce era `asyncio.create_task` +
    dict in-memory (`_pending_tasks`). Em todo restart do backend
    (hot reload, deploy, crash), as tasks pendentes morriam e o cliente
    NUNCA recebia a resposta — só ao reenviar uma mensagem.

    Agora: `wa_reply_pending` (Mongo) + worker de recovery garante que
    nenhuma mensagem fica órfã, mesmo com restart no meio da janela.
    """
    try:
        from services.wa_reply_scheduler import schedule as _wrp_schedule
        await _wrp_schedule(
            company_id=cid, phone=phone, user_text=user_text,
            subscriber_id=subscriber_id, subscriber_ctx=subscriber_ctx,
            inbound_was_voice=inbound_was_voice,
        )
        logger.info(
            "[wa-debounce] agendado (persistente) phone=%s text=%r",
            phone, (user_text or "")[:60],
        )
    except Exception as e:
        logger.exception(
            "[wa-debounce] schedule persistente falhou phone=%s: %s",
            phone, e,
        )


async def _wa_reply_handler(
    *, cid: str, phone: str, user_text: str,
    subscriber_id: Optional[str], subscriber_ctx: Optional[str],
    inbound_was_voice: bool = False,
    metrics: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Adapter: scheduler persistente → _maybe_auto_reply.

    O scheduler chama esta função com timestamps já populados em `metrics`.
    Aqui adicionamos `llm_finish_at` e `send_finish_at` no melhor esforço
    (refinamento mais granular pode ser feito dentro de _maybe_auto_reply).
    """
    lock = _get_phone_lock(phone)
    async with lock:
        result = await _maybe_auto_reply(
            cid=cid, phone=phone, user_text=user_text,
            subscriber_id=subscriber_id,
            subscriber_ctx=subscriber_ctx,
            inbound_was_voice=inbound_was_voice,
        )
        if metrics is not None:
            now = datetime.now(timezone.utc)
            metrics.setdefault("llm_finish_at", now)
            metrics.setdefault("send_finish_at", now)
        return result


# Registra o handler no scheduler persistente (idempotente)
try:
    from services.wa_reply_scheduler import register_handler as _wrs_register
    _wrs_register(_wa_reply_handler)
except Exception as _e:
    logger.warning("[wa-baileys] register scheduler handler skip: %s", _e)


async def _maybe_auto_reply(cid: str, phone: str, user_text: str,
                              subscriber_id: Optional[str],
                              subscriber_ctx: Optional[str],
                              inbound_was_voice: bool = False) -> Optional[str]:
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
    # iter183 — Se um técnico (PWA) está conversando com o cliente,
    # PAUSA a IA. Janela: 4h desde a última msg do técnico. Quando o
    # técnico envia algo novo, a janela é renovada via upsert no
    # public_tech_send. Comportamento: NÃO é falha — IA simplesmente
    # silencia para não atropelar a conversa do técnico.
    if conv and conv.get("has_tech_conversation"):
        last_tech_at = conv.get("last_tech_msg_at")
        if last_tech_at:
            try:
                t = datetime.fromisoformat(last_tech_at.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - t).total_seconds()
                if age < 4 * 3600:  # 4h
                    logger.info(
                        "[wa-baileys] auto-reply pulado — técnico %s ativo (%s, idade=%.0fs)",
                        conv.get("last_tech_collab_name") or "?",
                        phone, age,
                    )
                    return None
            except Exception:
                pass

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

    # 1b. FAST PATH — Fluxo de boleto/2ª via.
    # Detecta intenção e responde DIRETO com dados do Atlaz (sem LLM).
    # Envia texto curto + PDF anexo branded por cada fatura aberta.
    try:
        from services.boleto_flow import handle_boleto_flow_full
        boleto_full = await handle_boleto_flow_full(
            cid, phone, user_text, subscriber_id=subscriber_id
        )
        if boleto_full:
            await _deliver_boleto_with_pdf(
                cid, phone, subscriber_id, boleto_full,
            )
            return boleto_full.get("text")
    except Exception as e:
        logger.warning("[wa-baileys] boleto_flow falhou (segue p/ LLM): %s", e)

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

    # 2.1. HANDOFF DETERMINÍSTICO (pré-LLM): se o agente já fixado é o errado
    # pra essa mensagem (ex.: Isabella em conversa antiga, cliente agora pede
    # boleto), troca aqui mesmo. Economiza tokens + corrige leaks de escopo
    # que o LLM falha em detectar via marker.
    #
    # Anti-loop: se a conversa recebeu handoff nas últimas 3 mensagens do
    # cliente, NÃO força novo redirecionamento — deixa o agente atual
    # responder. Evita ping-pong infinito.
    try:
        from services.wa.handoff_detection import detect_forced_handoff
        conv_doc = await db.wa_conversations.find_one(
            {"company_id": cid, "phone": phone},
            {"_id": 0, "last_handoff_at": 1},
        )
        recent_handoff = False
        last_ho_iso = (conv_doc or {}).get("last_handoff_at")
        if last_ho_iso:
            try:
                msgs_since_ho = await db.aihub_wa_messages.count_documents({
                    "company_id": cid, "phone": phone,
                    "direction": "inbound",
                    "created_at": {"$gt": last_ho_iso},
                })
                recent_handoff = msgs_since_ho < 3
            except Exception:
                recent_handoff = False
        forced_target = detect_forced_handoff(
            agent.get("name"), user_text, recent_handoff=recent_handoff,
        )
        if forced_target:
            forced_agent = await db.aihub_agents.find_one(
                {"company_id": cid, "name": forced_target, "active": True},
                {"_id": 0},
            )
            if forced_agent:
                logger.info(
                    "[wa-baileys] handoff determinístico %s → %s phone=%s",
                    agent.get("name"), forced_agent.get("name"), phone,
                )
                # Atualiza conversa + registra handoff_greeting
                await db.wa_conversations.update_one(
                    {"company_id": cid, "phone": phone},
                    {"$set": {
                        "routed_agent_id": forced_agent.get("id"),
                        "routed_agent_name": forced_agent.get("name"),
                        "last_handoff_at": now_iso(),
                        "last_handoff_from": agent.get("name"),
                        "last_handoff_kind": "deterministic",
                    }},
                    upsert=True,
                )
                # O novo agente passa a atender a mensagem atual
                agent = forced_agent
    except Exception as e:
        logger.debug("[wa-baileys] forced handoff skip: %s", e)

    # 3. Monta prompt — herda personalidade/preços/situações + contexto do cliente
    sys_prompt = agent["system_prompt"]
    extra = []

    # 3.0. DATA E HORA ATUAIS (BRT) — sempre injetado pra IA saber "hoje"
    # quando cliente perguntar ou for agendar visita técnica/instalação.
    try:
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        _now_brt = _dt.now(_tz.utc).astimezone(_tz(_td(hours=-3)))
        _wd = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
                "sexta-feira", "sábado", "domingo"][_now_brt.weekday()]
        _periodo = ("madrugada" if _now_brt.hour < 6 else
                      "manhã" if _now_brt.hour < 12 else
                      "tarde" if _now_brt.hour < 18 else "noite")
        extra.append(
            "=== AGORA (DATA E HORA ATUAIS · BRASIL · BRT/UTC-3) ===\n"
            f"Data: {_now_brt.strftime('%d/%m/%Y')} ({_wd})\n"
            f"Horário: {_now_brt.strftime('%H:%M')} ({_periodo})\n"
            f"ISO: {_now_brt.isoformat(timespec='minutes')}\n"
            "Use ESTA data como referência absoluta para 'hoje', 'amanhã', "
            "'depois de amanhã', 'esta semana', 'que dia é hoje', 'que horas '"
            "são', e para todo agendamento de visita técnica ou instalação. "
            "Quando oferecer datas, calcule a partir DESTA data — nunca "
            "invente datas passadas ou de outro ano."
        )
    except Exception as _e:
        logger.debug("[wa-baileys] inject now_brt skip: %s", _e)

    if agent.get("company_info"):
        extra.append(f"=== INFORMAÇÕES DA EMPRESA ===\n{agent['company_info']}")
    # PREÇOS — Tabela oficial (pricing_catalog) é a fonte primária;
    # fallback pro campo livre pricing_info legado se o catálogo
    # estiver vazio.
    _pricing_block = ""
    try:
        from routes.pricing_catalog import compose_pricing_block
        _pricing_block = await compose_pricing_block(cid)
    except Exception as _e:
        logger.debug("[wa-baileys] pricing catalog skip: %s", _e)
    if _pricing_block:
        extra.append(_pricing_block)
    elif agent.get("pricing_info"):
        extra.append(f"=== PREÇOS E VALORES ===\n{agent['pricing_info']}")
    if agent.get("priority_situations"):
        extra.append(f"=== SITUAÇÕES PRIORITÁRIAS ===\n{agent['priority_situations']}")

    # 3.0b. HORÁRIO COMERCIAL — IA precisa saber se há humano disponível
    # pra escalar AGORA, e qual mensagem dar quando cliente pedir humano
    # fora do expediente. Config editável em Configurações.
    try:
        from services.business_hours import format_for_prompt as _bh_fmt
        bh_block = await _bh_fmt(cid)
        if bh_block:
            extra.append(bh_block)
    except Exception as _e:
        logger.debug("[wa-baileys] business_hours skip: %s", _e)

    # 3.0c. VIABILIDADE TÉCNICA — se o cliente mandou um endereço (rua,
    # avenida, CEP, bairro), checa cobertura cruzando com subscribers
    # ativos + CTOs. Injeta bloco === VIABILIDADE TÉCNICA === pra Isabella.
    try:
        from services.coverage_checker import (
            looks_like_address, check_coverage,
            format_for_prompt as _cov_fmt,
        )
        if looks_like_address(user_text):
            cov = await asyncio.wait_for(
                check_coverage(cid, user_text), timeout=4.0,
            )
            if cov:
                extra.append(_cov_fmt(cov))
                logger.info(
                    "[coverage] check phone=%s viable=%s neighbors=%d "
                    "ctos=%d", phone, cov.get("viable"),
                    len(cov.get("neighbors") or []),
                    len(cov.get("ctos") or []),
                )
    except asyncio.TimeoutError:
        logger.warning("[coverage] timeout pra phone=%s", phone)
    except Exception as _e:
        logger.warning("[coverage] skip: %s", _e)

    # 3.0d. LOOKUP CNPJ — CEO 17/02/2026. Quando o cliente envia um CNPJ
    # (14 dígitos, com/sem pontuação), consulta BrasilAPI e injeta
    # === LOOKUP CNPJ === pra Isabella confirmar empresa + escalar pro
    # Consultor PJ. Implementa Regra de Ouro (1.5): evidência objetiva
    # antes de afirmar nome/endereço de empresa.
    try:
        from services.cnpj_lookup import extract_cnpj, lookup as cnpj_lookup
        cnpj_d = extract_cnpj(user_text)
        if cnpj_d:
            cnpj_data = await asyncio.wait_for(cnpj_lookup(cnpj_d), timeout=6.0)
            if cnpj_data.get("ok"):
                block = (
                    "=== LOOKUP CNPJ (evidência objetiva — Regra de Ouro) ===\n"
                    f"CNPJ: {cnpj_data['cnpj']} ({cnpj_data['situacao']})\n"
                    f"Razão social: {cnpj_data['razao_social']}\n"
                    + (f"Nome fantasia: {cnpj_data['nome_fantasia']}\n"
                        if cnpj_data['nome_fantasia'] else "")
                    + f"Endereço: {cnpj_data['address_full']}\n"
                    + (f"Atividade: {cnpj_data['cnae_descricao']}\n"
                        if cnpj_data['cnae_descricao'] else "")
                    + (f"Porte: {cnpj_data['porte']}\n" if cnpj_data['porte'] else "")
                    + "\nUSE estes dados pra confirmar com o cliente "
                    "(trilha 6.8). Se ATIVA + cliente confirmar, "
                    "envie [CONSULTOR_PJ_ACIONAR]."
                )
            else:
                block = (
                    "=== LOOKUP CNPJ (FALHA — Regra de Ouro) ===\n"
                    f"CNPJ enviado: {cnpj_d}\n"
                    f"Erro: {cnpj_data.get('error')}\n"
                    "NÃO confirme nome/endereço de cabeça. Peça pro "
                    "cliente confirmar os números do CNPJ."
                )
            extra.append(block)
            logger.info(
                "[cnpj_lookup] phone=%s cnpj=%s ok=%s situacao=%s",
                phone, cnpj_d, cnpj_data.get("ok"),
                cnpj_data.get("situacao"),
            )
    except asyncio.TimeoutError:
        logger.warning("[cnpj_lookup] timeout pra phone=%s", phone)
    except Exception as _e:
        logger.warning("[cnpj_lookup] skip: %s", _e)
    # 3a. Conflito de vínculo: se o telefone está vinculado a 2+ subscribers
    # cadastrados, a IA NÃO pode chamar pelo nome (vazaria dados de outro
    # cliente). Injeta diretiva clara forçando a IA a pedir CPF antes de
    # qualquer personalização. Detecção feita aqui (re-lookup leve) pra não
    # ter que propagar a flag por toda a pipeline.
    conflict_count = 0
    if not subscriber_ctx:  # só importa quando não há vínculo único certo
        try:
            from routes.subscribers import find_subscriber_by_phone
            _r = await find_subscriber_by_phone(cid, phone)
            if _r and _r.get("status") == "conflict":
                conflict_count = len(_r.get("matches") or [])
        except Exception as e:
            logger.debug("[wa-baileys] conflict re-check skip: %s", e)
    if conflict_count >= 2:
        extra.append(
            "=== CONFLITO DE CADASTRO (CRÍTICO) ===\n"
            f"Este número de WhatsApp está cadastrado em {conflict_count} "
            "assinantes diferentes no nosso sistema. NÃO use nenhum nome "
            "próprio até o cliente CONFIRMAR a identidade — vazar nome de "
            "outro cliente é uma falha grave de privacidade.\n"
            "REGRA: na primeira resposta, peça gentilmente o CPF do titular "
            "da conta para identificar qual cadastro é o dele. Exemplo: "
            "\"Identifiquei mais de um cadastro com esse número 🙂 Pode me "
            "confirmar o CPF do titular para eu te atender certinho?\"\n"
            "Só personalize a conversa (nome/plano/endereço) DEPOIS que o "
            "cliente confirmar o CPF e o sistema vincular oficialmente."
        )
    if subscriber_ctx:
        extra.append(f"=== CLIENTE IDENTIFICADO ===\n{subscriber_ctx}\n\n"
                     "Use essas informações para personalizar — mas não recite "
                     "tudo, use só o que for relevante para a dúvida atual.")
    else:
        # CLIENTE NÃO IDENTIFICADO POR TELEFONE — aciona fluxo CPF
        # Detecta LID anônimo (telefone começa com 169/197/15+ dígitos sem 55)
        is_lid_phone = (
            len(phone) >= 14 and not phone.startswith("55")
            and (phone.startswith("169") or phone.startswith("197")
                  or phone.startswith("198"))
        )
        if is_lid_phone:
            extra.append(
                "=== CLIENTE COM WHATSAPP LID ANÔNIMO ===\n"
                "Este cliente está usando o WhatsApp com privacidade ativada "
                "(LID anônimo). NÃO TEMOS o telefone real dele. NÃO repita "
                "a mesma pergunta várias vezes — se o cliente já mandou "
                "uma mensagem, peça apenas: 1) NOME COMPLETO, 2) CPF do "
                "titular. Com isso o gestor consegue vincular manualmente. "
                "Se ele estiver com problema técnico urgente, transfira "
                "para atendente humano falando: 'Vou chamar nosso atendente "
                "para te ajudar pessoalmente, um momento'. Seja gentil e "
                "objetivo — não fique pedindo bairro/CEP repetidamente."
            )
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

    # 3a-pre. ÁLVARO TOOLS — diagnóstico SmartOLT + slots da Lousa
    # Quando a mensagem parece reparo técnico, busca status da ONU + slots e
    # injeta como contexto. O Álvaro recebe diagnóstico pronto + opções
    # de agendamento, e usa markers [REBOOT_ONU] / [AGENDAR_REPARO:...] pra
    # disparar as ações (tratadas no marker_router após a resposta).
    alvaro_diag = None
    try:
        from services.alvaro_tools import (
            looks_like_support, diagnose_for_alvaro, fetch_available_slots,
            format_diag_context,
        )
        if looks_like_support(user_text):
            alvaro_diag = await diagnose_for_alvaro(phone)
            if alvaro_diag and alvaro_diag.get("found"):
                slots = await fetch_available_slots(
                    alvaro_diag.get("company_id") or cid)
                ctx = format_diag_context(alvaro_diag, slots)
                if ctx:
                    extra.append(ctx)
                    logger.info(
                        "[alvaro_tools] diag injetado phone=%s status=%s slots=%d",
                        phone, alvaro_diag.get("status"), len(slots),
                    )
    except Exception as e:
        logger.warning("[alvaro_tools] skip: %s", e)

    # 3a-bis. ÁLVARO TOOLS — Wi-Fi self-service (Premium gate + upsell)
    # Quando a mensagem parece "trocar senha do wifi", injeta contexto com
    # estado computado (ready / premium_required / onu_offline / no_onu /
    # rate_limited) + instruções de fluxo. Markers [TROCAR_WIFI] e
    # [OFFER_UPGRADE] processados depois.
    wifi_ctx = None
    try:
        from services.alvaro_tools import (
            looks_like_wifi_change, fetch_wifi_status_for_alvaro,
            format_wifi_context,
        )
        if looks_like_wifi_change(user_text):
            # Resolve subscriber por telefone via cache do alvaro_diag se já
            # foi calculado — senão, descobre agora via lookup direto.
            sid_hint = (alvaro_diag or {}).get("subscriber_id")
            if not sid_hint:
                from routes.wifi import _resolve_subscriber_by_phone
                _sub = await _resolve_subscriber_by_phone(cid, phone)
                sid_hint = (_sub or {}).get("id")
            wifi_ctx = await fetch_wifi_status_for_alvaro(sid_hint, cid)
            ctx_text = format_wifi_context(wifi_ctx or {})
            extra.append(ctx_text)
            # injeta subscriber_id pra ação posterior nos markers
            if wifi_ctx is None and sid_hint:
                wifi_ctx = {"subscriber_id": sid_hint, "state": "unknown"}
            elif wifi_ctx:
                wifi_ctx["subscriber_id"] = sid_hint
            logger.info("[alvaro_tools] wifi ctx phone=%s state=%s sid=%s",
                        phone, (wifi_ctx or {}).get("state"), sid_hint)
    except Exception as e:
        logger.warning("[alvaro_tools] wifi ctx skip: %s", e)

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

            # Análise de HISTÓRICO do cliente — classifica problema como
            # persistente/recorrente/esporádico/eventual e injeta no prompt.
            # Isabella adapta o tom: persistente => empatia REAL, compensação.
            try:
                from services.customer_history import (
                    analyze_customer_history, format_history_for_prompt,
                )
                history = await analyze_customer_history(
                    cid, subscriber_id, current_phone=phone,
                )
                hist_block = format_history_for_prompt(history)
                if hist_block:
                    extra.append(hist_block)
                conn_info["history_classification"] = history.get("classification")
            except Exception as e:
                logger.info("[wa-baileys] history analysis skip: %s", e)

            # AÇÃO REAL — estratégia diferenciada por status (decisão 02/2026):
            #   - LOS: NÃO reinicia (não resolve fibra rompida). Cria bolha de
            #     reparo prioritária na Lousa AUTOMATICAMENTE. Isabella agenda
            #     a janela com o cliente usando a agenda da Lousa.
            #   - Offline: NÃO reinicia, NÃO abre chamado. Provável problema do
            #     lado do cliente (energia/tomada/cabo) — Isabella TRANSFERE
            #     direto pro Atendimento Especializado (handoff humano).
            #   - Power fail: NÃO é problema nosso (queda de luz no cliente).
            #     Ofereça agendamento de visita técnica.
            status_l = (conn_info.get("status") or "").strip().lower()
            try:
                from services.subscriber_connection import (
                    ensure_repair_ticket,
                    format_ticket_for_prompt,
                    format_power_fail_offer_for_prompt,
                    format_offline_transfer_for_prompt,
                )
                if conn_info.get("found") and status_l == "los":
                    # LOS → cria bolha de reparo na Lousa AUTOMATICAMENTE.
                    ticket_info = await ensure_repair_ticket(
                        cid, conn_info, phone, user_text
                    )
                    if ticket_info:
                        extra.append(format_ticket_for_prompt(ticket_info))
                elif conn_info.get("found") and status_l == "offline":
                    # Offline → transfere pra humano. Sem ticket, sem reboot.
                    # O handoff de fato é executado APÓS o envio (detectado
                    # pelo marcador no texto da resposta).
                    extra.append(format_offline_transfer_for_prompt())
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

    # 3g. Disponibilidade da LOUSA — quando cliente pede agendamento/visita,
    # injetamos a grade de horários atual pra Isabella só oferecer slots
    # com vagas. Implementa a regra: "nunca oferecer data que já tem
    # agendamento na lousa".
    try:
        from services.lousa_availability import (
            detects_scheduling_intent, get_availability_for_prompt,
        )
        if detects_scheduling_intent(user_text):
            lousa_block = await get_availability_for_prompt(cid, days=7)
            if lousa_block:
                extra.append(lousa_block)
                logger.info(
                    "[wa-baileys] lousa availability injetada p/ phone=%s", phone,
                )
    except Exception as e:
        logger.info("[wa-baileys] lousa availability skip: %s", e)

    # 3h. Fragments ativos da Isabella — módulos categorizados (vendas /
    # promoção / upgrade / novidade) gerenciados pelo gestor na sub-aba
    # "Gestão" do Atendimento IA. Cada módulo ligado é injetado aqui.
    try:
        from routes.isabella_prompt import compose_active_fragments_block
        frag_block = await compose_active_fragments_block(cid)
        if frag_block:
            extra.append(frag_block)
    except Exception as e:
        logger.info("[wa-baileys] fragments skip: %s", e)

    # 3i. Isabella V15 — ORÁCULO RELACIONAL ABSOLUTO
    # Orquestra as 4 prioridades (promessas, problemas recentes, memória
    # pessoal, VIP) + Regra de Afirmações (evidências auditadas).
    # Limita a 2 referências naturais — proíbe afirmação sem evidência.
    try:
        from services.customer_memory import build_v15_oracle_block
        oracle_block = await build_v15_oracle_block(
            company_id=cid, phone=phone, subscriber_id=subscriber_id,
        )
        if oracle_block:
            extra.append(oracle_block)
            logger.info(
                "[wa-baileys] V15 oracle block injetado phone=%s", phone,
            )
    except Exception as e:
        logger.info("[wa-baileys] V15 oracle block skip: %s", e)

    sys_prompt += "\n\n" + "\n\n".join(extra)

    # ════════════════════════════════════════════════════════════════
    # HUMANIZER — camada única (anti-CPF + listening + short-term +
    # conversa contínua). Mesmo helper de todos os canais.
    # ════════════════════════════════════════════════════════════════
    humanizer_ctx: dict = {}
    try:
        from services.humanizer import humanize_system_prompt
        sys_prompt, humanizer_ctx = await humanize_system_prompt(
            sys_prompt=sys_prompt, company_id=cid,
            phone=phone, user_text=user_text)
    except Exception as e:
        logger.info("[wa-baileys] humanizer prompt skip: %s", e)
    link_for_guard = humanizer_ctx.get("link_for_guard")
    listening_analysis = humanizer_ctx.get("listening_analysis") or {}

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

        # ────────────────────────────────────────────────────────────────
        # MARKER ROUTER — markers de funil de vendas + roteamento Isabella
        # ────────────────────────────────────────────────────────────────
        # Processa markers funcionais ([HOT_LEAD], [VENDA_AGENDADA],
        # [ROTEAR_HUMANO], [ROTEAR_FINANCEIRO], [CHURN_RISK]) que disparam
        # ações no sistema (cria ticket, alerta retenção, pausa IA, etc.)
        # Esses markers são REMOVIDOS do texto antes de enviar ao cliente.
        # NÃO interfere no HANDOFF_MAP abaixo ([ROTEAR_VENDAS/SUPORTE/
        # COBRANCA/TESTE]) que troca o agente da conversa.
        try:
            from services.marker_router import process_markers
            reply_text = await process_markers(
                reply_text, phone, cid,
            )
        except Exception as e:
            logger.warning("[marker_router] erro: %s", e)

        # Álvaro tools: processa [REBOOT_ONU] e [AGENDAR_REPARO:...]
        # (chamadas em paralelo ao marker_router; se diag existir o Álvaro
        # pode reiniciar a ONU e agendar reparo direto no mesmo turno).
        try:
            # Roda action processor sempre — markers de wifi/upgrade podem
            # estar presentes mesmo sem alvaro_diag (cliente pediu trocar wifi
            # diretamente, sem etapa de diagnóstico).
            if (alvaro_diag and alvaro_diag.get("found")) or wifi_ctx:
                from services.alvaro_tools import process_alvaro_actions
                reply_text = await process_alvaro_actions(
                    reply_text, phone, alvaro_diag, wifi_ctx=wifi_ctx,
                )
        except Exception as e:
            logger.warning("[alvaro_tools] actions erro: %s", e)

        # ────────────────────────────────────────────────────────────────
        # HANDOFF: detecta marker [ROTEAR_X] na resposta e troca de agente
        # ────────────────────────────────────────────────────────────────
        # Mapping dos markers → nome do agente alvo
        HANDOFF_MAP = {
            "[ROTEAR_VENDAS]":    "Isabella",
            "[ROTEAR_SUPORTE]":   "Alvaro",
            "[ROTEAR_COBRANCA]":  "Pâmela",
            "[ROTEAR_COBRANÇA]":  "Pâmela",  # acentuado, IA pode gerar assim
            "[ROTEAR_TESTE]":     "Teste",
        }
        handoff_target_name: Optional[str] = None
        for marker, target_name in HANDOFF_MAP.items():
            if reply_text and marker in reply_text:
                # Não passa pro próprio agente atual
                if (agent.get("name") or "").lower() == target_name.lower():
                    reply_text = reply_text.replace(marker, "").strip()
                    continue
                handoff_target_name = target_name
                reply_text = reply_text.replace(marker, "").strip()
                break

        # ANTI-LOOP: se a conversa já recebeu handoff nas últimas 3 mensagens
        # do cliente, ignoramos a tentativa de re-rotear pra evitar
        # ping-pong infinito (cliente que troca de tema toda hora).
        # Limpamos o marker e deixamos o agente atual responder normalmente.
        if handoff_target_name:
            try:
                conv = await db.wa_conversations.find_one(
                    {"company_id": cid, "phone": phone},
                    {"_id": 0, "last_handoff_at": 1},
                )
                last_ho = (conv or {}).get("last_handoff_at")
                if last_ho:
                    # Conta turnos de cliente desde o último handoff
                    inbound_since = await db.aihub_wa_messages.count_documents({
                        "company_id": cid,
                        "phone": phone,
                        "direction": "inbound",
                        "created_at": {"$gt": last_ho},
                    })
                    if inbound_since < 3:
                        logger.info(
                            "[wa-baileys] handoff %s→%s BLOQUEADO (anti-loop: "
                            "%d msgs do cliente desde último handoff em %s)",
                            agent.get("name"), handoff_target_name,
                            inbound_since, last_ho,
                        )
                        handoff_target_name = None
            except Exception as e:
                logger.info("[wa-baileys] anti-loop check skip: %s", e)

        if handoff_target_name:
            try:
                # Busca o agente alvo
                target_agent = await db.aihub_agents.find_one(
                    {"company_id": cid, "name": handoff_target_name,
                     "active": True},
                    {"_id": 0},
                )
                if target_agent:
                    # Atualiza routed_agent_id na conversa (próximas msgs já
                    # vão pro novo agente automaticamente)
                    await db.wa_conversations.update_one(
                        {"company_id": cid, "phone": phone},
                        {"$set": {
                            "routed_agent_id": target_agent.get("id"),
                            "routed_agent_name": target_agent.get("name"),
                            "last_handoff_at": now_iso(),
                            "last_handoff_from": agent.get("name"),
                        }},
                        upsert=True,
                    )
                    logger.info(
                        "[wa-baileys] handoff %s → %s phone=%s",
                        agent.get("name"), target_agent.get("name"), phone,
                    )
                    # Marca a saudação do novo agente pra ser enviada como
                    # segunda mensagem após o texto atual ser entregue
                    handoff_pending_agent = target_agent
                else:
                    logger.warning(
                        "[wa-baileys] handoff alvo %s não encontrado", handoff_target_name)
                    handoff_pending_agent = None
            except Exception as e:
                logger.warning("[wa-baileys] handoff falhou: %s", e)
                handoff_pending_agent = None
        else:
            handoff_pending_agent = None

        # Interceptor: se IA incluiu o marcador [GERAR_ONBOARDING_LINK],
        # cria a sessão de onboarding e substitui pela URL real.
        if reply_text and "[GERAR_ONBOARDING_LINK]" in reply_text:
            try:
                from services.onboarding import create_session
                # Tenta extrair plano da última mensagem da Isabella
                plan_match = re.search(
                    r"(\d{2,4}\s*M[EeÉé][Gg][Aa][^\n\.\,]*)", reply_text
                )
                plan_name = plan_match.group(1).strip() if plan_match else None
                obs = await create_session(
                    company_id=cid,
                    phone=phone,
                    plan_name=plan_name,
                    suggested_name=(subscriber_ctx or {}).get("name"),
                )
                reply_text = reply_text.replace(
                    "[GERAR_ONBOARDING_LINK]", obs["url"]
                )
                logger.info(
                    "[wa-baileys] onboarding link gerado phone=%s url=%s",
                    phone, obs["url"][:60],
                )
            except Exception as e:
                logger.warning("[wa-baileys] onboarding link skip: %s", e)
                # Remove o marcador mesmo se falhar, evitando vazar pra cliente
                reply_text = reply_text.replace("[GERAR_ONBOARDING_LINK]", "")
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

    # ════════════════════════════════════════════════════════════════
    # HUMANIZER REPLY — rewrite (listening + anti-CPF) + bolhas (≤180c
    # + anti-greet em conversa contínua). Mesmo helper de todos canais.
    # ════════════════════════════════════════════════════════════════
    try:
        from services.humanizer import humanize_reply, bubbles_for_send
        reply_text = await humanize_reply(
            reply_text=reply_text, ctx=humanizer_ctx,
            company_id=cid, phone=phone)
        humanized_bubbles = bubbles_for_send(
            reply_text=reply_text, ctx=humanizer_ctx, max_bubbles=6)
        chunks = humanized_bubbles or _split_ai_reply(reply_text,
                                                           max_chunks=6)
    except Exception as e:
        logger.warning("[wa-baileys] humanizer reply falhou: %s", e)
        chunks = _split_ai_reply(reply_text, max_chunks=6)

    # 5b. Se cliente mandou voice note, gera TTS do texto completo e envia
    # como áudio APÓS as bolhas de texto (UX "conversa falada").
    tts_audio_b64: Optional[str] = None
    if inbound_was_voice and chunks:
        try:
            from services.tts import synthesize_speech
            # Junta as bolhas em texto contínuo pro TTS, mas remove emojis
            # excessivos que ficam estranhos quando falados
            full_text = " ".join(chunks)
            audio_bytes = await synthesize_speech(cid, full_text)
            if audio_bytes:
                tts_audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
                logger.info("[wa-baileys] 🔊 TTS gerado · %s bytes",
                            len(audio_bytes))
        except Exception as e:
            logger.warning("[wa-baileys] TTS falhou: %s", e)

    # 6. Envia cada chunk via sidecar (sequencial, pequeno delay entre eles).
    # ANTI-DUPLICAÇÃO: antes de enviar, busca as últimas 6 bolhas outbound
    # nos últimos 60s. Se a chunk atual já foi enviada (texto idêntico após
    # strip+lower), PULA — evita duplicar saudação ou bolha em race condition.
    import asyncio as _asyncio
    try:
        cutoff_dup = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        recent_out = await db.aihub_wa_messages.find(
            {"company_id": cid, "phone": phone, "direction": "outbound",
             "created_at": {"$gt": cutoff_dup}},
            {"_id": 0, "text": 1}, sort=[("created_at", -1)], limit=6,
        ).to_list(6)
        recent_texts = {(m.get("text") or "").strip().lower()
                        for m in recent_out if m.get("text")}
    except Exception as e:
        logger.info("[wa-baileys] dedup lookup skip: %s", e)
        recent_texts = set()

    any_sent = False
    last_send_error: Optional[str] = None
    for idx, chunk in enumerate(chunks):
        chunk_norm = (chunk or "").strip().lower()
        if chunk_norm and chunk_norm in recent_texts:
            logger.warning(
                "[wa-baileys] DUPLICATE chunk evitado phone=%s text=%.80s",
                phone, chunk,
            )
            continue
        recent_texts.add(chunk_norm)
        send_ok = False
        send_error: Optional[str] = None
        send_body: Dict[str, Any] = {}
        try:
            async with httpx.AsyncClient(headers=_sidecar_headers(), timeout=15.0) as cli:
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

    # 6b. Após bolhas de texto, manda TTS se cliente mandou voice note
    if tts_audio_b64 and any_sent:
        try:
            await _asyncio.sleep(0.4)
            # P0.4 A1 — Roteado via gateway (TTS auto-resposta)
            from services.wa.sidecar import _sidecar_post_silent
            tts_body = await _sidecar_post_silent("/send-audio", {
                "phone": phone,
                "audio_b64": tts_audio_b64,
                "mimetype": "audio/ogg; codecs=opus",
                "ptt": True,
                "company_id": cid,
            }) or {}
            await db.aihub_wa_messages.insert_one({
                "id": f"wam-tts-{uuid.uuid4().hex[:10]}",
                "company_id": cid,
                "direction": "outbound",
                "phone": phone,
                "text": "🔊 Resposta em áudio",
                "channel": "baileys",
                "media_type": "audio",
                "media_is_ptt": True,
                "auto_generated": True,
                "auto_reason": "tts_response_to_voice_note",
                "message_id": tts_body.get("message_id"),
                "subscriber_id": subscriber_id,
                "session_id": f"wa-{phone}",
                "auto_reply": True,
                "delivery_status": "sent" if tts_body.get("ok")
                                    else "failed_sidecar",
                "created_at": now_iso(),
            })
        except Exception as e:
            logger.warning("[wa-baileys] envio TTS falhou: %s", e)

    send_ok = any_sent
    send_error = last_send_error
    if send_ok:
        logger.info("[wa-baileys] auto-reply enviado em %d bolha(s) para %s: %s",
                     len(chunks), phone, reply_text[:80])
        # Isabella V14 — detecta promessas da própria Isabella
        # ("vou verificar", "te retorno") e marca follow-up obrigatório
        # na próxima conversa.
        try:
            from services.customer_memory import (
                detect_promise, register_promise,
            )
            promise_text = detect_promise(reply_text)
            if promise_text:
                await register_promise(
                    company_id=cid, phone=phone,
                    subscriber_id=subscriber_id,
                    promise_text=promise_text,
                    context_user_text=user_text,
                )
                logger.info(
                    "[wa-baileys] promessa registrada phone=%s: %s",
                    phone, promise_text[:80],
                )
        except Exception as _e:
            logger.debug(
                "[wa-baileys] promise capture skip: %s", _e,
            )
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

    # 🟠 Auto-handover: Isabella concluiu a venda → transfere para "aguardando"
    # Detecta padrões claros de finalização de venda no texto da resposta para
    # mover a conversa do bucket "automatico" para "aguardando" (atendente
    # humano valida e fecha o pós-venda).
    if send_ok and _is_sales_completion(reply_text):
        try:
            await db.wa_conversations.update_one(
                {"company_id": cid, "phone": phone},
                {"$set": {
                    "assignee_role": None,
                    "assignee_user_id": None,
                    "sales_completed_at": now_iso(),
                    "sales_completion_reason": "isabella_handoff_to_human",
                    "updated_at": now_iso(),
                }},
            )
            logger.info(
                "[wa-baileys] venda concluída pela Isabella — "
                "%s movido para 'aguardando'", phone
            )
        except Exception as e:
            logger.warning("[wa-baileys] falha ao mover para aguardando: %s", e)

    # 🔴 Auto-handover de DIAGNÓSTICO OFFLINE: quando a Isabella conclui que o
    # equipamento está Offline e diz "vou transferir pro Atendimento
    # Especializado", o backend move a conversa pra `aguardando` e marca a
    # razão pra auditoria. Atendente humano assume manualmente em seguida.
    if send_ok:
        try:
            from services.subscriber_connection import is_offline_handoff_message
            if is_offline_handoff_message(reply_text):
                await db.wa_conversations.update_one(
                    {"company_id": cid, "phone": phone},
                    {"$set": {
                        "assignee_role": None,
                        "assignee_user_id": None,
                        "handoff_at": now_iso(),
                        "handoff_reason": "isabella_offline_diagnosis",
                        "updated_at": now_iso(),
                    }},
                )
                logger.info(
                    "[wa-baileys] handoff Offline pela Isabella — "
                    "%s movido para 'aguardando'", phone
                )
        except Exception as e:
            logger.warning("[wa-baileys] falha ao mover handoff offline: %s", e)

    # ─────────────────────────────────────────────────────────────
    # HANDOFF FOLLOW-UP: novo agente envia saudação inicial logo
    # após a mensagem de despedida do agente anterior. Cria a
    # sensação de "passei a bola, ela já chegou".
    # ─────────────────────────────────────────────────────────────
    if send_ok and handoff_pending_agent:
        try:
            await asyncio.sleep(2.0)  # pequena pausa pra UX humana
            greeting = (handoff_pending_agent.get("initial_message")
                          or f"Oi! Aqui é o(a) {handoff_pending_agent.get('name')}. Vou continuar te ajudando 🙂")
            # Envia saudação direta sem chamar LLM de novo (economia de tokens
            # + saudação fica idêntica à inicial cadastrada no agente).
            sent = await _sidecar_post_silent(
                "/send", {"phone": phone, "text": greeting},
            )
            if sent.get("ok") is not False:
                await db.aihub_wa_messages.insert_one({
                    "company_id": cid, "phone": phone,
                    "jid": f"{phone}@s.whatsapp.net",
                    "direction": "outbound", "text": greeting,
                    "subscriber_id": subscriber_id,
                    "auto_reply": True,
                    "agent": handoff_pending_agent.get("name"),
                    "agent_id": handoff_pending_agent.get("id"),
                    "is_handoff_greeting": True,
                    "handoff_from": agent.get("name"),
                    "delivery_status": "sent",
                    "external_id": sent.get("message_id"),
                    "created_at": now_iso(),
                })
                logger.info(
                    "[wa-baileys] handoff greeting %s → %s entregue",
                    agent.get("name"), handoff_pending_agent.get("name"),
                )
            else:
                logger.warning(
                    "[wa-baileys] handoff greeting falhou: %s",
                    sent.get("error"))
        except Exception as e:
            logger.warning("[wa-baileys] handoff greeting top-level: %s", e)

    return reply_text


# ---------------------------------------------------------------------------
# Detecção de conclusão de venda — extraída para services/wa/sales_detection.py
# Re-export pra compat com código que importa direto deste módulo.
# ---------------------------------------------------------------------------
from services.wa.sales_detection import (  # noqa: E402
    is_sales_completion as _is_sales_completion,
)




@router.get("/viability-heatmap")
async def get_viability_heatmap(
    days: int = 30,
    user: dict = Depends(require_role("gestor")),
):
    """Mapa de calor de leads SEM_REGISTROS — agrega `viability_requests`
    (lead sem cobertura) por bairro. Identifica regiões pra expansão de
    malha guiada por demanda real."""
    from services.coverage_checker import parse_address

    cid = user.get("company_id") or DEMO_COMPANY_ID
    days = max(1, min(int(days or 30), 365))
    since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since_dt.isoformat()

    # Pula os requests da janela
    requests = await db.viability_requests.find(
        {"company_id": cid, "created_at": {"$gte": since_iso}},
        {"_id": 0, "phone": 1, "created_at": 1, "address_text": 1,
         "address_district": 1, "status": 1},
    ).to_list(2000)

    # Como o address_text/district pode não estar no doc inicial, pega
    # a primeira mensagem inbound do phone que tinha endereço, e extrai
    # bairro via parse_address. Cache pra evitar dupla query.
    phone_to_district: Dict[str, Optional[str]] = {}

    async def _district_from_phone(ph: str) -> Optional[str]:
        if ph in phone_to_district:
            return phone_to_district[ph]
        msg = await db.aihub_wa_messages.find_one(
            {"company_id": cid, "phone": ph, "direction": "inbound"},
            {"_id": 0, "text": 1},
            sort=[("created_at", 1)],
        )
        if not msg or not msg.get("text"):
            phone_to_district[ph] = None
            return None
        parsed = parse_address(msg["text"])
        phone_to_district[ph] = parsed.get("district")
        return phone_to_district[ph]

    by_district: Dict[str, Dict[str, Any]] = {}
    for r in requests:
        ph = r.get("phone")
        district = r.get("address_district")
        if not district and ph:
            district = await _district_from_phone(ph)
        district = district or "Não identificado"
        key = district.strip().title()
        slot = by_district.setdefault(key, {
            "district": key, "count": 0, "phones": set(), "last_at": None,
        })
        slot["count"] += 1
        if ph:
            slot["phones"].add(ph)
        ts = r.get("created_at")
        if ts and (not slot["last_at"] or ts > slot["last_at"]):
            slot["last_at"] = ts

    heatmap = []
    for k, v in by_district.items():
        heatmap.append({
            "district": v["district"],
            "leads": v["count"],
            "unique_phones": len(v["phones"]),
            "last_at": v["last_at"],
        })
    heatmap.sort(key=lambda x: -x["leads"])

    total = sum(h["leads"] for h in heatmap)
    return {
        "window_days": days,
        "total_pending": total,
        "districts": heatmap[:10],
        "districts_count": len(heatmap),
    }


# ---------------------------------------------------------------------------
# Contact sync — agrega contatos das conversas + click-to-chat link
# ---------------------------------------------------------------------------
class ImportContactsIn(BaseModel):
    phones: List[str]  # apenas estes serão importados
    as_status: Optional[str] = "PROSPECT"
    branch: Optional[str] = None


@router.get("/contacts/from-conversations")
async def list_contacts_from_conversations(
    days: int = 60,
    only_new: bool = True,
    user: dict = Depends(require_role("gestor")),
):
    """Agrega contatos a partir do histórico de mensagens WhatsApp (Baileys).
    Cada `phone` único vira 1 contato com `push_name` (mais recente),
    `last_message_at`, `total_messages` e flag `already_subscriber` (true
    se já existe em `subscribers`/`subscriber_phones`)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    days = max(1, min(int(days or 60), 365))
    since_iso = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    pipeline = [
        {"$match": {"company_id": cid, "phone": {"$ne": None},
                       "created_at": {"$gte": since_iso}}},
        {"$sort": {"created_at": -1}},
        {"$group": {
            "_id": "$phone",
            "push_name": {"$first": "$push_name"},
            "last_message_at": {"$first": "$created_at"},
            "total_messages": {"$sum": 1},
            "directions": {"$addToSet": "$direction"},
        }},
        {"$sort": {"last_message_at": -1}},
        {"$limit": 5000},
    ]
    raw = await db.aihub_wa_messages.aggregate(pipeline).to_list(5000)

    phones = [r["_id"] for r in raw if r.get("_id")]
    # Já cadastrados — busca via subscriber_phones (normalized)
    existing = set()
    if phones:
        from phone_normalizer import get_phone_lookup_variants
        all_variants = []
        for p in phones:
            try:
                all_variants.extend(get_phone_lookup_variants(p) or [p])
            except Exception:
                all_variants.append(p)
        async for sp in db.subscriber_phones.find(
            {"company_id": cid,
              "normalized_number": {"$in": list(set(all_variants))}},
            {"_id": 0, "normalized_number": 1, "subscriber_id": 1},
        ):
            existing.add(sp.get("normalized_number"))

    contacts = []
    for r in raw:
        ph = r["_id"]
        already = any(v in existing
                          for v in (get_phone_lookup_variants(ph)
                                       if 'get_phone_lookup_variants' in dir()
                                       else [ph]))
        # Recalcula com variants
        try:
            from phone_normalizer import get_phone_lookup_variants as _gpv
            already = any(v in existing for v in (_gpv(ph) or [ph]))
        except Exception:
            already = ph in existing
        if only_new and already:
            continue
        contacts.append({
            "phone": ph,
            "push_name": r.get("push_name") or "(sem nome)",
            "last_message_at": r.get("last_message_at"),
            "total_messages": r.get("total_messages", 0),
            "already_subscriber": already,
            "had_inbound": "inbound" in (r.get("directions") or []),
        })

    return {
        "window_days": days,
        "total": len(contacts),
        "contacts": contacts[:500],
    }


@router.post("/contacts/import-as-leads")
async def import_contacts_as_leads(
    payload: ImportContactsIn,
    user: dict = Depends(require_role("gestor")),
):
    """Importa lote de contatos como subscribers em status PROSPECT.
    Cria também o vínculo em `subscriber_phones`."""
    from phone_normalizer import normalize_brazilian_phone
    cid = user.get("company_id") or DEMO_COMPANY_ID
    now = datetime.now(timezone.utc).isoformat()
    created = 0
    skipped = 0
    for raw_phone in (payload.phones or [])[:500]:
        norm = normalize_brazilian_phone(raw_phone)
        if not norm:
            skipped += 1
            continue
        # Verifica se já existe
        existing = await db.subscriber_phones.find_one(
            {"company_id": cid, "normalized_number": norm},
            {"_id": 0, "subscriber_id": 1},
        )
        if existing:
            skipped += 1
            continue
        # Busca push_name da última msg
        last_msg = await db.aihub_wa_messages.find_one(
            {"company_id": cid, "phone": raw_phone},
            {"_id": 0, "push_name": 1},
            sort=[("created_at", -1)],
        )
        push_name = (last_msg or {}).get("push_name") or f"WhatsApp {norm[-4:]}"
        sub_id = f"sub-{uuid.uuid4().hex[:10]}"
        await db.subscribers.insert_one({
            "id": sub_id, "company_id": cid, "name": push_name,
            "status": payload.as_status or "PROSPECT",
            "branch": payload.branch,
            "origin": "whatsapp_contact_sync",
            "created_at": now,
        })
        try:
            from services.event_bus import emit_event
            await emit_event(
                "subscriber.created",
                company_id=cid,
                source="whatsapp_baileys",
                payload={},
            )
        except Exception:
            pass
        await db.subscriber_phones.insert_one({
            "id": f"sphone-{uuid.uuid4().hex[:10]}",
            "company_id": cid, "subscriber_id": sub_id,
            "raw_number": raw_phone, "normalized_number": norm,
            "is_primary": True, "is_whatsapp": True,
            "created_at": now,
        })
        created += 1
    logger.info("[wa-contacts] imported %d skipped %d (by %s)",
                  created, skipped, user.get("email"))
    return {"ok": True, "created": created, "skipped": skipped}


@router.get("/click-to-chat")
async def click_to_chat_link(
    text: Optional[str] = None,
    user: dict = Depends(require_role("gestor")),
):
    """Retorna link público `wa.me/55XXXXXXXXX?text=...` da empresa pra
    incorporar em site/QR-code/email/anúncios.
    Usa o phone configurado em `aihub_settings.wa_business_phone` ou,
    em fallback, o telefone do próprio sidecar (status.me.user).
    """
    from phone_normalizer import normalize_brazilian_phone
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # 1. tenta config explícita
    cfg = await db.aihub_settings.find_one(
        {"company_id": cid, "key": "wa_business_phone"},
        {"_id": 0, "value": 1},
    )
    phone = (cfg or {}).get("value")
    # 2. fallback: pega do status do sidecar
    if not phone:
        try:
            async with httpx.AsyncClient(timeout=4.0) as cli:
                r = await cli.get(
                    f"{SIDECAR_BASE}/status",
                    headers=({"x-token": SIDECAR_TOKEN}
                              if SIDECAR_TOKEN else {}),
                )
                if r.status_code == 200:
                    js = r.json()
                    me = (js.get("me") or {}).get("id") or ""
                    # baileys: "5521999999999:1@s.whatsapp.net"
                    only = me.split(":")[0].split("@")[0]
                    if only and only.isdigit():
                        phone = only
        except Exception:
            pass

    norm = normalize_brazilian_phone(phone) if phone else None
    if not norm:
        raise HTTPException(
            404,
            "Telefone do WhatsApp Business não configurado. "
            "Configure em aihub_settings.wa_business_phone ou conecte o "
            "sidecar.",
        )
    if not norm.startswith("55"):
        norm = "55" + norm.lstrip("+").lstrip("55")
    from urllib.parse import quote as _q
    suffix = f"?text={_q(text)}" if text else ""
    link = f"https://wa.me/{norm}{suffix}"
    return {
        "phone": norm,
        "link": link,
        "preview_text": text,
    }


class WaPhoneIn(BaseModel):
    phone: str


@router.put("/click-to-chat/phone")
async def set_click_to_chat_phone(
    payload: WaPhoneIn,
    user: dict = Depends(require_role("gestor")),
):
    """Define o telefone usado no link click-to-chat."""
    from phone_normalizer import normalize_brazilian_phone
    cid = user.get("company_id") or DEMO_COMPANY_ID
    norm = normalize_brazilian_phone(payload.phone)
    if not norm:
        raise HTTPException(400, "Telefone inválido")
    if not norm.startswith("55"):
        norm = "55" + norm
    await db.aihub_settings.update_one(
        {"company_id": cid, "key": "wa_business_phone"},
        {"$set": {"value": norm,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "updated_by": user.get("email") or user.get("id")}},
        upsert=True,
    )
    return {"ok": True, "phone": norm,
            "link": f"https://wa.me/{norm}"}


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
        async with httpx.AsyncClient(headers=_sidecar_headers(), timeout=4.0) as cli:
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
    - "tecnico": conversa onde o técnico (via app PWA) trocou mensagens
    - "automatico": atualmente sendo respondida pela IA
    - "manual": atribuída a um humano
    - "aguardando": sem resposta humana há mais de 5min (e sem auto-reply)
    - "fora_de_hora": chegou fora do horário comercial configurado
    """
    if conv.get("is_group"):
        return "grupo"
    # iter183 — Conv. Técnico: qualquer conversa com mensagens enviadas pelo
    # técnico via PWA (source=tech_pwa) entra neste bucket prioritário.
    if conv.get("has_tech_conversation"):
        return "tecnico"
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
            async with httpx.AsyncClient(headers=_sidecar_headers(), timeout=5.0) as cli:
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
            # Lead tag — phone desconhecido aguardando identificação
            "lead_tag": conv.get("lead_tag"),
            "is_unknown_lead": conv.get("is_unknown_lead", False),
            # iter183 — Conv. Técnico (mensagens enviadas pelo técnico via PWA)
            "has_tech_conversation": conv.get("has_tech_conversation", False),
            "last_tech_msg_at": conv.get("last_tech_msg_at"),
            "last_tech_collab_name": conv.get("last_tech_collab_name"),
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
            async with httpx.AsyncClient(headers=_sidecar_headers(), timeout=15.0) as cli:
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
                try:
                    from services.event_bus import emit_event
                    await emit_event(
                        "wa.message.persisted",
                        company_id=(prev or {}).get("company_id"),
                        source="whatsapp_baileys",
                        payload={},
                    )
                except Exception:
                    pass
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


@router.get("/atendimento/duty-status")
async def atendimento_duty_status(user: dict = Depends(get_current_user)):
    """iter215an — Retorna se o usuário atual está com ponto válido pra
    operar o chat (regra global). Frontend consulta a cada 30s e aplica
    overlay grayscale + bloqueio quando off_duty=True."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    from services.atendente_duty import (
        is_user_on_duty, list_online_attendants, my_workload_snapshot,
    )
    on_duty, reason, last = await is_user_on_duty(cid, user)
    online = await list_online_attendants(cid, exclude_user_id=user.get("id"))
    workload = await my_workload_snapshot(cid, user)
    return {
        "on_duty": on_duty,
        "reason": reason,
        "last_event": last,
        "other_attendants_online": [
            {"id": a["id"], "name": a.get("name"), "role": a.get("role")}
            for a in online
        ],
        "role": user.get("role"),
        **workload,
    }



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
        async with httpx.AsyncClient(headers=_sidecar_headers(), timeout=10.0) as cli:
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
        async with httpx.AsyncClient(headers=_sidecar_headers(), timeout=8.0) as cli:
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
        async with httpx.AsyncClient(headers=_sidecar_headers(), timeout=8.0) as cli:
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


# ============================================================================
# Watchdog: auto-reload preventivo do sidecar quando socket zumbi
# ============================================================================
# Estado em memória do watchdog (não persistido — reset no restart do backend)
_wa_watchdog_state: Dict[str, Any] = {
    "last_check_at": None,
    "last_reload_at": None,
    "consecutive_zombie_checks": 0,
    "last_inbound_event_at_seen": None,
}


async def baileys_watchdog_job() -> None:
    """Roda a cada 2min via APScheduler.

    Detecta sidecar Baileys "zumbi": state=connected mas SEM eventos inbound
    por > 15min E o número está conectado há > 5min (não é boot).
    Quando detecta, dispara POST /reload no sidecar (mantém sessão — não
    precisa re-scan QR). Resolve sozinho ~80% dos casos de "WhatsApp parou
    de receber mensagens" sem ação humana.

    Auditoria: grava em `whatsapp_system_events` (kind=watchdog_reload).
    """
    now_ts = datetime.now(timezone.utc)
    _wa_watchdog_state["last_check_at"] = now_ts.isoformat()
    try:
        async with httpx.AsyncClient(headers=_sidecar_headers(),
                                         timeout=8.0) as cli:
            r = await cli.get(f"{SIDECAR_BASE}/health")
            if r.status_code >= 400:
                logger.info("[wa-watchdog] health %s — skip", r.status_code)
                _wa_watchdog_state["consecutive_zombie_checks"] = 0
                return
            health = r.json()
    except Exception as e:
        logger.info("[wa-watchdog] sidecar offline: %s", e)
        _wa_watchdog_state["consecutive_zombie_checks"] = 0
        return

    state = health.get("state")
    uptime_s = health.get("uptime_s") or 0
    last_inbound = health.get("last_inbound_event_at")

    # Só monitoramos quando state=connected
    if state != "connected":
        _wa_watchdog_state["consecutive_zombie_checks"] = 0
        return

    # Não age durante os primeiros 5min após boot
    if uptime_s < 300:
        return

    # Calcula segundos desde o último inbound
    secs_since_inbound = None
    if last_inbound:
        try:
            t = datetime.fromisoformat(last_inbound.replace("Z", "+00:00"))
            secs_since_inbound = (now_ts - t).total_seconds()
        except Exception:
            pass
    else:
        # nunca recebeu inbound desde boot
        secs_since_inbound = uptime_s

    ZOMBIE_THRESHOLD_S = 15 * 60  # 15 minutos
    is_zombie = (
        secs_since_inbound is not None and secs_since_inbound > ZOMBIE_THRESHOLD_S
    )

    # Evita reload em loop — só uma vez a cada 20min
    last_reload_iso = _wa_watchdog_state.get("last_reload_at")
    too_soon_to_reload = False
    if last_reload_iso:
        try:
            t = datetime.fromisoformat(last_reload_iso)
            too_soon_to_reload = (now_ts - t).total_seconds() < 1200
        except Exception:
            pass

    if not is_zombie:
        _wa_watchdog_state["consecutive_zombie_checks"] = 0
        return

    _wa_watchdog_state["consecutive_zombie_checks"] = (
        _wa_watchdog_state.get("consecutive_zombie_checks") or 0
    ) + 1

    # Só dispara reload após 2 checks consecutivos zumbi (~4min de confirmação)
    if _wa_watchdog_state["consecutive_zombie_checks"] < 2:
        logger.info(
            "[wa-watchdog] socket zumbi detectado (%.0fs sem inbound). "
            "aguardando confirmação no próximo check.",
            secs_since_inbound,
        )
        return

    if too_soon_to_reload:
        logger.warning(
            "[wa-watchdog] zumbi confirmado mas reload feito recentemente — pulando."
        )
        return

    # Dispara reload silencioso (mantém sessão)
    logger.warning(
        "[wa-watchdog] SOCKET ZUMBI (%.0fs sem inbound) — disparando /reload",
        secs_since_inbound,
    )
    try:
        async with httpx.AsyncClient(headers=_sidecar_headers(),
                                         timeout=15.0) as cli:
            await cli.post(f"{SIDECAR_BASE}/reload", json={})
        _wa_watchdog_state["last_reload_at"] = now_ts.isoformat()
        _wa_watchdog_state["consecutive_zombie_checks"] = 0
        await db.whatsapp_system_events.insert_one({
            "id": f"wae-{uuid.uuid4().hex[:10]}",
            "company_id": DEMO_COMPANY_ID,
            "event": "watchdog_reload",
            "code": 0,
            "name": "watchdog_reload",
            "retry_count": None,
            "reason": f"socket zumbi: {int(secs_since_inbound)}s sem inbound",
            "created_at": now_ts.isoformat(),
            "acknowledged": False,
        })
        # Notifica admins: watchdog detectou e auto-corrigiu
        await _notify_admins_baileys_down(
            DEMO_COMPANY_ID,
            f"Sidecar travou ({int(secs_since_inbound // 60)}min sem mensagens). "
            f"Reconectado automaticamente — verifique se voltou a responder.",
        )
    except Exception as e:
        logger.error("[wa-watchdog] reload falhou: %s", e)
        # Falhou até o reload — alerta urgente
        await _notify_admins_baileys_down(
            DEMO_COMPANY_ID,
            f"Sidecar travou há {int(secs_since_inbound // 60)}min e tentativa "
            f"de reconexão automática FALHOU. Re-pareie o QR Code manualmente.",
        )


@router.get("/watchdog/status")
async def get_watchdog_status(user: dict = Depends(require_role("gestor"))):
    """Estado atual do watchdog Baileys (debug/observabilidade)."""
    return {
        "last_check_at": _wa_watchdog_state.get("last_check_at"),
        "last_reload_at": _wa_watchdog_state.get("last_reload_at"),
        "consecutive_zombie_checks": _wa_watchdog_state.get(
            "consecutive_zombie_checks", 0),
    }


@router.get("/health-summary")
async def get_health_summary(user: dict = Depends(require_role("gestor"))):
    """Resumo unificado de saúde do WhatsApp (sidecar + watchdog + last events).

    Usado pelo HealthCard no painel Atendimento IA. Retorna:
      - sidecar: { state, uptime_s, last_inbound_event_at, me, online_age_s }
      - watchdog: estado do watchdog do backend
      - recent_events: últimos 5 system_events (loggedOut, watchdog_reload, etc)
      - status: 'green' | 'yellow' | 'red'
      - message: descrição textual amigável
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    now_ts = datetime.now(timezone.utc)

    # 1. Sidecar health (com timeout curto)
    sidecar: dict = {}
    sidecar_ok = False
    try:
        async with httpx.AsyncClient(headers=_sidecar_headers(),
                                       timeout=4.0) as cli:
            r = await cli.get(f"{SIDECAR_BASE}/health")
            if r.status_code < 400:
                sidecar = r.json() or {}
                sidecar_ok = True
    except Exception as e:
        sidecar = {"error": str(e)[:120]}

    state = (sidecar.get("state") or "unknown") if sidecar_ok else "offline"

    # 2. Calcula segundos desde último inbound
    secs_since_inbound = None
    last_inbound = sidecar.get("last_inbound_event_at")
    if last_inbound:
        try:
            t = datetime.fromisoformat(last_inbound.replace("Z", "+00:00"))
            secs_since_inbound = int((now_ts - t).total_seconds())
        except Exception:
            pass

    # 3. Últimos system_events da empresa
    recent_events = await db.whatsapp_system_events.find(
        {"company_id": cid},
        {"_id": 0, "id": 1, "event": 1, "name": 1, "reason": 1,
         "created_at": 1, "code": 1},
    ).sort("created_at", -1).limit(5).to_list(5)

    # 4. Status agregado
    if not sidecar_ok or state == "offline":
        status = "red"
        message = "Sidecar offline — Isabella não recebe nem envia mensagens."
    elif state == "banned":
        status = "red"
        message = "Conta bloqueada pelo WhatsApp. Re-pareie com outro número."
    elif state == "circuit_open":
        status = "red"
        message = ("Conexão em circuit-breaker (muitos logouts em sequência). "
                   "Re-pareie o QR Code para sair desse estado.")
    elif state == "disconnected":
        status = "red"
        message = "WhatsApp desconectado. Re-pareie o QR Code."
    elif state == "connecting":
        status = "yellow"
        message = "Conectando ao WhatsApp..."
    elif state == "connected":
        if secs_since_inbound is not None and secs_since_inbound > 900:
            status = "yellow"
            message = (f"Conectado, mas sem mensagens há "
                       f"{secs_since_inbound // 60}min. Watchdog monitorando.")
        else:
            status = "green"
            message = "Tudo online ✓"
    else:
        status = "yellow"
        message = f"Estado desconhecido: {state}"

    return {
        "status": status,
        "message": message,
        "sidecar": {
            "state": state,
            "uptime_s": sidecar.get("uptime_s"),
            "me": sidecar.get("me"),
            "last_inbound_event_at": last_inbound,
            "secs_since_inbound": secs_since_inbound,
            "online": sidecar_ok,
        },
        "watchdog": {
            "last_check_at": _wa_watchdog_state.get("last_check_at"),
            "last_reload_at": _wa_watchdog_state.get("last_reload_at"),
            "consecutive_zombie_checks": _wa_watchdog_state.get(
                "consecutive_zombie_checks", 0),
        },
        "recent_events": recent_events,
        "checked_at": now_ts.isoformat(),
    }


async def baileys_nightly_restart_job() -> None:
    """Restart preventivo diário do sidecar Baileys (04:00 horário Sampa).

    Mesmo sem detectar problema, força um /reload uma vez por dia pra:
      - Evitar memory leak (Node.js fica meses no ar)
      - Reaplicar configurações em caso de mudança de versão
      - Limpar caches antigos do socket

    /reload é silencioso (mantém auth_info, não pede QR). Apenas log e
    persistência em whatsapp_system_events.
    """
    now_ts = datetime.now(timezone.utc)
    try:
        async with httpx.AsyncClient(headers=_sidecar_headers(),
                                       timeout=15.0) as cli:
            r = await cli.post(f"{SIDECAR_BASE}/reload", json={})
        ok = r.status_code < 400
        logger.info("[wa-nightly-restart] %s (HTTP %s)",
                    "✓" if ok else "✗", r.status_code)
        await db.whatsapp_system_events.insert_one({
            "id": f"wae-{uuid.uuid4().hex[:10]}",
            "company_id": DEMO_COMPANY_ID,
            "event": "nightly_restart",
            "code": 0 if ok else r.status_code,
            "name": "nightly_restart",
            "retry_count": None,
            "reason": "restart preventivo programado (04:00)",
            "created_at": now_ts.isoformat(),
            "acknowledged": True,
        })
    except Exception as e:
        logger.warning("[wa-nightly-restart] falhou: %s", e)


async def _notify_admins_baileys_down(company_id: str, reason: str) -> None:
    """Cria notificação in-app pros administradores quando o Baileys cai.

    Inserido em `notifications` (collection existente que o frontend já
    consome). Idempotente por janela: só cria 1 alerta a cada 30min pro
    mesmo motivo.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    recent = await db.notifications.find_one({
        "company_id": company_id,
        "kind": "wa_down",
        "created_at": {"$gte": cutoff},
    })
    if recent:
        return
    try:
        await db.notifications.insert_one({
            "id": f"ntf-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "kind": "wa_down",
            "audience_role": "administrador",
            "title": "🔴 WhatsApp Isabella desconectado",
            "body": reason,
            "url": "/?view=atendimento",
            "read": False,
            "created_at": now_iso(),
        })
        logger.warning(
            "[wa-baileys] notify admins: WhatsApp desconectado company=%s "
            "reason=%s", company_id, reason,
        )
    except Exception as e:
        logger.warning("[wa-baileys] notify admins falhou: %s", e)


@router.get("/conversation/{phone}/inspect")
async def inspect_conversation_context(
    phone: str,
    user: dict = Depends(require_role("administrador")),
):
    """🔍 DEBUG: Mostra exatamente o que a Isabella "vê" da conversa.

    Apenas administradores podem usar. Retorna:
      - subscriber_ctx: bloco "VERIFICAÇÃO DA CONEXÃO" que vai pro prompt
      - history_block: bloco "HISTÓRICO DO CLIENTE" (90 dias)
      - history_turns: últimas N mensagens em formato ChatML (user/assistant)
      - subscriber_link: subscriber_id resolvido + nome + plano (se houver)
      - active_fragments: lista de fragmentos de prompt habilitados

    Útil pra debugar alucinações: se a Isabella inventa nome/plano, o
    `subscriber_ctx` aqui revela se o problema é:
      a) Vínculo errado em `subscriber_phones` (subscriber_ctx tem dados de
         outro cliente)
      b) Prompt fragment com exemplo literal (history_turns está vazio mas
         a Isabella ainda chuta dados — checar active_fragments)
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID

    # 1. Resolver subscriber_link
    subscriber_link = {"matched": False, "subscriber_id": None}
    subscriber_ctx_text = None
    try:
        from phone_normalizer import link_phone_to_subscriber
        link = await link_phone_to_subscriber(phone, cid)
        if link and link.get("subscriber_id"):
            sid = link["subscriber_id"]
            sub = await db.subscribers.find_one(
                {"id": sid, "company_id": cid},
                {"_id": 0, "name": 1, "external_code": 1, "plan_name": 1,
                 "status": 1, "branch": 1, "address": 1},
            )
            subscriber_link = {
                "matched": True,
                "subscriber_id": sid,
                "subscriber_name": (sub or {}).get("name"),
                "subscriber_plan": (sub or {}).get("plan_name"),
                "subscriber_status": (sub or {}).get("status"),
                "matched_by": link.get("matched_by") or "phone_lookup",
            }
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
                subscriber_ctx_text = " · ".join(parts)
    except Exception as e:
        subscriber_link["error"] = str(e)

    # 2. Bloco de histórico (90 dias)
    history_block = None
    history_classification = None
    try:
        from services.customer_history import (
            analyze_customer_history, format_history_for_prompt,
        )
        analysis = await analyze_customer_history(
            company_id=cid,
            subscriber_id=subscriber_link.get("subscriber_id"),
            current_phone=phone,
        )
        history_block = format_history_for_prompt(analysis)
        history_classification = analysis.get("classification")
    except Exception as e:
        history_block = f"(erro: {e})"

    # 3. Últimas N turns (formato ChatML que vai pro LLM)
    history_turns: List[dict] = []
    try:
        from services.ai_history import fetch_history_turns
        history_turns = await fetch_history_turns(cid, phone, limit=50,
                                                       token_budget=5000)
    except Exception as e:
        logger.warning("[inspect] history_turns falhou: %s", e)

    # 4. Fragmentos de prompt ativos da Isabella
    active_fragments: List[dict] = []
    try:
        async for f in db.isabella_prompt_fragments.find(
            {"company_id": cid, "enabled": True},
            {"_id": 0, "id": 1, "title": 1, "category": 1,
             "updated_at": 1, "updated_by": 1},
        ).sort("category", 1):
            active_fragments.append(f)
    except Exception as e:
        logger.warning("[inspect] active_fragments falhou: %s", e)

    # 5. Estado da conversa (reset_at, subscriber_id linkado na conversa)
    conv_state = await db.wa_conversations.find_one(
        {"company_id": cid, "phone": phone},
        {"_id": 0, "subscriber_id": 1, "context_reset_at": 1,
         "customer_name": 1, "updated_at": 1},
    )

    return {
        "phone": phone,
        "subscriber_link": subscriber_link,
        "subscriber_ctx_text": subscriber_ctx_text,
        "history_classification": history_classification,
        "history_block": history_block,
        "history_turns_count": len(history_turns),
        "history_turns_preview": [
            {"role": t.get("role"), "content": (t.get("content") or "")[:200]}
            for t in history_turns[-10:]
        ],
        "active_fragments_count": len(active_fragments),
        "active_fragments": active_fragments,
        "conversation_state": conv_state,
    }



@router.get("/conversation/{phone}/link-status")
async def conversation_link_status(
    phone: str,
    user: dict = Depends(require_role("gestor")),
):
    """⚡ Endpoint leve: retorna se o telefone tem MAIS DE UM subscriber vinculado.

    Usado pelo frontend pra mostrar banner ⚠️ "Atenção: este número está
    vinculado a N clientes" no header da conversa. Acessível a gestor (não
    exige admin) — é só leitura informativa.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    from routes.subscribers import get_phone_lookup_variants
    variants = list(get_phone_lookup_variants(phone))

    rows = await db.subscriber_phones.find(
        {"company_id": cid, "$or": [
            {"phone": {"$in": variants}},
            {"normalized_number": {"$in": variants}},
        ]},
        {"_id": 0, "subscriber_id": 1, "label": 1, "is_primary": 1},
    ).to_list(20)

    sids = list({r["subscriber_id"] for r in rows if r.get("subscriber_id")})
    if not sids:
        return {"phone": phone, "linked_count": 0, "has_conflict": False,
                "subscribers": []}

    subs = await db.subscribers.find(
        {"company_id": cid, "id": {"$in": sids}},
        {"_id": 0, "id": 1, "name": 1, "plan_name": 1, "status": 1},
    ).to_list(20)

    return {
        "phone": phone,
        "linked_count": len(sids),
        "has_conflict": len(sids) >= 2,
        "subscribers": subs,
    }



@router.delete("/conversation/{phone}/unlink-subscriber")
async def unlink_phone_from_subscriber(
    phone: str,
    subscriber_id: Optional[str] = None,
    user: dict = Depends(require_role("administrador")),
):
    """🛠️ ADMIN: Remove vínculo entre telefone e subscriber.

    Útil quando:
      - Cliente reportou comportamento estranho da Isabella (chamou de outro
        nome, mencionou plano errado)
      - `/conversation/{phone}/inspect` mostra subscriber errado/duplicado

    Params:
      - subscriber_id (query, opcional): se fornecido, remove APENAS o vínculo
        com esse subscriber. Se omitido, remove TODOS os vínculos do phone.

    O telefone permanece nas conversas (wa_conversations), mas a Isabella
    passa a tratar como número desconhecido na próxima mensagem.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID

    # Aceita formato 21998176526, 5521998176526, +5521998176526 etc
    from routes.subscribers import normalize_brazilian_phone, get_phone_lookup_variants
    variants = get_phone_lookup_variants(phone)
    normalized = normalize_brazilian_phone(phone)

    # Filtro: phone exato OU normalized_number ∈ variants
    base_filter: Dict[str, Any] = {
        "company_id": cid,
        "$or": [
            {"phone": {"$in": list(variants)}},
            {"normalized_number": {"$in": list(variants)}},
        ],
    }
    if subscriber_id:
        base_filter["subscriber_id"] = subscriber_id

    # Lista antes de apagar (pra retornar ao admin)
    before = await db.subscriber_phones.find(
        base_filter, {"_id": 0}
    ).to_list(20)

    if not before:
        return {
            "ok": True,
            "removed_count": 0,
            "message": "Nenhum vínculo encontrado pra remover.",
            "phone_normalized": normalized,
            "variants_tested": list(variants),
        }

    result = await db.subscriber_phones.delete_many(base_filter)

    # Auditoria
    await db.wa_system_events.insert_one({
        "company_id": cid,
        "type": "phone_unlinked_admin",
        "phone": phone,
        "normalized": normalized,
        "subscriber_id": subscriber_id,
        "removed_count": result.deleted_count,
        "removed_records": before,
        "actor": user.get("email"),
        "created_at": now_iso(),
    })

    return {
        "ok": True,
        "removed_count": result.deleted_count,
        "removed_records": before,
        "phone_normalized": normalized,
        "actor": user.get("email"),
    }


@router.get("/phone-conflicts")
async def list_phone_conflicts(
    user: dict = Depends(require_role("administrador")),
):
    """🛠️ ADMIN: Lista telefones com múltiplos subscribers vinculados.

    Esse cenário (1 phone → N subscribers) confunde a Isabella porque o
    `find_subscriber_by_phone` retorna o primeiro match arbitrário, podendo
    ser um cadastro desativado ou homônimo.

    Retorna lista pra UI de admin resolver via /unlink-subscriber.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID

    pipeline = [
        {"$match": {"company_id": cid}},
        {"$group": {
            "_id": {
                "$ifNull": ["$normalized_number", "$phone"],
            },
            "count": {"$sum": 1},
            "subscriber_ids": {"$addToSet": "$subscriber_id"},
            "records": {"$push": {
                "subscriber_id": "$subscriber_id",
                "phone": "$phone",
                "normalized": "$normalized_number",
                "label": "$label",
                "is_primary": "$is_primary",
            }},
        }},
        {"$match": {"count": {"$gte": 2}}},
        {"$sort": {"count": -1}},
        {"$limit": 100},
    ]

    conflicts = []
    async for row in db.subscriber_phones.aggregate(pipeline):
        sids = row.get("subscriber_ids") or []
        # Enriquece com nomes dos subscribers
        subs = await db.subscribers.find(
            {"company_id": cid, "id": {"$in": sids}},
            {"_id": 0, "id": 1, "name": 1, "plan_name": 1, "status": 1},
        ).to_list(20)
        subs_map = {s["id"]: s for s in subs}
        records = row.get("records") or []
        for r in records:
            sid = r.get("subscriber_id")
            r["subscriber_name"] = (subs_map.get(sid) or {}).get("name")
            r["subscriber_plan"] = (subs_map.get(sid) or {}).get("plan_name")
            r["subscriber_status"] = (subs_map.get(sid) or {}).get("status")
        conflicts.append({
            "phone_key": row["_id"],
            "subscribers_count": row["count"],
            "records": records,
        })

    return {"total_conflicts": len(conflicts), "conflicts": conflicts}



# ---------------------------------------------------------------------------
# iter183 — Endpoints PÚBLICOS para chat do técnico no app PWA
# Acesso via collaborator_id (sem JWT). Permitem ao técnico abrir o chat
# do cliente diretamente no card da OS na Lousa Mobile.
# ---------------------------------------------------------------------------

async def _company_for_collaborator_wa(collab_id: str) -> str:
    coll = await db.collaborators.find_one(
        {"id": collab_id}, {"_id": 0, "company_id": 1, "id": 1},
    )
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    return coll.get("company_id") or DEMO_COMPANY_ID


def _normalize_phone(phone: str) -> str:
    """Normaliza telefone para formato e164 só dígitos."""
    digits = re.sub(r"\D", "", phone or "")
    # Garante DDI 55 (Brasil) se não veio
    if digits and not digits.startswith("55") and len(digits) in (10, 11):
        digits = "55" + digits
    return digits


@router.get("/public/conversations/{collab_id}/{phone}/messages")
async def public_tech_get_messages(collab_id: str, phone: str,
                                       limit: int = 100):
    """Lista últimas mensagens (asc). Disponível para o técnico no PWA."""
    cid = await _company_for_collaborator_wa(collab_id)
    phone_norm = _normalize_phone(phone)
    capped = max(1, min(limit, 500))
    # Aceita ambas variações (com/sem 55) para compat com históricos antigos
    docs = await db.aihub_wa_messages.find(
        {"company_id": cid,
         "phone": {"$in": [phone_norm, phone, phone_norm.lstrip("55")]}},
        {"_id": 0},
    ).sort("created_at", -1).limit(capped).to_list(capped)
    docs.reverse()
    return {"items": docs, "phone": phone_norm, "count": len(docs)}


class PublicTechSendIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4096)


@router.post("/public/conversations/{collab_id}/{phone}/send")
async def public_tech_send(collab_id: str, phone: str,
                              payload: PublicTechSendIn):
    """Envia mensagem em nome do técnico. Mesmo fluxo do /send admin, mas
    sem exigir JWT — autenticado via collab_id válido.

    iter183 — Prefixa com "Técnico Ligo {primeiro_nome}: " para identificar
    quem está falando no WhatsApp do cliente.
    """
    cid = await _company_for_collaborator_wa(collab_id)
    phone_norm = _normalize_phone(phone)
    if not phone_norm:
        raise HTTPException(400, "Telefone inválido")
    coll = await db.collaborators.find_one(
        {"id": collab_id}, {"_id": 0, "name": 1, "email": 1},
    ) or {}
    first_name = ((coll.get("name") or "").strip().split() or [""])[0]
    if first_name:
        text_to_send = f"Técnico Ligo {first_name}: {payload.text}"
    else:
        text_to_send = payload.text
    send_ok = False
    send_error: Optional[str] = None
    out: Dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(headers=_sidecar_headers(), timeout=20.0) as cli:
            r = await cli.post(f"{SIDECAR_BASE}/send",
                                json={"phone": phone_norm, "text": text_to_send})
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
        logger.warning("[wa-baileys/tech] sidecar /send falhou: %s", e)
        send_error = str(e)

    await db.aihub_wa_messages.insert_one({
        "id": f"wam-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "direction": "outbound",
        "phone": phone_norm,
        "text": text_to_send,
        "channel": "baileys",
        "message_id": out.get("message_id"),
        "created_at": now_iso(),
        "actor_user": coll.get("email") or collab_id,
        "sent_by_collaborator_id": collab_id,
        "sent_by_collaborator_name": coll.get("name"),
        "source": "tech_pwa",
        "agent_tag": "tecnico_ligo",
        "auto_reply": False,
        "delivery_status": "sent" if send_ok else "failed",
        "delivery_error": send_error,
    })
    try:
        from services.event_bus import emit_event
        await emit_event(
            "wa.message.persisted",
            company_id=(coll or {}).get("company_id"),
            source="whatsapp_baileys",
            payload={},
        )
    except Exception:
        pass
    # iter183 — Marca a conversa como "Conv. Técnico" no painel WhatsApp
    if send_ok:
        await db.wa_conversations.update_one(
            {"company_id": cid, "phone": phone_norm},
            {"$set": {
                "has_tech_conversation": True,
                "last_tech_msg_at": now_iso(),
                "last_tech_collab_id": collab_id,
                "last_tech_collab_name": coll.get("name"),
            },
             "$setOnInsert": {
                 "company_id": cid,
                 "phone": phone_norm,
                 "created_at": now_iso(),
            }},
            upsert=True,
        )
    if not send_ok:
        raise HTTPException(
            status_code=502,
            detail=f"WhatsApp não confirmou entrega: {send_error or 'erro desconhecido'}",
        )
    return {"ok": True, "phone": phone_norm}



@router.get("/public/conversations/{collab_id}/{phone}/presence")
async def public_tech_presence(collab_id: str, phone: str):
    """iter183.3 — Presença do cliente (composing/recording/available)
    pra mostrar "escrevendo…" no chat do técnico no PWA. Inscreve em
    presence updates do Baileys (idempotente) + lê do cache.
    """
    await _company_for_collaborator_wa(collab_id)
    phone_norm = _normalize_phone(phone)
    out = {"phone": phone_norm, "presence": "unknown", "last_seen": None}
    if not phone_norm:
        return out
    try:
        async with httpx.AsyncClient(headers=_sidecar_headers(), timeout=5.0) as cli:
            # Fire-and-forget subscribe (sidecar ignora se já subscrito)
            try:
                await cli.post(f"{SIDECAR_BASE}/presence-subscribe",
                                json={"phone": phone_norm})
            except Exception:
                pass
            r = await cli.get(f"{SIDECAR_BASE}/contact-profile",
                              params={"phone": phone_norm})
            if r.status_code == 200:
                d = r.json()
                out["presence"] = d.get("presence") or "unknown"
                out["last_seen"] = d.get("last_seen")
    except Exception as e:
        logger.debug("[wa-baileys/tech] presence fetch falhou: %s", e)
    return out
