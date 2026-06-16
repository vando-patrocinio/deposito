"""ONDA 1.2 — Smoke test E2E das 2 rotas refatoradas.

Valida via banco direto (sem subir cliente HTTP) que o handler:
1. Rejeita sem `reason` (HTTP 400).
2. Aceita reason válido, grava `destructive_actions_audit` antes do delete.
3. Anexa `after_snapshot` após o delete.
4. Mantém compat com `stok_admin_log` (collection legada).
5. `before_snapshot.docs` contém dump completo (não só counts).
6. `audit_hash` SHA-256 presente.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import db  # noqa: E402
from services.destructive_audit import (  # noqa: E402
    PHYSICAL_COLLECTION as DA_COLLECTION,
    DestructiveAuditError,
)

# Importa o handler diretamente
from routes.stok import (  # noqa: E402
    stok_admin_reset, stok_admin_reset_granular,
    StokResetIn, StokGranularResetIn, ReasonIn,
)
from fastapi import HTTPException  # noqa: E402


TEST_CID = "co-onda1-test-xyz"
TEST_USER = {
    "id": "u-test-auditor",
    "email": "auditor@test",
    "name": "Auditor Teste",
    "role": "auditor",
    "company_id": TEST_CID,
}


async def seed():
    """Cria fixtures isoladas no tenant de teste."""
    await db.stok_onts.delete_many({"company_id": TEST_CID})
    await db.stok_consumables.delete_many({"company_id": TEST_CID})
    await db.stok_history.delete_many({"company_id": TEST_CID})
    await db.stok_admin_log.delete_many({"company_id": TEST_CID})
    await db.stok_stock.delete_many({"company_id": TEST_CID})
    await db[DA_COLLECTION].delete_many({"company_id": TEST_CID})

    # 3 ONTs de teste
    await db.stok_onts.insert_many([
        {"id": f"ont-{i}", "company_id": TEST_CID,
         "mac": f"AA:BB:CC:0{i}:00:00",
         "scan_sn": f"SN-TEST-{i}",
         "model": "FIBERHOME HG6145D",
         "status": "disponivel",
         "location_type": "empresa", "location_id": None,
         "client_name": None}
        for i in range(1, 4)
    ])
    # 2 consumables
    await db.stok_consumables.insert_many([
        {"id": f"cons-{i}", "company_id": TEST_CID, "type": "drop",
         "name": f"Drop teste {i}", "qty": 100}
        for i in range(1, 3)
    ])


async def cleanup():
    for c in ["stok_onts", "stok_consumables", "stok_history",
              "stok_admin_log", "stok_stock", DA_COLLECTION,
              "smartolt_onus"]:
        await db[c].delete_many({"company_id": TEST_CID})


async def test_reset_full_rejects_without_reason():
    payload = StokResetIn(confirm="ZERAR ESTOQUE", reset_onts=True)  # sem reason
    try:
        await stok_admin_reset(payload, user=TEST_USER)
    except HTTPException as e:
        assert e.status_code == 400, f"esperava 400, got {e.status_code}"
        detail = e.detail if isinstance(e.detail, dict) else {"error": e.detail}
        assert detail.get("error") == "destructive_reason_required" or \
               "reason" in str(detail).lower()
        print("✅ test_reset_full_rejects_without_reason")
        return
    raise AssertionError("deveria ter rejeitado payload sem reason")


async def test_reset_full_rejects_outro_short_details():
    payload = StokResetIn(
        confirm="ZERAR ESTOQUE",
        reset_onts=True, reset_insumos=False, reset_history=False,
        reason=ReasonIn(code="Outro", details="curto"),  # < 20 chars
    )
    try:
        await stok_admin_reset(payload, user=TEST_USER)
    except HTTPException as e:
        assert e.status_code == 400
        print(f"✅ test_reset_full_rejects_outro_short_details (detail={e.detail})")
        return
    raise AssertionError("deveria ter rejeitado Outro com details curto")


async def test_reset_full_happy_path():
    await seed()
    payload = StokResetIn(
        confirm="ZERAR ESTOQUE",
        reset_onts=True, reset_insumos=True, reset_history=False,
        reason=ReasonIn(code="Inventário incorreto"),
    )
    resp = await stok_admin_reset(payload, user=TEST_USER)
    assert resp["ok"] is True
    assert resp["deleted"]["onts"] == 3
    assert resp["deleted"]["insumos"] == 2
    assert resp["after"]["onts"] == 0
    assert resp["after"]["insumos"] == 0
    assert resp["audit_id"].startswith("dest-")
    assert len(resp["audit_hash"]) == 64

    # Verifica auditoria persistida
    audit = await db[DA_COLLECTION].find_one({"id": resp["audit_id"]}, {"_id": 0})
    assert audit is not None
    assert audit["action_type"] == "stok_reset_full"
    assert audit["reason"]["code"] == "Inventário incorreto"
    # before_snapshot.docs com dump COMPLETO
    docs = audit["before_snapshot"]["docs"]
    assert len(docs) == 5, f"esperava 5 docs (3 onts + 2 cons), got {len(docs)}"
    # confere campos do dump
    ont_docs = [d for d in docs if d.get("mac")]
    assert len(ont_docs) == 3
    for d in ont_docs:
        assert d.get("mac") and d.get("scan_sn") and d.get("model")
    # after_snapshot anexado
    assert audit["after_snapshot"] is not None
    assert audit["after_snapshot"]["counts"]["onts"] == 0
    # cross-reference com log legado
    log = await db.stok_admin_log.find_one({"id": resp["log_id"]}, {"_id": 0})
    assert log is not None
    assert log["destructive_audit_id"] == resp["audit_id"]
    assert log["destructive_audit_hash"] == resp["audit_hash"]
    print(f"✅ test_reset_full_happy_path (deleted={resp['deleted']})")


async def test_reset_granular_rejects_without_reason():
    await seed()
    payload = StokGranularResetIn(
        confirm="ZERAR ESTOQUE", scope="collaborator",
        target_id="non-existent-collab",
    )
    try:
        await stok_admin_reset_granular(payload, user=TEST_USER)
    except HTTPException as e:
        # Pode falhar em reason OU em colaborador-não-encontrado (404).
        # Aceita 400 como sucesso do teste (reason é validado ANTES do
        # lookup do colaborador na nova versão).
        assert e.status_code == 400, f"esperava 400, got {e.status_code}"
        print("✅ test_reset_granular_rejects_without_reason")
        return
    raise AssertionError("deveria ter rejeitado payload sem reason")


async def test_reset_granular_collaborator_happy_path():
    await seed()
    # Cria colaborador + ONT atribuída a ele
    coll_id = "tech-test-onda1"
    await db.collaborators.insert_one({
        "id": coll_id, "company_id": TEST_CID,
        "name": "Técnico Onda1", "email": "tech@test",
    })
    await db.stok_onts.update_one(
        {"id": "ont-1", "company_id": TEST_CID},
        {"$set": {"location_type": "tecnico", "location_id": coll_id}},
    )

    payload = StokGranularResetIn(
        confirm="ZERAR ESTOQUE", scope="collaborator",
        target_id=coll_id, reset_onts=True, reset_consumables=False,
        reason=ReasonIn(code="Erro operacional"),
    )
    resp = await stok_admin_reset_granular(payload, user=TEST_USER)
    assert resp["ok"] is True
    assert resp["deleted"]["onts"] == 1
    assert resp["audit_id"].startswith("dest-")

    audit = await db[DA_COLLECTION].find_one({"id": resp["audit_id"]}, {"_id": 0})
    assert audit["action_type"] == "stok_reset_granular"
    assert audit["scope"]["target_id"] == coll_id
    assert len(audit["before_snapshot"]["docs"]) == 1
    assert audit["before_snapshot"]["docs"][0]["mac"] == "AA:BB:CC:01:00:00"
    assert audit["after_snapshot"]["counts"]["onts"] == 0

    # Cleanup colaborador
    await db.collaborators.delete_one({"id": coll_id})
    print(f"✅ test_reset_granular_collaborator_happy_path (audit={resp['audit_id']})")


async def main():
    await cleanup()
    await test_reset_full_rejects_without_reason()
    await test_reset_full_rejects_outro_short_details()
    await test_reset_full_happy_path()
    await test_reset_granular_rejects_without_reason()
    await test_reset_granular_collaborator_happy_path()
    await cleanup()
    print("\n🟢 TODOS OS SMOKE TESTS DA ONDA 1.2 PASSARAM")


if __name__ == "__main__":
    asyncio.run(main())
