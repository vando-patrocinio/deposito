"""IAM v2 — Authorization core.

Função única: `has_permission(user, permission, [company_id])`.

⚠️  Em modo legacy (USE_NEW_IAM=0), o `iam_v2.auth_compat` faz o shim:
traduz `require_role("gestor")` → `has_permission` usando o mapping
em `permissions_catalog.LEGACY_ROLE_PERMISSIONS`.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

from .models import AuthedUser
from .permissions_catalog import PERMISSIONS

logger = logging.getLogger("iam_v2.authz")


def _matches(permission: str, allowed: str) -> bool:
    """True se a permission requerida bate com a allowed (suporta wildcard)."""
    if allowed == "*":
        return True
    if allowed == permission:
        return True
    if allowed.endswith(".*"):
        prefix = allowed[:-2]
        return permission.startswith(prefix + ".")
    return False


def has_permission(
    user: AuthedUser,
    permission: str,
    company_id: Optional[str] = None,
) -> bool:
    """Única função autorizadora do IAM v2."""

    # 0. Validate permission key (fail-safe)
    if permission != "*" and permission not in PERMISSIONS \
            and not permission.endswith(".*"):
        logger.warning(
            "[authz] permission desconhecida solicitada: %s — bloqueando "
            "por segurança.", permission,
        )
        return False

    # 1. Tenant boundary
    if company_id and user.membership.company_id != company_id:
        return False

    # 2. Membership status
    if user.membership.status != "active":
        return False

    # 3. Identity status
    if user.identity.status != "ativo":
        return False

    # 4. Permission overrides (precedência máxima)
    for ovr in user.membership.permission_overrides:
        if _matches(permission, ovr.permission):
            return ovr.effect == "allow"

    # 5. Profile permissions
    for allowed in user.profile.permissions:
        if _matches(permission, allowed):
            return True

    return False


def has_any(
    user: AuthedUser,
    permissions: Iterable[str],
    company_id: Optional[str] = None,
) -> bool:
    return any(has_permission(user, p, company_id) for p in permissions)


def has_all(
    user: AuthedUser,
    permissions: Iterable[str],
    company_id: Optional[str] = None,
) -> bool:
    return all(has_permission(user, p, company_id) for p in permissions)


# ──────────────────────────────────────────────────────────────────────────
# FastAPI dependencies
# ──────────────────────────────────────────────────────────────────────────

def require_permission(*permissions: str):
    """Dependency: exige PELO MENOS UMA das permissions listadas.

    Uso:
        @router.post("/tickets/{tid}/close")
        async def close(
            tid: str,
            user: AuthedUser = Depends(require_permission("tickets.close")),
        ):
            ...
    """
    from fastapi import Depends, HTTPException

    # Importação local pra evitar ciclo. O get_current_user é setado em
    # iam_v2.bootstrap ao registrar o módulo.
    from .runtime import get_current_user  # noqa

    async def _dep(user: AuthedUser = Depends(get_current_user)) -> AuthedUser:
        if not has_any(user, permissions):
            raise HTTPException(403, {
                "code": "missing_permission",
                "required": list(permissions),
                "user_permissions_count": len(user.profile.permissions),
            })
        return user
    return _dep


def require_all_permissions(*permissions: str):
    """Dependency: exige TODAS as permissions listadas."""
    from fastapi import Depends, HTTPException
    from .runtime import get_current_user  # noqa

    async def _dep(user: AuthedUser = Depends(get_current_user)) -> AuthedUser:
        if not has_all(user, permissions):
            raise HTTPException(403, {
                "code": "missing_permission",
                "required_all": list(permissions),
            })
        return user
    return _dep
