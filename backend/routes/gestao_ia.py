"""Routes para GESTAO_IA — análise estratégica de KPIs operacionais."""
from __future__ import annotations

from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db
from services.gestao_ai import (
    generate_competitive_analysis,
    generate_gestao_report,
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
