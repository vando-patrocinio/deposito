"""RCA Fibra 12FO/48FO — Estorno auditável (Onda C P0.1).

Reverte os 4 cabos de TESTE identificados em FIBRA_12FO_RCA.md sem deletar
NADA. Cria trilha reversa explícita:

  Débito original (network_cables.stok_debit + stok_history rede_lancamento)
       ↓
  RCA documentado (/app/memory/FIBRA_12FO_RCA.md)
       ↓
  Estorno (network_cables.status=anulado + stok_history rede_estorno
           + stok_stock += valores positivos + stok_admin_log)

Modos:
  --dry-run (default): apenas imprime o que faria, NÃO escreve.
  --execute:           grava o estorno (idempotente via audit_id).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
for _ln in open("/app/backend/.env"):
    if "=" in _ln and not _ln.startswith("#"):
        _k, _v = _ln.strip().split("=", 1)
        os.environ.setdefault(_k, _v.strip('"'))

from database import db  # noqa: E402

COMPANY_ID = "co-demo"
RCA_REF = "ADMIN_TEST_DATA_RCA_20260618"
RCA_DOC = "/app/memory/FIBRA_12FO_RCA.md"

# Os 4 cabos contaminados (identificados na RCA)
CONTAMINATED_CABLES = [
    {"id": "cab-4f21e3e0f7", "type": "12fo", "length_m": 364356.0,
     "serial": "ABCD-TEST-001", "invoice": "12345"},
    {"id": "cab-a530c12c0e", "type": "12fo", "length_m": 1500.0,
     "serial": "FB-TEST-001", "invoice": "NF-9999"},
    {"id": "cab-3f16ef51fa", "type": "12fo", "length_m": 500.0,
     "serial": "TST-DEBIT-12fo", "invoice": "NF-DEBIT"},
    {"id": "cab-afacf584d9", "type": "48fo", "length_m": 200.0,
     "serial": "TST-DEBIT-48fo", "invoice": "NF-DEBIT"},
]

CONSUMABLE_MAP = {"12fo": "fibra_12fo", "48fo": "fibra_48fo"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit_id_for(cable_id: str) -> str:
    """Gera ID determinístico (idempotente) por cabo."""
    base = f"{RCA_REF}|{cable_id}|fibra_estorno"
    h = hashlib.sha256(base.encode()).hexdigest()[:12]
    return f"rca-estorno-{h}"


async def _stock_snapshot() -> dict:
    s = await db.stok_stock.find_one(
        {"company_id": COMPANY_ID, "location": "empresa"}, {"_id": 0})
    return {
        "fibra_12fo": (s or {}).get("fibra_12fo", 0),
        "fibra_48fo": (s or {}).get("fibra_48fo", 0),
    }


async def _validate_cables() -> tuple[bool, list[str]]:
    """Confirma que os 4 cabos existem e estão exatamente como esperado."""
    errs = []
    for c in CONTAMINATED_CABLES:
        doc = await db.network_cables.find_one(
            {"id": c["id"], "company_id": COMPANY_ID}, {"_id": 0})
        if not doc:
            errs.append(f"cabo {c['id']} NÃO existe em network_cables")
            continue
        if doc.get("type") != c["type"]:
            errs.append(f"{c['id']} type esperado={c['type']} achei={doc.get('type')}")
        if abs((doc.get("length_m") or 0) - c["length_m"]) > 0.01:
            errs.append(
                f"{c['id']} length_m esperado={c['length_m']} achei={doc.get('length_m')}"
            )
        if (doc.get("cable_serial") or "").upper() != c["serial"].upper():
            errs.append(
                f"{c['id']} serial esperado={c['serial']} achei={doc.get('cable_serial')}"
            )
        if doc.get("status") == "anulado_admin_test_rca_20260618":
            errs.append(f"{c['id']} JÁ está anulado — não re-estornar")
    return (len(errs) == 0, errs)


async def _execute(dry_run: bool, executor: str) -> dict:
    """Faz o estorno (dry-run só simula)."""
    before = await _stock_snapshot()

    ok, errs = await _validate_cables()
    if not ok:
        return {"ok": False, "errors": errs, "before": before}

    # Soma esperada
    expected_12fo = sum(c["length_m"] for c in CONTAMINATED_CABLES if c["type"] == "12fo")
    expected_48fo = sum(c["length_m"] for c in CONTAMINATED_CABLES if c["type"] == "48fo")
    expected_after = {
        "fibra_12fo": before["fibra_12fo"] + expected_12fo,
        "fibra_48fo": before["fibra_48fo"] + expected_48fo,
    }

    actions_planned = []
    for c in CONTAMINATED_CABLES:
        audit_id = _audit_id_for(c["id"])
        actions_planned.append({
            "cable_id": c["id"], "type": c["type"],
            "length_m": c["length_m"], "audit_id": audit_id,
            "consumable_id": CONSUMABLE_MAP[c["type"]],
            "increment": c["length_m"],
        })

    if dry_run:
        return {
            "ok": True, "dry_run": True,
            "before": before,
            "expected_after": expected_after,
            "expected_estorno_12fo_m": expected_12fo,
            "expected_estorno_48fo_m": expected_48fo,
            "actions_planned": actions_planned,
            "executor": executor,
            "rca_doc": RCA_DOC, "rca_ref": RCA_REF,
        }

    # ────────── EXECUTE MODE ──────────
    now = _now_iso()
    estorno_history_ids = []
    cable_updates = []
    for c in CONTAMINATED_CABLES:
        audit_id = _audit_id_for(c["id"])
        # 1) Marca cabo como anulado (preserva tudo)
        update_res = await db.network_cables.update_one(
            {"id": c["id"], "company_id": COMPANY_ID,
             "status": {"$ne": "anulado_admin_test_rca_20260618"}},
            {"$set": {
                "status": "anulado_admin_test_rca_20260618",
                "previous_status": "cabo_solto",
                "anulado_at": now,
                "anulado_by": executor,
                "anulado_reason": RCA_REF,
                "anulado_audit_id": audit_id,
                "anulado_rca_doc": RCA_DOC,
                "updated_at": now,
            }},
        )
        cable_updates.append({"cable_id": c["id"], "modified": update_res.modified_count})

        # 2) stok_history rede_estorno (idempotente via id)
        hist_id = f"hist-{audit_id}"
        cons_label = "Fibra 12FO" if c["type"] == "12fo" else "Fibra 48FO"
        await db.stok_history.update_one(
            {"id": hist_id},
            {"$setOnInsert": {
                "id": hist_id,
                "company_id": COMPANY_ID,
                "type": "rede_estorno",
                "tag": "rca_fibra_20260618",
                "description": (
                    f"Estorno auditável de {c['length_m']:.0f}m de {cons_label} "
                    f"— cabo {c['id']} ({c['type'].upper()}) — "
                    f"motivo: {RCA_REF}"
                ),
                "user": executor,
                "created_at": now,
                "audit_id": audit_id,
                "rca_doc": RCA_DOC,
                "rca_ref": RCA_REF,
                "original_cable_id": c["id"],
                "original_cable_serial": c["serial"],
                "original_invoice": c["invoice"],
                "consumable_id": CONSUMABLE_MAP[c["type"]],
                "delta_meters_signed": +c["length_m"],  # POSITIVO = estorno
            }},
            upsert=True,
        )
        estorno_history_ids.append(hist_id)

    # 3) Atualiza stok_stock empresa com soma única ($inc) — atômico
    inc_doc = {}
    if expected_12fo > 0:
        inc_doc["fibra_12fo"] = expected_12fo
    if expected_48fo > 0:
        inc_doc["fibra_48fo"] = expected_48fo
    await db.stok_stock.update_one(
        {"company_id": COMPANY_ID, "location": "empresa"},
        {"$inc": inc_doc, "$set": {"updated_at": now}},
    )

    # 4) Registra em stok_admin_log (audit master)
    admin_log_id = f"adm-{_audit_id_for('master')}"
    await db.stok_admin_log.update_one(
        {"id": admin_log_id},
        {"$setOnInsert": {
            "id": admin_log_id,
            "company_id": COMPANY_ID,
            "action": "fibra_rca_estorno",
            "rca_ref": RCA_REF,
            "rca_doc": RCA_DOC,
            "executor": executor,
            "executed_at": now,
            "cables_anulados": [c["id"] for c in CONTAMINATED_CABLES],
            "estorno_12fo_m": expected_12fo,
            "estorno_48fo_m": expected_48fo,
            "history_ids": estorno_history_ids,
            "before": before,
            "expected_after": expected_after,
        }},
        upsert=True,
    )

    after = await _stock_snapshot()
    return {
        "ok": True, "dry_run": False,
        "before": before, "after": after,
        "expected_after": expected_after,
        "cable_updates": cable_updates,
        "estorno_history_ids": estorno_history_ids,
        "admin_log_id": admin_log_id,
        "executor": executor,
    }


def _print_report(res: dict, dry: bool):
    print()
    print("=" * 70)
    print(f"  RCA FIBRA 12FO/48FO — {'DRY-RUN (sem writes)' if dry else 'EXECUTADO'}")
    print("=" * 70)
    if not res.get("ok"):
        print("❌ FALHOU — errors:")
        for e in res.get("errors", []):
            print(f"   · {e}")
        return
    b = res["before"]
    exp = res["expected_after"]
    print(f"\n  Empresa: {COMPANY_ID}")
    print(f"  Executor: {res.get('executor')}")
    print(f"  RCA Ref:  {RCA_REF}")
    print(f"  RCA Doc:  {RCA_DOC}")
    print()
    print("  ┌─────────────┬──────────────┬──────────────┐")
    print("  │ Item        │       Atual  │ Após estorno │")
    print("  ├─────────────┼──────────────┼──────────────┤")
    print(f"  │ fibra_12fo  │ {b['fibra_12fo']:>12,} │ {exp['fibra_12fo']:>12,} │")
    print(f"  │ fibra_48fo  │ {b['fibra_48fo']:>12,} │ {exp['fibra_48fo']:>12,} │")
    print("  └─────────────┴──────────────┴──────────────┘")
    print()
    print(f"  Estorno 12FO: +{res.get('expected_estorno_12fo_m', 0):,}m")
    print(f"  Estorno 48FO: +{res.get('expected_estorno_48fo_m', 0):,}m")
    print()
    print("  Cabos a anular:")
    for a in res.get("actions_planned", []) or []:
        print(f"    · {a['cable_id']:>20} {a['type']:>4} "
              f"+{a['length_m']:>10,.0f}m  audit_id={a['audit_id']}")
    if not dry:
        actual_after = res.get("after", {})
        match12 = actual_after.get("fibra_12fo") == exp["fibra_12fo"]
        match48 = actual_after.get("fibra_48fo") == exp["fibra_48fo"]
        print()
        print(f"  Após execução real: 12fo={actual_after.get('fibra_12fo')} "
              f"(esperado {exp['fibra_12fo']}) "
              f"{'✅' if match12 else '❌'}")
        print(f"                       48fo={actual_after.get('fibra_48fo')} "
              f"(esperado {exp['fibra_48fo']}) "
              f"{'✅' if match48 else '❌'}")
        print(f"  admin_log_id: {res.get('admin_log_id')}")
        print(f"  history_ids: {res.get('estorno_history_ids')}")
    print()


async def main():
    ap = argparse.ArgumentParser(description="RCA Fibra Estorno (Onda C P0.1)")
    ap.add_argument("--execute", action="store_true",
                    help="Executa o estorno (sem essa flag = dry-run)")
    ap.add_argument("--executor", default="rca_20260618_cto",
                    help="Identificador do executor para audit")
    args = ap.parse_args()
    dry = not args.execute
    res = await _execute(dry_run=dry, executor=args.executor)
    _print_report(res, dry)


if __name__ == "__main__":
    asyncio.run(main())
