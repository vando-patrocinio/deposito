"""Routes para GESTAO_IA — análise estratégica de KPIs operacionais."""
from __future__ import annotations

from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db
from services.gestao_ai import generate_gestao_report

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
