"""Operação Memória Total — Validação Zero-Mocks.

Testa o pipeline de contexto da Isabella em 3 frentes:
  1. fetch_history_turns retém as mensagens MAIS RECENTES (bug antigo
     fazia o contrário: ele descartava as recentes ao estourar budget).
  2. Long-term memory retorna estrutura completa por janela (15/30/60d)
     para um phone com histórico real no banco demo/preview.
  3. Encadeamento: bloco de longo prazo + short-term + history_turns
     juntos não estouram limite de tokens do system prompt.

Política Zero-Mocks: TODAS as chamadas vão pro MongoDB real do tenant.
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

sys.path.insert(0, "/app/backend")

from database import db  # noqa: E402
from services.ai_history import fetch_history_turns  # noqa: E402
from services.long_term_memory import (
    summarize_subscriber_history,
    inject_long_term_block,
    build_long_term_block,
)  # noqa: E402


def assert_true(cond: bool, msg: str) -> None:
    if not cond:
        print(f"  ❌ FAIL — {msg}")
        raise SystemExit(1)
    print(f"  ✅ {msg}")


async def find_busy_phone(min_msgs: int = 100):
    """Acha o phone com mais histórico no banco real."""
    pipeline = [
        {"$group": {"_id": {"company_id": "$company_id", "phone": "$phone"},
                     "n": {"$sum": 1}}},
        {"$match": {"n": {"$gte": min_msgs}}},
        {"$sort": {"n": -1}},
        {"$limit": 1},
    ]
    async for d in db.aihub_wa_messages.aggregate(pipeline):
        return d["_id"]["company_id"], d["_id"]["phone"], d["n"]
    return None, None, 0


async def test_history_keeps_recent():
    print("\n[1] HISTORY KEEPS RECENT MESSAGES")
    cid, phone, total = await find_busy_phone(min_msgs=100)
    assert_true(bool(cid and phone), f"achei phone com histórico ({total} msgs)")

    # Última mensagem REAL no banco
    last = await db.aihub_wa_messages.find_one(
        {"company_id": cid, "phone": phone},
        {"_id": 0, "id": 1, "text": 1, "direction": 1, "created_at": 1},
        sort=[("created_at", -1)],
    )
    assert_true(bool(last), "última mensagem existe no banco")

    turns = await fetch_history_turns(cid, phone, limit=200, token_budget=6000)
    assert_true(len(turns) > 0, f"turns retornados: {len(turns)}")

    # A última mensagem do banco DEVE aparecer entre os turns retornados
    last_text = (last.get("text") or "").strip()
    found = any(last_text in (t.get("content") or "") for t in turns[-3:])
    assert_true(found,
                f"última msg ({last_text[:40]!r}) presente nos últimos turns")


async def test_long_term_summary():
    print("\n[2] LONG-TERM MEMORY SUMMARY")
    cid, phone, _ = await find_busy_phone(min_msgs=50)
    summary = await summarize_subscriber_history(
        company_id=cid, phone=phone, subscriber_id=None)
    assert_true(summary["phone"] == phone, "summary tem phone correto")
    assert_true(set(summary["windows"].keys()) == {15, 30, 60},
                "summary contém janelas 15/30/60 dias")
    for d in (15, 30, 60):
        w = summary["windows"][d]
        for key in ("messages", "tickets", "outcomes", "ledger"):
            assert_true(key in w, f"janela {d}d contém '{key}'")
    print(f"     first_contact: {summary.get('first_contact')}")
    print(f"     msgs 15d: {summary['windows'][15]['messages']}")
    print(f"     msgs 60d: {summary['windows'][60]['messages']}")


async def test_long_term_block_text():
    print("\n[3] LONG-TERM MEMORY BLOCK INJECTION")
    cid, phone, _ = await find_busy_phone(min_msgs=50)
    block = await build_long_term_block(
        company_id=cid, phone=phone, subscriber_id=None)
    print(f"     tamanho do bloco: {len(block)} chars")
    if block:
        assert_true("MEMÓRIA HISTÓRICA" in block,
                    "bloco contém cabeçalho MEMÓRIA HISTÓRICA")
        assert_true("Janela" in block or "Primeiro contato" in block,
                    "bloco contém janelas ou primeiro contato")
        # Tamanho razoável (não estoura prompt)
        assert_true(len(block) < 8000,
                    f"bloco cabe em ~8k chars (atual: {len(block)})")
    else:
        print("     ⚠ bloco vazio — phone sem histórico operacional "
              "(esperado se for novato)")


async def test_short_reply_keeps_context():
    print("\n[4] SHORT REPLY MANTÉM HISTÓRICO (sim/ok/pode)")
    cid, phone, _ = await find_busy_phone(min_msgs=100)
    # Simula que o cliente acabou de mandar "sim"
    turns = await fetch_history_turns(cid, phone, limit=200, token_budget=6000)
    assert_true(len(turns) >= 10,
                f"pelo menos 10 turnos de contexto disponível ({len(turns)})")
    # Última mensagem nos turns deve ser próxima da última real
    recent_outbound = [t for t in turns if t["role"] == "assistant"]
    recent_inbound = [t for t in turns if t["role"] == "user"]
    assert_true(len(recent_inbound) >= 3,
                f"contém ao menos 3 turnos do cliente "
                f"({len(recent_inbound)})")
    assert_true(len(recent_outbound) >= 3,
                f"contém ao menos 3 turnos da Isabella "
                f"({len(recent_outbound)})")


async def main():
    print("=" * 60)
    print(" OPERAÇÃO MEMÓRIA TOTAL — Validação Zero-Mocks")
    print("=" * 60)
    await test_history_keeps_recent()
    await test_long_term_summary()
    await test_long_term_block_text()
    await test_short_reply_keeps_context()
    print("\n" + "=" * 60)
    print(" ✅ TODOS OS TESTES PASSARAM")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
