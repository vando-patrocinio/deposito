"""Histórico de Equipamento por Cliente (iter163).

Auditoria centralizada por `client_id` consolidando:
- Instalação de ONT (quem instalou, MAC, SN, ticket)
- Retirada de ONT (quem retirou, motivo, defeito)
- Vínculo / troca / liberação de porta da CTO

Tabela: `db.client_equipment_history`.

Schema:
{
  "id": "ceh-XXXX",
  "company_id": str,
  "client_id": str,
  "client_name": str | None,
  "action": "install" | "withdraw" | "port_link" | "port_swap" | "port_release",
  "ont_mac": str | None,
  "ont_sn": str | None,
  "cto_id": str | None,
  "cto_name": str | None,
  "cto_port_number": int | None,
  "prev_cto_id": str | None,
  "prev_cto_port_number": int | None,
  "actor_id": str | None,
  "actor_name": str | None,
  "actor_email": str | None,
  "ticket_id": str | None,
  "service_id": str | None,
  "notes": str | None,
  "captured_at": ISO 8601 UTC,
}
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from core import now_iso
from database import db

logger = logging.getLogger("ponto.client_equipment_history")


VALID_ACTIONS = {
    "install", "withdraw", "port_link", "port_swap", "port_release",
}


async def log_event(
    *,
    company_id: str,
    client_id: Optional[str],
    action: str,
    client_name: Optional[str] = None,
    ont_mac: Optional[str] = None,
    ont_sn: Optional[str] = None,
    cto_id: Optional[str] = None,
    cto_name: Optional[str] = None,
    cto_port_number: Optional[int] = None,
    prev_cto_id: Optional[str] = None,
    prev_cto_port_number: Optional[int] = None,
    actor_id: Optional[str] = None,
    actor_name: Optional[str] = None,
    actor_email: Optional[str] = None,
    ticket_id: Optional[str] = None,
    service_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> Optional[str]:
    """Insere 1 evento no histórico. Retorna o id criado ou None em caso
    de erro (best-effort, nunca derruba o fluxo principal)."""
    if not company_id or not client_id:
        return None
    if action not in VALID_ACTIONS:
        logger.warning("[ceh] ação inválida ignorada: %s", action)
        return None
    doc = {
        "id": f"ceh-{uuid.uuid4().hex[:12]}",
        "company_id": company_id,
        "client_id": client_id,
        "client_name": client_name,
        "action": action,
        "ont_mac": ont_mac,
        "ont_sn": ont_sn,
        "cto_id": cto_id,
        "cto_name": cto_name,
        "cto_port_number": cto_port_number,
        "prev_cto_id": prev_cto_id,
        "prev_cto_port_number": prev_cto_port_number,
        "actor_id": actor_id,
        "actor_name": actor_name,
        "actor_email": actor_email,
        "ticket_id": ticket_id,
        "service_id": service_id,
        "notes": (notes or "").strip()[:500] or None,
        "captured_at": now_iso(),
    }
    try:
        await db.client_equipment_history.insert_one(doc)
        return doc["id"]
    except Exception as e:
        logger.warning("[ceh] insert falhou (%s/%s): %s", action, client_id, e)
        return None


async def list_events(company_id: str, client_id: str,
                        limit: int = 100) -> List[Dict[str, Any]]:
    """Linha do tempo do equipamento do cliente, ordem cronológica DESC."""
    cur = db.client_equipment_history.find(
        {"company_id": company_id, "client_id": client_id},
        {"_id": 0},
    ).sort("captured_at", -1).limit(min(max(limit, 1), 500))
    return await cur.to_list(min(max(limit, 1), 500))


async def get_current_summary(company_id: str,
                                  client_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Retorna o estado mais recente de cada cliente, em lote.

    Para cada `client_id`, devolve:
      - install: último evento `install` (instalador, ticket, MAC)
      - withdraw: último evento `withdraw`
      - port: último vínculo/troca de porta (port_link ou port_swap)

    Usado para enriquecer a listagem de clientes SmartOLT.
    """
    if not client_ids:
        return {}
    pipeline = [
        {"$match": {
            "company_id": company_id,
            "client_id": {"$in": client_ids},
        }},
        {"$sort": {"captured_at": -1}},
        {"$group": {
            "_id": {"client_id": "$client_id", "action": "$action"},
            "doc": {"$first": "$$ROOT"},
        }},
    ]
    out: Dict[str, Dict[str, Any]] = {cid: {} for cid in client_ids}
    async for r in db.client_equipment_history.aggregate(pipeline):
        client_id = r["_id"]["client_id"]
        action = r["_id"]["action"]
        d = r["doc"]
        d.pop("_id", None)
        if action == "install":
            out[client_id]["install"] = d
        elif action == "withdraw":
            out[client_id]["withdraw"] = d
        elif action in ("port_link", "port_swap"):
            cur = out[client_id].get("port")
            if not cur or d.get("captured_at") > cur.get("captured_at", ""):
                out[client_id]["port"] = d
    return out
