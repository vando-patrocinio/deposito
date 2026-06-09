"""
migrate_audit_chain.py — Sprint 7 / pós-auditoria CTO
Hashing retroativo de todos os registros do audit_log que ainda não
têm `hash`/`prev_hash`. Garante 100% de cobertura da hash-chain.

Estratégia:
  1. Lista todos os docs em ordem cronológica (created_at ASC).
  2. Recomputa hash usando `compute_hash(doc, prev_hash)` da
     `services/lgpd_chain.py`.
  3. Faz update_one por id, encadeando o prev_hash do anterior.
  4. NUNCA modifica docs que já têm hash válido na cadeia certa
     (idempotente).

Uso:
    cd /app/backend && python scripts/migrate_audit_chain.py            # dry-run
    cd /app/backend && python scripts/migrate_audit_chain.py --apply
    cd /app/backend && python scripts/migrate_audit_chain.py --apply --rebuild-all
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import db  # noqa: E402
from services.lgpd_chain import compute_hash  # noqa: E402


async def migrate(apply: bool, rebuild_all: bool) -> dict:
    """Rehash registros sem hash ou (se rebuild_all) toda a cadeia."""
    cur = db.audit_log.find({}, sort=[("created_at", 1)])
    total = 0
    needs_fix = 0
    fixed = 0
    chain_breaks = 0
    prev_hash = ""

    async for d in cur:
        total += 1
        recomputed = compute_hash(d, prev_hash)
        current_hash = d.get("hash") or ""
        needs_update = False
        if rebuild_all:
            needs_update = (current_hash != recomputed or
                            d.get("prev_hash") != prev_hash)
        else:
            if not current_hash:
                needs_update = True
            else:
                if current_hash != recomputed:
                    chain_breaks += 1
                # mantém hash existente, mas registramos quebra
        if needs_update:
            needs_fix += 1
            if apply:
                try:
                    await db.audit_log.update_one(
                        {"id": d["id"]},
                        {"$set": {"hash": recomputed,
                                    "prev_hash": prev_hash,
                                    "_rehashed": True}}
                    )
                    fixed += 1
                except Exception as e:  # noqa: BLE001
                    print(f"[ERR] {d.get('id')}: {e}")
        # avança o ponteiro com o NOVO hash (após patch) ou o existente
        # válido (modo conservador)
        prev_hash = recomputed if (rebuild_all or needs_update) \
            else (current_hash or recomputed)

    return {
        "total_docs": total,
        "needed_fix": needs_fix,
        "fixed": fixed,
        "chain_breaks_detected": chain_breaks,
        "applied": apply,
        "rebuild_all": rebuild_all,
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                     help="aplica de fato (default = dry-run)")
    ap.add_argument("--rebuild-all", action="store_true",
                     help="reconstrói a cadeia inteira (use só se "
                          "souber que há tampering anterior)")
    args = ap.parse_args()
    result = await migrate(args.apply, args.rebuild_all)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
