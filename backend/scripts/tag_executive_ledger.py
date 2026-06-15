"""Tag DUAL idempotente nos registros sintéticos do executive_ledger.

Etapa 3 — Ligo Executive OS · Consolidation (15/06/2026).

Marca cada doc cujo `company_id ∈ SYNTHETIC_TENANTS` com:
- `synthetic_detected=True` (filtro padrão dos endpoints executivos)
- `pre_sanitize_2026_06_14=True` (marcador histórico)
- `_tagged_at` / `_tagged_by` (auditoria + rollback)

Reversível via `--rollback` (remove os 4 campos sem tocar o resto).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
from database import db  # noqa: E402
from constants.synthetic_tenants import SYNTHETIC_TENANTS  # noqa: E402


async def tag() -> None:
    now = datetime.now(timezone.utc).isoformat()
    res = await db.executive_ledger.update_many(
        {"company_id": {"$in": SYNTHETIC_TENANTS}},
        {"$set": {
            "synthetic_detected": True,
            "pre_sanitize_2026_06_14": True,
            "_tagged_at": now,
            "_tagged_by": "fase_a_etapa3_sanitize",
        }}
    )
    print(f"[TAG] matched={res.matched_count} modified={res.modified_count}")

    syn_tag = await db.executive_ledger.count_documents(
        {"synthetic_detected": True})
    real = await db.executive_ledger.count_documents(
        {"$or": [{"synthetic_detected": {"$ne": True}},
                  {"synthetic_detected": {"$exists": False}}]})
    print(f"[CHECK] synthetic_detected=true: {syn_tag} · "
          f"reais (filtro padrão): {real}")


async def rollback() -> None:
    res = await db.executive_ledger.update_many(
        {"_tagged_by": "fase_a_etapa3_sanitize"},
        {"$unset": {
            "synthetic_detected": "",
            "pre_sanitize_2026_06_14": "",
            "_tagged_at": "",
            "_tagged_by": "",
        }}
    )
    print(f"[ROLLBACK] matched={res.matched_count} modified={res.modified_count}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollback", action="store_true",
                        help="Remove as tags aplicadas pelo modo padrão.")
    args = parser.parse_args()
    if args.rollback:
        await rollback()
    else:
        await tag()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
