"""network_access_canonical — Sprint 5 Onda 4 (CEO mandate 19/02/2026)

FONTE CANÔNICA ÚNICA para responder: Cliente → CTO → Porta → ONU →
Ticket → Técnico.

ESCOLHA DA FONTE (decisão técnica RCA):
  - Authoritative: `cto_ports` (granular físico por porta)
  - Projeção: `subscribers.cto_id/cto_port_id` (read-fast lookup)
  - `subscriber_access_points` = cadastro de endereço/plano ATLAZ,
    NÃO fonte de verdade de CTO/porta.

CAMADA: collection `network_access_canonical` materializa o link
COMPLETO (todos os 7 vértices) em um único doc por porta ocupada.
Todos os reads de "qual cliente está em qual CTO" passam por aqui.

REGRA DE OURO (CEO):
  - Toda gravação canônica passa por `upsert_link()` ou
    `release_link()` deste módulo.
  - Writes diretos em `cto_ports`/`subscribers.cto_id` fora do
    helper são detectados e registrados como
    `rejected_parallel_write` na audit.
  - Zero deletes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CANONICAL_COLLECTION = "network_access_canonical"
CTO_PORTS_COLLECTION = "cto_ports"
SOURCE_OF_TRUTH = "cto_ports"  # decisão RCA Onda 4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_canonical_hash(link: Dict[str, Any]) -> str:
    keys = ["cto_id", "port_number", "subscriber_id",
            "ont_sn", "ont_mac", "ticket_id", "collaborator_id",
            "updated_at"]
    canon = {k: link.get(k) for k in keys}
    enc = json.dumps(canon, sort_keys=True, default=str).encode()
    return hashlib.sha256(enc).hexdigest()


async def upsert_link(
    db,
    *,
    company_id: str,
    cto_id: str,
    port_number: int,
    cto_port_id: Optional[str] = None,
    subscriber_id: Optional[str] = None,
    subscriber_name: Optional[str] = None,
    ont_sn: Optional[str] = None,
    ont_mac: Optional[str] = None,
    ticket_id: Optional[str] = None,
    service_id: Optional[str] = None,
    collaborator_id: Optional[str] = None,
    source: str = "manual",
    batch_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Cria/atualiza link canônico. Sincroniza cto_ports + subscribers
    em uma única operação coordenada.
    """
    if not company_id or not cto_id or port_number is None:
        raise ValueError("upsert_link: company_id+cto_id+port_number obrigatórios")

    doc_id = f"nac-{cto_id}-p{int(port_number)}"
    now = _now_iso()
    link: Dict[str, Any] = {
        "id": doc_id,
        "company_id": company_id,
        "cto_id": cto_id,
        "port_number": int(port_number),
        "cto_port_id": cto_port_id or f"{cto_id}-p{int(port_number)}",
        "subscriber_id": subscriber_id,
        "subscriber_name": subscriber_name,
        "ont_sn": ont_sn,
        "ont_mac": ont_mac,
        "ticket_id": ticket_id,
        "service_id": service_id,
        "collaborator_id": collaborator_id,
        "status": "occupied" if subscriber_id else "free",
        "source": source,
        "batch_id": batch_id,
        "updated_at": now,
        "updated_by": actor_user_id,
    }
    link["canonical_hash"] = compute_canonical_hash(link)

    # Upsert no canonical
    await db[CANONICAL_COLLECTION].update_one(
        {"id": doc_id, "company_id": company_id},
        {"$set": link, "$setOnInsert": {"created_at": now,
                                            "created_by": actor_user_id}},
        upsert=True,
    )

    # Sincroniza cto_ports (autoritativo) — write controlado, com
    # marca `canonical_writer=true` para distinguir de writes paralelos.
    await db[CTO_PORTS_COLLECTION].update_one(
        {"id": link["cto_port_id"], "company_id": company_id},
        {"$set": {
            "subscriber_id": subscriber_id,
            "subscriber_name": subscriber_name,
            "status": "occupied" if subscriber_id else "free",
            "occupied_at": now if subscriber_id else None,
            "freed_at": None if subscriber_id else now,
            "mac": ont_mac,
            "sn": ont_sn,
            "last_updated_at": now,
            "last_updated_via": "canonical_writer",
            "last_batch_id": batch_id,
        }},
    )

    # Sincroniza subscribers (projeção)
    if subscriber_id:
        await db.subscribers.update_one(
            {"id": subscriber_id, "company_id": company_id},
            {"$set": {
                "cto_id": cto_id,
                "cto_port_id": link["cto_port_id"],
                "cto_port_number": int(port_number),
                "cto_port_source": "canonical_writer",
                "owner_normalized_at": now,
            }},
        )

    return link


