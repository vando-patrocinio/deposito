"""
test_observability.py — Tests Observability Twin (mocks controlados).

Cobre:
  - Zabbix problem open / resolved (via mock httpx)
  - Grafana alert firing / resolved
  - Correlação com cliente impactado
  - DecisionV5 gerada
  - Evento no motor_ia_events
  - Isolamento multi-tenant (CO1 vs CO2)
"""
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

CO1 = "test-obs-co1"
CO2 = "test-obs-co2"
COLLS = [
    "motor_ia_events", "motor_ia_decisions", "motor_ia_actions",
    "motor_ia_outcomes", "motor_ia_learnings",
    "motor_ia_autonomous_cycles", "motor_ia_analysis",
    "subscribers", "smartolt_onus", "tickets",
    "knowledge_graph_nodes", "knowledge_graph_edges",
    "observability_incidents",
    "grafana_dashboards", "grafana_folders",
    "grafana_datasources", "grafana_alerts",
]


def _run(coro):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        # P0.4 — força conector mock no teste (.env tem Grafana REAL agora)
        os.environ["GRAFANA_URL"] = ""
        os.environ["GRAFANA_SERVICE_ACCOUNT_TOKEN"] = ""
        os.environ["GRAFANA_USER"] = ""
        os.environ["GRAFANA_PASSWORD"] = ""
        os.environ["ZABBIX_URL"] = ""
        os.environ["ZABBIX_API_TOKEN"] = ""
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import database as dm
        dm.db = db
        from services import observability_twin as twin
        from services import autonomous_engine as eng
        importlib.reload(twin)
        importlib.reload(eng)
        for co in (CO1, CO2):
            for col in COLLS:
                await db[col].delete_many({"company_id": co})
        try:
            return await coro(db, twin, eng)
        finally:
            for co in (CO1, CO2):
                for col in COLLS:
                    await db[col].delete_many({"company_id": co})
            c.close()
    return asyncio.new_event_loop().run_until_complete(_wrap())


def _id(p):
    return f"{p}-{uuid.uuid4().hex[:10]}"


def test_classify_zbx_event_mapping():
    from services import observability_twin as twin
    assert twin._classify_zbx_event("CPU high") == "ZABBIX_CPU_HIGH"
    assert twin._classify_zbx_event("Memory low") == "ZABBIX_MEMORY_HIGH"
    assert twin._classify_zbx_event("Host ping down") == "ZABBIX_HOST_DOWN"
    assert twin._classify_zbx_event("Latency RTT 300") == \
        "ZABBIX_HIGH_LATENCY"
    assert twin._classify_zbx_event("Service down http") == \
        "ZABBIX_SERVICE_DOWN"
    assert twin._classify_zbx_event("Link FE down") == \
        "ZABBIX_LINK_DEGRADED"


def test_classify_health_levels():
    from services import observability_twin as twin
    assert twin._classify_health(100) == "EXCELENTE"
    assert twin._classify_health(94) == "SAUDAVEL"
    assert twin._classify_health(85) == "ATENCAO"
    assert twin._classify_health(72) == "CRITICO"
    assert twin._classify_health(50) == "INCIDENTE"


def test_ingest_zabbix_mock_creates_event():
    async def t(db, twin, eng):
        out = await twin.ingest_zabbix_problems(CO1)
        assert out["is_real_connector"] is False  # mock
        assert out["inserted_events"] >= 1
        ev = await db.motor_ia_events.find_one(
            {"company_id": CO1, "source": "zabbix"})
        assert ev is not None
        assert ev["event_type"] in (
            "ZABBIX_CPU_HIGH", "ZABBIX_PROBLEM_OPEN",
            "ZABBIX_PROBLEM_RESOLVED", "ZABBIX_HOST_DOWN")
        # Dedup: chamar de novo não duplica
        out2 = await twin.ingest_zabbix_problems(CO1)
        assert out2["skipped_dedup"] >= 1
    _run(t)


def test_grafana_snapshot_emits_firing_event():
    async def t(db, twin, eng):
        out = await twin.snapshot_grafana(CO1)
        assert out["is_real_connector"] is False
        assert out["dashboards"] >= 1
        assert out["firing_events_emitted"] >= 1
        ev = await db.motor_ia_events.find_one(
            {"company_id": CO1, "event_type": "GRAFANA_ALERT_FIRING"})
        assert ev is not None
    _run(t)


