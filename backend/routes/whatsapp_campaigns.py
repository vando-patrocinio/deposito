"""
whatsapp_campaigns.py — Aprovação e envio de Campanhas em Massa (iter217b)

Trabalha sobre a collection `whatsapp_campaigns_drafts` populada pelo
Agente IA (`bulk_whatsapp_campaign` tool) ou criada manualmente.

Fluxo:
  1. Admin lista drafts pendentes (`pending_approval`)
  2. Pode editar template, escolher canal WhatsApp, ajustar destinatários
  3. Clica "Aprovar e Enviar" → status muda pra `dispatching` e um
     BackgroundTask manda 1 msg a cada 3 ± 1.5s (anti-ban)
  4. Cada envio é logado em `mass_messages_jobs` + bump nos contadores
  5. Status final: `completed` ou `failed`

Endpoints:
  GET    /api/wa-campaigns/drafts                  Lista (filtros: status)
  GET    /api/wa-campaigns/drafts/{id}             Detalhe + alvos
  PUT    /api/wa-campaigns/drafts/{id}             Edita template/ids
  POST   /api/wa-campaigns/drafts/{id}/approve     Aprova e dispara
  POST   /api/wa-campaigns/drafts/{id}/reject      Rejeita
  POST   /api/wa-campaigns/drafts                  Cria draft manual
  GET    /api/wa-campaigns/drafts/{id}/log         Log do envio
"""
from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, get_current_user
from database import db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/wa-campaigns", tags=["wa-campaigns"])


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────── Schemas ───────────────────
class DraftIn(BaseModel):
    segment_name: str = Field(..., min_length=1, max_length=120)
    template: str = Field(..., min_length=1, max_length=2000)
    subscriber_ids: List[str] = []


class DraftEditIn(BaseModel):
    segment_name: Optional[str] = None
    template: Optional[str] = None
    subscriber_ids: Optional[List[str]] = None


