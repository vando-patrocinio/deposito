"""WhatsApp config extras — Business Hours, Quick Images, PDF Export.

Endpoints adicionados:
  Business Hours:
    GET    /api/whatsapp-baileys/business-hours
    PUT    /api/whatsapp-baileys/business-hours
  Quick Images (até 5 imagens prontas pra envio rápido):
    GET    /api/whatsapp-baileys/quick-images
    POST   /api/whatsapp-baileys/quick-images
    DELETE /api/whatsapp-baileys/quick-images/{id}
    POST   /api/whatsapp-baileys/quick-images/{id}/send
  PDF Export (transcrição completa anexada ao cadastro do cliente):
    POST   /api/whatsapp-baileys/conversation/{phone}/export-pdf
    GET    /api/whatsapp-baileys/subscriber/{subscriber_id}/documents
"""
from __future__ import annotations

import base64
import io
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.wa_config")
router = APIRouter(prefix="/api/whatsapp-baileys", tags=["whatsapp-baileys-config"])

SIDECAR_BASE = "http://127.0.0.1:3002"

WA_QUICKIMG_DIR = Path("/app/backend/uploads/wa_quickimages")
WA_QUICKIMG_DIR.mkdir(parents=True, exist_ok=True)

WA_TRANSCRIPTS_DIR = Path("/app/backend/uploads/wa_transcripts")
WA_TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# BUSINESS HOURS — horário de atendimento configurável
# ============================================================================
DEFAULT_HOURS = {
    "enabled": True,
    "timezone_offset_hours": -3,  # BRT (UTC-3)
    "weekly_schedule": {
        # 0=Domingo ... 6=Sábado
        "0": {"enabled": False, "open": "08:00", "close": "18:00"},
        "1": {"enabled": True, "open": "08:00", "close": "18:00"},
        "2": {"enabled": True, "open": "08:00", "close": "18:00"},
        "3": {"enabled": True, "open": "08:00", "close": "18:00"},
        "4": {"enabled": True, "open": "08:00", "close": "18:00"},
        "5": {"enabled": True, "open": "08:00", "close": "18:00"},
        "6": {"enabled": True, "open": "08:00", "close": "13:00"},
    },
    "holidays": [],  # ["YYYY-MM-DD", ...]
    "fora_de_hora_message": "",
}


class DaySchedule(BaseModel):
    enabled: bool = True
    open: str = "08:00"
    close: str = "18:00"


class BusinessHoursPayload(BaseModel):
    enabled: bool = True
    timezone_offset_hours: int = -3
    weekly_schedule: Dict[str, DaySchedule]
    holidays: List[str] = []
    fora_de_hora_message: str = ""


async def get_business_hours(company_id: str) -> Dict[str, Any]:
    doc = await db.wa_business_hours.find_one(
        {"company_id": company_id}, {"_id": 0},
    )
    if not doc:
        return {"company_id": company_id, **DEFAULT_HOURS}
    return doc


async def is_outside_business_hours(company_id: str) -> bool:
    """Retorna True se o momento atual está fora do horário comercial configurado."""
    cfg = await get_business_hours(company_id)
    if not cfg.get("enabled"):
        return False
    tz_offset = cfg.get("timezone_offset_hours", -3)
    from datetime import timedelta as _td
    now_local = datetime.now(timezone.utc) + _td(hours=tz_offset)
    weekday = (now_local.weekday() + 1) % 7  # python: 0=Mon → adaptar p/ 0=Sun
    date_str = now_local.strftime("%Y-%m-%d")
    holidays = cfg.get("holidays") or []
    if date_str in holidays:
        return True
    day = (cfg.get("weekly_schedule") or {}).get(str(weekday))
    if not day or not day.get("enabled"):
        return True
    try:
        oh, om = (day.get("open") or "08:00").split(":")
        ch, cm = (day.get("close") or "18:00").split(":")
        open_min = int(oh) * 60 + int(om)
        close_min = int(ch) * 60 + int(cm)
        now_min = now_local.hour * 60 + now_local.minute
        return not (open_min <= now_min < close_min)
    except Exception:
        return False


