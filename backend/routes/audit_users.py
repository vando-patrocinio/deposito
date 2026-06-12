"""Auditoria de usuários × colaboradores × tags (CTO 12/06/2026).

Endpoints:
  GET  /api/audit/users-collaborators  → mapa de zumbis, vínculos inválidos
  POST /api/audit/cleanup-zombie-users → desativa zumbis (active=False)
  POST /api/audit/backfill-collaborator-codes → atribui LIGO-NNNN
  GET  /api/audit/access-tags-by-user → per-user tag analysis (explícitas
                                          vs herdadas vs divergentes)
"""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import (
    DEMO_COMPANY_ID,
    is_super_admin,
    now_iso,
    require_role,
)
from database import db
from access_tags import DEFAULT_TAGS_BY_ROLE, effective_tags
from services.collaborator_code import backfill_all as _backfill_codes

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/audit", tags=["audit"])


# Usuários que PODEM existir sem colaborador (whitelist de serviço)
SERVICE_USER_WHITELIST = {
    "admin@empresa.com",       # super admin operacional
    "isabella@ia.local",       # IA Isabella (não-humano)
}


# Zumbis óbvios (placeholders dev) — alvo da cleanup automática
KNOWN_ZOMBIE_EMAILS = {
    "admin@example.com",
    "auditor@example.com",
    "vando@example.com",
    "gestor@example.com",
    "gestor@empresa.com",
    "gestorrede@empresa.com",
    "test_gestor_iter72@empresa.com",
}


@router.get("/users-collaborators")
async def audit_users_collaborators(user: dict = Depends(require_role("auditor"))):
    """Mapa do estado de saúde da relação usuário↔colaborador no tenant."""
    cid = user.get("company_id") or DEMO_COMPANY_ID

    users = await db.users.find(
        {"company_id": cid},
        {"_id": 0, "password_hash": 0},
    ).to_list(2000)

    cols = await db.collaborators.find(
        {"company_id": cid},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "active": 1,
         "role": 1, "cargo": 1, "code": 1},
    ).to_list(5000)

    by_col_id = {c["id"]: c for c in cols}
    cols_active_with_user: set[str] = set()

    zombies: List[dict] = []        # users sem collaborator
    invalid_links: List[dict] = []  # users com collaborator_id inexistente/inativo
    duplicates: List[dict] = []     # 2+ users com mesmo collaborator_id

    by_col_user_count: dict[str, list[dict]] = {}
    for u in users:
        col_id = u.get("collaborator_id")
        if col_id:
            by_col_user_count.setdefault(col_id, []).append(u)
            cols_active_with_user.add(col_id)

    for col_id, ulist in by_col_user_count.items():
        if len(ulist) > 1:
            duplicates.append({
                "collaborator_id": col_id,
                "collaborator_name": (by_col_id.get(col_id) or {}).get("name"),
                "users": [{"email": x["email"], "name": x.get("name"),
                            "active": x.get("active")} for x in ulist],
            })

    for u in users:
        col_id = u.get("collaborator_id")
        if not col_id:
            email = u.get("email") or ""
            zombies.append({
                "id": u.get("id"),
                "email": email,
                "name": u.get("name"),
                "role": u.get("role"),
                "active": u.get("active"),
                "is_whitelisted": email in SERVICE_USER_WHITELIST,
                "is_known_zombie": email in KNOWN_ZOMBIE_EMAILS,
                "last_login_at": u.get("last_login_at"),
            })
            continue
        c = by_col_id.get(col_id)
        if not c:
            invalid_links.append({
                "user_email": u.get("email"),
                "collaborator_id": col_id,
                "reason": "collaborator inexistente neste tenant",
            })
        elif not c.get("active"):
            invalid_links.append({
                "user_email": u.get("email"),
                "collaborator_id": col_id,
                "collaborator_name": c.get("name"),
                "reason": "collaborator inativo",
            })

    # Colaboradores ativos com email mas sem usuário (potenciais)
    candidates: List[dict] = []
    for c in cols:
        if not c.get("active"):
            continue
        if c["id"] in cols_active_with_user:
            continue
        if not c.get("email"):
            continue
        candidates.append({
            "collaborator_id": c["id"],
            "code": c.get("code"),
            "name": c.get("name"),
            "email": c.get("email"),
            "role": c.get("role") or c.get("cargo"),
        })

    # Colaboradores ativos sem code (precisam backfill)
    no_code = sum(1 for c in cols if c.get("active") and not c.get("code"))

    return {
        "company_id": cid,
        "total_users": len(users),
        "total_collaborators": len(cols),
        "zombies": zombies,
        "zombies_count": len(zombies),
        "invalid_links": invalid_links,
        "invalid_links_count": len(invalid_links),
        "duplicates": duplicates,
        "duplicates_count": len(duplicates),
        "potential_user_candidates": candidates,
        "potential_user_candidates_count": len(candidates),
        "collaborators_without_code": no_code,
        "service_user_whitelist": sorted(SERVICE_USER_WHITELIST),
        "known_zombie_emails": sorted(KNOWN_ZOMBIE_EMAILS),
        "audited_at": now_iso(),
    }