def test_correlate_with_impacted_subscribers():
    async def t(db, twin, eng):
        # Setup: 3 subscribers em CTO-IMPACTO + ONU em LOS
        for _ in range(3):
            await db.subscribers.insert_one({
                "id": _id("sub"), "company_id": CO1, "status": "active",
                "smartolt_onu_zone": "CTO-IMPACTO",
                "plan_price": 100})
        await db.smartolt_onus.insert_one({
            "company_id": CO1, "sn": _id("sn"), "status": "LOS",
            "zone_name": "CTO-IMPACTO",
            "olt_name": "OLT", "board": 1, "port": 1})
        # Injetar evento Zabbix de host_down crítico
        await twin.ingest_zabbix_problems(CO1)
        # Forçar evento crítico no DB para correlate
        await db.motor_ia_events.update_many(
            {"company_id": CO1, "source": "zabbix"},
            {"$set": {"severity": "4"}})
        incidents = await twin.correlate(CO1, window_hours=24)
        assert len(incidents) >= 1
        inc = incidents[0]
        assert inc["impacted_subscribers"] >= 3
        assert inc["revenue_at_risk_BRL"] >= 300
        assert inc["confidence"] >= 0.7
    _run(t)


def test_decision_v5_generated_from_observability_incident():
    async def t(db, twin, eng):
        # Setup mínimo para correlate gerar incidente crítico
        await db.subscribers.insert_one({
            "id": _id("sub"), "company_id": CO1, "status": "active",
            "smartolt_onu_zone": "CTO-X", "plan_price": 150})
        await db.smartolt_onus.insert_one({
            "company_id": CO1, "sn": _id("sn"), "status": "LOS",
            "zone_name": "CTO-X", "olt_name": "OLT",
            "board": 1, "port": 1})
        await twin.ingest_zabbix_problems(CO1)
        await db.motor_ia_events.update_many(
            {"company_id": CO1, "source": "zabbix"},
            {"$set": {"severity": "5"}})
        out = await twin.emit_decisions_from_correlations(
            CO1, window_hours=24)
        assert out["cycles_triggered"] >= 1
        cyc_id = out["cycle_ids"][0]
        cyc = await db.motor_ia_autonomous_cycles.find_one(
            {"cycle_id": cyc_id})
        assert cyc and cyc["status"] == "complete"
        dec = await db.motor_ia_decisions.find_one(
            {"decision_id": cyc["decision_id"]})
        assert dec is not None
        assert dec["cause"]
        assert dec["effect"]
        assert dec["impact"]
        assert dec["recommended_action"]
        assert isinstance(dec["evidence"], list)  # pode estar vazio em incident type
        assert dec["action_kind"] in (
            "open_noc_ticket", "open_technical_ticket",
            "create_incident", "notify_manager", "noop")
        # Ticket gerado (não bloqueado por WA)
        act = await db.motor_ia_actions.find_one(
            {"action_id": cyc["action_id"]})
        assert act and act["status"] in ("executed", "skipped", "noop")
    _run(t)


def test_multi_tenant_isolation():
    async def t(db, twin, eng):
        await twin.ingest_zabbix_problems(CO1)
        await twin.ingest_zabbix_problems(CO2)
        n1 = await db.motor_ia_events.count_documents(
            {"company_id": CO1, "source": "zabbix"})
        n2 = await db.motor_ia_events.count_documents(
            {"company_id": CO2, "source": "zabbix"})
        assert n1 >= 1 and n2 >= 1
        # Correlate de CO1 não pode incluir eventos de CO2
        inc1 = await twin.correlate(CO1, window_hours=24)
        for i in inc1:
            assert i["company_id"] == CO1
    _run(t)


def test_knowledge_graph_persisted():
    async def t(db, twin, eng):
        await db.subscribers.insert_one({
            "id": _id("sub"), "company_id": CO1, "status": "active",
            "smartolt_onu_zone": "CTO-K", "plan_price": 200})
        await db.smartolt_onus.insert_one({
            "company_id": CO1, "sn": _id("sn"), "status": "LOS",
            "zone_name": "CTO-K", "olt_name": "OLT",
            "board": 1, "port": 1})
        await twin.ingest_zabbix_problems(CO1)
        await db.motor_ia_events.update_many(
            {"company_id": CO1, "source": "zabbix"},
            {"$set": {"severity": "4"}})
        incidents = await twin.correlate(CO1, window_hours=24)
        out = await twin.persist_knowledge_graph(CO1, incidents)
        assert out["nodes_upserted"] >= 2
        assert out["edges_upserted"] >= 1
        # Verificar nós
        n = await db.knowledge_graph_nodes.find_one(
            {"company_id": CO1, "kind": "ZABBIX_HOST"})
        assert n is not None
    _run(t)


def test_observability_summary_returns_ten_cards():
    async def t(db, twin, eng):
        s = await twin.observability_summary(CO1, window_hours=24)
        assert "cards" in s and len(s["cards"]) == 10
        for c in s["cards"]:
            for must in ("problem", "cause", "impact", "action",
                         "confidence", "evidence"):
                assert must in c, f"card {c['title']} sem {must}"
            assert 0 <= c["confidence"] <= 1
    _run(t)
