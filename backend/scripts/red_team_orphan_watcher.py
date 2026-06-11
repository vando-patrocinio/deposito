"""RED TEAM ORPHAN WATCHER — 10 testes do CTO. Zero mocks."""
import asyncio, sys, uuid
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import db
from services import orphan_event_watcher as ow

async def main():
    # 0) Setup: garante indexes + limpa state anterior do source de teste
    await ow.ensure_indexes()
    test_src = f"redteam_orphan_{uuid.uuid4().hex[:8]}"
    await db[ow.QUAR_COLL].delete_many({"source": test_src})
    await db.motor_ia_events.delete_many({"source": test_src})

    # 1) Inserir evento fake sem company_id
    ev_id = f"ev-{uuid.uuid4().hex[:8]}"
    await db.motor_ia_events.insert_one({
        "id": ev_id, "event_type": "FAKE_ORPHAN_TEST",
        "source": test_src, "company_id": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    print("  ✅ 1. evento órfão fake inserido")

    # 2) Watcher detecta
    res = await ow.scan_orphans(window_minutes=10)
    assert res["detected"] >= 1
    assert test_src in res["sources"]
    print(f"  ✅ 2. watcher detectou {res['detected']} órfão(s)")

    # 3) Audit chain registra
    audit_recs = await db.audit_chain.find(
        {"chain_key": f"shield-orphan-{test_src}"}).to_list(10)
    assert len(audit_recs) >= 2, f"esperava ≥2 audit, got {len(audit_recs)}"
    actions = [r.get("action") for r in audit_recs]
    assert "ORPHAN_EVENT_DETECTED" in actions
    assert "SOURCE_QUARANTINED" in actions
    print(f"  ✅ 3. audit_chain: {actions}")

    # 4) Source entra em quarentena
    quar = await db[ow.QUAR_COLL].find_one({"source": test_src})
    assert quar and quar["status"] == "ACTIVE"
    print(f"  ✅ 4. quarentena ACTIVE: {test_src}")

    # 5) Conselho recebe opp critical
    opp = await db.isabella_commander_opportunities.find_one(
        {"kind": "multi_tenant_violation", "evidence.source": test_src})
    assert opp and opp["score"] == 100
    print(f"  ✅ 5. opp critical: {opp['id']}")

    # 6) Health status RED
    status = await ow.orphan_status_24h()
    assert status["status"] in ("RED", "YELLOW")
    print(f"  ✅ 6. health status: {status['status']} "
          f"(orphans 24h={status['orphans_24h']}, quarantines={status['active_quarantines']})")

    # 7) Presidente IA brief inclui quarentena
    from services.presidente_ia_nl import daily_natural
    brief = await daily_natural("co-demo")
    nf = brief.get("nervous_foundation") or {}
    assert "orphan_status" in nf
    print(f"  ✅ 7. presidente_ia brief: orphan_status={nf['orphan_status']}")

    # 8) is_quarantined retorna True
    assert await ow.is_quarantined(test_src)
    print(f"  ✅ 8. is_quarantined({test_src}) = True (bloqueio ativo)")

    # 9) Admin libera com justificativa
    rel = await ow.release_source(
        source=test_src,
        justificativa="Red Team test — bug consertado em código",
        released_by="cto@smartprov")
    assert rel["ok"]
    print(f"  ✅ 9. release: {rel}")

    # 10) Audit registra liberação
    audit_after = await db.audit_chain.find(
        {"chain_key": f"shield-orphan-{test_src}",
         "action": "SOURCE_RELEASED"}).to_list(5)
    assert len(audit_after) >= 1
    print(f"  ✅ 10. audit SOURCE_RELEASED: {len(audit_after)} record(s)")

    # cleanup
    await db.motor_ia_events.delete_many({"source": test_src})
    await db[ow.QUAR_COLL].delete_many({"source": test_src})
    await db.isabella_commander_opportunities.delete_many(
        {"evidence.source": test_src})
    await db.audit_chain.delete_many({"chain_key": f"shield-orphan-{test_src}"})
    print("\n=== 10/10 PASSED ✅ ===")

if __name__ == "__main__":
    asyncio.run(main())
