"""Tests for Isabella V15 — Oráculo Relacional Absoluto.

Cobertura (6 cenários CTO 18/02/2026):
  1. Promessa aberta
  2. Memória pessoal
  3. Reparo recente
  4. Cliente VIP
  5. Conflito / sem evidência
  6. Limite de 2 referências
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app/backend")
os.environ.setdefault(
    "MONGO_URL",
    open("/app/backend/.env").read().split("MONGO_URL=")[1].split("\n")[0].strip().strip('"'),
)

CID = "TEST-COMPANY-V15"


async def _cleanup():
    from database import db
    await db.customer_memory.delete_many({"company_id": CID})
    await db.customer_promises.delete_many({"company_id": CID})
    await db.customer_timeline.delete_many({"company_id": CID})
    await db.subscribers.delete_many({"company_id": CID})
    await db.tickets.delete_many({"company_id": CID})
    await db.isabella_factual_claims.delete_many({"company_id": CID})


async def test_promise_open():
    from services.customer_memory import register_promise, build_v15_oracle_block
    phone = f"5511{uuid.uuid4().hex[:9]}"
    await register_promise(
        company_id=CID, phone=phone, subscriber_id=None,
        promise_text="vou verificar sua fatura e te retorno",
        context_user_text="cliente perguntou sobre cobrança",
    )
    block = await build_v15_oracle_block(
        company_id=CID, phone=phone, subscriber_id=None,
    )
    assert "PROMESSA EM ABERTO (P1)" in block, f"sem promessa: {block!r}"
    assert "sobre o que eu havia ficado" in block.lower()
    print("  ✓ Promessa aberta injetada como P1")


async def test_personal_memory():
    from services.customer_memory import (
        capture_from_inbound, build_v15_oracle_block,
    )
    phone = f"5511{uuid.uuid4().hex[:9]}"
    await capture_from_inbound(
        company_id=CID, phone=phone, subscriber_id=None,
        user_text="Minha filha vai fazer prova amanhã, então não posso falar agora.",
    )
    block = await build_v15_oracle_block(
        company_id=CID, phone=phone, subscriber_id=None,
    )
    assert "MEMÓRIA RELACIONAL (pessoal" in block, f"sem memória pessoal: {block!r}"
    assert "vi aqui" in block.lower()
    print("  ✓ Memória pessoal injetada com naturalidade")


async def test_recent_repair():
    from services.customer_memory import build_v15_oracle_block
    from database import db
    phone = f"5511{uuid.uuid4().hex[:9]}"
    sub_id = f"sub-{uuid.uuid4().hex[:10]}"
    # Insere subscriber + ticket aberto
    await db.subscribers.insert_one({
        "id": sub_id, "company_id": CID, "name": "João Recente",
        "plan_name": "300 Mega", "plan_price": 99.90,
        "activation_date": (datetime.now(timezone.utc) - timedelta(days=120)).isoformat(),
    })
    await db.tickets.insert_one({
        "id": f"tk-{uuid.uuid4().hex[:10]}", "company_id": CID,
        "client_id": sub_id, "type": "reparo", "status": "open",
        "atlaz_assunto": "sem sinal",
        "created_at": (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat(),
        "scheduled_time": (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat(),
    })
    block = await build_v15_oracle_block(
        company_id=CID, phone=phone, subscriber_id=sub_id,
    )
    assert "REPARO/OS EM ABERTO" in block, f"sem reparo: {block!r}"
    assert "sem sinal" in block
    print("  ✓ Reparo recente em aberto injetado como P2")


async def test_vip_customer():
    from services.customer_memory import build_v15_oracle_block
    from database import db
    phone = f"5511{uuid.uuid4().hex[:9]}"
    sub_id = f"sub-{uuid.uuid4().hex[:10]}"
    # VIP: 5 anos de casa + plano premium R$ 299
    await db.subscribers.insert_one({
        "id": sub_id, "company_id": CID, "name": "Maria VIP",
        "plan_name": "1 Giga Premium", "plan_price": 299.90,
        "activation_date": (datetime.now(timezone.utc) - timedelta(days=5 * 365)).isoformat(),
        "tags": [],
    })
    block = await build_v15_oracle_block(
        company_id=CID, phone=phone, subscriber_id=sub_id,
    )
    assert "CLIENTE VIP" in block, f"sem VIP: {block!r}"
    assert "score=" in block
    print("  ✓ Cliente VIP reconhecido (5 anos + plano premium)")


async def test_no_evidence_blocks_factual_claim():
    """Sem evidência auditada, bloco NÃO deve injetar afirmação técnica."""
    from services.customer_memory import build_v15_oracle_block
    from database import db
    phone = f"5511{uuid.uuid4().hex[:9]}"
    sub_id = f"sub-{uuid.uuid4().hex[:10]}"
    await db.subscribers.insert_one({
        "id": sub_id, "company_id": CID, "name": "Ze Sem Evidencia",
        "plan_name": "200 Mega", "plan_price": 79.90,
        "activation_date": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
    })
    block = await build_v15_oracle_block(
        company_id=CID, phone=phone, subscriber_id=sub_id,
    )
    # Cliente novo, sem nada → bloco vazio
    assert block == "" or "EVIDÊNCIAS AUDITADAS" not in block, (
        f"sem evidência mas bloco contém: {block!r}"
    )
    # Agora COM evidência válida
    await db.isabella_factual_claims.insert_one({
        "id": f"claim-financial-{uuid.uuid4().hex[:10]}",
        "domain": "financial", "entity_type": "subscriber",
        "entity_id": sub_id, "company_id": CID,
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "checks": [{"name": "identification", "ok": True}],
        "warnings": [], "audit_passed": True,
        "evidence": {"ultima_fatura_paga": "11/06/2026",
                       "proxima_vencimento": "10/07/2026",
                       "valor": "R$ 99,90"},
        "ttl_minutes": 30, "consumed_by": None,
    })
    block2 = await build_v15_oracle_block(
        company_id=CID, phone=phone, subscriber_id=sub_id,
    )
    assert "EVIDÊNCIAS AUDITADAS" in block2, f"sem evidências válidas: {block2!r}"
    assert "11/06/2026" in block2 or "ultima_fatura_paga" in block2
    assert "deixa eu confirmar" in block2.lower()
    print("  ✓ Sem evidência: bloco não permite afirmação. Com evidência: injeta.")


async def test_max_2_references():
    """Cliente com TODAS as prioridades ativas — bloco deve ter no máximo 2 refs."""
    from services.customer_memory import (
        register_promise, capture_from_inbound, build_v15_oracle_block,
    )
    from database import db
    phone = f"5511{uuid.uuid4().hex[:9]}"
    sub_id = f"sub-{uuid.uuid4().hex[:10]}"
    # P1: promessa
    await register_promise(
        company_id=CID, phone=phone, subscriber_id=sub_id,
        promise_text="vou checar sua velocidade",
    )
    # P2: ticket aberto
    await db.tickets.insert_one({
        "id": f"tk-{uuid.uuid4().hex[:10]}", "company_id": CID,
        "client_id": sub_id, "type": "reparo", "status": "open",
        "atlaz_assunto": "lentidão",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # P3: memória pessoal
    await capture_from_inbound(
        company_id=CID, phone=phone, subscriber_id=sub_id,
        user_text="vou casar mês que vem, animado demais!",
    )
    # P4: VIP (5 anos + premium)
    await db.subscribers.insert_one({
        "id": sub_id, "company_id": CID, "name": "TudoJunto",
        "plan_name": "Gigabit", "plan_price": 350.0,
        "activation_date": (datetime.now(timezone.utc) - timedelta(days=5 * 365)).isoformat(),
    })

    block = await build_v15_oracle_block(
        company_id=CID, phone=phone, subscriber_id=sub_id,
    )
    # Conta as bullets de "• " na seção REFERÊNCIAS PRIORITÁRIAS
    refs_section = block.split("REFERÊNCIAS PRIORITÁRIAS")[-1].split("REGRAS DE OURO")[0]
    bullet_count = refs_section.count("\n• ")
    assert bullet_count == 2, (
        f"esperava exatamente 2 referências, encontrou {bullet_count}: "
        f"{refs_section!r}"
    )
    # P1 (promessa) e P2 (reparo) devem ganhar — menor número de prioridade
    assert "PROMESSA EM ABERTO" in block
    assert "REPARO/OS EM ABERTO" in block
    # P3 e P4 devem ter sido suprimidas
    assert "MEMÓRIA RELACIONAL (pessoal" not in block
    print(f"  ✓ Máximo 2 refs respeitado (P1+P2 ganharam, P3/P4 suprimidas)")


async def main():
    print("=== Isabella V15 — Oráculo Relacional Absoluto: tests ===")
    await _cleanup()
    tests = [
        test_promise_open,
        test_personal_memory,
        test_recent_repair,
        test_vip_customer,
        test_no_evidence_blocks_factual_claim,
        test_max_2_references,
    ]
    passed = failed = 0
    for t in tests:
        print(f"\n-- {t.__name__}")
        try:
            await t()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"  ✗ FAILED: {e}")
        except Exception as e:
            failed += 1
            import traceback
            print(f"  ✗ ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()
    await _cleanup()
    print(f"\n=== {passed} passed · {failed} failed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
