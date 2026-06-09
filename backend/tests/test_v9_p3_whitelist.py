"""test_v9_p3_whitelist.py — V9 P3 Whitelist CAUSALITY_PILOT_PHONES.

Garante a liberação cirúrgica do gateway de homologação:
  - whitelist vazia → comportamento V8 (bloqueia, mascara, prefixa)
  - número whitelistado → envia ao original sem máscara/prefixo,
    com environment="causality_pilot" e evento CAUSALITY_PILOT_REAL_SEND
  - HOMOLOG_MODE permanece true em ambos os casos (invariante)
  - números NÃO whitelistados continuam bloqueados mesmo após carregar
    a whitelist (isolamento)
  - parse robusto da env var (CSV, espaços, prefixo 55 opcional)
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

CO = "test-v9-p3-whitelist-co"
COLLS = ["motor_ia_events", "wa_outbox", "wa_messages_sent"]
WHITELISTED_PHONE = "5511955554444"  # número fictício do piloto
NON_WHITELISTED_PHONE = "5511966667777"


def _run(coro, whitelist_env: str = ""):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        os.environ["HOMOLOG_MODE"] = "true"  # invariante
        os.environ["CAUSALITY_PILOT_PHONES"] = whitelist_env
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import database as dm
        dm.db = db
        from services import homologation as homo
        importlib.reload(homo)
        for col in COLLS:
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro(db, homo)
        finally:
            for col in COLLS:
                await db[col].delete_many({"company_id": CO})
            os.environ["CAUSALITY_PILOT_PHONES"] = ""
            c.close()
    return asyncio.new_event_loop().run_until_complete(_wrap())


def test_whitelist_empty_parses_to_empty_set():
    from services import homologation as homo
    os.environ["CAUSALITY_PILOT_PHONES"] = ""
    importlib.reload(homo)
    assert homo._parse_whitelist() == set()
    assert homo.is_whitelisted(WHITELISTED_PHONE) is False


def test_whitelist_parses_csv_with_spaces_and_55_prefix():
    from services import homologation as homo
    os.environ["CAUSALITY_PILOT_PHONES"] = \
        "5511955554444 , 11966667777,  5511933332222"
    importlib.reload(homo)
    wl = homo._parse_whitelist()
    assert "5511955554444" in wl
    assert "5511966667777" in wl  # prefixo 55 adicionado
    assert "5511933332222" in wl
    assert homo.is_whitelisted("11955554444") is True  # com/sem 55 ok
    os.environ["CAUSALITY_PILOT_PHONES"] = ""


def test_whitelisted_phone_sends_real_without_mask_or_prefix():
    """Quando whitelist contém o número, envio vai SEM máscara/prefixo,
    com environment=causality_pilot e evento CAUSALITY_PILOT_REAL_SEND."""
    async def t(db, homo):
        # HOMOLOG_MODE continua true (invariante)
        assert homo.is_homolog() is True
        assert homo.is_whitelisted(WHITELISTED_PHONE) is True

        out = await homo.safe_send_whatsapp(
            company_id=CO,
            target_phone=WHITELISTED_PHONE,
            message="Sua fatura vence hoje.",
            origin="v9_p3_unit",
            client_context={"name": "João", "phone": WHITELISTED_PHONE,
                            "document": "11122233344"})

        # NÃO bloqueado
        assert out["blocked"] is False
        # destino real preservado
        assert out["to_effective"] == WHITELISTED_PHONE
        # environment marcado como causality_pilot
        assert out["environment"] == "causality_pilot"

        # outbox: mensagem SEM prefixo de homologação
        ob = await db.wa_outbox.find_one({"id": out["id"]})
        assert ob is not None
        assert not ob["message"].startswith("[HOMOLOGAÇÃO SMARTPROV]")
        assert ob["message"] == "Sua fatura vence hoje."
        # contexto NÃO mascarado
        assert ob["masked_client"]["name"] == "João"
        assert ob["masked_client"]["phone"] == WHITELISTED_PHONE
        assert ob["environment"] == "causality_pilot"

        # evento de auditoria emitido
        ev = await db.motor_ia_events.find_one({
            "company_id": CO,
            "event_type": "CAUSALITY_PILOT_REAL_SEND"})
        assert ev is not None
        assert ev["environment"] == "causality_pilot"
        assert "***" in ev["payload"]["phone_redacted"]  # redacted

        # wa_messages_sent.kind correto
        sent = await db.wa_messages_sent.find_one({"id": out["id"]})
        assert sent is not None
        assert sent["kind"] == "causality_pilot_send"

        # NENHUM evento de bloqueio para este envio
        blocked_ev = await db.motor_ia_events.find_one({
            "company_id": CO,
            "event_type": "HOMOLOGATION_BLOCKED_REAL_PHONE"})
        assert blocked_ev is None
    _run(t, whitelist_env=WHITELISTED_PHONE)


def test_non_whitelisted_phone_still_blocked_when_whitelist_loaded():
    """Mesmo com whitelist carregada, números fora dela continuam
    redirecionados/mascarados (isolamento da liberação)."""
    async def t(db, homo):
        assert homo.is_homolog() is True
        # whitelist tem outro número, não este
        assert homo.is_whitelisted(NON_WHITELISTED_PHONE) is False

        out = await homo.safe_send_whatsapp(
            company_id=CO,
            target_phone=NON_WHITELISTED_PHONE,
            message="cobrança",
            origin="v9_p3_unit_negative",
            client_context={"name": "Maria",
                            "phone": NON_WHITELISTED_PHONE})

        assert out["blocked"] is True
        assert out["to_effective"] == homo.TEST_PHONE
        assert out["environment"] == "homolog"

        ev = await db.motor_ia_events.find_one({
            "company_id": CO,
            "event_type": "HOMOLOGATION_BLOCKED_REAL_PHONE"})
        assert ev is not None

        ob = await db.wa_outbox.find_one({"id": out["id"]})
        assert ob["message"].startswith("[HOMOLOGAÇÃO SMARTPROV]")
        assert ob["masked_client"]["name"] == "CLIENTE TESTE"

        # NÃO emite evento de pilot real para este número
        real_ev = await db.motor_ia_events.find_one({
            "company_id": CO,
            "event_type": "CAUSALITY_PILOT_REAL_SEND"})
        assert real_ev is None
    _run(t, whitelist_env=WHITELISTED_PHONE)


def test_homolog_mode_stays_true_with_whitelist():
    """Invariante: whitelist NUNCA desliga HOMOLOG_MODE."""
    async def t(db, homo):
        assert homo.is_homolog() is True
        # Mesmo após múltiplos envios whitelistados
        for _ in range(3):
            await homo.safe_send_whatsapp(
                company_id=CO,
                target_phone=WHITELISTED_PHONE,
                message="ping",
                origin="invariant_check")
        # HOMOLOG_MODE continua true
        assert os.environ["HOMOLOG_MODE"] == "true"
        assert homo.is_homolog() is True
    _run(t, whitelist_env=WHITELISTED_PHONE)


def test_test_phone_still_works_with_whitelist_loaded():
    """TEST_PHONE continua funcionando normalmente mesmo com whitelist."""
    async def t(db, homo):
        out = await homo.safe_send_whatsapp(
            company_id=CO,
            target_phone=homo.TEST_PHONE,
            message="ping técnico")
        assert out["blocked"] is False
        assert out["to_effective"] == homo.TEST_PHONE
        # TEST_PHONE NÃO é piloto real — mantém environment=homolog
        assert out["environment"] == "homolog"
        ob = await db.wa_outbox.find_one({"id": out["id"]})
        # Mensagem ao TEST_PHONE ainda recebe prefixo (caminho legado)
        assert ob["message"].startswith("[HOMOLOGAÇÃO SMARTPROV]")
    _run(t, whitelist_env=WHITELISTED_PHONE)
