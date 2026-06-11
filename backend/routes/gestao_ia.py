"""Routes para GESTAO_IA — análise estratégica de KPIs operacionais."""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db
from services.gestao_ai import (
    fire_retention_playbook,
    generate_competitive_analysis,
    generate_gestao_report,
    get_retention_playbook_config,
    RETENTION_DEFAULTS,
)

router = APIRouter(prefix="/api/gestao-ia", tags=["gestao-ia"])


@router.post("/generate")
async def post_generate(user: dict = Depends(require_role("administrador", "gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    report = await generate_gestao_report(company_id)
    # Persiste o último report pra consulta rápida
    await db.gestao_reports.replace_one(
        {"company_id": company_id},
        {**report, "company_id": company_id, "saved_at": now_iso()},
        upsert=True,
    )
    return report


@router.get("/latest")
async def get_latest(user: dict = Depends(require_role("administrador", "gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.gestao_reports.find_one(
        {"company_id": company_id}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Nenhum relatório gerado ainda")
    return doc


class CompetitiveIn(BaseModel):
    market_input: str


@router.post("/competitive-analysis")
async def post_competitive(payload: CompetitiveIn,
                             user: dict = Depends(require_role("administrador", "gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    try:
        result = await generate_competitive_analysis(
            company_id, payload.market_input,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    await db.gestao_competitive.replace_one(
        {"company_id": company_id},
        {**result, "company_id": company_id, "saved_at": now_iso()},
        upsert=True,
    )
    return result


@router.get("/competitive-analysis/latest")
async def get_competitive_latest(user: dict = Depends(require_role("administrador", "gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.gestao_competitive.find_one(
        {"company_id": company_id}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Sem análise competitiva ainda")
    return doc



# -----------------------------------------------------------------------------
# Modo Cliente Cancelando — Playbook de Retenção
# -----------------------------------------------------------------------------
class RetentionConfigIn(BaseModel):
    enabled: bool | None = None
    trigger_risk: str | None = None  # alto | critico
    discount_pct: int | None = None
    visit_window_hours: int | None = None
    auto_send_whatsapp: bool | None = None
    create_urgent_ticket: bool | None = None
    message_template: str | None = None


@router.get("/retention/config")
async def get_retention_config(user: dict = Depends(require_role("administrador", "gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    return await get_retention_playbook_config(company_id)


@router.post("/retention/config")
async def set_retention_config(payload: RetentionConfigIn,
                                  user: dict = Depends(require_role("administrador", "gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    updates = {k: v for k, v in payload.dict().items()
                 if v is not None and k in RETENTION_DEFAULTS}
    if not updates:
        raise HTTPException(400, "Nenhum campo válido enviado")
    if updates.get("trigger_risk") not in (None, "alto", "critico"):
        raise HTTPException(400, "trigger_risk deve ser 'alto' ou 'critico'")
    if "discount_pct" in updates and not (0 <= updates["discount_pct"] <= 100):
        raise HTTPException(400, "discount_pct entre 0 e 100")
    if "visit_window_hours" in updates and not (1 <= updates["visit_window_hours"] <= 168):
        raise HTTPException(400, "visit_window_hours entre 1 e 168")
    await db.retention_playbook.update_one(
        {"company_id": company_id},
        {"$set": {**updates, "company_id": company_id,
                    "updated_at": now_iso()}},
        upsert=True,
    )
    return await get_retention_playbook_config(company_id)


class TriggerIn(BaseModel):
    phone: str
    customer_name: str | None = None
    risk_reason: str | None = ""


@router.post("/retention/trigger")
async def trigger_retention(payload: TriggerIn,
                              user: dict = Depends(require_role("administrador", "gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    return await fire_retention_playbook(
        company_id=company_id, phone=payload.phone,
        customer_name=payload.customer_name,
        risk_reason=payload.risk_reason or "Disparado manualmente pelo gestor",
        source="manual",
    )


@router.get("/retention/mural")
async def list_retention_mural(user: dict = Depends(require_role("administrador", "gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    docs = await db.retention_mural.find(
        {"company_id": company_id}, {"_id": 0},
    ).sort("created_at", -1).limit(50).to_list(50)
    return {"company_id": company_id, "items": docs, "total": len(docs)}


class RetentionStatusIn(BaseModel):
    status: str  # open | in_progress | won | lost


@router.patch("/retention/mural/{rid}")
async def update_retention_status(rid: str, payload: RetentionStatusIn,
                                      user: dict = Depends(require_role("administrador", "gestor"))):
    if payload.status not in ("open", "in_progress", "won", "lost"):
        raise HTTPException(400, "status inválido")
    r = await db.retention_mural.update_one(
        {"id": rid},
        {"$set": {"status": payload.status, "updated_at": now_iso()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Retenção não encontrada")
    doc = await db.retention_mural.find_one({"id": rid}, {"_id": 0})
    return doc
