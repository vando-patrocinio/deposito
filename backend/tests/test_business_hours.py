"""E2E para validar:
1. Endpoints GET/PUT /api/whatsapp-baileys/business-hours
2. Bloco `=== HORÁRIO COMERCIAL ===` injetado no prompt
3. IA respeita o status (ABERTO/FECHADO) ao responder pedido de humano
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta

import httpx
import pytest

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8001")


@pytest.mark.asyncio
async def test_business_hours_full():
    from database import db
    from services.business_hours import (
        compute_status, get_business_hours, set_business_hours,
        format_for_prompt,
    )
    from routes.whatsapp_baileys import _maybe_auto_reply

    cid = "co-demo"
    suffix = uuid.uuid4().hex[:6]
    digits = "765432"
    name = f"Roberto BH {suffix}"
    sub_id = f"sub-bh-{suffix}"
    phone1 = f"5521955{digits[:6]}"
    phone2 = f"5521955{digits[:5]}1"
    sphones = [
        (f"sphone-bh1-{suffix}", phone1),
        (f"sphone-bh2-{suffix}", phone2),
    ]

    # Backup config atual
    orig_cfg = await get_business_hours(cid)

    await db.subscribers.insert_one({
        "id": sub_id, "company_id": cid, "name": name,
        "status": "ATIVO", "plan_name": "Ligo Family",
        "branch": "TESTE",
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
    sub_ctx = (f"Nome: {name} · Plano: Ligo Family · Status: ATIVO · "
                f"Filial: TESTE")

    try:
        # ── 1. Endpoints GET/PUT (via process direto) ──
        cfg = await get_business_hours(cid)
        assert cfg["timezone_offset_hours"] == -3
        assert "1" in cfg["weekly_schedule"]  # segunda

        # PUT custom: força FECHADO em todos os dias
        all_off_schedule = {str(i): {"enabled": False} for i in range(7)}
        await set_business_hours(cid, {
            "enabled": True,
            "timezone_offset_hours": -3,
            "weekly_schedule": all_off_schedule,
            "fora_de_hora_message": (
                "Estamos OFFLINE. Resolvo tudo aqui pelo chat 🙂"
            ),
        }, by="test")
        cfg2 = await get_business_hours(cid)
        st2 = compute_status(cfg2)
        assert st2["is_open"] is False
        assert st2["status"] == "closed_today"
        print(f"✓ Force-closed: {st2['status']}")

        # Bloco prompt deve conter "FECHADO"/"FORA DE HORÁRIO"
        block = await format_for_prompt(cid)
        assert "FORA DE HORÁRIO" in block or "FECHADO" in block
        assert "Estamos OFFLINE" in block
        print(f"✓ Bloco contém status FECHADO + mensagem custom")

        # ── 2. IA respeita status FECHADO quando cliente pede humano ──
        await _maybe_auto_reply(
            cid=cid, phone=phone1,
            user_text="oi, preciso falar com um atendente humano agora",
            subscriber_id=sub_id, subscriber_ctx=sub_ctx,
        )
        # Pega TODAS bolhas da rodada (IA divide em chunks)
        outs = await db.aihub_wa_messages.find(
            {"phone": phone1, "direction": "outbound"},
            {"_id": 0, "text": 1},
        ).sort("created_at", 1).to_list(20)
        text1 = " ".join((o.get("text") or "") for o in outs).lower()
        print(f"\n=== IA · cliente pede humano (FECHADO) ===")
        print(f"Resposta: {text1}")
        # Não deve prometer humano agora (algumas variações aceitas)
        bad_phrases = [
            "humano vai te chamar agora", "atendente já vai falar",
            "vou te transferir agora",
        ]
        for ph in bad_phrases:
            assert ph not in text1, f"IA prometeu humano agora: {ph!r}"
        # Deve ter sinal de "fora do horário" OU "resolvo aqui" OU
        # mencionar próxima abertura
        ok_keywords = ["fora do horário", "fora do expediente",
                          "fechado", "offline", "resolvo aqui",
                          "resolver aqui", "amanhã", "próxima",
                          "aqui pelo chat"]
        assert any(k in text1 for k in ok_keywords), \
            f"IA não reconheceu fechamento: {text1}"
        print(f"✓ IA respondeu coerentemente fora do horário")

        # ── 3. Voltar ao default + status open agora ──
        always_open = {str(i): {"enabled": True, "open": "00:00",
                                       "close": "23:59"} for i in range(7)}
        await set_business_hours(cid, {
            "enabled": True,
            "timezone_offset_hours": -3,
            "weekly_schedule": always_open,
            "fora_de_hora_message": "default",
        }, by="test")
        st3 = compute_status(await get_business_hours(cid))
        assert st3["is_open"] is True
        assert st3["status"] == "open"
        print(f"✓ Force-open: {st3['status']}")

    finally:
        # restaura config original
        await set_business_hours(cid, orig_cfg, by="test:cleanup")
        await db.subscribers.delete_one({"id": sub_id})
        await db.subscriber_phones.delete_many(
            {"id": {"$in": [sid for sid, _ in sphones]}}
        )
        await db.wa_conversations.delete_many({"phone": {"$in": phones_all}})
        await db.aihub_wa_messages.delete_many({"phone": {"$in": phones_all}})
