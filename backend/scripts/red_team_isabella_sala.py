"""red_team_isabella_sala.py — Zero-Mocks ponta-a-ponta SALA.

Valida que TODA bolha agendada pela Isabella vai pra Lousa SALA, com
slot CRAVADO DENTRO da janela oferecida, e que esgotar a janela
retorna mensagem ao cliente.

Cobertura:
  1. Agendar manhã → ticket cai em SALA com hora 09h (primeiro slot livre).
  2. Segundo agendar manhã → 10h (próximo slot livre).
  3. Terceiro agendar manhã → 11h (último slot).
  4. Quarto agendar manhã → JANELA CHEIA (texto ao cliente).
  5. Agendar tarde → 13h (slot livre).
  6. Ticket cai na Lousa SALA, não em técnico real.
  7. needs_assignment_review=True (atendimento especializado distribui).
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db
from services.isabella_actions import execute_action_markers, _ensure_sala


CID = "co-demo"
PHONE = "5521900099887"
DATE = "2026-07-15"


def _ok(m): print(f"  ✅ {m}")
def _fail(m):
    print(f"  ❌ {m}")
    raise AssertionError(m)


async def _cleanup():
    await db.tickets.delete_many({
        "company_id": CID, "phone": PHONE,
        "created_by": "isabella",
    })


async def t1_sala_exists():
    print("\n[1] Lousa SALA garantida")
    sid = await _ensure_sala(CID)
    sala = await db.collaborators.find_one(
        {"id": sid, "company_id": CID}, {"_id": 0})
    if not sala:
        _fail("SALA não existe em collaborators")
    if not sala.get("is_virtual"):
        _fail("SALA não marcada is_virtual")
    if sala.get("name") != "SALA":
        _fail(f"name esperado SALA, got {sala.get('name')}")
    _ok(f"SALA id={sid} virtual_kind={sala.get('virtual_kind')}")


async def _agendar(window: str):
    reply = (f"Ok! [AGENDAR_VISITA data={DATE} "
             f"janela={window} motivo=\"redteam\"]")
    out, actions = await execute_action_markers(
        reply_text=reply, company_id=CID, phone=PHONE,
        subscriber_id="sub-rt", subscriber_name="RED TEAM")
    return out, actions


async def t2_manha_slots_sequentes():
    print("\n[2] Slots manhã: 09h → 10h → 11h sequencialmente")
    expected = ["09h", "10h", "11h"]
    for i, slot in enumerate(expected, 1):
        out, actions = await _agendar("manha")
        if not actions or actions[0]["type"] != "schedule_visit":
            _fail(f"agendamento #{i} falhou: actions={actions}")
        got = actions[0]["slot_label"]
        if got != slot:
            _fail(f"#{i} slot esperado {slot}, got {got}")
        if f"às {slot}" not in out:
            _fail(f"#{i} texto cliente não menciona slot: {out}")
        _ok(f"agendamento #{i}: slot={got} · texto: {out!r}")


async def t3_manha_cheia():
    print("\n[3] Quarto agendamento manhã → JANELA CHEIA")
    out, actions = await _agendar("manha")
    if not actions:
        _fail("nenhuma action retornada")
    if actions[0]["type"] != "schedule_visit_failed":
        _fail(f"deveria ter falhado, mas: {actions[0]}")
    if actions[0].get("reason") != "window_full":
        _fail(f"reason esperado window_full, got {actions[0].get('reason')}")
    if "cheia" not in out.lower():
        _fail(f"texto não comunica janela cheia: {out}")
    _ok(f"window_full sinalizado · texto: {out!r}")


async def t4_tarde_livre():
    print("\n[4] Tarde livre → slot 13h")
    out, actions = await _agendar("tarde")
    if not actions or actions[0]["type"] != "schedule_visit":
        _fail(f"falhou: {actions}")
    if actions[0]["slot_label"] != "13h":
        _fail(f"esperado 13h, got {actions[0]['slot_label']}")
    _ok(f"tarde slot=13h · {out!r}")


async def t5_tickets_em_sala():
    print("\n[5] Todos os tickets ficaram na SALA")
    cursor = db.tickets.find(
        {"company_id": CID, "phone": PHONE, "created_by": "isabella"},
        {"_id": 0, "short_id": 1, "assigned_collaborator_id": 1,
         "scheduled_time": 1, "needs_assignment_review": 1,
         "scheduled_slot_label": 1})
    rows = [t async for t in cursor]
    if len(rows) != 4:
        _fail(f"esperado 4 tickets, got {len(rows)}")
    for t in rows:
        if t["assigned_collaborator_id"] != "col-sala":
            _fail(f"ticket {t['short_id']} não está em SALA: "
                  f"{t['assigned_collaborator_id']}")
        if not t["needs_assignment_review"]:
            _fail(f"{t['short_id']} sem needs_assignment_review")
    # slot times distintos
    times = [t["scheduled_time"] for t in rows]
    if len(set(times)) != 4:
        _fail(f"horários duplicados em SALA: {times}")
    _ok(f"4 tickets em SALA, horários únicos: "
         f"{sorted(t['scheduled_slot_label'] for t in rows)}")


async def t6_lousa_query_sala():
    print("\n[6] Query Lousa SALA traz as bolhas no dia certo")
    q = {"assigned_collaborator_id": "col-sala",
         "status": {"$in": ["pendente", "aberta",
                              "aguardando_atendimento"]},
         "scheduled_time": {"$regex": f"^{DATE}"}}
    n = await db.tickets.count_documents(q)
    if n < 4:
        _fail(f"Lousa SALA deveria ter ≥4 do dia {DATE}, got {n}")
    _ok(f"Lousa SALA do dia {DATE}: {n} bolha(s)")


async def main():
    print("══════════ RED-TEAM ISABELLA × SALA ══════════")
    await _cleanup()
    try:
        await t1_sala_exists()
        await t2_manha_slots_sequentes()
        await t3_manha_cheia()
        await t4_tarde_livre()
        await t5_tickets_em_sala()
        await t6_lousa_query_sala()
        print("\n══════════ ✅ TUDO VERDE ══════════")
    finally:
        await _cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
