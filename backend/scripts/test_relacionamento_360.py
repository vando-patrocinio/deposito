"""OPERAÇÃO RELACIONAMENTO 360° — Prova de fogo Zero-Mocks.

Simula um turno real da Isabella exercitando todos os fixes:
  F3. register_isabella_outcome
  F4. schedule_followup
  F5. relationship_memory_block
  F6. universo_ligo_contextual_pitch
  F7. encerramento_humanizado + log_closing
  F8. detect_and_reopen_case

Tudo em DB real, sem mocks. Imprime ANTES/DEPOIS para auditoria.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "low",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app/backend")

from database import db
from services.isabella_relationship import (
    register_isabella_outcome,
    relationship_memory_block,
    universo_ligo_contextual_pitch,
    humanized_closing_block,
    log_closing,
    _detect_outcomes,
)
from services.isabella_followup import (
    schedule_followup,
    detect_and_reopen_case,
    run_due_followups,
)


CID = "co-demo"
TEST_PHONE = f"55119999{uuid.uuid4().hex[:7]}"
TEST_SUB = f"sub-r360-{uuid.uuid4().hex[:8]}"


def hr(t: str) -> None:
    print("\n" + "=" * 64)
    print(" " + t)
    print("=" * 64)


async def setup_subscriber_with_history() -> None:
    """Cria histórico realista de um subscriber pra testar os novos services."""
    now = datetime.now(timezone.utc)
    # Subscriber existente
    await db.subscribers.insert_one({
        "company_id": CID, "id": TEST_SUB,
        "name": "João da Silva", "plan": "Fibra 1 Giga",
        "status": "ATIVO", "city": "São Paulo",
        "created_at": (now - timedelta(days=90)).isoformat(),
    })
    # Ticket closed há 10 dias (lentidão)
    await db.tickets.insert_one({
        "id": f"tk-old-{uuid.uuid4().hex[:8]}",
        "company_id": CID, "subscriber_id": TEST_SUB,
        "phone": TEST_PHONE, "type": "lentidão",
        "status": "closed",
        "created_at": (now - timedelta(days=10)).isoformat(),
    })
    # 1 evaluation passada
    await db.ai_evaluations.insert_one({
        "id": f"eval-{uuid.uuid4().hex[:10]}",
        "company_id": CID, "phone": TEST_PHONE,
        "subscriber_id": TEST_SUB,
        "kind": "ISABELLA_TURN", "outcome": "resolveu",
        "outcomes": {"resolveu": True},
        "nps_inferido": 8, "ai_attributed": "Isabella",
        "user_text": "Minha internet tá lenta", "tags": ["resolveu"],
        "isabella_reply": "Ajustei sua ONU, deve melhorar agora.",
        "created_at": (now - timedelta(days=10)).isoformat(),
    })
    # Ledger preservado R$ 800
    await db.executive_ledger.insert_one({
        "id": f"led-{uuid.uuid4().hex[:10]}",
        "action_id": f"tr-{uuid.uuid4().hex[:12]}",
        "company_id": CID, "subscriber_id": TEST_SUB,
        "kind": "TRUCK_ROLL_AVOIDED", "actual_BRL": 800,
        "created_at": (now - timedelta(days=10)).isoformat(),
    })


async def cleanup() -> None:
    await db.subscribers.delete_many({"id": TEST_SUB})
    await db.tickets.delete_many({"subscriber_id": TEST_SUB})
    await db.ai_evaluations.delete_many({"phone": TEST_PHONE})
    await db.executive_ledger.delete_many({"subscriber_id": TEST_SUB})
    await db.isabella_followups.delete_many({"phone": TEST_PHONE})
    await db.aihub_wa_messages.delete_many({"phone": TEST_PHONE})
    await db.isabella_queue.delete_many({"phone": TEST_PHONE})


async def main() -> None:
    await cleanup()
    await setup_subscriber_with_history()

    # ============== F5. RELATIONSHIP MEMORY ==============
    hr("F5 — RELATIONSHIP MEMORY BLOCK (system prompt enriquecido)")
    block = await relationship_memory_block(
        company_id=CID, phone=TEST_PHONE, subscriber_id=TEST_SUB)
    print(block or "(vazio)")
    assert "Última conversa" in block, "memory_block não citou última conversa"
    assert "VIP" in block, "memory_block não citou VIP (R$ 800)"
    print("\n✅ relationship_memory_block injeta histórico real")

    # ============== F8. CASE REOPENER ==============
    hr("F8 — DETECT & REOPEN CASE (cliente diz 'voltou a cair')")
    new_tid = await detect_and_reopen_case(
        company_id=CID, phone=TEST_PHONE, subscriber_id=TEST_SUB,
        user_text="minha internet voltou a cair de novo")
    print(f"reopened ticket: {new_tid}")
    assert new_tid, "reopener não criou ticket"
    reopened = await db.tickets.find_one({"id": new_tid})
    assert reopened.get("status") == "reopened"
    assert reopened.get("parent_ticket_id"), "sem parent_ticket_id"
    led = await db.executive_ledger.find_one(
        {"kind": "ISABELLA_CASE_REOPENED", "new_ticket_id": new_tid})
    assert led, "ledger CASE_REOPENED não foi gravado"
    print("✅ ticket reaberto com parent + ledger gravado")

    # ============== F3. REGISTER OUTCOME ==============
    hr("F3 — REGISTER ISABELLA OUTCOME (após resposta resolutiva)")
    reply = "Pronto, ajustei a sinal da sua ONU. Já liberei e deve voltar agora."
    user_text = "minha internet voltou a cair de novo"
    eid = await register_isabella_outcome(
        company_id=CID, phone=TEST_PHONE,
        subscriber_id=TEST_SUB,
        user_text=user_text, reply=reply)
    print(f"eval gravado: {eid}")
    assert eid, "outcome não foi gravado"
    ev = await db.ai_evaluations.find_one({"id": eid})
    print(f"  outcomes detectados: {ev.get('outcomes')}")
    print(f"  NPS: {ev.get('nps_inferido')} ({ev.get('nps_motivo')})")
    assert ev.get("outcomes", {}).get("resolveu"), "resolveu não detectado"
    assert ev.get("nps_inferido") >= 7
    print("✅ outcome real gravado em ai_evaluations")

    # ============== F4. SCHEDULE FOLLOW-UP ==============
    hr("F4 — SCHEDULE FOLLOWUP (4h pós resolução técnica)")
    outcomes = _detect_outcomes(reply)
    n = await schedule_followup(
        company_id=CID, phone=TEST_PHONE,
        subscriber_id=TEST_SUB, outcomes=outcomes)
    print(f"follow-ups agendados: {n}")
    assert n >= 1
    pending = await db.isabella_followups.find({
        "phone": TEST_PHONE, "status": "scheduled"
    }).to_list(10)
    for f in pending:
        print(f"  trigger={f['trigger']:18s} due_at={f['due_at']}")
        f["due_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        await db.isabella_followups.update_one({"id": f["id"]},
                                                  {"$set": {"due_at": f["due_at"]}})
    print("✅ follow-ups agendados")

    # ============== F4b. RUN DUE FOLLOWUPS ==============
    hr("F4b — RUN DUE FOLLOWUPS (despacha pra fila)")
    stats = await run_due_followups(limit=50)
    print(f"due={stats['due']} sent={stats['sent']} cancelled={stats['cancelled']} err={stats['errors']}")
    assert stats["sent"] >= 1
    # Mensagem outbound criada?
    out = await db.aihub_wa_messages.find_one({
        "phone": TEST_PHONE, "direction": "outbound",
        "source": "followup_scheduler"
    })
    assert out, "mensagem outbound de followup não foi criada"
    print(f"  ✓ outbound automático criado: {out.get('text')[:60]!r}")
    print("✅ followup foi executado e a Isabella enviou mensagem proativa")

    # ============== F6. UNIVERSO LIGO PITCH ==============
    hr("F6 — UNIVERSO LIGO CONTEXTUAL PITCH (após resolução)")
    pitch = await universo_ligo_contextual_pitch(
        company_id=CID, phone=TEST_PHONE,
        subscriber_id=TEST_SUB, reply=reply)
    print(f"pitch: {pitch[:120] if pitch else '(vazio)'!r}")
    assert pitch, "pitch não foi gerado após resolução"
    # ledger UNIVERSO_LIGO_PITCH gravado?
    led_pitch = await db.executive_ledger.find_one(
        {"phone": TEST_PHONE, "kind": "UNIVERSO_LIGO_PITCH"})
    assert led_pitch, "ledger UNIVERSO_LIGO_PITCH não gravado"
    print(f"  ✓ produto: {led_pitch.get('produto')}, status: {led_pitch.get('status')}")
    # Segunda chamada NÃO deve gerar pitch (já foi nos últimos 30d)
    pitch2 = await universo_ligo_contextual_pitch(
        company_id=CID, phone=TEST_PHONE,
        subscriber_id=TEST_SUB, reply=reply)
    assert not pitch2, "pitch duplicado não deveria ser gerado"
    print("✅ pitch contextual gerado 1x — não repete em <30d")

    # ============== F7. CLOSING HUMANIZADO ==============
    hr("F7 — HUMANIZED CLOSING (cliente disse 'valeu, obrigado')")
    block = await humanized_closing_block(
        company_id=CID, phone=TEST_PHONE,
        subscriber_id=TEST_SUB, user_text="valeu, obrigado!")
    print(block[:200] if block else "(vazio)")
    assert block, "closing block não foi gerado"
    assert "0 a 10" in block, "closing sem sondagem NPS"
    await log_closing(company_id=CID, phone=TEST_PHONE,
                          subscriber_id=TEST_SUB)
    closing_log = await db.ai_evaluations.find_one(
        {"phone": TEST_PHONE, "kind": "ISABELLA_CLOSING"})
    assert closing_log
    print("✅ encerramento humanizado com NPS conversacional")

    # ============== CLEANUP ==============
    hr("CLEANUP")
    await cleanup()
    print("✅ ambiente limpo")
    print("\n" + "🟢" * 32)
    print("  TODOS OS 6 FIXES VALIDADOS COM DB REAL")
    print("🟢" * 32)


if __name__ == "__main__":
    asyncio.run(main())
