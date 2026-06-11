"""TEST ISABELLA ACTIONS — valida criação real de tickets na Lousa
via marcadores emitidos pelo LLM. Zero mocks. MongoDB real."""

NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import db
from services.isabella_actions import (actions_prompt_block,
                                            execute_action_markers)


async def test_agendar_visita():
    print("\n[1] [AGENDAR_VISITA] cria ticket real na Lousa")
    cid = "co-demo"
    phone = f"5511{uuid.uuid4().hex[:8]}"
    reply = ('Beleza, amanhã manhã. '
             '[AGENDAR_VISITA data=2026-02-11 janela=manha '
             'motivo="sinal não vinculado"]')
    cleaned, actions = await execute_action_markers(
        reply_text=reply, company_id=cid, phone=phone,
        subscriber_id="sub-pamela", subscriber_name="Pamela Nery")
    assert "[AGENDAR_VISITA" not in cleaned, "marcador não foi removido"
    assert len(actions) == 1
    assert actions[0]["type"] == "schedule_visit"
    short_id = actions[0]["short_id"]
    assert short_id in cleaned, f"protocolo {short_id} não no reply"
    assert "11/02" in cleaned, f"data não formatada: {cleaned}"
    print(f"  ✅ reply: {cleaned}")
    # Verify ticket real
    tk = await db.tickets.find_one(
        {"id": actions[0]["ticket_id"]}, {"_id": 0})
    assert tk is not None, "ticket não persistiu"
    assert tk["type"] == "visita_tecnica"
    assert tk["scheduled_date"] == "2026-02-11"
    assert tk["scheduled_window"] == "manha"
    assert tk["status"] == "AGENDADO"
    assert tk["subscriber_id"] == "sub-pamela"
    assert tk["source"] == "isabella_whatsapp"
    print(f"  ✅ ticket persistido: id={tk['id']} status={tk['status']} "
          f"scheduled={tk['scheduled_time']}")
    # cleanup
    await db.tickets.delete_one({"id": tk["id"]})


async def test_abrir_chamado():
    print("\n[2] [ABRIR_CHAMADO] cria ticket sem agendamento")
    cid = "co-demo"
    phone = f"5511{uuid.uuid4().hex[:8]}"
    reply = ('Vou repassar pro técnico. '
             '[ABRIR_CHAMADO tipo=tecnico motivo="sinal lento"]')
    cleaned, actions = await execute_action_markers(
        reply_text=reply, company_id=cid, phone=phone,
        subscriber_id="sub-vando", subscriber_name="Vando")
    assert "[ABRIR_CHAMADO" not in cleaned
    assert actions[0]["type"] == "open_ticket"
    assert actions[0]["short_id"] in cleaned
    print(f"  ✅ reply: {cleaned}")
    tk = await db.tickets.find_one({"id": actions[0]["ticket_id"]},
                                       {"_id": 0})
    assert tk["type"] == "chamado_tecnico"
    assert tk["status"] == "ABERTO"
    await db.tickets.delete_one({"id": tk["id"]})
    print(f"  ✅ chamado_tecnico persistido")


async def test_no_marker_passthrough():
    print("\n[3] sem marcador → texto inalterado")
    cleaned, actions = await execute_action_markers(
        reply_text="Tudo certo, te aviso quando tiver retorno.",
        company_id="co-demo", phone="5511000")
    assert cleaned == "Tudo certo, te aviso quando tiver retorno."
    assert not actions
    print(f"  ✅ passthrough ok")


async def test_humanizer_integration():
    print("\n[4] humanize_reply executa o marcador (integração)")
    from services.humanizer import humanize_reply
    cid = "co-demo"
    phone = f"5511{uuid.uuid4().hex[:8]}"
    ctx = {
        "link_for_guard": {"subscriber_id": "sub-test",
                             "subscriber_name": "Teste"},
    }
    reply = ('Marquei sim. '
             '[AGENDAR_VISITA data=2026-02-12 janela=tarde motivo="upgrade"]')
    out = await humanize_reply(
        reply_text=reply, ctx=ctx, company_id=cid, phone=phone)
    assert "[AGENDAR_VISITA" not in out
    assert "13h" in out or "12/02" in out
    print(f"  ✅ via humanize_reply: {out}")
    # cleanup any ticket created
    await db.tickets.delete_many(
        {"phone": phone, "source": "isabella_whatsapp"})


def test_actions_prompt_block():
    print("\n[5] actions_prompt_block — está no system prompt")
    block = actions_prompt_block()
    assert "AGENDAR_VISITA" in block
    assert "ABRIR_CHAMADO" in block
    assert "EXECUTE" in block
    assert "manha" in block and "tarde" in block
    print(f"  ✅ bloco ok ({len(block)} chars)")


async def main():
    await test_agendar_visita()
    await test_abrir_chamado()
    await test_no_marker_passthrough()
    await test_humanizer_integration()
    test_actions_prompt_block()
    print("\n=== 5/5 PASSED ✅ ===")


if __name__ == "__main__":
    asyncio.run(main())
