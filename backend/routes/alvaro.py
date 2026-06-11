"""API ALVARO IA — análise de conversas WhatsApp + relatórios consolidados."""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from core import DEMO_COMPANY_ID, require_role
from database import db
from services.alvaro_ai import run_daily_analysis

logger = logging.getLogger("alvaro_ai.route")
router = APIRouter(prefix="/api/alvaro", tags=["alvaro-ia"])


@router.post("/run-daily")
async def run_daily(
    background: BackgroundTasks,
    hours_back: int = Query(24, ge=1, le=168),
    sync: bool = Query(False, description="Se true, espera terminar e retorna o report. Se false, roda em background"),
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Dispara análise das últimas N horas (default 24h).

    Por padrão roda em background (retorna imediatamente). Use sync=true em
    testes ou pra ver o resultado na hora (pode demorar muito).
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if sync:
        result = await run_daily_analysis(cid, hours_back)
        return result

    async def _bg():
        try:
            await run_daily_analysis(cid, hours_back)
        except Exception as e:
            logger.exception("[alvaro] background run failed: %s", e)

    background.add_task(_bg)
    return {
        "ok": True,
        "message": (
            f"Análise das últimas {hours_back}h disparada em background. "
            f"Acompanhe via GET /api/alvaro/reports/latest"
        ),
    }


@router.get("/reports/latest")
async def get_latest_report(
    user: dict = Depends(require_role("administrador", "gestor", "financeiro")),
):
    """Retorna o último relatório consolidado gerado."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.alvaro_reports.find_one(
        {"company_id": cid}, {"_id": 0},
        sort=[("finished_at", -1)],
    )
    if not doc:
        return {"report": None, "message": "Nenhum relatório gerado ainda."}
    return doc


@router.get("/reports")
async def list_reports(
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(require_role("administrador", "gestor", "financeiro")),
):
    """Lista relatórios consolidados anteriores (sem o payload completo)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cur = db.alvaro_reports.find(
        {"company_id": cid},
        {
            "_id": 0,
            "id": 1, "run_id": 1, "period_hours": 1,
            "started_at": 1, "finished_at": 1,
            "phones_processed": 1, "analyses_ok": 1, "analyses_failed": 1,
            "report.total_conversas": 1,
            "report.media_geral_notas": 1,
            "report.total_risco_cancelamento": 1,
        },
    ).sort("finished_at", -1).limit(limit)
    items = [d async for d in cur]
    return {"items": items, "total": len(items)}


@router.get("/reports/{report_id}")
async def get_report(
    report_id: str,
    user: dict = Depends(require_role("administrador", "gestor", "financeiro")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.alvaro_reports.find_one(
        {"company_id": cid, "id": report_id}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Relatório não encontrado")
    return doc


@router.get("/analyses")
async def list_analyses(
    run_id: Optional[str] = None,
    phone: Optional[str] = None,
    risco: Optional[str] = Query(None, description="baixo|medio|alto|critico"),
    limit: int = Query(50, ge=1, le=500),
    user: dict = Depends(require_role("administrador", "gestor", "financeiro")),
):
    """Lista análises individuais (filtros opcionais por run/phone/risco)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if run_id:
        q["run_id"] = run_id
    if phone:
        q["phone"] = phone
    if risco:
        # risco vem do result.analise.risco_cancelamento (texto BR)
        risk_map = {
            "baixo": ["Baixo", "baixo"],
            "medio": ["Médio", "Medio", "medio", "médio"],
            "alto": ["Alto", "alto"],
            "critico": ["Crítico", "Critico", "critico", "crítico"],
        }
        q["result.analise.risco_cancelamento"] = {"$in": risk_map.get(risco, [risco])}
    cur = db.alvaro_analyses.find(q, {"_id": 0}).sort("analyzed_at", -1).limit(limit)
    items = [d async for d in cur]
    return {"items": items, "total": len(items)}


@router.get("/analyses/{phone}/latest")
async def get_latest_analysis_for_phone(
    phone: str,
    user: dict = Depends(require_role("administrador", "gestor", "financeiro")),
):
    """Última análise individual feita para um telefone específico."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.alvaro_analyses.find_one(
        {"company_id": cid, "phone": phone}, {"_id": 0},
        sort=[("analyzed_at", -1)],
    )
    if not doc:
        raise HTTPException(404, "Nenhuma análise para este telefone")
    return doc
