"""Testes da FASE 3 da Constituição V3.0 — Sistema Nervoso 90%."""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


CO = "test-ns-pytest"


def _run(coro_factory):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        import importlib
        import database as database_mod
        database_mod.db = db
        from services import event_bus, event_emitters
        importlib.reload(event_bus)
        importlib.reload(event_emitters)
        from services import nervous_synchronizer, nervous_coverage
        importlib.reload(nervous_synchronizer)
        importlib.reload(nervous_coverage)

        # cleanup
        for col in ("motor_ia_events", "subscriber_invoices",
                     "tickets", "appointments", "referrals",
                     "nervous_checkpoints", "smartolt_onus",
                     "parcerias_redemptions", "stok_history",
                     "clock_records", "aihub_wa_messages",
                     "sales_leads", "fin_cash_movements",
                     "signal_degradation_alerts", "ticket_logs"):
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro_factory(db, nervous_synchronizer,
                                            nervous_coverage)
        finally:
            for col in ("motor_ia_events", "subscriber_invoices",
                         "tickets", "appointments", "referrals",
                         "nervous_checkpoints", "smartolt_onus",
                         "parcerias_redemptions", "stok_history",
                         "clock_records", "aihub_wa_messages",
                         "sales_leads", "fin_cash_movements",
                         "signal_degradation_alerts", "ticket_logs"):
                await db[col].delete_many({"company_id": CO})
            client.close()
    return asyncio.run(_wrap())


def test_synchronizer_emits_invoice_created():
    async def go(db, ns, nc):
        # Checkpoint=now() para isolar do produção
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        for plan in ns.SYNC_PLAN:
            await ns._set_checkpoint(plan["collection"],
                                            plan["kind"], now)
        await asyncio.sleep(0.05)
        new_iso = datetime.now(timezone.utc).isoformat()
        await db.subscriber_invoices.insert_one({
            "id": "inv-ns-1", "company_id": CO,
            "subscriber_external_id": "ext-1",
            "amount": 99.9, "due_date": "2026-06-15",
            "status": "open",
            "created_at": new_iso,
        })
        r = await ns.run_synchronization()
        # Pelo menos 1 (o nosso). Pode haver outros tenants em paralelo.
        assert r["per_kind"]["invoice.created"] >= 1
        # idempotência: rodar de novo não duplica do nosso
        before = await db.motor_ia_events.count_documents(
            {"company_id": CO, "event_type": "INVOICE_CREATED"})
        await ns.run_synchronization()
        after = await db.motor_ia_events.count_documents(
            {"company_id": CO, "event_type": "INVOICE_CREATED"})
        assert after == before
    _run(go)


def test_coverage_report_structure():
    async def go(db, ns, nc):
        from services.event_bus import emit_event, EventType
        await emit_event(EventType.INVOICE_CREATED,
                              company_id=CO, source="test")
        await emit_event(EventType.TICKET_OPENED,
                              company_id=CO, source="test")
        r = await nc.coverage_report(CO, window_days=1)
        assert "overall_coverage_pct" in r
        assert "domains" in r
        assert r["domains"]["financeiro"]["event_count"] >= 1
        assert r["domains"]["atendimento"]["event_count"] >= 1
        # Pelo menos 2 tipos cobertos
        assert r["total_covered_types"] >= 2
        assert r["level"] in ("VERDE", "AMARELO", "VERMELHO")
    _run(go)


def test_what_happened_today():
    async def go(db, ns, nc):
        from services.event_bus import emit_event, EventType
        for _ in range(3):
            await emit_event(EventType.WA_INBOUND_RECEIVED,
                                  company_id=CO, source="test")
        r = await nc.what_happened_today(CO)
        assert "headline" in r
        assert "bullets" in r
        assert any("Whatsapp" in b or "whatsapp" in b.lower()
                    for b in r["bullets"])
        assert r["domain_counts"]["whatsapp"] >= 3
    _run(go)


def test_top_events_descending_count():
    async def go(db, ns, nc):
        from services.event_bus import emit_event, EventType
        for _ in range(5):
            await emit_event(EventType.INVOICE_CREATED,
                                  company_id=CO, source="test")
        for _ in range(2):
            await emit_event(EventType.TICKET_OPENED,
                                  company_id=CO, source="test")
        items = await nc.top_events(CO, hours=24, limit=10)
        # mais frequente primeiro
        assert items[0]["count"] >= items[-1]["count"]
        assert items[0]["event_type"] == "INVOICE_CREATED"
    _run(go)


def test_synchronizer_skips_no_company_id():
    async def go(db, ns, nc):
        from datetime import datetime, timezone
        # Checkpoint=now() para zerar histórico de produção
        now = datetime.now(timezone.utc).isoformat()
        for plan in ns.SYNC_PLAN:
            await ns._set_checkpoint(plan["collection"],
                                            plan["kind"], now)
        await asyncio.sleep(0.05)
        await db.subscriber_invoices.insert_one({
            "id": "inv-no-co", "subscriber_external_id": "ext-2",
            "amount": 50, "due_date": "2026-06-15",
            "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        # nenhum evento deste invoice (sem company_id) deve aparecer
        before = await db.motor_ia_events.count_documents(
            {"event_type": "INVOICE_CREATED",
             "payload.id": "inv-no-co"})
        await ns.run_synchronization()
        after = await db.motor_ia_events.count_documents(
            {"event_type": "INVOICE_CREATED",
             "payload.id": "inv-no-co"})
        assert after == before  # guard tenant leak não emitiu
        await db.subscriber_invoices.delete_many({"id": "inv-no-co"})
    _run(go)


def test_tenant_isolation():
    async def go(db, ns, nc):
        from services.event_bus import emit_event, EventType
        await emit_event(EventType.INVOICE_PAID,
                              company_id=CO, source="t")
        await emit_event(EventType.INVOICE_PAID,
                              company_id="other-co", source="t")
        r_co = await nc.coverage_report(CO, window_days=1)
        r_other = await nc.coverage_report("other-co", window_days=1)
        assert r_co["domains"]["financeiro"]["event_count"] == 1
        assert r_other["domains"]["financeiro"]["event_count"] == 1
        # cleanup
        await db.motor_ia_events.delete_many({"company_id": "other-co"})
    _run(go)
