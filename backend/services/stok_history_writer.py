"""stok_history_writer — Sprint 5 Onda 1 (CEO mandate 19/02/2026)

Helper canônico para gravação em `stok_history`. Garante que toda
movimentação possua os 6 campos obrigatórios de rastreabilidade:
    ticket_id, service_id, collaborator_id, subscriber_id,
    event_type, event_timestamp.

REGRA: NUNCA mais gravar OS-XXXX apenas dentro de `description`. A
description vira humanamente legível; os IDs vivem em campos próprios.

USO:
    from services.stok_history_writer import write_stok_event
    await write_stok_event(
        db, company_id=cid,
        event_type="instalacao",            # canonical event type
        ticket_id="tkt-xxx",
        service_id="OS-XXXXXX",
        collaborator_id="col-xxx",
        subscriber_id="sub-xxx",
        description="Instalação finalizada (auto Lousa)",
        actor_user_id="usr-xxx",
        actor_user_label="João",
        materials_count=3,
    )

Se `allow_missing=False` (default) e algum dos 6 campos críticos estiver
ausente, levanta ValueError e o caller decide se loga warning ou aborta.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Tipos canônicos aceitos (event_type) — espelha tipos da Lousa/OS
CANONICAL_EVENT_TYPES = {
    "instalacao", "reparo", "troca", "retirada",
    "manutencao", "vistoria", "preventiva",
    "transfer_to_tech", "transfer_to_client",
    "return_to_company", "defective_return",
    "purchase_in", "manual_adjust", "audit_heal",
    "rompimento", "swap_ont", "rede_ia_event",
}

OS_RX = re.compile(
    r"(?:OS-([A-F0-9]{4,8})"
    r"|(test-iter[\w-]+-svc\d*-[a-f0-9]+)"
    r"|(srv-test-iter[\w-]+-[a-f0-9]+)"
    r"|\b(svc-[a-f0-9]{6,12})\b)",
    re.IGNORECASE,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_os_short(description: str) -> Optional[str]:
    """Extrai identificador de OS de uma description.

    Aceita formatos:
      - OS-FA47F6  → retorna 'FA47F6'
      - test-iter196-svc-ea1dae6a
      - srv-test-iter174-560b28
      - svc-b71e6064
    """
    if not description:
        return None
    m = OS_RX.search(description)
    if not m:
        return None
    if m.group(1):
        return m.group(1).upper()
    return m.group(2) or m.group(3) or m.group(4)


async def write_stok_event(
    db,
    *,
    company_id: str,
    event_type: str,
    ticket_id: Optional[str] = None,
    service_id: Optional[str] = None,
    collaborator_id: Optional[str] = None,
    subscriber_id: Optional[str] = None,
    event_timestamp: Optional[str] = None,
    description: str = "",
    actor_user_id: Optional[str] = None,
    actor_user_label: Optional[str] = None,
    tag: Optional[str] = None,
    materials: Optional[list] = None,
    extra: Optional[Dict[str, Any]] = None,
    allow_missing: bool = False,
) -> Dict[str, Any]:
    """Grava um doc em stok_history com rastreabilidade completa.

    Returns o doc gravado (com `id`).
    """
    if not company_id:
        raise ValueError("write_stok_event: company_id é obrigatório")
    if not event_type:
        raise ValueError("write_stok_event: event_type é obrigatório")

    if event_type not in CANONICAL_EVENT_TYPES:
        logger.warning(
            "[stok_history_writer] event_type fora do canônico: %s", event_type)

    # Identifica campos faltantes
    missing = [
        n for n, v in (
            ("ticket_id", ticket_id),
            ("service_id", service_id),
            ("collaborator_id", collaborator_id),
            ("subscriber_id", subscriber_id),
        ) if not v
    ]
    if missing and not allow_missing:
        raise ValueError(
            f"write_stok_event: campos obrigatórios ausentes: {missing}. "
            f"event_type={event_type}, desc={description[:80]!r}. "
            f"Use allow_missing=True somente em fluxos não-OS (ex. rede_ia).")

    ts = event_timestamp or _now_iso()
    doc = {
        "id": str(uuid.uuid4()),
        "company_id": company_id,
        "event_type": event_type,
        # Espelha event_type em `type` para compat com leitura legada
        "type": event_type,
        "ticket_id": ticket_id,
        "service_id": service_id,
        "collaborator_id": collaborator_id,
        "subscriber_id": subscriber_id,
        "event_timestamp": ts,
        # Compat com leitores que usam `date`:
        "date": ts,
        "description": description or "",
        "user": actor_user_label or "?",
        "actor_user_id": actor_user_id,
        "actor_user_label": actor_user_label,
        "tag": tag,
        "materials": materials or [],
        "created_at": _now_iso(),
        "schema_version": "sprint5_onda1",
    }
    if extra:
        doc.update(extra)

    await db.stok_history.insert_one(doc)
    return doc


async def backfill_orphan_events(
    db,
    company_id: str,
    *,
    batch_id: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Backfill dos eventos órfãos em stok_history para `company_id`.

    Classifica cada doc em uma de 3 categorias:
      - OS_EVENT: descrição contém OS-XXXX (instalação/reparo/troca/etc).
        Precisa ticket_id+service_id+collaborator_id+subscriber_id.
      - NON_OS_EVENT: type ∈ {transferencia, entrada_ont, entrada_insumo,
        compra, reconcile}. Apenas event_type+event_timestamp obrigatórios.
      - UNKNOWN: nem OS nem type canônico → marca traceability_status.

    Aplica $set com:
      - ticket_id, service_id, collaborator_id, subscriber_id (quando aplicável)
      - event_type, event_timestamp (sempre)
      - traceability_status (full | non_os | partial | unknown)
      - backfill_source, backfill_batch_id, backfill_applied_at
    """
    NON_OS_TYPES = {
        "transferencia", "transferencia_insumo",
        "entrada_ont", "entrada_insumo", "compra",
        "reconcile", "ajuste_manual",
        "rede_lancamento", "rede_estorno",
        "set_sn", "migrate_sn", "admin_reset_granular",
        "entrada_insumo_reversao", "field_equipment_return",
        "recovery",
    }

    q = {
        "company_id": company_id,
        "$and": [
            {"$or": [
                {"ticket_id": {"$in": [None, ""]}},
                {"ticket_id": {"$exists": False}},
                {"traceability_status": {"$exists": False}},
                {"traceability_status": "unknown"},
            ]},
            # Já normalizados pela Onda 1 não voltam (a menos que ainda
            # estejam marcados como "unknown" — esses sim podem evoluir).
            {"$or": [
                {"backfill_source": {"$exists": False}},
                {"backfill_source": {"$ne": "sprint5_onda1_2026"}},
                {"traceability_status": "unknown"},
            ]},
        ],
    }
    orphans = await db.stok_history.find(q, {"_id": 0}).to_list(length=20000)

    total = len(orphans)
    fixed_os_full = 0
    fixed_non_os = 0
    partial = 0
    unknown = 0
    unresolved_ids: list = []

    for doc in orphans:
        desc = doc.get("description") or ""
        os_token = extract_os_short(desc)
        legacy_type = (doc.get("type") or "").strip().lower()
        ts = doc.get("date") or doc.get("created_at") or _now_iso()
        existing_ticket = doc.get("ticket_id")

        update_fields: Dict[str, Any] = {
            "event_timestamp": ts,
            "backfill_source": "sprint5_onda1_2026",
            "backfill_batch_id": batch_id,
            "backfill_applied_at": _now_iso(),
        }

        # CASO 0: doc já tem ticket_id (ex.: rompimentos) — só falta event_type
        # e enriquecer subscriber_id/collaborator_id via ticket.
        if existing_ticket and not os_token:
            tk = await db.tickets.find_one(
                {"company_id": company_id, "id": existing_ticket},
                {"_id": 0, "assigned_to": 1, "client_id": 1},
            )
            sub_id = tk.get("client_id") if tk else None
            collab_id = tk.get("assigned_to") if tk else None
            update_fields.update({
                "event_type": legacy_type or "unknown",
                "service_id": doc.get("service_id"),
                "subscriber_id": doc.get("subscriber_id") or sub_id,
                "collaborator_id": doc.get("collaborator_id") or collab_id,
                "traceability_status": "full" if (sub_id and collab_id)
                                          else "partial",
            })
            if sub_id and collab_id:
                fixed_os_full += 1
            else:
                partial += 1
            if not dry_run:
                await db.stok_history.update_one(
                    {"id": doc["id"]},
                    {"$set": update_fields},
                )
            continue

        if os_token:
            # Identifica formato e monta query
            tok_lower = os_token.lower()
            if (tok_lower.startswith("test-iter")
                    or tok_lower.startswith("srv-")
                    or tok_lower.startswith("svc-")):
                # ID direto (formato literal)
                svc_query = {"company_id": company_id, "id": tok_lower}
            else:
                # OS-XXXXXX
                svc_query = {
                    "company_id": company_id,
                    "id": {"$regex": f"OS-{os_token}", "$options": "i"},
                }
            svc = await db.stok_services.find_one(
                svc_query,
                {"_id": 0, "id": 1, "ticket_id": 1, "type": 1,
                 "client_id": 1, "technician_id": 1},
            )
            ticket_id = svc.get("ticket_id") if svc else None
            service_id = (svc.get("id") if svc
                          else (tok_lower if (
                              tok_lower.startswith("test-iter")
                              or tok_lower.startswith("srv-")
                              or tok_lower.startswith("svc-"))
                              else f"OS-{os_token}"))
            ev_type = (svc.get("type") if svc else None) or legacy_type
            subscriber_id = svc.get("client_id") if svc else None
            collaborator_id = svc.get("technician_id") if svc else None
            if ticket_id and not collaborator_id:
                tk = await db.tickets.find_one(
                    {"company_id": company_id, "id": ticket_id},
                    {"_id": 0, "assigned_to": 1, "client_id": 1},
                )
                if tk:
                    collaborator_id = collaborator_id or tk.get("assigned_to")
                    subscriber_id = subscriber_id or tk.get("client_id")

            update_fields.update({
                "ticket_id": ticket_id,
                "service_id": service_id,
                "collaborator_id": collaborator_id,
                "subscriber_id": subscriber_id,
                "event_type": ev_type,
            })

            non_null = sum(1 for v in (ticket_id, service_id,
                                            collaborator_id, subscriber_id)
                           if v)
            if non_null == 4:
                fixed_os_full += 1
                update_fields["traceability_status"] = "full"
            else:
                partial += 1
                update_fields["traceability_status"] = (
                    "partial_os_not_found" if not svc else "partial")
        elif legacy_type in NON_OS_TYPES:
            update_fields["event_type"] = legacy_type
            update_fields["traceability_status"] = "non_os_required"
            fixed_non_os += 1
        else:
            unknown += 1
            unresolved_ids.append(doc.get("id"))
            update_fields["event_type"] = legacy_type or "unknown"
            update_fields["traceability_status"] = "unknown"

        if not dry_run:
            await db.stok_history.update_one(
                {"id": doc["id"]},
                {"$set": update_fields},
            )

    cured = fixed_os_full + fixed_non_os + partial
    coverage_pct = round(
        (cured / total * 100.0) if total else 100.0, 2)

    return {
        "total_orphans": total,
        "fixed_os_full_4of4": fixed_os_full,
        "fixed_non_os_event": fixed_non_os,
        "partial_os": partial,
        "unknown_unresolved": unknown,
        "unresolved_ids_sample": unresolved_ids[:20],
        "coverage_pct_after": coverage_pct,
        "cured_total": cured,
    }
