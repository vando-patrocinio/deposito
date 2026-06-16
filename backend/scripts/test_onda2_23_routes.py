"""ONDA 2.2 + 2.3 — Smoke test E2E das 3 rotas refatoradas.

- POST /api/stok/onts/transfer-to-tech
- POST /api/stok/onts/transfer-to-tech/bulk
- POST /api/stok/onts/{mac}/return-to-company
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import db  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from routes.stok import (  # noqa: E402
    transfer_ont_to_tech, transfer_onts_bulk, return_ont_to_company,
    OntTransferIn, OntBulkTransferReasonIn,
)

TEST_CID = "co-onda2-23-test"
TEST_USER = {"id": "u-test", "email": "tester@ligo", "name": "Tester",
              "role": "gestor", "company_id": TEST_CID}
MAC1 = "AA:BB:CC:DD:02:01"
MAC2 = "AA:BB:CC:DD:02:02"
MAC3 = "AA:BB:CC:DD:02:03"
TECH_ID = "tech-onda2-test"


async def setup():
    await db.collaborators.delete_many({"company_id": TEST_CID})
    await db.collaborators.delete_many({"id": TECH_ID})
    await db.collaborators.insert_one({
        "id": TECH_ID, "company_id": TEST_CID,
        "name": "Tech Onda2", "email": "tech@test", "role": "tecnico",
        "cpf": f"00099988877-test-{TEST_CID}",
    })
    await db.stok_onts.delete_many({"company_id": TEST_CID})
    await db.inventory_os_movements_audit.delete_many({"company_id": TEST_CID})
    await db.stok_onts.insert_many([
        {"id": f"ont-{mac.replace(':', '')}", "company_id": TEST_CID,
         "mac": mac, "scan_sn": f"SN-{mac[-5:]}", "model": "HG6145D",
         "status": "disponivel", "location_type": "empresa",
         "location_id": None, "client_name": None}
        for mac in (MAC1, MAC2, MAC3)
    ])


async def cleanup():
    for c in ["collaborators", "stok_onts",
              "inventory_os_movements_audit", "stok_history"]:
        await db[c].delete_many({"company_id": TEST_CID})


async def test_transfer_to_tech_requires_reason():
    await setup()
    payload = OntTransferIn(mac=MAC1, technician_id=TECH_ID)  # sem reason
    try:
        await transfer_ont_to_tech(payload, user=TEST_USER)
    except HTTPException as e:
        assert e.status_code == 400
        print("✅ test_transfer_to_tech_requires_reason")
        return
    raise AssertionError("deveria rejeitar sem reason")


async def test_transfer_to_tech_happy():
    await setup()
    payload = OntTransferIn(mac=MAC1, technician_id=TECH_ID,
                              reason={"code": "Saída pra campo"})
    resp = await transfer_ont_to_tech(payload, user=TEST_USER)
    assert resp["ok"] is True
    assert resp["movement_id"].startswith("mov-")
    assert len(resp["audit_hash"]) == 64
    o = await db.stok_onts.find_one({"company_id": TEST_CID, "mac": MAC1})
    assert o["location_type"] == "tecnico"
    assert o["location_id"] == TECH_ID
    assert o["last_transfer_id"] == resp["movement_id"]
    inv = await db.inventory_os_movements_audit.count_documents(
        {"company_id": TEST_CID, "mac": MAC1})
    assert inv == 1
    print(f"✅ test_transfer_to_tech_happy (mov={resp['movement_id']})")


async def test_bulk_requires_reason():
    await setup()
    payload = OntBulkTransferReasonIn(
        macs=[MAC2, MAC3], technician_id=TECH_ID)  # sem reason
    try:
        await transfer_onts_bulk(payload, user=TEST_USER)
    except HTTPException as e:
        assert e.status_code == 400
        print("✅ test_bulk_requires_reason")
        return
    raise AssertionError("bulk sem reason deveria falhar")


async def test_bulk_happy():
    await setup()
    payload = OntBulkTransferReasonIn(
        macs=[MAC2, MAC3], technician_id=TECH_ID,
        reason={"code": "Saída pra campo"})
    resp = await transfer_onts_bulk(payload, user=TEST_USER)
    assert resp["transferred_count"] == 2
    assert len(resp["skipped"]) == 0
    inv = await db.inventory_os_movements_audit.count_documents(
        {"company_id": TEST_CID})
    assert inv == 2
    print(f"✅ test_bulk_happy (2 ONTs transferidas)")


async def test_return_to_company_requires_reason():
    await setup()
    # Coloca em técnico primeiro
    await db.stok_onts.update_one(
        {"company_id": TEST_CID, "mac": MAC1},
        {"$set": {"location_type": "tecnico", "location_id": TECH_ID,
                  "status": "com_tecnico"}})
    try:
        await return_ont_to_company(MAC1, payload=None, user=TEST_USER)
    except HTTPException as e:
        assert e.status_code == 400
        print("✅ test_return_to_company_requires_reason")
        return
    raise AssertionError("return sem reason deveria falhar")


async def test_return_to_company_happy():
    await setup()
    await db.stok_onts.update_one(
        {"company_id": TEST_CID, "mac": MAC1},
        {"$set": {"location_type": "tecnico", "location_id": TECH_ID}})
    resp = await return_ont_to_company(
        MAC1, payload={"reason": {"code": "Devolução estoque"}},
        user=TEST_USER)
    assert resp["ok"] is True
    o = await db.stok_onts.find_one({"company_id": TEST_CID, "mac": MAC1})
    assert o["location_type"] == "empresa"
    print(f"✅ test_return_to_company_happy (mov={resp['movement_id']})")


async def test_cliente_to_empresa_blocked():
    """Garante que cliente→empresa direto é BLOQUEADO pelo grafo."""
    await setup()
    # Força ONT em cliente
    await db.stok_onts.update_one(
        {"company_id": TEST_CID, "mac": MAC1},
        {"$set": {"location_type": "cliente", "location_id": "cli-x",
                  "client_name": "Cliente X", "status": "instalada"}})
    # Tenta retornar diretamente — deve falhar pelo grafo do execute_transfer
    # via _resolve_movement_type. Não há rota direta cliente→empresa.
    # Aqui testamos diretamente o engine.
    from services.transfer_engine import execute_transfer, TransferEngineError
    try:
        await execute_transfer(
            company_id=TEST_CID, origin_type="cliente",
            origin_id="cli-x", destination_type="empresa",
            destination_id=None,
            actor={"id": "u-1", "email": "test@ligo"},
            reason={"code": "Devolução estoque"}, mac=MAC1)
    except TransferEngineError as e:
        assert "não permitida" in str(e)
        print("✅ test_cliente_to_empresa_blocked")
        return
    raise AssertionError("cliente→empresa deveria ter sido bloqueado")


async def main():
    await cleanup()
    await test_transfer_to_tech_requires_reason()
    await test_transfer_to_tech_happy()
    await test_bulk_requires_reason()
    await test_bulk_happy()
    await test_return_to_company_requires_reason()
    await test_return_to_company_happy()
    await test_cliente_to_empresa_blocked()
    await cleanup()
    print("\n🟢 TODOS OS SMOKE TESTS DA ONDA 2.2+2.3 PASSARAM")


if __name__ == "__main__":
    asyncio.run(main())
