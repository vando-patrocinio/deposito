"""Onda C P2 — Endpoint Watchtower Patrimônio Consolidado.

GET /api/watchtower/estoque/patrimonio-consolidado

Pacote READ-ONLY que responde 5 perguntas em <30s para o CEO/gestor.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from core import DEMO_COMPANY_ID, require_role
from services.patrimonio_consolidado import compute_patrimonio_consolidado

router = APIRouter(tags=["watchtower_patrimonio_consolidado"])


@router.get("/api/watchtower/estoque/patrimonio-consolidado")
async def patrimonio_consolidado(
    user: dict = Depends(require_role("gestor", "administrador", "auditor")),
) -> Dict[str, Any]:
    """Responde:
    P1) Quanto patrimônio existe?           → `ativos`, `consumiveis_qty`
    P2) Quanto vale?                          → `valor`
    P3) Quanto é auditável?                   → `patrimonio_confiavel`
    P4) Onde está?                            → `ativos.by_location_raw`
    P5) O que não consigo rastrear?           → `rastreabilidade.worst_assets`
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await compute_patrimonio_consolidado(cid)
