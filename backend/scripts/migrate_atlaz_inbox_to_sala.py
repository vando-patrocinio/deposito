"""migrate_atlaz_inbox_to_sala.py — Migra bolhas orfas Atlaz para SALA.

REGRA (11/02/2026): tudo que veio do Atlaz sem tecnico mapeavel
sempre cai na grade SALA da Lousa.

O placeholder `📥 Sem técnico (Atlaz)` (atlaz_inbox=True) foi descontinuado.

Este script:
  1. Para cada company com colaboradores `atlaz_inbox=True`:
     a. Garante que existe SALA (via _ensure_sala).
     b. Reatribui TODOS os tickets ativos do inbox -> SALA.
  2. Desativa o colaborador atlaz_inbox (active=False) — preserva historico
     mas tira ele de listas/relatorios.

Idempotente: pode ser rodado N vezes sem efeito colateral.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "atlaz",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db
from services.isabella_actions import _ensure_sala


ACTIVE_STATES = ["pendente", "aberta", "aguardando_atendimento"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def main():
    print("="*70)
    print("MIGRACAO :: Atlaz Inbox -> SALA (todos os tenants)")
    print("="*70)

    inboxes = [c async for c in db.collaborators.find(
        {"atlaz_inbox": True},
        {"_id": 0, "id": 1, "company_id": 1, "name": 1, "active": 1},
    )]
    if not inboxes:
        print("\n[OK] Nenhum colaborador atlaz_inbox encontrado. Nada a migrar.")
        return

    print(f"\nEncontrados {len(inboxes)} inbox(es) atlaz_inbox:")
    for ib in inboxes:
        print(f"  - {ib['id']} (company={ib['company_id']}, active={ib.get('active')})")

    grand_moved = 0
    for ib in inboxes:
        cid = ib["company_id"]
        inbox_id = ib["id"]
        sala_id = await _ensure_sala(cid)
        print(f"\n[company={cid}] SALA={sala_id}")

        # Migra tickets ATIVOS do inbox -> SALA
        res_active = await db.tickets.update_many(
            {
                "company_id": cid,
                "assigned_collaborator_id": inbox_id,
                "status": {"$in": ACTIVE_STATES},
            },
            {"$set": {
                "assigned_collaborator_id": sala_id,
                "atlaz_unassigned": True,
                "migrated_from_atlaz_inbox": True,
                "migrated_to_sala_at": _now(),
            }},
        )
        print(f"  tickets ATIVOS migrados: {res_active.modified_count}")
        grand_moved += res_active.modified_count

        # Migra tickets FINALIZADOS tambem (historico precisa apontar pra SALA)
        # Sem update no status, so mexe na referencia.
        res_done = await db.tickets.update_many(
            {
                "company_id": cid,
                "assigned_collaborator_id": inbox_id,
                "status": {"$nin": ACTIVE_STATES},
            },
            {"$set": {
                "assigned_collaborator_id": sala_id,
                "migrated_from_atlaz_inbox": True,
                "migrated_to_sala_at": _now(),
            }},
        )
        print(f"  tickets HISTORICOS migrados: {res_done.modified_count}")
        grand_moved += res_done.modified_count

        # Desativa o inbox legado (preserva o documento como historico)
        if ib.get("active") is not False:
            await db.collaborators.update_one(
                {"id": inbox_id},
                {"$set": {
                    "active": False,
                    "deactivated_at": _now(),
                    "deactivation_reason": "Migrado para SALA (atlaz_inbox descontinuado)",
                    "updated_at": _now(),
                }},
            )
            print(f"  inbox {inbox_id} desativado (preservado como historico)")
        else:
            print(f"  inbox {inbox_id} ja estava inativo")

    print("\n" + "="*70)
    print(f"MIGRACAO OK :: {grand_moved} ticket(s) movidos para SALA.")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