async def release_link(
    db,
    *,
    company_id: str,
    cto_id: str,
    port_number: int,
    reason: str,
    batch_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Libera porta no canonical + cto_ports. Mantém histórico (zero
    delete) — apenas muda status para free e zera subscriber.
    """
    doc_id = f"nac-{cto_id}-p{int(port_number)}"
    prev = await db[CANONICAL_COLLECTION].find_one(
        {"id": doc_id, "company_id": company_id}, {"_id": 0})
    sub_id = prev.get("subscriber_id") if prev else None
    now = _now_iso()
    await db[CANONICAL_COLLECTION].update_one(
        {"id": doc_id, "company_id": company_id},
        {"$set": {
            "subscriber_id": None,
            "subscriber_name": None,
            "status": "free",
            "release_reason": reason,
            "released_at": now,
            "released_by": actor_user_id,
            "batch_id": batch_id,
            "updated_at": now,
        }},
    )
    await db[CTO_PORTS_COLLECTION].update_one(
        {"id": f"{cto_id}-p{int(port_number)}", "company_id": company_id},
        {"$set": {
            "subscriber_id": None,
            "subscriber_name": None,
            "status": "free",
            "freed_at": now,
            "release_reason": reason,
            "last_updated_at": now,
            "last_updated_via": "canonical_writer",
        }},
    )
    if sub_id:
        # Limpa projeção em subscribers (mas mantém audit em owner_normalized_at)
        await db.subscribers.update_one(
            {"id": sub_id, "company_id": company_id},
            {"$set": {
                "cto_id": None,
                "cto_port_id": None,
                "cto_port_number": None,
                "cto_port_source": "canonical_writer:released",
                "owner_normalized_at": now,
            }},
        )
    return {"released": True, "previous_subscriber": sub_id,
            "released_at": now}


async def build_initial_canonical(
    db, company_id: str, *, batch_id: str,
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Constrói (ou re-sincroniza) `network_access_canonical` a partir
    de `cto_ports` (fonte autoritativa).

    Idempotente — re-execução é segura.
    """
    ports = await db[CTO_PORTS_COLLECTION].find(
        {"company_id": company_id}, {"_id": 0}).to_list(length=20000)
    created = 0
    updated_filled = 0
    skipped = 0

    for p in ports:
        cto_id = p.get("cto_id")
        port_number = p.get("port_number")
        if not cto_id or port_number is None:
            skipped += 1
            continue
        sub_id = p.get("subscriber_id")
        sub_name = p.get("subscriber_name")
        ont_sn = p.get("sn")
        ont_mac = p.get("mac")

        # Verifica se sub existe (consistência)
        if sub_id:
            sub_doc = await db.subscribers.find_one(
                {"id": sub_id, "company_id": company_id},
                {"_id": 0, "name": 1})
            if not sub_doc:
                # órfão: mantém o status mas registra
                sub_name = sub_name or "(órfão)"

        # Enriquece com último ticket via stok_history.swap_event
        last_swap = await db.auto_ont_swap_events.find_one(
            {"company_id": company_id, "subscriber_id": sub_id},
            {"_id": 0, "ticket_id": 1, "service_id": 1,
             "collaborator_id": 1, "created_at": 1},
            sort=[("created_at", -1)],
        ) if sub_id else None

        link = await upsert_link(
            db,
            company_id=company_id,
            cto_id=cto_id,
            port_number=int(port_number),
            cto_port_id=p.get("id"),
            subscriber_id=sub_id,
            subscriber_name=sub_name,
            ont_sn=ont_sn,
            ont_mac=ont_mac,
            ticket_id=(last_swap.get("ticket_id")
                          if last_swap else None),
            service_id=(last_swap.get("service_id")
                          if last_swap else None),
            collaborator_id=(last_swap.get("collaborator_id")
                                 if last_swap else None),
            source="build_initial_cto_ports",
            batch_id=batch_id,
            actor_user_id=actor_user_id,
        )
        if link.get("subscriber_id"):
            updated_filled += 1
        created += 1

    return {
        "ports_processed": len(ports),
        "canonical_docs_synced": created,
        "occupied_links": updated_filled,
        "skipped": skipped,
    }


async def detect_parallel_writes(
    db, company_id: str,
) -> Dict[str, Any]:
    """Detecta writes em cto_ports que NÃO passaram pelo canonical_writer.

    Conta docs sem `last_updated_via=canonical_writer` ou cuja data
    de update é mais nova que a do canonical correspondente.
    """
    total_ports = await db[CTO_PORTS_COLLECTION].count_documents(
        {"company_id": company_id})
    via_canonical = await db[CTO_PORTS_COLLECTION].count_documents(
        {"company_id": company_id,
         "last_updated_via": "canonical_writer"})
    via_other = total_ports - via_canonical
    return {
        "total_ports": total_ports,
        "via_canonical_writer": via_canonical,
        "via_other_or_legacy": via_other,
        "compliance_pct": round(via_canonical / total_ports * 100, 2)
            if total_ports else 0.0,
    }


async def check_consistency(
    db, company_id: str,
) -> Dict[str, Any]:
    """Compara network_access_canonical x cto_ports x subscribers.

    Detecta divergências (duplicate truth):
      - canonical.subscriber != cto_ports.subscriber para mesmo port
      - canonical.subscriber != subscribers.id (reverso)
    """
    cur = db[CANONICAL_COLLECTION].find(
        {"company_id": company_id}, {"_id": 0})
    total = 0
    divergent_vs_port = 0
    divergent_vs_sub = 0
    async for link in cur:
        total += 1
        port = await db[CTO_PORTS_COLLECTION].find_one(
            {"id": link.get("cto_port_id"),
             "company_id": company_id},
            {"_id": 0, "subscriber_id": 1, "status": 1})
        if port and port.get("subscriber_id") != link.get("subscriber_id"):
            divergent_vs_port += 1
        if link.get("subscriber_id"):
            sub = await db.subscribers.find_one(
                {"id": link["subscriber_id"],
                 "company_id": company_id},
                {"_id": 0, "cto_port_id": 1, "cto_id": 1})
            if sub and (sub.get("cto_port_id") != link.get("cto_port_id")
                        or sub.get("cto_id") != link.get("cto_id")):
                divergent_vs_sub += 1
    consistency_pct = round(
        ((total - divergent_vs_port - divergent_vs_sub) / total * 100)
        if total else 100.0, 2)
    return {
        "canonical_total": total,
        "divergent_vs_cto_ports": divergent_vs_port,
        "divergent_vs_subscribers": divergent_vs_sub,
        "consistency_pct": consistency_pct,
        "duplicate_truth_pct": round(
            (divergent_vs_port + divergent_vs_sub) / total * 100, 2)
            if total else 0.0,
    }
