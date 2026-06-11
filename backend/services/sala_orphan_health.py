"""
sala_orphan_health_check.py — CTO P0 11/06/2026

Health check periódico que detecta tickets órfãos (sem
`assigned_collaborator_id` ou com valor vazio) e os move automaticamente
para a SALA do tenant correspondente.

Sai do "fail-silent" do bug original: cada vez que o autonomous_engine,
isabella_actions, ou qualquer outro caminho criar um ticket sem rotear,
o job pega na próxima janela.

Periodicidade sugerida: a cada 15 minutos.

Persiste resultado em `sala_orphan_health` para auditoria + alerta.
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "sala_routing",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["sala.orphan_detected", "sala.orphan_healed"],
    "company_id_required": True,
}

import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List

from database import db

log = logging.getLogger("sala_orphan_health")

ORPHAN_QUERY = {
    "$or": [
        {"assigned_collaborator_id": None},
        {"assigned_collaborator_id": {"$exists": False}},
        {"assigned_collaborator_id": ""},
    ],
    "status": {"$ne": "closed"},
}


async def _heal_orphans() -> Dict[str, int]:
    """Move órfãos para a SALA do tenant. Retorna {cid: count}."""
    from services.isabella_actions import _ensure_sala

    now = datetime.now(timezone.utc).isoformat()
    fixed: Dict[str, int] = defaultdict(int)

    # Resolve SALAs por tenant (1 lookup por cid)
    cids: List[str] = await db.tickets.distinct("company_id", ORPHAN_QUERY)
    sala_by_cid: Dict[str, str] = {}
    for cid in cids:
        if cid:
            try:
                sala_by_cid[cid] = await _ensure_sala(cid)
            except Exception as e:
                log.warning("ensure_sala falhou para %s: %s", cid, e)

    async for t in db.tickets.find(
        ORPHAN_QUERY, {"_id": 0, "id": 1, "company_id": 1, "origin": 1, "source": 1}
    ):
        cid = t.get("company_id")
        sala_id = sala_by_cid.get(cid) if cid else None
        if not sala_id:
            continue
        await db.tickets.update_one(
            {"id": t["id"]},
            {"$set": {
                "assigned_collaborator_id": sala_id,
                "system_generated": True,
                "sala_route_reason": "orphan_health_auto_heal",
                "sala_routed_at": now,
                "auto_healed_at": now,
                "auto_healed_origin": t.get("origin") or t.get("source") or "unknown",
            }},
        )
        fixed[cid] += 1
    return dict(fixed)


async def run_orphan_health_check() -> Dict:
    """Job principal. Pode ser chamado pelo scheduler ou manualmente."""
    start = datetime.now(timezone.utc)
    before = await db.tickets.count_documents(ORPHAN_QUERY)

    healed: Dict[str, int] = {}
    if before > 0:
        try:
            healed = await _heal_orphans()
        except Exception as e:  # pragma: no cover
            log.exception("heal_orphans falhou: %s", e)

    after = await db.tickets.count_documents(ORPHAN_QUERY)
    elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)

    report = {
        "id": f"orphhealth-{uuid.uuid4().hex[:12]}",
        "executed_at": start.isoformat(),
        "elapsed_ms": elapsed_ms,
        "orphans_before": before,
        "orphans_after": after,
        "healed": healed,
        "healed_total": sum(healed.values()),
    }

    try:
        await db.sala_orphan_health.insert_one({**report})
    except Exception:
        pass

    # Emite evento se detectou órfãos (visibilidade no Sistema Nervoso)
    if before > 0:
        try:
            for cid, n in healed.items():
                await db.system_events.insert_one({
                    "id": f"evt-{uuid.uuid4().hex[:14]}",
                    "company_id": cid,
                    "event_type": "sala.orphan_healed",
                    "payload": {"healed_count": n, "report_id": report["id"]},
                    "created_at": start.isoformat(),
                })
        except Exception:
            pass

    log.info(
        "sala_orphan_health: before=%d healed=%d after=%d elapsed=%dms",
        before, report["healed_total"], after, elapsed_ms,
    )
    return report


# Helper p/ disparo manual via shell/endpoint
def main():
    asyncio.run(run_orphan_health_check())


if __name__ == "__main__":
    main()
