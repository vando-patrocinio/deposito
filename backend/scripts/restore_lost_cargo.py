"""
restore_lost_cargo.py — CTO P0 11/06/2026

Restaura `cargo` em colaboradores que perderam o valor por causa do bug do
PUT incompleto no toggle "Bate ponto" (corrigido em 11/06/2026).

Critério: cargo None/vazio E `role` herdado contém uma palavra-chave conhecida.

Idempotente. Pode rodar em produção logo após o redeploy.

Uso:
    python3 backend/scripts/restore_lost_cargo.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")

from database import db

ROLE_KEYWORDS = [
    ("atendente", "atendente"),
    ("reparador", "reparador"),
    ("instalador", "instalador"),
    ("associado", "associado"),
    ("almoxarife", "almoxarife"),
    ("auxiliar", "auxiliar_administrativo"),
    ("tecnico", "tecnico"),  # checagem mais flexível: "tecnico" / "técnico" normalizado
    ("técnico", "tecnico"),
]


async def main():
    now = datetime.now(timezone.utc).isoformat()
    q = {"$or": [{"cargo": None}, {"cargo": ""}, {"cargo": {"$exists": False}}]}
    affected = []
    async for c in db.collaborators.find(
        q, {"_id": 0, "id": 1, "name": 1, "role": 1, "company_id": 1}
    ):
        role_norm = (c.get("role") or "").lower().replace("é", "e")
        # admin sem ser "administra" → auxiliar_administrativo
        if "admin" in role_norm and "administra" not in role_norm:
            c["__cargo"] = "auxiliar_administrativo"
            affected.append(c)
            continue
        for kw, cargo in ROLE_KEYWORDS:
            if kw in role_norm:
                c["__cargo"] = cargo
                affected.append(c)
                break

    print(f"Colaboradores com cargo perdido: {len(affected)}")
    by_cargo = {}
    for c in affected:
        by_cargo.setdefault(c["__cargo"], []).append(c.get("name"))
    for cargo, names in by_cargo.items():
        print(f"  {cargo}: {len(names)}")
        for n in names[:5]:
            print(f"    - {n}")
        if len(names) > 5:
            print(f"    ... +{len(names)-5}")

    fixed = 0
    for c in affected:
        await db.collaborators.update_one(
            {"id": c["id"]},
            {"$set": {
                "cargo": c["__cargo"],
                "updated_at": now,
                "updated_by": "cargo_restore_script",
            }},
        )
        fixed += 1
    print(f"\n✓ Restaurados: {fixed}")


if __name__ == "__main__":
    asyncio.run(main())
