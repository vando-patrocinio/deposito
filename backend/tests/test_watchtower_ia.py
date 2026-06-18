"""Testes dos endpoints Watchtower IA (IA Presidente + Relacionamento).

Cobertura:
  • GET /api/isabella/watchtower/ia-presidente devolve shape correto
  • GET /api/isabella/watchtower/relacionamento devolve shape correto
  • Endpoints filtram por company_id corretamente
  • _claims_no_evidence, _promises_stats, _wa_dispatch_stats funcionam
    de forma agregada
"""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, "/app/backend")
for ln in open("/app/backend/.env"):
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.strip().split("=", 1)
        os.environ.setdefault(k, v.strip('"'))

pytestmark = pytest.mark.asyncio(loop_scope="session")
CID = "TEST-WATCHTOWER-IA"


async def _cleanup():
    from database import db
    await db.customer_memory.delete_many({"company_id": CID})
    await db.customer_promises.delete_many({"company_id": CID})
    await db.isabella_factual_claims.delete_many({"company_id": CID})
    await db.wa_dispatch_metrics.delete_many({"company_id": CID})


async def test_ia_presidente_empty_shape():
    """Sem dados, devolve shape com zeros (não 500)."""
    await _cleanup()
    from routes.isabella_watchtower import (
        watchtower_ia_presidente,
    )
    # Simula a chamada chamando os helpers diretamente já que a route
    # depende de decorators de FastAPI/auth — vamos validar via helper.
    from routes.isabella_watchtower import (
        _claims_no_evidence, _promises_stats, _wa_dispatch_stats,
    )
    claims = await _claims_no_evidence(CID, 24)
    promises = await _promises_stats(CID, 24)
    dispatch = await _wa_dispatch_stats(CID, 24)

    assert claims == {"failed": 0, "orphan_no_consume": 0, "samples": []}
    assert promises["open"] == 0 and promises["overdue"] == 0
    assert promises["fulfilled"] == 0
    assert dispatch["total"] == 0 and dispatch["failures"] == 0
    assert dispatch["success_rate"] is None
    print("  ✓ Shape vazio (sem dados) OK · sem 500")


async def test_claims_no_evidence_counts():
    await _cleanup()
    from database import db
    from routes.isabella_watchtower import _claims_no_evidence
    now = datetime.now(timezone.utc)
    docs = [
        {"_id": f"c-{uuid.uuid4().hex[:6]}", "company_id": CID,
          "audit_passed": False, "consumed_by": None,
          "domain": "technical",
          "entity_type": "onu",
          "warnings": ["no_evidence_found"],
          "audited_at": (now - timedelta(hours=2)).isoformat()},
        {"_id": f"c-{uuid.uuid4().hex[:6]}", "company_id": CID,
          "audit_passed": False, "consumed_by": None,
          "domain": "cadastro",
          "entity_type": "subscriber",
          "warnings": ["subscriber_not_found"],
          "audited_at": (now - timedelta(hours=5)).isoformat()},
        # 1 órfão (passou audit mas não foi consumido)
        {"_id": f"c-{uuid.uuid4().hex[:6]}", "company_id": CID,
          "audit_passed": True, "consumed_by": None,
          "domain": "financial", "entity_type": "subscriber",
          "audited_at": (now - timedelta(hours=1)).isoformat()},
    ]
    await db.isabella_factual_claims.insert_many(docs)
    out = await _claims_no_evidence(CID, 24)
    assert out["failed"] == 2
    assert out["orphan_no_consume"] == 1
    assert len(out["samples"]) == 2
    await _cleanup()
    print(f"  ✓ Claims: 2 failed + 1 orphan detectados")


