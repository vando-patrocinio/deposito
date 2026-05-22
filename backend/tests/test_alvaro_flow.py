"""E2E para o fluxo Álvaro auto-diagnóstico (SmartOLT → reboot → agendar).

Roda TUDO num único teste assíncrono pra evitar problema de event-loop
fechado do motor + pytest-asyncio entre fixtures.

Cobre:
  1. /api/smartolt/public/onu-diagnose/{phone}
  2. /api/lousa/public/available-slots
  3. format_diag_context produz bloco rico
  4. [REBOOT_ONU] removido + endpoint disparado
  5. [AGENDAR_REPARO:date,time] cria ticket de reparo
  6. extract_markers limpa [ROTEAR_*]
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import httpx
import pytest

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8001")


@pytest.mark.asyncio
async def test_alvaro_full_flow():
    from database import db
    from services.alvaro_tools import (
        diagnose_for_alvaro, fetch_available_slots,
        format_diag_context, process_alvaro_actions,
    )
    from services.marker_router import extract_markers

    suffix = uuid.uuid4().hex[:6]
    digits = "".join(ch for ch in suffix if ch.isdigit()) or "1"
    digits = (digits * 6)[:6]
    pppoe = f"alvaro{suffix}"  # apenas alnum, casa com _norm
    name_norm = pppoe.lower()
    name = f"Cliente Teste Alvaro {suffix}"
    phone = f"5521999{digits}"
    sub_id = f"sub-test-{suffix}"
    cid = "co-demo"
    sphone_id = f"sphone-test-{suffix}"
    onu_uid = f"HWTC-TEST-{suffix.upper()}"

    # ---- SETUP ----
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

    try:
        # 1. ENDPOINT diagnose
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{BACKEND}/api/smartolt/public/onu-diagnose/{phone}")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["found"] is True, data
        assert data["status"] == "online", data
        assert data["external_id"] == onu_uid
        assert data["subscriber_id"] == sub_id

        # 2. ENDPOINT available-slots
        async with httpx.AsyncClient(timeout=10.0) as c:
            r2 = await c.get(f"{BACKEND}/api/lousa/public/available-slots",
                                params={"company_id": cid, "days_ahead": 3})
        assert r2.status_code == 200
        opts = r2.json().get("options") or []
        assert opts, "deveria ter ao menos 1 slot"
        slot = opts[0]

        # 3. SERVICE diagnose_for_alvaro + context format
        diag = await diagnose_for_alvaro(phone, base_url=BACKEND)
        assert diag and diag.get("found") is True
        slots = await fetch_available_slots(cid, base_url=BACKEND)
        ctx = format_diag_context(diag, slots)
        assert "DIAGNÓSTICO TÉCNICO" in ctx
        assert "ONLINE" in ctx
        assert "HORÁRIOS DISPONÍVEIS" in ctx
        assert onu_uid in ctx

        # 4. [REBOOT_ONU] processado e removido
        raw1 = ("Oi! Vou reiniciar seu equipamento agora 🙂\n"
                  "Em 1-2 min testa pra mim?\n[REBOOT_ONU]")
        cleaned1 = await process_alvaro_actions(raw1, phone, diag,
                                                       base_url=BACKEND)
        assert "[REBOOT_ONU]" not in cleaned1
        assert "vou reiniciar" in cleaned1.lower()

        # 5. [AGENDAR_REPARO] cria ticket
        raw2 = (f"Combinado! Agendei a visita pra {slot['human']} ✅\n"
                  f"[AGENDAR_REPARO:date={slot['date']},time={slot['time']}]")
        cleaned2 = await process_alvaro_actions(raw2, phone, diag,
                                                       base_url=BACKEND)
        assert "[AGENDAR_REPARO" not in cleaned2

        tk = await db.tickets.find_one(
            {"origin_phone": phone, "origin_source": "alvaro_diagnose"},
            {"_id": 0},
        )
        assert tk is not None, "ticket de reparo NÃO foi criado"
        assert tk["scheduled_date"] == slot["date"]
        assert tk["scheduled_time"] == slot["time"]
        assert tk["type"] == "reparo"
        assert tk["status"] == "aberto"
        assert tk["client_snapshot"]["name"] == name
        assert tk["client_snapshot"]["smartolt_status"] == "online"

        # 6. marker_router strip de [ROTEAR_*]
        cleaned3, found = extract_markers(
            "Tudo bem! Vou passar para o suporte 🙂\n[ROTEAR_SUPORTE]",
        )
        assert "[ROTEAR_SUPORTE]" not in cleaned3
        assert "ROTEAR_SUPORTE" in found

    finally:
        # ---- CLEANUP ----
        await db.subscribers.delete_one({"id": sub_id})
        await db.subscriber_phones.delete_one({"id": sphone_id})
        await db.smartolt_onus.delete_one({"unique_external_id": onu_uid})
        await db.tickets.delete_many({"origin_phone": phone})
        await db.wa_conversations.delete_many({"phone": phone})
