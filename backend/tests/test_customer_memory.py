"""Tests for Isabella V14 — Customer Memory Oracle.

Run: python3 -m tests.test_customer_memory (or via pytest single loop)
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, "/app/backend")
os.environ.setdefault(
    "MONGO_URL",
    open("/app/backend/.env").read().split("MONGO_URL=")[1].split("\n")[0].strip().strip('"'),
)

CID = "TEST-COMPANY-V14"


async def _cleanup():
    from database import db
    await db.customer_memory.delete_many({"company_id": CID})
    await db.customer_promises.delete_many({"company_id": CID})
    await db.customer_timeline.delete_many({"company_id": CID})


async def test_l1_captures_pessoal_filha_prova():
    from services.customer_memory import capture_from_inbound
    from database import db
    phone = f"55119{uuid.uuid4().hex[:9]}"
    mid = await capture_from_inbound(
        company_id=CID, phone=phone, subscriber_id=None,
        user_text="Oi, minha filha vai fazer prova amanhã, então não posso atender.",
        source_msg_id="m1",
    )
    assert mid, "L1 deve capturar memória pessoal"
    doc = await db.customer_memory.find_one({"_id": mid})
    assert doc["memory_type"] == "PESSOAL", f"esperado PESSOAL, got {doc['memory_type']}"
    assert doc["confidence"] >= 0.80
    print(f"  ✓ L1 PESSOAL filha+prova capturado (conf={doc['confidence']})")


async def test_l1_ignores_operational():
    from services.customer_memory import capture_from_inbound
    phone = f"55119{uuid.uuid4().hex[:9]}"
    mid = await capture_from_inbound(
        company_id=CID, phone=phone, subscriber_id=None,
        user_text="Nossa internet caiu agora.",
        source_msg_id="m2",
    )
    assert mid is None, "msg operacional NÃO deve virar memória"
    print(f"  ✓ Operacional ignorado (sem memória)")


async def test_promise_detection_and_block():
    from services.customer_memory import (
        detect_promise, register_promise, build_memory_oracle_block,
    )
    phone = f"55119{uuid.uuid4().hex[:9]}"
    pt = detect_promise("Vou verificar isso para você e te retorno em breve.")
    assert pt is not None, "promessa deve ser detectada"
    await register_promise(
        company_id=CID, phone=phone, subscriber_id=None,
        promise_text=pt, context_user_text="cliente perguntou sobre cobrança",
    )
    block = await build_memory_oracle_block(
        company_id=CID, phone=phone, subscriber_id=None,
    )
    assert "PROMESSA EM ABERTO" in block, f"bloco sem promessa: {block!r}"
    assert "verificar" in block.lower()
    print(f"  ✓ Promessa detectada + bloco inclui PROMESSA EM ABERTO")


async def test_memory_block_pessoal():
    from services.customer_memory import (
        capture_from_inbound, build_memory_oracle_block,
    )
    phone = f"55119{uuid.uuid4().hex[:9]}"
    await capture_from_inbound(
        company_id=CID, phone=phone, subscriber_id=None,
        user_text="Vou viajar pra Bahia semana que vem, fica difícil falar.",
    )
    block = await build_memory_oracle_block(
        company_id=CID, phone=phone, subscriber_id=None,
    )
    assert "MEMÓRIA RELACIONAL" in block, f"bloco sem memória: {block!r}"
    assert "viajar" in block.lower() or "viagem" in block.lower(), (
        f"bloco não contém referência: {block!r}"
    )
    print(f"  ✓ Memória pessoal viajar injetada no bloco")


async def test_dedup_within_24h():
    from services.customer_memory import capture_from_inbound
    from database import db
    phone = f"55119{uuid.uuid4().hex[:9]}"
    text = "Minha filha vai fazer vestibular semana que vem."
    m1 = await capture_from_inbound(
        company_id=CID, phone=phone, subscriber_id=None, user_text=text,
    )
    m2 = await capture_from_inbound(
        company_id=CID, phone=phone, subscriber_id=None, user_text=text,
    )
    assert m1 == m2, f"dedup falhou: {m1} != {m2}"
    count = await db.customer_memory.count_documents(
        {"company_id": CID, "phone": phone},
    )
    assert count == 1, f"esperava 1 doc, encontrou {count}"
    print(f"  ✓ Dedup em 24h funciona (1 doc, 2 capturas)")


async def test_empty_block_for_new_client():
    from services.customer_memory import build_memory_oracle_block
    phone = f"55119{uuid.uuid4().hex[:9]}"
    block = await build_memory_oracle_block(
        company_id=CID, phone=phone, subscriber_id=None,
    )
    assert block == "", f"cliente novo: esperava vazio, got {block!r}"
    print(f"  ✓ Cliente novo: bloco vazio (não polui prompt)")


async def main():
    print("=== Isabella V14 — Customer Memory Oracle: tests ===")
    await _cleanup()
    tests = [
        test_l1_captures_pessoal_filha_prova,
        test_l1_ignores_operational,
        test_promise_detection_and_block,
        test_memory_block_pessoal,
        test_dedup_within_24h,
        test_empty_block_for_new_client,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            print(f"\n-- {t.__name__}")
            await t()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"  ✗ FAILED: {e}")
        except Exception as e:
            failed += 1
            print(f"  ✗ ERROR: {type(e).__name__}: {e}")
    await _cleanup()
    print(f"\n=== {passed} passed · {failed} failed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