# ─────────────────── List ───────────────────
@router.get("/drafts")
async def list_drafts(
    status: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    cid = _cid(user)
    q: Dict[str, Any] = {"company_id": cid}
    if status:
        q["status"] = status
    items = await db.whatsapp_campaigns_drafts.find(
        q, {"_id": 0}
    ).sort("created_at", -1).to_list(200)

    # enrich com totals
    for it in items:
        it["recipients_total"] = len(it.get("subscriber_ids") or [])
    return {"items": items, "total": len(items)}


@router.get("/drafts/{draft_id}")
async def get_draft(draft_id: str,
                       user: dict = Depends(get_current_user)):
    cid = _cid(user)
    d = await db.whatsapp_campaigns_drafts.find_one(
        {"company_id": cid, "id": draft_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "draft não encontrado")
    # Carrega nomes/phones dos primeiros 30 alvos pra preview
    ids = (d.get("subscriber_ids") or [])[:30]
    if ids:
        subs = await db.subscribers.find(
            {"id": {"$in": ids}},
            {"_id": 0, "id": 1, "name": 1, "phone": 1,
             "plan_name": 1, "status": 1}
        ).to_list(30)
        d["recipients_preview"] = subs
    d["recipients_total"] = len(d.get("subscriber_ids") or [])
    return d


# ─────────────────── Create / Edit ───────────────────
@router.post("/drafts")
async def create_draft(payload: DraftIn,
                          user: dict = Depends(get_current_user)):
    cid = _cid(user)
    doc = {
        "id": f"camp-{uuid.uuid4().hex[:14]}",
        "company_id": cid,
        "segment_name": payload.segment_name,
        "template": payload.template,
        "subscriber_ids": payload.subscriber_ids[:5000],
        "status": "pending_approval",
        "created_at": _now_iso(),
        "created_by": user.get("email") or "admin",
        "sent_count": 0, "failed_count": 0,
    }
    await db.whatsapp_campaigns_drafts.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/drafts/{draft_id}")
async def edit_draft(draft_id: str, payload: DraftEditIn,
                        user: dict = Depends(get_current_user)):
    cid = _cid(user)
    draft = await db.whatsapp_campaigns_drafts.find_one(
        {"company_id": cid, "id": draft_id}, {"_id": 0, "status": 1})
    if not draft:
        raise HTTPException(404, "draft não encontrado")
    if draft.get("status") not in (None, "pending_approval"):
        raise HTTPException(409, f"Draft está {draft['status']} — "
                                    "não pode mais ser editado")
    upd: Dict[str, Any] = {"updated_at": _now_iso()}
    if payload.segment_name is not None:
        upd["segment_name"] = payload.segment_name
    if payload.template is not None:
        upd["template"] = payload.template
    if payload.subscriber_ids is not None:
        upd["subscriber_ids"] = payload.subscriber_ids[:5000]
    r = await db.whatsapp_campaigns_drafts.update_one(
        {"company_id": cid, "id": draft_id}, {"$set": upd})
    return {"ok": True, "modified": r.modified_count}


@router.post("/drafts/{draft_id}/reject")
async def reject_draft(draft_id: str,
                          user: dict = Depends(get_current_user)):
    cid = _cid(user)
    r = await db.whatsapp_campaigns_drafts.update_one(
        {"company_id": cid, "id": draft_id,
         "status": "pending_approval"},
        {"$set": {"status": "rejected", "rejected_at": _now_iso(),
                   "rejected_by": user.get("email")}})
    if r.matched_count == 0:
        raise HTTPException(404, "draft não encontrado ou já processado")
    return {"ok": True}


# ─────────────────── Approve + Dispatch ───────────────────
class ApproveIn(BaseModel):
    delay_min_sec: float = 2.0
    delay_max_sec: float = 5.0


@router.post("/drafts/{draft_id}/approve")
async def approve_draft(draft_id: str, payload: ApproveIn,
                           background_tasks: BackgroundTasks,
                           user: dict = Depends(get_current_user)):
    cid = _cid(user)
    draft = await db.whatsapp_campaigns_drafts.find_one(
        {"company_id": cid, "id": draft_id}, {"_id": 0})
    if not draft:
        raise HTTPException(404, "draft não encontrado")
    if draft.get("status") != "pending_approval":
        raise HTTPException(409, f"Draft está {draft.get('status')} — "
                                    "não pode ser aprovado")
    ids = draft.get("subscriber_ids") or []
    if not ids:
        raise HTTPException(400, "Sem destinatários")

    delay_min = max(1.0, float(payload.delay_min_sec or 2.0))
    delay_max = max(delay_min, float(payload.delay_max_sec or 5.0))

    await db.whatsapp_campaigns_drafts.update_one(
        {"company_id": cid, "id": draft_id},
        {"$set": {
            "status": "dispatching",
            "approved_at": _now_iso(),
            "approved_by": user.get("email"),
            "delay_min_sec": delay_min,
            "delay_max_sec": delay_max,
        }})
    background_tasks.add_task(
        _dispatch_campaign, cid, draft_id, delay_min, delay_max)
    return {"ok": True, "queued": len(ids),
             "delay_window_sec": [delay_min, delay_max]}


@router.get("/drafts/{draft_id}/log")
async def get_log(draft_id: str,
                     limit: int = Query(200, ge=1, le=2000),
                     user: dict = Depends(get_current_user)):
    cid = _cid(user)
    items = await db.wa_campaign_logs.find(
        {"company_id": cid, "draft_id": draft_id}, {"_id": 0}
    ).sort("sent_at", -1).to_list(limit)
    return {"items": items, "total": len(items)}


# ─────────────────── Worker ───────────────────
def _render_template(tpl: str, sub: Dict[str, Any]) -> str:
    nome = (sub.get("name") or "").strip()
    primeiro = nome.split()[0] if nome else ""
    plano = (sub.get("plan_name") or "").strip()
    return (tpl or "") \
        .replace("{nome}", nome or "cliente") \
        .replace("{primeiro_nome}", primeiro or "cliente") \
        .replace("{plano}", plano or "—")


async def _dispatch_campaign(cid: str, draft_id: str,
                                delay_min: float, delay_max: float):
    """Worker em background: envia 1 msg de cada vez com delay
    aleatório entre `delay_min` e `delay_max` segundos."""
    try:
        from services.wa.sidecar import _sidecar_post_silent
    except Exception as e:
        logger.error("[wa-camp] sidecar import falhou: %s", e)
        await db.whatsapp_campaigns_drafts.update_one(
            {"company_id": cid, "id": draft_id},
            {"$set": {"status": "failed",
                       "failed_reason": f"import: {e}"}})
        return

    draft = await db.whatsapp_campaigns_drafts.find_one(
        {"company_id": cid, "id": draft_id}, {"_id": 0})
    if not draft:
        return
    tpl = draft.get("template") or ""
    ids = draft.get("subscriber_ids") or []

    sent = 0
    failed = 0
    for sub_id in ids:
        # Resolve phone+name
        sub = await db.subscribers.find_one(
            {"id": sub_id},
            {"_id": 0, "phone": 1, "name": 1, "plan_name": 1})
        if not sub or not sub.get("phone"):
            failed += 1
            await db.wa_campaign_logs.insert_one({
                "id": f"log-{uuid.uuid4().hex[:10]}",
                "company_id": cid, "draft_id": draft_id,
                "subscriber_id": sub_id,
                "ok": False, "error": "phone ausente",
                "sent_at": _now_iso(),
            })
            continue
        msg = _render_template(tpl, sub)
        phone = "".join(c for c in str(sub["phone"]) if c.isdigit())
        try:
            res = await _sidecar_post_silent(
                "/send", {"phone": phone, "text": msg}, timeout=30.0)
            ok = bool(res.get("ok"))
            await db.wa_campaign_logs.insert_one({
                "id": f"log-{uuid.uuid4().hex[:10]}",
                "company_id": cid, "draft_id": draft_id,
                "subscriber_id": sub_id, "phone": phone,
                "ok": ok, "external_id": res.get("message_id"),
                "error": None if ok else res.get("error"),
                "sent_at": _now_iso(),
            })
            if ok:
                sent += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            await db.wa_campaign_logs.insert_one({
                "id": f"log-{uuid.uuid4().hex[:10]}",
                "company_id": cid, "draft_id": draft_id,
                "subscriber_id": sub_id, "phone": phone,
                "ok": False, "error": str(e),
                "sent_at": _now_iso(),
            })

        # Atualiza contadores a cada 10
        if (sent + failed) % 10 == 0:
            await db.whatsapp_campaigns_drafts.update_one(
                {"company_id": cid, "id": draft_id},
                {"$set": {"sent_count": sent, "failed_count": failed,
                            "progress_at": _now_iso()}})

        # Anti-ban: jitter aleatório
        await asyncio.sleep(random.uniform(delay_min, delay_max))

    await db.whatsapp_campaigns_drafts.update_one(
        {"company_id": cid, "id": draft_id},
        {"$set": {
            "status": "completed" if failed == 0 else "completed_partial",
            "sent_count": sent, "failed_count": failed,
            "finished_at": _now_iso(),
        }})
    logger.info("[wa-camp] draft=%s done sent=%d failed=%d",
                  draft_id, sent, failed)
