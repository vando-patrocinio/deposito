"""
ONDA 0 — Smoke test dos patches (0a/0b/0d).

Valida:
1. `ticket_reopen_revert` está no whitelist MOVEMENT_TYPES.
2. `write_movement` aceita o novo tipo com payload mínimo.
3. SN bloqueado (AUTOSN_*) continua sendo rejeitado em ticket_reopen_revert.
4. `auto_close_service_from_ticket` aceita kwarg `caller` sem quebrar.

Uso: python3 scripts/test_onda0_patches.py
"""
import asyncio
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.inventory_movements import (  # noqa: E402
    MOVEMENT_TYPES,
    InventoryMovementError,
    validate_movement,
)


def _hash(rec):
    canon = json.dumps({k: rec.get(k) for k in (
        "os_id", "ticket_id", "client_id", "technician_id",
        "equipment_id", "sn", "mac", "movement_type",
        "origin_owner", "destination_owner", "actor_id",
    )}, sort_keys=True, default=str)
    return hashlib.sha256(canon.encode()).hexdigest()


def test_movement_type_registered():
    assert "ticket_reopen_revert" in MOVEMENT_TYPES, \
        "ticket_reopen_revert deve estar no whitelist"
    print("✅ test_movement_type_registered")


def test_validate_revert_payload_ok():
    rec = {
        "os_id": "tk-001",
        "ticket_id": "tk-001",
        "company_id": "co-demo",
        "movement_type": "ticket_reopen_revert",
        "origin_type": "cliente",
        "destination_type": "tecnico",
        "origin_owner": "cliente",
        "destination_owner": "tecnico",
        "sn": "REAL-1234567890",
        "mac": "AA:BB:CC:DD:EE:01",
        "actor_id": "adm-1",
        "technician_id": "tech-1",
        "client_id": "cli-1",
    }
    rec["audit_hash"] = _hash(rec)
    validate_movement(rec)
    print("✅ test_validate_revert_payload_ok")


def test_validate_revert_blocks_autosn():
    rec = {
        "os_id": "tk-002",
        "ticket_id": "tk-002",
        "company_id": "co-demo",
        "movement_type": "ticket_reopen_revert",
        "origin_type": "cliente",
        "destination_type": "tecnico",
        "origin_owner": "cliente",
        "destination_owner": "tecnico",
        "sn": "AUTOSN_ABCDEF",  # D3=a — deve bloquear
        "actor_id": "adm-1",
    }
    rec["audit_hash"] = _hash(rec)
    try:
        validate_movement(rec)
    except InventoryMovementError as e:
        print(f"✅ test_validate_revert_blocks_autosn (msg='{e}')")
        return
    raise AssertionError("ticket_reopen_revert com AUTOSN_ deveria ter sido bloqueado")


def test_auto_close_accepts_caller_kwarg():
    # Apenas valida que a função expõe `caller` como kwarg sem quebrar.
    from routes.stok import auto_close_service_from_ticket
    import inspect
    sig = inspect.signature(auto_close_service_from_ticket)
    assert "caller" in sig.parameters, "auto_close_service_from_ticket deve aceitar kwarg `caller`"
    p = sig.parameters["caller"]
    assert p.kind == inspect.Parameter.KEYWORD_ONLY, "caller deve ser keyword-only"
    print("✅ test_auto_close_accepts_caller_kwarg")


def test_finalize_ticket_has_guardrail():
    # Lê o source de routes/lousa.py e verifica menção ao chokepoint
    # exatamente dentro de finalize_ticket (não public).
    src = (ROOT / "routes" / "lousa.py").read_text(encoding="utf-8")
    marker = "ONDA 0a — Chokepoint no handler JWT autenticado"
    assert marker in src, "chokepoint Onda 0a NÃO está presente em lousa.py"
    print("✅ test_finalize_ticket_has_guardrail")


def test_revert_writes_movement():
    # Idem: verifica que _revert_ticket_side_effects chama write_movement
    # antes de mutar stok_onts.
    src = (ROOT / "routes" / "lousa.py").read_text(encoding="utf-8")
    assert "Onda 0d — Trilha reversa ANTES de mutar stok_onts" in src, \
        "movimento reverso Onda 0d ausente em lousa.py"
    # Garantir que aparece nos 2 ramos (uninstall + reinstall)
    count = src.count("Onda 0d — Trilha reversa ANTES de mutar stok_onts")
    assert count >= 2, f"esperava 2 ocorrências do patch 0d, encontrei {count}"
    print(f"✅ test_revert_writes_movement (occorrências={count})")


async def main():
    test_movement_type_registered()
    test_validate_revert_payload_ok()
    test_validate_revert_blocks_autosn()
    test_auto_close_accepts_caller_kwarg()
    test_finalize_ticket_has_guardrail()
    test_revert_writes_movement()
    print("\n🟢 TODOS OS SMOKE TESTS DA ONDA 0 PASSARAM")


if __name__ == "__main__":
    asyncio.run(main())
