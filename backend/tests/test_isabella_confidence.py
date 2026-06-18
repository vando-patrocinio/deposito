"""Tests for V15.2 — Isabella Confidence Score + Autonomy Alarms.

Cobertura:
  1. Trust Score com evidências consumidas
  2. Relationship Score com memórias usadas
  3. Promise Score com promises resolved
  4. Resolution Score com outcomes positivos
  5. ISABELLA INDEX composite + cor
  6. Autonomy snapshot + alarme quando cai >5pp
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

CID = "TEST-CONFIDENCE-V15-2"


async def _cleanup():
    from database import db
    await db.isabella_factual_claims.delete_many({"company_id": CID})
    await db.aihub_wa_messages.delete_many({"company_id": CID})
    await db.customer_memory.delete_many({"company_id": CID})
    await db.customer_promises.delete_many({"company_id": CID})
    await db.customer_timeline.delete_many({"company_id": CID})
    await db.ai_evaluations.delete_many({"company_id": CID})
    await db.isabella_index_snapshots.delete_many({"company_id": CID})
    await db.isabella_autonomy_snapshots.delete_many({"company_id": CID})
    await db.isabella_autonomy_alarms.delete_many({"company_id": CID})
    await db.isabella_commander_opportunities.delete_many({"company_id": CID})


async def test_trust_score():
    from database import db
    from services.isabella_confidence import trust_score
    now = datetime.now(timezone.utc).isoformat()
    # 4 outbounds da Isabella
    for i in range(4):
        await db.aihub_wa_messages.insert_one({
            "id": f"wam-{uuid.uuid4().hex[:10]}",
            "company_id": CID, "direction": "outbound",
            "auto_reply": True, "phone": "5511999",
            "created_at": now,
        })
    # 3 claims consumidos
    for i in range(3):
        await db.isabella_factual_claims.insert_one({
            "id": f"claim-fin-{i}", "company_id": CID,
            "domain": "financial", "audited_at": now,
            "audit_passed": True, "consumed_by": f"wam-x{i}",
        })
    t = await trust_score(company_id=CID, hours=24)
    assert t["outbounds"] == 4
    assert t["claims_consumed"] == 3
    assert t["score"] >= 70.0, f"score baixo: {t}"
    print(f"  ✓ Trust score: {t['score']} (3/4 outbounds com evidência)")


async def test_relationship_score():
    from database import db
    from services.isabella_confidence import relationship_score
    now = datetime.now(timezone.utc)
    # 5 memórias, 3 usadas
    for i in range(5):
        await db.customer_memory.insert_one({
            "_id": f"mem-{i}", "company_id": CID, "phone": f"55{i}",
            "memory_type": "PESSOAL", "title": "x", "description": "y",
            "confidence": 0.85, "source": "regex_l1",
            "created_at": now, "expires_at": now + timedelta(days=180),
            "hit_count": 1 if i < 3 else 0,
        })
    r = await relationship_score(company_id=CID, hours=24)
    assert r["memories_used"] == 3, f"esperava 3 used, got {r}"
    assert r["score"] >= 50.0, f"score baixo: {r}"
    print(f"  ✓ Relationship score: {r['score']} (3/5 memórias usadas)")


async def test_promise_score():
    from database import db
    from services.isabella_confidence import promise_score
    now = datetime.now(timezone.utc)
    # 4 promises criadas, 3 resolved
    for i in range(4):
        await db.customer_promises.insert_one({
            "_id": f"prom-{i}", "company_id": CID, "phone": f"55{i}",
            "promise_text": f"prom {i}",
            "status": "resolved" if i < 3 else "pending",
            "created_at": now,
            "due_at": now + timedelta(hours=24),
        })
    p = await promise_score(company_id=CID, hours=24)
    assert p["created_window"] == 4
    assert p["resolved_window"] == 3
    assert p["score"] == 75.0, f"esperava 75%, got {p}"
    print(f"  ✓ Promise score: {p['score']} (3/4 resolved)")


async def test_resolution_score():
    from database import db
    from services.isabella_confidence import resolution_score
    now = datetime.now(timezone.utc).isoformat()
    for i, outcome in enumerate(["resolveu", "resolveu", "vendeu",
                                    "interacao", "interacao"]):
        await db.ai_evaluations.insert_one({
            "id": f"eval-{i}", "company_id": CID, "phone": f"55{i}",
            "kind": "ISABELLA_TURN", "outcome": outcome,
            "created_at": now,
        })
    r = await resolution_score(company_id=CID, hours=24)
    assert r["turns_total"] == 5
    assert r["resolved"] == 3
    assert r["score"] == 60.0, f"esperava 60%, got {r}"
    print(f"  ✓ Resolution score: {r['score']} (3/5 resolveu/vendeu)")


async def test_isabella_index():
    from database import db
    from services.isabella_confidence import isabella_index
    # Aproveita dados dos testes anteriores
    r = await isabella_index(company_id=CID, hours=24)
    assert "isabella_index" in r
    assert "color" in r
    assert r["color"] in ("green", "amber", "red")
    assert all(k in r["scores"]
                 for k in ("trust", "relationship", "resolution", "promise"))
    # Pesos devem somar 1
    assert sum(r["weights"].values()) == 1.0
    print(f"  ✓ ISABELLA INDEX: {r['isabella_index']}% ({r['color']}) "
          f"trust={r['scores']['trust']['score']} "
          f"rel={r['scores']['relationship']['score']} "
          f"res={r['scores']['resolution']['score']} "
          f"prom={r['scores']['promise']['score']}")


async def test_autonomy_alarm():
    from database import db
    from services.isabella_confidence import (
        snapshot_autonomy, autonomy_alarms,
    )
    # Snapshot ANTIGO: alta autonomia
    await db.isabella_autonomy_snapshots.insert_one({
        "company_id": CID,
        "ts": datetime.now(timezone.utc) - timedelta(hours=25),
        "autonomy_index_pct": 80.0,
        "elegiveis": 100, "executadas": 80,
    })
    # Snapshot atual: vai medir o que tiver (zero opps neste cid)
    # Então autonomy=0, queda de 80pp → alarme deve disparar
    r = await snapshot_autonomy(company_id=CID)
    assert r.get("alarm_triggered") is True, f"alarme não disparou: {r}"
    assert r["delta_pp"] <= -5.0
    alarms = await autonomy_alarms(company_id=CID, hours=24)
    assert alarms["n"] >= 1, "alarme não foi persistido"
    print(f"  ✓ Autonomy alarm disparou: delta={r['delta_pp']}pp, "
          f"severity={alarms['items'][0]['severity']}")


async def main():
    print("=== V15.2 — Isabella Confidence Score: tests ===")
    await _cleanup()
    tests = [
        test_trust_score,
        test_relationship_score,
        test_promise_score,
        test_resolution_score,
        test_isabella_index,
        test_autonomy_alarm,
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
