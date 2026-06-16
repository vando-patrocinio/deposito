"""ONDA 1.4 — Smoke test E2E das 2 rotas refatoradas (scrap + revert)."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import db  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from routes.stok_transfers import (  # noqa: E402
    scrap_defective_ont, revert_defective_ont, DefectiveOntReasonIn,
)
from services.destructive_audit import (  # noqa: E402
    PHYSICAL_COLLECTION as DA_COLLECTION,
)

TEST_CID = "co-onda1-4-test"
TEST_USER = {
    "id": "u-test-gestor", "email": "gestor@test", "name": "Gestor",
    "role": "gestor", "company_id": TEST_CID,
}
MAC1 = "AA:BB:CC:DD:01:01"
MAC2 = "AA:BB:CC:DD:01:02"


async def seed_ont(mac, status):
    await db.stok_onts.delete_many({"company_id": TEST_CID, "mac": mac})
    await db[DA_COLLECTION].delete_many({"company_id": TEST_CID})
    await db.stok_onts.insert_one({
        "id": f"ont-{mac.replace(':', '')}",
        "company_id": TEST_CID, "mac": mac,
        "scan_sn": f"SN-{mac[-5:]}",
        "model": "TESTONT",
        "status": status,
        "location_type": "empresa", "location_id": None,
        "client_name": None,
    })


async def cleanup():
    for c in ["stok_onts", DA_COLLECTION]:
        await db[c].delete_many({"company_id": TEST_CID})


async def test_scrap_requires_reason():
    await seed_ont(MAC1, "defeito_devolver_empresa")
    try:
        await scrap_defective_ont(MAC1, payload=None, user=TEST_USER)
    except HTTPException as e:
        assert e.status_code == 400
        print("✅ test_scrap_requires_reason")
        return
    raise AssertionError("deveria rejeitar scrap sem reason")


async def test_scrap_happy_path():
    await seed_ont(MAC1, "defeito_em_analise")
    payload = DefectiveOntReasonIn(code="Equipamento condenado")
    resp = await scrap_defective_ont(MAC1, payload=payload, user=TEST_USER)
    assert resp["ok"] is True
    assert resp["new_status"] == "sucateada"
    assert resp["audit_id"].startswith("dest-")
    # ONT atualizada
    ont = await db.stok_onts.find_one({"mac": MAC1.upper()}, {"_id": 0})
    assert ont["status"] == "sucateada"
    assert ont["destructive_audit_id"] == resp["audit_id"]
    # Auditoria com snapshot
    audit = await db[DA_COLLECTION].find_one({"id": resp["audit_id"]}, {"_id": 0})
    assert audit["action_type"] == "scrap_ont"
    assert len(audit["before_snapshot"]["docs"]) == 1
    assert audit["before_snapshot"]["previous_status"] == "defeito_em_analise"
    assert audit["after_snapshot"]["new_status"] == "sucateada"
    print(f"✅ test_scrap_happy_path (audit={resp['audit_id']})")


async def test_revert_requires_reason():
    await seed_ont(MAC2, "defeito_em_analise")
    try:
        await revert_defective_ont(MAC2, payload=None, user=TEST_USER)
    except HTTPException as e:
        assert e.status_code == 400
        print("✅ test_revert_requires_reason")
        return
    raise AssertionError("deveria rejeitar revert sem reason")


async def test_revert_happy_path():
    await seed_ont(MAC2, "defeito_em_analise")
    payload = DefectiveOntReasonIn(
        code="Outro",
        details="Falso positivo confirmado em laudo técnico nº 4521.",
    )
    resp = await revert_defective_ont(MAC2, payload=payload, user=TEST_USER)
    assert resp["ok"] is True and resp["new_status"] == "disponivel"
    ont = await db.stok_onts.find_one({"mac": MAC2.upper()}, {"_id": 0})
    assert ont["status"] == "disponivel"
    assert ont["is_defective"] is False
    audit = await db[DA_COLLECTION].find_one({"id": resp["audit_id"]}, {"_id": 0})
    assert audit["action_type"] == "revert_defective_ont"
    assert audit["reason"]["code"] == "Outro"
    assert len(audit["reason"]["details"]) >= 20
    print(f"✅ test_revert_happy_path (audit={resp['audit_id']})")


async def main():
    await cleanup()
    await test_scrap_requires_reason()
    await test_scrap_happy_path()
    await test_revert_requires_reason()
    await test_revert_happy_path()
    await cleanup()
    print("\n🟢 TODOS OS SMOKE TESTS DA ONDA 1.4 PASSARAM")


if __name__ == "__main__":
    asyncio.run(main())
