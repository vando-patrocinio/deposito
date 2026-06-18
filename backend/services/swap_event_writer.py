"""swap_event_writer — Sprint 5 Onda 2 (CEO mandate 19/02/2026)

Helper canônico para gravação em `auto_ont_swap_events`.

Schema mínimo obrigatório por event_type:

  install:
    ticket_id, service_id, subscriber_id, collaborator_id,
    cto_id, port_number, ont_new_sn|ont_new_mac, created_at, created_by

  swap (reparo com troca de ONU):
    ticket_id, service_id, subscriber_id, collaborator_id,
    cto_id, port_number, ont_old_sn|ont_old_mac, ont_new_sn|ont_new_mac,
    swap_reason, created_at, created_by

  replacement:
    Mesmo do swap.

  removal:
    ticket_id, service_id, subscriber_id, collaborator_id,
    ont_old_sn|ont_old_mac, destino, created_at, created_by

REGRA: zero descrição textual como fonte de verdade. Audit hash SHA256
sobre os campos canônicos.

Confirmation states permitidos (CEO list — não criar novos):
  pending_confirmation, sent_to_technician, confirmed, disputed,
  needs_review, overdue_confirmation
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

EVENT_TYPES = {"install", "swap", "replacement", "removal"}

CONFIRMATION_STATES = {
    "pending_confirmation", "sent_to_technician", "confirmed",
    "disputed", "needs_review", "overdue_confirmation",
}

REQUIRED_FIELDS_BY_TYPE: Dict[str, set] = {
    "install": {"ticket_id", "service_id", "subscriber_id",
                "collaborator_id", "cto_id", "port_number",
                "ont_new_identifier"},
    "swap": {"ticket_id", "service_id", "subscriber_id",
             "collaborator_id", "cto_id", "port_number",
             "ont_old_identifier", "ont_new_identifier", "swap_reason"},
    "replacement": {"ticket_id", "service_id", "subscriber_id",
                    "collaborator_id", "cto_id", "port_number",
                    "ont_old_identifier", "ont_new_identifier"},
    "removal": {"ticket_id", "service_id", "subscriber_id",
                "collaborator_id", "ont_old_identifier"},
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_id(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    return str(v).strip().upper() or None


def compute_audit_hash(payload: Dict[str, Any]) -> str:
    """Hash SHA-256 determinístico sobre campos canônicos."""
    keys = [
        "event_type", "company_id", "ticket_id", "service_id",
        "subscriber_id", "collaborator_id", "cto_id", "port_number",
        "ont_old_sn", "ont_old_mac", "ont_new_sn", "ont_new_mac",
        "swap_reason", "created_at",
    ]
    canon = {k: payload.get(k) for k in keys}
    encoded = json.dumps(canon, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def write_swap_event(
    db,
    *,
    company_id: str,
    event_type: str,
    ticket_id: Optional[str] = None,
    service_id: Optional[str] = None,
    subscriber_id: Optional[str] = None,
    collaborator_id: Optional[str] = None,
    cto_id: Optional[str] = None,
    port_number: Optional[int] = None,
    ont_old_sn: Optional[str] = None,
    ont_old_mac: Optional[str] = None,
    ont_new_sn: Optional[str] = None,
    ont_new_mac: Optional[str] = None,
    swap_reason: Optional[str] = None,
    destino: Optional[str] = None,
    created_by: Optional[str] = None,
    smartolt_snapshot: Optional[dict] = None,
    confirmation_status: str = "pending_confirmation",
    stok_history_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    allow_missing: bool = False,
) -> Dict[str, Any]:
    """Grava um doc em auto_ont_swap_events. Valida campos por event_type.

    `allow_missing=True` apenas para backfill retroativo que não
    consegue recuperar 100% dos campos.
    """
    if event_type not in EVENT_TYPES:
        raise ValueError(
            f"write_swap_event: event_type inválido: {event_type}. "
            f"Use um de: {sorted(EVENT_TYPES)}")
    if confirmation_status not in CONFIRMATION_STATES:
        raise ValueError(
            f"confirmation_status inválido: {confirmation_status}. "
            f"Use um de: {sorted(CONFIRMATION_STATES)}")

    ont_old_sn = _normalize_id(ont_old_sn)
    ont_old_mac = _normalize_id(ont_old_mac)
    ont_new_sn = _normalize_id(ont_new_sn)
    ont_new_mac = _normalize_id(ont_new_mac)

    # Identificadores combinados (qualquer SN ou MAC vale)
    ont_old_identifier = ont_old_sn or ont_old_mac
    ont_new_identifier = ont_new_sn or ont_new_mac

    # Validação de campos obrigatórios
    required = REQUIRED_FIELDS_BY_TYPE[event_type]
    have = {
        "ticket_id": ticket_id,
        "service_id": service_id,
        "subscriber_id": subscriber_id,
        "collaborator_id": collaborator_id,
        "cto_id": cto_id,
        "port_number": port_number,
        "ont_old_identifier": ont_old_identifier,
        "ont_new_identifier": ont_new_identifier,
        "swap_reason": swap_reason,
    }
    missing = [k for k in required if not have.get(k)]
    if missing and not allow_missing:
        raise ValueError(
            f"write_swap_event[{event_type}]: campos obrigatórios "
            f"ausentes: {missing}")

    now = _now_iso()
    event_id = f"swp-{uuid.uuid4().hex[:14]}"

    doc: Dict[str, Any] = {
        "event_id": event_id,
        "id": event_id,  # alias para queries genéricas
        "event_type": event_type,
        "company_id": company_id,
        "ticket_id": ticket_id,
        "service_id": service_id,
        "subscriber_id": subscriber_id,
        "collaborator_id": collaborator_id,
        "cto_id": cto_id,
        "port_number": int(port_number) if port_number is not None else None,
        "ont_old_sn": ont_old_sn,
        "ont_old_mac": ont_old_mac,
        "ont_new_sn": ont_new_sn,
        "ont_new_mac": ont_new_mac,
        "swap_reason": swap_reason,
        "destino": destino,
        "created_at": now,
        "created_by": created_by or "system",
        "confirmation_status": confirmation_status,
        "confirmation_at": None,
        "smartolt_snapshot": smartolt_snapshot,
        "stok_history_id": stok_history_id,
        "schema_version": "sprint5_onda2",
        "missing_fields": missing if missing else None,
        "traceability_complete": len(missing) == 0,
    }
    if extra:
        doc.update(extra)

    doc["audit_hash"] = compute_audit_hash(doc)

    await db.auto_ont_swap_events.insert_one(doc)

    # Cross-link: marca stok_history correspondente com swap_event_id
    if stok_history_id:
        try:
            await db.stok_history.update_one(
                {"id": stok_history_id, "company_id": company_id},
                {"$set": {
                    "swap_event_id": event_id,
                    "swap_event_audit_hash": doc["audit_hash"],
                }},
            )
        except Exception as e:
            logger.warning("[swap_event_writer] cross-link falhou: %s", e)

    return doc


async def capture_smartolt_snapshot(
    db, company_id: str, *, old_id: Optional[str],
    new_id: Optional[str],
) -> Dict[str, Any]:
    """Snapshot best-effort dos ONUs antes/depois no SmartOLT.

    Retorna {'old': {...}, 'new': {...}} ou {} se nada encontrado.
    Nunca quebra fluxo.
    """
    snap: Dict[str, Any] = {}
    try:
        if old_id:
            d = await db.smartolt_onus.find_one(
                {"company_id": company_id,
                 "$or": [{"unique_external_id": old_id}, {"sn": old_id}]},
                {"_id": 0, "unique_external_id": 1, "sn": 1, "name": 1,
                 "olt_name": 1, "status": 1, "signal_1490": 1,
                 "subscriber_name": 1},
            )
            if d:
                snap["old"] = d
        if new_id:
            d = await db.smartolt_onus.find_one(
                {"company_id": company_id,
                 "$or": [{"unique_external_id": new_id}, {"sn": new_id}]},
                {"_id": 0, "unique_external_id": 1, "sn": 1, "name": 1,
                 "olt_name": 1, "status": 1, "signal_1490": 1,
                 "subscriber_name": 1},
            )
            if d:
                snap["new"] = d
    except Exception as e:
        logger.warning("[swap_event_writer.smartolt] %s", e)
    snap["captured_at"] = _now_iso()
    return snap
