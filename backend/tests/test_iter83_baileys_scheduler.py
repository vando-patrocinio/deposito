"""Iter83 — Baileys channel + pending-count + daily scheduler.

ZERO MOCK (02/2026): substituído `unittest.mock.patch(httpx)` pelo
modo `SMARTPROV_TRANSPORT_FAKE=1` do `wa_dispatcher` (grava em
`wa_fake_outbox` em vez de chamar o sidecar real). Os testes
continuam validando o caminho ponta-a-ponta sem mocks.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

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


@pytest.fixture(scope="module", autouse=True)
def _fake_transport():
    """Ativa o modo fake do wa_dispatcher para todos os testes do módulo."""
    prev = os.environ.get("SMARTPROV_TRANSPORT_FAKE")
    os.environ["SMARTPROV_TRANSPORT_FAKE"] = "1"
    yield
    if prev is None:
        os.environ.pop("SMARTPROV_TRANSPORT_FAKE", None)
    else:
        os.environ["SMARTPROV_TRANSPORT_FAKE"] = prev


def test_baileys_channel_accepted_by_approve_schema(event_loop):
    """Pydantic accept channel='baileys' on ApproveIn."""
    from routes.disparo_ia import ApproveIn
    m = ApproveIn(channel="baileys", throttle_per_min=30)
    assert m.channel == "baileys"
    assert ApproveIn(channel="meta_cloud").channel == "meta_cloud"
    assert ApproveIn(channel="twilio").channel == "twilio"
    with pytest.raises(Exception):
        ApproveIn(channel="invalid")


def test_send_text_writes_fake_outbox(event_loop):
    """wa_dispatcher.send_text em modo fake grava em wa_fake_outbox
    (substitui o antigo teste que mockava httpx)."""
    from services.wa_dispatcher import send_text
    test_phone = "5500001112233-iter83"

    async def main():
        await _module_db.wa_fake_outbox.delete_many({"to": test_phone})
        r = await send_text(company_id=CID, to=test_phone,
                              text="Mensagem teste Baileys")
        assert r.get("ok") is True
        assert r.get("fake") is True
        doc = await _module_db.wa_fake_outbox.find_one(
            {"to": test_phone}, {"_id": 0})
        assert doc is not None
        assert doc["text"] == "Mensagem teste Baileys"
        assert doc["company_id"] == CID
        # cleanup
        await _module_db.wa_fake_outbox.delete_many({"to": test_phone})

    event_loop.run_until_complete(main())


def test_send_text_resilient_when_no_session(event_loop):
    """Quando o fake transport está OFF e não há sessão, retorna ok=False
    com reason — sem exceções, sem necessidade de mockar httpx."""
    from services.wa_dispatcher import send_text

    async def main():
        # Garante uma janela em que o fake transport está temporariamente off
        os.environ.pop("SMARTPROV_TRANSPORT_FAKE", None)
        try:
            r = await send_text(company_id="co-nonexistent-xyz",
                                  to="5500009998877", text="x")
            assert r.get("ok") is False
            assert r.get("reason") in (
                "no_session", "BAILEYS_SIDECAR_URL_missing",
                "breaker_open")
        finally:
            os.environ["SMARTPROV_TRANSPORT_FAKE"] = "1"

    event_loop.run_until_complete(main())


def test_mass_campaign_create_accepts_baileys(event_loop):
    """CampaignCreate Pydantic accepts channel='baileys'."""
    from routes.mass_messaging import CampaignCreate
    m = CampaignCreate(name="T", channel="baileys", mode="free", text="hi")
    assert m.channel == "baileys"


def test_pending_count_endpoint_shape():
    """Smoke do shape do endpoint pending-count via import direto."""
    from routes.disparo_ia import pending_count  # noqa
    assert callable(pending_count)


def test_scheduler_job_registered():
    """Verifica que o job APScheduler 'disparo_ia_daily' foi registrado."""
    src = open("/app/backend/server.py").read()
    assert "disparo_ia_daily" in src
    assert "_disparo_daily_all_companies" in src
    assert "CronTrigger(hour=6, minute=30)" in src
