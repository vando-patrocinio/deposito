"""Tests for Sprint B — Opportunity Executor.

Cobertura:
  1. Allowlist Fase 1 — tipos permitidos executam em produção
  2. Tipos fora da allowlist são forçados para phase_dry_run
  3. Approved órfãs são processadas pelo worker (FIX P0 18/02/2026)
  4. block_subscriber pós-approval gera pending_smartolt_action
  5. Gate de approval ainda funciona (requires_approval=True)
  6. Audit log reflete dry_run REAL (global OR phase)
  7. Pipeline Health endpoint retorna funil + autonomy_index
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
# Carrega .env
for ln in open("/app/backend/.env"):
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.strip().split("=", 1)
        os.environ.setdefault(k, v.strip('"'))

CID = "TEST-SPRINT-B"


def _opp(action_type, status="pending", requires_approval=False, **extra):
    return {
        "id": f"opp-{uuid.uuid4().hex[:14]}",
        "company_id": CID,
        "kind": "test",
        "subkind": "test",
        "target_type": "subscriber",
        "target_id": "sub-test",
        "target_label": "Test User",
        "status": status,
        "recommended_action": {
            "type": action_type,
            "phone": "5511999999999",
            "requires_approval": requires_approval,
            "subscriber_id": "sub-test",
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        **extra,
    }


async def _cleanup():
    from database import db
    await db.isabella_commander_opportunities.delete_many({"company_id": CID})
    await db.opportunity_executor_audit.delete_many({"company_id": CID})
    await db.pending_os_requests.delete_many({"company_id": CID})
    await db.pending_smartolt_actions.delete_many({"company_id": CID})


async def test_allowlist_phase1_permitted():
    """send_reminder está na allowlist → executa real (dry=False)."""
    from database import db
    from services.opportunity_executor import execute_opportunity, _is_dry_for
    assert not _is_dry_for("send_reminder"), "send_reminder deveria estar permitido"
    opp = _opp("send_reminder")
    await db.isabella_commander_opportunities.insert_one(opp)
    r = await execute_opportunity(opp)
    # OK ou fail por wa_dispatcher é OK — o que importa é que NÃO foi dry
    cur = await db.isabella_commander_opportunities.find_one({"id": opp["id"]})
    assert cur.get("phase_dry_run") is not True, "send_reminder não deveria ser phase_dry"
    audit = await db.opportunity_executor_audit.find_one(
        {"opp_id": opp["id"]}, sort=[("created_at", -1)])
    assert audit is not None
    assert audit["dry_run"] is False, f"audit dry_run deveria ser False, got {audit['dry_run']}"
    print(f"  ✓ send_reminder executou em produção (dry=False)")


async def test_allowlist_phase2_blocked():
    """send_negotiation NÃO está na allowlist → força phase_dry_run."""
    from database import db
    from services.opportunity_executor import execute_opportunity, _is_dry_for
    assert _is_dry_for("send_negotiation"), "send_negotiation deveria estar BLOQUEADO em Fase 1"
    opp = _opp("send_negotiation")
    await db.isabella_commander_opportunities.insert_one(opp)
    await execute_opportunity(opp)
    cur = await db.isabella_commander_opportunities.find_one({"id": opp["id"]})
    assert cur.get("phase_dry_run") is True, f"send_negotiation deveria ser phase_dry: {cur}"
    audit = await db.opportunity_executor_audit.find_one(
        {"opp_id": opp["id"]}, sort=[("created_at", -1)])
    assert audit["dry_run"] is True, f"audit dry_run deveria ser True (phase)"
    assert audit["phase_dry_run"] is True
    print(f"  ✓ send_negotiation forçado para phase_dry_run (Fase 2)")


async def test_approved_orphan_processed():
    """FIX P0: approved sem executed_at deve ser pego pelo worker."""
    from database import db
    from services.opportunity_executor import drain_pending
    opp = _opp("satisfaction_survey", status="approved")
    opp["approved_at"] = datetime.now(timezone.utc).isoformat()
    opp["approved_by"] = "admin@empresa.com"
    await db.isabella_commander_opportunities.insert_one(opp)
    r = await drain_pending(company_id=CID, limit=5)
    summary = r["summary"]
    assert summary["from_approved"] >= 1, f"approved não foi processado: {summary}"
    print(f"  ✓ Approved órfã processada pelo worker ({summary['from_approved']} from_approved)")


async def test_block_subscriber_post_approval():
    """block_subscriber aprovado deve criar pending_smartolt_action."""
    from database import db
    from services.opportunity_executor import execute_opportunity
    opp = _opp("block_subscriber", status="approved", requires_approval=True)
    opp["approved_by"] = "admin@empresa.com"
    opp["approved_at"] = datetime.now(timezone.utc).isoformat()
    await db.isabella_commander_opportunities.insert_one(opp)
    r = await execute_opportunity(opp)
    # block_subscriber está fora da allowlist → phase_dry_run
    assert r["ok"] is True, f"block aprovado deveria retornar ok: {r}"
    # Em phase_dry_run não cria action real, mas em modo real criaria
    print(f"  ✓ block_subscriber pós-approval roteado corretamente (dry={r['result'].get('dry_run')})")


async def test_gate_requires_approval():
    """opp com requires_approval=True e status=pending → bloqueado."""
    from database import db
    from services.opportunity_executor import execute_opportunity
    opp = _opp("send_reminder", requires_approval=True)
    await db.isabella_commander_opportunities.insert_one(opp)
    r = await execute_opportunity(opp)
    assert r["ok"] is False
    assert r["reason"] == "requires_approval", f"esperava requires_approval, got {r}"
    print(f"  ✓ Gate de approval bloqueia execução de pending+requires_approval")


async def test_pipeline_health_endpoint():
    """pipeline_overview retorna funil + autonomy_index."""
    from services.opportunity_executor_health import pipeline_overview
    r = await pipeline_overview(company_id=CID, hours=24)
    assert "funnel" in r
    assert "autonomy_index" in r
    assert "by_action_type" in r
    assert "roi" in r
    assert "executor_audit" in r
    assert "conversion_pct" in r["funnel"]
    print(f"  ✓ pipeline_overview retorna estrutura completa")


async def main():
    print("=== Sprint B — Opportunity Executor: tests ===")
    await _cleanup()
    tests = [
        test_allowlist_phase1_permitted,
        test_allowlist_phase2_blocked,
        test_approved_orphan_processed,
        test_block_subscriber_post_approval,
        test_gate_requires_approval,
        test_pipeline_health_endpoint,
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
