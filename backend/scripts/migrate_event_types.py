"""
migrate_event_types.py — Pós-CTO audit P1
Padroniza os 54 docs legados em `motor_ia_events` que foram inseridos
direto pela versão antiga de `scan_security_alerts` (campo `type` em
vez de `event_type`, sem `correlation_id`, sem `company_id` formal).

Estratégia:
  1. Lê docs com event_type ausente.
  2. Mapeia legacy.type ('mass_export','mass_delete','rbac_abuse',
     'impersonate','security_alert') → EventType formal.
  3. Adiciona correlation_id quando ausente.
  4. Para legacy.scope (user_id), tenta resolver company_id em users.

Uso:
    cd /app/backend && python scripts/migrate_event_types.py            # dry-run
    cd /app/backend && python scripts/migrate_event_types.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import db  # noqa: E402


TYPE_MAP = {
    "mass_export": "AUDIT_EXPORT",
    "mass_delete": "AUDIT_DELETE",
    "rbac_abuse": "RBAC_DENIED",
    "impersonate": "IMPERSONATE",
    "security_alert": "RBAC_DENIED",
}


async def migrate(apply: bool) -> dict:
    cur = db.motor_ia_events.find(
        {"$or": [{"event_type": None},
                 {"event_type": {"$exists": False}}]})
    n = 0
    fixed = 0
    async for d in cur:
        n += 1
        legacy_type = d.get("type") or d.get("category") or "security_alert"
        new_event_type = TYPE_MAP.get(legacy_type, "RBAC_DENIED")
        updates = {"event_type": new_event_type,
                   "_migrated_legacy_type": legacy_type}
        if not d.get("correlation_id"):
            updates["correlation_id"] = f"corr-{uuid.uuid4().hex[:14]}"
        if not d.get("source"):
            updates["source"] = "audit_alerts_legacy"
        if not d.get("payload"):
            updates["payload"] = {
                "title": d.get("title"),
                "message": d.get("message"),
                "evidence": d.get("evidence"),
                "scope": d.get("scope"),
                "detector": legacy_type,
            }
        if not d.get("timestamp") and d.get("created_at"):
            updates["timestamp"] = d["created_at"]
        # tenta resolver company_id pelo escopo (user_id)
        if not d.get("company_id") and d.get("scope"):
            try:
                u = await db.users.find_one(
                    {"id": d["scope"]}, {"company_id": 1})
                if u and u.get("company_id"):
                    updates["company_id"] = u["company_id"]
            except Exception:
                pass
        if apply:
            try:
                await db.motor_ia_events.update_one(
                    {"_id": d["_id"]}, {"$set": updates})
                fixed += 1
            except Exception:
                pass
        else:
            fixed += 1
    return {"scanned": n, "would_fix" if not apply else "fixed": fixed,
            "applied": apply}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    print(await migrate(args.apply))


if __name__ == "__main__":
    asyncio.run(main())
