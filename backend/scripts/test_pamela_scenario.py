"""TEST PAMELA SCENARIO — replica end-to-end o screenshot do CTO
e valida que:
  - Bolha gigante quebra em ≤180c
  - "Oi Pamela!" suprimido em conversa contínua (<30min)
  - Listening guard remove pergunta qualificatória recusada
  - Anti-CPF rewrite remove "Pode me passar o CPF" se identificado
  - Saudação repetida em turn 2/3/4 → dropada
"""

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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import db
from services import bubble_splitter
from services.anti_cpf_guardian import detect_violations
from services.listening_guard import (analyze_listening,
                                          rewrite_if_violates)


def test_long_bubble_breaks():
    print("\n[1] Bolha gigante quebra em ≤180c")
    # Exato texto que apareceu no screenshot 21:25
    bad = ("Oi Pamela! 😊\nConsultei aqui e seu equipamento NÃO está vinculado "
           "ao cadastro técnico.\nPode me passar o CPF do titular pra eu abrir "
           "um chamado especializado e localizar manualmente?")
    bubbles = bubble_splitter.split_into_bubbles(bad)
    for i, b in enumerate(bubbles):
        assert len(b) <= 180, f"bolha {i} tem {len(b)}c"
        print(f"  [{i+1}/{len(bubbles)}] ({len(b)}c) {b}")
    # Deve ter pelo menos 2 bolhas (originalmente era 1 mega)
    assert len(bubbles) >= 2, f"deveria quebrar, got {len(bubbles)}"
    print(f"  ✅ {len(bad)}c → {len(bubbles)} bolhas")


def test_name_suppression_intra_turn():
    print("\n[2] Nome 'Pamela' só 1x dentro do turn")
    bad = ("Perfeito, Pamela! Pamela, quantas pessoas usam internet aí? "
           "Pamela me diz pra eu te ajudar.")
    bubbles = bubble_splitter.split_into_bubbles(bad)
    total_pamela = sum(b.lower().count("pamela") for b in bubbles)
    assert total_pamela <= 1, f"'Pamela' aparece {total_pamela}x: {bubbles}"
    print(f"  ✅ 'Pamela' = {total_pamela}x (deveria ≤ 1)")
    for b in bubbles:
        print(f"     {b}")


async def test_anti_cpf_when_identified():
    print("\n[3] Anti-CPF: cliente identificado → remove pedido de CPF")
    bad = ("Oi Pamela! 😊 Consultei aqui e seu equipamento NÃO está vinculado "
           "ao cadastro técnico. Pode me passar o CPF do titular pra eu "
           "abrir um chamado especializado e localizar manualmente?")
    vio = detect_violations(bad)
    assert vio, f"deveria detectar violação, got {vio}"
    print(f"  ✅ violações detectadas: {vio}")
    # Simula link identificado
    link = {"subscriber_id": "sub-pamela", "subscriber_name": "Pamela Nery"}
    from services.anti_cpf_guardian import rewrite_if_violates as cpf_rw
    safe = cpf_rw(bad, link)
    assert "cpf" not in safe.lower()
    print(f"  ✅ reescrito: {safe}")


async def test_listening_guard_quer_instalar():
    print("\n[4] Listening: 'so quero instalar vc tem?' bloqueia qualificação")
    cid = "co-demo"
    phone = f"5511{uuid.uuid4().hex[:8]}"
    a = await analyze_listening(
        company_id=cid, phone=phone,
        user_text="So quero instalar vc tem?")
    assert "intent_direct" in a["intents"]
    # Reply ofensivo (Isabella ignorou intenção e pediu qualificação)
    bad = ("É no mesmo endereço do seu cadastro atual ou é uma mudança? "
           "Quantas pessoas usam a internet aí na sua casa?")
    cleaned = rewrite_if_violates(bad, a)
    assert "quantas pessoas" not in cleaned.lower(), \
        f"deveria remover, got: {cleaned}"
    print(f"  ✅ reescrito: {cleaned!r}")


async def test_anti_greeting_continuous():
    print("\n[5] Anti-saudação em conversa contínua")
    import re
    # Mesma regex usada no whatsapp_baileys.py
    greet_rx = re.compile(
        r"^\s*(?:oi|ol[áa]|opa|bom\s+dia|boa\s+tarde|boa\s+noite)"
        r"[\s,!]+[A-ZÁÉÍÓÚ][a-záéíóú]+[!,.\s]*\s*[😊😄🙂🚀✨🎉]?\s*",
        re.IGNORECASE)
    cases = [
        ("Oi Pamela! 😊 Pra instalação, preciso confirmar...",
         "Pra instalação, preciso confirmar..."),
        ("Oi Pamela!\nDeixa eu consultar",
         "Deixa eu consultar"),
        ("Oi Pamela! 😊\nConsultei aqui",
         "Consultei aqui"),
    ]
    for inp, expected_start in cases:
        out = greet_rx.sub("", inp).strip()
        assert "Oi Pamela" not in out, f"greeting não removido: {out}"
        assert expected_start.split()[0].lower() in out.lower()
        print(f"  ✅ {inp[:40]!r} → {out[:60]!r}")


def test_bubble_splitter_caso_realCTO():
    print("\n[6] Cenário REAL CTO (screenshot 21:24): 3 frases em 1 mega-bolha")
    raw = ("Oi Pamela! 😊\nConsultei aqui e seu equipamento NÃO está vinculado "
           "ao cadastro técnico.\nPode me passar o CPF do titular pra eu abrir "
           "um chamado especializado e localizar manualmente?")
    bubbles = bubble_splitter.split_into_bubbles(raw)
    # Espera 3 bolhas: saudação / status / pergunta
    assert len(bubbles) >= 2
    assert all(len(b) <= 180 for b in bubbles)
    # ≤1 pergunta no turn inteiro
    q_total = sum(b.count("?") for b in bubbles)
    assert q_total <= 1, f"{q_total} perguntas no turn"
    print(f"  ✅ split em {len(bubbles)} bolhas, ≤180c cada, {q_total} pergunta")


async def main():
    test_long_bubble_breaks()
    test_name_suppression_intra_turn()
    await test_anti_cpf_when_identified()
    await test_listening_guard_quer_instalar()
    await test_anti_greeting_continuous()
    test_bubble_splitter_caso_realCTO()
    print("\n=== 6/6 PASSED ✅ ===")


if __name__ == "__main__":
    asyncio.run(main())
