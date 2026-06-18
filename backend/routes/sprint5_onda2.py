"""sprint5_onda2 — Normalização Owner/Location (CTO ↔ Porta ↔ Subscriber).

Mandato CEO 18/06/2026 — Sprint 5 Onda 2:
- Adiciona campos canônicos em `subscribers`: cto_id, cto_port_id,
  cto_port_number, cto_port_assigned_at, cto_port_source.
- Backfill reverso: para cada `cto_ports` com status=occupied e
  subscriber_id válido, popula os campos canônicos no doc do subscriber.
- Cura órfãos: `cto_ports` que apontam para subscriber inexistente
  → libera porta (status=free, release_reason=audit_2026_orphan_sub).
  NUNCA deleta (Golden Rule).
- 100% idempotente. Audit em `sprint5_audit_log` para cada operação.
- Endpoint dry-run para inspeção sem writes.

Endpoints (prefix /api/sprint5/onda2):
  GET  /preview                      — dry-run, retorna o que SERIA feito
  POST /normalize-owner-location     — executa normalização + audit
  GET  /status                       — métricas atuais de integridade
"""

NERVOUS_METADATA = {
    "owner": "infra-team",
    "domain": "patrimonio",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["sprint5.onda2.normalized"],
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core import require_role
from database import db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sprint5/onda2", tags=["sprint5", "onda2"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_company(user: dict) -> str:
    cid = user.get("company_id")
    if not cid:
        raise HTTPException(400, "Usuário sem company_id")
    return cid


async def _audit(batch_id: str, company_id: str, action: str,
                 target: str, before: Optional[dict],
                 after: Optional[dict], user: dict) -> None:
    """Audit best-effort. Nunca quebra o request."""
    try:
        doc = {
            "id": f"o2a-{uuid.uuid4().hex[:14]}",
            "batch_id": batch_id,
            "company_id": company_id,
            "wave": "sprint5_onda2",
            "action": action,
            "target": target,
            "before": before,
            "after": after,
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "created_at": _now_iso(),
        }
        await db.sprint5_audit_log.insert_one(doc)
    except Exception as e:
        logger.warning("[onda2.audit] falha: %s", e)


async def _compute_plan(company_id: str) -> Dict[str, Any]:
    """Calcula o plano de normalização SEM aplicar nada."""
    # 1) Portas ocupadas com subscriber_id
    occupied_ports = await db.cto_ports.find(
        {"company_id": company_id,
         "status": "occupied",
         "subscriber_id": {"$ne": None}},
        {"_id": 0},
    ).to_list(length=10000)

    valid_links: List[Dict[str, Any]] = []
    orphans: List[Dict[str, Any]] = []

    for port in occupied_ports:
        sub_id = port.get("subscriber_id")
        if not sub_id:
            continue
        sub = await db.subscribers.find_one(
            {"id": sub_id, "company_id": company_id},
            {"_id": 0, "id": 1, "name": 1, "status": 1,
             "cto_id": 1, "cto_port_id": 1, "cto_port_number": 1},
        )
        if not sub:
            orphans.append({
                "cto_port_id": port.get("id"),
                "cto_id": port.get("cto_id"),
                "port_number": port.get("port_number"),
                "missing_subscriber_id": sub_id,
            })
            continue

        already_synced = (
            sub.get("cto_id") == port.get("cto_id")
            and sub.get("cto_port_id") == port.get("id")
            and sub.get("cto_port_number") == port.get("port_number")
        )
        valid_links.append({
            "subscriber_id": sub_id,
            "subscriber_name": sub.get("name"),
            "subscriber_status": sub.get("status"),
            "cto_port_id": port.get("id"),
            "cto_id": port.get("cto_id"),
            "cto_name": port.get("cto_name"),
            "port_number": port.get("port_number"),
            "needs_update": not already_synced,
        })

    return {
        "company_id": company_id,
        "total_occupied_ports": len(occupied_ports),
        "valid_links": valid_links,
        "valid_links_count": len(valid_links),
        "subscribers_to_update": sum(
            1 for v in valid_links if v["needs_update"]),
        "orphans": orphans,
        "orphans_count": len(orphans),
    }


@router.get("/preview")
async def preview(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    """Dry-run: retorna o que seria feito se executasse normalize."""
    cid = _user_company(user)
    plan = await _compute_plan(cid)
    plan["mode"] = "preview"
    plan["computed_at"] = _now_iso()
    return plan


@router.post("/normalize-owner-location")
async def normalize_owner_location(
    dry_run: bool = Query(False, description="Se true, não aplica writes"),
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Executa normalização Owner/Location. Idempotente."""
    cid = _user_company(user)
    batch_id = f"o2b-{uuid.uuid4().hex[:14]}"
    plan = await _compute_plan(cid)

    updates_applied = 0
    orphans_healed = 0

    if not dry_run:
        # Aplica backfill nos subscribers
        for link in plan["valid_links"]:
            if not link["needs_update"]:
                continue
            sub_id = link["subscriber_id"]
            before = await db.subscribers.find_one(
                {"id": sub_id, "company_id": cid},
                {"_id": 0, "cto_id": 1, "cto_port_id": 1,
                 "cto_port_number": 1, "cto_port_assigned_at": 1,
                 "cto_port_source": 1},
            )
            update_fields = {
                "cto_id": link["cto_id"],
                "cto_port_id": link["cto_port_id"],
                "cto_port_number": link["port_number"],
                "cto_port_assigned_at": _now_iso(),
                "cto_port_source": "sprint5_onda2_backfill",
                "owner_normalized_at": _now_iso(),
            }
            res = await db.subscribers.update_one(
                {"id": sub_id, "company_id": cid},
                {"$set": update_fields},
            )
            if res.modified_count:
                updates_applied += 1
                await _audit(
                    batch_id, cid, "subscriber.cto_link_set",
                    f"subscriber/{sub_id}", before, update_fields, user,
                )

        # Cura órfãos: libera porta (não deleta — Golden Rule)
        for o in plan["orphans"]:
            port_id = o["cto_port_id"]
            before = await db.cto_ports.find_one(
                {"id": port_id, "company_id": cid},
                {"_id": 0, "status": 1, "subscriber_id": 1,
                 "subscriber_name": 1, "release_reason": 1},
            )
            new_fields = {
                "status": "free",
                "subscriber_id": None,
                "subscriber_name": None,
                "freed_at": _now_iso(),
                "release_reason": "sprint5_onda2_orphan_subscriber",
                "last_updated_at": _now_iso(),
            }
            res = await db.cto_ports.update_one(
                {"id": port_id, "company_id": cid,
                 "status": "occupied"},
                {"$set": new_fields},
            )
            if res.modified_count:
                orphans_healed += 1
                await _audit(
                    batch_id, cid, "cto_port.orphan_released",
                    f"cto_port/{port_id}", before,
                    {**new_fields,
                     "missing_subscriber_id": o["missing_subscriber_id"]},
                    user,
                )

        # Garante índice em cto_id/cto_port_id (idempotente)
        try:
            await db.subscribers.create_index("cto_id", sparse=True)
            await db.subscribers.create_index("cto_port_id", sparse=True)
        except Exception as e:
            logger.warning("[onda2] index ensure: %s", e)

        # Audit do batch como um todo
        await _audit(
            batch_id, cid, "wave.completed",
            f"sprint5_onda2/{batch_id}",
            None,
            {"updates_applied": updates_applied,
             "orphans_healed": orphans_healed,
             "plan_summary": {
                 "valid_links_count": plan["valid_links_count"],
                 "orphans_count": plan["orphans_count"],
             }},
            user,
        )

    return {
        "batch_id": batch_id,
        "dry_run": dry_run,
        "mode": "preview" if dry_run else "applied",
        "plan": {
            "valid_links_count": plan["valid_links_count"],
            "subscribers_to_update": plan["subscribers_to_update"],
            "orphans_count": plan["orphans_count"],
        },
        "result": {
            "subscribers_updated": updates_applied,
            "orphans_healed": orphans_healed,
        },
        "completed_at": _now_iso(),
    }


@router.get("/status")
async def status(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    """Métricas atuais de integridade Owner/Location."""
    cid = _user_company(user)

    total_active = await db.subscribers.count_documents(
        {"company_id": cid,
         "status": {"$in": ["ATIVO", "ativo", "Ativo", "ACTIVE", "active"]}})
    with_cto = await db.subscribers.count_documents(
        {"company_id": cid,
         "status": {"$in": ["ATIVO", "ativo", "Ativo", "ACTIVE", "active"]},
         "cto_id": {"$exists": True, "$ne": None}})
    with_port = await db.subscribers.count_documents(
        {"company_id": cid,
         "status": {"$in": ["ATIVO", "ativo", "Ativo", "ACTIVE", "active"]},
         "cto_port_id": {"$exists": True, "$ne": None}})

    total_ports = await db.cto_ports.count_documents(
        {"company_id": cid})
    occupied = await db.cto_ports.count_documents(
        {"company_id": cid, "status": "occupied"})
    occupied_with_sub = await db.cto_ports.count_documents(
        {"company_id": cid, "status": "occupied",
         "subscriber_id": {"$ne": None}})

    # Detecta órfãos remanescentes
    orphans = 0
    cursor = db.cto_ports.find(
        {"company_id": cid, "status": "occupied",
         "subscriber_id": {"$ne": None}},
        {"_id": 0, "subscriber_id": 1})
    async for p in cursor:
        sub = await db.subscribers.find_one(
            {"id": p["subscriber_id"], "company_id": cid},
            {"_id": 0, "id": 1})
        if not sub:
            orphans += 1

    coverage = (with_port / total_active * 100.0) if total_active else 0.0

    return {
        "company_id": cid,
        "subscribers_total_active": total_active,
        "subscribers_with_cto_id": with_cto,
        "subscribers_with_cto_port_id": with_port,
        "coverage_owner_location_pct": round(coverage, 2),
        "cto_ports_total": total_ports,
        "cto_ports_occupied": occupied,
        "cto_ports_occupied_with_subscriber": occupied_with_sub,
        "cto_ports_orphan_subscribers": orphans,
        "gate_95pct": coverage >= 95.0,
        "computed_at": _now_iso(),
    }


@router.get("/audit-log")
async def audit_log(
    batch_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    """Histórico de operações da Onda 2."""
    cid = _user_company(user)
    q: Dict[str, Any] = {"company_id": cid, "wave": "sprint5_onda2"}
    if batch_id:
        q["batch_id"] = batch_id
    items = await db.sprint5_audit_log.find(
        q, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(length=limit)
    return {"items": items, "count": len(items)}
