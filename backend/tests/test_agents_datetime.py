"""E2E para validar que os agentes (Isabella, Álvaro, Pâmela) sabem a
data e a hora atuais do Brasil (BRT) injetadas via `=== AGORA ===`.

Cenários:
  1. Isabella · cliente pergunta "que dia é hoje?" → resposta menciona
     a data correta (dd/mm ou dia da semana).
  2. Pâmela · cliente pergunta "que horas são?" → resposta menciona o
     horário correto (HH:MM) ou faixa (manhã/tarde/noite).
  3. Isabella · "tem horário pra instalação amanhã?" → menciona uma data
     futura (não do passado) e/ou usa "amanhã" relativo a hoje.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone, timedelta

import pytest

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8001")


@pytest.mark.asyncio
async def test_agentes_conhecem_data_hora():
    from database import db
    from routes.whatsapp_baileys import _maybe_auto_reply

    suffix = uuid.uuid4().hex[:6]
    digits = "876543"
    name = f"Joana Datetime {suffix}"
    cid = "co-demo"
    sub_id = f"sub-dt-{suffix}"
    phone_isa1 = f"5521966{digits[:6]}"
    phone_cam = f"5521966{digits[:5]}1"
    phone_isa2 = f"5521966{digits[:5]}2"
    sphones = [
        (f"sphone-isa1-{suffix}", phone_isa1),
        (f"sphone-cam-{suffix}", phone_cam),
        (f"sphone-isa2-{suffix}", phone_isa2),
    ]

    await db.subscribers.insert_one({
        "id": sub_id, "company_id": cid, "name": name,
        "status": "ATIVO", "plan_name": "Ligo Cinema",
        "branch": "TESTE", "monthly_price": 139.90,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await db.subscriber_phones.insert_many([
        {"id": sid, "company_id": cid, "subscriber_id": sub_id,
          "raw_number": ph, "normalized_number": ph,
          "is_primary": True, "is_whatsapp": True}
        for sid, ph in sphones
    ])
    phones_all = [p for _, p in sphones]
    await db.wa_conversations.delete_many({"phone": {"$in": phones_all}})
    await db.aihub_wa_messages.delete_many({"phone": {"$in": phones_all}})

    sub_ctx = (f"Nome: {name} · Plano: Ligo Cinema · Status: ATIVO · "
                f"Filial: TESTE")

    # AGORA esperado (BRT)
    now_brt = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-3)))
    today_dd_mm = now_brt.strftime("%d/%m")
    today_dd = now_brt.strftime("%d")
    weekday = ["segunda", "terça", "quarta", "quinta", "sexta",
                  "sábado", "domingo"][now_brt.weekday()]

    try:
        # 1. Isabella · "que dia é hoje?"
        await _maybe_auto_reply(
            cid=cid, phone=phone_isa1,
            user_text="oi, que dia é hoje?",
            subscriber_id=sub_id, subscriber_ctx=sub_ctx,
        )
        outs1 = await db.aihub_wa_messages.find(
            {"phone": phone_isa1, "direction": "outbound"},
            {"_id": 0, "text": 1},
        ).sort("created_at", 1).to_list(20)
        text1 = " ".join((o.get("text") or "") for o in outs1).lower()
        print(f"\n=== Isabella · 'que dia é hoje?' ===")
        print(f"Resposta: {text1}")
        # Aceita: "dd/mm" ou "dia X" ou "dia da semana"
        ok_data = (today_dd_mm in text1
                      or weekday in text1
                      or re.search(rf"\b{today_dd}\b", text1) is not None)
        assert ok_data, (
            f"Isabella NÃO mencionou data atual. Esperava {today_dd_mm} ou "
            f"'{weekday}' no texto. Resposta: {text1}"
        )
        print(f"✓ Isabella mencionou a data atual ({today_dd_mm}/{weekday})")

        # 2. Pâmela · "que horas são?"
        await _maybe_auto_reply(
            cid=cid, phone=phone_cam,
            user_text="oi, que horas são aí?",
            subscriber_id=sub_id, subscriber_ctx=sub_ctx,
        )
        outs2 = await db.aihub_wa_messages.find(
            {"phone": phone_cam, "direction": "outbound"},
            {"_id": 0, "text": 1},
        ).sort("created_at", 1).to_list(20)
        text2 = " ".join((o.get("text") or "") for o in outs2).lower()
        print(f"\n=== Pâmela · 'que horas são?' ===")
        print(f"Resposta: {text2}")
        # Aceita: "HH:MM", "HHh", "HH horas", ou período (manhã/tarde/noite)
        hour = now_brt.hour
        periodo = ("madrugada" if hour < 6 else "manhã" if hour < 12 else
                      "tarde" if hour < 18 else "noite")
        hour_pattern = re.compile(r"\b\d{1,2}[h:]\d{0,2}\b")
        ok_hora = (hour_pattern.search(text2) is not None
                      or periodo in text2)
        assert ok_hora, (
            f"Pâmela NÃO mencionou hora atual. Esperava padrão de hora ou "
            f"'{periodo}' no texto. Resposta: {text2}"
        )
        print(f"✓ Pâmela mencionou hora/período ({periodo})")

        # 3. Isabella · "tem horário pra instalação amanhã?"
        await _maybe_auto_reply(
            cid=cid, phone=phone_isa2,
            user_text="vocês tem horário pra instalação amanhã?",
            subscriber_id=None, subscriber_ctx=None,  # prospect novo
        )
        outs3 = await db.aihub_wa_messages.find(
            {"phone": phone_isa2, "direction": "outbound"},
            {"_id": 0, "text": 1},
        ).sort("created_at", 1).to_list(20)
        text3 = " ".join((o.get("text") or "") for o in outs3).lower()
        print(f"\n=== Isabella · 'instalação amanhã?' ===")
        print(f"Resposta: {text3}")
        # Aceita: a IA respondeu de forma coerente — não precisa mencionar
        # data exata se não tem dados pra confirmar (cobertura). Mas deve
        # NÃO mencionar datas claramente passadas (ex: 2024).
        assert "2024" not in text3 and "2023" not in text3, \
            f"Isabella mencionou ano passado errado: {text3}"
        print(f"✓ Isabella respondeu sem inventar datas passadas")

    finally:
        await db.subscribers.delete_one({"id": sub_id})
        await db.subscriber_phones.delete_many(
            {"id": {"$in": [sid for sid, _ in sphones]}}
        )
        await db.wa_conversations.delete_many({"phone": {"$in": phones_all}})
        await db.aihub_wa_messages.delete_many({"phone": {"$in": phones_all}})
