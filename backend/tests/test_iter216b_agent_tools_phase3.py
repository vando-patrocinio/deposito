"""
test_iter216b_agent_tools_phase3.py — Conselho IA Fase 3 tools

Cobre as 3 ferramentas novas:
  - escalate_dunning
  - assign_technician
  - pause_promo_inactive

Roda direto contra o Mongo do app (mesma DB que o backend usa), sem HTTP.
"""
import asyncio
import uuid
from datetime import datetime, timezone

import pytest

from services.agent_tools import (
    TOOL_CATALOG, TOOL_EXECUTORS, execute_tool_call,
)
from database import db


CID = "test-iter216b"


def _aio(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    """Limpa qualquer resíduo antes e depois dos testes."""
    async def _clean():
        await db.subscribers.delete_many({"company_id": CID})
        await db.tickets.delete_many({"company_id": CID})
        await db.collaborators.delete_many({"company_id": CID})
        await db.parcerias_promotions.delete_many({"company_id": CID})
        await db.conselho_ia_agent_actions.delete_many({"company_id": CID})
    _aio(_clean())
    yield
    _aio(_clean())


def test_catalog_has_new_tools():
    assert "escalate_dunning" in TOOL_CATALOG
    assert "assign_technician" in TOOL_CATALOG
    assert "pause_promo_inactive" in TOOL_CATALOG
    for t in ("escalate_dunning", "assign_technician", "pause_promo_inactive"):
        assert TOOL_CATALOG[t]["auto_apply"] is True
        assert TOOL_CATALOG[t]["description"]
        assert TOOL_CATALOG[t]["args_schema"]
        assert t in TOOL_EXECUTORS


def test_escalate_dunning_eleva_stage():
    """Cria 3 subscribers em dunning, escala 2 deles."""
    async def _run():
        ids = []
        for i in range(3):
            sid = f"sub-{uuid.uuid4().hex[:10]}"
            ids.append(sid)
            await db.subscribers.insert_one({
                "id": sid, "company_id": CID, "name": f"S{i}",
                "dunning_queue": True,
                "dunning_stage": 1,
                "status": "ATIVO",
            })
        # 3o subscriber NÃO está em queue → deve ficar fora
        sid3 = f"sub-{uuid.uuid4().hex[:10]}"
        await db.subscribers.insert_one({
            "id": sid3, "company_id": CID, "dunning_queue": False,
            "dunning_stage": 1, "status": "ATIVO", "name": "Fora",
        })
        return ids, sid3

    ids, sid3 = _aio(_run())
    # Escala stage 1→3 nos 2 primeiros + o 3o que está fora de queue
    out = _aio(execute_tool_call(CID, {
        "tool": "escalate_dunning",
        "args": {"subscriber_ids": ids[:2] + [sid3],
                  "to_stage": 3, "reason": "teste"},
        "justification": "Pytest",
    }))
    assert out["status"] == "executed", out
    res = out["result"]
    # 2 foram modificados (os em queue), o de fora não
    assert res["matched"] == 2
    assert res["modified"] == 2
    assert res["to_stage"] == 3

    # Verifica direto no DB
    async def _check():
        rows = []
        async for s in db.subscribers.find(
                {"id": {"$in": ids[:2]}}, {"_id": 0,
                 "dunning_stage": 1, "dunning_escalation_reason": 1}):
            rows.append(s)
        out_of_queue = await db.subscribers.find_one(
            {"id": sid3}, {"_id": 0, "dunning_stage": 1})
        return rows, out_of_queue
    rows, fora = _aio(_check())
    assert all(r["dunning_stage"] == 3 for r in rows)
    assert all(r["dunning_escalation_reason"] == "teste" for r in rows)
    assert fora["dunning_stage"] == 1  # não mexeu


def test_escalate_dunning_rejeita_stage_invalido():
    out = _aio(execute_tool_call(CID, {
        "tool": "escalate_dunning",
        "args": {"subscriber_ids": ["x"], "to_stage": 99, "reason": "x"},
        "justification": "stage fora do range",
    }))
    assert out["status"] == "failed"
    assert "to_stage" in (out.get("error") or "")


def test_assign_technician_atribui_e_recusa_invalidos():
    """Cria ticket aberto + técnico ativo + técnico inativo."""
    async def _seed():
        tid = f"tk-{uuid.uuid4().hex[:10]}"
        await db.tickets.insert_one({
            "id": tid, "company_id": CID, "status": "ABERTO",
            "type": "instalacao", "created_at": datetime.now(
                timezone.utc).isoformat(),
        })
        active_tech = f"col-{uuid.uuid4().hex[:10]}"
        await db.collaborators.insert_one({
            "id": active_tech, "company_id": CID,
            "cpf": f"cpf-{uuid.uuid4().hex[:11]}",
            "name": "Tec Ativo", "role": "tecnico", "active": True,
        })
        inactive_tech = f"col-{uuid.uuid4().hex[:10]}"
        await db.collaborators.insert_one({
            "id": inactive_tech, "company_id": CID,
            "cpf": f"cpf-{uuid.uuid4().hex[:11]}",
            "name": "Tec Off", "role": "tecnico", "active": False,
        })
        closed_tid = f"tk-{uuid.uuid4().hex[:10]}"
        await db.tickets.insert_one({
            "id": closed_tid, "company_id": CID, "status": "FECHADO",
            "type": "reparo",
        })
        return tid, active_tech, inactive_tech, closed_tid

    tid, tech_ok, tech_off, closed_tid = _aio(_seed())

    # Sucesso
    out = _aio(execute_tool_call(CID, {
        "tool": "assign_technician",
        "args": {"ticket_id": tid, "technician_id": tech_ok,
                  "reason": "Pytest"},
        "justification": "ok",
    }))
    assert out["status"] == "executed", out
    assert out["result"]["technician_id"] == tech_ok
    assert out["result"]["modified"] == 1

    async def _check_tk():
        t = await db.tickets.find_one({"id": tid}, {"_id": 0,
            "assigned_collaborator_id": 1, "assigned_by": 1})
        return t
    t = _aio(_check_tk())
    assert t["assigned_collaborator_id"] == tech_ok
    assert t["assigned_by"] == "agent_ia"

    # Falha: técnico inativo
    out = _aio(execute_tool_call(CID, {
        "tool": "assign_technician",
        "args": {"ticket_id": tid, "technician_id": tech_off,
                  "reason": "inativo"},
        "justification": "deve falhar",
    }))
    assert out["status"] == "failed"
    assert "inativo" in (out.get("error") or "").lower()

    # Falha: ticket fechado
    out = _aio(execute_tool_call(CID, {
        "tool": "assign_technician",
        "args": {"ticket_id": closed_tid, "technician_id": tech_ok,
                  "reason": "fechado"},
        "justification": "deve falhar",
    }))
    assert out["status"] == "failed"
    assert "fechado" in (out.get("error") or "").lower() or \
           "FECHADO" in (out.get("error") or "")

    # Falha: técnico inexistente
    out = _aio(execute_tool_call(CID, {
        "tool": "assign_technician",
        "args": {"ticket_id": tid, "technician_id": "fantasma",
                  "reason": "x"},
        "justification": "ghost",
    }))
    assert out["status"] == "failed"


def test_pause_promo_inactive_pausa_e_idempotente():
    async def _seed():
        pid = f"promo-{uuid.uuid4().hex[:10]}"
        await db.parcerias_promotions.insert_one({
            "id": pid, "company_id": CID, "title": "Combo Teste",
            "partner_name": "Parceiro Pytest",
            "active": True, "total_redemptions": 0,
        })
        return pid

    pid = _aio(_seed())
    out = _aio(execute_tool_call(CID, {
        "tool": "pause_promo_inactive",
        "args": {"promotion_id": pid, "reason": "zero resgates"},
        "justification": "pytest",
    }))
    assert out["status"] == "executed", out
    assert out["result"]["modified"] == 1

    async def _check():
        p = await db.parcerias_promotions.find_one({"id": pid},
            {"_id": 0, "active": 1, "paused_by": 1, "pause_reason": 1})
        return p
    p = _aio(_check())
    assert p["active"] is False
    assert p["paused_by"] == "agent_ia"
    assert p["pause_reason"] == "zero resgates"

    # Idempotência
    out2 = _aio(execute_tool_call(CID, {
        "tool": "pause_promo_inactive",
        "args": {"promotion_id": pid, "reason": "x"},
        "justification": "pytest 2",
    }))
    assert out2["status"] == "executed"
    assert out2["result"].get("already_paused") is True
    assert out2["result"]["modified"] == 0


def test_pause_promo_not_found():
    out = _aio(execute_tool_call(CID, {
        "tool": "pause_promo_inactive",
        "args": {"promotion_id": "promo-inexistente", "reason": "x"},
        "justification": "ghost",
    }))
    assert out["status"] == "failed"
    assert "não encontrada" in (out.get("error") or "")
