"""test_v8_1.py — Simulador homologação operacional V8.1."""
from __future__ import annotations
import asyncio
import importlib
import os
import sys
import uuid
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CO = "test-v8-co"  # company isolada para testes
COLLS = ["tickets", "smart_installs", "smart_repairs",
         "smart_withdrawals", "collaborators", "wa_messages_sent",
         "motor_ia_events"]


def _run(coro):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import database as dm
        dm.db = db
        from services import v8_1_simulator
        importlib.reload(v8_1_simulator)
        for col in COLLS:
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro(db, v8_1_simulator)
        finally:
            for col in COLLS:
                await db[col].delete_many({"company_id": CO})
            c.close()
    return asyncio.new_event_loop().run_until_complete(_wrap())


def _id(p):
    return f"{p}-{uuid.uuid4().hex[:8]}"


def test_simulate_installation_creates_all_v8_fields():
    async def t(db, m):
        await db.collaborators.insert_one({
            "id": "col-test", "company_id": CO, "active": True, "cpf": f"sim-cpf-{uuid.uuid4().hex[:8]}"})
        out = await m.simulate_installation(
            company_id=CO, n=5, simulation_run_id="r1")
        assert out["created"] == 5
        # Idempotência
        out2 = await m.simulate_installation(
            company_id=CO, n=5, simulation_run_id="r1")
        assert out2["created"] == 0
        assert out2["updated_idempotent"] == 5
        # Schema COMPLETO
        s = await db.smart_installs.find_one({"company_id": CO})
        for f in ["service_mode", "environment", "technician_id",
                  "started_at", "finished_at", "customer_confirmed",
                  "execution_notes", "photos_count",
                  "signal_before", "signal_after", "onu_serial",
                  "cto", "vlan", "wifi_test_done",
                  "speed_test_done", "customer_trained"]:
            assert f in s, f"missing field: {f}"
        assert s["environment"] == "homolog"
        assert s["service_mode"] == "simulated"
        # Ticket associado
        tk = await db.tickets.find_one({"id": s["ticket_id"]})
        assert tk is not None
        assert tk["environment"] == "homolog"
        assert tk["service_mode"] == "simulated"
        assert tk["category"] == "INSTALL"
    _run(t)


def test_simulate_repair_creates_all_v8_fields():
    async def t(db, m):
        await db.collaborators.insert_one({
            "id": "col-test", "company_id": CO, "active": True, "cpf": f"sim-cpf-{uuid.uuid4().hex[:8]}"})
        out = await m.simulate_repair(
            company_id=CO, n=5, simulation_run_id="r2")
        assert out["created"] == 5
        s = await db.smart_repairs.find_one({"company_id": CO})
        for f in ["service_mode", "environment", "technician_id",
                  "started_at", "finished_at", "customer_confirmed",
                  "execution_notes", "photos_count",
                  "root_cause", "replaced_onu", "replaced_drop",
                  "changed_port", "changed_cto",
                  "truck_roll_avoidable", "resolved_remotely"]:
            assert f in s, f"missing field: {f}"
        assert s["environment"] == "homolog"
        # remote_resolved alias
        assert s["remote_resolved"] == s["resolved_remotely"]
        assert s["truck_roll_avoided"] == s["truck_roll_avoidable"]
    _run(t)


def test_simulate_withdrawal_creates_all_v8_fields():
    async def t(db, m):
        await db.collaborators.insert_one({
            "id": "col-test", "company_id": CO, "active": True, "cpf": f"sim-cpf-{uuid.uuid4().hex[:8]}"})
        out = await m.simulate_withdrawal(
            company_id=CO, n=5, simulation_run_id="r3")
        assert out["created"] == 5
        s = await db.smart_withdrawals.find_one({"company_id": CO})
        for f in ["service_mode", "environment", "technician_id",
                  "started_at", "finished_at", "customer_confirmed",
                  "execution_notes", "photos_count",
                  "equipment_recovered", "signed_receipt",
                  "asset_condition"]:
            assert f in s, f"missing field: {f}"
        assert s["environment"] == "homolog"
        # alias V6 espelhado
        assert s["asset_recovered"] == s["equipment_recovered"]
    _run(t)


def test_full_batch_250_scenarios():
    async def t(db, m):
        await db.collaborators.insert_one({
            "id": "col-test", "company_id": CO, "active": True, "cpf": f"sim-cpf-{uuid.uuid4().hex[:8]}"})
        out = await m.run_homolog_batch(
            company_id=CO, n_install=100, n_repair=100,
            n_withdraw=50, simulation_run_id="batch1",
            tag_legacy=False)
        assert out["totals"]["grand_total"] == 250
        assert out["totals"]["smart_installs"] == 100
        assert out["totals"]["smart_repairs"] == 100
        assert out["totals"]["smart_withdrawals"] == 50
        # 100% environment=homolog (anti-contaminação)
        for col in ("smart_installs", "smart_repairs",
                    "smart_withdrawals"):
            real = await db[col].count_documents({
                "company_id": CO,
                "environment": {"$ne": "homolog"}})
            assert real == 0, f"{col} tem doc fora de homolog!"
        # Idempotência total
        out2 = await m.run_homolog_batch(
            company_id=CO, n_install=100, n_repair=100,
            n_withdraw=50, simulation_run_id="batch1",
            tag_legacy=False)
        assert out2["totals"]["grand_total"] == 250
        # Nenhum NOVO criado
        assert (out2["installation"]["created"]
                + out2["repair"]["created"]
                + out2["withdrawal"]["created"]) == 0
    _run(t)


