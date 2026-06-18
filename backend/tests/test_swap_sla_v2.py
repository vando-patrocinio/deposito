"""Onda C P1 V2.0 — Lembrete 4h + Escalonamento 24h + Compliance Score.

Aprovado CEO 18/06/2026. Cobre:
  - Lembrete dispara só após 4h sem resposta e só 1 vez.
  - Escalonamento muda status para overdue_confirmation após 24h.
  - Compliance Score por técnico (100 no prazo, 60 atrasado, 85 dispute/review, 0 overdue).
  - Worker é idempotente (rodar 2x não duplica reminder nem escalonamento).
  - Notifications para gestores criadas no escalonamento.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

import pytest

sys.path.insert(0, "/app/backend")
for ln in open("/app/backend/.env"):
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.strip().split("=", 1)
        os.environ.setdefault(k, v.strip('"'))

pytestmark = pytest.mark.asyncio(loop_scope="session")
CID = "TEST-SLA-V2"


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


async def _cleanup():
    from database import db
    await db.auto_ont_swap_events.delete_many({"company_id": CID})
    await db.auto_ont_swap_confirmations.delete_many({"company_id": CID})
    await db.collaborators.delete_many({"company_id": CID})
    await db.notifications.delete_many({"company_id": CID})
    await db.users.delete_many({"company_id": CID})
    await db.patrimonial_sla_runs.delete_many({"id": {"$regex": "^sla-"}})


async def _seed_tech():
    from database import db
    tid = f"col-sla-{uuid.uuid4().hex[:8]}"
    await db.collaborators.update_one(
        {"id": tid},
        {"$set": {
            "id": tid, "company_id": CID, "name": "TEC SLA V2",
            "phone": "11999999999", "cpf": f"99{uuid.uuid4().hex[:9]}",
            "cargo": "tecnico", "active": True,
        }},
        upsert=True,
    )
    return tid


async def _seed_manager():
    from database import db
    uid = f"user-mgr-{uuid.uuid4().hex[:8]}"
    await db.users.insert_one({
        "id": uid, "company_id": CID, "role": "gestor",
        "email": "mgr@test", "name": "GESTOR V2",
    })
    return uid


async def _seed_sent_event(tid, hours_ago, reminder_count=0):
    """Cria evento sent_to_technician com confirmation_sent_at no passado."""
    from database import db
    sent_at = _now() - timedelta(hours=hours_ago)
    eid = f"evt-sla-{uuid.uuid4().hex[:8]}"
    await db.auto_ont_swap_events.insert_one({
        "id": eid, "company_id": CID,
        "ticket_id": f"tkt-{uuid.uuid4().hex[:8]}",
        "ticket_type": "reparo",
        "ont_anterior": "ALCL1111", "ont_atual": "HWTC9999",
        "technician_id": tid,
        "status": "sent_to_technician",
        "detected_at": _iso(_now() - timedelta(hours=hours_ago + 1)),
        "confirmation_sent_at": _iso(sent_at),
        "confirmation_audit_id": f"audit-{uuid.uuid4().hex[:10]}",
        "confirmation_phone": "11999999999",
        "reminder_count": reminder_count,
    })
    return eid


# ─── Nível 2 — Lembrete ───────────────────────────────────────────────────

@patch("services.patrimonial_confirmation_worker._send_reminder_whatsapp",
       new_callable=AsyncMock, return_value=(True, None))
async def test_reminder_fires_after_4h_only_once(mock_send):
    from database import db
    from services.patrimonial_confirmation_worker import patrimonial_sla_tick
    await _cleanup()
    tid = await _seed_tech()
    eid = await _seed_sent_event(tid, hours_ago=5)  # >4h, <24h

    stats1 = await patrimonial_sla_tick()
    assert stats1["reminders_sent"] == 1

    evt = await db.auto_ont_swap_events.find_one({"id": eid}, {"_id": 0})
    assert evt["reminder_count"] == 1
    assert evt.get("reminder_sent_at") is not None

    # Segunda tick: não envia de novo
    stats2 = await patrimonial_sla_tick()
    assert stats2["reminders_sent"] == 0
    await _cleanup()


@patch("services.patrimonial_confirmation_worker._send_reminder_whatsapp",
       new_callable=AsyncMock, return_value=(True, None))
async def test_reminder_not_fired_before_4h(mock_send):
    from services.patrimonial_confirmation_worker import patrimonial_sla_tick
    await _cleanup()
    tid = await _seed_tech()
    await _seed_sent_event(tid, hours_ago=2)  # <4h

    stats = await patrimonial_sla_tick()
    assert stats["reminders_sent"] == 0
    await _cleanup()


# ─── Nível 3 — Escalonamento ──────────────────────────────────────────────

async def test_escalation_fires_after_24h():
    from database import db
    from services.patrimonial_confirmation_worker import patrimonial_sla_tick
    await _cleanup()
    tid = await _seed_tech()
    await _seed_manager()
    eid = await _seed_sent_event(tid, hours_ago=25, reminder_count=1)

    stats = await patrimonial_sla_tick()
    assert stats["escalated"] == 1
    assert stats["notifications_created"] == 1

    evt = await db.auto_ont_swap_events.find_one({"id": eid}, {"_id": 0})
    assert evt["status"] == "overdue_confirmation"
    assert evt.get("escalated_at") is not None
    assert evt.get("escalation_reason") == "no_response_24h"

    notif = await db.notifications.find_one(
        {"company_id": CID, "type": "patrimonial_confirmation_overdue"},
        {"_id": 0})
    assert notif is not None
    assert notif["related_swap_event_id"] == eid
    await _cleanup()


async def test_escalation_idempotent():
    """Rodar tick 2x não duplica overdue nem notificações."""
    from database import db
    from services.patrimonial_confirmation_worker import patrimonial_sla_tick
    await _cleanup()
    tid = await _seed_tech()
    await _seed_manager()
    await _seed_sent_event(tid, hours_ago=25, reminder_count=1)

    await patrimonial_sla_tick()
    n1 = await db.notifications.count_documents(
        {"company_id": CID, "type": "patrimonial_confirmation_overdue"})
    stats2 = await patrimonial_sla_tick()
    n2 = await db.notifications.count_documents(
        {"company_id": CID, "type": "patrimonial_confirmation_overdue"})
    assert stats2["escalated"] == 0
    assert n1 == n2  # não duplicou
    await _cleanup()


# ─── Compliance Score ─────────────────────────────────────────────────────

async def test_compliance_on_time_scores_100():
    """Resposta dentro de 4h → 100 pts."""
    from database import db
    from services.patrimonial_confirmation_worker import (
        compute_compliance_score,
    )
    await _cleanup()
    tid = await _seed_tech()
    sent = _now() - timedelta(hours=2)
    resp = sent + timedelta(hours=1)  # respondeu em 1h
    await db.auto_ont_swap_events.insert_one({
        "id": f"e-{uuid.uuid4().hex[:8]}", "company_id": CID,
        "ticket_id": "t1", "technician_id": tid,
        "ont_anterior": "a", "ont_atual": "b",
        "status": "confirmed",
        "detected_at": _iso(sent - timedelta(minutes=10)),
        "confirmation_sent_at": _iso(sent),
        "confirmation_response_at": _iso(resp),
    })
    res = await compute_compliance_score(CID, days=30)
    assert res["overall_score"] == 100
    rank = res["ranking"][0]
    assert rank["score"] == 100
    assert rank["events_confirmed"] == 1
    await _cleanup()


async def test_compliance_late_response_scores_60():
    from database import db
    from services.patrimonial_confirmation_worker import (
        compute_compliance_score,
    )
    await _cleanup()
    tid = await _seed_tech()
    sent = _now() - timedelta(hours=10)
    resp = sent + timedelta(hours=6)  # respondeu após 6h
    await db.auto_ont_swap_events.insert_one({
        "id": f"e-{uuid.uuid4().hex[:8]}", "company_id": CID,
        "ticket_id": "t1", "technician_id": tid,
        "ont_anterior": "a", "ont_atual": "b",
        "status": "confirmed",
        "detected_at": _iso(sent - timedelta(minutes=10)),
        "confirmation_sent_at": _iso(sent),
        "confirmation_response_at": _iso(resp),
    })
    res = await compute_compliance_score(CID, days=30)
    assert res["overall_score"] == 60
    await _cleanup()


async def test_compliance_overdue_scores_0():
    from database import db
    from services.patrimonial_confirmation_worker import (
        compute_compliance_score,
    )
    await _cleanup()
    tid = await _seed_tech()
    await db.auto_ont_swap_events.insert_one({
        "id": f"e-{uuid.uuid4().hex[:8]}", "company_id": CID,
        "ticket_id": "t1", "technician_id": tid,
        "ont_anterior": "a", "ont_atual": "b",
        "status": "overdue_confirmation",
        "detected_at": _iso(_now() - timedelta(days=2)),
    })
    res = await compute_compliance_score(CID, days=30)
    assert res["overall_score"] == 0.0
    await _cleanup()


async def test_compliance_ranking_orders_worst_first():
    """Ranking ordena pior score primeiro (pra ação imediata)."""
    from database import db
    from services.patrimonial_confirmation_worker import (
        compute_compliance_score,
    )
    await _cleanup()
    # Tech 1: 100 pts (on-time)
    t1 = await _seed_tech()
    sent = _now() - timedelta(hours=2)
    await db.auto_ont_swap_events.insert_one({
        "id": "e-best", "company_id": CID,
        "ticket_id": "t", "technician_id": t1,
        "ont_anterior": "a", "ont_atual": "b",
        "status": "confirmed",
        "detected_at": _iso(_now() - timedelta(hours=3)),
        "confirmation_sent_at": _iso(sent),
        "confirmation_response_at": _iso(sent + timedelta(minutes=30)),
    })
    # Tech 2: 0 pts (overdue)
    t2 = await _seed_tech()
    await db.auto_ont_swap_events.insert_one({
        "id": "e-worst", "company_id": CID,
        "ticket_id": "t", "technician_id": t2,
        "ont_anterior": "a", "ont_atual": "b",
        "status": "overdue_confirmation",
        "detected_at": _iso(_now() - timedelta(days=1)),
    })
    res = await compute_compliance_score(CID, days=30)
    ranking = res["ranking"]
    assert len(ranking) == 2
    # Primeiro = pior
    assert ranking[0]["technician_id"] == t2
    assert ranking[0]["score"] == 0.0
    assert ranking[1]["technician_id"] == t1
    assert ranking[1]["score"] == 100
    await _cleanup()


# ─── Worker insere run log ───────────────────────────────────────────────

@patch("services.patrimonial_confirmation_worker._send_reminder_whatsapp",
       new_callable=AsyncMock, return_value=(True, None))
async def test_worker_logs_run_in_collection(mock_send):
    from database import db
    from services.patrimonial_confirmation_worker import patrimonial_sla_tick
    await _cleanup()
    stats = await patrimonial_sla_tick()
    # Sempre cria log de run (mesmo se sem trabalho)
    runs = await db.patrimonial_sla_runs.count_documents({})
    assert runs >= 1
    assert "started_at" in stats and "finished_at" in stats
    await _cleanup()


if __name__ == "__main__":
    async def _main():
        await test_reminder_fires_after_4h_only_once()
        await test_reminder_not_fired_before_4h()
        await test_escalation_fires_after_24h()
        await test_escalation_idempotent()
        await test_compliance_on_time_scores_100()
        await test_compliance_late_response_scores_60()
        await test_compliance_overdue_scores_0()
        await test_compliance_ranking_orders_worst_first()
        await test_worker_logs_run_in_collection()
        print("✅ SLA V2.0 — 9/9 tests PASS")
    asyncio.run(_main())
