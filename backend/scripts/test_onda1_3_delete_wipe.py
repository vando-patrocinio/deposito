"""ONDA 1.3 — Smoke test E2E das 3 rotas refatoradas.

Cobre:
- delete_purchase: rejeita sem reason_code; happy path grava audit + after.
- batch_delete_purchases: rejeita sem reason; processa N ids.
- wipe_all_tickets: rejeita sem reason; deleta + compensa em inventory_movements.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import db  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from routes.purchases import (  # noqa: E402
    delete_purchase, batch_delete_purchases, BatchDeleteIn,
)
from routes.lousa import wipe_all_tickets  # noqa: E402
from services.destructive_audit import (  # noqa: E402
    PHYSICAL_COLLECTION as DA_COLLECTION,
)


TEST_CID = "co-onda1-3-test"
TEST_USER = {
    "id": "u-test-auditor", "email": "auditor@test", "name": "Auditor",
    "role": "auditor", "company_id": TEST_CID,
}


async def seed_purchase():
    await db.purchases.delete_many({"company_id": TEST_CID})
    await db.stok_onts.delete_many({"company_id": TEST_CID})
    await db.purchases_deletion_audit.delete_many({"company_id": TEST_CID})
    await db[DA_COLLECTION].delete_many({"company_id": TEST_CID})
    pid = "pur-test-onda13"
    await db.purchases.insert_one({
        "id": pid, "company_id": TEST_CID, "type": "ont",
        "status": "confirmed", "supplier_name": "Forn X",
        "invoice_number": "NF123", "items": [
            {"description": "HG6145D", "quantity": 2, "unit_price": 300.0,
             "macs": ["AA:11:22:33:44:01", "AA:11:22:33:44:02"]}
        ],
    })
    await db.stok_onts.insert_many([
        {"id": "ont-pur-1", "company_id": TEST_CID, "purchase_id": pid,
         "mac": "AA:11:22:33:44:01", "scan_sn": "SN-PUR-1",
         "model": "HG6145D",
         "location_type": "empresa", "status": "disponivel",
         "client_name": None, "location_id": None},
        {"id": "ont-pur-2", "company_id": TEST_CID, "purchase_id": pid,
         "mac": "AA:11:22:33:44:02", "scan_sn": "SN-PUR-2",
         "model": "HG6145D",
         "location_type": "empresa", "status": "disponivel",
         "client_name": None, "location_id": None},
    ])
    return pid


async def seed_tickets():
    await db.tickets.delete_many({"company_id": TEST_CID})
    await db.lousa_logs.delete_many({"company_id": TEST_CID})
    await db.inventory_os_movements_audit.delete_many({"company_id": TEST_CID})
    await db[DA_COLLECTION].delete_many({"company_id": TEST_CID})
    await db.tickets.delete_many({"id": {"$in": ["tk-test-1", "tk-test-2"]}})
    # Importante: o hook anti-órfãos rejeita tickets sem cliente. Adicionamos
    # client_snapshot para passar pela validação.
    cs = {"id": "cli-test-onda1", "name": "Cliente Teste Onda 1"}
    try:
        res = await db.tickets.insert_many([
            {"id": "tk-test-1", "company_id": TEST_CID, "status": "finalizada",
             "outcome": "sucesso", "type": "instalacao",
             "client_id": cs["id"], "client_snapshot": cs,
             "completion_data": {"ont": "AA:BB:CC:00:00:01", "ont_sn": "SN-T1"},
             "os_inventory_guardrail": {"movements": [{"audit_hash": "x"*64}]}},
            {"id": "tk-test-2", "company_id": TEST_CID, "status": "aberta",
             "client_id": cs["id"], "client_snapshot": cs, "type": "reparo"},
        ])
        print(f"  [seed_tickets] inserted_ids count: {len(res.inserted_ids)}")
    except Exception as e:
        print(f"  [seed_tickets] insert_many FAILED: {type(e).__name__}: {e}")


async def cleanup():
    for c in ["purchases", "stok_onts", "purchases_deletion_audit",
              "tickets", "lousa_logs", DA_COLLECTION,
              "inventory_os_movements_audit"]:
        await db[c].delete_many({"company_id": TEST_CID})


async def test_delete_purchase_requires_reason():
    pid = await seed_purchase()
    try:
        await delete_purchase(pid, reason_code=None, reason_details=None, user=TEST_USER)
    except HTTPException as e:
        assert e.status_code == 400
        print("✅ test_delete_purchase_requires_reason")
        return
    raise AssertionError("deveria rejeitar sem reason")


async def test_delete_purchase_happy_path():
    pid = await seed_purchase()
    resp = await delete_purchase(
        pid, reason_code="Devolução fornecedor", reason_details=None, user=TEST_USER)
    assert resp["ok"] is True
    assert resp["audit_id"].startswith("dest-")
    audit = await db[DA_COLLECTION].find_one({"id": resp["audit_id"]}, {"_id": 0})
    assert audit["action_type"] == "delete_purchase"
    assert audit["reason"]["code"] == "Devolução fornecedor"
    # Snapshot tem o purchase + 2 ONTs
    assert len(audit["before_snapshot"]["docs"]) == 3
    assert audit["after_snapshot"]["counts"]["purchase_exists"] is False
    print(f"✅ test_delete_purchase_happy_path (audit={resp['audit_id']})")


async def test_batch_delete_requires_reason():
    pid = await seed_purchase()
    payload = BatchDeleteIn(ids=[pid])  # sem reason
    try:
        await batch_delete_purchases(payload, user=TEST_USER)
    except HTTPException as e:
        assert e.status_code == 400
        print("✅ test_batch_delete_requires_reason")
        return
    raise AssertionError("deveria rejeitar batch sem reason")


async def test_batch_delete_happy_path():
    pid = await seed_purchase()
    payload = BatchDeleteIn(ids=[pid], reason={"code": "Correção de auditoria"})
    resp = await batch_delete_purchases(payload, user=TEST_USER)
    assert resp["processed"] == 1 and resp["succeeded"] == 1
    r = resp["results"][0]
    assert r["ok"] is True and r["audit_id"].startswith("dest-")
    audit = await db[DA_COLLECTION].find_one({"id": r["audit_id"]}, {"_id": 0})
    assert audit["action_type"] == "batch_delete_purchases"
    print(f"✅ test_batch_delete_happy_path (audit={r['audit_id']})")


async def test_wipe_tickets_requires_reason():
    await seed_tickets()
    try:
        await wipe_all_tickets(
            {"confirm": "APAGAR TUDO"}, user=TEST_USER)  # sem reason
    except HTTPException as e:
        assert e.status_code == 400
        print("✅ test_wipe_tickets_requires_reason")
        return
    raise AssertionError("deveria rejeitar wipe sem reason")


async def test_wipe_tickets_happy_path_with_compensation():
    await seed_tickets()
    # debug: garantir que o seed populou
    pre_count = await db.tickets.count_documents({"company_id": TEST_CID})
    print(f"  [debug] tickets after seed: {pre_count}")
    resp = await wipe_all_tickets(
        {"confirm": "APAGAR TUDO",
         "reason": {"code": "Determinação diretoria"}},
        user=TEST_USER)
    assert resp["ok"] is True
    assert resp["deleted_count"] == 2, f"esperava 2, got {resp['deleted_count']}"
    # Auditoria gravada
    audit = await db[DA_COLLECTION].find_one({"id": resp["audit_id"]}, {"_id": 0})
    assert audit["action_type"] == "wipe_tickets"
    assert len(audit["before_snapshot"]["docs"]) == 2
    # Compensação em inventory_movements para o ticket finalizado com guardrail
    comp = await db.inventory_os_movements_audit.find_one(
        {"ticket_id": "tk-test-1",
         "reason": "ticket_wipe_compensation"}, {"_id": 0})
    assert comp is not None, "trilha reversa não foi gravada"
    assert comp["destructive_audit_id"] == resp["audit_id"]
    print(f"✅ test_wipe_tickets_happy_path_with_compensation (audit={resp['audit_id']})")


async def main():
    await cleanup()
    await test_delete_purchase_requires_reason()
    await test_delete_purchase_happy_path()
    await test_batch_delete_requires_reason()
    await test_batch_delete_happy_path()
    await test_wipe_tickets_requires_reason()
    await test_wipe_tickets_happy_path_with_compensation()
    await cleanup()
    print("\n🟢 TODOS OS SMOKE TESTS DA ONDA 1.3 PASSARAM")


if __name__ == "__main__":
    asyncio.run(main())
