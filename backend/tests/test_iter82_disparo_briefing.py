"""Iter82 — Disparo IA · briefing injection no system_prompt da Isabella."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, "/app/backend")
# Importa o módulo cedo pra que 'db' (motor singleton) carregue no loop atual
from database import db as _module_db  # noqa: E402
from services.disparo_briefing import fetch_disparo_briefing_for_phone  # noqa: E402


CID = "co-demo"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def test_briefing_injected_when_phone_has_recent_campaign(event_loop):
    phone = "5599999000111"
    camp_id = "test-camp-disparo-briefing-iter82"
    rec_id = "test-rec-disparo-briefing-iter82"

    async def main():
        now = _now_iso()
        await _module_db.mass_campaigns.delete_many({"id": camp_id})
        await _module_db.mass_recipients.delete_many({"id": rec_id})
        await _module_db.mass_campaigns.insert_one({
            "id": camp_id, "company_id": CID,
            "name": "TEST · Upsell Fibra 600",
            "channel": "meta_cloud", "mode": "free",
            "text": "Oi {{nome}}! Tem upgrade rolando.",
            "origin": "disparo_ia",
            "disparo_type": "plan_upsell",
            "isabella_briefing":
                "Tom amistoso. Se cliente perguntar preço, ofereça 3 opções. "
                "Escale humano se mencionar concorrente direto.",
            "expected_kpis": {"reply_rate_min": 0.3},
            "status": "running", "created_at": now,
        })
        await _module_db.mass_recipients.insert_one({
            "id": rec_id, "campaign_id": camp_id, "company_id": CID,
            "phone": phone, "name": "Cliente Teste",
            "status": "sent",
            "queued_at": now, "sent_at": now,
        })
        try:
            block = await fetch_disparo_briefing_for_phone(CID, phone)
            assert block is not None
            assert "DISPARO IA" in block
            assert "Upsell" in block
            assert "Tom amistoso" in block
            assert "humano" in block.lower()
        finally:
            await _module_db.mass_campaigns.delete_many({"id": camp_id})
            await _module_db.mass_recipients.delete_many({"id": rec_id})

    event_loop.run_until_complete(main())


def test_briefing_skipped_for_unknown_phone(event_loop):
    async def main():
        block = await fetch_disparo_briefing_for_phone(CID, "5500000000000")
        assert block is None

    event_loop.run_until_complete(main())


def test_briefing_skipped_for_non_disparo_campaign(event_loop):
    phone = "5511122223333"
    camp_id = "test-camp-manual-iter82"
    rec_id = "test-rec-manual-iter82"

    async def main():
        now = _now_iso()
        await _module_db.mass_campaigns.insert_one({
            "id": camp_id, "company_id": CID,
            "name": "TEST · Manual sem origin",
            "channel": "meta_cloud", "mode": "free",
            "isabella_briefing": "isso aqui não deveria vazar",
            "status": "running", "created_at": now,
        })
        await _module_db.mass_recipients.insert_one({
            "id": rec_id, "campaign_id": camp_id, "company_id": CID,
            "phone": phone, "status": "sent",
            "sent_at": now, "queued_at": now,
        })
        try:
            block = await fetch_disparo_briefing_for_phone(CID, phone)
            assert block is None
        finally:
            await _module_db.mass_campaigns.delete_many({"id": camp_id})
            await _module_db.mass_recipients.delete_many({"id": rec_id})

    event_loop.run_until_complete(main())


def test_briefing_skipped_for_old_campaign(event_loop):
    phone = "5544455566677"
    camp_id = "test-camp-old-disparo-iter82"
    rec_id = "test-rec-old-disparo-iter82"

    async def main():
        old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        await _module_db.mass_campaigns.insert_one({
            "id": camp_id, "company_id": CID,
            "name": "TEST · Antiga",
            "channel": "meta_cloud", "mode": "free",
            "origin": "disparo_ia",
            "disparo_type": "churn_recovery",
            "isabella_briefing": "briefing antigo",
            "status": "done", "created_at": old,
        })
        await _module_db.mass_recipients.insert_one({
            "id": rec_id, "campaign_id": camp_id, "company_id": CID,
            "phone": phone, "status": "sent",
            "sent_at": old, "queued_at": old,
        })
        try:
            block = await fetch_disparo_briefing_for_phone(CID, phone)
            assert block is None
        finally:
            await _module_db.mass_campaigns.delete_many({"id": camp_id})
            await _module_db.mass_recipients.delete_many({"id": rec_id})

    event_loop.run_until_complete(main())
