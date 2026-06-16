"""
ONDA 1.1 — Smoke tests do helper canônico `destructive_audit`.

Valida:
1. Constantes (`ACTION_TYPES`, `DESTRUCTIVE_REASONS`) corretas.
2. `record_destructive_action` rejeita action_type inválido.
3. Rejeita `reason.code` fora da whitelist.
4. Rejeita `reason.code == "Outro"` sem `details ≥ 20 chars`.
5. Rejeita `executed_by` sem id/email.
6. Aceita registro completo, gera `audit_hash` SHA-256, persiste.
7. `attach_after_snapshot` atualiza o doc gravado.
8. Hash é determinístico (mesmo input → mesmo hash).
9. Collection física é `destructive_actions_audit` (separada).

Uso: python3 scripts/test_onda1_destructive_audit.py
"""
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import db  # noqa: E402
from services.destructive_audit import (  # noqa: E402
    ACTION_TYPES, DESTRUCTIVE_REASONS, MIN_REASON_DETAILS_LENGTH,
    DestructiveAuditError, PHYSICAL_COLLECTION,
    record_destructive_action, attach_after_snapshot,
    count_destructive_actions, find_destructive_actions,
    validate_record, _audit_hash,
)


# Marker para limpar nossos próprios docs de teste (sem afetar produção)
TEST_COMPANY = "co-test-destructive-audit-xyz"


def test_constants():
    assert "stok_reset_full" in ACTION_TYPES
    assert "scrap_ont" in ACTION_TYPES
    assert "wipe_tickets" in ACTION_TYPES
    assert len(ACTION_TYPES) == 8, f"esperava 8 action_types, got {len(ACTION_TYPES)}"
    assert "Outro" in DESTRUCTIVE_REASONS
    assert "Inventário incorreto" in DESTRUCTIVE_REASONS
    assert len(DESTRUCTIVE_REASONS) == 9, \
        f"esperava 9 motivos, got {len(DESTRUCTIVE_REASONS)}"
    assert MIN_REASON_DETAILS_LENGTH == 20
    print("✅ test_constants")


def test_validate_rejects_bad_action_type():
    rec = {
        "action_type": "fake_destruction",
        "company_id": "co",
        "executed_at": "2026-02-16T00:00:00Z",
        "executed_by": {"id": "u1", "email": "a@b"},
        "reason": {"code": "Erro operacional"},
        "before_snapshot": {"counts": {"onts": 1}},
    }
    try:
        validate_record(rec)
    except DestructiveAuditError as e:
        assert "action_type inválido" in str(e)
        print("✅ test_validate_rejects_bad_action_type")
        return
    raise AssertionError("deveria ter rejeitado action_type inválido")


def test_validate_rejects_bad_reason_code():
    rec = {
        "action_type": "stok_reset_full",
        "company_id": "co",
        "executed_at": "2026-02-16T00:00:00Z",
        "executed_by": {"id": "u1"},
        "reason": {"code": "Porque sim"},  # fora da whitelist
        "before_snapshot": {"counts": {}},
    }
    try:
        validate_record(rec)
    except DestructiveAuditError as e:
        assert "reason.code inválido" in str(e)
        print("✅ test_validate_rejects_bad_reason_code")
        return
    raise AssertionError("deveria ter rejeitado reason.code fora da whitelist")


def test_validate_rejects_outro_without_details():
    rec = {
        "action_type": "scrap_ont",
        "company_id": "co",
        "executed_at": "2026-02-16T00:00:00Z",
        "executed_by": {"email": "a@b"},
        "reason": {"code": "Outro", "details": "pouco"},  # < 20 chars
        "before_snapshot": {"counts": {}},
    }
    try:
        validate_record(rec)
    except DestructiveAuditError as e:
        assert "Outro" in str(e) and "20 caracteres" in str(e)
        print("✅ test_validate_rejects_outro_without_details")
        return
    raise AssertionError("deveria exigir details ≥ 20 chars em reason=Outro")


def test_validate_rejects_executed_by_empty():
    rec = {
        "action_type": "wipe_tickets",
        "company_id": "co",
        "executed_at": "2026-02-16T00:00:00Z",
        "executed_by": {},  # sem id nem email
        "reason": {"code": "Erro operacional"},
        "before_snapshot": {"counts": {}},
    }
    try:
        validate_record(rec)
    except DestructiveAuditError as e:
        assert "id" in str(e) and "email" in str(e)
        print("✅ test_validate_rejects_executed_by_empty")
        return
    raise AssertionError("deveria rejeitar executed_by sem id/email")


