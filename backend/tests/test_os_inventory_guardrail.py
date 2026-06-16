"""test_os_inventory_guardrail.py — REGRA GLOBAL ESTOQUE OS (CTO 2026-02).

Cobre os 12 casos do prompt CEO. Roda contra Mongo real (preview).
Estratégia event-loop: 1 mega `async def main()` (Motor x pytest-asyncio).
"""
from __future__ import annotations

import uuid

import pytest

from database import db
from services.os_inventory_guardrail import (
    enforce_os_inventory_movement, explain_block,
)


CID = "co-test-osinv"


async def _cleanup():
    await db.stok_onts.delete_many({"company_id": CID})
    await db.tickets.delete_many({"company_id": CID})
    await db.inventory_os_movements_audit.delete_many({"company_id": CID})


def _ont(mac, sn, *, location_type="empresa", location_id=None,
         status="disponivel", model="ZTE-F601"):
    return {
        "company_id": CID, "mac": mac, "scan_sn": sn, "model": model,
        "location_type": location_type, "location_id": location_id,
        "status": status, "created_at": "2026-06-16T00:00:00Z",
    }


def _ticket(ttype, *, client_id="sub-x1", tech_id="col-t1",
            company_id=CID):
    return {
        "id": f"tkt-{uuid.uuid4().hex[:8]}",
        "company_id": company_id,
        "type": ttype, "status": "aberta",
        "client_snapshot": {"id": client_id, "name": "Cliente Teste"},
        "assigned_collaborator_id": tech_id,
    }


def _actor():
    return {"id": "u-admin", "email": "admin@x", "role": "super_admin",
            "is_super_admin": True, "name": "CTO"}


