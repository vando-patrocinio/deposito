"""sprint5_onda3 — Validação obrigatória CTO+Porta+ONU (CEO 19/02/2026)

Endpoints (prefix /api/sprint5/onda3):
  GET  /status                — métricas linkage atual + estado enforcement
  GET  /preview-block?ticket_id=... — simula validação sem aplicar
  GET  /enforcement-stats      — bloqueios x liberados pós-Onda-3
  GET  /audit-log              — trilha de validações
  GET  /certidao               — certidão JSON com ANTES x DEPOIS
  POST /manual-override-record — registra audit_source=manual_override
"""

NERVOUS_METADATA = {
    "owner": "infra-team",
    "domain": "patrimonio",
    "criticality": "critical",
    "company_id_required": True,
}

import logging
import os as _os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from core import require_role
from database import db
from services.os_finalization_validator import (
    validate_finalization, is_enforcement_active,
    ENFORCED_SERVICE_TYPES, EXEMPT_SERVICE_TYPES,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sprint5/onda3", tags=["sprint5", "onda3"])

# Marca o início da Onda 3 — usado para calcular gates forward-only
ONDA3_START_AT_ENV = "SPRINT5_ONDA3_START_AT"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_company(user: dict) -> str:
    cid = user.get("company_id")
    if not cid:
        raise HTTPException(400, "Usuário sem company_id")
    return cid


def _onda3_start_at() -> str:
    """Retorna ISO timestamp do início da Onda 3."""
    return _os.environ.get(ONDA3_START_AT_ENV) or "2026-02-19T00:00:00+00:00"


async def _compute_linkage_forward(cid: str) -> Dict[str, Any]:
    """Linkage forward-only sobre swap_events emitidos REAL-TIME (não backfill).

    Apenas eventos criados pelo `auto_close_lousa` pós-enforcement contam.
    Backfill retroativo (created_by='backfill_*') é EXCLUÍDO do gate.
    """
    base = {
        "company_id": cid,
        "created_by": {"$regex": "^auto_close_lousa"},
        "data_quality": {"$nin": ["terminal_source_destroyed",
                                        "no_ticket_in_source"]},
    }
    total = await db.auto_ont_swap_events.count_documents(base)

    def link(f):
        q = dict(base)
        q[f] = {"$exists": True, "$nin": [None, "", 0]}
        return q

    with_cto = await db.auto_ont_swap_events.count_documents(link("cto_id"))
    with_port = await db.auto_ont_swap_events.count_documents(
        {**base, "port_number": {"$exists": True, "$ne": None}})
    with_ont = await db.auto_ont_swap_events.count_documents({
        **base,
        "$or": [{"ont_new_mac": {"$nin": [None, ""]}},
                  {"ont_new_sn": {"$nin": [None, ""]}},
                  {"ont_old_mac": {"$nin": [None, ""]}},
                  {"ont_old_sn": {"$nin": [None, ""]}}],
    })
    with_ticket = await db.auto_ont_swap_events.count_documents(
        link("ticket_id"))
    with_sub = await db.auto_ont_swap_events.count_documents(
        link("subscriber_id"))
    with_collab = await db.auto_ont_swap_events.count_documents(
        link("collaborator_id"))

    def pct(n):
        return round((n / total * 100.0), 2) if total else 0.0

    return {
        "total_forward_swap_events": total,
        "source_filter": "auto_close_lousa (real-time only, no backfill)",
        "cto_linkage_pct": pct(with_cto),
        "port_linkage_pct": pct(with_port),
        "ont_linkage_pct": pct(with_ont),
        "ticket_linkage_pct": pct(with_ticket),
        "subscriber_linkage_pct": pct(with_sub),
        "collaborator_linkage_pct": pct(with_collab),
        "gate_95pct_cto": pct(with_cto) >= 95.0,
        "gate_95pct_port": pct(with_port) >= 95.0,
        "gate_95pct_ont": pct(with_ont) >= 95.0,
        "gate_95pct_ticket": pct(with_ticket) >= 95.0,
        "gate_95pct_subscriber": pct(with_sub) >= 95.0,
    }


async def _enforcement_stats(cid: str) -> Dict[str, Any]:
    base = {"company_id": cid}
    total = await db.sprint5_onda3_validations.count_documents(base)
    ok = await db.sprint5_onda3_validations.count_documents(
        {**base, "ok": True})
    blocked = await db.sprint5_onda3_validations.count_documents(
        {**base, "ok": False})

    # Top motivos de bloqueio
    pipe = [
        {"$match": {**base, "ok": False}},
        {"$unwind": "$diag.missing"},
        {"$group": {"_id": "$diag.missing", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 10},
    ]
    top_blocks = await db.sprint5_onda3_validations.aggregate(
        pipe).to_list(length=20)

    return {
        "total_validations": total,
        "validations_ok": ok,
        "validations_blocked": blocked,
        "block_rate_pct": round((blocked / total * 100.0), 2)
            if total else 0.0,
        "top_block_reasons": [{"field": x["_id"], "count": x["n"]}
                                  for x in top_blocks],
    }


async def _top_ctos_and_techs(cid: str) -> Dict[str, Any]:
    """Top CTOs usadas + top técnicos (sobre swap_events real-time)."""
    base = {"company_id": cid,
            "created_by": {"$regex": "^auto_close_lousa"}}

    top_ctos = await db.auto_ont_swap_events.aggregate([
        {"$match": {**base, "cto_id": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$cto_id", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 10},
    ]).to_list(length=20)

    top_techs = await db.auto_ont_swap_events.aggregate([
        {"$match": {**base, "collaborator_id": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$collaborator_id", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 10},
    ]).to_list(length=20)

    return {
        "top_ctos_used": [{"cto_id": x["_id"], "count": x["n"]}
                              for x in top_ctos],
        "top_technicians": [{"collaborator_id": x["_id"], "count": x["n"]}
                                for x in top_techs],
    }


@router.get("/status")
async def status(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    fwd = await _compute_linkage_forward(cid)
    enf = await _enforcement_stats(cid)
    return {
        "company_id": cid,
        "enforcement_active": is_enforcement_active(),
        "enforced_types": sorted(ENFORCED_SERVICE_TYPES),
        "exempt_types": sorted(EXEMPT_SERVICE_TYPES),
        "forward_linkage": fwd,
        "enforcement_stats": enf,
        "computed_at": _now_iso(),
    }


@router.get("/preview-block")
async def preview_block(
    ticket_id: str = Query(..., description="Ticket a ser simulado"),
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    """Simula a validação para um ticket existente — útil para gestor
    verificar antes da finalização do técnico."""
    cid = _user_company(user)
    tk = await db.tickets.find_one(
        {"company_id": cid, "id": ticket_id}, {"_id": 0})
    if not tk:
        raise HTTPException(404, "Ticket não encontrado")

    svc = await db.stok_services.find_one(
        {"company_id": cid, "ticket_id": ticket_id},
        {"_id": 0, "id": 1, "type": 1, "client_id": 1,
         "technician_id": 1},
    )
    cd = tk.get("completion_data") or {}
    ok, diag = await validate_finalization(
        db,
        company_id=cid,
        service_type=(svc.get("type") if svc else tk.get("type")) or "",
        ticket_id=ticket_id,
        service_id=svc.get("id") if svc else None,
        subscriber_id=tk.get("client_id"),
        collaborator_id=tk.get("assigned_to"),
        completion_data=cd,
    )
    return {"ticket_id": ticket_id, "ok": ok, "diag": diag,
            "evaluated_at": _now_iso()}


@router.get("/enforcement-stats")
async def enforcement_stats(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    return {"company_id": cid, **(await _enforcement_stats(cid)),
            "computed_at": _now_iso()}


@router.get("/audit-log")
async def audit_log(
    only_blocked: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    q: Dict[str, Any] = {"company_id": cid}
    if only_blocked:
        q["ok"] = False
    items = await db.sprint5_onda3_validations.find(
        q, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(
        length=limit)
    return {"items": items, "count": len(items)}


@router.post("/manual-override-record")
async def manual_override_record(
    target_collection: str = Body(..., embed=True),
    target_id: str = Body(..., embed=True),
    reason: str = Body(..., embed=True),
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Registra audit_source=manual_override em alteração posterior
    à finalização via Lousa (CEO regra Onda 3).
    """
    if len(reason.strip()) < 20:
        raise HTTPException(400, "Motivo deve ter ≥20 caracteres")
    cid = _user_company(user)
    doc = {
        "id": f"o3mo-{uuid.uuid4().hex[:14]}",
        "company_id": cid,
        "audit_source": "manual_override",
        "audit_reason": reason,
        "target_collection": target_collection,
        "target_id": target_id,
        "actor_user_id": user.get("id"),
        "actor_email": user.get("email"),
        "created_at": _now_iso(),
    }
    await db.sprint5_audit_log.insert_one({
        **doc, "wave": "sprint5_onda3", "action": "manual_override",
        "target": f"{target_collection}/{target_id}",
        "payload": {"reason": reason},
    })
    return {"ok": True, **doc}


@router.get("/certidao")
async def certidao(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    fwd = await _compute_linkage_forward(cid)
    enf = await _enforcement_stats(cid)
    tops = await _top_ctos_and_techs(cid)

    gates = {
        "cto_linkage_95": fwd["gate_95pct_cto"],
        "port_linkage_95": fwd["gate_95pct_port"],
        "ont_linkage_95": fwd["gate_95pct_ont"],
        "ticket_linkage_95": fwd["gate_95pct_ticket"],
        "subscriber_linkage_95": fwd["gate_95pct_subscriber"],
    }
    # Convenção: zero finalizações pós-Onda-3 → "vacuous_pass" (não há
    # dado ruim entrando, mas gates não podem ser declarados positivos
    # sem amostragem real). gate_overall só TRUE com amostragem.
    has_sample = fwd["total_forward_swap_events"] > 0
    gate_overall = has_sample and all(gates.values())

    return {
        "certidao_type": "SPRINT5_ONDA3_CTO_PORTA_OBRIGATORIOS",
        "company_id": cid,
        "enforcement_active": is_enforcement_active(),
        "metrics_forward": fwd,
        "enforcement_stats": enf,
        "top": tops,
        "gates": gates,
        "has_sample": has_sample,
        "gate_95pct_overall": gate_overall,
        "vacuous_pass_no_sample": (
            not has_sample and is_enforcement_active()),
        "issued_at": _now_iso(),
    }
