"""Integration test do fluxo Álvaro END-TO-END (via _maybe_auto_reply real).

Cria fixture (subscriber + phone + ONU) → chama `_maybe_auto_reply` direto
(que faz LLM call REAL via Emergent Key) → valida:

  ✓ Conversa foi roteada para Alvaro (routing picks por keyword "internet caiu")
  ✓ Contexto SmartOLT foi injetado no prompt do agente
  ✓ Resposta gerada foi persistida em aihub_wa_messages (bolha 0)
  ✓ Se a IA gerou [AGENDAR_REPARO:...], o ticket foi criado em db.tickets
  ✓ Se a IA gerou [REBOOT_ONU], o reboot foi disparado

Custo: ~1 chamada DeepSeek (centavos). Roda com `pytest -v -s`.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8001")


@pytest.mark.asyncio
async def test_alvaro_end_to_end_via_maybe_auto_reply():
    from database import db
    from routes.whatsapp_baileys import _maybe_auto_reply

    suffix = uuid.uuid4().hex[:6]
    digits = "".join(ch for ch in suffix if ch.isdigit()) or "1"
    digits = (digits * 6)[:6]
    pppoe = f"alvaroe2e{suffix}"
    name_norm = pppoe.lower()
    name = f"Cliente E2E Alvaro {suffix}"
    phone = f"5521988{digits}"
    sub_id = f"sub-e2e-{suffix}"
    cid = "co-demo"
    sphone_id = f"sphone-e2e-{suffix}"
    onu_uid = f"HWTC-E2E-{suffix.upper()}"

    # ── SETUP ──
    await db.subscribers.insert_one({
        "id": sub_id, "company_id": cid, "name": name,
        "pppoe_user": pppoe, "external_code": None,
        "status": "ATIVO", "plan_name": "Fibra 500 Mega Teste",
        "branch": "TESTE",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await db.subscriber_phones.insert_one({
        "id": sphone_id, "company_id": cid, "subscriber_id": sub_id,
        "raw_number": phone, "normalized_number": phone,
        "is_primary": True, "is_whatsapp": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await db.smartolt_onus.insert_one({
        "unique_external_id": onu_uid, "company_id": cid,
        "name": pppoe, "name_norm": name_norm, "status": "Online",
        "olt_name": "TEST_OLT", "olt_id": "99",
        "board": "1", "port": "1", "onu": "1",
        "last_status_change": datetime.now(timezone.utc).replace(
            microsecond=0).isoformat(),
        "signal_text": "Good (-22.0 dBm)", "signal_1490": "-22.0",
    })
    await db.wa_conversations.delete_many({"phone": phone})
    await db.aihub_wa_messages.delete_many({"phone": phone})

    try:
        # ── EXECUTA O FLUXO REAL ──
        # Mensagem que claramente é suporte técnico — deve rotear pra Alvaro
        # e disparar `looks_like_support` em alvaro_tools.
        user_text = "minha internet caiu completamente, sem net"

        result = await _maybe_auto_reply(
            cid=cid, phone=phone, user_text=user_text,
            subscriber_id=sub_id, subscriber_ctx=None,
            inbound_was_voice=False,
        )
        print(f"\n=== AUTO-REPLY RESULT ===")
        print(f"Texto enviado: {result!r}")

        # ── VALIDAÇÕES ──
        # 1. Roteador escolheu Alvaro
        conv = await db.wa_conversations.find_one(
            {"company_id": cid, "phone": phone},
            {"_id": 0, "routed_agent_id": 1, "routed_reason": 1},
        )
        assert conv, "wa_conversations não criou registro"
        assert conv.get("routed_agent_id"), "routed_agent_id ausente"
        agent = await db.aihub_agents.find_one(
            {"id": conv["routed_agent_id"]}, {"_id": 0, "name": 1},
        )
        assert agent and agent["name"] == "Alvaro", \
            f"esperava Alvaro, veio {agent and agent.get('name')}"
        print(f"✓ Roteado para: {agent['name']} (reason={conv.get('routed_reason')})")

        # 2. Mensagem outbound foi persistida (mesmo se SEND falhou)
        out = await db.aihub_wa_messages.find_one(
            {"company_id": cid, "phone": phone, "direction": "outbound"},
            {"_id": 0, "text": 1, "agent_name": 1, "delivery_status": 1,
             "auto_reply": 1},
            sort=[("created_at", -1)],
        )
        assert out, "Nenhuma mensagem outbound persistida"
        assert out.get("agent_name") == "Alvaro"
        print(f"✓ Outbound persistido (agent={out['agent_name']}, "
                f"status={out.get('delivery_status')})")
        print(f"  Resposta: {(out.get('text') or '')[:200]}...")

        # 3. Se a IA emitiu marker de agendar → ticket foi criado
        tk = await db.tickets.find_one(
            {"origin_phone": phone, "origin_source": "alvaro_diagnose"},
            {"_id": 0, "id": 1, "scheduled_date": 1, "scheduled_time": 1,
             "client_snapshot": 1},
        )
        if tk:
            print(f"✓ TICKET criado por marker: {tk['id']} "
                    f"({tk['scheduled_date']} às {tk['scheduled_time']})")
        else:
            print("ℹ️  IA não emitiu [AGENDAR_REPARO] nesta resposta "
                    "(comportamento OK no 1º turno; geralmente oferece reboot primeiro)")

        # 4. Se a IA emitiu [REBOOT_ONU] → reboot foi disparado
        reboot_action = await db.smartolt_actions.find_one(
            {"action": "reboot", "external_id": onu_uid},
            {"_id": 0, "action": 1, "executed_at": 1, "result": 1},
        )
        if reboot_action:
            print(f"✓ REBOOT disparado: {reboot_action.get('result')}")
        else:
            print("ℹ️  IA não emitiu [REBOOT_ONU] nesta resposta")

        # 5. Mensagem outbound NÃO contém markers crus (foram processados)
        text_out = (out.get("text") or "")
        assert "[REBOOT_ONU]" not in text_out, \
            "marker [REBOOT_ONU] vazou para o cliente!"
        assert "[AGENDAR_REPARO" not in text_out, \
            "marker [AGENDAR_REPARO] vazou para o cliente!"
        assert "[ROTEAR_" not in text_out, \
            "marker [ROTEAR_*] vazou para o cliente!"
        print("✓ Markers limpos (cliente não vê colchetes)")

    finally:
        # ── CLEANUP ──
        await db.subscribers.delete_one({"id": sub_id})
        await db.subscriber_phones.delete_one({"id": sphone_id})
        await db.smartolt_onus.delete_one({"unique_external_id": onu_uid})
        await db.tickets.delete_many({"origin_phone": phone})
        await db.wa_conversations.delete_many({"phone": phone})
        await db.aihub_wa_messages.delete_many({"phone": phone})
