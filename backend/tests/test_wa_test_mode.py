"""iter246 — WhatsApp Test Mode via UI Configurações.

Garante que:
  1. Sem setting no banco → default failsafe (enabled=True, número legado).
  2. Setting `enabled=False` no banco → libera envio real (homolog_active=False).
  3. `test_phone` editado no banco é usado pelo redirecionamento.
  4. Cache TTL é invalidado quando `_invalidate_settings_cache` é chamado.
"""
from __future__ import annotations

import asyncio
import importlib
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


def _run(coro_factory):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        d = c[os.environ["DB_NAME"]]
        import database as dm
        dm.db = d
        from services import homologation as homo
        importlib.reload(homo)
        await d.aihub_settings.delete_many(
            {"company_id": "co-test-wa", "key": "wa_test_mode"})
        try:
            return await coro_factory(d, homo)
        finally:
            await d.aihub_settings.delete_many(
                {"company_id": "co-test-wa", "key": "wa_test_mode"})
            c.close()
    return asyncio.new_event_loop().run_until_complete(_wrap())


def test_default_failsafe_when_no_setting():
    async def _t(db, homo):
        homo._invalidate_settings_cache()
        active = await homo.is_homolog_for("co-test-wa")
        phone = await homo.get_test_phone_for("co-test-wa")
        # Default env var HOMOLOG_MODE=true (não setado → default true)
        assert active is True
        assert phone == "5521998176526"
    _run(_t)


def test_db_setting_disabled_releases_real_send():
    async def _t(db, homo):
        homo._invalidate_settings_cache()
        await db.aihub_settings.update_one(
            {"company_id": "co-test-wa", "key": "wa_test_mode"},
            {"$set": {"value": {"enabled": False,
                                  "test_phone": "5521998176526"}}},
            upsert=True,
        )
        homo._invalidate_settings_cache("co-test-wa")
        active = await homo.is_homolog_for("co-test-wa")
        assert active is False, "setting enabled=false deve liberar envio real"
    _run(_t)


def test_db_setting_uses_custom_test_phone():
    async def _t(db, homo):
        homo._invalidate_settings_cache()
        await db.aihub_settings.update_one(
            {"company_id": "co-test-wa", "key": "wa_test_mode"},
            {"$set": {"value": {"enabled": True,
                                  "test_phone": "5511988887777"}}},
            upsert=True,
        )
        homo._invalidate_settings_cache("co-test-wa")
        phone = await homo.get_test_phone_for("co-test-wa")
        assert phone == "5511988887777"
    _run(_t)


def test_cache_invalidation_picks_up_new_value():
    async def _t(db, homo):
        homo._invalidate_settings_cache()
        # Estado inicial: enabled=True
        await db.aihub_settings.update_one(
            {"company_id": "co-test-wa", "key": "wa_test_mode"},
            {"$set": {"value": {"enabled": True,
                                  "test_phone": "5521998176526"}}},
            upsert=True,
        )
        homo._invalidate_settings_cache("co-test-wa")
        assert await homo.is_homolog_for("co-test-wa") is True

        # Alterado: enabled=False, MAS sem invalidar cache → ainda True
        await db.aihub_settings.update_one(
            {"company_id": "co-test-wa", "key": "wa_test_mode"},
            {"$set": {"value": {"enabled": False,
                                  "test_phone": "5521998176526"}}},
        )
        # Sem invalidação, cache ainda válido por 30s → mantém True
        assert await homo.is_homolog_for("co-test-wa") is True

        # Após invalidar → reflete novo valor
        homo._invalidate_settings_cache("co-test-wa")
        assert await homo.is_homolog_for("co-test-wa") is False
    _run(_t)


def test_safe_send_redirects_to_test_phone():
    """E2E: chamar safe_send_whatsapp com phone diferente → redireciona
    para o test_phone configurado no banco."""
    async def _t(db, homo):
        homo._invalidate_settings_cache()
        await db.aihub_settings.update_one(
            {"company_id": "co-test-wa", "key": "wa_test_mode"},
            {"$set": {"value": {"enabled": True,
                                  "test_phone": "5521998176526"}}},
            upsert=True,
        )
        homo._invalidate_settings_cache("co-test-wa")

        # Patch sidecar dispatch to avoid hitting real Baileys
        from services.wa import sidecar as _sc
        _orig = _sc._sidecar_post_silent

        async def _fake(path, payload):
            return {"ok": True, "id": "fake-sent"}
        _sc._sidecar_post_silent = _fake
        try:
            res = await homo.safe_send_whatsapp(
                company_id="co-test-wa",
                target_phone="5511999990000",   # número diferente
                message="hello",
                origin="pytest_iter246",
            )
        finally:
            _sc._sidecar_post_silent = _orig

        # Deve ter bloqueado (não whitelistado) e redirecionado
        assert res["blocked"] is True
        assert res["to_effective"] == "5521998176526"
        # Limpa eventos/outbox criados
        await db.motor_ia_events.delete_many({"company_id": "co-test-wa"})
        await db.wa_outbox.delete_many({"company_id": "co-test-wa"})
        await db.wa_messages_sent.delete_many({"company_id": "co-test-wa"})
    _run(_t)
