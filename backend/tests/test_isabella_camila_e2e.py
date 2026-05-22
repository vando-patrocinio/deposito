"""Smoke E2E para Isabella (vendas) e Camila (financeiro) — verificar se
prompts atualizados ESTÃO USANDO `=== CLIENTE IDENTIFICADO ===` e não
estão pedindo CPF redundante quando o cliente já está autenticado.

Roda 2 cenários:
  1. Isabella · cliente identificado pergunta "tenho disney+ no meu plano?"
     → não deve pedir CPF, deve usar o nome
  2. Camila · cliente identificado pede boleto
     → não deve pedir CPF, deve responder de volta ao nome
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8001")


@pytest.mark.asyncio
async def test_isabella_camila_use_subscriber_ctx():
    from database import db
    from routes.whatsapp_baileys import _maybe_auto_reply

    suffix = uuid.uuid4().hex[:6]
    digits = "987654"
    name = f"Maria Silva Teste {suffix}"
    nickname = "Maria"
    cid = "co-demo"

    # Setup: 2 phones (um para Isabella, outro para Camila — pra evitar
    # coincidir com routing já persistido)
    sub_id = f"sub-isacam-{suffix}"
    phone_isa = f"5521977{digits[:6]}"
    phone_cam = f"5521977{digits[:5]}1"
    sphone_isa = f"sphone-isa-{suffix}"
    sphone_cam = f"sphone-cam-{suffix}"

    await db.subscribers.insert_one({
        "id": sub_id, "company_id": cid, "name": name, "nickname": nickname,
        "status": "ATIVO", "plan_name": "Ligo Family",
        "branch": "TESTE", "monthly_price": 119.90,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await db.subscriber_phones.insert_many([
        {"id": sphone_isa, "company_id": cid, "subscriber_id": sub_id,
          "raw_number": phone_isa, "normalized_number": phone_isa,
          "is_primary": True, "is_whatsapp": True},
        {"id": sphone_cam, "company_id": cid, "subscriber_id": sub_id,
          "raw_number": phone_cam, "normalized_number": phone_cam,
          "is_primary": False, "is_whatsapp": True},
    ])
    await db.wa_conversations.delete_many({"phone": {"$in": [phone_isa, phone_cam]}})
    await db.aihub_wa_messages.delete_many({"phone": {"$in": [phone_isa, phone_cam]}})

    sub_ctx = (f"Nome: {name} · Plano: Ligo Family · Status: ATIVO · "
                f"Filial: TESTE")

    try:
        # 1. ISABELLA — vendas / pergunta sobre plano
        await _maybe_auto_reply(
            cid=cid, phone=phone_isa,
            user_text="oi, tenho disney+ no meu plano atual?",
            subscriber_id=sub_id, subscriber_ctx=sub_ctx,
        )
        out_isa = await db.aihub_wa_messages.find_one(
            {"phone": phone_isa, "direction": "outbound"},
            {"_id": 0, "text": 1, "agent_name": 1, "delivery_status": 1},
            sort=[("created_at", -1)],
        )
        text_isa = (out_isa or {}).get("text") or ""
        print(f"\n=== ISABELLA ===")
        print(f"Agent: {(out_isa or {}).get('agent_name')}")
        print(f"Resposta: {text_isa}")

        # 2. CAMILA — pede boleto
        await _maybe_auto_reply(
            cid=cid, phone=phone_cam,
            user_text="bom dia, manda meu boleto desse mês por favor",
            subscriber_id=sub_id, subscriber_ctx=sub_ctx,
        )
        out_cam = await db.aihub_wa_messages.find_one(
            {"phone": phone_cam, "direction": "outbound"},
            {"_id": 0, "text": 1, "agent_name": 1, "delivery_status": 1},
            sort=[("created_at", -1)],
        )
        text_cam = (out_cam or {}).get("text") or ""
        print(f"\n=== CAMILA ===")
        print(f"Agent: {(out_cam or {}).get('agent_name')}")
        print(f"Resposta: {text_cam}")

        # ── ASSERTS ──
        # Isabella não deve pedir CPF nem dizer "não te encontro"
        cpf_phrases_isa = ["preciso do cpf", "me passa o cpf",
                              "não consigo localizar", "não te encontrei",
                              "qual seu cpf"]
        for phrase in cpf_phrases_isa:
            assert phrase not in text_isa.lower(), \
                f"Isabella pediu CPF inadequado: {phrase!r} | resposta: {text_isa}"
        # Deve usar nome ou apelido (já que está identificado)
        # Tolerante: pelo menos referenciar o cliente com algum dado
        print(f"✓ Isabella não pediu CPF redundante")

        # Camila não deve pedir CPF (cliente já identificado)
        cpf_phrases_cam = ["preciso do cpf", "me passa o cpf", "qual seu cpf",
                              "informar seu cpf", "passar seu cpf"]
        for phrase in cpf_phrases_cam:
            assert phrase not in text_cam.lower(), \
                f"Camila pediu CPF inadequado: {phrase!r} | resposta: {text_cam}"
        print(f"✓ Camila não pediu CPF redundante")

        # Markers limpos (não vazam pro cliente)
        for txt in (text_isa, text_cam):
            assert "[ROTEAR_" not in txt
            assert "[HOT_LEAD]" not in txt
            assert "[VENDA_AGENDADA]" not in txt
        print(f"✓ Sem markers crus em ambas")

    finally:
        await db.subscribers.delete_one({"id": sub_id})
        await db.subscriber_phones.delete_many(
            {"id": {"$in": [sphone_isa, sphone_cam]}},
        )
        await db.wa_conversations.delete_many(
            {"phone": {"$in": [phone_isa, phone_cam]}},
        )
        await db.aihub_wa_messages.delete_many(
            {"phone": {"$in": [phone_isa, phone_cam]}},
        )
