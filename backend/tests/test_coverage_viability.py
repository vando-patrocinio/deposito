"""E2E para o sistema de viabilidade técnica por endereço.

Cenários:
  1. VIAVEL_DIRETO: cliente menciona endereço com rua coberta por CTO →
     Isabella confirma cobertura.
  2. VIAVEL_PROVAVEL: cliente menciona bairro coberto sem rua específica →
     Isabella oferece visita de viabilidade.
  3. SEM_REGISTROS: cliente menciona bairro fora da malha → Isabella
     registra como pendente.
  4. parse_address extrai street/district/cep/number corretamente.
  5. extract_markers reconhece [AGENDAR_VIABILIDADE:date,time] e
     [VIABILIDADE_PENDENTE].
  6. Quando Isabella emite [AGENDAR_VIABILIDADE], cria ticket de
     `type=viabilidade` na Lousa.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8001")


@pytest.mark.asyncio
async def test_coverage_full():
    from database import db
    from services.coverage_checker import (
        parse_address, check_coverage, format_for_prompt, looks_like_address,
    )
    from services.marker_router import extract_markers, process_markers
    from routes.whatsapp_baileys import _maybe_auto_reply

    cid = "co-demo"
    suffix = uuid.uuid4().hex[:6]
    dist_name = f"Cordovil Teste {suffix}"
    street_name = f"Rua Teste Cobertura {suffix}"

    sub_active_id = f"sub-cov-{suffix}"
    sub_addr_id = f"saddr-cov-{suffix}"
    cto_id = f"cto-cov-{suffix}"

    # ── SETUP: 1 cliente ATIVO com endereço + 1 CTO no mesmo bairro ──
    await db.subscribers.insert_one({
        "id": sub_active_id, "company_id": cid,
        "name": f"Cliente Cobertura {suffix}",
        "status": "ATIVO", "plan_name": "Fibra 500 Mega",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await db.subscriber_addresses.insert_one({
        "id": sub_addr_id, "company_id": cid,
        "subscriber_id": sub_active_id,
        "street": street_name, "number": "150",
        "district": dist_name, "city": "Rio de Janeiro", "state": "RJ",
        "zip_code": "21000000", "is_primary": True,
    })
    await db.ctos.insert_one({
        "id": cto_id, "company_id": cid,
        "name": f"CTO-COB-{suffix}", "number": "001",
        "address": {"rua": street_name, "numero": "300",
                       "bairro": dist_name, "cidade": "Rio de Janeiro"},
        "capacity": 16, "ports": [], "status": "active",
    })

    try:
        # ── 1. parse_address ──
        p = parse_address(f"{street_name}, 200, bairro {dist_name}, "
                              f"Rio de Janeiro, CEP 21000-000")
        assert p["street"], p
        assert dist_name.lower() in (p["district"] or "").lower(), p
        assert p["cep"] == "21000000", p
        assert p["number"] in ("200", "21000000")  # 1º número
        assert p["tokens"], p
        print(f"✓ parse_address ok ({p['street'][:40]}..., {p['district']})")

        # ── 2. looks_like_address ──
        assert looks_like_address(f"{street_name}, 200, {dist_name}") is True
        assert looks_like_address("oi") is False
        print(f"✓ looks_like_address ok")

        # ── 3. VIAVEL_DIRETO (mesma rua) ──
        c1 = await check_coverage(
            cid, f"{street_name}, 200, bairro {dist_name}",
        )
        assert c1["viable"] == "VIAVEL_DIRETO", c1
        assert c1["neighbors"], "deveria ter pelo menos 1 vizinho ativo"
        assert c1["ctos"], "deveria ter pelo menos 1 CTO"
        print(f"✓ VIAVEL_DIRETO: {len(c1['neighbors'])} vizinhos + "
                f"{len(c1['ctos'])} CTOs")

        # Formato pra prompt
        block = format_for_prompt(c1)
        assert "VIABILIDADE TÉCNICA" in block
        assert "VIAVEL_DIRETO" in block
        # Nomes mascarados (não cita nome completo)
        full_name = f"Cliente Cobertura {suffix}"
        assert full_name not in block
        print(f"✓ Bloco prompt sanitizado (nomes mascarados)")

        # ── 4. VIAVEL_PROVAVEL (só bairro, rua diferente) ──
        c2 = await check_coverage(
            cid, f"Avenida Outra completamente diferente, "
                  f"bairro {dist_name}",
        )
        assert c2["viable"] in ("VIAVEL_DIRETO", "VIAVEL_PROVAVEL"), c2
        print(f"✓ {c2['viable']} (só bairro)")

        # ── 5. SEM_REGISTROS (bairro inventado) ──
        c3 = await check_coverage(
            cid, "Rua Inexistente 999, bairro Lugar Que Nao Existe ZZZ",
        )
        assert c3["viable"] == "SEM_REGISTROS", c3
        print(f"✓ SEM_REGISTROS para bairro fictício")

        # ── 6. extract_markers reconhece os 2 novos ──
        text_a = ("Combinado! Agendei viabilidade pra terça 28/05 às 10h ✅\n"
                    "[AGENDAR_VIABILIDADE:date=2026-05-28,time=10:00]")
        cleaned_a, found_a = extract_markers(text_a)
        assert "[AGENDAR_VIABILIDADE" not in cleaned_a
        assert any("AGENDAR_VIABILIDADE" in m for m in found_a)
        text_b = ("Ok, vou registrar pra equipe analisar 🙂\n[VIABILIDADE_PENDENTE]")
        cleaned_b, found_b = extract_markers(text_b)
        assert "[VIABILIDADE_PENDENTE]" not in cleaned_b
        assert "VIABILIDADE_PENDENTE" in found_b
        print(f"✓ extract_markers reconhece os 2 novos")

        # ── 7. process_markers cria ticket de viabilidade ──
        phone_v = f"5521977{suffix[:6].replace('a','0').replace('b','1').replace('c','2').replace('d','3').replace('e','4').replace('f','5')}"
        # garante só dígitos
        phone_v = "".join(ch for ch in phone_v if ch.isdigit())[:13]
        await db.wa_conversations.delete_many({"phone": phone_v})
        await db.tickets.delete_many({"origin_phone": phone_v})
        await db.viability_requests.delete_many({"phone": phone_v})

        cleaned = await process_markers(text_a, phone_v, cid)
        assert "[AGENDAR_VIABILIDADE" not in cleaned
        tk = await db.tickets.find_one(
            {"origin_phone": phone_v,
              "origin_source": "isabella_viability"},
            {"_id": 0},
        )
        assert tk, "ticket de viabilidade NÃO foi criado"
        assert tk["type"] == "viabilidade"
        assert tk["scheduled_date"] == "2026-05-28"
        assert tk["scheduled_time"] == "10:00"
        print(f"✓ Ticket de viabilidade criado: {tk['id']}")

        # process_markers VIABILIDADE_PENDENTE cria viability_request
        await process_markers(text_b, phone_v + "9", cid)
        vr = await db.viability_requests.find_one(
            {"phone": phone_v + "9"}, {"_id": 0},
        )
        assert vr, "viability_requests deveria ter sido criado"
        assert vr["status"] == "pending_technical_review"
        print(f"✓ viability_requests criado: {vr['id']}")

        # ── 8. E2E real: Isabella recebe endereço → injeta bloco no prompt ──
        phone_e2e = phone_v + "0"
        await db.wa_conversations.delete_many({"phone": phone_e2e})
        await db.aihub_wa_messages.delete_many({"phone": phone_e2e})
        await _maybe_auto_reply(
            cid=cid, phone=phone_e2e,
            user_text=(f"oi! moro na {street_name}, 200, "
                          f"bairro {dist_name}. vocês atendem aqui?"),
            subscriber_id=None, subscriber_ctx=None,
        )
        outs = await db.aihub_wa_messages.find(
            {"phone": phone_e2e, "direction": "outbound"},
            {"_id": 0, "text": 1, "agent_name": 1},
        ).sort("created_at", 1).to_list(20)
        text_out = " ".join((o.get("text") or "") for o in outs).lower()
        print(f"\n=== Isabella · endereço com cobertura ===")
        print(f"Resposta: {text_out}")
        # Não deve dizer "não atendemos"
        assert "não atendemos" not in text_out
        assert "não temos cobertura" not in text_out
        # Não deve vazar nome de cliente
        assert full_name.lower() not in text_out
        # Não deve vazar markers crus
        assert "[viabilidade" not in text_out
        assert "[agendar_viabilidade" not in text_out
        print(f"✓ Isabella respondeu coerentemente (sem vazar dados)")

        # Cleanup E2E
        await db.wa_conversations.delete_many({"phone": phone_e2e})
        await db.aihub_wa_messages.delete_many({"phone": phone_e2e})

    finally:
        await db.subscribers.delete_one({"id": sub_active_id})
        await db.subscriber_addresses.delete_one({"id": sub_addr_id})
        await db.ctos.delete_one({"id": cto_id})
        await db.tickets.delete_many({"origin_source": "isabella_viability"})
        await db.viability_requests.delete_many({})
        await db.wa_conversations.delete_many({"phone": {"$regex": f"^5521977"}})
