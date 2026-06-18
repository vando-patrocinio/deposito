"""Onda B — late_close_worker + cron job — testes de regressão."""
import asyncio
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
CID = "TEST-ONDA-B"


async def _cleanup():
    from database import db
    await db.tickets.delete_many({"company_id": CID})
    await db.stok_services.delete_many({"company_id": CID})
    await db.lousa_finalize_trace.delete_many({"company_id": CID})
    await db.late_close_runs.delete_many({"company_filter": CID})


async def _seed_finalized_ticket_with_active_svc(*, grace_secs_ago: int):
    """Cria ticket finalizado há `grace_secs_ago` + stok_service ativo."""
    from database import db
    tid = f"tkt-onda-b-{uuid.uuid4().hex[:8]}"
    sid = f"OS-OB-{uuid.uuid4().hex[:8]}"
    finalized = datetime.now(timezone.utc) - timedelta(seconds=grace_secs_ago)
    await db.tickets.insert_one({
        "id": tid, "company_id": CID, "status": "finalizada",
        "type": "reparo", "client_id": "cli-x",
        "client_snapshot": {"name": "T", "phone": "0", "address": "0"},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finalized_at": finalized.isoformat(),
        "outcome": "sucesso",
        "completion_data": {"qtd_drop": 0, "esticadores": 0,
                              "conectores_fast": 0, "cabo_rede": 0,
                              "conectores_rede": 0, "ont": None},
        "assigned_collaborator_id": "col-test",
        "assigned_collaborator_name": "Tech Test",
    })
    await db.stok_services.insert_one({
        "id": sid, "company_id": CID, "ticket_id": tid,
        "status": "ativo", "type": "reparo",
        "technician_id": "col-test",
        "created_at": (finalized - timedelta(seconds=2)).isoformat(),
    })
    return tid, sid


async def test_late_close_finds_finalized_ticket_with_active_svc():
    """Worker detecta stok_services 'ativo' cujo ticket finalizou."""
    await _cleanup()
    from services.late_close_worker import find_late_close_candidates
    tid, sid = await _seed_finalized_ticket_with_active_svc(
        grace_secs_ago=120,
    )
    cands = await find_late_close_candidates(
        company_id=CID, grace_seconds=60,
    )
    assert len(cands) == 1
    assert cands[0]["svc"]["id"] == sid
    await _cleanup()
    print("  ✓ Late close: detecta ticket finalizado há 120s")


async def test_late_close_respects_grace_period():
    """Ticket finalizado há < grace NÃO entra como candidato."""
    await _cleanup()
    from services.late_close_worker import find_late_close_candidates
    await _seed_finalized_ticket_with_active_svc(grace_secs_ago=10)
    cands = await find_late_close_candidates(
        company_id=CID, grace_seconds=60,
    )
    assert len(cands) == 0
    await _cleanup()
    print("  ✓ Late close: respeita grace (10s não entra com grace=60)")


async def test_late_close_dry_run_nao_altera():
    """Dry-run detecta mas não fecha."""
    await _cleanup()
    from database import db
    from services.late_close_worker import run_late_close
    tid, sid = await _seed_finalized_ticket_with_active_svc(
        grace_secs_ago=120,
    )
    stats = await run_late_close(
        company_id=CID, grace_seconds=60, dry_run=True,
    )
    assert stats["candidates_found"] == 1
    assert stats["closed_ok"] == 0
    s = await db.stok_services.find_one({"id": sid}, {"_id": 0, "status": 1})
    assert s["status"] == "ativo"  # ainda ativo
    await _cleanup()
    print("  ✓ Late close dry-run: detecta sem fechar")


async def test_late_close_real_fecha_e_marca():
    """Execução real fecha + marca late_closed=True."""
    await _cleanup()
    from database import db
    from services.late_close_worker import run_late_close
    tid, sid = await _seed_finalized_ticket_with_active_svc(
        grace_secs_ago=120,
    )
    stats = await run_late_close(
        company_id=CID, grace_seconds=60, dry_run=False,
    )
    assert stats["candidates_found"] == 1
    assert stats["closed_ok"] == 1
    s = await db.stok_services.find_one({"id": sid}, {"_id": 0})
    assert s["status"] == "fechado"
    assert s.get("late_closed") is True
    assert "late_closed_at" in s
    assert s.get("auto_closed") is True  # via auto_close_service_from_ticket
    await _cleanup()
    print("  ✓ Late close real: fecha OS + marca late_closed=True")


async def test_late_close_idempotente():
    """Rodar 2x não duplica nem reabre."""
    await _cleanup()
    from services.late_close_worker import run_late_close
    await _seed_finalized_ticket_with_active_svc(grace_secs_ago=120)
    s1 = await run_late_close(company_id=CID, grace_seconds=60)
    s2 = await run_late_close(company_id=CID, grace_seconds=60)
    assert s1["closed_ok"] == 1
    assert s2["candidates_found"] == 0  # já fechado
    await _cleanup()
    print("  ✓ Late close idempotente: 2ª execução = 0 candidatos")


async def test_late_close_grava_run_report():
    """Cada execução grava em late_close_runs."""
    from database import db
    await _cleanup()
    await db.late_close_runs.delete_many({"company_filter": CID})
    from services.late_close_worker import run_late_close
    await _seed_finalized_ticket_with_active_svc(grace_secs_ago=120)
    await run_late_close(company_id=CID, grace_seconds=60)
    n = await db.late_close_runs.count_documents({"company_filter": CID})
    assert n == 1
    await _cleanup()
    print("  ✓ Late close: relatório gravado em late_close_runs")


async def test_trace_phase_grava_doc():
    """trace_phase grava cada fase com timestamp + details."""
    from database import db
    from services.lousa_finalize_trace import (
        trace_phase, PHASE_ENTRY,
    )
    tid = f"tkt-trace-{uuid.uuid4().hex[:8]}"
    await db.lousa_finalize_trace.delete_many({"ticket_id": tid})
    await trace_phase(
        ticket_id=tid, company_id=CID, phase=PHASE_ENTRY,
        details={"type": "reparo", "outcome": "sucesso"},
    )
    r = await db.lousa_finalize_trace.find_one({"ticket_id": tid},
                                                  {"_id": 0})
    assert r["phase"] == PHASE_ENTRY
    assert r["outcome"] == "ok"
    assert r["details"]["type"] == "reparo"
    assert "ts" in r
    await db.lousa_finalize_trace.delete_many({"ticket_id": tid})
    print("  ✓ Trace phase: grava doc com ts + details")
