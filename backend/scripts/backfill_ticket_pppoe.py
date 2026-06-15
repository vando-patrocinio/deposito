"""P0-2 — Backfill `client_snapshot.pppoe_user` em tickets ativos.

OPERAÇÃO TICKET ARMADO (CTO 2026-02)

Causa raiz: 87% dos tickets LOS-like estão sem `pppoe_user`, o que torna
impossível ligar o ticket à ONU correta no SmartOLT. A Lousa cai em
"sem leitura" porque o linkage está quebrado.

Estratégia (confidence-driven, reversível):
  1. Para cada ticket aberto/pendente sem `client_snapshot.pppoe_user`:
     a. Lookup direto via `client_id → subscribers.pppoe_login` (confidence=high)
     b. Lookup via `subscribers.atlaz_pppoe_user` (preenchido pelo backfill A.2)
        (confidence=high)
     c. Match por nome em `smartolt_onus.name` se for exato e único
        (confidence=medium)
  2. Grava em `client_snapshot.pppoe_user`, `pppoe_source`, `pppoe_confidence`.
  3. NÃO INVENTA: se confiança baixa, marca `pppoe_confidence=low` e
     preserva campo vazio.
  4. Log em `ticket_logs` para auditoria reversível.

Uso:
  python scripts/backfill_ticket_pppoe.py
      [--company-id=<cid>]
      [--limit=500]
      [--dry-run]
      [--include-closed]   (default False, só ativos)

Idempotente. Reversível via:
  db.tickets.updateMany({pppoe_backfilled_at:{$exists:true}},
                          {$unset:{...}})
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db  # noqa: E402

logger = logging.getLogger("ticket_pppoe_backfill")


def _norm(s: Any) -> str:
    return "".join(ch for ch in str(s or "").lower()
                    if ch.isalnum())


async def _find_subscriber_pppoe(company_id: str,
                                    client_id: Optional[str]
                                    ) -> Optional[Dict[str, Any]]:
    """Busca subscriber e retorna pppoe_user + fonte."""
    if not client_id:
        return None
    sub = await db.subscribers.find_one(
        {"company_id": company_id, "id": client_id},
        {"_id": 0, "pppoe_login": 1, "atlaz_pppoe_user": 1,
         "pppoe_user": 1, "atlaz_id_ponto": 1, "atlaz_id_assinante": 1,
         "name": 1},
    )
    if not sub:
        return None
    pppoe = (sub.get("pppoe_login") or sub.get("pppoe_user")
              or sub.get("atlaz_pppoe_user"))
    if not pppoe:
        return None
    source = ("subscribers.pppoe_login" if sub.get("pppoe_login")
               else "subscribers.pppoe_user" if sub.get("pppoe_user")
               else "subscribers.atlaz_pppoe_user")
    return {
        "pppoe": pppoe,
        "source": source,
        "confidence": "high",
        "atlaz_id_ponto": sub.get("atlaz_id_ponto"),
        "atlaz_id_assinante": sub.get("atlaz_id_assinante"),
    }


async def _match_by_name(company_id: str,
                          name: str) -> Optional[Dict[str, Any]]:
    """Busca smartolt_onus.name exato/contém para inferir PPPoE.
    Confidence = medium — só usar como fallback.
    """
    if not name or len(name) < 4:
        return None
    norm_target = _norm(name)
    # Tenta match exato em name_norm primeiro
    candidates = []
    cur = db.smartolt_onus.find(
        {"company_id": company_id, "name_norm": norm_target},
        {"_id": 0, "name": 1, "unique_external_id": 1, "sn": 1},
    ).limit(5)
    async for o in cur:
        candidates.append(o)
    if not candidates:
        # Tenta match prefix (suficientemente exclusivo)
        cur = db.smartolt_onus.find(
            {"company_id": company_id,
             "name": {"$regex": f"^{name}$", "$options": "i"}},
            {"_id": 0, "name": 1, "unique_external_id": 1, "sn": 1},
        ).limit(5)
        async for o in cur:
            candidates.append(o)
    if len(candidates) != 1:
        return None  # ambíguo, abortar
    o = candidates[0]
    return {
        "pppoe": o.get("name"),
        "source": "smartolt_onus.name_exact",
        "confidence": "medium",
    }


async def backfill_company(company_id: str, *,
                              limit: int = 500,
                              dry_run: bool = False,
                              include_closed: bool = False
                              ) -> Dict[str, Any]:
    q: Dict[str, Any] = {"company_id": company_id}
    if not include_closed:
        q["status"] = {"$in": ["aberta", "pendente", "em_andamento",
                                "em andamento"]}
    # Apenas tickets sem pppoe (ou com pppoe_confidence=low ainda não revisado)
    q["$or"] = [
        {"client_snapshot.pppoe_user": {"$in": [None, ""]}},
        {"client_snapshot.pppoe_user": {"$exists": False}},
    ]

    stats = {
        "total_processed": 0,
        "matched_high_subscriber": 0,
        "matched_medium_smartolt_name": 0,
        "not_found": 0,
        "errors": 0,
        "dry_run": dry_run,
        "company_id": company_id,
    }

    cur = db.tickets.find(
        q, {"_id": 0, "id": 1, "client_id": 1,
            "client_snapshot": 1, "status": 1, "type": 1},
    ).limit(limit)

    async for t in cur:
        stats["total_processed"] += 1
        ticket_id = t.get("id")
        snap = t.get("client_snapshot") or {}
        client_id = t.get("client_id") or snap.get("subscriber_id")
        client_name = snap.get("name") or ""

        match = await _find_subscriber_pppoe(company_id, client_id)
        if match:
            stats["matched_high_subscriber"] += 1
        else:
            # Fallback medium
            match = await _match_by_name(company_id, client_name)
            if match:
                stats["matched_medium_smartolt_name"] += 1
            else:
                stats["not_found"] += 1
                if not dry_run:
                    # Marca confidence=low pra parar de re-processar
                    await db.tickets.update_one(
                        {"id": ticket_id},
                        {"$set": {
                            "client_snapshot.pppoe_confidence": "low",
                            "client_snapshot.pppoe_backfill_attempted_at":
                                datetime.now(timezone.utc).isoformat(),
                        }},
                    )
                continue

        if dry_run:
            logger.info("[dry] %s ← %s (%s, conf=%s)",
                         ticket_id, match["pppoe"], match["source"],
                         match["confidence"])
            continue

        set_doc = {
            "client_snapshot.pppoe_user": match["pppoe"],
            "client_snapshot.pppoe_source": match["source"],
            "client_snapshot.pppoe_confidence": match["confidence"],
            "client_snapshot.pppoe_backfilled_at":
                datetime.now(timezone.utc).isoformat(),
        }
        if match.get("atlaz_id_ponto"):
            set_doc["atlaz_id_ponto"] = match["atlaz_id_ponto"]
        if match.get("atlaz_id_assinante"):
            set_doc["atlaz_id_assinante"] = match["atlaz_id_assinante"]

        try:
            await db.tickets.update_one({"id": ticket_id}, {"$set": set_doc})
            # Log reversível
            await db.ticket_logs.insert_one({
                "id": f"tl-{uuid.uuid4().hex[:10]}",
                "company_id": company_id,
                "ticket_id": ticket_id,
                "action": "pppoe_backfill",
                "details": (f"pppoe={match['pppoe']} "
                             f"source={match['source']} "
                             f"confidence={match['confidence']}"),
                "actor_id": "system_backfill",
                "at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.warning("[backfill] update fail %s: %s", ticket_id, e)
            stats["errors"] += 1

    return stats


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-id", default=None)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-closed", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                          format="%(asctime)s %(levelname)s %(message)s")

    companies: list[str] = []
    if args.company_id:
        companies = [args.company_id]
    else:
        cur = db.tickets.aggregate([{"$group": {"_id": "$company_id"}}])
        async for c in cur:
            if c.get("_id"):
                companies.append(c["_id"])

    print(f"Processando {len(companies)} empresa(s): {companies}")
    for cid in companies:
        res = await backfill_company(
            cid, limit=args.limit, dry_run=args.dry_run,
            include_closed=args.include_closed,
        )
        print(f"  {cid}: {res}")


if __name__ == "__main__":
    asyncio.run(main())
