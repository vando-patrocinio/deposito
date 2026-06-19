#!/usr/bin/env python3
"""seed_super_admins.py — Cria/atualiza 2 super admins masters em PRODUÇÃO.

Executive Order do CEO (19/02/2026): garantir que vando@ligotelecom.com e
isaac@ligotelecom.com existam como super admin com acesso full no ambiente
de produção (universoligo.com).

USO (em produção, com Emergent Support assistindo):
    cd /app/backend
    python3 scripts/seed_super_admins.py

CARACTERÍSTICAS:
- Idempotente (`upsert=True`) — pode rodar quantas vezes for necessário.
- Bcrypt-hash da senha (nunca grava plaintext).
- Respeita policy `min_length=8` (Ligo696150@@@ = 13, Isaac123456@@@ = 14).
- Marca `last_password_change_at` para passar a janela de rotação 90d.
- Grava `created_by="executive-order-19/02/2026"` para auditoria.
- Validação pós-execução: confirma que ambos existem com is_super_admin=True.

NÃO ROTACIONA AUTOMATICAMENTE — senhas explicitamente definidas pelo CEO.
"""
import asyncio
import sys
import uuid
from datetime import datetime, timezone

# Adiciona o diretório pai (backend) ao path para importar database/auth
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db          # noqa: E402
from auth import hash_password   # noqa: E402


SUPER_ADMINS = [
    {
        "email": "vando@ligotelecom.com",
        "password": "Ligo696150@@@",
        "name": "Vando",
    },
    {
        "email": "isaac@ligotelecom.com",
        "password": "Isaac123456@@@",
        "name": "Isaac",
    },
]


async def main() -> int:
    now_iso = datetime.now(timezone.utc).isoformat()
    results = []

    for u in SUPER_ADMINS:
        existing = await db.users.find_one({"email": u["email"]})
        user_id = existing.get("id") if existing else f"usr-{uuid.uuid4().hex[:12]}"
        doc = {
            "id": user_id,
            "email": u["email"],
            "name": u["name"],
            "password_hash": hash_password(u["password"]),
            "role": "administrador",
            "is_super_admin": True,
            "active": True,
            "must_change_password": False,
            "company_id": "co-demo",
            "created_at": (existing.get("created_at")
                           if existing else now_iso),
            "updated_at": now_iso,
            "last_password_change_at": now_iso,
            "created_by": "executive-order-19/02/2026",
        }
        await db.users.update_one(
            {"email": u["email"]},
            {"$set": doc},
            upsert=True,
        )
        op = "UPDATED" if existing else "CREATED"
        results.append((u["email"], op, user_id))

    print("=" * 60)
    print(" SEED — Super Admins (Production)")
    print("=" * 60)
    for email, op, uid in results:
        print(f"  {op:8} {email:30} id={uid}")

    print()
    print("=== Validação ===")
    ok = 0
    for u in SUPER_ADMINS:
        d = await db.users.find_one(
            {"email": u["email"]},
            {"_id": 0, "email": 1, "role": 1, "is_super_admin": 1, "active": 1},
        )
        if d and d.get("is_super_admin") and d.get("active"):
            print(f"  ✅ {d['email']:30} role={d['role']:14} super=True active=True")
            ok += 1
        else:
            print(f"  ❌ FALHA: {u['email']} — {d}")

    if ok == len(SUPER_ADMINS):
        print()
        print(f"✅ SUCESSO — {ok}/{len(SUPER_ADMINS)} super admins prontos.")
        print("   Pode testar login agora em: https://universoligo.com")
        return 0

    print()
    print(f"❌ FALHA — apenas {ok}/{len(SUPER_ADMINS)} OK.")
    return 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
