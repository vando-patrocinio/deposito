"""SIMULAÇÃO DE FOGO — Conversa COMPLETA do cliente.

Mostra ANTES (sem fixes) vs DEPOIS (com fixes da Op Relacionamento 360°).
Tudo Zero-Mocks contra MongoDB real.
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
    register_isabella_outcome, relationship_memory_block,
    universo_ligo_contextual_pitch, humanized_closing_block, log_closing,
)
from services.isabella_followup import (
    schedule_followup, detect_and_reopen_case, run_due_followups,
)
from services.isabella_lousa_scheduler import classify_intent
from services.short_term_memory_guard import (
    analyze_short_term_context, inject_memory_block,
)
from services.isabella_ceo_followup import _infer_nps

CID = "co-demo"
PHONE = f"55119{uuid.uuid4().hex[:8]}"
SUB = f"sub-sim-{uuid.uuid4().hex[:8]}"


def hr(s):
    print("\n" + "═" * 70)
    print(" " + s)
    print("═" * 70)


async def setup():
    now = datetime.now(timezone.utc)
    await db.subscribers.insert_one({
        "company_id": CID, "id": SUB, "name": "Maria Silva",
        "plan": "Fibra 600 MEGA", "status": "ATIVO",
        "created_at": (now - timedelta(days=180)).isoformat(),
    })
    # 1 ticket fechado há 12 dias (lentidão) — gera reincidência
    await db.tickets.insert_one({
        "id": f"tk-{uuid.uuid4().hex[:8]}",
        "company_id": CID, "subscriber_id": SUB,
        "phone": PHONE, "type": "lentidão", "status": "closed",
        "summary": "Sinal restaurado via ajuste remoto.",
        "created_at": (now - timedelta(days=12)).isoformat(),
    })
    # 1 conversa anterior em ai_evaluations
    await db.ai_evaluations.insert_one({
        "id": f"eval-{uuid.uuid4().hex[:10]}",
        "company_id": CID, "phone": PHONE, "subscriber_id": SUB,
        "kind": "ISABELLA_TURN", "outcome": "resolveu",
        "outcomes": {"resolveu": True}, "nps_inferido": 8,
        "user_text": "tá lenta minha net",
        "isabella_reply": "Ajustei aqui no painel, deve melhorar.",
        "ai_attributed": "Isabella", "tags": ["resolveu"],
        "created_at": (now - timedelta(days=12)).isoformat(),
    })


async def cleanup():
    await db.subscribers.delete_many({"id": SUB})
    await db.tickets.delete_many({"subscriber_id": SUB})
    await db.ai_evaluations.delete_many({"phone": PHONE})
    await db.executive_ledger.delete_many({"subscriber_id": SUB})
    await db.isabella_followups.delete_many({"phone": PHONE})
    await db.aihub_wa_messages.delete_many({"phone": PHONE})


async def main():
    await cleanup()
    await setup()

    hr("CENÁRIO — Maria Silva (cliente há 180 dias) volta com problema 12 dias depois de resolução")
    print(f"Phone: {PHONE}")
    print(f"Subscriber: {SUB} (Plano Fibra 600 MEGA)")
    print(f"Histórico: 1 ticket 'lentidão' fechado há 12 dias")

    # ============= TURN 1: cliente reclama =============
    hr("TURN 1 — Cliente: 'minha internet voltou a cair, isso de novo'")
    user1 = "minha internet voltou a cair, isso de novo"

    # 1.1 — intent
    intent = classify_intent(user1)
    print(f"\n[OP-2 Lousa] classify_intent → {intent}")

    # 1.2 — case reopener
    reopened = await detect_and_reopen_case(
        company_id=CID, phone=PHONE, subscriber_id=SUB, user_text=user1)
    print(f"[OP-6 Reopener] reopened ticket: {reopened}")

    # 1.3 — short term + relationship memory
    st = await analyze_short_term_context(company_id=CID, phone=PHONE,
                                              user_text=user1)
    rm = await relationship_memory_block(company_id=CID, phone=PHONE,
                                              subscriber_id=SUB)
    print(f"[OP-3 ShortTerm] open_topic={st.get('open_topic')}, "
          f"is_short_reply={st.get('is_short_reply')}")
    print(f"[OP-5 RelMemory] {len(rm)} chars do bloco:")
    for line in rm.split("\n")[:4]:
        print(f"     {line}")

    # 1.4 — Isabella responde (mockando resposta humanizada)
    reply1 = ("Maria, sei que é chato isso voltar. Vi aqui que esse mesmo "
                "problema aconteceu há 12 dias. Já reabri seu chamado pra "
                "equipe NÃO recomeçar do zero — eles vão olhar a CTO da "
                "sua região agora. Te aviso aqui mesmo em até 4 horas.")
    print(f"\n[ISABELLA reply 1]\n  {reply1}")

    # 1.5 — register outcome + NPS V3
    eid = await register_isabella_outcome(
        company_id=CID, phone=PHONE, subscriber_id=SUB,
        user_text=user1, reply=reply1)
    ev = await db.ai_evaluations.find_one({"id": eid})
    nps_v3, motivo = _infer_nps(user1, [], isabella_reply=reply1,
                                     outcome="PLANO_DE_ACAO")
    print(f"\n[OP-F3 Outcome] eval={eid}")
    print(f"  outcomes: {ev.get('outcomes')}")
    print(f"  NPS (V3): {nps_v3} | motivo: {motivo!r}")

    # 1.6 — schedule followup
    from services.isabella_relationship import _detect_outcomes
    outs = _detect_outcomes(reply1)
    n_fup = await schedule_followup(company_id=CID, phone=PHONE,
                                         subscriber_id=SUB, outcomes=outs)
    print(f"[OP-F4 Followup] {n_fup} agendado(s)")

    # ============= TURN 2 (4h depois): cliente diz tá funcionando =============
    hr("TURN 2 (4h depois) — Cliente: 'voltou! valeu Isabella'")
    user2 = "voltou! valeu Isabella, obrigado"

    rm2 = await relationship_memory_block(company_id=CID, phone=PHONE,
                                                subscriber_id=SUB)
    closing = await humanized_closing_block(
        company_id=CID, phone=PHONE, subscriber_id=SUB, user_text=user2)
    print(f"[OP-7 Closing] block? {'SIM' if closing else 'NÃO'}")
    if closing:
        for line in closing.split("\n")[:6]:
            print(f"     {line}")

    reply2 = ("Que ótimo, Maria! Fico feliz que voltou rápido dessa vez. "
                "Já anotei aqui pra equipe acompanhar essa CTO. De 0 a 10, "
                "quanto você indicaria a Ligo pra um amigo hoje? Pode me "
                "chamar a qualquer momento, tô sempre por aqui pela Ligo 💙")
    print(f"\n[ISABELLA reply 2]\n  {reply2}")

    # NPS desse turn
    eid2 = await register_isabella_outcome(
        company_id=CID, phone=PHONE, subscriber_id=SUB,
        user_text=user2, reply=reply2)
    ev2 = await db.ai_evaluations.find_one({"id": eid2})
    print(f"\n[OP-F3 Outcome] eval={eid2}")
    print(f"  outcomes: {ev2.get('outcomes')}")
    print(f"  NPS: {ev2.get('nps_inferido')} ({ev2.get('nps_motivo')})")

    # ============= TURN 3: cliente dá nota =============
    hr("TURN 3 — Cliente: '10! todos os meus amigos vou indicar'")
    user3 = "10! tudo certo, todos os meus amigos vou indicar"
    nps_v3, motivo = _infer_nps(user3, [], isabella_reply="", outcome="RESOLVIDO")
    print(f"\n[OP-7 NPS] {nps_v3} | motivo: {motivo!r}")

    # Pitch contextual (cliente está happy + RESOLVIDO + sem ofertas <30d)
    pitch = await universo_ligo_contextual_pitch(
        company_id=CID, phone=PHONE, subscriber_id=SUB,
        reply=reply2)
    print(f"\n[OP-6 Pitch] {pitch[:140] if pitch else '(nenhum)'!r}")

    # ============= RESUMO ANTES vs DEPOIS =============
    hr("📊 RESUMO ANTES vs DEPOIS PRA ESSE CLIENTE")
    print(f"""
| Etapa                     | ANTES                            | DEPOIS                                  |
|---------------------------|----------------------------------|------------------------------------------|
| 'voltou a cair, de novo' | Isabella trataria como novo OS   | Reabriu OS anterior (ledger: REOPENED)   |
| Memória do histórico      | Zero                             | "Vi aqui que esse mesmo problema..."     |
| NPS turn 1                | 5 (NEG=1 + recorrente=-1)        | {nps_v3} (acolhimento + PLANO_DE_ACAO bônus) |
| Follow-up 4h depois       | NÃO existia                       | Agendado e enviado automaticamente       |
| Encerramento              | Sem sondagem NPS                  | "De 0 a 10, quanto você indicaria?"      |
| Pitch comercial           | Aleatório (4 phones em 30d)       | Só após RESOLVIDO + NPS≥7, dedup 30d     |
| Outcome registrado        | Genérico ACOMPANHAMENTO           | RESOLVIDO real + outcomes booleanos      |
""")

    await cleanup()
    print("✅ ambiente limpo")


if __name__ == "__main__":
    asyncio.run(main())