@router.get("/business-hours")
async def get_hours(
    user: dict = Depends(require_role("gestor", "auditor", "administrador")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await get_business_hours(cid)


@router.put("/business-hours")
async def update_hours(
    payload: BusinessHoursPayload,
    user: dict = Depends(require_role("gestor", "administrador")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # valida weekday keys
    for k in payload.weekly_schedule.keys():
        if k not in ("0", "1", "2", "3", "4", "5", "6"):
            raise HTTPException(400, f"weekday inválido: {k} (use 0=Dom..6=Sab)")
    # valida holidays format
    for h in payload.holidays:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", h):
            raise HTTPException(400, f"holiday inválido: {h} (use YYYY-MM-DD)")
    doc = {
        "company_id": cid,
        "enabled": payload.enabled,
        "timezone_offset_hours": payload.timezone_offset_hours,
        "weekly_schedule": {k: v.dict() for k, v in payload.weekly_schedule.items()},
        "holidays": payload.holidays,
        "fora_de_hora_message": payload.fora_de_hora_message,
        "updated_at": now_iso(),
        "updated_by": user.get("email") or user.get("id"),
    }
    await db.wa_business_hours.update_one(
        {"company_id": cid}, {"$set": doc}, upsert=True,
    )
    return {"ok": True, "config": doc, "is_outside_now": await is_outside_business_hours(cid)}


# ============================================================================
# QUICK IMAGES — até 5 imagens prontas pra envio rápido
# ============================================================================
MAX_QUICK_IMAGES = 5
ALLOWED_IMG_EXT = {"png", "jpg", "jpeg", "webp", "gif"}


@router.get("/quick-images")
async def list_quick_images(
    user: dict = Depends(require_role("gestor", "auditor", "administrador")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    items = await db.wa_quick_images.find(
        {"company_id": cid}, {"_id": 0, "image_b64": 0},
    ).sort("sort_order", 1).to_list(50)
    # Adiciona URL pública (servida via /file)
    for it in items:
        it["url"] = f"/api/whatsapp-baileys/quick-images/{it['id']}/file"
    return {"items": items, "max": MAX_QUICK_IMAGES}


@router.post("/quick-images")
async def upload_quick_image(
    label: str = Form(""),
    file: UploadFile = File(...),
    user: dict = Depends(require_role("gestor", "administrador")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    count = await db.wa_quick_images.count_documents({"company_id": cid})
    if count >= MAX_QUICK_IMAGES:
        raise HTTPException(400, f"Limite de {MAX_QUICK_IMAGES} imagens atingido. Remova uma antes.")
    fname = (file.filename or "").lower()
    ext = fname.rsplit(".", 1)[-1] if "." in fname else "png"
    if ext not in ALLOWED_IMG_EXT:
        raise HTTPException(400, f"Extensão {ext} não permitida (use png/jpg/webp/gif)")
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(400, "Imagem maior que 5MB")
    img_id = f"wqi-{uuid.uuid4().hex[:10]}"
    out_path = WA_QUICKIMG_DIR / f"{img_id}.{ext}"
    out_path.write_bytes(data)
    doc = {
        "id": img_id, "company_id": cid,
        "label": label[:80], "file_ext": ext,
        "size_bytes": len(data),
        "sort_order": count,
        "created_at": now_iso(),
        "uploaded_by": user.get("email") or user.get("id"),
    }
    await db.wa_quick_images.insert_one(doc)
    doc.pop("_id", None)
    doc["url"] = f"/api/whatsapp-baileys/quick-images/{img_id}/file"
    return doc


@router.delete("/quick-images/{img_id}")
async def delete_quick_image(
    img_id: str,
    user: dict = Depends(require_role("gestor", "administrador")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.wa_quick_images.find_one({"company_id": cid, "id": img_id})
    if not doc:
        raise HTTPException(404, "Imagem não encontrada")
    try:
        p = WA_QUICKIMG_DIR / f"{img_id}.{doc.get('file_ext', 'png')}"
        if p.exists():
            p.unlink()
    except Exception:
        pass
    await db.wa_quick_images.delete_one({"company_id": cid, "id": img_id})
    return {"ok": True}


@router.get("/quick-images/{img_id}/file")
async def get_quick_image_file(
    img_id: str,
    t: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    # Auth via Bearer ou ?t= (necessário pra <img src>)
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
    doc = await db.wa_quick_images.find_one({"id": img_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Imagem não encontrada")
    ext = doc.get("file_ext", "png")
    path = WA_QUICKIMG_DIR / f"{img_id}.{ext}"
    if not path.exists():
        raise HTTPException(404, "Arquivo não encontrado em disco")
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/png")
    return FileResponse(path, media_type=mime)


class QuickSendPayload(BaseModel):
    phone: str = Field(..., min_length=8)
    caption: str = ""


@router.post("/quick-images/{img_id}/send")
async def send_quick_image(
    img_id: str,
    payload: QuickSendPayload,
    user: dict = Depends(require_role("gestor", "administrador")),
):
    """Envia uma das imagens rápidas configuradas para um telefone."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.wa_quick_images.find_one(
        {"company_id": cid, "id": img_id}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Imagem não encontrada")
    ext = doc.get("file_ext", "png")
    path = WA_QUICKIMG_DIR / f"{img_id}.{ext}"
    if not path.exists():
        raise HTTPException(404, "Arquivo não encontrado")
    image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")

    # Envia via sidecar
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{SIDECAR_BASE}/send-image",
                json={
                    "phone": payload.phone,
                    "image_b64": image_b64,
                    "caption": payload.caption,
                    "mimetype": f"image/{ext if ext != 'jpg' else 'jpeg'}",
                },
            )
        sidecar_ok = r.status_code == 200
        sidecar_resp = r.json() if sidecar_ok else None
    except Exception as e:
        raise HTTPException(502, f"Erro no sidecar: {e}")

    if not sidecar_ok:
        raise HTTPException(502, f"Sidecar retornou {r.status_code}: {r.text[:200]}")

    msg_id = (sidecar_resp or {}).get("message_id") or f"wam-{uuid.uuid4().hex[:10]}"
    await db.aihub_wa_messages.insert_one({
        "id": f"wam-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "direction": "outbound",
        "phone": payload.phone,
        "text": payload.caption or f"🖼️ Imagem rápida: {doc.get('label') or img_id}",
        "media_type": "image",
        "media_url": f"/api/whatsapp-baileys/quick-images/{img_id}/file",
        "channel": "baileys",
        "message_id": msg_id,
        "created_at": now_iso(),
        "actor_user": user.get("email") or user.get("id"),
        "sent_by_user_id": user.get("id"),
        "auto_reply": False,
        "delivery_status": "sent",
    })
    return {"ok": True, "message_id": msg_id}


# ============================================================================
# PDF EXPORT — transcrição completa anexada ao cadastro do cliente
# ============================================================================
def _build_transcript_pdf(
    conv_meta: Dict[str, Any],
    messages: List[Dict[str, Any]],
    subscriber: Optional[Dict[str, Any]],
) -> bytes:
    """Renderiza PDF da transcrição completa da conversa."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=1.6 * cm, rightMargin=1.6 * cm,
        topMargin=1.6 * cm, bottomMargin=1.6 * cm,
        title=f"Transcrição WhatsApp - {conv_meta.get('phone')}",
    )
    styles = getSampleStyleSheet()
    H = ParagraphStyle("Header", parent=styles["Heading1"],
                        textColor=colors.HexColor("#1e3a8a"), fontSize=18, spaceAfter=8)
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10, leading=14)
    meta = ParagraphStyle("Meta", parent=styles["BodyText"], fontSize=9,
                           textColor=colors.HexColor("#475569"))
    bubble_in = ParagraphStyle("BubbleIn", parent=body, fontSize=10,
                                 backColor=colors.HexColor("#f1f5f9"),
                                 borderColor=colors.HexColor("#cbd5e1"), borderWidth=0.5,
                                 borderPadding=6, leftIndent=0, rightIndent=80)
    bubble_out = ParagraphStyle("BubbleOut", parent=body, fontSize=10,
                                  backColor=colors.HexColor("#dcfce7"),
                                  borderColor=colors.HexColor("#86efac"), borderWidth=0.5,
                                  borderPadding=6, leftIndent=80, rightIndent=0,
                                  alignment=2)  # right
    bubble_ai = ParagraphStyle("BubbleAi", parent=body, fontSize=10,
                                 backColor=colors.HexColor("#fae8ff"),
                                 borderColor=colors.HexColor("#e9d5ff"), borderWidth=0.5,
                                 borderPadding=6, leftIndent=80, rightIndent=0,
                                 alignment=2)
    note = ParagraphStyle("Note", parent=body, fontSize=8,
                            textColor=colors.HexColor("#92400e"),
                            backColor=colors.HexColor("#fef3c7"),
                            borderColor=colors.HexColor("#fde68a"), borderWidth=0.5,
                            borderPadding=4)

    story = [Paragraph("Transcrição de Atendimento WhatsApp", H)]

    # Bloco de metadados
    rows = [
        ["Telefone:", f"+{conv_meta.get('phone')}"],
        ["Nome (push):", conv_meta.get("push_name") or "—"],
    ]
    if subscriber:
        rows.append(["Cliente cadastrado:", subscriber.get("name") or "—"])
        if subscriber.get("plan_name"):
            rows.append(["Plano:", subscriber["plan_name"]])
        if subscriber.get("address"):
            rows.append(["Endereço:", subscriber["address"]])
        if subscriber.get("external_code"):
            rows.append(["Código Atlaz:", subscriber["external_code"]])
    rows.append(["Mensagens:", str(len(messages))])
    rows.append(["Gerado em:", datetime.now(timezone.utc)
                                .strftime("%d/%m/%Y %H:%M UTC")])
    t = Table(rows, colWidths=[3.5 * cm, 13 * cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#475569")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.4 * cm))

    # Mensagens
    last_day = None
    for m in messages:
        ts = (m.get("created_at") or "")[:19].replace("T", " ")
        day = ts[:10]
        if day != last_day:
            story.append(Spacer(1, 0.2 * cm))
            story.append(Paragraph(f"<b>{day}</b>", meta))
            last_day = day
        text = (m.get("text") or "").strip()
        if m.get("media_type") == "audio":
            text = f"[🎤 Áudio {m.get('media_duration_sec') or '?'}s]"
        elif m.get("media_type") == "image":
            text = f"[🖼️ Imagem] {text}".strip()
        # Sanitiza HTML básico
        text = (text.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;"))
        text = text.replace("\n", "<br/>")
        direction = m.get("direction")
        if direction == "internal":
            label = f"📝 Nota interna · {ts[11:]}"
            story.append(Paragraph(f"<i>{label}</i><br/>{text}", note))
        elif direction == "outbound":
            actor = m.get("actor_user") or ""
            is_ai = m.get("auto_reply") or "isabella" in str(actor).lower() or "ia" in str(actor).lower()
            style = bubble_ai if is_ai else bubble_out
            label = f"{ts[11:]} · {'IA' if is_ai else actor or 'Atendente'}"
            story.append(Paragraph(f"<i>{label}</i><br/>{text}", style))
        else:  # inbound
            label = f"{ts[11:]} · Cliente"
            story.append(Paragraph(f"<i>{label}</i><br/>{text}", bubble_in))
        story.append(Spacer(1, 0.1 * cm))

    doc.build(story)
    return buffer.getvalue()


@router.post("/conversation/{phone}/export-pdf")
async def export_conversation_pdf(
    phone: str,
    user: dict = Depends(require_role("gestor", "auditor", "administrador")),
):
    """Gera PDF da conversa e vincula ao cadastro do cliente (se houver)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID

    conv = await db.wa_conversations.find_one(
        {"company_id": cid, "phone": phone}, {"_id": 0},
    ) or {"phone": phone}

    msgs = await db.aihub_wa_messages.find(
        {"company_id": cid, "phone": phone},
        {"_id": 0},
    ).sort("created_at", 1).limit(5000).to_list(5000)

    if not msgs:
        raise HTTPException(404, "Conversa sem mensagens")

    subscriber = None
    sub_id = conv.get("subscriber_id")
    if sub_id:
        subscriber = await db.subscribers.find_one(
            {"id": sub_id, "company_id": cid}, {"_id": 0},
        )

    pdf_bytes = _build_transcript_pdf(conv, msgs, subscriber)

    doc_id = f"watp-{uuid.uuid4().hex[:10]}"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    fname = f"transcricao_{phone}_{ts}.pdf"
    out_path = WA_TRANSCRIPTS_DIR / f"{doc_id}.pdf"
    out_path.write_bytes(pdf_bytes)

    public_url = f"/api/whatsapp-baileys/transcripts/{doc_id}.pdf"

    # Insere documento (vinculado ao subscriber se existir)
    doc_record = {
        "id": doc_id,
        "company_id": cid,
        "subscriber_id": sub_id,
        "phone": phone,
        "type": "wa_transcript",
        "title": f"Transcrição WhatsApp — {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')}",
        "file_name": fname,
        "file_path": str(out_path),
        "public_url": public_url,
        "size_bytes": len(pdf_bytes),
        "message_count": len(msgs),
        "created_at": now_iso(),
        "created_by_user_id": user.get("id"),
        "created_by_user_name": user.get("name") or user.get("email"),
    }
    await db.subscriber_documents.insert_one(doc_record)
    # MongoDB injetou _id no dict — remove pra resposta JSON
    doc_record.pop("_id", None)

    return {
        "ok": True,
        "document": {k: v for k, v in doc_record.items() if k != "file_path"},
        "subscriber_linked": bool(sub_id),
        "message_count": len(msgs),
        "download_url": public_url,
    }


@router.get("/transcripts/{filename}")
async def get_transcript(
    filename: str,
    t: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Download do PDF de transcrição (auth via Bearer ou ?t=)."""
    if not re.match(r"^watp-[a-f0-9]+\.pdf$", filename):
        raise HTTPException(400, "filename inválido")
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
    path = WA_TRANSCRIPTS_DIR / filename
    if not path.exists():
        raise HTTPException(404, "PDF não encontrado")
    return FileResponse(path, media_type="application/pdf", filename=filename)


@router.get("/subscriber/{subscriber_id}/documents")
async def list_subscriber_documents(
    subscriber_id: str,
    user: dict = Depends(require_role("gestor", "auditor", "administrador")),
):
    """Lista documentos (transcrições, etc.) vinculados a um cliente."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cur = db.subscriber_documents.find(
        {"company_id": cid, "subscriber_id": subscriber_id},
        {"_id": 0, "file_path": 0},
    ).sort("created_at", -1)
    items = [d async for d in cur]
    return {"items": items, "total": len(items)}
