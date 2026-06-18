"""sprint5_swap_events — Sprint 5 Onda 2 (CEO mandate 19/02/2026)

Trilha auditável de swap/install/replacement/removal de ONUs.

Endpoints (prefix /api/sprint5/swap-events):
  GET  /status                — métricas operacionais + gate 95%
  GET  /preview-backfill      — dry-run do backfill retroativo
  POST /backfill-from-history — gera swap_events retroativos
  GET  /metrics-operational   — swaps hoje/mês/confirmados/contestados/pendentes/overdue
  GET  /certidao              — certidão JSON
  GET  /audit-log             — trilha por batch_id
  POST /{event_id}/confirm    — confirmação patrimonial (técnico/auditor)
  POST /{event_id}/dispute    — contestação (técnico/auditor)
"""

NERVOUS_METADATA = {
    "owner": "infra-team",
    "domain": "patrimonio",
    "criticality": "critical",
    "emits_events": True,
    "event_types": ["sprint5.onda2.swap_event"],
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body

from core import require_role
from database import db
from services.swap_event_writer import (
    write_swap_event, capture_smartolt_snapshot,
    CONFIRMATION_STATES,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sprint5/swap-events", tags=["sprint5", "onda2"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_company(user: dict) -> str:
    cid = user.get("company_id")
    if not cid:
        raise HTTPException(400, "Usuário sem company_id")
    return cid


def _map_history_type_to_event_type(htype: str) -> str:
    """Mapeia stok_history.type → swap_event.event_type."""
    m = (htype or "").lower()
    if m in ("instalacao", "install"):
        return "install"
    if m in ("retirada", "removal"):
        return "removal"
    if m in ("troca", "replacement"):
        return "replacement"
    # reparo só vira swap se houve troca de ONU (detectado posteriormente)
    return "swap"


async def _build_status(cid: str) -> Dict[str, Any]:
    total = await db.auto_ont_swap_events.count_documents(
        {"company_id": cid})

    IRRECOVERABLE_QUALITIES = ["terminal_source_destroyed",
                                  "no_ticket_in_source"]
    terminal_total = await db.auto_ont_swap_events.count_documents(
        {"company_id": cid,
         "data_quality": {"$in": IRRECOVERABLE_QUALITIES}})
    eligible = max(total - terminal_total, 0)

    def link_q(field):
        return {"company_id": cid,
                field: {"$exists": True, "$nin": [None, ""]},
                "data_quality": {"$nin": IRRECOVERABLE_QUALITIES}}

    with_ticket = await db.auto_ont_swap_events.count_documents(
        link_q("ticket_id"))
    with_sub = await db.auto_ont_swap_events.count_documents(
        link_q("subscriber_id"))
    with_collab = await db.auto_ont_swap_events.count_documents(
        link_q("collaborator_id"))
    with_cto = await db.auto_ont_swap_events.count_documents(
        link_q("cto_id"))
    with_port = await db.auto_ont_swap_events.count_documents(
        {"company_id": cid,
         "port_number": {"$exists": True, "$ne": None},
         "data_quality": {"$nin": IRRECOVERABLE_QUALITIES}})
    with_history = await db.auto_ont_swap_events.count_documents(
        link_q("stok_history_id"))
    with_smartolt = await db.auto_ont_swap_events.count_documents(
        {"company_id": cid,
         "smartolt_snapshot": {"$exists": True, "$ne": None,
                                  "$nin": [{}, None]},
         "data_quality": {"$nin": IRRECOVERABLE_QUALITIES}})

    by_event = await db.auto_ont_swap_events.aggregate([
        {"$match": {"company_id": cid}},
        {"$group": {"_id": "$event_type", "n": {"$sum": 1}}},
    ]).to_list(length=20)
    by_event_map = {x["_id"]: x["n"] for x in by_event}

    by_conf = await db.auto_ont_swap_events.aggregate([
        {"$match": {"company_id": cid}},
        {"$group": {"_id": "$confirmation_status", "n": {"$sum": 1}}},
    ]).to_list(length=20)
    by_conf_map = {x["_id"]: x["n"] for x in by_conf}

    # Universo esperado: instalações/reparos/retiradas com service_id
    expected = await db.stok_history.count_documents({
        "company_id": cid,
        "service_id": {"$exists": True, "$nin": [None, ""]},
        "event_type": {"$in": ["instalacao", "reparo", "retirada",
                                  "troca"]},
    })

    def pct(n, total_):
        return round((n / total_ * 100.0), 2) if total_ else 0.0

    # Cobertura "vs expected" (sobre tudo)
    coverage_vs_expected = pct(total, expected)
    # Cobertura "linkage" sobre eligible (exclui terminais)

    return {
        "company_id": cid,
        "total_swap_events": total,
        "irrecoverable_total": terminal_total,
        "eligible_for_gate": eligible,
        "by_event_type": by_event_map,
        "by_confirmation_status": by_conf_map,
        "expected_universe_from_history": expected,
        "coverage_vs_expected_pct": coverage_vs_expected,
        "ticket_linkage_pct": pct(with_ticket, eligible),
        "subscriber_linkage_pct": pct(with_sub, eligible),
        "collaborator_linkage_pct": pct(with_collab, eligible),
        "cto_linkage_pct": pct(with_cto, eligible),
        "port_linkage_pct": pct(with_port, eligible),
        "stok_history_linkage_pct": pct(with_history, eligible),
        "smartolt_linkage_pct": pct(with_smartolt, eligible),
        "gate_95pct_coverage": coverage_vs_expected >= 95.0,
        "gate_95pct_ticket": pct(with_ticket, eligible) >= 95.0,
        "gate_95pct_subscriber": pct(with_sub, eligible) >= 95.0,
        "gate_95pct_collaborator": pct(with_collab, eligible) >= 95.0,
        "gate_95pct_stok_history": pct(with_history, eligible) >= 95.0,
        "computed_at": _now_iso(),
    }


async def _resolve_swap_from_history(
    db, cid: str, hist_doc: dict,
) -> Optional[Dict[str, Any]]:
    """Extrai dados de um stok_history para gerar swap_event retroativo.

    Prioriza campos já populados no hist_doc (pós-Onda 1).
    Marca terminal_data_missing quando svc foi removido (irrecuperável).
    """
    service_id = hist_doc.get("service_id")
    ticket_id = hist_doc.get("ticket_id")
    if not service_id and not ticket_id:
        return None

    htype = hist_doc.get("event_type") or hist_doc.get("type") or ""
    event_type = _map_history_type_to_event_type(htype)

    # PRIORIDADE 1: campos já populados pela Onda 1
    subscriber_id = hist_doc.get("subscriber_id")
    collaborator_id = hist_doc.get("collaborator_id")

    # Detecta caso terminal (svc removido — irrecuperável)
    hist_trace = (hist_doc.get("traceability_status") or "").lower()
    terminal_missing = hist_trace == "partial_os_not_found"

    # Enriquece via stok_services (se ainda existe)
    svc = None
    if service_id:
        svc = await db.stok_services.find_one(
            {"company_id": cid, "id": service_id},
            {"_id": 0, "ticket_id": 1, "type": 1, "client_id": 1,
             "technician_id": 1, "auto_closed_ont_mac": 1,
             "ont_sn": 1, "reason": 1},
        )
        if svc:
            ticket_id = ticket_id or svc.get("ticket_id")
            subscriber_id = subscriber_id or svc.get("client_id")
            collaborator_id = collaborator_id or svc.get("technician_id")

    # Enriquece via ticket
    cto_id = None
    port_number = None
    ont_old_mac = None
    ont_new_mac = None
    ont_new_sn = (svc or {}).get("ont_sn") if svc else None
    swap_reason = None
    if ticket_id:
        tk = await db.tickets.find_one(
            {"company_id": cid, "id": ticket_id},
            {"_id": 0, "assigned_to": 1, "client_id": 1,
             "completion_data": 1, "cto_id": 1, "port_number": 1,
             "type": 1, "reason": 1},
        )
        if tk:
            collaborator_id = collaborator_id or tk.get("assigned_to")
            subscriber_id = subscriber_id or tk.get("client_id")
            cd = tk.get("completion_data") or {}
            cto_id = (cd.get("cto_id") or tk.get("cto_id"))
            port_number = (cd.get("port_number") or tk.get("port_number"))
            ont_new_mac = ont_new_mac or cd.get("ont")
            ont_new_sn = ont_new_sn or cd.get("ont_sn")
            swap_reason = swap_reason or cd.get("swap_reason") \
                or tk.get("reason")

    # CTO canônico via subscriber (pós Onda 2 Owner/Location)
    if subscriber_id and (not cto_id or not port_number):
        sub = await db.subscribers.find_one(
            {"id": subscriber_id, "company_id": cid},
            {"_id": 0, "cto_id": 1, "cto_port_number": 1,
             "cto_port_id": 1},
        )
        if sub:
            cto_id = cto_id or sub.get("cto_id")
            port_number = port_number or sub.get("cto_port_number")

    if event_type == "removal":
        ont_old_mac = ont_old_mac or ont_new_mac
        ont_new_mac = None
        ont_new_sn = None

    return {
        "company_id": cid,
        "event_type": event_type,
        "ticket_id": ticket_id,
        "service_id": service_id,
        "subscriber_id": subscriber_id,
        "collaborator_id": collaborator_id,
        "cto_id": cto_id,
        "port_number": port_number,
        "ont_old_sn": None,
        "ont_old_mac": ont_old_mac,
        "ont_new_sn": ont_new_sn,
        "ont_new_mac": ont_new_mac,
        "swap_reason": swap_reason,
        "stok_history_id": hist_doc.get("id"),
        "created_by": "backfill_sprint5_onda2",
        "_terminal_data_missing": terminal_missing,
        # CEO 19/02/2026 — quando o svc existe mas nasceu sem ticket
        # (auto_opened legado), também não conta no gate de ticket.
        "_no_ticket_in_source": bool(svc and not ticket_id),
    }


@router.get("/status")
async def status(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    return await _build_status(_user_company(user))


@router.get("/preview-backfill")
async def preview_backfill(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    # Universo: stok_history com event_type ∈ {instalacao,reparo,retirada,troca}
    # E que ainda NÃO foram convertidos (sem swap_event_id).
    hist = await db.stok_history.find({
        "company_id": cid,
        "event_type": {"$in": ["instalacao", "reparo", "retirada", "troca"]},
        "service_id": {"$exists": True, "$nin": [None, ""]},
        "swap_event_id": {"$in": [None, ""], "$exists": False}
        if False else {"$exists": False},
    }, {"_id": 0}).to_list(length=10000)

    plan_full = 0
    plan_partial = 0
    plan_skip = 0
    by_type: Dict[str, int] = {}
    for h in hist:
        resolved = await _resolve_swap_from_history(db, cid, h)
        if not resolved:
            plan_skip += 1
            continue
        ev = resolved["event_type"]
        by_type[ev] = by_type.get(ev, 0) + 1
        # Estima se ficaria full (todos campos críticos)
        required = {"ticket_id", "service_id", "subscriber_id",
                       "collaborator_id"}
        if ev in ("install", "swap", "replacement"):
            required.update({"cto_id", "port_number"})
            if ev != "install":
                required.add("ont_old_mac")
            required.add("ont_new_mac")
        else:  # removal
            required.add("ont_old_mac")
        have = {k for k in required if resolved.get(k)}
        if have == required:
            plan_full += 1
        else:
            plan_partial += 1

    return {
        "mode": "preview",
        "total_history_candidates": len(hist),
        "plan_full": plan_full,
        "plan_partial": plan_partial,
        "plan_skip": plan_skip,
        "by_event_type_planned": by_type,
        "computed_at": _now_iso(),
    }


@router.post("/backfill-from-history")
async def backfill(
    dry_run: bool = Query(False),
    capture_smartolt: bool = Query(True),
    user: dict = Depends(require_role("administrador", "gestor")),
):
    cid = _user_company(user)
    batch_id = f"o2sb-{uuid.uuid4().hex[:14]}"

    hist = await db.stok_history.find({
        "company_id": cid,
        "event_type": {"$in": ["instalacao", "reparo", "retirada", "troca"]},
        "service_id": {"$exists": True, "$nin": [None, ""]},
        "swap_event_id": {"$exists": False},
    }, {"_id": 0}).to_list(length=10000)

    created_full = 0
    created_partial = 0
    skipped = 0
    by_type: Dict[str, int] = {}

    for h in hist:
        kwargs = await _resolve_swap_from_history(db, cid, h)
        if not kwargs:
            skipped += 1
            continue

        if capture_smartolt and not dry_run:
            kwargs["smartolt_snapshot"] = await capture_smartolt_snapshot(
                db, cid,
                old_id=kwargs.get("ont_old_mac") or kwargs.get("ont_old_sn"),
                new_id=kwargs.get("ont_new_mac") or kwargs.get("ont_new_sn"),
            )

        if dry_run:
            ev = kwargs["event_type"]
            by_type[ev] = by_type.get(ev, 0) + 1
            continue

        try:
            terminal_flag = kwargs.pop("_terminal_data_missing", False)
            no_ticket_flag = kwargs.pop("_no_ticket_in_source", False)
            doc = await write_swap_event(
                db, allow_missing=True,
                **{k: v for k, v in kwargs.items()
                   if k in {"company_id", "event_type", "ticket_id",
                             "service_id", "subscriber_id",
                             "collaborator_id", "cto_id", "port_number",
                             "ont_old_sn", "ont_old_mac", "ont_new_sn",
                             "ont_new_mac", "swap_reason",
                             "stok_history_id", "created_by",
                             "smartolt_snapshot"}})
            ev = doc["event_type"]
            by_type[ev] = by_type.get(ev, 0) + 1
            quality_marker = None
            if terminal_flag:
                quality_marker = "terminal_source_destroyed"
            elif no_ticket_flag:
                quality_marker = "no_ticket_in_source"
            if quality_marker:
                await db.auto_ont_swap_events.update_one(
                    {"event_id": doc["event_id"]},
                    {"$set": {
                        "data_quality": quality_marker,
                        "irrecoverable": True,
                    }},
                )
            if doc.get("traceability_complete"):
                created_full += 1
            else:
                created_partial += 1
        except Exception as e:
            logger.warning(
                "[onda2.backfill] falhou hist=%s: %s", h.get("id"), e)
            skipped += 1

    # Audit batch
    if not dry_run:
        try:
            await db.sprint5_audit_log.insert_one({
                "id": f"o2a-{uuid.uuid4().hex[:14]}",
                "batch_id": batch_id,
                "company_id": cid,
                "wave": "sprint5_onda2_swap",
                "action": "backfill.completed",
                "target": f"auto_ont_swap_events/{batch_id}",
                "payload": {
                    "candidates": len(hist),
                    "created_full": created_full,
                    "created_partial": created_partial,
                    "skipped": skipped,
                    "by_type": by_type,
                },
                "actor_user_id": user.get("id"),
                "actor_email": user.get("email"),
                "created_at": _now_iso(),
            })
        except Exception:
            pass

    return {
        "batch_id": batch_id,
        "dry_run": dry_run,
        "mode": "preview" if dry_run else "applied",
        "candidates": len(hist),
        "created_full": created_full,
        "created_partial": created_partial,
        "skipped": skipped,
        "by_event_type": by_type,
        "completed_at": _now_iso(),
    }


@router.get("/metrics-operational")
async def metrics_operational(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    """Métricas operacionais sem novo dashboard — para consumo de telas
    já existentes (Watchtower / IA Cards).
    """
    cid = _user_company(user)
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    overdue_threshold = (now - timedelta(hours=72)).isoformat()

    def base(q):
        return {"company_id": cid, **q}

    swaps_today = await db.auto_ont_swap_events.count_documents(
        base({"created_at": {"$gte": today_start.isoformat()}}))
    swaps_month = await db.auto_ont_swap_events.count_documents(
        base({"created_at": {"$gte": month_start.isoformat()}}))
    confirmed = await db.auto_ont_swap_events.count_documents(
        base({"confirmation_status": "confirmed"}))
    disputed = await db.auto_ont_swap_events.count_documents(
        base({"confirmation_status": "disputed"}))
    pending = await db.auto_ont_swap_events.count_documents(
        base({"confirmation_status": {"$in": [
            "pending_confirmation", "sent_to_technician", "needs_review"]}}))
    overdue = await db.auto_ont_swap_events.count_documents(
        base({"confirmation_status": {"$in": [
            "pending_confirmation", "sent_to_technician"]},
              "created_at": {"$lt": overdue_threshold}}))

    return {
        "company_id": cid,
        "swaps_today": swaps_today,
        "swaps_month": swaps_month,
        "swaps_confirmed_total": confirmed,
        "swaps_disputed_total": disputed,
        "swaps_pending_total": pending,
        "swaps_overdue_total": overdue,
        "computed_at": _now_iso(),
    }


@router.post("/{event_id}/confirm")
async def confirm(
    event_id: str,
    user: dict = Depends(require_role("administrador", "gestor",
                                            "tecnico", "auditor")),
):
    cid = _user_company(user)
    res = await db.auto_ont_swap_events.update_one(
        {"event_id": event_id, "company_id": cid},
        {"$set": {
            "confirmation_status": "confirmed",
            "confirmation_at": _now_iso(),
            "confirmed_by_user_id": user.get("id"),
            "confirmed_by_email": user.get("email"),
        }},
    )
    if not res.matched_count:
        raise HTTPException(404, "Swap event não encontrado")
    return {"event_id": event_id, "status": "confirmed",
            "confirmed_at": _now_iso()}


@router.post("/{event_id}/dispute")
async def dispute(
    event_id: str,
    motivo: str = Body(..., embed=True),
    user: dict = Depends(require_role("administrador", "gestor",
                                            "tecnico", "auditor")),
):
    cid = _user_company(user)
    if len(motivo.strip()) < 5:
        raise HTTPException(400, "Motivo da contestação muito curto")
    res = await db.auto_ont_swap_events.update_one(
        {"event_id": event_id, "company_id": cid},
        {"$set": {
            "confirmation_status": "disputed",
            "confirmation_at": _now_iso(),
            "dispute_reason": motivo,
            "disputed_by_user_id": user.get("id"),
            "disputed_by_email": user.get("email"),
        }},
    )
    if not res.matched_count:
        raise HTTPException(404, "Swap event não encontrado")
    return {"event_id": event_id, "status": "disputed",
            "disputed_at": _now_iso()}


@router.get("/audit-log")
async def audit_log(
    batch_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    q: Dict[str, Any] = {"company_id": cid, "wave": "sprint5_onda2_swap"}
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
    st = await _build_status(cid)
    ops = await metrics_operational(user)
    last = await db.sprint5_audit_log.find_one(
        {"company_id": cid, "wave": "sprint5_onda2_swap"},
        {"_id": 0}, sort=[("created_at", -1)])

    gates = {
        "coverage_vs_expected": st["gate_95pct_coverage"],
        "ticket_linkage": st["gate_95pct_ticket"],
        "subscriber_linkage": st["gate_95pct_subscriber"],
        "collaborator_linkage": st["gate_95pct_collaborator"],
        "stok_history_linkage": st["gate_95pct_stok_history"],
    }
    gate_overall = all(gates.values())

    return {
        "certidao_type": "SPRINT5_ONDA2_SWAP_EVENTS",
        "company_id": cid,
        "metrics": st,
        "operational": ops,
        "gates": gates,
        "gate_95pct_overall": gate_overall,
        "last_batch": last,
        "confirmation_states_allowed": sorted(CONFIRMATION_STATES),
        "issued_at": _now_iso(),
    }