def test_audit_hash_is_sha256_hex():
    rec = {
        "action_type": "stok_reset_full",
        "company_id": "co-x",
        "executed_at": "2026-02-16T00:00:00Z",
        "executed_by": {"id": "u-1", "email": "a@b"},
        "reason": {"code": "Erro operacional"},
        "scope": {"reset_onts": True},
        "before_snapshot": {"docs": [{"id": "ont-1", "mac": "AA:BB"}]},
    }
    h = _audit_hash(rec)
    assert isinstance(h, str) and len(h) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", h), f"hash não é SHA-256 hex: {h}"
    # Determinístico
    h2 = _audit_hash(rec)
    assert h == h2, "hash não é determinístico!"
    print("✅ test_audit_hash_is_sha256_hex")


async def test_record_persists_and_returns():
    rec = await record_destructive_action(
        company_id=TEST_COMPANY,
        action_type="stok_reset_granular",
        reason={"code": "Inventário incorreto"},
        executed_by={"id": "u-test-1", "email": "test@ligo",
                     "name": "Teste", "role": "auditor"},
        before_snapshot={
            "docs": [
                {"id": "ont-1", "mac": "AA:BB:CC:01", "scan_sn": "SN001"},
                {"id": "ont-2", "mac": "AA:BB:CC:02", "scan_sn": "SN002"},
            ],
            "counts": {"onts": 2},
        },
        scope={"scope": "collaborator", "target_id": "tech-1"},
    )
    assert rec["audit_id"].startswith("dest-")
    assert len(rec["audit_hash"]) == 64
    assert rec["after_snapshot"] is None
    # Persistiu?
    n = await count_destructive_actions({"id": rec["audit_id"]})
    assert n == 1, f"doc não persistiu (count={n})"
    # Collection física correta?
    raw = await db[PHYSICAL_COLLECTION].find_one(
        {"id": rec["audit_id"]}, {"_id": 0})
    assert raw is not None
    print(f"✅ test_record_persists_and_returns (audit_id={rec['audit_id']})")
    return rec["audit_id"]


async def test_attach_after_snapshot(audit_id):
    updated = await attach_after_snapshot(
        audit_id,
        {"counts": {"onts": 0}, "delta": {"onts_removed": 2}},
    )
    assert updated["after_snapshot"] is not None
    assert updated["after_snapshot"]["counts"]["onts"] == 0
    assert updated["after_attached_at"] is not None
    print("✅ test_attach_after_snapshot")


async def test_attach_nonexistent_raises():
    try:
        await attach_after_snapshot("dest-doesnotexist", {"counts": {}})
    except DestructiveAuditError as e:
        assert "não encontrado" in str(e)
        print("✅ test_attach_nonexistent_raises")
        return
    raise AssertionError("deveria ter levantado erro para audit_id inexistente")


async def test_find_destructive_actions():
    items = await find_destructive_actions(
        {"company_id": TEST_COMPANY}, limit=10)
    assert isinstance(items, list)
    assert len(items) >= 1
    # Ordenado por executed_at desc
    for it in items:
        assert "_id" not in it
        assert it.get("audit_hash"), "audit_hash deve estar no doc lido"
    print(f"✅ test_find_destructive_actions ({len(items)} encontrados)")


async def test_collection_is_separate():
    # Garante que NÃO está em stok_admin_log nem em inventory_movements
    in_admin_log = await db.stok_admin_log.count_documents(
        {"company_id": TEST_COMPANY})
    in_inv_movements = await db.inventory_os_movements_audit.count_documents(
        {"company_id": TEST_COMPANY})
    assert in_admin_log == 0, "vazou para stok_admin_log!"
    assert in_inv_movements == 0, "vazou para inventory_movements!"
    print("✅ test_collection_is_separate")


async def cleanup():
    await db[PHYSICAL_COLLECTION].delete_many({"company_id": TEST_COMPANY})


async def main():
    # Cleanup prévio (idempotência)
    await cleanup()

    # Sync tests
    test_constants()
    test_validate_rejects_bad_action_type()
    test_validate_rejects_bad_reason_code()
    test_validate_rejects_outro_without_details()
    test_validate_rejects_executed_by_empty()
    test_audit_hash_is_sha256_hex()

    # Async tests (precisam de banco)
    audit_id = await test_record_persists_and_returns()
    await test_attach_after_snapshot(audit_id)
    await test_attach_nonexistent_raises()
    await test_find_destructive_actions()
    await test_collection_is_separate()

    # Final cleanup
    await cleanup()
    print("\n🟢 TODOS OS SMOKE TESTS DA ONDA 1.1 PASSARAM")


if __name__ == "__main__":
    asyncio.run(main())
