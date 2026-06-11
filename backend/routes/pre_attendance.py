"""
pre_attendance.py — Rotas de Propaganda Pré-Atendimento (iter217a)

Endpoints:
  GET    /api/pre-attendance/promos                Lista promos
  POST   /api/pre-attendance/promos                Cria
  PUT    /api/pre-attendance/promos/{id}           Edita
  DELETE /api/pre-attendance/promos/{id}           Remove
  POST   /api/pre-attendance/promos/{id}/toggle    Ativa/inativa
  POST   /api/pre-attendance/upload-image          Upload imagem (b64)
  GET    /api/pre-attendance/dispatches            Histórico recente
  GET    /api/pre-attendance/stats                 Totais agregados
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "atendimento",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import base64
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, get_current_user
from database import db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/pre-attendance", tags=["pre-attendance"])

UPLOAD_DIR = Path("/app/backend/uploads/pre_attendance")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PromoIn(BaseModel):
    title: str = Field(..., min_length=2, max_length=120)
    message_text: str = Field(..., min_length=1, max_length=2000)
    image_url: Optional[str] = None
    target_filter: str = "all"        # all|active|inactive|inadimplentes|by_plan
    target_plan_ids: List[str] = []
    weight: int = 1
    ai_enabled: bool = True
    active: bool = True


def _to_doc(cid: str, payload: PromoIn,
              promo_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": promo_id or f"promo-{uuid.uuid4().hex[:14]}",
        "company_id": cid,
        "title": payload.title.strip(),
        "message_text": payload.message_text.strip(),
        "image_url": (payload.image_url or "").strip() or None,
        "target_filter": payload.target_filter or "all",
        "target_plan_ids": payload.target_plan_ids or [],
        "weight": max(int(payload.weight or 1), 1),
        "ai_enabled": bool(payload.ai_enabled),
        "active": bool(payload.active),
    }


# ─────────────────── CRUD ───────────────────
@router.get("/promos")
async def list_promos(user: dict = Depends(get_current_user)):
    cid = _cid(user)
    items = await db.pre_attendance_promos.find(
        {"company_id": cid}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    return {"items": items, "total": len(items)}


@router.post("/promos")
async def create_promo(payload: PromoIn,
                          user: dict = Depends(get_current_user)):
    cid = _cid(user)
    doc = _to_doc(cid, payload)
    doc.update({
        "stats_sent": 0, "stats_replied": 0,
        "last_sent_at": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "created_by": user.get("email"),
    })
    await db.pre_attendance_promos.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/promos/{promo_id}")
async def update_promo(promo_id: str, payload: PromoIn,
                          user: dict = Depends(get_current_user)):
    cid = _cid(user)
    upd = _to_doc(cid, payload, promo_id)
    upd["updated_at"] = _now_iso()
    upd.pop("id", None)
    upd.pop("company_id", None)
    r = await db.pre_attendance_promos.update_one(
        {"company_id": cid, "id": promo_id}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(404, "Promoção não encontrada")
    return {"ok": True, "modified": r.modified_count}


@router.delete("/promos/{promo_id}")
async def delete_promo(promo_id: str,
                          user: dict = Depends(get_current_user)):
    cid = _cid(user)
    r = await db.pre_attendance_promos.delete_one(
        {"company_id": cid, "id": promo_id})
    if r.deleted_count == 0:
        raise HTTPException(404, "Promoção não encontrada")
    return {"ok": True}


@router.post("/promos/{promo_id}/toggle")
async def toggle_promo(promo_id: str,
                          user: dict = Depends(get_current_user)):
    cid = _cid(user)
    promo = await db.pre_attendance_promos.find_one(
        {"company_id": cid, "id": promo_id}, {"_id": 0, "active": 1})
    if not promo:
        raise HTTPException(404, "Promoção não encontrada")
    new = not promo.get("active")
    await db.pre_attendance_promos.update_one(
        {"company_id": cid, "id": promo_id},
        {"$set": {"active": new, "updated_at": _now_iso()}})
    return {"ok": True, "active": new}


# ─────────────────── Upload imagem ───────────────────
class ImageUploadIn(BaseModel):
    image_b64: str
    filename: Optional[str] = None


@router.post("/upload-image")
async def upload_image(payload: ImageUploadIn,
                          user: dict = Depends(get_current_user)):
    """Recebe imagem em base64 (com prefixo data:image/... ou puro),
    salva em disco e devolve URL pública servida pelo backend."""
    cid = _cid(user)
    try:
        raw = payload.image_b64 or ""
        if "," in raw:
            raw = raw.split(",", 1)[1]
        data = base64.b64decode(raw)
        if len(data) > 5 * 1024 * 1024:
            raise HTTPException(413, "Imagem maior que 5MB")
        if len(data) < 32:
            raise HTTPException(400, "Imagem inválida")
        # detecta extensão pelo magic byte
        if data.startswith(b"\xff\xd8\xff"):
            ext = "jpg"
        elif data.startswith(b"\x89PNG"):
            ext = "png"
        elif data[:6] in (b"GIF87a", b"GIF89a"):
            ext = "gif"
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            ext = "webp"
        else:
            ext = "jpg"
        fname = f"{cid}_{uuid.uuid4().hex[:14]}.{ext}"
        path = UPLOAD_DIR / fname
        path.write_bytes(data)
        url = f"/api/pre-attendance/image/{fname}"
        return {"ok": True, "url": url, "filename": fname,
                 "size_bytes": len(data)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[pre-attendance] upload-image falhou: %s", e)
        raise HTTPException(400, f"upload falhou: {e}")


@router.get("/image/{filename}")
async def get_image(filename: str,
                       user: dict = Depends(get_current_user)):
    """Serve a imagem armazenada. iter220 — agora exige autenticação
    (qualquer usuário logado da empresa pode ler — controle a nível
    de empresa pelo prefixo do filename `{cid}_...`)."""
    from fastapi.responses import FileResponse
    # Sanitização básica
    if "/" in filename or ".." in filename:
        raise HTTPException(400, "filename inválido")
    # Garante que a imagem pertence à empresa do usuário (prefixo)
    cid = _cid(user)
    if cid and not filename.startswith(f"{cid}_"):
        # Bloqueia leitura cross-company
        raise HTTPException(403,
            "Você não tem permissão para acessar este recurso.")
    path = UPLOAD_DIR / filename
    if not path.exists():
        raise HTTPException(404, "imagem não encontrada")
    return FileResponse(str(path))


# ─────────────────── Histórico + stats ───────────────────
@router.get("/dispatches")
async def list_dispatches(
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(get_current_user),
):
    cid = _cid(user)
    items = await db.pre_attendance_dispatches.find(
        {"company_id": cid}, {"_id": 0}
    ).sort("sent_at", -1).to_list(limit)
    return {"items": items, "total": len(items)}


@router.get("/stats")
async def stats(user: dict = Depends(get_current_user)):
    cid = _cid(user)
    total_sent = await db.pre_attendance_dispatches.count_documents(
        {"company_id": cid})
    total_replied = await db.pre_attendance_dispatches.count_documents(
        {"company_id": cid, "replied": True})
    ai_picks = await db.pre_attendance_dispatches.count_documents(
        {"company_id": cid, "ai_picked": True})
    promos = await db.pre_attendance_promos.count_documents(
        {"company_id": cid})
    active = await db.pre_attendance_promos.count_documents(
        {"company_id": cid, "active": True})
    return {
        "total_promos": promos, "active_promos": active,
        "total_sent": total_sent, "total_replied": total_replied,
        "reply_rate_pct": round(
            100 * total_replied / total_sent, 1) if total_sent else 0.0,
        "ai_picks": ai_picks,
    }


# ─────────────────── Teste manual ───────────────────
class TestSendIn(BaseModel):
    promo_id: str
    phone: str
    subscriber_id: Optional[str] = None


@router.post("/test-send")
async def test_send(payload: TestSendIn,
                       user: dict = Depends(get_current_user)):
    """Envia uma promo específica pra um phone (debug/preview)."""
    cid = _cid(user)
    promo = await db.pre_attendance_promos.find_one(
        {"company_id": cid, "id": payload.promo_id}, {"_id": 0})
    if not promo:
        raise HTTPException(404, "Promoção não encontrada")

    sub = {}
    if payload.subscriber_id:
        sub = (await db.subscribers.find_one(
            {"id": payload.subscriber_id},
            {"_id": 0, "name": 1, "plan_name": 1}) or {})

    from services.pre_attendance_promo import (
        _placeholders, _send_via_sidecar)
    msg = _placeholders(promo.get("message_text") or "", sub)
    res = await _send_via_sidecar(payload.phone, msg,
                                     promo.get("image_url"))
    return {"ok": bool(res.get("ok")), "result": res,
             "text_sent": msg, "image": promo.get("image_url")}
