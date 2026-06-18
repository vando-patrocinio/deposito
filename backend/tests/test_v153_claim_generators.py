"""Testes V15.3 — Isabella Claim Generators + Trust Formula reformulada.

Cobertura:
  • cadastro_claim — passa quando subscriber tem nome+plano; falha sem nome
  • smartolt_status_claim — passa com ONU online+freshness; falha sem ONU
  • ticket_status_claim — passa com status+updated_at; falha sem ticket
  • financial_extended_claim — falha com sync_stale; passa com sync ok
  • log_fallback_used + fallback_stats — registra e agrega
  • trust_score (V15.3) — nova fórmula audit+delivery
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, "/app/backend")
for ln in open("/app/backend/.env"):
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.strip().split("=", 1)
        os.environ.setdefault(k, v.strip('"'))

pytestmark = pytest.mark.asyncio(loop_scope="session")
CID = "TEST-V153-CLAIMS"


async def _cleanup():
    from database import db
    await db.isabella_factual_claims.delete_many({"company_id": CID})
    await db.isabella_fallback_events.delete_many({"company_id": CID})
    await db.aihub_wa_messages.delete_many({"company_id": CID})
    await db.ai_evaluations.delete_many({"company_id": CID})


async def test_cadastro_claim_full():
    await _cleanup()
    from services.isabella_claim_generators import cadastro_claim
    sub = {"id": "sub-1", "name": "João Silva",
            "plan_name": "100MB", "plan_speed": "100/50",
            "plan_price": 99.90, "branch": "Centro"}
    r = await cadastro_claim(
        company_id=CID, phone="5511A", subscriber=sub,
    )
    assert r["audit_passed"] is True
    assert r["claim_type"] == "subscriber_status"
    assert r["source"] == "db.subscribers"
    assert r["evidence_id"] is not None
    assert r["evidence"]["name"] == "João Silva"
    assert r["fallback_required"] is False
    await _cleanup()
    print("  ✓ cadastro_claim: full → passed + evidence_id presente")


async def test_cadastro_claim_no_subscriber():
    await _cleanup()
    from services.isabella_claim_generators import cadastro_claim
    r = await cadastro_claim(
        company_id=CID, phone="5511X", subscriber=None,
    )
    assert r["audit_passed"] is False
    assert r["fallback_required"] is True
    assert "subscriber_not_found" in r["warnings"]
    assert r["evidence"] == {}  # nada afirmável
    await _cleanup()
    print("  ✓ cadastro_claim: not_found → fallback_required=True · evidence={}")


async def test_smartolt_claim_online():
    await _cleanup()
    from services.isabella_claim_generators import smartolt_status_claim
    onu = {"id": "onu-1", "sn": "SN001", "status": "online",
            "signal_text": "Very good", "signal_1310": -18.5,
            "last_status_change": datetime.now(timezone.utc).isoformat(),
            "minutes_since_change": 5}
    r = await smartolt_status_claim(
        company_id=CID, subscriber_id="sub-1", onu=onu,
    )
    assert r["audit_passed"] is True
    assert r["claim_type"] == "smartolt_status"
    assert r["source"] == "smartolt.api"
    assert r["evidence"]["status"] == "online"
    await _cleanup()
    print("  ✓ smartolt_claim: online + fresh → passed")


async def test_smartolt_claim_stale_freshness():
    await _cleanup()
    from services.isabella_claim_generators import smartolt_status_claim
    onu = {"id": "onu-1", "sn": "SN001", "status": "online",
            "last_status_change": None, "minutes_since_change": 999}
    r = await smartolt_status_claim(
        company_id=CID, subscriber_id="sub-1", onu=onu,
        max_stale_minutes=60,
    )
    assert r["audit_passed"] is False
    assert r["fallback_required"] is True
    await _cleanup()
    print("  ✓ smartolt_claim: stale freshness → fallback_required")


async def test_ticket_claim_full():
    await _cleanup()
    from services.isabella_claim_generators import ticket_status_claim
    tk = {"_id": "tkt-1", "code": "TKT-001", "status": "em_atendimento",
           "title": "Sem internet",
           "updated_at": datetime.now(timezone.utc).isoformat()}
    r = await ticket_status_claim(
        company_id=CID, subscriber_id="sub-1", ticket=tk,
    )
    assert r["audit_passed"] is True
    assert r["claim_type"] == "ticket_status"
    assert r["evidence"]["ticket_code"] == "TKT-001"
    await _cleanup()
    print("  ✓ ticket_claim: full → passed")


async def test_ticket_claim_missing_status():
    await _cleanup()
    from services.isabella_claim_generators import ticket_status_claim
    tk = {"_id": "tkt-2", "code": "TKT-002", "status": "",
           "updated_at": None}
    r = await ticket_status_claim(
        company_id=CID, subscriber_id="sub-1", ticket=tk,
    )
    assert r["audit_passed"] is False
    assert r["fallback_required"] is True
    assert "ticket_without_status" in r["warnings"]
    assert "ticket_without_updated_at" in r["warnings"]
    await _cleanup()
    print("  ✓ ticket_claim: incomplete → fallback")


async def test_financial_claim_sync_stale():
    await _cleanup()
    from services.isabella_claim_generators import financial_extended_claim
    r = await financial_extended_claim(
        company_id=CID, subscriber_id="sub-1",
        open_invoices=[{"amount": 99.9,
                           "due_date": "2026-07-01",
                           "status": "pending"}],
        next_due_date="2026-07-01",
        sync_freshness_hours=48.0,  # > 24h default
        max_stale_hours=24.0,
    )
    assert r["audit_passed"] is False
    assert "financial_sync_stale" in r["warnings"]
    await _cleanup()
    print("  ✓ financial_claim: sync stale → fallback")


async def test_financial_claim_full():
    await _cleanup()
    from services.isabella_claim_generators import financial_extended_claim
    r = await financial_extended_claim(
        company_id=CID, subscriber_id="sub-1",
        open_invoices=[{"amount": 99.9,
                           "due_date": "2026-07-01",
                           "status": "pending"}],
        next_due_date="2026-07-01",
        sync_freshness_hours=2.0,
    )
    assert r["audit_passed"] is True
    assert r["evidence"]["open_count"] == 1
    assert r["evidence"]["open_total"] == 99.9
    await _cleanup()
    print("  ✓ financial_claim: sync fresh → passed")


async def test_fallback_log_and_stats():
    await _cleanup()
    from services.isabella_claim_generators import (
        log_fallback_used, fallback_stats,
    )
    for ct in ("smartolt_status", "smartolt_status", "ticket_status"):
        await log_fallback_used(
            company_id=CID, phone="5511A",
            claim_type=ct, evidence_id="claim-x",
            reason="audit failed → IA usou fallback",
        )
    stats = await fallback_stats(company_id=CID, hours=24)
    assert stats["total"] == 3
    assert stats["by_type"]["smartolt_status"] == 2
    assert stats["by_type"]["ticket_status"] == 1
    assert len(stats["samples"]) == 3
    await _cleanup()
    print(f"  ✓ fallback_stats: {stats['by_type']}")


async def test_trust_score_v153_formula():
    """V15.3: formula nova baseada em audit_pass + delivery rates."""
    await _cleanup()
    from database import db
    from services.isabella_confidence import trust_score
    now = datetime.now(timezone.utc)
    # 5 claims passados, 4 consumidos
    docs = []
    for i in range(5):
        docs.append({
            "id": f"claim-test-{i}",
            "company_id": CID,
            "domain": "cadastro",
            "audited_at": now.isoformat(),
            "audit_passed": True,
            "consumed_by": f"wam-{i}" if i < 4 else None,
        })
    # 2 claims falhos (não passaram audit)
    for i in range(2):
        docs.append({
            "id": f"claim-fail-{i}",
            "company_id": CID,
            "domain": "technical",
            "audited_at": now.isoformat(),
            "audit_passed": False,
            "consumed_by": None,
        })
    await db.isabella_factual_claims.insert_many(docs)

    r = await trust_score(company_id=CID, hours=24)
    # audit_pass_rate = 5/7 = 71.4%
    # delivery_rate = 4/5 = 80.0%
    # base = (71.4 + 80.0) / 2 = 75.7
    assert r["claims_total"] == 7
    assert r["claims_passed"] == 5
    assert r["claims_consumed"] == 4
    assert r["audit_pass_rate"] == pytest.approx(71.4, abs=0.2)
    assert r["delivery_rate"] == pytest.approx(80.0, abs=0.2)
    assert r["score"] == pytest.approx(75.7, abs=0.5)
    await _cleanup()
    print(f"  ✓ Trust V15.3: audit={r['audit_pass_rate']}% "
          f"+ delivery={r['delivery_rate']}% → score={r['score']}")


async def test_trust_score_no_claims_defaults_100():
    """Sem claims (zero atividade factual) → trust = 100 (não há
    fabricação possível)."""
    await _cleanup()
    from services.isabella_confidence import trust_score
    r = await trust_score(company_id=CID, hours=24)
    assert r["claims_total"] == 0
    assert r["score"] == 100.0
    print("  ✓ Trust sem claims → default 100.0")
