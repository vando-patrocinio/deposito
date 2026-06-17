"""Sprint 3.A — Backfill sintético dos órfãos da Onda 2.

Identifica ONTs ATIVAS (`empresa`/`tecnico`/`cliente`/`defeito`) sem
nenhuma trilha em `inventory_os_movements_audit` e cria UMA trilha
sintética por ONT na collection SEPARADA
`inventory_movements_synthetic_backfill`.

⚠️ NÃO polui o ledger canônico. NÃO valida o grafo (apenas registra
o estado atual como genesis sintético).

Uso:
    cd /app/backend && python -m scripts.backfill_onda2_orphans \\
        --company co-demo --dry-run
    # Se OK:
    python -m scripts.backfill_onda2_orphans --company co-demo --apply

Mapeamento de inferência (decisão CEO 16/02/2026):
    - source ∈ {compra, compra-reprocess, reprocess-image, reprocess-sns}
      → movement_type = synthetic_purchase_genesis_backfill
    - source ∈ {ai_scan_retirada, ai_scan_batch, retirada_manual, scan_batch_commit}
      → movement_type = synthetic_scan_genesis_backfill
    - source vazio/desconhecido
      → movement_type = synthetic_unknown_genesis_backfill, needs_human_review=True
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Any, Dict, List

# Garantir que rodando de /app/backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db  # noqa: E402
from services.transfer_engine import record_synthetic_backfill  # noqa: E402

logger = logging.getLogger("backfill_onda2_orphans")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

PURCHASE_SOURCES = {"compra", "compra-reprocess", "reprocess-image",
                     "reprocess-sns"}
SCAN_SOURCES = {"ai_scan_retirada", "ai_scan_batch", "retirada_manual",
                 "scan_batch_commit", "ai_scan_install"}

ACTIVE_LOCATIONS = ["empresa", "tecnico", "cliente", "defeito"]


def classify(source: str | None) -> tuple[str, bool]:
    """Retorna (movement_type, needs_human_review)."""
    s = (source or "").strip().lower()
    if s in PURCHASE_SOURCES:
        return "synthetic_purchase_genesis_backfill", False
    if s in SCAN_SOURCES:
        return "synthetic_scan_genesis_backfill", False
    return "synthetic_unknown_genesis_backfill", True


async def find_orphans(company_id: str) -> List[Dict[str, Any]]:
    """Retorna ONTs ativas sem trilha em inventory_os_movements_audit."""
    cursor = db.stok_onts.find(
        {"company_id": company_id,
         "location_type": {"$in": ACTIVE_LOCATIONS}},
        {"_id": 0, "id": 1, "mac": 1, "scan_sn": 1, "location_type": 1,
         "location_id": 1, "status": 1, "source": 1, "created_at": 1,
         "valuation_grade": 1, "valuation_genesis_via": 1, "model": 1,
         "client_name": 1, "installed_at": 1, "withdrawn_at": 1},
    )
    orphans: List[Dict[str, Any]] = []
    async for d in cursor:
        # Já tem trilha sintética? skip (idempotente).
        existing_synthetic = await db.inventory_movements_synthetic_backfill.find_one(
            {"company_id": company_id,
             "$or": [{"mac": d.get("mac")}, {"sn": d.get("scan_sn")}]},
            {"_id": 1},
        )
        if existing_synthetic:
            continue
        # Já tem trilha canônica? skip.
        canonical = await db.inventory_os_movements_audit.find_one(
            {"company_id": company_id,
             "$or": [{"mac": d.get("mac")}, {"sn": d.get("scan_sn")}]},
            {"_id": 1},
        )
        if canonical:
            continue
        orphans.append(d)
    return orphans


async def main(company_id: str, apply: bool, operator_email: str) -> int:
    mode = "APPLY" if apply else "DRY-RUN"
    logger.info("═" * 70)
    logger.info("Sprint 3.A — Backfill Onda 2 — company=%s · mode=%s",
                company_id, mode)
    logger.info("═" * 70)

    orphans = await find_orphans(company_id)
    total = len(orphans)
    logger.info("Órfãs detectadas: %d", total)
    if total == 0:
        logger.info("Nada a fazer. Saindo.")
        return 0

    # Classificação
    by_type: Dict[str, int] = {}
    by_review: int = 0
    sample: List[Dict[str, Any]] = []
    for o in orphans:
        mt, nhr = classify(o.get("source"))
        by_type[mt] = by_type.get(mt, 0) + 1
        if nhr:
            by_review += 1
        sample.append({
            "mac": (o.get("mac") or "")[:24],
            "sn": (o.get("scan_sn") or "")[:24],
            "location_type": o.get("location_type"),
            "source": o.get("source") or "(sem source)",
            "valuation_grade": o.get("valuation_grade"),
            "movement_type": mt,
            "needs_human_review": nhr,
        })

    logger.info("─" * 70)
    logger.info("Por tipo sintético:")
    for k, v in by_type.items():
        logger.info("  %-46s %4d", k, v)
    logger.info("Needs human review: %d", by_review)
    logger.info("─" * 70)
    logger.info("Amostra primeiras 8:")
    for s in sample[:8]:
        logger.info(
            "  mac=%-24s loc=%-9s src=%-20s grade=%s → %s%s",
            s["mac"], s["location_type"], s["source"][:20],
            s["valuation_grade"], s["movement_type"],
            "  ⚠️ REVIEW" if s["needs_human_review"] else "",
        )

    if not apply:
        logger.info("─" * 70)
        logger.info("[DRY-RUN] Nenhuma escrita executada.")
        logger.info("Para aplicar:")
        logger.info("  python -m scripts.backfill_onda2_orphans "
                    "--company %s --apply", company_id)
        return total

    # APPLY
    logger.info("─" * 70)
    logger.info("[APPLY] Iniciando inserções...")
    inserted = 0
    failed = 0
    for o in orphans:
        mt, nhr = classify(o.get("source"))
        try:
            await record_synthetic_backfill(
                company_id=company_id,
                ont=o,
                inferred_movement_type=mt,
                reason_note=(
                    f"Backfill Sprint 3.A — ONT estava ativa em "
                    f"'{o.get('location_type')}' sem trilha canônica em "
                    f"inventory_os_movements_audit. Source inferido: "
                    f"'{o.get('source') or '(vazio)'}'. Inserido sintético "
                    f"em 16/02/2026 por decisão CEO."
                ),
                operator_email=operator_email,
                needs_human_review=nhr,
                inference_signals={
                    "source_raw": o.get("source"),
                    "has_installed_at": bool(o.get("installed_at")),
                    "has_withdrawn_at": bool(o.get("withdrawn_at")),
                    "valuation_grade": o.get("valuation_grade"),
                    "location_type": o.get("location_type"),
                },
            )
            # Marca a ONT pra Watchtower mudar de "Sem Trilha" → "Trilha Sintética"
            await db.stok_onts.update_one(
                {"company_id": company_id, "mac": o.get("mac")},
                {"$set": {
                    "valuation_genesis_via": "synthetic_backfill_onda2",
                    "synthetic_backfill_applied": True,
                    "synthetic_backfill_movement_type": mt,
                    "synthetic_backfill_needs_review": nhr,
                }},
            )
            inserted += 1
        except Exception as e:  # noqa: BLE001
            logger.error("  Falha mac=%s: %s", o.get("mac"), e)
            failed += 1

    logger.info("─" * 70)
    logger.info("[APPLY] Concluído: inserted=%d  failed=%d", inserted, failed)
    logger.info("Synthetic collection total agora:")
    n = await db.inventory_movements_synthetic_backfill.count_documents(
        {"company_id": company_id})
    logger.info("  inventory_movements_synthetic_backfill = %d docs", n)
    logger.info("═" * 70)
    return inserted


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", required=True, help="company_id (ex: co-demo)")
    parser.add_argument("--operator-email", default="cto@ligo.com",
                         help="email do operador para audit trail")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true",
                     help="Apenas relata, não escreve")
    grp.add_argument("--apply", action="store_true",
                     help="Aplica as inserções de fato")
    args = parser.parse_args()
    rc = asyncio.run(main(args.company, args.apply, args.operator_email))
    sys.exit(0)
