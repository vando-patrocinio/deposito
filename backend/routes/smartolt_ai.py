"""SmartOLT AI — endpoints REST.

Inclui:
- Outages (ativos / histórico / força detecção)
- Drafts de mensagem (ATIVO: rascunho aprovado pelo atendente humano)
- Templates configuráveis (proactive / resolved / internal_assist / internal_resolved)
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "infra-team",
    "domain": "rede",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db
from services.smartolt_ai import (
    DEFAULT_TEMPLATES, OUTAGE_MIN_LOS, OUTAGE_MIN_PCT, INTERVAL_SECONDS,
    detect_outages, list_active_outages, list_recent_resolved,
)

router = APIRouter(prefix="/api/smartolt-ai", tags=["smartolt-ai"])
logger = logging.getLogger("smartolt_ai.routes")

SIDECAR_BASE = "http://127.0.0.1:3002"


# ───────────────────────── Outages ─────────────────────────
@router.get("/outages/active")
async def get_active(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    items = await list_active_outages(cid)
    return {"items": items, "count": len(items)}


@router.get("/outages/recent")
async def get_recent(hours: int = Query(24, ge=1, le=168),
                       user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    items = await list_recent_resolved(cid, hours=hours)
    return {"items": items, "count": len(items), "hours": hours}


@router.post("/outages/detect")
async def force_detect(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    result = await detect_outages(cid)
    return result


@router.get("/summary")
async def summary(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    active = await list_active_outages(cid)
    recent = await list_recent_resolved(cid, hours=24)
    total_affected = sum(len(o.get("affected_phones") or []) for o in active)
    pending_drafts = await db.outage_drafts.count_documents(
        {"company_id": cid, "status": "pending"}
    )
    return {
        "active_count": len(active),
        "resolved_24h": len(recent),
        "total_affected_clients": total_affected,
        "pending_drafts": pending_drafts,
        "active": active[:5],
        "config": {
            "interval_seconds": INTERVAL_SECONDS,
            "min_los": OUTAGE_MIN_LOS,
            "min_pct": OUTAGE_MIN_PCT,
        },
    }


# ───────────────────────── Drafts (modo ATIVO) ─────────────────────────
@router.get("/drafts")
async def list_drafts(status: str = Query("pending"),
                        outage_id: Optional[str] = Query(None),
                        limit: int = Query(200, ge=1, le=500),
                        user: dict = Depends(require_role("gestor"))):
    """Lista rascunhos de mensagem proativa criados pelo SmartOLT AI.

    Cada rascunho aguarda aprovação do atendente humano antes de ser
    enviado de fato via Baileys.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if status and status != "all":
        q["status"] = status
    if outage_id:
        q["outage_id"] = outage_id
    items = await db.outage_drafts.find(q, {"_id": 0}) \
        .sort("created_at", -1).limit(limit).to_list(limit)
    return {"items": items, "count": len(items)}


class DraftEditIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4096)


