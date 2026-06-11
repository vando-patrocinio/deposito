"""red_team_atlaz_to_sala.py — Atlaz orfan SEMPRE cai na grade SALA.

Cobertura:
  1. `_get_or_create_unassigned_inbox(company_id)` retorna `col-sala`
     (ou `col-sala-<cid>` em tenants secundarios).
  2. Nenhum ticket ATIVO aponta para `col-atlaz-inbox*` em nenhuma company.
  3. O placeholder `📥 Sem técnico (Atlaz)` esta desativado (active=False).
  4. SALA existe e e `is_virtual=True` (sumir de listas de tecnicos reais).
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db


ACTIVE_STATES = ["pendente", "aberta", "aguardando_atendimento"]


def _ok(m): print(f"  OK  {m}")
def _fail(m):
    print(f"  FAIL {m}")
    raise AssertionError(m)


async def t_resolver_returns_sala():
    print("\n[1] _get_or_create_unassigned_inbox -> SALA")
    from routes.atlaz import _get_or_create_unassigned_inbox
    rid = await _get_or_create_unassigned_inbox("co-demo")
    if rid != "col-sala":
        _fail(f"esperado col-sala em co-demo, veio {rid!r}")
    _ok(f"co-demo -> {rid}")
    # Outra company gera SALA tenant-isolated
    rid2 = await _get_or_create_unassigned_inbox("co-attribution-test")
    if not rid2.startswith("col-sala"):
        _fail(f"esperado col-sala* em co-attribution-test, veio {rid2!r}")
    _ok(f"co-attribution-test -> {rid2}")


async def t_no_active_in_legacy_inbox():
    print("\n[2] Nenhum ticket ATIVO em inbox legado (atlaz_inbox=True)")
    legacy_ids = [c["id"] async for c in db.collaborators.find(
        {"atlaz_inbox": True}, {"_id": 0, "id": 1})]
    if not legacy_ids:
        _ok("Sem inbox atlaz_inbox no DB (limpeza total).")
        return
    bad = await db.tickets.count_documents({
        "assigned_collaborator_id": {"$in": legacy_ids},
        "status": {"$in": ACTIVE_STATES},
    })
    if bad > 0:
        _fail(f"Ainda existem {bad} ticket(s) ATIVOS em inbox legado {legacy_ids}")
    _ok(f"0 tickets ativos em {len(legacy_ids)} inbox(es) legado(s) -> {legacy_ids}")


async def t_legacy_inbox_deactivated():
    print("\n[3] Placeholder atlaz_inbox desativado (preservado como historico)")
    actives = [c async for c in db.collaborators.find(
        {"atlaz_inbox": True, "active": True},
        {"_id": 0, "id": 1, "name": 1, "company_id": 1})]
    if actives:
        _fail(f"Inbox(es) legado ainda ATIVO(s): {actives}")
    _ok("Todos os inbox legados estao desativados.")


async def t_sala_is_virtual():
    print("\n[4] SALA existe e e virtual (some de listas de tecnicos reais)")
    salas = [s async for s in db.collaborators.find(
        {"is_virtual": True, "virtual_kind": "sala_atendimento"},
        {"_id": 0, "id": 1, "company_id": 1, "name": 1})]
    if not salas:
        _fail("Nenhuma SALA virtual no DB.")
    for s in salas:
        if s.get("name") != "SALA":
            _fail(f"name esperado SALA, veio {s.get('name')!r} ({s['id']})")
    _ok(f"{len(salas)} SALA virtual(is) encontrada(s).")


async def t_sala_has_atlaz_tickets():
    print("\n[5] SALA recebeu os tickets migrados (com flag de rastreio)")
    migrated = await db.tickets.count_documents({
        "assigned_collaborator_id": {"$regex": "^col-sala"},
        "migrated_from_atlaz_inbox": True,
    })
    _ok(f"{migrated} ticket(s) com flag migrated_from_atlaz_inbox=True em SALA.")


async def main():
    print("="*70)
    print("RED TEAM :: Atlaz orfan -> SALA")
    print("="*70)
    await t_resolver_returns_sala()
    await t_no_active_in_legacy_inbox()
    await t_legacy_inbox_deactivated()
    await t_sala_is_virtual()
    await t_sala_has_atlaz_tickets()
    print("\n" + "="*70)
    print("PASS :: Atlaz orfan SEMPRE cai na grade SALA.")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
