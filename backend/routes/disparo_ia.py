"""DISPARO IA — REST endpoints.

- POST /api/disparo-ia/generate-suggestions  → chama Claude e gera sugestões
- GET  /api/disparo-ia/suggestions            → lista (filtros: status, type)
- GET  /api/disparo-ia/suggestions/{id}       → detalhe
- POST /api/disparo-ia/suggestions/{id}/approve → vira mass_campaign
- POST /api/disparo-ia/suggestions/{id}/reject
- POST /api/disparo-ia/suggestions/{id}/regenerate-message
- GET  /api/disparo-ia/kpis                   → dashboard agregado
- GET  /api/disparo-ia/campaigns              → campanhas Disparo IA (mass_campaigns origin=disparo_ia)
- GET  /api/disparo-ia/types                  → catálogo dos 6 tipos
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db
from services.disparo_ai import (
    CAMPAIGN_TYPE_IDS,
    CAMPAIGN_TYPES,
    compute_kpis,
    generate_campaign_suggestions,
)

logger = logging.getLogger("ponto.disparo_ia")
router = APIRouter(prefix="/api/disparo-ia", tags=["disparo-ia"])


PHONE_RE = re.compile(r"\D+")


def _normalize_phone(p: str) -> Optional[str]:
    if not p:
        return None
    digits = PHONE_RE.sub("", str(p))
    if not digits:
        return None
    if not digits.startswith("55") and len(digits) in (10, 11):
        digits = "55" + digits
    if len(digits) < 12 or len(digits) > 15:
        return None
    return digits


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class GenerateIn(BaseModel):
    types: Optional[List[str]] = None
    max_suggestions: int = Field(default=6, ge=1, le=10)


class ApproveIn(BaseModel):
    channel: str = Field(default="meta_cloud", pattern="^(meta_cloud|twilio)$")
    schedule_at: Optional[str] = None
    throttle_per_min: int = Field(default=60, ge=1, le=600)
    edited_message: Optional[str] = None
    edited_briefing: Optional[str] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------
@router.get("/types")
async def list_types(user: dict = Depends(require_role("administrador", "gestor"))):
    return {"items": CAMPAIGN_TYPES}


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------
@router.post("/generate-suggestions")
async def generate_suggestions(payload: GenerateIn = GenerateIn(),
                                  user: dict = Depends(require_role(
                                      "administrador", "gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    types_filter = payload.types or None
    if types_filter:
        invalid = [t for t in types_filter if t not in CAMPAIGN_TYPE_IDS]
        if invalid:
            raise HTTPException(400,
                                  f"Tipos inválidos: {invalid}. "
                                  f"Use {sorted(CAMPAIGN_TYPE_IDS)}")
    try:
        result = await generate_campaign_suggestions(
            cid, types_filter=types_filter,
            max_suggestions=payload.max_suggestions,
        )
        return result
    except Exception as e:
        logger.exception("[disparo] generate falhou: %s", e)
        raise HTTPException(502, f"Disparo IA falhou: {e}") from e


# ---------------------------------------------------------------------------
# List / Detail
# ---------------------------------------------------------------------------
@router.get("/suggestions")
async def list_suggestions(
    status: Optional[str] = Query(default=None),
    type_id: Optional[str] = Query(default=None, alias="type"),
    limit: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(require_role("administrador", "gestor")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if status:
        q["status"] = status
    if type_id:
        q["type"] = type_id
    cur = db.disparo_suggestions.find(q, {"_id": 0}) \
        .sort("created_at", -1).limit(limit)
    items = [d async for d in cur]
    return {"items": items, "total": len(items)}


@router.get("/suggestions/{suggestion_id}")
async def get_suggestion(suggestion_id: str,
                          user: dict = Depends(require_role(
                              "administrador", "gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.disparo_suggestions.find_one(
        {"id": suggestion_id, "company_id": cid}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Sugestão não encontrada")
    return doc


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------
@router.post("/suggestions/{suggestion_id}/reject")
async def reject_suggestion(suggestion_id: str,
                              user: dict = Depends(require_role(
                                  "administrador", "gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    res = await db.disparo_suggestions.update_one(
        {"id": suggestion_id, "company_id": cid, "status": "pending"},
        {"$set": {"status": "rejected",
                  "rejected_at": now_iso(),
                  "rejected_by": user.get("email") or user.get("id")}},
    )
    if res.matched_count == 0:
        raise HTTPException(404,
                              "Sugestão não encontrada ou já processada")
    return {"ok": True, "status": "rejected"}


# ---------------------------------------------------------------------------
# Approve → cria mass_campaign + recipients
# ---------------------------------------------------------------------------
@router.post("/suggestions/{suggestion_id}/approve")
async def approve_suggestion(suggestion_id: str,
                                payload: ApproveIn,
                                user: dict = Depends(require_role(
                                    "administrador", "gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    sug = await db.disparo_suggestions.find_one(
        {"id": suggestion_id, "company_id": cid}, {"_id": 0},
    )
    if not sug:
        raise HTTPException(404, "Sugestão não encontrada")
    if sug.get("status") != "pending":
        raise HTTPException(400,
                              f"Sugestão já está em status='{sug.get('status')}'")

    # Resolve audiência REAL (não a preview) usando os filtros salvos
    from services.disparo_ai import _resolve_audience
    audience = await _resolve_audience(cid, sug.get("audience") or {})
    audience_size = audience.get("size", 0)
    if audience_size <= 0:
        raise HTTPException(400, "Audiência vazia — nenhum cliente "
                              "casou com os filtros. Revise a sugestão.")

    # Cria mass_campaign
    message_text = (payload.edited_message
                     or sug.get("message_template") or "").strip()
    briefing = payload.edited_briefing or sug.get("isabella_briefing") or ""
    if not message_text:
        raise HTTPException(400, "Mensagem vazia. Edite antes de aprovar.")

    camp_id = f"camp-{uuid.uuid4().hex[:10]}"
    campaign_doc = {
        "id": camp_id,
        "company_id": cid,
        "name": sug.get("title") or "Disparo IA",
        "channel": payload.channel,
        "mode": "free",
        "text": message_text,
        "template_name": None,
        "template_language": "pt_BR",
        "template_components": None,
        "schedule_at": payload.schedule_at,
        "throttle_per_min": payload.throttle_per_min,
        "status": "draft",
        "total_recipients": 0,
        "sent": 0, "delivered": 0, "failed": 0,
        "created_at": now_iso(),
        "created_by": user.get("email"),
        "started_at": None, "finished_at": None,
        # Marcadores do Disparo IA
        "origin": "disparo_ia",
        "disparo_suggestion_id": suggestion_id,
        "disparo_type": sug.get("type"),
        "disparo_run_id": sug.get("run_id"),
        "isabella_briefing": briefing,
        "expected_kpis": sug.get("expected_kpis") or {},
        "approval_notes": payload.notes,
    }
    await db.mass_campaigns.insert_one(campaign_doc)

    # Insere recipients reais (refaz a query pra pegar a lista completa)
    filters = (sug.get("audience") or {}).get("filters") or {}
    # Reaproveita lógica: chama _resolve_audience mas precisamos lista completa.
    # Fazemos a query crua aqui pra eficiência:
    sub_q: Dict[str, Any] = {"company_id": cid}
    if filters.get("plan_contains"):
        sub_q["plan_name"] = {"$regex": re.escape(filters["plan_contains"]),
                                "$options": "i"}
    if filters.get("bairro_in"):
        sub_q["$or"] = [
            {"address": {"$regex": re.escape(b), "$options": "i"}}
            for b in filters["bairro_in"]
        ]
    if filters.get("status"):
        sub_q["status"] = filters["status"]

    riscos = filters.get("risco_cancelamento") or []
    since_days = filters.get("since_days") or 0
    phones_filter: Optional[set] = None
    if riscos or since_days:
        from datetime import timedelta
        riscos_lower = [r.lower().replace("í", "i").replace("ç", "c")
                          for r in riscos]
        q: Dict[str, Any] = {"company_id": cid}
        if since_days:
            q["analyzed_at"] = {"$gte": (datetime.now(timezone.utc)
                                          - timedelta(days=since_days)).isoformat()}
        cur = db.alvaro_analyses.find(q, {
            "_id": 0, "phone": 1,
            "result.analise.risco_cancelamento": 1,
        })
        phones_filter = set()
        async for d in cur:
            risk = (d.get("result", {}).get("analise", {})
                     .get("risco_cancelamento", "")
                     .lower().replace("í", "i").replace("ç", "c"))
            if not riscos_lower or risk in riscos_lower:
                phones_filter.add(d.get("phone"))

    sub_cur = db.subscribers.find(sub_q, {
        "_id": 0, "phone": 1, "name": 1, "plan_name": 1, "address": 1,
        "external_code": 1,
    }).limit(50000)

    seen_phones: set = set()
    bulk: List[Dict[str, Any]] = []
    async for s in sub_cur:
        ph = _normalize_phone(s.get("phone") or "")
        if not ph or ph in seen_phones:
            continue
        if phones_filter is not None and ph not in phones_filter:
            continue
        seen_phones.add(ph)
        bulk.append({
            "id": f"rec-{uuid.uuid4().hex[:10]}",
            "campaign_id": camp_id,
            "company_id": cid,
            "phone": ph,
            "name": s.get("name", ""),
            "vars": {
                "nome": (s.get("name") or "").split()[0] if s.get("name") else "",
                "plano": s.get("plan_name") or "",
                "codigo": s.get("external_code") or "",
            },
            "status": "queued",
            "message_id": None, "error": None,
            "queued_at": now_iso(), "sent_at": None,
        })

    # Se phones_filter não casou com nenhum subscriber mas tem phones,
    # adiciona-os crus (sem nome).
    if phones_filter is not None and not bulk:
        for ph in phones_filter:
            ph_n = _normalize_phone(ph)
            if not ph_n or ph_n in seen_phones:
                continue
            seen_phones.add(ph_n)
            bulk.append({
                "id": f"rec-{uuid.uuid4().hex[:10]}",
                "campaign_id": camp_id, "company_id": cid,
                "phone": ph_n, "name": "",
                "vars": {"nome": "cliente"},
                "status": "queued", "message_id": None, "error": None,
                "queued_at": now_iso(), "sent_at": None,
            })

    inserted = 0
    if bulk:
        # Insere em lotes de 500
        for i in range(0, len(bulk), 500):
            chunk = bulk[i:i + 500]
            await db.mass_recipients.insert_many(chunk)
            inserted += len(chunk)

    await db.mass_campaigns.update_one(
        {"id": camp_id, "company_id": cid},
        {"$set": {"total_recipients": inserted, "updated_at": now_iso()}},
    )

    await db.disparo_suggestions.update_one(
        {"id": suggestion_id, "company_id": cid},
        {"$set": {
            "status": "approved",
            "approved_at": now_iso(),
            "approved_by": user.get("email") or user.get("id"),
            "campaign_id": camp_id,
            "approval_notes": payload.notes,
            "approved_audience_size": inserted,
        }},
    )

    logger.info(
        "[disparo] sug=%s aprovada → camp=%s · %d destinatários",
        suggestion_id, camp_id, inserted,
    )

    return {
        "ok": True,
        "campaign_id": camp_id,
        "recipients_inserted": inserted,
        "next_step": (
            f"POST /api/mass-messaging/campaigns/{camp_id}/start "
            "para iniciar o envio."
        ),
    }


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------
@router.get("/kpis")
async def get_kpis(days: int = Query(default=30, ge=1, le=365),
                    user: dict = Depends(require_role(
                        "administrador", "gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await compute_kpis(cid, days=days)


@router.get("/campaigns")
async def list_disparo_campaigns(
    limit: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(require_role("administrador", "gestor")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cur = db.mass_campaigns.find(
        {"company_id": cid, "origin": "disparo_ia"},
        {"_id": 0},
    ).sort("created_at", -1).limit(limit)
    items = [d async for d in cur]
    return {"items": items, "total": len(items)}
