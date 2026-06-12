"""Sistema de Perfis de Acesso (CTO 12/06/2026).

Substitui o modelo `role + access_tags` por `profile` (perfil reutilizável
com conjunto de tags). Cada user/colaborador escolhe 1 profile, que define
automaticamente os módulos acessíveis.

5 perfis seed padrão (criados automaticamente no startup):
  • Colaborador     — acesso operacional básico (técnico, atendente)
  • Gestão          — gestor de área (lousa, frota, cadastro, financeiro)
  • Administrador   — acesso TOTAL (todas as tags)
  • Auditor         — acesso TOTAL (somente leitura por convenção)
  • Super Admin     — acesso TOTAL + único que pode atribuir o próprio
                      perfil Super Admin a outros usuários
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from access_tags import ALL_TAG_KEYS, sanitize_tags
from database import db

logger = logging.getLogger("access_profiles")

# Seed dos 5 perfis padrão
SEED_PROFILES = [
    {
        "key": "colaborador",
        "name": "Colaborador",
        "description": "Acesso operacional básico (técnico, atendente, instalador)",
        "is_seed": True,
        "is_admin_level": False,
        "is_super_admin_profile": False,
        "access_tags": [
            "lousa", "field-ops", "estoque", "cadastro",
        ],
    },
    {
        "key": "gestao",
        "name": "Gestão",
        "description": "Gestor de área — lousa, frota, cadastro, financeiro, vendas",
        "is_seed": True,
        "is_admin_level": False,
        "is_super_admin_profile": False,
        "access_tags": [
            "dashboard", "lousa", "field-ops", "estoque", "projects",
            "central-compras", "contracts", "payments", "site", "balanco",
            "fleet", "fleet-tracking", "projetos", "propostas",
            "atendimento", "mass-messaging", "sales-funnel",
            "cadastro", "clientes", "subscribers", "plans", "pracas",
            "espelho", "sheet", "feriados", "budget", "parcerias",
        ],
    },
    {
        "key": "administrador",
        "name": "Administrador",
        "description": "Acesso TOTAL ao sistema. Pode tudo.",
        "is_seed": True,
        "is_admin_level": True,
        "is_super_admin_profile": False,
        "access_tags": sorted(list(ALL_TAG_KEYS)),
    },
    {
        "key": "auditor",
        "name": "Auditor",
        "description": "Acesso total para auditoria (somente leitura por convenção)",
        "is_seed": True,
        "is_admin_level": True,
        "is_super_admin_profile": False,
        "access_tags": sorted(list(ALL_TAG_KEYS)),
    },
    {
        "key": "super_admin",
        "name": "Super Admin",
        "description": (
            "Acesso TOTAL + privilégio exclusivo de atribuir/revogar "
            "o próprio perfil Super Admin para outros usuários. "
            "Use com extrema cautela."
        ),
        "is_seed": True,
        "is_admin_level": True,
        "is_super_admin_profile": True,
        "access_tags": sorted(list(ALL_TAG_KEYS)),
    },
]


async def seed_default_profiles(company_id: str) -> dict:
    """Cria os perfis padrão no tenant se ainda não existirem (idempotente).

    Também atualiza o flag `is_super_admin_profile` em seeds já existentes
    para manter o estado consistente após upgrade da feature.
    """
    created = 0
    skipped = 0
    patched = 0
    for p in SEED_PROFILES:
        existing = await db.access_profiles.find_one(
            {"company_id": company_id, "key": p["key"]},
            {"_id": 0, "id": 1, "is_super_admin_profile": 1, "is_admin_level": 1},
        )
        if existing:
            skipped += 1
            # Garante que o flag is_super_admin_profile esteja correto em seeds antigos.
            patch: dict = {}
            if existing.get("is_super_admin_profile") != p["is_super_admin_profile"]:
                patch["is_super_admin_profile"] = p["is_super_admin_profile"]
            if existing.get("is_admin_level") != p["is_admin_level"]:
                patch["is_admin_level"] = p["is_admin_level"]
            if patch:
                await db.access_profiles.update_one(
                    {"company_id": company_id, "key": p["key"]},
                    {"$set": patch},
                )
                patched += 1
            continue
        doc = {
            "id": f"prof-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "key": p["key"],
            "name": p["name"],
            "description": p["description"],
            "is_seed": True,
            "is_admin_level": p["is_admin_level"],
            "is_super_admin_profile": p["is_super_admin_profile"],
            "access_tags": sanitize_tags(p["access_tags"]),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": "seed",
            "user_count_cache": 0,
        }
        await db.access_profiles.insert_one(doc)
        created += 1
    return {
        "company_id": company_id,
        "created": created,
        "skipped": skipped,
        "patched": patched,
    }


async def get_profile(profile_id: str, company_id: str) -> Optional[dict]:
    return await db.access_profiles.find_one(
        {"id": profile_id, "company_id": company_id},
        {"_id": 0},
    )


async def get_profile_by_key(key: str, company_id: str) -> Optional[dict]:
    return await db.access_profiles.find_one(
        {"key": key, "company_id": company_id},
        {"_id": 0},
    )


async def list_profiles(company_id: str) -> List[dict]:
    docs = await db.access_profiles.find(
        {"company_id": company_id},
        {"_id": 0},
    ).sort([("is_seed", -1), ("name", 1)]).to_list(200)
    # Cache count de users por profile
    for p in docs:
        n = await db.users.count_documents({
            "company_id": company_id, "profile_id": p["id"],
        })
        p["user_count"] = n
    return docs


async def create_profile(
    company_id: str, name: str, access_tags: List[str],
    description: Optional[str] = None,
    created_by: str = "?",
) -> dict:
    key = name.lower().strip().replace(" ", "_")[:30]
    if await db.access_profiles.find_one({"company_id": company_id, "key": key}):
        raise ValueError(f"Já existe perfil com key '{key}'")
    doc = {
        "id": f"prof-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "key": key,
        "name": name,
        "description": description,
        "is_seed": False,
        "is_admin_level": False,
        "access_tags": sanitize_tags(access_tags),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": created_by,
        "user_count_cache": 0,
    }
    await db.access_profiles.insert_one(doc)
    return doc


async def update_profile(
    profile_id: str, company_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    access_tags: Optional[List[str]] = None,
    updated_by: str = "?",
) -> dict:
    p = await get_profile(profile_id, company_id)
    if not p:
        raise ValueError("Perfil não encontrado")
    if p.get("is_seed") and access_tags is not None:
        # SEED é mutável (gestor pode customizar tags), mas avisa
        logger.info("[profiles] alterando tags do perfil seed %s", p["key"])
    update: dict = {"updated_at": datetime.now(timezone.utc).isoformat(),
                     "updated_by": updated_by}
    if name:
        update["name"] = name
    if description is not None:
        update["description"] = description
    if access_tags is not None:
        update["access_tags"] = sanitize_tags(access_tags)
    await db.access_profiles.update_one(
        {"id": profile_id, "company_id": company_id},
        {"$set": update},
    )
    return await get_profile(profile_id, company_id)


async def delete_profile(profile_id: str, company_id: str) -> dict:
    p = await get_profile(profile_id, company_id)
    if not p:
        raise ValueError("Perfil não encontrado")
    if p.get("is_seed"):
        raise ValueError("Perfis padrão (seed) não podem ser excluídos")
    # Verifica se algum user usa
    n = await db.users.count_documents(
        {"company_id": company_id, "profile_id": profile_id},
    )
    if n > 0:
        raise ValueError(
            f"{n} usuário(s) vinculado(s) a este perfil. "
            "Mude o perfil deles antes de excluir."
        )
    await db.access_profiles.delete_one(
        {"id": profile_id, "company_id": company_id},
    )
    return {"deleted": True, "id": profile_id}


async def seed_all_tenants() -> dict:
    """Seed em TODOS os tenants existentes (startup hook)."""
    tenants = await db.users.distinct("company_id")
    summary = {"tenants": 0, "created_total": 0}
    for cid in tenants:
        if not cid:
            continue
        r = await seed_default_profiles(cid)
        summary["tenants"] += 1
        summary["created_total"] += r["created"]
    return summary


async def user_has_super_admin_profile(user: dict) -> bool:
    """Verifica se o usuário está vinculado ao perfil seed 'Super Admin'.

    Independente do flag legado `users.is_super_admin` (controlado pelo
    grantor hardcoded). Esta função é usada para autorizar a ATRIBUIÇÃO
    do perfil Super Admin a outros usuários.
    """
    if not user:
        return False
    pid = user.get("profile_id")
    if not pid:
        return False
    cid = user.get("company_id")
    if not cid:
        return False
    p = await db.access_profiles.find_one(
        {"id": pid, "company_id": cid},
        {"_id": 0, "is_super_admin_profile": 1, "key": 1},
    )
    if not p:
        return False
    return bool(p.get("is_super_admin_profile")) or p.get("key") == "super_admin"


async def is_super_admin_profile_id(profile_id: str, company_id: str) -> bool:
    """True se o profile_id referido é o seed Super Admin do tenant."""
    if not profile_id or not company_id:
        return False
    p = await db.access_profiles.find_one(
        {"id": profile_id, "company_id": company_id},
        {"_id": 0, "is_super_admin_profile": 1, "key": 1},
    )
    if not p:
        return False
    return bool(p.get("is_super_admin_profile")) or p.get("key") == "super_admin"
