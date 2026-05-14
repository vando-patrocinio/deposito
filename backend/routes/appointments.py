"""Agendamentos — bolhas de serviço criadas a partir do chat.

Estrutura `db.appointments`:
- id (str), company_id (str)
- phone (str)                     ─ conversa de origem (se houver)
- date (YYYY-MM-DD), time (HH:MM)
- reason (str), description (str)
- subscriber_id (str | None), subscriber_name (str), subscriber_document (str | None)
- created_by (str), created_at (iso)
- status: scheduled | completed | cancelled
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.appointments")
router = APIRouter(prefix="/api/appointments", tags=["appointments"])


class AppointmentIn(BaseModel):
    phone: Optional[str] = None
    date: str = Field(..., min_length=10, max_length=10)  # YYYY-MM-DD
    time: str = Field(..., min_length=4, max_length=5)    # HH:MM
    reason: str = Field(..., min_length=2, max_length=200)
    description: Optional[str] = ""
    subscriber_id: Optional[str] = None
    subscriber_name: Optional[str] = ""
    subscriber_document: Optional[str] = None


@router.post("")
async def create_appointment(payload: AppointmentIn,
                                user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID

    # Valida formato data/hora
    try:
        datetime.strptime(payload.date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Data inválida — formato esperado YYYY-MM-DD.")
    try:
        datetime.strptime(payload.time, "%H:%M")
    except ValueError:
        raise HTTPException(400, "Hora inválida — formato esperado HH:MM.")

    doc = {
        "id": f"appt-{uuid.uuid4().hex[:12]}",
        "company_id": cid,
        "phone": (payload.phone or "").strip() or None,
        "date": payload.date,
        "time": payload.time,
        "reason": payload.reason.strip(),
        "description": (payload.description or "").strip()[:1000],
        "subscriber_id": payload.subscriber_id or None,
        "subscriber_name": (payload.subscriber_name or "").strip()[:160],
        "subscriber_document": payload.subscriber_document or None,
        "status": "scheduled",
        "created_at": now_iso(),
        "created_by": user.get("email") or user.get("id"),
        "created_by_id": user.get("id"),
    }
    await db.appointments.insert_one(doc)
    doc.pop("_id", None)

    # Posta uma bolha no histórico WhatsApp como nota interna pra ficar
    # visível no chat (não envia ao cliente — é registro interno).
    if payload.phone:
        await db.aihub_wa_messages.insert_one({
            "id": f"wam-{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "direction": "internal",
            "phone": payload.phone.strip(),
            "text": (
                f"📅 Agendamento: {payload.reason}\n"
                f"📍 {payload.date} às {payload.time}\n"
                + (f"👤 {doc['subscriber_name']}\n" if doc["subscriber_name"] else "")
                + (f"📝 {doc['description']}" if doc["description"] else "")
            ),
            "is_internal_note": True,
            "note_kind": "appointment",
            "appointment_id": doc["id"],
            "created_at": doc["created_at"],
            "actor_user": doc["created_by"],
        })

    return doc


@router.get("")
async def list_appointments(
    phone: Optional[str] = None,
    subscriber_id: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    user: dict = Depends(require_role("gestor")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    flt = {"company_id": cid}
    if phone:
        flt["phone"] = phone.strip()
    if subscriber_id:
        flt["subscriber_id"] = subscriber_id
    if status:
        flt["status"] = status
    if date_from or date_to:
        flt["date"] = {}
        if date_from:
            flt["date"]["$gte"] = date_from
        if date_to:
            flt["date"]["$lte"] = date_to
    items = await db.appointments.find(
        flt, {"_id": 0},
    ).sort([("date", 1), ("time", 1)]).limit(limit).to_list(limit)
    return {"items": items, "count": len(items)}


@router.patch("/{appt_id}/status")
async def update_status(appt_id: str, status: str,
                           user: dict = Depends(require_role("gestor"))):
    if status not in ("scheduled", "completed", "cancelled"):
        raise HTTPException(400, "Status inválido.")
    cid = user.get("company_id") or DEMO_COMPANY_ID
    res = await db.appointments.update_one(
        {"id": appt_id, "company_id": cid},
        {"$set": {"status": status, "updated_at": now_iso()}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Agendamento não encontrado.")
    return {"ok": True}


@router.delete("/{appt_id}")
async def delete_appointment(appt_id: str,
                                user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    res = await db.appointments.delete_one({"id": appt_id, "company_id": cid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Agendamento não encontrado.")
    return {"ok": True}
