"""EXECUTIVE DECISIONS — fluxo IA propõe -> humano aprova com rastro auditável.

Collection MongoDB `executive_decisions`. Origem do recado: Isabella
(operacional) ou Presidente IA (executiva). Aprovação: CEO.
Schema:
    {
      id, company_id, decision (text), context, related_kpi,
      priority: p0|p1|p2|p3,
      proposed_by: isabella|presidente_ia|cto|ceo,
      approved_by: str|None,
      owner: str (quem executa),
      deadline: YYYY-MM-DD,
      status: proposed|approved|in_progress|done|cancelled,
      created_at, updated_at, completed_at
    }
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "ceo_digital",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import uuid
from datetime import datetime, timezone
from typing import Optional

from database import db

ALLOWED_STATUS = {"proposed", "approved", "in_progress", "done", "cancelled"}
# Aliases aceitos em filtros (status=pending == proposed) para alinhar com
# spec do CEO (15/06/2026, mensagem cto-7f1b3d5e3de846).
STATUS_ALIASES = {"pending": "proposed"}
ALLOWED_PRIORITY = {"p0", "p1", "p2", "p3"}
ALLOWED_PROPOSER = {"isabella", "presidente_ia", "cto", "ceo"}


async def create_decision(cid: str, payload: dict) -> dict:
    decision_text = (payload.get("decision") or payload.get("title") or "").strip()
    if not decision_text:
        raise ValueError("campo 'decision' obrigatório")

    proposed_by = payload.get("proposed_by") or "presidente_ia"
    if proposed_by not in ALLOWED_PROPOSER:
        raise ValueError(f"proposed_by inválido. use {ALLOWED_PROPOSER}")

    priority = payload.get("priority") or "p2"
    if priority not in ALLOWED_PRIORITY:
        raise ValueError(f"priority inválida. use {ALLOWED_PRIORITY}")

    status = STATUS_ALIASES.get(payload.get("status") or "", payload.get("status") or "proposed")
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status inválido. use {ALLOWED_STATUS}")

    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": f"dec-{uuid.uuid4().hex[:14]}",
        "company_id": cid,
        "decision": decision_text,
        "title": payload.get("title") or decision_text[:80],
        "rationale": payload.get("rationale") or payload.get("context"),
        "context": payload.get("context"),
        "related_kpi": payload.get("related_kpi") or payload.get("kpi"),
        "kpi": payload.get("kpi") or payload.get("related_kpi"),
        "expected_impact": payload.get("expected_impact"),
        "source_snapshot_id": payload.get("source_snapshot_id"),
        "priority": priority,
        "proposed_by": proposed_by,
        "approved_by": payload.get("approved_by"),
        "approved_at": payload.get("approved_at"),
        "owner": payload.get("owner") or "ceo",
        "deadline": payload.get("deadline"),
        "status": status,
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
    }
    await db.executive_decisions.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def list_decisions(cid: str, status: Optional[str] = None,
                          limit: int = 50) -> list[dict]:
    flt: dict = {"company_id": cid}
    if status:
        normalized = STATUS_ALIASES.get(status, status)
        if normalized not in ALLOWED_STATUS:
            raise ValueError("status inválido")
        flt["status"] = normalized
    cur = db.executive_decisions.find(flt, {"_id": 0}).sort(
        "created_at", -1).limit(min(max(limit, 1), 200))
    return await cur.to_list(length=200)


async def update_status(cid: str, decision_id: str, payload: dict) -> dict:
    raw_status = payload.get("status")
    new_status = STATUS_ALIASES.get(raw_status, raw_status) if raw_status else None
    if new_status and new_status not in ALLOWED_STATUS:
        raise ValueError(f"status inválido. use {ALLOWED_STATUS}")
    now = datetime.now(timezone.utc).isoformat()
    set_doc: dict = {"updated_at": now}
    if new_status:
        set_doc["status"] = new_status
        if new_status == "done":
            set_doc["completed_at"] = now
        if new_status == "approved":
            # approved_at auto-preenche se não vier explícito
            set_doc["approved_at"] = payload.get("approved_at") or now
            if payload.get("approved_by"):
                set_doc["approved_by"] = payload.get("approved_by")
    for k in ("owner", "deadline", "context", "priority", "title",
               "rationale", "expected_impact", "source_snapshot_id",
               "related_kpi", "kpi"):
        if payload.get(k) is not None:
            set_doc[k] = payload.get(k)

    res = await db.executive_decisions.update_one(
        {"id": decision_id, "company_id": cid}, {"$set": set_doc})
    if res.matched_count == 0:
        raise LookupError(f"decision {decision_id} não encontrada")
    doc = await db.executive_decisions.find_one(
        {"id": decision_id}, {"_id": 0})
    return doc or {}