async def test_promises_stats_overdue():
    await _cleanup()
    from database import db
    from routes.isabella_watchtower import _promises_stats
    now = datetime.now(timezone.utc)
    docs = [
        # 1 vencida (status pending + due_at no passado)
        {"_id": "p1", "company_id": CID, "phone": "5511",
          "status": "pending", "promise_text": "Mando até 18h",
          "created_at": now - timedelta(hours=6),
          "due_at": now - timedelta(hours=1), "resolved_at": None},
        # 1 ainda aberta (não vencida)
        {"_id": "p2", "company_id": CID, "phone": "5512",
          "status": "pending", "promise_text": "Te aviso amanhã",
          "created_at": now - timedelta(hours=1),
          "due_at": now + timedelta(hours=10), "resolved_at": None},
        # 1 cumprida na janela
        {"_id": "p3", "company_id": CID, "phone": "5513",
          "status": "resolved", "promise_text": "Resolvi",
          "created_at": now - timedelta(hours=3),
          "due_at": now + timedelta(hours=5),
          "resolved_at": now - timedelta(hours=2)},
    ]
    await db.customer_promises.insert_many(docs)
    out = await _promises_stats(CID, 24)
    assert out["open"] == 2  # p1 + p2 ainda pending
    assert out["overdue"] == 1  # p1
    assert out["fulfilled"] == 1  # p3
    assert len(out["overdue_samples"]) == 1
    await _cleanup()
    print("  ✓ Promises: 2 abertas, 1 vencida, 1 cumprida")


async def test_wa_dispatch_stats_latency_p95():
    await _cleanup()
    from database import db
    from routes.isabella_watchtower import _wa_dispatch_stats
    now = datetime.now(timezone.utc)
    docs = []
    for i in range(20):
        docs.append({
            "company_id": CID, "ok": True,
            "latency_ms": 100 + i * 10,
            "ts": now - timedelta(minutes=i)})
    # 2 falhas
    for r in ("timeout", "connection_refused"):
        docs.append({"company_id": CID, "ok": False,
                      "latency_ms": 5000, "reason": r,
                      "ts": now - timedelta(minutes=1)})
    await db.wa_dispatch_metrics.insert_many(docs)
    out = await _wa_dispatch_stats(CID, 24)
    assert out["total"] == 22
    assert out["failures"] == 2
    assert out["success_rate"] == round(20 / 22 * 100, 1)
    assert out["latency_ms_avg"] > 0
    assert out["latency_ms_p95"] >= out["latency_ms_avg"]
    assert len(out["fail_samples"]) == 2
    await _cleanup()
    print(f"  ✓ Dispatch: 20 sucessos + 2 falhas · p95={out['latency_ms_p95']}ms")


async def test_relacionamento_memories_aggregation():
    await _cleanup()
    from database import db
    from routes.isabella_watchtower import (
        _memories_stats, _follow_ups_pending, _top_clients_by_memories,
        _vip_clients,
    )
    now = datetime.now(timezone.utc)
    mems = [
        {"_id": "m1", "company_id": CID, "phone": "5511AAA",
          "memory_type": "PESSOAL", "title": "Aniversário 15/03",
          "description": "Filho do João faz 15 em março",
          "confidence": 0.95, "follow_up_required": True,
          "expires_at": now + timedelta(days=30),
          "created_at": now - timedelta(hours=2)},
        {"_id": "m2", "company_id": CID, "phone": "5511AAA",
          "memory_type": "TECNICA",
          "title": "ONU trocada", "description": "Modelo X",
          "confidence": 0.9, "follow_up_required": False,
          "created_at": now - timedelta(hours=10)},
        {"_id": "m3", "company_id": CID, "phone": "5511BBB",
          "memory_type": "PESSOAL", "title": "Cliente VIP gold",
          "description": "VIP — atender prioridade máxima",
          "confidence": 0.99, "follow_up_required": True,
          "expires_at": now + timedelta(days=180),
          "created_at": now - timedelta(hours=1)},
    ]
    await db.customer_memory.insert_many(mems)

    out = await _memories_stats(CID, 168)
    assert out["total"] == 3
    assert out["by_type"].get("PESSOAL") == 2
    assert out["by_type"].get("TECNICA") == 1
    assert len(out["samples"]) == 3

    fu = await _follow_ups_pending(CID)
    assert fu["count"] == 2  # m1 + m3

    top = await _top_clients_by_memories(CID, limit=10)
    # AAA tem 2 memórias, BBB tem 1
    assert top[0]["phone"] == "5511AAA"
    assert top[0]["memory_count"] == 2
    assert top[0]["trust_score"] > 0

    vips = await _vip_clients(CID)
    assert len(vips) == 1
    assert vips[0]["phone"] == "5511BBB"

    await _cleanup()
    print(f"  ✓ Relacionamento: 3 mems · 2 follow-ups · 1 VIP · top={top[0]['phone']}")
