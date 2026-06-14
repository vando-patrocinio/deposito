"""UNIVERSO LIGO — Curadoria, Convites, DNC e NPS Mínimo Viável.

Endpoints administrativos para o piloto de convite humano dos fundadores.

REGRA DE OURO: nenhum endpoint aqui dispara comunicação automática ao
cliente. Tudo é registro manual feito por humano, com auditoria completa.

Collections novas:
- `universo_ligo_invites` — convites e seus desfechos
- `nps_responses_mvp` — 1 pergunta, 1 resposta

Field novo em `subscribers`:
- `do_not_contact_universo_ligo` (bool) — DNC absoluto. Respeitado
  pelo sistema todo (helper `should_contact_subscriber`).
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "universo_ligo",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import get_current_user, is_super_admin
from database import db

log = logging.getLogger("ponto.universo_ligo_curadoria")
router = APIRouter(prefix="/api/universo-ligo/curadoria",
                   tags=["universo_ligo_curadoria"])


VALID_DECISIONS = {"APTO", "REVISAR", "NAO_CONVIDAR"}
VALID_SOURCES = {"fundador", "ouro", "embaixador", "manual"}
VALID_CONFIDENCE = {"alta", "media", "baixa"}
VALID_CHANNELS = {"call", "wa", "visita", "manual"}


# --------------------------------------------------------------------- helpers
def _actor(user: dict) -> str:
    return user.get("email") or user.get("id") or "unknown"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _ensure_indexes():
    try:
        await db.universo_ligo_invites.create_index("subscriber_id")
        await db.universo_ligo_invites.create_index("document")
        await db.universo_ligo_invites.create_index(
            [("invite_source", 1), ("status", 1)]
        )
        await db.universo_ligo_invites.create_index(
            [("do_not_contact_universo_ligo", 1)]
        )
        await db.nps_responses_mvp.create_index(
            [("subscriber_id", 1), ("created_at", -1)]
        )
        await db.nps_responses_mvp.create_index([("company_id", 1), ("score", 1)])
    except Exception as e:
        log.warning(f"[curadoria] indexes: {e}")


def _require_admin(user: dict):
    role = (user.get("role") or "").lower()
    if role not in ("administrador", "auditor", "diretor", "ceo"):
        if not is_super_admin(user):
            raise HTTPException(403, "acesso negado — apenas liderança")


# --------------------------------------------------------------------- TOP 10
async def _load_top10_from_loyalty() -> List[Dict[str, Any]]:
    """Re-deriva o TOP 10 fundadores em runtime a partir de loyalty_imported_db.

    Critério estrito (mesmo dos relatórios):
      - co-demo, status=Ativo
      - sem placeholders de documento
      - 0 cancelamentos no histórico
      - reg < 2020-01-01
      - paid >= 50, overdue = 0
    Sort: registration_date ASC, paid DESC. Limit 10.
    """
    from collections import defaultdict
    PLACEHOLDER = ["00000000000", "99999999999", ""]
    doc_states: Dict[str, list] = defaultdict(list)
    async for r in db.loyalty_imported_db.find(
        {"company_id": "co-demo",
         "document": {"$nin": PLACEHOLDER + [None]}},
        {"document": 1, "status": 1, "name": 1, "city": 1, "district": 1,
         "registration_date": 1, "invoices_paid": 1, "invoices_overdue": 1,
         "tickets_open": 1, "tickets_closed": 1, "plan_name": 1,
         "monthly_fee": 1, "phone1": 1}
    ):
        doc_states[r["document"]].append(r)

    pool: List[Dict[str, Any]] = []
    for d, recs in doc_states.items():
        actives = [r for r in recs if r.get("status") == "Ativo"]
        cancels = [r for r in recs if r.get("status") == "Desativado"]
        if not actives or cancels:
            continue
        valid = [r for r in recs if r.get("registration_date")
                 and str(r["registration_date"])[:4] >= "2008"]
        if not valid:
            continue
        oldest = min(valid, key=lambda r: r["registration_date"])
        main = max(actives, key=lambda r: r.get("invoices_paid", 0) or 0)
        if (oldest["registration_date"] < "2020-01-01"
            and (main.get("invoices_paid") or 0) >= 50
            and (main.get("invoices_overdue") or 0) == 0):
            pool.append({
                "document": d, "name": main.get("name"),
                "first_reg": oldest["registration_date"][:10],
                "city": main.get("city"), "district": main.get("district"),
                "paid": main.get("invoices_paid"),
                "tickets_closed": main.get("tickets_closed"),
                "tickets_open": main.get("tickets_open"),
                "plan": main.get("plan_name"),
                "fee": main.get("monthly_fee"),
                "phone": main.get("phone1"),
            })

    pool.sort(key=lambda x: (x["first_reg"], -(x["paid"] or 0)))
    return pool[:10]


@router.get("/top10")
async def get_top10(user: dict = Depends(get_current_user)):
    """Retorna TOP 10 fundadores enriquecidos com status atual de validação."""
    _require_admin(user)
    items = await _load_top10_from_loyalty()
    # Mescla status de validação já existente (se houver)
    for it in items:
        v = await db.universo_ligo_invites.find_one(
            {"document": it["document"], "invite_source": "fundador"},
            {"_id": 0}
        )
        if v:
            it["validation"] = {
                "decision": v.get("decision"),
                "decision_reason": v.get("decision_reason"),
                "validated_by": v.get("validated_by"),
                "validated_at": v.get("validated_at"),
                "confidence": v.get("confidence"),
                "status": v.get("status"),
            }
        else:
            it["validation"] = None
        # mascarar CPF/telefone em response
        d = it.get("document") or ""
        it["document_masked"] = ("***" + d[-4:]) if d else "—"
        phone = it.get("phone") or ""
        it["phone_masked"] = (phone[:4] + "****" + phone[-4:]) if len(phone) >= 8 else (phone or "—")
    return {
        "items": items,
        "total": len(items),
        "generated_at": _now(),
    }


# --------------------------------------------------------------------- VALIDATE
class ValidationBody(BaseModel):
    document: str = Field(..., min_length=11, max_length=14)
    decision: str
    decision_reason: str = Field(..., min_length=5)
    confidence: str = "media"
    invite_source: str = "fundador"


@router.post("/validate")
async def validate_founder(body: ValidationBody,
                           user: dict = Depends(get_current_user)):
    """Salva carimbo APTO/REVISAR/NAO_CONVIDAR de Atendimento.

    `decision_reason` é obrigatório (governança CTO).
    """
    _require_admin(user)
    await _ensure_indexes()
    if body.decision not in VALID_DECISIONS:
        raise HTTPException(400, f"decision deve ser um de {VALID_DECISIONS}")
    if body.confidence not in VALID_CONFIDENCE:
        raise HTTPException(400, f"confidence deve ser um de {VALID_CONFIDENCE}")
    if body.invite_source not in VALID_SOURCES:
        raise HTTPException(400, f"invite_source deve ser um de {VALID_SOURCES}")
    if not body.decision_reason or len(body.decision_reason.strip()) < 5:
        raise HTTPException(
            400,
            "decision_reason é obrigatório e deve ter pelo menos 5 caracteres"
        )

    # Buscar subscriber_id real
    sub = await db.subscribers.find_one(
        {"document": body.document}, {"id": 1, "company_id": 1, "name": 1}
    )

    now = _now()
    actor = _actor(user)

    existing = await db.universo_ligo_invites.find_one(
        {"document": body.document, "invite_source": body.invite_source}
    )

    payload = {
        "subscriber_id": sub.get("id") if sub else None,
        "company_id": sub.get("company_id") if sub else "co-demo",
        "document": body.document,
        "name_snapshot": sub.get("name") if sub else None,
        "decision": body.decision,
        "decision_reason": body.decision_reason.strip(),
        "confidence": body.confidence,
        "invite_source": body.invite_source,
        "validated_by": actor,
        "validated_at": now,
        "status": ("validated_apto" if body.decision == "APTO" else
                   "validated_review" if body.decision == "REVISAR" else
                   "validated_declined"),
        "updated_at": now,
    }

    if existing:
        # mantém histórico no campo `history`
        history = existing.get("history") or []
        history.append({
            "decision": existing.get("decision"),
            "decision_reason": existing.get("decision_reason"),
            "validated_by": existing.get("validated_by"),
            "validated_at": existing.get("validated_at"),
        })
        await db.universo_ligo_invites.update_one(
            {"_id": existing["_id"]},
            {"$set": {**payload, "history": history}}
        )
        invite_id = existing.get("id")
    else:
        invite_id = f"uli-{uuid.uuid4().hex[:12]}"
        payload.update({
            "id": invite_id,
            "created_at": now,
            "invited_at": None,
            "invited_by": None,
            "channel": None,
            "accepted_at": None,
            "declined_at": None,
            "decline_reason": None,
            "do_not_contact_universo_ligo": False,
            "do_not_contact_at": None,
            "do_not_contact_reason": None,
            "notes": [],
            "history": [],
        })
        await db.universo_ligo_invites.insert_one(payload)

    log.info(
        f"[curadoria] validate doc={body.document} by={actor} "
        f"decision={body.decision} reason={body.decision_reason[:40]}"
    )
    return {"ok": True, "invite_id": invite_id, "status": payload["status"]}


# --------------------------------------------------------------------- INVITE
class InviteBody(BaseModel):
    document: str
    channel: str
    notes: Optional[str] = None
    accepted: Optional[bool] = None
    declined: Optional[bool] = None
    decline_reason: Optional[str] = None


@router.post("/invite")
async def record_invite(body: InviteBody,
                        user: dict = Depends(get_current_user)):
    """Registra um convite manual feito por humano.

    Bloqueia se DNC universo_ligo está marcado para o documento.
    """
    _require_admin(user)
    if body.channel not in VALID_CHANNELS:
        raise HTTPException(400, f"channel deve ser um de {VALID_CHANNELS}")

    invite = await db.universo_ligo_invites.find_one(
        {"document": body.document, "invite_source": {"$ne": None}}
    )
    if not invite:
        raise HTTPException(
            404,
            "Documento ainda não validado — chame /validate primeiro"
        )
    if invite.get("decision") != "APTO":
        raise HTTPException(
            422,
            f"Documento não está APTO (decision={invite.get('decision')})"
        )
    # DNC universo_ligo é checado em DOIS lugares (fonte primária = subscribers):
    if invite.get("do_not_contact_universo_ligo"):
        raise HTTPException(
            422,
            "Documento marcado como Do Not Contact — convite proibido"
        )
    sub = await db.subscribers.find_one(
        {"document": body.document},
        {"do_not_contact_universo_ligo": 1, "do_not_contact_all": 1}
    )
    if sub and (sub.get("do_not_contact_universo_ligo") or
                sub.get("do_not_contact_all")):
        raise HTTPException(
            422,
            "Subscriber marcado como Do Not Contact — convite proibido"
        )

    now = _now()
    actor = _actor(user)
    update: Dict[str, Any] = {
        "invited_at": now,
        "invited_by": actor,
        "channel": body.channel,
        "updated_at": now,
    }
    if body.accepted:
        update["accepted_at"] = now
        update["status"] = "accepted"
    elif body.declined:
        update["declined_at"] = now
        update["decline_reason"] = (body.decline_reason or "").strip()
        update["status"] = "declined"
    else:
        update["status"] = "invited_pending"

    notes_push = None
    if body.notes:
        notes_push = {"at": now, "by": actor, "text": body.notes.strip()}

    op: Dict[str, Any] = {"$set": update}
    if notes_push:
        op["$push"] = {"notes": notes_push}

    await db.universo_ligo_invites.update_one({"_id": invite["_id"]}, op)
    log.info(
        f"[curadoria] invite doc={body.document} channel={body.channel} "
        f"by={actor} status={update['status']}"
    )
    return {"ok": True, "status": update["status"]}


# --------------------------------------------------------------------- DNC
class DncBody(BaseModel):
    document: str
    reason: str = Field(..., min_length=3)


@router.post("/dnc")
async def set_dnc(body: DncBody, user: dict = Depends(get_current_user)):
    """Marca DNC universo_ligo PERMANENTE.

    Registra no `universo_ligo_invites` E no `subscribers` (flag global).
    """
    _require_admin(user)
    actor = _actor(user)
    now = _now()

    sub = await db.subscribers.find_one({"document": body.document})
    if not sub:
        # mesmo assim registra DNC no invites
        await db.universo_ligo_invites.update_one(
            {"document": body.document},
            {"$set": {
                "do_not_contact_universo_ligo": True,
                "do_not_contact_at": now,
                "do_not_contact_reason": body.reason.strip(),
                "do_not_contact_by": actor,
                "status": "do_not_contact",
                "updated_at": now,
            }},
            upsert=True,
        )
        return {"ok": True, "warning": "subscriber não encontrado, DNC registrado mesmo assim"}

    # 1. subscribers — flag global
    await db.subscribers.update_one(
        {"_id": sub["_id"]},
        {"$set": {
            "do_not_contact_universo_ligo": True,
            "do_not_contact_universo_ligo_at": now,
            "do_not_contact_universo_ligo_reason": body.reason.strip(),
            "do_not_contact_universo_ligo_by": actor,
        }}
    )
    # 2. universo_ligo_invites — registro auditável (propaga em TODOS os
    # docs do documento, não apenas no de um invite_source específico)
    await db.universo_ligo_invites.update_many(
        {"document": body.document},
        {"$set": {
            "subscriber_id": sub.get("id"),
            "do_not_contact_universo_ligo": True,
            "do_not_contact_at": now,
            "do_not_contact_reason": body.reason.strip(),
            "do_not_contact_by": actor,
            "updated_at": now,
        }}
    )
    # Garante pelo menos 1 doc com flag (upsert se nenhum existia)
    existing = await db.universo_ligo_invites.find_one({"document": body.document})
    if not existing:
        await db.universo_ligo_invites.insert_one({
            "id": f"uli-{uuid.uuid4().hex[:12]}",
            "subscriber_id": sub.get("id"),
            "company_id": sub.get("company_id") or "co-demo",
            "document": body.document,
            "invite_source": "manual",
            "do_not_contact_universo_ligo": True,
            "do_not_contact_at": now,
            "do_not_contact_reason": body.reason.strip(),
            "do_not_contact_by": actor,
            "status": "do_not_contact",
            "created_at": now,
            "updated_at": now,
        })
    log.warning(
        f"[curadoria] DNC SET doc={body.document} by={actor} "
        f"reason={body.reason[:50]}"
    )
    return {"ok": True, "subscriber_id": sub.get("id")}


# --------------------------------------------------------------------- LIST
@router.get("/invites")
async def list_invites(status: Optional[str] = None,
                       invite_source: Optional[str] = None,
                       user: dict = Depends(get_current_user)):
    _require_admin(user)
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if invite_source:
        q["invite_source"] = invite_source
    items = []
    async for it in db.universo_ligo_invites.find(q, {"_id": 0}).sort(
            "updated_at", -1).limit(500):
        # mascarar CPF
        d = it.get("document") or ""
        it["document_masked"] = ("***" + d[-4:]) if d else "—"
        items.append(it)
    return {"items": items, "total": len(items)}


# --------------------------------------------------------------------- NPS MVP
class NpsBody(BaseModel):
    subscriber_id: Optional[str] = None
    document: Optional[str] = None
    phone: Optional[str] = None
    score: int = Field(..., ge=0, le=10)
    comment: Optional[str] = None
    source: str = "manual"  # manual | whatsapp | portal | call


@router.post("/nps")
async def submit_nps(body: NpsBody, user: dict = Depends(get_current_user)):
    """Coleta NPS mínimo viável: 1 pergunta, 1 resposta (0-10) + comentário opcional."""
    await _ensure_indexes()
    actor = _actor(user)
    now = _now()

    # resolver subscriber
    sub = None
    if body.subscriber_id:
        sub = await db.subscribers.find_one({"id": body.subscriber_id})
    elif body.document:
        sub = await db.subscribers.find_one({"document": body.document})
    elif body.phone:
        sub = await db.subscribers.find_one({"phone": body.phone})

    payload = {
        "id": f"nps-{uuid.uuid4().hex[:12]}",
        "subscriber_id": (sub.get("id") if sub else body.subscriber_id),
        "company_id": (sub.get("company_id") if sub else "co-demo"),
        "document": (sub.get("document") if sub else body.document),
        "score": body.score,
        "comment": (body.comment or "").strip() or None,
        "source": body.source,
        "submitted_by": actor,
        "created_at": now,
        "category": ("promoter" if body.score >= 9 else
                     "passive" if body.score >= 7 else "detractor"),
    }
    await db.nps_responses_mvp.insert_one(payload)
    log.info(
        f"[curadoria] NPS score={body.score} category={payload['category']} "
        f"sub={payload['subscriber_id']}"
    )
    return {"ok": True, "id": payload["id"], "category": payload["category"]}


@router.get("/nps/stats")
async def nps_stats(user: dict = Depends(get_current_user)):
    """Estatísticas básicas (apenas admin). Sem dashboard ainda — só números crus."""
    _require_admin(user)
    company_id = user.get("company_id") or "co-demo"
    total = await db.nps_responses_mvp.count_documents(
        {"company_id": company_id}
    )
    promoters = await db.nps_responses_mvp.count_documents(
        {"company_id": company_id, "category": "promoter"}
    )
    passives = await db.nps_responses_mvp.count_documents(
        {"company_id": company_id, "category": "passive"}
    )
    detractors = await db.nps_responses_mvp.count_documents(
        {"company_id": company_id, "category": "detractor"}
    )
    nps_score = None
    if total > 0:
        nps_score = round(
            ((promoters / total) - (detractors / total)) * 100, 1
        )
    return {
        "company_id": company_id,
        "total_responses": total,
        "promoters": promoters,
        "passives": passives,
        "detractors": detractors,
        "nps_score": nps_score,
        "confidence": ("baixa" if total < 30 else
                       "media" if total < 100 else "alta"),
    }


# --------------------------------------------------------------- GUARD STATUS
@router.get("/guard/log")
async def guard_log(limit: int = 50, user: dict = Depends(get_current_user)):
    """Lista classificações do synthetic_tenant_guard."""
    _require_admin(user)
    items = []
    async for it in db.synthetic_tenant_guard_log.find(
        {}, {"_id": 0}
    ).sort("scanned_at", -1).limit(min(limit, 500)):
        items.append(it)
    return {"items": items, "total": len(items)}


# --------------------------------------------------------------- DNC helper
async def should_contact_subscriber(subscriber_id: str,
                                    *, scope: str = "universo_ligo") -> bool:
    """Helper global: chame antes de qualquer comunicação ao cliente.

    scope='universo_ligo' bloqueia se DNC universo_ligo.
    scope='*' bloqueia em qualquer flag de DNC.
    """
    sub = await db.subscribers.find_one(
        {"id": subscriber_id},
        {"do_not_contact_universo_ligo": 1, "do_not_contact_all": 1}
    )
    if not sub:
        return True
    if sub.get("do_not_contact_all"):
        return False
    if scope == "universo_ligo" and sub.get("do_not_contact_universo_ligo"):
        return False
    return True
