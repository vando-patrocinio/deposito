"""red_team_sala_routing.py — TODA nota sistemica cai em SALA.

Verifica que os principais geradores automaticos de tickets passam
pelo helper `services.sala_router.route_to_sala` e que o ticket
resultante tem:
  - assigned_collaborator_id == col-sala (ou col-sala-<tenant>)
  - system_generated == True
  - sala_route_reason preenchido
  - original_tech_suggested preservado (rastreio)

Cobertura:
  1. Helper unit: route_to_sala muta o doc corretamente.
  2. Helper unit: company sem SALA cria SALA antes de rotear.
  3. Helper unit: reason invalida vira "system_other".
  4. Helper unit: company_id ausente -> ValueError.
  5. Codebase audit: insertion sites que mencionamos importam o helper.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "sala_routing",
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
from services.sala_router import route_to_sala, VALID_REASONS


def _ok(m): print(f"  OK  {m}")
def _fail(m):
    print(f"  FAIL {m}")
    raise AssertionError(m)


# Sites verificados — qualquer regressao aqui significa que alguem
# adicionou um insertion sem rotear pra SALA.
EXPECTED_SITES = {
    "services/isabella_lousa_scheduler.py": "isabella_agendamento",
    "services/isabella_incident.py":         "isabella_incident",
    "routes/ai_preventive.py":               "ai_preventive_accepted",
    "routes/preventive_os.py":               "preventive_auto",
    "services/rede_ia_outage_detector.py":   "rede_ia_outage",
    "services/smartolt_predictive.py":       "smartolt_predictive",
    "routes/atlaz.py":                        None,  # rota via _get_or_create_unassigned_inbox
}


async def t_helper_basic_route():
    print("\n[1] route_to_sala — basico")
    doc = {"company_id": "co-demo", "id": "tkt-test",
            "assigned_collaborator_id": "col-someone"}
    sid = await route_to_sala(doc, reason="ai_preventive_accepted",
                                  original_tech_suggested="col-someone")
    if not sid.startswith("col-sala"):
        _fail(f"sid {sid!r} nao comeca com col-sala")
    if doc["assigned_collaborator_id"] != sid:
        _fail(f"doc.assigned nao virou {sid}")
    if doc.get("system_generated") is not True:
        _fail("system_generated nao virou True")
    if doc.get("sala_route_reason") != "ai_preventive_accepted":
        _fail(f"reason invalido: {doc.get('sala_route_reason')}")
    if doc.get("original_tech_suggested") != "col-someone":
        _fail("original_tech_suggested perdido")
    _ok(f"route_to_sala muta doc -> assigned={sid} system_generated=True reason=ai_preventive_accepted")


async def t_helper_creates_sala_per_tenant():
    print("\n[2] route_to_sala — cria SALA em tenant novo")
    cid_test = "co-redteam-sala"
    # Limpa estado anterior
    await db.collaborators.delete_one({"id": f"col-sala-{cid_test}"})
    doc = {"company_id": cid_test, "id": "tkt-redteam"}
    sid = await route_to_sala(doc, reason="preventive_auto")
    if sid != f"col-sala-{cid_test}":
        _fail(f"esperado col-sala-{cid_test}, veio {sid}")
    coll = await db.collaborators.find_one(
        {"id": sid}, {"_id": 0, "is_virtual": 1, "virtual_kind": 1})
    if not coll or coll.get("is_virtual") is not True:
        _fail(f"SALA do tenant {cid_test} nao foi criada como virtual: {coll}")
    _ok(f"SALA do tenant novo {cid_test} criada com is_virtual=True")
    # cleanup
    await db.collaborators.delete_one({"id": sid})


async def t_helper_invalid_reason():
    print("\n[3] route_to_sala — reason invalida vira system_other")
    doc = {"company_id": "co-demo"}
    await route_to_sala(doc, reason="bla bla nao existe")
    if doc.get("sala_route_reason") != "system_other":
        _fail(f"reason invalida nao foi normalizada: {doc.get('sala_route_reason')}")
    _ok("reason invalida -> system_other")


async def t_helper_missing_company():
    print("\n[4] route_to_sala — sem company_id explode")
    doc = {"id": "tkt-test"}
    try:
        await route_to_sala(doc, reason="preventive_auto")
        _fail("Deveria ter levantado ValueError sem company_id")
    except ValueError:
        _ok("ValueError esperado em doc sem company_id")


def t_audit_call_sites():
    print("\n[5] Audit: insertion sites importam sala_router")
    backend_root = "/app/backend"
    failures: list[str] = []
    for rel, reason in EXPECTED_SITES.items():
        if reason is None:
            # atlaz tem rota propria (_get_or_create_unassigned_inbox -> SALA)
            continue
        path = os.path.join(backend_root, rel)
        if not os.path.exists(path):
            failures.append(f"{rel} nao existe")
            continue
        src = open(path).read()
        if "from services.sala_router import route_to_sala" not in src:
            failures.append(f"{rel} NAO importa services.sala_router")
            continue
        if reason and f'reason="{reason}"' not in src and f"reason='{reason}'" not in src:
            failures.append(f"{rel} nao usa reason={reason!r}")
    if failures:
        for f in failures:
            print(f"  FAIL {f}")
        _fail(f"{len(failures)} site(s) sem SALA routing.")
    _ok(f"Todos os {len(EXPECTED_SITES) - 1} sites esperados importam route_to_sala.")


async def t_reasons_listed():
    print("\n[6] VALID_REASONS cobre todas as fontes esperadas")
    needed = {r for r in EXPECTED_SITES.values() if r is not None}
    missing = needed - VALID_REASONS
    if missing:
        _fail(f"Falta whitelist em VALID_REASONS: {missing}")
    _ok(f"{len(needed)} reasons whitelisted: {sorted(needed)}")


async def main():
    print("="*70)
    print("RED TEAM :: route_to_sala — toda nota sistemica -> SALA")
    print("="*70)
    await t_helper_basic_route()
    await t_helper_creates_sala_per_tenant()
    await t_helper_invalid_reason()
    await t_helper_missing_company()
    t_audit_call_sites()
    await t_reasons_listed()
    print("\n" + "="*70)
    print("PASS :: SALA routing instalado em todos os geradores citados.")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
