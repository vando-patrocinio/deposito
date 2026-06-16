"""ONDA 2.5 + 2.7 — Smoke test das 3 rotas refatoradas."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import db  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from routes.stok_transfers import (  # noqa: E402
    approve_pending, reject_pending, confirm_defective_return,
    TransferDecisionIn, DefectiveReturnIn,
)

TEST_CID = "co-onda2-57-test"
TEST_USER = {"id": "u-test", "email": "tester@ligo", "name": "Tester",
              "role": "gestor", "company_id": TEST_CID}
MAC1 = "AA:BB:CC:DD:57:01"
MAC2 = "AA:BB:CC:DD:57:02"


async def setup_approve():
    await db.stok_onts.delete_many({"company_id": TEST_CID})
    await db.stok_pending_transfers.delete_many({"company_id": TEST_CID})
    await db.inventory_os_movements_audit.delete_many({"company_id": TEST_CID})
    pt_id = "pt-test-57"
    await db.stok_onts.insert_one({
        "id": "ont-a57-1", "company_id": TEST_CID, "mac": MAC1,
        "scan_sn": "SN-A571", "model": "HG6145D",
        "status": "pendente_aprovacao", "location_type": "tecnico",
        "location_id": "tech-A", "pending_transfer_id": pt_id,
    })
    await db.stok_pending_transfers.insert_one({
        "id": pt_id, "company_id": TEST_CID, "status": "pending",
        "stock_mac": MAC1, "technician_id": "tech-A",
        "client_id": "cli-A", "client_name": "Cliente A",
    })
    return pt_id


async def setup_defective():
    await db.stok_onts.delete_many({"company_id": TEST_CID, "mac": MAC2})
    await db.stok_onts.insert_one({
        "id": "ont-a57-2", "company_id": TEST_CID, "mac": MAC2,
        "scan_sn": "SN-A572", "model": "HG6145D",
        "status": "defeito_devolver_empresa",
        "location_type": "tecnico", "location_id": "tech-B",
    })


async def cleanup():
    for c in ["stok_onts", "stok_pending_transfers",
              "inventory_os_movements_audit"]:
        await db[c].delete_many({"company_id": TEST_CID})


async def test_approve_requires_reason():
    pt_id = await setup_approve()
    try:
        await approve_pending(pt_id, TransferDecisionIn(), user=TEST_USER)
    except HTTPException as e:
        assert e.status_code == 400
        print("✅ test_approve_requires_reason")
        return
    raise AssertionError("approve sem reason deveria falhar")


async def test_approve_happy():
    pt_id = await setup_approve()
    payload = TransferDecisionIn(reason={"code": "Instalação OS"})
    resp = await approve_pending(pt_id, payload, user=TEST_USER)
    assert resp["status"] == "approved"
    assert resp["movement_id"].startswith("mov-")
    o = await db.stok_onts.find_one({"company_id": TEST_CID, "mac": MAC1})
    assert o["location_type"] == "cliente"
    assert o["location_id"] == "cli-A"
    inv = await db.inventory_os_movements_audit.count_documents(
        {"company_id": TEST_CID, "mac": MAC1})
    assert inv == 1
    print(f"✅ test_approve_happy (mov={resp['movement_id']})")


async def test_reject_requires_reason():
    pt_id = await setup_approve()
    try:
        await reject_pending(pt_id, TransferDecisionIn(), user=TEST_USER)
    except HTTPException as e:
        assert e.status_code == 400
        print("✅ test_reject_requires_reason")
        return
    raise AssertionError("reject sem reason deveria falhar")


async def test_reject_happy():
    pt_id = await setup_approve()
    payload = TransferDecisionIn(reason={"code": "Erro operacional"})
    resp = await reject_pending(pt_id, payload, user=TEST_USER)
    assert resp["status"] == "rejected"
    # Não cria movimento (sem owner change)
    inv = await db.inventory_os_movements_audit.count_documents(
        {"company_id": TEST_CID, "mac": MAC1})
    assert inv == 0
    print("✅ test_reject_happy")


async def test_confirm_defective_requires_reason():
    await setup_defective()
    try:
        await confirm_defective_return(
            MAC2, DefectiveReturnIn(), user=TEST_USER)
    except HTTPException as e:
        assert e.status_code == 400
        print("✅ test_confirm_defective_requires_reason")
        return
    raise AssertionError("confirm-return sem reason deveria falhar")


async def test_confirm_defective_happy():
    await setup_defective()
    payload = DefectiveReturnIn(
        notes="Laudo 4521",
        reason={"code": "Confirmação defeito"},
    )
    resp = await confirm_defective_return(MAC2, payload, user=TEST_USER)
    assert resp["ok"] is True
    assert resp["new_status"] == "defeito_em_analise"
    assert resp["movement_id"].startswith("mov-")
    o = await db.stok_onts.find_one({"company_id": TEST_CID, "mac": MAC2})
    assert o["location_type"] == "empresa"
    assert o["status"] == "defeito_em_analise"
    print(f"✅ test_confirm_defective_happy (mov={resp['movement_id']})")


async def main():
    await cleanup()
    await test_approve_requires_reason()
    await test_approve_happy()
    await test_reject_requires_reason()
    await test_reject_happy()
    await test_confirm_defective_requires_reason()
    await test_confirm_defective_happy()
    await cleanup()
    print("\n🟢 TODOS OS SMOKE TESTS DA ONDA 2.5+2.7 PASSARAM")


if __name__ == "__main__":
    asyncio.run(main())