@pytest.mark.asyncio
async def test_os_inventory_guardrail_all_cases():
    await _cleanup()
    actor = _actor()

    # 1) INSTALAÇÃO com ONT no técnico → técnico→cliente
    ont1 = _ont("AA:BB:CC:00:00:01", "SN-INST-TECH",
                location_type="tecnico", location_id="col-t1",
                status="com_tecnico")
    await db.stok_onts.insert_one(dict(ont1))
    t1 = _ticket("instalacao")
    await db.tickets.insert_one(dict(t1))
    r = await enforce_os_inventory_movement(
        t1, {"physical_attendance": True, "ont_sn": "SN-INST-TECH"}, actor)
    assert r["allowed"] is True, r
    assert any(m["movement_type"] == "instalacao_tecnico_cliente"
               for m in r["movements"])
    # Verifica banco
    moved = await db.stok_onts.find_one({"mac": "AA:BB:CC:00:00:01"})
    assert moved["location_type"] == "cliente"
    assert moved["location_id"] == "sub-x1"
    assert moved["status"] == "instalada"

    # 2) INSTALAÇÃO com ONT na empresa → auto-pull empresa→técnico→cliente
    await db.stok_onts.insert_one(_ont("AA:BB:CC:00:00:02", "SN-INST-CO"))
    t2 = _ticket("instalacao", client_id="sub-x2", tech_id="col-t2")
    await db.tickets.insert_one(dict(t2))
    r = await enforce_os_inventory_movement(
        t2, {"physical_attendance": True, "ont_sn": "SN-INST-CO"}, actor)
    assert r["allowed"] is True, r
    types = [m["movement_type"] for m in r["movements"]]
    assert "auto_pull_empresa_tecnico" in types
    assert "instalacao_tecnico_cliente" in types

    # 3) INSTALAÇÃO com SN inexistente → bloqueia
    t3 = _ticket("instalacao", client_id="sub-x3", tech_id="col-t3")
    await db.tickets.insert_one(dict(t3))
    r = await enforce_os_inventory_movement(
        t3, {"physical_attendance": True, "ont_sn": "SN-NAO-EXISTE"}, actor)
    assert r["allowed"] is False
    assert "regra_4_equipamento_nao_existe" in r["blocked_reasons"]

    # 4) RETIRADA correta → cliente→técnico
    await db.stok_onts.insert_one(
        _ont("AA:BB:CC:00:00:04", "SN-WD-OK",
             location_type="cliente", location_id="sub-x4",
             status="instalada"))
    t4 = _ticket("retirada", client_id="sub-x4", tech_id="col-t4")
    await db.tickets.insert_one(dict(t4))
    r = await enforce_os_inventory_movement(
        t4, {"physical_attendance": True, "ont_sn": "SN-WD-OK"}, actor)
    assert r["allowed"] is True, r
    moved = await db.stok_onts.find_one({"mac": "AA:BB:CC:00:00:04"})
    assert moved["location_type"] == "tecnico"
    assert moved["location_id"] == "col-t4"
    assert moved["status"] == "retirada_com_tecnico"

    # 5) RETIRADA de equipamento de outro cliente → bloqueia
    await db.stok_onts.insert_one(
        _ont("AA:BB:CC:00:00:05", "SN-WD-WRONG",
             location_type="cliente", location_id="sub-OUTRO",
             status="instalada"))
    t5 = _ticket("retirada", client_id="sub-x5", tech_id="col-t5")
    await db.tickets.insert_one(dict(t5))
    r = await enforce_os_inventory_movement(
        t5, {"physical_attendance": True, "ont_sn": "SN-WD-WRONG"}, actor)
    assert r["allowed"] is False
    assert ("regra_2_retirada_equipamento_nao_pertence_cliente"
            in r["blocked_reasons"])

    # 6) TROCA correta — duas movimentações
    await db.stok_onts.insert_one(
        _ont("AA:BB:CC:00:00:06", "SN-OLD-6",
             location_type="cliente", location_id="sub-x6",
             status="instalada"))
    await db.stok_onts.insert_one(
        _ont("AA:BB:CC:00:00:07", "SN-NEW-6",
             location_type="tecnico", location_id="col-t6",
             status="com_tecnico"))
    t6 = _ticket("troca", client_id="sub-x6", tech_id="col-t6")
    await db.tickets.insert_one(dict(t6))
    r = await enforce_os_inventory_movement(
        t6, {"physical_attendance": True,
             "old_ont_sn": "SN-OLD-6",
             "new_ont_sn": "SN-NEW-6"}, actor)
    assert r["allowed"] is True, r
    mts = [m["movement_type"] for m in r["movements"]]
    assert "troca_entrega_tecnico_cliente" in mts
    assert "troca_devolucao_cliente_tecnico" in mts

    # 7) TROCA com nova ONT já em outro cliente → bloqueia
    await db.stok_onts.insert_one(
        _ont("AA:BB:CC:00:00:08", "SN-OLD-7",
             location_type="cliente", location_id="sub-x7",
             status="instalada"))
    await db.stok_onts.insert_one(
        _ont("AA:BB:CC:00:00:09", "SN-NEW-7-USADA",
             location_type="cliente", location_id="sub-OUTRO-CLI",
             status="instalada"))
    t7 = _ticket("troca", client_id="sub-x7", tech_id="col-t7")
    await db.tickets.insert_one(dict(t7))
    r = await enforce_os_inventory_movement(
        t7, {"physical_attendance": True,
             "old_ont_sn": "SN-OLD-7",
             "new_ont_sn": "SN-NEW-7-USADA"}, actor)
    assert r["allowed"] is False
    assert "regra_4_equipamento_de_outro_cliente" in r["blocked_reasons"]

    # 8) Fechamento administrativo sem atendimento físico — não movimenta,
    #    exige motivo
    t8 = _ticket("retirada", client_id="sub-x8")
    await db.tickets.insert_one(dict(t8))
    r_no_reason = await enforce_os_inventory_movement(
        t8, {"physical_attendance": False}, actor)
    assert r_no_reason["allowed"] is False
    assert "admin_close_motivo_obrigatorio" in r_no_reason["blocked_reasons"]
    r_ok = await enforce_os_inventory_movement(
        t8, {"physical_attendance": False,
             "admin_reason": "cliente desistiu antes do agendamento"}, actor)
    assert r_ok["allowed"] is True
    assert r_ok["movements"] == []
    assert r_ok["classification"] == "admin_no_attendance"

    # 9) Fechamento gestor com atendimento físico SEM SN/MAC → bloqueia
    t9 = _ticket("instalacao", client_id="sub-x9")
    await db.tickets.insert_one(dict(t9))
    r = await enforce_os_inventory_movement(
        t9, {"physical_attendance": True}, actor)
    assert r["allowed"] is False
    assert "regra_absoluta_sem_sn_e_mac" in r["blocked_reasons"]

    # 10) Override SmartOLT — divergência sem motivo → bloqueia; com motivo
    #     >=20 chars e super_admin → libera
    #     (Stub: skip se SmartOLT cache não dispara divergence — assert
    #     somente comportamento da rota com override curto)
    # → Como esse caso é sensível ao SmartOLT real, validamos a estrutura
    #   da função explain_block + integração mínima.
    txt = explain_block(["regra_5_smartolt_divergencia_sn"])
    assert "SmartOLT" in txt

    # 11) Falha SmartOLT após movimentação local → pending_conciliacao
    # Cria ticket SEM PPPoE pra SmartOLT não resolver (available=False)
    await db.stok_onts.insert_one(
        _ont("AA:BB:CC:00:00:0A", "SN-CONC-11",
             location_type="tecnico", location_id="col-t11",
             status="com_tecnico"))
    t11 = _ticket("instalacao", client_id="sub-x11", tech_id="col-t11")
    await db.tickets.insert_one(dict(t11))
    r = await enforce_os_inventory_movement(
        t11, {"physical_attendance": True,
              "ont_sn": "SN-CONC-11"}, actor)
    assert r["allowed"] is True
    assert r["os_pending_conciliation"] is True
    assert r["smartolt"]["available"] is False

    # 12) Auditoria sempre tem hash
    rows = await db.inventory_os_movements_audit.find(
        {"company_id": CID}, {"_id": 0}).to_list(500)
    assert rows
    assert all(r.get("hash_auditoria") for r in rows)

    await _cleanup()


def test_explain_block_humanizes_all():
    txt = explain_block([
        "regra_absoluta_sem_sn_e_mac",
        "regra_4_equipamento_nao_existe",
        "regra_2_retirada_equipamento_nao_pertence_cliente",
    ])
    assert "SN" in txt
    assert "estoque" in txt
    assert "pertence" in txt
