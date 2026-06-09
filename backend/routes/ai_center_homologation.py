"""ai_center_homologation.py — Endpoints REST do Modo Homologação."""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from database import db
from core import require_role
from services import homologation as homo

router = APIRouter(prefix="/api/ai-center/homologation",
                   tags=["homologation"])


def _co(user):
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid:
        raise HTTPException(400, "company_id ausente.")
    return cid


@router.get("/status")
async def get_status(user=Depends(require_role("administrador",
                                               "auditor", "gestor"))):
    return await homo.homologation_status(_co(user))


@router.get("/status/public")
async def get_status_public():
    """Status mínimo (sem auth) para frontend mostrar badge global."""
    return {"homolog_mode_active": homo.is_homolog(),
            "test_phone": homo.TEST_PHONE,
            "homolog_prefix": homo.HOMOLOG_PREFIX}


class TestSendIn(BaseModel):
    target_phone: str = Field(..., min_length=8, max_length=20,
                              description="Telefone real do cliente "
                              "(será SUBSTITUÍDO por TEST_PHONE)")
    message: str = Field(..., min_length=1, max_length=2000)
    origin: str = Field(default="manual_test")
    client_name: Optional[str] = None
    client_phone: Optional[str] = None
    client_document: Optional[str] = None


@router.post("/test-send")
async def test_send(body: TestSendIn,
                    user=Depends(require_role("administrador"))):
    """Envia mensagem via gateway de homologação.

    Se phone ≠ TEST_PHONE, BLOQUEIA e emite evento.
    """
    ctx = {}
    if body.client_name: ctx["name"] = body.client_name
    if body.client_phone: ctx["phone"] = body.client_phone
    if body.client_document: ctx["document"] = body.client_document
    return await homo.safe_send_whatsapp(
        company_id=_co(user),
        target_phone=body.target_phone,
        message=body.message,
        origin=body.origin,
        client_context=ctx,
    )


@router.post("/simulate-pipeline")
async def simulate(scenario: str = Query("default", min_length=1),
                   user=Depends(require_role("administrador"))):
    """Roda pipeline completo Evento→Decisão→Ação→WhatsApp→
    Outcome→Learning em modo homologação."""
    return await homo.simulate_full_pipeline(_co(user),
                                             scenario=scenario)


@router.post("/reconcile")
async def reconcile(user=Depends(require_role("administrador"))):
    return await homo.reconcile_outbox(_co(user))


@router.get("/outbox")
async def list_outbox(
    limit: int = Query(50, ge=1, le=500),
    only_blocked: bool = Query(False),
    user=Depends(require_role("administrador", "auditor", "gestor")),
):
    q = {"company_id": _co(user)}
    if only_blocked:
        q["blocked"] = True
    items = []
    async for d in db.wa_outbox.find(q).sort("queued_at", -1).limit(limit):
        d.pop("_id", None)
        items.append(d)
    return {"items": items, "count": len(items)}


@router.get("/blocked-events")
async def blocked_events(
    limit: int = Query(50, ge=1, le=500),
    user=Depends(require_role("administrador", "auditor", "gestor")),
):
    items = []
    async for d in db.motor_ia_events.find({
        "company_id": _co(user),
        "event_type": "HOMOLOGATION_BLOCKED_REAL_PHONE"
    }).sort("created_at", -1).limit(limit):
        d.pop("_id", None)
        items.append(d)
    return {"items": items, "count": len(items)}


@router.get("/isolation-check")
async def isolation_check(
    window_days: int = Query(30, ge=1, le=365),
    user=Depends(require_role("administrador", "auditor", "gestor")),
):
    """Verifica que outcomes homolog NÃO contaminam métricas de
    produção."""
    return await homo.filter_production_outcomes(
        _co(user), window_days=window_days)
