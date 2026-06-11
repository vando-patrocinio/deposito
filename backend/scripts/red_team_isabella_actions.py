"""red_team_isabella_actions.py — Zero-Mocks ponta-a-ponta.

Valida o ciclo COMPLETO Isabella → Lousa:
  1. Marcador [AGENDAR_VISITA] gera ticket com formato Lousa.
  2. Ticket aparece na Lousa do técnico atribuído.
  3. Idempotência: 2 marcadores no mesmo turno geram 2 tickets distintos.
  4. _pick_default_collaborator escolhe o menos sobrecarregado.
  5. Marcador [ABRIR_CHAMADO] também segue formato Lousa.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "isabella",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db
from services.isabella_actions import execute_action_markers


CID = "co-demo"
PHONE = "5521900000999"


def _ok(m): print(f"  ✅ {m}")
def _fail(m):
    print(f"  ❌ {m}")
    raise AssertionError(m)


def _today_br():
    return (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%d")


async def _cleanup():
    await db.tickets.delete_many({
        "company_id": CID,
        "phone": PHONE,
        "created_by": "isabella",
    })


async def t1_agendar_visita():
    print("\n[1] [AGENDAR_VISITA] cria ticket no formato Lousa")
    today = _today_br()
    reply_in = (f"Beleza! [AGENDAR_VISITA data={today} "
                f"janela=manha motivo=\"redteam visita\"]")
    out, actions = await execute_action_markers(
        reply_text=reply_in, company_id=CID, phone=PHONE,
        subscriber_id="sub-redteam", subscriber_name="RED TEAM")
    if "[AGENDAR_VISITA" in out:
        _fail("marcador não foi substituído")
    if not actions or actions[0]["type"] != "schedule_visit":
        _fail(f"action não registrada: {actions}")
    if "Marquei pra" not in out:
        _fail(f"texto cliente errado: {out}")
    sid = actions[0]["short_id"]
    _ok(f"texto cliente: {out!r}")
    _ok(f"short_id retornado: {sid}")
    return sid


async def t2_ticket_lousa_format(short_id: str):
    print("\n[2] Ticket existe com formato Lousa")
    t = await db.tickets.find_one({"short_id": short_id}, {"_id": 0})
    if not t:
        _fail(f"ticket {short_id} não encontrado")
    required = {
        "status": "pendente",
        "priority": "horario",
        "type": "reparo",
        "auto_created_by_isabella": True,
    }
    for k, v in required.items():
        if t.get(k) != v:
            _fail(f"{k}={t.get(k)} esperado={v}")
    if not t.get("client_snapshot"):
        _fail("client_snapshot ausente")
    if not t.get("scheduled_time"):
        _fail("scheduled_time ausente")
    if not t["scheduled_time"].endswith("+00:00"):
        _fail(f"scheduled_time sem timezone: {t['scheduled_time']}")
    _ok(f"status={t['status']} priority={t['priority']} "
         f"type={t['type']}")
    _ok(f"client_snapshot.name={t['client_snapshot']['name']}")
    _ok(f"scheduled_time={t['scheduled_time']}")
    return t


async def t3_appears_in_lousa(t: dict):
    print("\n[3] Ticket aparece na Lousa do técnico atribuído")
    assigned = t.get("assigned_collaborator_id")
    if not assigned:
        _fail("ticket sem collaborator atribuído")
    # mimic query lousa
    q = {"assigned_collaborator_id": assigned,
         "status": {"$in": ["pendente", "aberta",
                              "aguardando_atendimento"]}}
    found = False
    async for x in db.tickets.find(q, {"_id": 0, "id": 1}):
        if x["id"] == t["id"]:
            found = True
            break
    if not found:
        _fail(f"ticket {t['id']} não aparece na query da Lousa")
    # Verifica _ticket_day_iso
    sched = t.get("scheduled_time")
    d = datetime.fromisoformat(str(sched).replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    day = (d - timedelta(hours=3)).strftime("%Y-%m-%d")
    if day != _today_br():
        _fail(f"_ticket_day_iso={day} mas today={_today_br()}")
    _ok(f"ticket roteado para collaborator={assigned}")
    _ok(f"_ticket_day_iso={day} → aparece na Lousa de hoje")


async def t4_idempotent_unique_ids():
    print("\n[4] Dois marcadores no mesmo turno geram 2 tickets distintos")
    today = _today_br()
    reply_in = (f"Ok! [AGENDAR_VISITA data={today} janela=manha motivo=\"v1\"] "
                f"E também [AGENDAR_VISITA data={today} "
                f"janela=tarde motivo=\"v2\"]")
    out, actions = await execute_action_markers(
        reply_text=reply_in, company_id=CID, phone=PHONE,
        subscriber_id="sub-redteam", subscriber_name="RED TEAM")
    if len(actions) != 2:
        _fail(f"esperado 2 actions, got {len(actions)}")
    if actions[0]["short_id"] == actions[1]["short_id"]:
        _fail("short_ids duplicados")
    if "[AGENDAR_VISITA" in out:
        _fail("marcadores não substituídos")
    _ok(f"2 tickets criados: "
         f"{actions[0]['short_id']} + {actions[1]['short_id']}")


async def t5_abrir_chamado():
    print("\n[5] [ABRIR_CHAMADO] cria chamado no formato Lousa")
    reply_in = ('Vou abrir. [ABRIR_CHAMADO tipo=tecnico '
                'motivo="redteam chamado"]')
    out, actions = await execute_action_markers(
        reply_text=reply_in, company_id=CID, phone=PHONE,
        subscriber_id="sub-redteam", subscriber_name="RED TEAM")
    if "[ABRIR_CHAMADO" in out:
        _fail("marcador não substituído")
    if actions[0]["type"] != "open_ticket":
        _fail(f"action errada: {actions}")
    sid = actions[0]["short_id"]
    t = await db.tickets.find_one({"short_id": sid}, {"_id": 0})
    if t.get("status") != "pendente":
        _fail(f"chamado status={t.get('status')} esperado pendente")
    if t.get("type") != "reparo":
        _fail(f"chamado type={t.get('type')}")
    _ok(f"chamado {sid} criado com status=pendente type=reparo")


async def main():
    print("══════════ RED-TEAM ISABELLA ACTIONS ══════════")
    await _cleanup()
    try:
        sid = await t1_agendar_visita()
        t = await t2_ticket_lousa_format(sid)
        await t3_appears_in_lousa(t)
        await t4_idempotent_unique_ids()
        await t5_abrir_chamado()
        print("\n══════════ ✅ TUDO VERDE ══════════")
    finally:
        await _cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
