"""TEST ISABELLA LISTENING — valida end-to-end (Zero Mocks):
  1. Aggregator: 3 bolhas "Oi" em rajada → 1 só job processa todas
  2. Bubble splitter: respostas longas viram bolhas ≤180 chars
  3. Listening guard: cliente "so quero instalar" → Isabella não pergunta qualificação
  4. Name suppression: "Pamela" só 1x por turn
"""

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
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import db
from services import (bubble_splitter, listening_guard,
                       message_aggregator)


async def test_aggregator():
    print("\n[1] AGGREGATOR — debounce")
    phone = f"5511{uuid.uuid4().hex[:8]}"
    cid = "co-demo"
    # 3 bolhas em rajada (dentro da janela)
    for i, txt in enumerate(["Oi", "Bom dia", "Tudo bem?"], 1):
        await message_aggregator.push(
            company_id=cid, phone=phone,
            message_sid=f"sid-{i}", text=txt)
    # pop_ready ainda não retorna (silêncio < 6s)
    immediate = await message_aggregator.pop_ready(
        company_id=cid, phone=phone)
    assert immediate is None, "pop_ready deveria esperar janela"
    print("  ✅ pop_ready bloqueado dentro da janela (silêncio<6s)")
    # peek mostra 3 msgs
    peek = await message_aggregator.peek(company_id=cid, phone=phone)
    assert peek and len(peek["messages"]) == 3
    print(f"  ✅ peek: {len(peek['messages'])} msgs no buffer")
    # wait_for_quiet_window deve esperar e devolver join
    t0 = time.time()
    ready = await message_aggregator.wait_for_quiet_window(
        company_id=cid, phone=phone, max_wait_s=10.0)
    elapsed = time.time() - t0
    assert ready, "wait_for_quiet_window deveria devolver"
    assert ready["count"] == 3
    assert ready["joined_text"] == "Oi | Bom dia | Tudo bem?", \
        f"joined unexpected: {ready['joined_text']!r}"
    print(f"  ✅ join 3→1: {ready['joined_text']!r} (após {elapsed:.1f}s)")
    # Buffer foi limpo
    remaining = await message_aggregator.peek(company_id=cid, phone=phone)
    assert remaining is None
    print("  ✅ buffer limpo após pop")


async def test_dedup_consecutive():
    print("\n[1.b] AGGREGATOR — dedup 'Oi' consecutivo")
    phone = f"5511{uuid.uuid4().hex[:8]}"
    cid = "co-demo"
    for i in range(3):
        await message_aggregator.push(
            company_id=cid, phone=phone,
            message_sid=f"sid-{i}", text="Oi")
    ready = await message_aggregator.wait_for_quiet_window(
        company_id=cid, phone=phone, max_wait_s=10.0)
    assert ready and ready["joined_text"].lower() == "oi", \
        f"deveria deduplicar 'Oi' consecutivo, got: {ready['joined_text']!r}"
    print(f"  ✅ dedup: 3x 'Oi' → {ready['joined_text']!r}")


def test_bubble_splitter():
    print("\n[2] BUBBLE SPLITTER")
    cases = [
        ("Oi Pamela! 😊 Vi que você quer instalação. É pra um novo endereço ou é upgrade do plano atual?",
         {"min_bubbles": 2, "name_count_max": 1}),
        ("Perfeito, Pamela! 🚀 Vou verificar as opções de upgrade pra você. Pamela, quantas pessoas usam a internet aí na sua casa?",
         {"min_bubbles": 2, "name_count_max": 1}),
        ("Beleza, te confirmo já.",
         {"min_bubbles": 1, "max_bubbles": 1}),
    ]
    for txt, exp in cases:
        bubbles = bubble_splitter.split_into_bubbles(txt)
        # Each bubble ≤180 chars
        assert all(len(b) <= 180 for b in bubbles), \
            f"bolha excedeu 180c: {[len(b) for b in bubbles]}"
        if "min_bubbles" in exp:
            assert len(bubbles) >= exp["min_bubbles"], \
                f"esperava ≥{exp['min_bubbles']} bolhas, got {len(bubbles)}"
        if "max_bubbles" in exp:
            assert len(bubbles) <= exp["max_bubbles"]
        if "name_count_max" in exp:
            name_count = sum(b.lower().count("pamela") for b in bubbles)
            assert name_count <= exp["name_count_max"], \
                f"nome aparece {name_count}x: {bubbles}"
        print(f"  ✅ {len(txt)}c → {len(bubbles)} bolhas, max={max(len(b) for b in bubbles)}c")


async def test_listening_guard():
    print("\n[3] LISTENING GUARD")
    cid = "co-demo"
    phone = f"5511{uuid.uuid4().hex[:8]}"
    # Cliente diz "só quero instalar"
    a = await listening_guard.analyze_listening(
        company_id=cid, phone=phone,
        user_text="So quero instalar vc tem?")
    assert "intent_direct" in a["intents"], \
        f"deveria detectar intent_direct: {a}"
    assert "asks_availability" in a["intents"]
    assert a["is_listening_violation_risk"]
    print(f"  ✅ intents: {a['intents']}")
    # Bloco no prompt
    block = listening_guard.inject_listening_block(a)
    assert "MODO ESCUTA OBRIGATÓRIO" in block
    assert "Confirme a ação que ele pediu" in block
    print("  ✅ inject_listening_block gera diretiva clara")
    # Rewrite remove pergunta qualificatória que cliente recusou
    bad_reply = "Beleza! Mas pra te indicar o ideal — quantas pessoas usam a internet aí?"
    cleaned = listening_guard.rewrite_if_violates(bad_reply, a)
    assert "quantas pessoas" not in cleaned.lower(), \
        f"deveria remover, got: {cleaned!r}"
    print(f"  ✅ rewrite removeu pergunta: {cleaned!r}")


async def test_pergunta_da_pergunta():
    print("\n[4] LISTENING — cliente diz 'mas pra que essa pergunta'")
    cid = "co-demo"
    phone = f"5511{uuid.uuid4().hex[:8]}"
    a = await listening_guard.analyze_listening(
        company_id=cid, phone=phone,
        user_text="Mas pra que essa pergunta")
    assert "questions_question" in a["intents"]
    assert a["is_listening_violation_risk"]
    block = listening_guard.inject_listening_block(a)
    assert "EXPLICAR o motivo em 1 frase curta" in block
    print(f"  ✅ detecta + injeta: {a['intents']}")


async def main():
    await test_aggregator()
    await test_dedup_consecutive()
    test_bubble_splitter()
    await test_listening_guard()
    await test_pergunta_da_pergunta()
    print("\n=== 5/5 SUITES PASSED ✅ ===")


if __name__ == "__main__":
    asyncio.run(main())
