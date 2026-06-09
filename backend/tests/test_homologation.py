"""test_homologation.py — MODO HOMOLOGAÇÃO CONTROLADA.

Garante:
  - phone real é BLOQUEADO + redirecionado
  - prefixo HOMOLOGAÇÃO obrigatório
  - dados do cliente mascarados
  - evento HOMOLOGATION_BLOCKED_REAL_PHONE emitido
  - pipeline completo grava environment=homolog
  - outcomes homolog NÃO contaminam produção
"""
from __future__ import annotations
import asyncio, importlib, os, sys, uuid
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CO = "test-homolog-co"
COLLS = ["motor_ia_events", "motor_ia_decisions",
         "motor_ia_actions", "motor_ia_outcomes",
         "motor_ia_learnings", "motor_ia_autonomous_cycles",
         "motor_ia_analysis", "wa_outbox", "wa_messages_sent",
         "tickets"]


def _run(coro):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        os.environ["HOMOLOG_MODE"] = "true"
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import database as dm
        dm.db = db
        from services import homologation as homo
        from services import autonomous_engine as eng
        importlib.reload(homo)
        importlib.reload(eng)
        for col in COLLS:
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro(db, homo, eng)
        finally:
            for col in COLLS:
                await db[col].delete_many({"company_id": CO})
            c.close()
    return asyncio.new_event_loop().run_until_complete(_wrap())


def test_is_homolog_default_true():
    from services import homologation as homo
    os.environ["HOMOLOG_MODE"] = "true"
    assert homo.is_homolog() is True


def test_is_homolog_off_when_false():
    from services import homologation as homo
    os.environ["HOMOLOG_MODE"] = "false"
    assert homo.is_homolog() is False
    os.environ["HOMOLOG_MODE"] = "true"  # restore


def test_mask_client_data_all_fields():
    from services import homologation as homo
    masked = homo.mask_client_data({
        "name": "João da Silva", "phone": "11999999999",
        "document": "12345678900", "untouched": "x"})
    assert masked["name"] == "CLIENTE TESTE"
    assert masked["phone"] == "OCULTO"
    assert masked["document"] == "OCULTO"
    assert masked["untouched"] == "x"


def test_prefix_is_idempotent():
    from services import homologation as homo
    p = homo.prefix_message("Sua conta vence")
    assert p.startswith("[HOMOLOGAÇÃO SMARTPROV]")
    assert homo.prefix_message(p) == p  # idempotente


def test_safe_send_blocks_real_phone_and_emits_event():
    async def t(db, homo, eng):
        out = await homo.safe_send_whatsapp(
            company_id=CO, target_phone="11912345678",
            message="Teste de cobrança",
            origin="unit_test",
            client_context={"name": "Real", "phone": "11912345678",
                            "document": "00011122233"})
        # Bloqueio efetivo
        assert out["blocked"] is True
        # Redireciona para TEST_PHONE
        assert out["to_effective"] == homo.TEST_PHONE
        # Evento gravado
        ev = await db.motor_ia_events.find_one({
            "company_id": CO,
            "event_type": "HOMOLOGATION_BLOCKED_REAL_PHONE"})
        assert ev is not None
        assert ev["environment"] == "homolog"
        # Outbox tem o registro com mascarado + prefixo
        ob = await db.wa_outbox.find_one({"id": out["id"]})
        assert ob is not None
        assert ob["message"].startswith("[HOMOLOGAÇÃO SMARTPROV]")
        assert ob["masked_client"]["name"] == "CLIENTE TESTE"
        assert ob["masked_client"]["phone"] == "OCULTO"
        assert ob["to_effective"] == homo.TEST_PHONE
    _run(t)


def test_safe_send_accepts_test_phone_without_blocking():
    async def t(db, homo, eng):
        out = await homo.safe_send_whatsapp(
            company_id=CO, target_phone=homo.TEST_PHONE,
            message="OK")
        assert out["blocked"] is False
        assert out["to_effective"] == homo.TEST_PHONE
        # NÃO emite evento de bloqueio
        ev = await db.motor_ia_events.find_one({
            "company_id": CO,
            "event_type": "HOMOLOGATION_BLOCKED_REAL_PHONE"})
        assert ev is None
    _run(t)


def test_simulate_full_pipeline_creates_complete_cycle():
    async def t(db, homo, eng):
        out = await homo.simulate_full_pipeline(CO,
                                                scenario="cobranca")
        # Pipeline completo
        for k in ("event_id", "cycle_id", "analysis_id",
                  "decision_id", "action_id", "outcome_id",
                  "learning_id"):
            assert out.get(k), f"campo {k} ausente"
        # WhatsApp passou pelo gateway (blocked porque phone real)
        assert out["wa_send"]["blocked"] is True
        assert out["wa_send"]["to_effective"] == homo.TEST_PHONE
        # Outcome marcado com environment=homolog
        oc = await db.motor_ia_outcomes.find_one(
            {"outcome_id": out["outcome_id"]})
        assert oc["environment"] == "homolog"
        assert oc["wa_message_id"] == out["wa_send"]["id"]
        # Action marcada também
        ac = await db.motor_ia_actions.find_one(
            {"action_id": out["action_id"]})
        assert ac["environment"] == "homolog"
    _run(t)


def test_status_returns_metrics():
    async def t(db, homo, eng):
        # Disparar 1 simulação + 1 send para TEST_PHONE
        await homo.simulate_full_pipeline(CO)
        await homo.safe_send_whatsapp(
            company_id=CO, target_phone=homo.TEST_PHONE,
            message="ping")
        s = await homo.homologation_status(CO)
        assert s["homolog_mode_active"] is True
        assert s["test_phone"] == "5521998176526"
        assert s["metrics"]["messages_sent"] >= 2
        assert s["metrics"]["messages_blocked"] >= 1
        assert s["metrics"]["blocked_events_emitted"] >= 1
        assert s["metrics"]["outcomes_with_environment_homolog"] >= 1
    _run(t)


def test_reconcile_marks_outcomes_reconciled():
    async def t(db, homo, eng):
        out = await homo.simulate_full_pipeline(CO)
        rec = await homo.reconcile_outbox(CO)
        assert rec["matched_outcomes"] >= 1
        oc = await db.motor_ia_outcomes.find_one(
            {"outcome_id": out["outcome_id"]})
        assert oc["status"] == "reconciled_homolog"
        assert oc.get("reconciled_at")
    _run(t)


def test_isolation_production_metrics_dont_include_homolog():
    async def t(db, homo, eng):
        await homo.simulate_full_pipeline(CO)
        # Adiciona outcome FAKE de produção
        await db.motor_ia_outcomes.insert_one({
            "id": f"out-{uuid.uuid4().hex[:8]}",
            "company_id": CO, "environment": "production",
            "observed_at": "2026-06-08T17:00:00+00:00",
            "actual_BRL": 100,
        })
        out = await homo.filter_production_outcomes(CO)
        assert out["production_outcomes"] >= 1
        assert out["homolog_outcomes"] >= 1
        assert out["isolation_correct"] is True
    _run(t)