@router.put("/drafts/{draft_id}")
async def edit_draft(draft_id: str, payload: DraftEditIn,
                       user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    res = await db.outage_drafts.update_one(
        {"id": draft_id, "company_id": cid, "status": "pending"},
        {"$set": {"text": payload.text.strip(),
                  "edited_at": now_iso(),
                  "edited_by": user.get("email") or user.get("id")}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Rascunho não encontrado ou já enviado.")
    return {"ok": True}


@router.post("/drafts/{draft_id}/discard")
async def discard_draft(draft_id: str,
                          user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    res = await db.outage_drafts.update_one(
        {"id": draft_id, "company_id": cid, "status": "pending"},
        {"$set": {"status": "discarded",
                  "discarded_at": now_iso(),
                  "discarded_by": user.get("email") or user.get("id")}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Rascunho não encontrado ou já processado.")
    return {"ok": True, "status": "discarded"}


async def _send_draft_via_baileys(cid: str, draft: Dict[str, Any],
                                    user: Dict[str, Any]) -> Dict[str, Any]:
    """Envia 1 rascunho via Baileys e persiste no histórico do chat.
    Retorna {ok, error?}.
    """
    phone = draft["phone"]
    text = draft["text"]
    send_ok = False
    send_error: Optional[str] = None
    send_body: Dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.post(f"{SIDECAR_BASE}/send",
                                 json={"phone": phone, "text": text})
            try:
                send_body = r.json()
            except Exception:
                send_body = {"raw": r.text}
            if r.status_code < 400 and send_body.get("ok"):
                send_ok = True
            else:
                send_error = send_body.get("error") or f"HTTP {r.status_code}"
    except Exception as e:
        send_error = str(e)

    # Persiste no histórico (aparece na aba Atendimento → Mensagens)
    await db.aihub_wa_messages.insert_one({
        "id": f"wam-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "direction": "outbound",
        "phone": phone,
        "text": text,
        "message_id": send_body.get("message_id"),
        "subscriber_id": draft.get("subscriber_id"),
        "outage_id": draft.get("outage_id"),
        "kind": draft.get("kind"),
        "auto_reply": False,
        "sent_from_draft": draft["id"],
        "actor_user": user.get("email") or user.get("id"),
        "sent_by_user_id": user.get("id"),
        "delivery_status": "sent" if send_ok else "failed",
        "delivery_error": send_error,
        "created_at": now_iso(),
    })
    return {"ok": send_ok, "error": send_error}


@router.post("/drafts/{draft_id}/send")
async def send_draft(draft_id: str,
                       user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    draft = await db.outage_drafts.find_one(
        {"id": draft_id, "company_id": cid, "status": "pending"},
        {"_id": 0},
    )
    if not draft:
        raise HTTPException(404, "Rascunho não encontrado ou já enviado.")
    res = await _send_draft_via_baileys(cid, draft, user)
    if res["ok"]:
        await db.outage_drafts.update_one(
            {"id": draft_id, "company_id": cid},
            {"$set": {"status": "sent",
                      "sent_at": now_iso(),
                      "sent_by_user_id": user.get("id"),
                      "sent_by": user.get("email") or user.get("id")}},
        )
        return {"ok": True, "draft_id": draft_id}
    raise HTTPException(502,
                        f"Sidecar Baileys não confirmou entrega: {res['error']}")


class BulkSendIn(BaseModel):
    ids: Optional[List[str]] = None
    outage_id: Optional[str] = None
    kind: Optional[str] = None  # "outage_proactive" | "outage_resolved"


@router.post("/drafts/send-bulk")
async def send_bulk(payload: BulkSendIn,
                      user: dict = Depends(require_role("gestor"))):
    """Aprova e envia múltiplos rascunhos. Aceita:
    - ids=[...] (lista explícita)  OU
    - outage_id + kind opcional (todos pendentes desse outage)
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid, "status": "pending"}
    if payload.ids:
        q["id"] = {"$in": payload.ids}
    elif payload.outage_id:
        q["outage_id"] = payload.outage_id
        if payload.kind:
            q["kind"] = payload.kind
    else:
        raise HTTPException(400, "Informe `ids` ou `outage_id`.")
    drafts = await db.outage_drafts.find(q, {"_id": 0}).to_list(500)
    if not drafts:
        return {"ok": True, "sent": 0, "failed": 0, "total": 0}
    sent = 0
    failed = 0
    errors: List[Dict[str, Any]] = []
    for d in drafts:
        try:
            res = await _send_draft_via_baileys(cid, d, user)
            if res["ok"]:
                await db.outage_drafts.update_one(
                    {"id": d["id"], "company_id": cid},
                    {"$set": {"status": "sent",
                              "sent_at": now_iso(),
                              "sent_by_user_id": user.get("id"),
                              "sent_by": user.get("email") or user.get("id")}},
                )
                sent += 1
            else:
                failed += 1
                errors.append({"draft_id": d["id"], "phone": d.get("phone"),
                                "error": res.get("error")})
        except Exception as e:
            failed += 1
            errors.append({"draft_id": d["id"], "phone": d.get("phone"),
                            "error": str(e)})
    return {"ok": True, "sent": sent, "failed": failed,
            "total": len(drafts), "errors": errors[:20]}


# ───────────────────────── Templates ─────────────────────────
class TemplatesIn(BaseModel):
    proactive: Optional[str] = None
    resolved: Optional[str] = None
    internal_assist: Optional[str] = None
    internal_resolved: Optional[str] = None


@router.get("/templates")
async def get_templates(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await db.aihub_settings.find_one(
        {"company_id": cid, "key": "smartolt_outage_templates"},
        {"_id": 0, "templates": 1, "updated_at": 1, "updated_by": 1},
    ) or {}
    saved = cfg.get("templates") or {}
    return {
        "templates": {**DEFAULT_TEMPLATES, **{k: v for k, v in saved.items() if v}},
        "defaults": DEFAULT_TEMPLATES,
        "placeholders": [
            "{olt}", "{board}", "{port}", "{vlan}",
            "{los_count}", "{total_count}", "{severity_pct}",
            "{duration_min}", "{since_resolved_min}",
        ],
        "updated_at": cfg.get("updated_at"),
        "updated_by": cfg.get("updated_by"),
    }


@router.put("/templates")
async def put_templates(payload: TemplatesIn,
                          user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    tpl = {k: v.strip() for k, v in payload.model_dump(exclude_none=True).items() if v}
    await db.aihub_settings.update_one(
        {"company_id": cid, "key": "smartolt_outage_templates"},
        {"$set": {
            "company_id": cid, "key": "smartolt_outage_templates",
            "templates": tpl,
            "updated_at": now_iso(),
            "updated_by": user.get("email") or user.get("id"),
        }},
        upsert=True,
    )
    return {"ok": True, "templates": tpl}
