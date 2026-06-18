"""Onda A — Bug #1 + Bug #2 — testes de regressão.

Bug #1: transferência empresa→técnico deve ZERAR deficit antes de creditar.
Bug #2: stok_services órfãs (ticket inexistente) devem ser marcadas, não apagadas.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, "/app/backend")
for ln in open("/app/backend/.env"):
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.strip().split("=", 1)
        os.environ.setdefault(k, v.strip('"'))

pytestmark = pytest.mark.asyncio(loop_scope="session")
CID = "TEST-ONDA-A"


async def _setup_stock(tech_id, drop_qty):
    """Coloca o técnico com `drop_qty` (pode ser negativo)."""
    import uuid as _uuid
    from database import db
    await db.stok_stock.delete_many({"company_id": CID})
    await db.stok_stock.insert_one({
        "company_id": CID, "location": "empresa", "drop": 200,
    })
    if drop_qty != 0:
        await db.stok_stock.insert_one({
            "company_id": CID, "location": tech_id, "drop": drop_qty,
        })
    await db.collaborators.delete_many({"company_id": CID})
    await db.collaborators.insert_one({
        "id": tech_id, "name": "Teste Tech", "company_id": CID,
        "cpf": f"TEST-{_uuid.uuid4().hex[:11]}",  # cpf unique idx
    })


async def _do_transfer(tech_id, qty, mode=None):
    """Chama a função internamente (bypass auth)."""
    from routes.stok import transfer_consumable, ConsumableTransferIn
    payload = ConsumableTransferIn(
        consumable_id="drop", quantity=qty,
        technician_id=tech_id, mode=mode,
    )
    user = {"id": "test-user", "name": "Test", "company_id": CID,
             "role": "gestor"}
    return await transfer_consumable(payload, user=user)


async def _cleanup():
    from database import db
    await db.stok_stock.delete_many({"company_id": CID})
    await db.collaborators.delete_many({"company_id": CID})
    await db.stok_services.delete_many({"company_id": CID})
    await db.tickets.delete_many({"company_id": CID})
    await db.stok_transfer_audit.delete_many({"company_id": CID})


# ─── Bug #1 ────────────────────────────────────────────────────


async def test_bug1_auto_zera_deficit_negativo():
    """Saldo -24 + transferir 30 → reposicao, qty=6, deficit=24."""
    tech = "col-test-vando"
    await _setup_stock(tech, -24)
    out = await _do_transfer(tech, 30)
    assert out["mode_effective"] == "reposicao"
    assert out["qty_before"] == -24
    assert out["qty_after"] == 6
    assert out["deficit_zeroed"] == 24
    # Verifica o real estado no DB
    from database import db
    s = await db.stok_stock.find_one({"company_id": CID, "location": tech})
    assert s["drop"] == 6
    await _cleanup()
    print("  ✓ Bug#1 AUTO em deficit: -24 + 30 → 6 (Reposição)")


async def test_bug1_explicit_credito_em_negativo():
    """Mode=credito força legacy mesmo com saldo negativo."""
    tech = "col-test-credito"
    await _setup_stock(tech, -24)
    out = await _do_transfer(tech, 30, mode="credito")
    assert out["mode_effective"] == "credito"
    assert out["qty_before"] == -24
    assert out["qty_after"] == 6  # ainda chega a 6 ($inc cumulativo)
    assert out["deficit_zeroed"] == 0
    await _cleanup()
    print("  ✓ Bug#1 modo crédito explícito: -24 + 30 (cego) → 6")


async def test_bug1_reposicao_cobertura_parcial():
    """Saldo -10 + transferir 5 → reposicao parcial, qty=-5."""
    tech = "col-test-parcial"
    await _setup_stock(tech, -10)
    out = await _do_transfer(tech, 5)
    assert out["mode_effective"] == "reposicao"
    assert out["qty_before"] == -10
    assert out["qty_after"] == -5
    assert out["deficit_zeroed"] == 10  # deficit existia, contado integral
    from database import db
    s = await db.stok_stock.find_one({"company_id": CID, "location": tech})
    assert s["drop"] == -5
    await _cleanup()
    print("  ✓ Bug#1 cobertura parcial: -10 + 5 → -5")


async def test_bug1_auto_credito_em_positivo():
    """Saldo +6 + transferir 10 → credito (auto), qty=16."""
    tech = "col-test-pos"
    await _setup_stock(tech, 6)
    out = await _do_transfer(tech, 10)
    assert out["mode_effective"] == "credito"
    assert out["qty_before"] == 6
    assert out["qty_after"] == 16
    assert out["deficit_zeroed"] == 0
    await _cleanup()
    print("  ✓ Bug#1 saldo positivo: 6 + 10 → 16 (crédito auto)")


async def test_bug1_audit_persistido():
    """Cada transfer gera doc em stok_transfer_audit."""
    from database import db
    tech = "col-test-audit"
    await _setup_stock(tech, -5)
    out = await _do_transfer(tech, 15)
    audit = await db.stok_transfer_audit.find_one(
        {"id": out["transfer_audit_id"]}, {"_id": 0},
    )
    assert audit is not None
    assert audit["qty_before"] == -5
    assert audit["qty_after"] == 10
    assert audit["deficit_zeroed"] == 5
    assert audit["mode_effective"] == "reposicao"
    await _cleanup()
    print("  ✓ Bug#1 audit log persistido com antes/depois")


async def test_bug1_mode_invalido_400():
    from fastapi import HTTPException
    tech = "col-test-mode"
    await _setup_stock(tech, 0)
    try:
        await _do_transfer(tech, 5, mode="xpto")
        assert False, "deveria ter levantado HTTPException"
    except HTTPException as e:
        assert e.status_code == 400
        assert "Modo inválido" in e.detail
    await _cleanup()
    print("  ✓ Bug#1 mode='xpto' → HTTPException 400")


# ─── Bug #2 ────────────────────────────────────────────────────


async def test_bug2_reconciliacao_marca_orfa():
    """OS ativa cujo ticket NÃO existe vira 'orfa_sem_ticket'."""
    import uuid as _uuid
    from database import db
    from scripts.reconcile_orphan_stok_services import reconcile
    # Cenário: 2 OS ativas, 1 com ticket válido, 1 órfã (IDs únicos)
    valid_tid = f"tkt-valid-{_uuid.uuid4().hex[:8]}"
    orfa_sid = f"OS-ORFA-{_uuid.uuid4().hex[:8]}"
    valid_sid = f"OS-VALID-{_uuid.uuid4().hex[:8]}"
    await _cleanup()
    await db.tickets.insert_one({
        "id": valid_tid, "company_id": CID, "status": "aberta",
        "client_id": "cli-test", "type": "reparo",
        "client_snapshot": {"name": "Test", "phone": "0", "address": "0"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await db.stok_services.insert_many([
        {"id": valid_sid, "company_id": CID, "ticket_id": valid_tid,
          "status": "ativo", "type": "instalacao"},
        {"id": orfa_sid, "company_id": CID,
          "ticket_id": f"tkt-NOPE-{_uuid.uuid4().hex[:8]}",
          "status": "ativo", "type": "reparo"},
    ])
    stats = await reconcile(company_id=CID, dry_run=False)
    assert stats["scanned"] == 2
    assert stats["valid_ticket"] == 1
    assert stats["orphan_marked"] == 1

    # Verifica estado final
    s_orfa = await db.stok_services.find_one({"id": orfa_sid}, {"_id": 0})
    s_valid = await db.stok_services.find_one({"id": valid_sid}, {"_id": 0})
    assert s_orfa["status"] == "orfa_sem_ticket"
    assert s_orfa["previous_status"] == "ativo"
    assert "orphaned_at" in s_orfa
    assert s_valid["status"] == "ativo"  # intacto
    await _cleanup()
    print("  ✓ Bug#2 órfã marcada · válida preservada")


async def test_bug2_dry_run_nao_altera():
    """Dry-run conta órfãs mas não escreve nada."""
    from database import db
    from scripts.reconcile_orphan_stok_services import reconcile
    await db.stok_services.insert_one({
        "id": "OS-DRY", "company_id": CID, "ticket_id": "tkt-noexist",
        "status": "ativo", "type": "instalacao",
    })
    stats = await reconcile(company_id=CID, dry_run=True)
    assert stats["orphan_marked"] == 1
    # Estado NÃO mudou
    s = await db.stok_services.find_one({"id": "OS-DRY"}, {"_id": 0})
    assert s["status"] == "ativo"  # ainda ativo
    assert "orphaned_at" not in s
    await _cleanup()
    print("  ✓ Bug#2 dry-run: detecta mas não altera")


async def test_bug2_idempotente():
    """Rodar 2x não duplica nem altera órfãs já marcadas."""
    from database import db
    from scripts.reconcile_orphan_stok_services import reconcile
    await db.stok_services.insert_one({
        "id": "OS-IDEM", "company_id": CID, "ticket_id": "tkt-x",
        "status": "ativo", "type": "instalacao",
    })
    s1 = await reconcile(company_id=CID, dry_run=False)
    s2 = await reconcile(company_id=CID, dry_run=False)
    assert s1["orphan_marked"] == 1
    # 2ª passada não acha nada (filtro é status=ativo)
    assert s2["scanned"] == 0
    await _cleanup()
    print("  ✓ Bug#2 idempotente: 2ª execução não re-marca")