class CleanupReq(BaseModel):
    deactivate: bool = True   # default: desativa, não deleta
    dry_run: bool = False
    extra_emails: List[str] = []   # emails adicionais a tratar como zumbi


@router.post("/cleanup-zombie-users")
async def cleanup_zombie_users(payload: CleanupReq,
                                  user: dict = Depends(require_role("auditor"))):
    """Desativa (active=False) usuários SEM collaborator_id que não estejam
    na whitelist. Por segurança, NÃO deleta. Idempotente."""
    cid = user.get("company_id") or DEMO_COMPANY_ID

    targets_emails = set(KNOWN_ZOMBIE_EMAILS) | {
        e.lower().strip() for e in payload.extra_emails
    }
    # Remove whitelist por segurança
    targets_emails -= SERVICE_USER_WHITELIST

    # Conjunto final: users sem col_id, ativos, em targets_emails
    cursor = db.users.find(
        {"company_id": cid, "email": {"$in": list(targets_emails)}},
        {"_id": 0, "id": 1, "email": 1, "name": 1, "active": 1,
         "collaborator_id": 1},
    )
    found: List[dict] = []
    async for u in cursor:
        if u.get("collaborator_id"):
            continue   # não mexe em users com vínculo
        if u.get("email") in SERVICE_USER_WHITELIST:
            continue
        found.append(u)

    if payload.dry_run:
        return {"dry_run": True, "would_deactivate": found,
                "count": len(found)}

    deactivated: List[dict] = []
    for u in found:
        if u.get("active") is False:
            continue
        r = await db.users.update_one(
            {"id": u["id"], "company_id": cid},
            {"$set": {"active": False,
                       "deactivated_at": now_iso(),
                       "deactivated_by": user.get("email"),
                       "deactivated_reason": "zombie_cleanup_cto_audit"}},
        )
        if r.modified_count > 0:
            deactivated.append(u)
    return {
        "deactivated": deactivated,
        "deactivated_count": len(deactivated),
        "scanned": len(found),
        "performed_by": user.get("email"),
        "ran_at": now_iso(),
    }


@router.post("/backfill-collaborator-codes")
async def backfill_collaborator_codes(
    user: dict = Depends(require_role("auditor")),
):
    """Atribui código LIGO-NNNN a todos os colaboradores sem code (idempotente)."""
    cid = None if is_super_admin(user) else user.get("company_id")
    summary = await _backfill_codes(cid)
    return {**summary, "performed_by": user.get("email"), "ran_at": now_iso()}


@router.get("/access-tags-by-user")
async def audit_access_tags_by_user(
    user: dict = Depends(require_role("auditor")),
):
    """Per-user audit: tags explícitas vs herdadas do papel vs divergências."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    users = await db.users.find(
        {"company_id": cid},
        {"_id": 0, "id": 1, "email": 1, "name": 1, "role": 1,
         "access_tags": 1, "active": 1, "collaborator_id": 1},
    ).to_list(2000)

    summary = {"total": len(users), "uses_default": 0, "custom": 0,
                "empty_role_default": 0}
    rows = []
    for u in users:
        explicit = list(u.get("access_tags") or [])
        role_default = list(DEFAULT_TAGS_BY_ROLE.get(u.get("role") or "", []))
        effective = effective_tags(u)
        added = sorted(set(explicit) - set(role_default))
        removed = sorted(set(role_default) - set(explicit)) if explicit else []
        is_default = (not explicit) or (sorted(explicit) == sorted(role_default))
        if is_default:
            summary["uses_default"] += 1
        else:
            summary["custom"] += 1
        if not role_default:
            summary["empty_role_default"] += 1
        rows.append({
            "id": u.get("id"),
            "email": u.get("email"),
            "name": u.get("name"),
            "role": u.get("role"),
            "active": u.get("active"),
            "explicit_count": len(explicit),
            "role_default_count": len(role_default),
            "effective_count": len(effective),
            "uses_role_default": is_default,
            "tags_added_to_role": added,
            "tags_removed_from_role": removed,
        })
    return {"summary": summary, "users": rows, "audited_at": now_iso()}
