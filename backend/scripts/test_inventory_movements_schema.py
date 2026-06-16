"""
test_inventory_movements_schema.py — CTO 16/02/2026 — Fase 2.

Validações obrigatórias do contrato lógico `inventory_movements`.

Roda como script standalone (não via pytest) para facilitar smoke-test
em produção. Cada teste é uma asserção independente; falha imprime
diagnóstico e exit code != 0.

Cobre:
  1. Movimento válido grava no contrato lógico
  2. Collection física permanece `inventory_os_movements_audit`
  3. Alias lógico funciona (find_movements lê o mesmo lugar)
  4. Movimento sem SN/MAC bloqueia
  5. Movimento com AUTOSN_* bloqueia (D3=a)
  6. movement_type inválido bloqueia
  7. audit_hash obrigatório
  8. origem/destino obrigatórios
  9. Guardrail usa o helper (escrita passa pela validação)
  10. Rollback não apaga histórico (delete_many só remove os de teste)

Uso:
  cd /app/backend && python3 scripts/test_inventory_movements_schema.py
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
import uuid
from datetime import datetime, timezone

# Ajusta path pra importar do /app/backend
sys.path.insert(0, "/app/backend")

from database import db
from services.inventory_movements import (
    PHYSICAL_COLLECTION, LOGICAL_NAME, MOVEMENT_TYPES, OWNER_TYPES,
    InventoryMovementError, is_sn_blocked, write_movement,
    write_movements_bulk, find_movements, count_movements,
    validate_movement,
)
from services.os_inventory_guardrail import enforce_os_inventory_movement


CID = "co-test-fase2-schema"
results = []


def _h(payload: str) -> str:
    """Helper SHA-256 hex para audit_hash de teste."""
    return hashlib.sha256(payload.encode()).hexdigest()


def _record(mtype, **overrides):
    base = {
        "company_id": CID,
        "os_id": f"tkt-{uuid.uuid4().hex[:6]}",
        "ticket_id": None,
        "movement_type": mtype,
        "audit_hash": _h(f"{mtype}-{uuid.uuid4().hex}"),
        "actor_id": "u-test",
        "origin_type": "empresa",
        "destination_type": "tecnico",
        "sn": "REAL-SN-001",
        "mac": "AA:BB:CC:DD:EE:01",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    base["ticket_id"] = base["os_id"]
    base.update(overrides)
    return base


def check(label, ok, detail=""):
    icon = "✅" if ok else "❌"
    results.append((label, ok, detail))
    print(f"  {icon} {label}" + (f" — {detail}" if detail and not ok else ""))


async def cleanup():
    await db[PHYSICAL_COLLECTION].delete_many({"company_id": CID})
    await db.stok_onts.delete_many({"company_id": CID})
    await db.tickets.delete_many({"company_id": CID})


async def main():
    print(f"=== Fase 2 — Validação Schema {LOGICAL_NAME} ===\n")
    await cleanup()
    before_global = await db[PHYSICAL_COLLECTION].count_documents({})

    # T1 — movimento válido grava
    print("T1) Movimento válido grava no contrato lógico")
    rec = _record("instalacao_tecnico_cliente", origin_type="tecnico",
                  destination_type="cliente")
    doc = await write_movement(rec)
    check("grava doc com movement_id + audit_hash",
          bool(doc.get("movement_id") and doc.get("audit_hash")))
    check("created_at preenchido", bool(doc.get("created_at")))
    check("origin_type ↔ origin_owner duplicados",
          doc.get("origin_type") == doc.get("origin_owner") == "tecnico")

    # T2 — collection física permanece inventory_os_movements_audit
    print("\nT2) Collection física permanece inventory_os_movements_audit")
    check(f"PHYSICAL_COLLECTION == 'inventory_os_movements_audit'",
          PHYSICAL_COLLECTION == "inventory_os_movements_audit")
    cnt_phys = await db.inventory_os_movements_audit.count_documents(
        {"company_id": CID})
    check(f"doc gravado em inventory_os_movements_audit (cnt={cnt_phys})",
          cnt_phys >= 1)

    # T3 — alias lógico funciona (read)
    print("\nT3) Alias lógico (find/count_movements) lê a mesma collection")
    found = await find_movements({"company_id": CID}, limit=10)
    cnt_log = await count_movements({"company_id": CID})
    check(f"find_movements retorna {len(found)} doc(s)", len(found) >= 1)
    check(f"count_movements coincide com leitura física",
          cnt_log == cnt_phys)

    # T4 — sem SN nem MAC bloqueia
    print("\nT4) Movimento físico SEM SN/MAC é bloqueado")
    try:
        await write_movement(_record("retirada_cliente_tecnico",
                                       sn=None, mac=None,
                                       origin_type="cliente",
                                       destination_type="tecnico"))
        check("bloqueio sem SN/MAC", False, "deveria ter levantado")
    except InventoryMovementError as e:
        check("bloqueio sem SN/MAC", "obrigatório" in str(e).lower(),
              str(e))

    # T5 — AUTOSN_* bloqueia (D3=a)
    print("\nT5) SN AUTOSN_* é bloqueado (D3=a)")
    try:
        await write_movement(_record("instalacao_tecnico_cliente",
                                       sn="AUTOSN_22334491",
                                       origin_type="tecnico",
                                       destination_type="cliente"))
        check("bloqueio AUTOSN_*", False, "deveria ter levantado")
    except InventoryMovementError as e:
        check("bloqueio AUTOSN_*", "Re-scan" in str(e), str(e))
    # E REAL-LABEL-*-FIXED
    try:
        await write_movement(_record("instalacao_tecnico_cliente",
                                       sn="REAL-LABEL-001-FIXED",
                                       origin_type="tecnico",
                                       destination_type="cliente"))
        check("bloqueio REAL-LABEL-*-FIXED", False)
    except InventoryMovementError:
        check("bloqueio REAL-LABEL-*-FIXED", True)

    # T6 — movement_type inválido
    print("\nT6) movement_type inválido é bloqueado")
    try:
        await write_movement(_record("tipo_que_nao_existe"))
        check("bloqueio movement_type inválido", False)
    except InventoryMovementError as e:
        check("bloqueio movement_type inválido", "inválido" in str(e))

    # T7 — audit_hash obrigatório
    print("\nT7) audit_hash obrigatório e formato SHA-256")
    try:
        bad = _record("instalacao_tecnico_cliente", origin_type="tecnico",
                       destination_type="cliente")
        bad.pop("audit_hash")
        await write_movement(bad)
        check("bloqueio sem audit_hash", False)
    except InventoryMovementError as e:
        check("bloqueio sem audit_hash", "audit_hash" in str(e).lower())
    try:
        bad = _record("instalacao_tecnico_cliente", origin_type="tecnico",
                       destination_type="cliente", audit_hash="ZZZZ")
        await write_movement(bad)
        check("bloqueio audit_hash mal formado", False)
    except InventoryMovementError as e:
        check("bloqueio audit_hash mal formado",
              "SHA-256" in str(e) or "audit_hash" in str(e))

    # T8 — origem/destino obrigatórios
    print("\nT8) origin_type e destination_type obrigatórios (físico)")
    try:
        bad = _record("instalacao_tecnico_cliente")
        bad.pop("origin_type")
        await write_movement(bad)
        check("bloqueio sem origin_type", False)
    except InventoryMovementError:
        check("bloqueio sem origin_type", True)
    try:
        bad = _record("instalacao_tecnico_cliente")
        bad.pop("destination_type")
        await write_movement(bad)
        check("bloqueio sem destination_type", False)
    except InventoryMovementError:
        check("bloqueio sem destination_type", True)
    # owner inválido
    try:
        bad = _record("instalacao_tecnico_cliente",
                       origin_type="planet_mars")
        await write_movement(bad)
        check("bloqueio origin_type fora de OWNER_TYPES", False)
    except InventoryMovementError as e:
        check("bloqueio origin_type fora de OWNER_TYPES",
              "permitidos" in str(e).lower() or "OWNER" in str(e))

    # T9 — guardrail usa o helper
    print("\nT9) Guardrail (apply_on_close) escreve VIA helper (E2E)")
    # Cria ONT confiável + ticket de instalação
    sn_ok = "REAL-SN-T9-001"; mac_ok = "AA:BB:CC:T9:99:01"
    await db.stok_onts.insert_one({
        "id": "ont-t9", "company_id": CID, "scan_sn": sn_ok, "mac": mac_ok,
        "model": "ZTE", "location_type": "tecnico", "location_id": "col-t9",
        "status": "com_tecnico",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    tkt = {
        "id": f"tkt-t9-{uuid.uuid4().hex[:6]}", "company_id": CID,
        "type": "instalacao", "status": "aberta",
        "client_snapshot": {"id": "sub-t9", "name": "T9 Cliente"},
        "assigned_collaborator_id": "col-t9",
    }
    await db.tickets.insert_one(dict(tkt))
    n0 = await db[PHYSICAL_COLLECTION].count_documents({"company_id": CID})
    result = await enforce_os_inventory_movement(
        tkt,
        {"outcome": "sucesso", "physical_attendance": True,
         "ont_sn": sn_ok, "ont": mac_ok, "sinal": -22.5},
        {"id": "col-t9", "role": "colaborador",
         "name": "Tec T9", "origin": "tecnico_app",
         "is_super_admin": False},
    )
    n1 = await db[PHYSICAL_COLLECTION].count_documents({"company_id": CID})
    check(f"guardrail allowed={result['allowed']}", result["allowed"])
    check(f"guardrail gravou {n1-n0} doc(s) via helper canônico",
          n1 - n0 >= 1)
    # Confirma que os docs gravados têm campos canônicos
    docs = await find_movements({"company_id": CID,
                                  "movement_type":
                                      {"$ne": "instalacao_tecnico_cliente"}},
                                 limit=20)
    sample = await db[PHYSICAL_COLLECTION].find_one(
        {"company_id": CID, "movement_type": "instalacao_tecnico_cliente"},
        {"_id": 0},
    )
    check("doc gravado tem origin_type canônico",
          sample and sample.get("origin_type") == "tecnico")
    check("doc gravado tem audit_hash canônico (64 hex)",
          sample and len(sample.get("audit_hash") or "") == 64)

    # T9 bonus — ONT com AUTOSN_* bloqueia via guardrail
    print("\nT9b) Guardrail bloqueia ONT estoque com AUTOSN_* (D3=a)")
    await db.stok_onts.insert_one({
        "id": "ont-t9b", "company_id": CID,
        "scan_sn": "AUTOSN_DEAD0001", "mac": "AA:BB:CC:T9B:99:02",
        "sn_auto_generated": "True",
        "model": "ZTE", "location_type": "tecnico", "location_id": "col-t9b",
        "status": "com_tecnico",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    tkt2 = {
        "id": f"tkt-t9b-{uuid.uuid4().hex[:6]}", "company_id": CID,
        "type": "instalacao", "status": "aberta",
        "client_snapshot": {"id": "sub-t9b", "name": "T9B Cliente"},
        "assigned_collaborator_id": "col-t9b",
    }
    await db.tickets.insert_one(dict(tkt2))
    result2 = await enforce_os_inventory_movement(
        tkt2,
        {"outcome": "sucesso", "physical_attendance": True,
         "ont_sn": "AUTOSN_DEAD0001",
         "ont": "AA:BB:CC:T9B:99:02"},
        {"id": "col-t9b", "role": "colaborador",
         "name": "Tec T9B", "is_super_admin": False},
    )
    check(f"guardrail bloqueou (allowed={result2['allowed']})",
          not result2["allowed"])
    check("motivo D3 presente em blocked_reasons",
          "regra_d3_sn_nao_confiavel_requer_rescan"
          in (result2.get("blocked_reasons") or []))

    # T10 — rollback não apaga histórico (apenas o universo de teste)
    print("\nT10) Cleanup (rollback do teste) só apaga company_id=test")
    n_before_cleanup_global = await db[PHYSICAL_COLLECTION].count_documents({})
    await cleanup()
    n_after_cleanup_global = await db[PHYSICAL_COLLECTION].count_documents({})
    check(f"docs globais antes/depois cleanup: {n_before_cleanup_global}/"
          f"{n_after_cleanup_global} (delta deve ser apenas docs de teste)",
          n_after_cleanup_global == before_global)

    # ── Sumário ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"RESULTADO FINAL: {passed}/{total} checks PASSARAM")
    if passed != total:
        print("\nFALHAS:")
        for label, ok, detail in results:
            if not ok:
                print(f"  ❌ {label} — {detail}")
        sys.exit(1)
    print("✅ Fase 2 — Schema do movimento operacional validado.")


if __name__ == "__main__":
    asyncio.run(main())
