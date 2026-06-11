"""TEST HUMANIZER — valida o serviço central usado por TODOS os canais.

Zero mocks. MongoDB real.

Valida:
  - humanize_system_prompt anexa anti-CPF + listening + short-term +
    conversa contínua
  - humanize_reply aplica listening rewrite + anti-CPF rewrite
  - bubbles_for_send quebra em ≤180c + remove saudação se contínua
  - Funciona para qualquer canal (interface canal-agnóstica)
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
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import db
from services import humanizer


async def _seed_outbound(cid: str, phone: str):
    """Cria 1 outbound recente para simular conversa contínua."""
    await db.aihub_wa_messages.insert_one({
        "id": f"wam-{uuid.uuid4().hex[:10]}",
        "company_id": cid, "phone": phone,
        "direction": "outbound", "channel": "test",
        "text": "Oi! Como posso ajudar?",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


async def test_humanize_system_prompt():
    print("\n[1] humanize_system_prompt")
    cid = "co-demo"
    phone = f"55119000{uuid.uuid4().hex[:6]}"
    base = "Você é a Isabella."
    sp, ctx = await humanizer.humanize_system_prompt(
        sys_prompt=base, company_id=cid,
        phone=phone, user_text="So quero instalar vc tem?")
    assert "MODO ESCUTA OBRIGATÓRIO" in sp, "listening block ausente"
    assert "intent_direct" in (ctx.get("listening_analysis") or {}).get("intents", [])
    assert ctx.get("is_continuous_conversation") is False, "primeira interação"
    print(f"  ✅ listening + ctx ok; prompt cresceu {len(sp)-len(base)}c")


async def test_continuous_conversation():
    print("\n[2] conversa contínua → bloco anti-saudação injetado")
    cid = "co-demo"
    phone = f"55119001{uuid.uuid4().hex[:6]}"
    await _seed_outbound(cid, phone)
    sp, ctx = await humanizer.humanize_system_prompt(
        sys_prompt="base", company_id=cid,
        phone=phone, user_text="Oi")
    assert ctx["is_continuous_conversation"] is True
    assert "CONVERSA CONTÍNUA" in sp
    print(f"  ✅ continuous detectado, bloco anti-greet injetado")
    # Cleanup
    await db.aihub_wa_messages.delete_many({"company_id": cid, "phone": phone})


async def test_humanize_reply():
    print("\n[3] humanize_reply — listening + anti-CPF rewrite")
    cid = "co-demo"
    phone = f"55119002{uuid.uuid4().hex[:6]}"
    # Mock ctx com listening_analysis dizendo intent_direct
    ctx = {
        "link_for_guard": {"subscriber_id": "sub-x",
                             "subscriber_name": "Cliente Teste"},
        "listening_analysis": {
            "intents": ["intent_direct"],
            "direct_intent_text": "So quero instalar",
            "rejected_topics": ["qualifying_questions"],
            "is_listening_violation_risk": True,
            "isabella_questions_repeated": [],
        },
    }
    bad = ("Oi! Quantas pessoas usam a internet aí? "
           "Pode me passar o CPF do titular?")
    out = await humanizer.humanize_reply(
        reply_text=bad, ctx=ctx, company_id=cid, phone=phone)
    assert "quantas pessoas" not in out.lower(), \
        f"listening rewrite falhou: {out}"
    assert "cpf" not in out.lower(), f"anti-cpf rewrite falhou: {out}"
    print(f"  ✅ rewrite removeu listening + CPF: {out!r}")


def test_bubbles_for_send():
    print("\n[4] bubbles_for_send — split + anti-greet contextual")
    text = ("Oi Pamela! 😊 Vi que você quer instalação. "
            "É pra novo endereço ou upgrade?")
    # Sem ctx contínuo: mantém greeting
    bs = humanizer.bubbles_for_send(reply_text=text, ctx=None)
    assert any("Oi Pamela" in b for b in bs), "deveria manter saudação"
    assert all(len(b) <= 180 for b in bs)
    print(f"  ✅ sem contínuo: {len(bs)} bolhas, mantém saudação")
    # Com ctx contínuo: remove
    bs2 = humanizer.bubbles_for_send(
        reply_text=text, ctx={"is_continuous_conversation": True})
    assert not any("Oi Pamela" in b for b in bs2), \
        f"deveria remover saudação, got: {bs2}"
    print(f"  ✅ contínuo: saudação removida, {len(bs2)} bolhas")


def test_strip_greetings_variations():
    print("\n[5] _strip_repeated_greetings — variantes")
    variants = [
        ("Oi Pamela! 😊 Pra instalação...", "Pra instalação..."),
        ("Olá João! Quanto custa?", "Quanto custa?"),
        ("Bom dia Maria, tudo bem?", "tudo bem?"),
        ("Hey Carlos! Verifiquei aqui.", "Verifiquei aqui."),
        ("Boa noite Ana, segue o link", "segue o link"),
    ]
    for inp, expected in variants:
        out = humanizer._strip_repeated_greetings([inp])
        assert out and expected.split()[0] in out[0], \
            f"falhou em {inp!r} → {out}"
        print(f"  ✅ {inp!r} → {out[0]!r}")


async def main():
    await test_humanize_system_prompt()
    await test_continuous_conversation()
    await test_humanize_reply()
    test_bubbles_for_send()
    test_strip_greetings_variations()
    print("\n=== 5/5 PASSED ✅ ===")


if __name__ == "__main__":
    asyncio.run(main())
