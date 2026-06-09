"""
test_alvaro_v5.py — Sprint 1 da Constituição V5.0 (Álvaro IA 2.0)

Cobre:
  - Fase J: DecisionV5 schema (validação estrita)
  - Fase A: consult_network + triage com bloqueio de reboot em LOS
  - Fase B: recurrence_score (cálculo, classificação, emissão de evento)

Segue o pattern `_run(...)` já adotado pelos demais testes async deste
projeto (cria Motor client próprio por teste para evitar "Event loop is
closed" entre testes do pytest-asyncio).
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CO = "test-alvaro-v5"
COLLS_TO_CLEAN = [
    "subscribers", "smartolt_onus", "tickets",
    "client_equipment_history", "motor_ia_events",
    "motor_ia_decisions", "motor_ia_recurrence_scores",
]


def _run(coro):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import database as dm
        dm.db = db
        from services import alvaro_v5 as mod
        importlib.reload(mod)
        for col in COLLS_TO_CLEAN:
            await db[col].delete_many({"company_id": CO})
        try:
            return await coro(db, mod)
        finally:
            for col in COLLS_TO_CLEAN:
                await db[col].delete_many({"company_id": CO})
            c.close()
    return asyncio.new_event_loop().run_until_complete(_wrap())


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


# ═══════════════════════ Fase J (sync) ═══════════════════════
def test_decision_v5_requires_all_fields():
    from services import alvaro_v5 as mod
    with pytest.raises(mod.DecisionV5Error):
        mod.build_v5_decision(
            cause="", effect="x", impact="y",
            recommended_action="z", confidence=0.5,
            evidence=[{"type": "t", "value": 1, "source": "s"}],
        )


def test_decision_v5_requires_evidence_nonempty():
    from services import alvaro_v5 as mod
    with pytest.raises(mod.DecisionV5Error):
        mod.build_v5_decision(
            cause="c", effect="e", impact="i",
            recommended_action="a", confidence=0.7, evidence=[],
        )


def test_decision_v5_validates_confidence_range():
    from services import alvaro_v5 as mod
    with pytest.raises(mod.DecisionV5Error):
        mod.build_v5_decision(
            cause="c", effect="e", impact="i",
            recommended_action="a", confidence=1.5,
            evidence=[{"type": "t", "value": 1, "source": "s"}],
        )


def test_decision_v5_builds_valid():
    from services import alvaro_v5 as mod
    d = mod.build_v5_decision(
        cause="ONU em LOS detectada",
        effect="Cliente sem serviço há 2h",
        impact="Risco de churn alto",
        recommended_action="Abrir OS técnica imediatamente",
        confidence=0.95,
        evidence=[{"type": "onu_status", "value": "LOS",
                   "source": "smartolt_onus"}],
        company_id="co-test",
        subscriber_id="sub-test",
        action_type="open_technical_ticket",
        domain="technical",
    )
    assert d["v5_compliant"] is True
    assert d["confidence"] == 0.95
    assert d["domain"] == "technical"
    assert d["id"].startswith("dec-")
    for f in ("cause", "effect", "impact",
              "recommended_action", "evidence"):
        assert d[f]


def test_classify_recurrence_boundaries():
    from services import alvaro_v5 as mod
    assert mod._classify_recurrence(0) == "BAIXO"
    assert mod._classify_recurrence(30) == "BAIXO"
    assert mod._classify_recurrence(31) == "MEDIO"
    assert mod._classify_recurrence(60) == "MEDIO"
    assert mod._classify_recurrence(61) == "ALTO"
    assert mod._classify_recurrence(80) == "ALTO"
    assert mod._classify_recurrence(81) == "CRITICO"
    assert mod._classify_recurrence(100) == "CRITICO"


# ═══════════════════════ Fase A (async) ═══════════════════════
def test_consult_network_subscriber_not_found():
    async def t(db, mod):
        out = await mod.consult_network("does-not-exist-zzz")
        assert out["found"] is False
        assert out["block_reboot"] is False
    _run(t)


def test_consult_network_with_los_blocks_reboot():
    async def t(db, mod):
        sid = _id("sub")
        onu_sn = _id("sn")
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO,
            "smartolt_onu_sn": onu_sn,
            "smartolt_onu_status": "LOS",
            "smartolt_onu_zone": "CTO-X",
        })
        await db.smartolt_onus.insert_one({
            "company_id": CO, "sn": onu_sn,
            "status": "LOS", "signal_1310": -32,
            "olt_name": "OLT-1", "board": 1, "port": 2,
            "zone_name": "CTO-X",
        })
        out = await mod.consult_network(sid, company_id=CO)
        assert out["found"] is True
        assert out["block_reboot"] is True
        assert "LOS" in out["onu"]["status"]
        assert out["network"]["cto"] == "CTO-X"
        types = [e["type"] for e in out["evidence"]]
        assert "onu_status" in types
    _run(t)


def test_triage_with_los_proibe_reboot_e_gera_decision_v5():
    async def t(db, mod):
        sid = _id("sub")
        onu_sn = _id("sn")
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO,
            "smartolt_onu_sn": onu_sn,
            "smartolt_onu_status": "LOS",
            "smartolt_onu_zone": "CTO-Y",
        })
        await db.smartolt_onus.insert_one({
            "company_id": CO, "sn": onu_sn,
            "status": "LOS", "signal_1310": -33,
            "olt_name": "OLT-2", "board": 1, "port": 1,
            "zone_name": "CTO-Y",
        })
        out = await mod.triage(
            sid, complaint="Internet caiu novamente.",
            company_id=CO)
        assert out["reboot_blocked"] is True
        d = out["decision"]
        assert d["v5_compliant"] is True
        assert d["action_type"] == "open_technical_ticket"
        ra = d["recommended_action"].lower()
        assert "desligue e ligue" not in ra
        assert "reinici" not in ra
        assert any(k in ra for k in ("os ", "técnic", "diagn"))
        assert d["action_payload"]["reason_no_reboot"]
        assert d["action_payload"]["priority"] == "high"
    _run(t)


def test_triage_with_online_onu_permite_diagnostico_remoto():
    async def t(db, mod):
        sid = _id("sub")
        onu_sn = _id("sn")
        await db.subscribers.insert_one({
            "id": sid, "company_id": CO,
            "smartolt_onu_sn": onu_sn,
            "smartolt_onu_status": "Online",
            "smartolt_onu_zone": "CTO-Z",
            "current_vlan": "100",
        })
        await db.smartolt_onus.insert_one({
            "company_id": CO, "sn": onu_sn,
            "status": "Online", "signal_1310": -22,
            "olt_name": "OLT-3", "board": 2, "port": 4,
            "zone_name": "CTO-Z",
        })
        out = await mod.triage(
            sid, complaint="Wi-Fi lento à noite.",
            company_id=CO)
        assert out["reboot_blocked"] is False
        d = out["decision"]
        assert d["v5_compliant"] is True
        assert d["action_type"] == "remote_diagnostic"
        assert d["confidence"] < 0.95
    _run(t)


# ═══════════════════════ Fase B (async) ═══════════════════════
def test_recurrence_score_baixo_com_zero_eventos():
    async def t(db, mod):
        sid = _id("sub")
        await db.subscribers.insert_one(
            {"id": sid, "company_id": CO, "status": "active"})
        r = await mod.compute_recurrence_score(
            sid, company_id=CO, persist=False)
        assert r["score"] == 0.0
        assert r["classification"] == "BAIXO"
        assert r["force_os"] is False
    _run(t)


def test_recurrence_score_critico_com_muitos_tickets_e_trocas():
    async def t(db, mod):
        sid = _id("sub")
        await db.subscribers.insert_one(
            {"id": sid, "company_id": CO, "status": "active"})

        base = datetime.now(timezone.utc)
        tickets = [{
            "id": _id("tk"),
            "company_id": CO, "client_id": sid,
            "opened_at": (base - timedelta(days=2 * i)).isoformat(),
            "status": "open",
            "subject": "queda recorrente conector drop",
        } for i in range(8)]
        await db.tickets.insert_many(tickets)

        eq = [{
            "id": _id("ceh"),
            "company_id": CO, "client_id": sid,
            "action": "install", "ont_sn": _id("sn"),
            "captured_at": (base - timedelta(days=10 * (i + 1))).isoformat(),
        } for i in range(3)]
        await db.client_equipment_history.insert_many(eq)

        r = await mod.compute_recurrence_score(
            sid, company_id=CO, persist=True)
        assert r["score"] >= 61, f"esperado >= 61, obtido {r['score']}"
        assert r["classification"] in ("ALTO", "CRITICO")
        if r["score"] > 70:
            assert r["force_os"] is True
            ev = await db.motor_ia_events.find_one(
                {"subscriber_id": sid, "event_type": "RECURRENCE_HIGH"})
            assert ev is not None
    _run(t)


def test_recurrence_batch_processes_company():
    async def t(db, mod):
        sids = [_id("sub") for _ in range(3)]
        for sid in sids:
            await db.subscribers.insert_one(
                {"id": sid, "company_id": CO, "status": "active"})
        out = await mod.recompute_recurrence_batch(CO, limit=10)
        assert out["processed"] == 3
        assert "generated_at" in out
    _run(t)
