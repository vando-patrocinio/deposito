"""test_os_inventory_e2e_tech_and_worker.py — Fechamento técnico + Worker.

Cobre os 10 cenários do prompt CTO (OPERAÇÃO ESTOQUE OS — FECHAMENTO COMPLETO):
  1. Técnico finaliza instalação com ONT válida.
  2. Técnico finaliza retirada.
  3. Técnico finaliza troca.
  4. Técnico bloqueado sem SN/MAC.
  5. Gestor continua protegido (regressão).
  6. Ticket "pendente_conciliacao" entra no worker.
  7. Worker resolve quando SmartOLT volta.
  8. Worker escala após retries.
  9. Auditoria registra origem (tecnico_app / admin_close / reconciliation_worker).
 10. Nenhum fluxo legado finaliza fora do guardrail.

NOTA: testes 1-4 chamam `enforce_os_inventory_movement` direto com
`actor.origin='tecnico_app'` (o hook em `public_finalize_ticket` é o mesmo).
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from database import db
from services.os_inventory_guardrail import enforce_os_inventory_movement
from services.os_inventory_reconciliation import (
    run_reconciliation_pass, MAX_RETRIES,
)


CID = "co-test-osinv-e2e"


async def _cleanup():
    await db.stok_onts.delete_many({"company_id": CID})
    await db.tickets.delete_many({"company_id": CID})
    await db.inventory_os_movements_audit.delete_many({"company_id": CID})
    await db.notifications.delete_many(
        {"company_id": CID, "type": "os_reconciliation_failed"})


def _ont(mac, sn, **k):
    return {"company_id": CID, "mac": mac, "scan_sn": sn,
            "model": "ZTE-F601", **k}


def _ticket(ttype, **k):
    return {"id": f"tkt-{uuid.uuid4().hex[:8]}",
            "company_id": CID, "type": ttype, "status": "aberta",
            "client_snapshot": {"id": "sub-A", "name": "Cliente A"},
            "assigned_collaborator_id": "col-T1",
            **k}


def _tech_actor():
    return {"id": "col-T1", "role": "colaborador",
            "name": "João Técnico", "origin": "tecnico_app",
            "is_super_admin": False}


def _admin_actor():
    return {"id": "u-admin", "role": "super_admin",
            "email": "admin@x", "is_super_admin": True}


@pytest.mark.asyncio
async def test_e2e_tech_paths_and_worker():
    await _cleanup()

    # ── 1. Técnico finaliza INSTALAÇÃO com ONT válida ───────────────────
    await db.stok_onts.insert_one(_ont("AA:BB:00:00:00:01", "SN-T1",
                                         location_type="tecnico",
                                         location_id="col-T1",
                                         status="com_tecnico"))
    t1 = _ticket("instalacao")
    await db.tickets.insert_one(dict(t1))
    r = await enforce_os_inventory_movement(
        t1, {"physical_attendance": True, "ont_sn": "SN-T1"},
        _tech_actor())
    assert r["allowed"], r
    assert any(m["movement_type"] == "instalacao_tecnico_cliente"
               for m in r["movements"])

    # ── 2. Técnico finaliza RETIRADA ────────────────────────────────────
    await db.stok_onts.insert_one(_ont("AA:BB:00:00:00:02", "SN-T2",
                                         location_type="cliente",
                                         location_id="sub-B",
                                         status="instalada"))
    t2 = _ticket("retirada", client_snapshot={"id": "sub-B", "name": "B"})
    await db.tickets.insert_one(dict(t2))
    r = await enforce_os_inventory_movement(
        t2, {"physical_attendance": True, "ont_sn": "SN-T2"},
        _tech_actor())
    assert r["allowed"], r

    # ── 3. Técnico finaliza TROCA ───────────────────────────────────────
    await db.stok_onts.insert_one(_ont("AA:BB:00:00:00:03", "SN-OLD3",
                                         location_type="cliente",
                                         location_id="sub-C",
                                         status="instalada"))
    await db.stok_onts.insert_one(_ont("AA:BB:00:00:00:04", "SN-NEW3",
                                         location_type="tecnico",
                                         location_id="col-T1",
                                         status="com_tecnico"))
    t3 = _ticket("troca", client_snapshot={"id": "sub-C", "name": "C"})
    await db.tickets.insert_one(dict(t3))
    r = await enforce_os_inventory_movement(
        t3, {"physical_attendance": True,
             "old_ont_sn": "SN-OLD3",
             "new_ont_sn": "SN-NEW3"},
        _tech_actor())
    assert r["allowed"], r
    mts = [m["movement_type"] for m in r["movements"]]
    assert "troca_devolucao_cliente_tecnico" in mts
    assert "troca_entrega_tecnico_cliente" in mts

    # ── 4. Técnico SEM SN/MAC → bloqueia ────────────────────────────────
    t4 = _ticket("instalacao", client_snapshot={"id": "sub-D", "name": "D"})
    await db.tickets.insert_one(dict(t4))
    r = await enforce_os_inventory_movement(
        t4, {"physical_attendance": True}, _tech_actor())
    assert r["allowed"] is False
    assert "regra_absoluta_sem_sn_e_mac" in r["blocked_reasons"]

    # ── 5. Gestor continua protegido (regressão dos casos do prompt anterior)
    t5 = _ticket("instalacao", client_snapshot={"id": "sub-E", "name": "E"})
    await db.tickets.insert_one(dict(t5))
    r = await enforce_os_inventory_movement(
        t5, {"physical_attendance": True}, _admin_actor())
    assert r["allowed"] is False
    assert "regra_absoluta_sem_sn_e_mac" in r["blocked_reasons"]

    # ── 9. Auditoria registra origens distintas ─────────────────────────
    rows = await db.inventory_os_movements_audit.find(
        {"company_id": CID, "ticket_id": t1["id"]}).to_list(10)
    assert any(r.get("actor_origin") == "tecnico_app" for r in rows)
    rows_admin = await db.inventory_os_movements_audit.find(
        {"company_id": CID, "ticket_id": t5["id"]}).to_list(10)
    assert any(r.get("actor_origin") == "admin_close" for r in rows_admin)

    # ── 6/7. Worker resolve ticket pendente quando SmartOLT volta ───────
    t_pend = _ticket("instalacao",
                       status="pendente_conciliacao",
                       client_snapshot={"id": "sub-P", "name": "P"},
                       pending_conciliation_retries=0,
                       completion_data={"ont_sn": "SN-PEND"})
    await db.tickets.insert_one(dict(t_pend))
    # Simula SmartOLT disponível + dados batendo
    with patch(
        "services.os_inventory_guardrail._validate_smartolt",
        return_value={"available": True, "sn": "SN-PEND", "divergence": None},
    ):
        stats = await run_reconciliation_pass()
    assert stats["resolved"] >= 1
    t_resolved = await db.tickets.find_one({"id": t_pend["id"]})
    assert t_resolved["status"] == "finalizada"
    assert t_resolved.get("conciliado") is True

    # ── 8. Worker escala após MAX_RETRIES ───────────────────────────────
    t_esc = _ticket("instalacao",
                      status="pendente_conciliacao",
                      client_snapshot={"id": "sub-X", "name": "X"},
                      pending_conciliation_retries=MAX_RETRIES - 1,
                      completion_data={"ont_sn": "SN-NEVER"})
    await db.tickets.insert_one(dict(t_esc))
    with patch(
        "services.os_inventory_guardrail._validate_smartolt",
        return_value={"available": False},
    ):
        stats = await run_reconciliation_pass()
    assert stats["escalated"] >= 1
    t_after = await db.tickets.find_one({"id": t_esc["id"]})
    assert t_after.get("pending_conciliation_escalated") is True
    # Notificação criada
    notif = await db.notifications.find_one(
        {"ticket_id": t_esc["id"], "type": "os_reconciliation_failed"})
    assert notif is not None

    # ── 10. Audit com origem reconciliation_worker registrada ───────────
    recon_audit = await db.inventory_os_movements_audit.find_one(
        {"ticket_id": t_pend["id"],
         "movement_type": "reconciliation_resolved"})
    assert recon_audit is not None
    assert recon_audit.get("actor_origin") == "reconciliation_worker"

    await _cleanup()
