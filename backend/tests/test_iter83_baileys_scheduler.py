"""Iter83 — Baileys channel + pending-count + daily scheduler."""
import asyncio
import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, "/app/backend")
from database import db as _module_db  # noqa: E402


CID = "co-demo"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def test_baileys_channel_accepted_by_approve_schema(event_loop):
    """Pydantic accept channel='baileys' on ApproveIn."""
    from routes.disparo_ia import ApproveIn
    m = ApproveIn(channel="baileys", throttle_per_min=30)
    assert m.channel == "baileys"
    # Also still accepts meta_cloud and twilio
    assert ApproveIn(channel="meta_cloud").channel == "meta_cloud"
    assert ApproveIn(channel="twilio").channel == "twilio"
    with pytest.raises(Exception):
        ApproveIn(channel="invalid")


def test_send_baileys_calls_sidecar_and_persists(event_loop):
    """_send_baileys POST sidecar /send + grava em aihub_wa_messages."""
    from routes.mass_messaging import _send_baileys
    test_phone = "5500001112233"

    camp = {
        "id": "camp-iter83-test",
        "company_id": CID,
        "origin": "disparo_ia",
        "channel": "baileys",
    }
    rec = {"phone": test_phone, "vars": {"nome": "Cliente"}}

    async def main():
        # mock httpx response
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json = MagicMock(return_value={"ok": True, "message_id": "BAIL123"})

        class FakeCli:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, json=None, **kw):
                assert "/send" in url
                assert json["phone"] == test_phone
                assert "Mensagem teste" in json["text"]
                return fake_resp

        with patch.object(httpx, "AsyncClient", lambda **kw: FakeCli()):
            await _module_db.aihub_wa_messages.delete_many(
                {"campaign_id": "camp-iter83-test"})
            r = await _send_baileys(camp, rec, "Mensagem teste Baileys")
            assert r == {"ok": True, "message_id": "BAIL123"}

            # Verifica que persistiu no histórico
            doc = await _module_db.aihub_wa_messages.find_one(
                {"campaign_id": "camp-iter83-test"}, {"_id": 0})
            assert doc is not None
            assert doc["channel"] == "baileys"
            assert doc["direction"] == "outbound"
            assert doc["phone"] == test_phone
            assert doc["text"] == "Mensagem teste Baileys"
            assert doc["delivery_status"] == "sent"
            assert doc["actor_user"] == "disparo_ia"
            assert doc["auto_reply"] is False
            assert doc["campaign_origin"] == "disparo_ia"

            # Cleanup
            await _module_db.aihub_wa_messages.delete_many(
                {"campaign_id": "camp-iter83-test"})

    event_loop.run_until_complete(main())


def test_send_baileys_returns_error_on_sidecar_failure(event_loop):
    from routes.mass_messaging import _send_baileys

    async def main():
        fake_resp = MagicMock()
        fake_resp.status_code = 500
        fake_resp.json = MagicMock(return_value={"ok": False, "error": "socket dead"})

        class FakeCli:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, json=None, **kw):
                return fake_resp

        with patch.object(httpx, "AsyncClient", lambda **kw: FakeCli()):
            r = await _send_baileys(
                {"id": "camp-x", "company_id": CID, "origin": "disparo_ia"},
                {"phone": "5500009998877", "vars": {}}, "x",
            )
            assert r["ok"] is False
            assert "socket dead" in r["error"] or "500" in r["error"]

    event_loop.run_until_complete(main())


def test_mass_campaign_create_accepts_baileys(event_loop):
    """CampaignCreate Pydantic accepts channel='baileys'."""
    from routes.mass_messaging import CampaignCreate
    m = CampaignCreate(name="T", channel="baileys", mode="free", text="hi")
    assert m.channel == "baileys"


def test_pending_count_endpoint_shape():
    """Smoke do shape do endpoint pending-count via import direto."""
    from routes.disparo_ia import pending_count  # noqa
    # endpoint existe e é callable; teste real é via HTTP
    assert callable(pending_count)


def test_scheduler_job_registered():
    """Verifica que o job APScheduler 'disparo_ia_daily' foi registrado."""
    # Não conseguimos inspecionar scheduler em runtime aqui (vive no server.py),
    # mas a inscrição é checada por inspeção do código fonte:
    src = open("/app/backend/server.py").read()
    assert "disparo_ia_daily" in src
    assert "_disparo_daily_all_companies" in src
    assert "CronTrigger(hour=6, minute=30)" in src