def test_success_rates_realistic():
    """Verifica que outcomes seguem distribuição realista (~70-80%)."""
    async def t(db, m):
        await db.collaborators.insert_one({
            "id": "col-test", "company_id": CO, "active": True, "cpf": f"sim-cpf-{uuid.uuid4().hex[:8]}"})
        # Massa grande p/ estatística
        await m.simulate_installation(
            company_id=CO, n=200, simulation_run_id="stat1")
        await m.simulate_repair(
            company_id=CO, n=200, simulation_run_id="stat2")
        await m.simulate_withdrawal(
            company_id=CO, n=200, simulation_run_id="stat3")
        ftc = await db.smart_installs.count_documents({
            "company_id": CO, "first_time_complete": True})
        remote = await db.smart_repairs.count_documents({
            "company_id": CO, "resolved_remotely": True})
        recovered = await db.smart_withdrawals.count_documents({
            "company_id": CO, "equipment_recovered": True})
        # ±10pp da meta (78%, 72%, 76%)
        assert 65 <= ftc / 2 <= 90, f"FTC fora da banda: {ftc/2}%"
        assert 60 <= remote / 2 <= 85, (
            f"remote fora: {remote/2}%")
        assert 65 <= recovered / 2 <= 90, (
            f"recovered fora: {recovered/2}%")
    _run(t)


def test_coverage_report_100pct_v8_fields():
    async def t(db, m):
        await db.collaborators.insert_one({
            "id": "col-test", "company_id": CO, "active": True, "cpf": f"sim-cpf-{uuid.uuid4().hex[:8]}"})
        # Hack: simulator usa HOMOLOG_COMPANY por default, mas
        # coverage_report aceita company_id parametrizado
        await m.run_homolog_batch(
            company_id=CO, n_install=10, n_repair=10,
            n_withdraw=10, simulation_run_id="cov1",
            tag_legacy=False)
        cov = await m.coverage_report(company_id=CO)
        # Todos campos V8 devem ter 100% cobertura nos simulados
        # (alguns são None quando lógica diz — não devem contar)
        # Verifica os obrigatórios sempre preenchidos:
        for f in ["service_mode", "environment", "technician_id",
                  "started_at", "execution_notes", "photos_count"]:
            for col in ("common_in_smart_installs",
                        "common_in_smart_repairs",
                        "common_in_smart_withdrawals"):
                assert cov["fields"][col][f]["pct"] == 100.0, (
                    f"{col}.{f} = {cov['fields'][col][f]['pct']}%")
        # Safety check
        assert cov["safety_check"][
            "smart_installs_outside_homolog"] == 0
        assert cov["safety_check"][
            "smart_repairs_outside_homolog"] == 0
        assert cov["safety_check"][
            "smart_withdrawals_outside_homolog"] == 0
    _run(t)


def test_tag_legacy_tickets_idempotent():
    async def t(db, m):
        # Cria tickets "legados" sem environment
        for i in range(5):
            await db.tickets.insert_one({
                "id": _id("legacy"), "company_id": "co-demo-test",
                "type": "reparo"})
        # Hack: a função tagueia "co-demo" por default; vamos
        # forçar legacy_company_id='co-demo-test'
        r1 = await m.tag_legacy_tickets("co-demo-test")
        assert r1["tagged"] == 5
        r2 = await m.tag_legacy_tickets("co-demo-test")
        assert r2["tagged"] == 0
        # Cleanup
        await db.tickets.delete_many(
            {"company_id": "co-demo-test"})
    _run(t)


def test_no_wa_message_to_real_phone():
    """O simulador NÃO chama WA. Verifica que nenhuma wa_message
    foi criada com phone diferente de TEST_PHONE."""
    async def t(db, m):
        await db.collaborators.insert_one({
            "id": "col-test", "company_id": CO, "active": True, "cpf": f"sim-cpf-{uuid.uuid4().hex[:8]}"})
        await m.run_homolog_batch(
            company_id=CO, n_install=20, n_repair=20,
            n_withdraw=10, simulation_run_id="nowa",
            tag_legacy=False)
        # Simulador NÃO deve criar wa_messages — é puramente
        # operacional. Se quiser comunicar, deve ir via
        # homologation.safe_send_whatsapp.
        n = await db.wa_messages_sent.count_documents({
            "company_id": CO})
        # 0 mensagens (simulador não envia). Se enviar no futuro,
        # garantir to_effective == TEST_PHONE.
        if n > 0:
            bad = await db.wa_messages_sent.count_documents({
                "company_id": CO,
                "to_effective": {"$ne": m.TEST_PHONE}})
            assert bad == 0
    _run(t)
