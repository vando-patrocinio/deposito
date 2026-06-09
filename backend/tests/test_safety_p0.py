"""test_safety_p0.py — Kill Switch + Backup + Vault (smoke).

Cobre as 3 medidas P0 entregues em 2026-06-09:
  - kill_switch.set_state / is_off
  - homologation.safe_send_whatsapp respeita kill_switch.whatsapp
  - mongo_backup.list_backups / purge_old (sem dump real)
  - secrets_vault.set_secret / get_secret / list / delete
"""
from __future__ import annotations
import asyncio
import importlib
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CO = "test-safety-p0-co"
KS_COLLS = ["system_killswitch", "audit_log", "secrets_vault",
            "motor_ia_events", "wa_outbox", "wa_messages_sent"]


def _run(coro):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        os.environ["HOMOLOG_MODE"] = "true"
        # Master key efêmera só para o teste
        os.environ["SECRETS_MASTER_KEY"] = \
            "g8VGsZw6cn2k1MBYRT3Yz_lqAVk-mTfL2Y3yLEvxbXk="
        # ISOLAR de produção — usar DB dedicado para evitar wipe de
        # `secrets_vault`, `audit_log` etc do banco real.
        test_db_name = f"{os.environ['DB_NAME']}__test_safety_p0"
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[test_db_name]
        import database as dm
        dm.db = db
        from services import kill_switch, secrets_vault, homologation
        importlib.reload(kill_switch)
        importlib.reload(secrets_vault)
        importlib.reload(homologation)
        for col in KS_COLLS:
            await db[col].delete_many({})
        try:
            return await coro(db, kill_switch, secrets_vault, homologation)
        finally:
            await c.drop_database(test_db_name)
            c.close()
    return asyncio.new_event_loop().run_until_complete(_wrap())


def test_kill_switch_set_and_query():
    """set_state persiste, get_state lê, is_off responde."""
    async def t(db, ks, _v, _h):
        # Default = OFF=false
        s = await ks.get_state("whatsapp")
        assert s["off"] is False

        # Ligar
        await ks.set_state("whatsapp", off=True,
                           reason="teste", updated_by="pytest")
        assert await ks.is_off("whatsapp") is True

        # Auditoria
        audit = await db.audit_log.find_one({"kind": "killswitch_toggle"})
        assert audit and audit["component"] == "whatsapp"

        # Desligar
        await ks.set_state("whatsapp", off=False, updated_by="pytest")
        assert await ks.is_off("whatsapp") is False
    _run(t)


def test_kill_switch_global_overrides():
    """Quando global está OFF, todos componentes ficam OFF."""
    async def t(db, ks, _v, _h):
        await ks.set_state("global", off=True, updated_by="pytest")
        # WhatsApp não foi setado, mas global=OFF derruba
        assert await ks.is_off("whatsapp") is True
        assert await ks.is_off("ai_actions") is True

        await ks.set_state("global", off=False, updated_by="pytest")
        assert await ks.is_off("whatsapp") is False
    _run(t)


def test_homologation_respects_killswitch():
    """safe_send_whatsapp bloqueia ANTES de tentar enviar quando KS=OFF."""
    async def t(db, ks, _v, homo):
        # Liga kill switch do whatsapp
        await ks.set_state("whatsapp", off=True,
                           reason="teste de bloqueio", updated_by="pytest")

        out = await homo.safe_send_whatsapp(
            company_id=CO,
            target_phone=homo.TEST_PHONE,
            message="ping",
            origin="ks_test")

        assert out["blocked"] is True
        assert out["status"] == "blocked_killswitch"
        assert "kill_switch.whatsapp" in (out.get("blocked_reason") or "")

        # NÃO deve ter criado wa_outbox/wa_messages_sent
        ob = await db.wa_outbox.find_one({"company_id": CO})
        assert ob is None
        sent = await db.wa_messages_sent.find_one({"company_id": CO})
        assert sent is None

        # Religa
        await ks.set_state("whatsapp", off=False, updated_by="pytest")
        out2 = await homo.safe_send_whatsapp(
            company_id=CO,
            target_phone=homo.TEST_PHONE,
            message="ping ok")
        assert out2["status"] != "blocked_killswitch"
    _run(t)


def test_secrets_vault_round_trip():
    """set → get retorna o mesmo plaintext; list não vaza valor."""
    async def t(db, _ks, vault, _h):
        assert vault.is_available() is True

        await vault.set_secret(
            name="TEST_TOKEN", value="super-secret-abc-123",
            scope="pilot-co", updated_by="pytest", hint="token de teste")

        # Get retorna plaintext
        v = await vault.get_secret("TEST_TOKEN", scope="pilot-co")
        assert v == "super-secret-abc-123"

        # List retorna metadados SEM valor
        lst = await vault.list_secrets(scope="pilot-co")
        assert lst["count"] == 1
        item = lst["items"][0]
        assert item["name"] == "TEST_TOKEN"
        assert item["scope"] == "pilot-co"
        assert "value" not in item
        assert "ciphertext" not in item

        # Auditoria
        audit = await db.audit_log.find_one({"kind": "secret_set"})
        assert audit and audit["name"] == "TEST_TOKEN"

        # Delete
        d = await vault.delete_secret("TEST_TOKEN", scope="pilot-co",
                                      deleted_by="pytest")
        assert d["ok"] is True
        v2 = await vault.get_secret("TEST_TOKEN", scope="pilot-co")
        assert v2 is None
    _run(t)


def test_secrets_vault_unavailable_without_key():
    """Sem MASTER_KEY: get/set falham gracefully (sem crash)."""
    import importlib as _il
    os.environ.pop("SECRETS_MASTER_KEY", None)
    from services import secrets_vault as v
    _il.reload(v)
    assert v.is_available() is False
    # Restaurar para próximos testes
    os.environ["SECRETS_MASTER_KEY"] = \
        "g8VGsZw6cn2k1MBYRT3Yz_lqAVk-mTfL2Y3yLEvxbXk="


def test_mongo_backup_list_and_purge_no_crash():
    """list_backups / purge_old funcionam mesmo sem snapshots."""
    from services import mongo_backup as bk
    os.environ["BACKUP_DIR"] = "/tmp/smartprov_test_backups"
    os.environ["BACKUP_RETENTION_DAYS"] = "30"

    lst = bk.list_backups()
    assert isinstance(lst, list)

    purged = bk.purge_old()
    assert isinstance(purged, list)
