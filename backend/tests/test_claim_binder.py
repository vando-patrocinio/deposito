"""Tests for V15.2 — Factual Claim Binder.

Cobertura:
  1. list_active_claims só retorna passed + dentro do TTL + não consumidos
  2. bind_active_claims marca como consumed e impacta Trust Score
  3. Idempotência: 2ª chamada não re-vincula
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app/backend")
for ln in open("/app/backend/.env"):
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.strip().split("=", 1)
        os.environ.setdefault(k, v.strip('"'))

CID = "TEST-BINDER-V15-2"
SUB_ID = f"sub-{uuid.uuid4().hex[:10]}"


async def _cleanup():
    from database import db
    await db.isabella_factual_claims.delete_many({"company_id": CID})
    await db.aihub_wa_messages.delete_many({"company_id": CID})


async def test_list_active_filters():
    """Só retorna claims passed + TTL válido + consumed_by=null."""
    from database import db
    from services.factual_claim_binder import list_active_claims_for_subscriber
    now_iso = datetime.now(timezone.utc).isoformat()
    old_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    docs = [
        {"id": "c-ok-1", "company_id": CID, "entity_id": SUB_ID,
         "domain": "financial", "audited_at": now_iso,
         "audit_passed": True, "consumed_by": None, "ttl_minutes": 30,
         "evidence": {"x": 1}},
        # Expirado (TTL excedido)
        {"id": "c-expired", "company_id": CID, "entity_id": SUB_ID,
         "domain": "technical", "audited_at": old_iso,
         "audit_passed": True, "consumed_by": None, "ttl_minutes": 30},
        # Já consumido
        {"id": "c-consumed", "company_id": CID, "entity_id": SUB_ID,
         "domain": "cadastro", "audited_at": now_iso,
         "audit_passed": True, "consumed_by": "wam-x", "ttl_minutes": 30},
        # Failed audit
        {"id": "c-failed", "company_id": CID, "entity_id": SUB_ID,
         "domain": "estoque", "audited_at": now_iso,
         "audit_passed": False, "consumed_by": None, "ttl_minutes": 30},
    ]
    await db.isabella_factual_claims.insert_many(docs)
    rows = await list_active_claims_for_subscriber(
        company_id=CID, subscriber_id=SUB_ID,
    )
    ids = [r["id"] for r in rows]
    assert ids == ["c-ok-1"], f"esperava só c-ok-1, got {ids}"
    print(f"  ✓ Filtros corretos: expired/consumed/failed ignorados")


async def test_bind_marks_consumed():
    """bind_active_claims marca consumed_by + consumed_at."""
    from database import db
    from services.factual_claim_binder import bind_active_claims_to_outbound
    msg_id = f"wam-{uuid.uuid4().hex[:10]}"
    r = await bind_active_claims_to_outbound(
        company_id=CID, subscriber_id=SUB_ID, outbound_msg_id=msg_id,
    )
    assert r["bound_count"] == 1, f"esperava 1 bound, got {r}"
    doc = await db.isabella_factual_claims.find_one({"id": "c-ok-1"})
    assert doc["consumed_by"] == msg_id
    assert doc.get("consumed_at") is not None
    print(f"  ✓ Claim marcado consumed_by={msg_id[:15]}")


async def test_bind_idempotent():
    """2ª chamada não re-vincula claims já consumed."""
    from services.factual_claim_binder import bind_active_claims_to_outbound
    r = await bind_active_claims_to_outbound(
        company_id=CID, subscriber_id=SUB_ID,
        outbound_msg_id="wam-different",
    )
    assert r["bound_count"] == 0, f"deveria ser 0 (idempotente), got {r}"
    print(f"  ✓ Idempotência: 0 binds na 2ª chamada")


async def test_no_subscriber_no_bind():
    """Sem subscriber_id, retorna 0 sem erro."""
    from services.factual_claim_binder import bind_active_claims_to_outbound
    r = await bind_active_claims_to_outbound(
        company_id=CID, subscriber_id=None, outbound_msg_id="wam-x",
    )
    assert r["bound_count"] == 0
    print(f"  ✓ Sem subscriber: 0 binds (sem erro)")


async def test_trust_score_uses_consumed():
    """Após bind, Trust Score deve refletir claim consumido."""
    from database import db
    from services.isabella_confidence import trust_score
    now_iso = datetime.now(timezone.utc).isoformat()
    # Cria 2 outbounds
    for i in range(2):
        await db.aihub_wa_messages.insert_one({
            "id": f"wam-trust-{i}", "company_id": CID,
            "direction": "outbound", "auto_reply": True,
            "phone": "5511", "created_at": now_iso,
        })
    t = await trust_score(company_id=CID, hours=24)
    # 2 claims consumed (c-ok-1 que bindamos + c-consumed pré-existente)
    # 2 outbounds = 100%
    assert t["outbounds"] == 2
    assert t["claims_consumed"] == 2, f"esperava 2 consumed, got {t}"
    assert t["score"] == 100.0, f"Trust 100% esperado, got {t['score']}"
    print(f"  ✓ Trust Score reflete bind: {t['score']}% "
          f"({t['claims_consumed']}/{t['outbounds']} outbounds)")


async def main():
    print("=== V15.2 — Factual Claim Binder: tests ===")
    await _cleanup()
    tests = [
        test_list_active_filters,
        test_bind_marks_consumed,
        test_bind_idempotent,
        test_no_subscriber_no_bind,
        test_trust_score_uses_consumed,
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
