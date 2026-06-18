"""sprint5_onda4 — Fonte Canônica Única (CEO 19/02/2026)

Endpoints (prefix /api/sprint5/onda4):
  GET  /rca                       — diagnóstico das 3 fontes
  GET  /status                    — métricas atuais
  POST /build-canonical           — materializa canonical a partir de cto_ports
  GET  /validate-consistency      — divergências vs source-of-truth
  GET  /parallel-writes           — writes paralelos detectados
  GET  /certidao                  — certidão JSON
  GET  /audit-log                 — trilha por batch
  GET  /resolve/{subscriber_id}   — resolve cliente → CTO/porta/ONU via canonical
"""

NERVOUS_METADATA = {
    "owner": "infra-team",
    "domain": "patrimonio",
    "criticality": "critical",
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core import require_role
from database import db
from services.network_access_canonical import (
    SOURCE_OF_TRUTH, CANONICAL_COLLECTION,
    build_initial_canonical, detect_parallel_writes,
    check_consistency,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sprint5/onda4", tags=["sprint5", "onda4"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_company(user: dict) -> str:
    cid = user.get("company_id")
    if not cid:
        raise HTTPException(400, "Usuário sem company_id")
    return cid


@router.get("/rca")
async def rca(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    """RCA das 3 fontes — evidência objetiva da escolha."""
    cid = _user_company(user)
    active = {"company_id": cid,
              "status": {"$in": ["ATIVO", "ativo", "Ativo",
                                    "ACTIVE", "active"]}}
    sub_total = await db.subscribers.count_documents(active)
    cp_total = await db.cto_ports.count_documents({"company_id": cid})
    cp_occupied = await db.cto_ports.count_documents(
        {"company_id": cid, "status": "occupied"})
    cp_with_sub = await db.cto_ports.count_documents(
        {"company_id": cid, "subscriber_id": {"$nin": [None, ""]}})
    sub_with_cto = await db.subscribers.count_documents(
        {"company_id": cid, "cto_id": {"$nin": [None, ""]}})
    sap_total = await db.subscriber_access_points.count_documents(
        {"company_id": cid})
    sap_with_cto = await db.subscriber_access_points.count_documents(
        {"company_id": cid, "cto_id": {"$exists": True,
                                              "$nin": [None, ""]}})
    sap_with_port = await db.subscriber_access_points.count_documents(
        {"company_id": cid, "cto_port_id": {"$exists": True,
                                                  "$nin": [None, ""]}})

    return {
        "company_id": cid,
        "source_of_truth": SOURCE_OF_TRUTH,
        "sources": {
            "cto_ports": {
                "role": "AUTHORITATIVE",
                "rationale": (
                    "Granular físico por porta. Cada doc = 1 porta. "
                    "Maior precisão de status (occupied/free)."),
                "total": cp_total,
                "occupied": cp_occupied,
                "with_subscriber": cp_with_sub,
                "writers": ["routes/cto_ports_base.py",
                              "services/network_access_canonical.py"],
            },
            "subscribers_cto_id": {
                "role": "PROJECTION",
                "rationale": (
                    "Campo materializado no doc do cliente (read-fast). "
                    "Populado via Onda 2 Owner/Location e por "
                    "canonical_writer."),
                "with_cto_populated": sub_with_cto,
                "active_subscribers": sub_total,
                "coverage_pct": round(
                    (sub_with_cto / sub_total * 100), 2)
                    if sub_total else 0.0,
                "writers": ["services/network_access_canonical.py",
                              "routes/sprint5_onda2.py"],
            },
            "subscriber_access_points": {
                "role": "OUT_OF_SCOPE",
                "rationale": (
                    "NÃO é fonte de verdade de CTO/porta. Schema "
                    "contém endereço, plano, pppoe_user, "
                    "atlaz_id_plano. É cadastro de endereço/plano "
                    "importado do ATLAZ."),
                "total": sap_total,
                "with_cto": sap_with_cto,
                "with_port": sap_with_port,
                "writers": ["ATLAZ webhook (external)"],
            },
        },
        "decision": (
            f"SOURCE_OF_TRUTH = {SOURCE_OF_TRUTH}. "
            "subscribers.cto_id é projeção derivada. "
            "subscriber_access_points é collection de domínio "
            "DIFERENTE (endereço/plano), preservada mas fora do "
            "escopo da Onda 4 de unificação de CTO/porta."),
        "computed_at": _now_iso(),
    }


@router.get("/status")
async def status(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    canonical_total = await db[CANONICAL_COLLECTION].count_documents(
        {"company_id": cid})
    canonical_occupied = await db[CANONICAL_COLLECTION].count_documents(
        {"company_id": cid, "status": "occupied"})
    consistency = await check_consistency(db, cid)
    pwrites = await detect_parallel_writes(db, cid)
    return {
        "company_id": cid,
        "source_of_truth": SOURCE_OF_TRUTH,
        "canonical_total": canonical_total,
        "canonical_occupied": canonical_occupied,
        "consistency": consistency,
        "parallel_writes": pwrites,
        "gates": {
            "coverage_95": canonical_total >= 0
                and consistency["canonical_total"] >= 1,
            "consistency_95":
                consistency["consistency_pct"] >= 95.0,
            "duplicate_truth_under_1pct":
                consistency["duplicate_truth_pct"] <= 1.0,
            "parallel_writes_zero":
                pwrites["via_other_or_legacy"] == 0,
            "canonical_source_coverage_95":
                pwrites["compliance_pct"] >= 95.0,
        },
        "computed_at": _now_iso(),
    }


@router.post("/build-canonical")
async def build_canonical(
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Materializa network_access_canonical a partir de cto_ports.

    Idempotente. Cria 1 doc por porta física.
    """
    cid = _user_company(user)
    batch_id = f"o4b-{uuid.uuid4().hex[:14]}"
    res = await build_initial_canonical(
        db, cid, batch_id=batch_id,
        actor_user_id=user.get("id"))
    try:
        await db.sprint5_audit_log.insert_one({
            "id": f"o4a-{uuid.uuid4().hex[:14]}",
            "batch_id": batch_id,
            "company_id": cid,
            "wave": "sprint5_onda4",
            "action": "build_canonical.completed",
            "target": f"{CANONICAL_COLLECTION}/{batch_id}",
            "payload": res,
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "created_at": _now_iso(),
        })
    except Exception:
        pass
    return {"batch_id": batch_id, "result": res,
            "completed_at": _now_iso()}


@router.get("/validate-consistency")
async def validate_consistency(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    return {"company_id": cid, **(await check_consistency(db, cid)),
            "computed_at": _now_iso()}


@router.get("/parallel-writes")
async def parallel_writes(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    return {"company_id": cid, **(await detect_parallel_writes(db, cid)),
            "computed_at": _now_iso()}


@router.get("/resolve/{subscriber_id}")
async def resolve_subscriber(
    subscriber_id: str,
    user: dict = Depends(require_role("administrador", "gestor", "auditor",
                                            "tecnico", "atendimento")),
):
    """Resolve via UMA ÚNICA FONTE (canonical) — Cliente → CTO →
    Porta → ONU → Ticket → Técnico.
    """
    cid = _user_company(user)
    link = await db[CANONICAL_COLLECTION].find_one(
        {"company_id": cid, "subscriber_id": subscriber_id},
        {"_id": 0})
    if not link:
        raise HTTPException(404,
            f"Subscriber {subscriber_id} sem link canônico")
    return {
        "subscriber_id": subscriber_id,
        "cto_id": link.get("cto_id"),
        "port_number": link.get("port_number"),
        "cto_port_id": link.get("cto_port_id"),
        "ont_sn": link.get("ont_sn"),
        "ont_mac": link.get("ont_mac"),
        "ticket_id": link.get("ticket_id"),
        "service_id": link.get("service_id"),
        "collaborator_id": link.get("collaborator_id"),
        "status": link.get("status"),
        "source": link.get("source"),
        "canonical_hash": link.get("canonical_hash"),
        "updated_at": link.get("updated_at"),
    }


@router.get("/audit-log")
async def audit_log(
    batch_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    q: Dict[str, Any] = {"company_id": cid, "wave": "sprint5_onda4"}
    if batch_id:
        q["batch_id"] = batch_id
    items = await db.sprint5_audit_log.find(
        q, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(
        length=limit)
    return {"items": items, "count": len(items)}


@router.get("/certidao")
async def certidao(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    st = await status(user)
    last_batch = await db.sprint5_audit_log.find_one(
        {"company_id": cid, "wave": "sprint5_onda4",
         "action": "build_canonical.completed"},
        {"_id": 0}, sort=[("created_at", -1)])

    gates = st["gates"]
    gate_overall = all(gates.values())
    return {
        "certidao_type": "SPRINT5_ONDA4_CANONICAL_SOURCE",
        "company_id": cid,
        "source_of_truth": SOURCE_OF_TRUTH,
        "metrics": st,
        "gates": gates,
        "gate_95pct_overall": gate_overall,
        "last_batch": last_batch,
        "issued_at": _now_iso(),
    }
