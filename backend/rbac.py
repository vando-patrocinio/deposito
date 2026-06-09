"""
rbac.py — Sprint 1 Blindagem de Produção (iter220)

Centraliza:
  • require_roles(...) — dependência FastAPI para validar perfis
  • mock_guard(name) — bloqueia módulos mockados quando ALLOW_MOCK_MODULES=false
  • audit_log(...) — registro de eventos sensíveis em `audit_log`
  • rate_limit(...) — controle por usuário, empresa, por minuto e por dia

Roles válidos: administrador | gestor | financeiro | tecnico |
                atendimento | auditor | colaborador
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request, status

from core import get_current_user

logger = logging.getLogger(__name__)

VALID_ROLES = {"administrador", "gestor", "financeiro",
                 "tecnico", "atendimento", "auditor", "colaborador"}

FORBIDDEN_MSG = (
    "Você não tem permissão para acessar este recurso.")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────── require_roles ───────────────────
def require_roles(*roles: str):
    """Dependência FastAPI que valida o perfil do usuário.

    Uso:
        @router.get("/x", dependencies=[Depends(require_roles("administrador", "financeiro"))])
        async def x(...): ...

    OU como dependency com user injetado:
        async def x(user = Depends(require_roles("admin"))): ...
    """
    allowed = set(roles) or {"administrador"}
    invalid = allowed - VALID_ROLES
    if invalid:
        raise ValueError(f"Roles inválidos: {invalid}")

    async def _dep(user: Dict[str, Any] = Depends(get_current_user)
                   ) -> Dict[str, Any]:
        # administrador SEMPRE passa (super-role)
        role = (user or {}).get("role") or "colaborador"
        is_super = bool((user or {}).get("is_super_admin"))
        if is_super or role == "administrador" or role in allowed:
            return user
        raise HTTPException(status.HTTP_403_FORBIDDEN, FORBIDDEN_MSG)

    return _dep


# ─────────────────── Mock guard ───────────────────
def _allow_mock() -> bool:
    """Lê ALLOW_MOCK_MODULES — padrão True em preview, False em prod.

    Convenções aceitas: "true"/"1"/"yes" → libera mocks.
    """
    v = (os.environ.get("ALLOW_MOCK_MODULES") or "true").strip().lower()
    return v in ("1", "true", "yes", "y", "on")


def mock_guard(module_name: str):
    """Dependência que bloqueia o endpoint se ALLOW_MOCK_MODULES=false."""
    async def _dep():
        if _allow_mock():
            return True
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Módulo em implantação. Não disponível em produção.")
    return _dep


# ─────────────────── Audit log ───────────────────
async def audit_log(user: Dict[str, Any], category: str, action: str,
                       target: str = "", data: Optional[Dict[str, Any]] = None,
                       ) -> None:
    """Grava em `audit_log` via hash-chain (best-effort, nunca falha
    o request). Pós-CTO audit: sempre via lgpd_chain para garantir
    integridade criptográfica."""
    try:
        from services.lgpd_chain import insert_audit_event
        await insert_audit_event({
            "id": f"aud-{uuid.uuid4().hex[:14]}",
            "company_id": (user or {}).get("company_id"),
            "user_id": (user or {}).get("id"),
            "user_email": (user or {}).get("email"),
            "user_role": (user or {}).get("role"),
            "category": category,
            "action": action,
            "target": target,
            "data": data or {},
            "created_at": _now_iso(),
        })
    except Exception as e:
        logger.warning("[audit] falha em audit_log: %s", e)


# ─────────────────── Rate limit ───────────────────
# Janela: contadores em memória local (best-effort).
_minute_buckets: Dict[str, list] = {}
_day_buckets: Dict[str, int] = {}
_day_reset_at: float = time.time()


def _maybe_reset_daily() -> None:
    global _day_reset_at, _day_buckets
    now = time.time()
    if now - _day_reset_at >= 86400:
        _day_buckets = {}
        _day_reset_at = now


def rate_limit(per_minute: int = 30, per_day: int = 1000,
                  scope: str = "ia"):
    """Limita chamadas. Scope identifica grupo (ex.: 'ia', 'reports').
    Limites por usuário E por empresa simultaneamente.
    """
    async def _dep(request: Request,
                     user: Dict[str, Any] = Depends(get_current_user)
                     ) -> Dict[str, Any]:
        _maybe_reset_daily()
        uid = (user or {}).get("id") or "anon"
        cid = (user or {}).get("company_id") or "anon"
        now = time.time()
        for key, limit_min, limit_day in (
            (f"{scope}:u:{uid}", per_minute, per_day),
            (f"{scope}:c:{cid}",
                 per_minute * 5, per_day * 5),  # empresa = 5x usuário
        ):
            arr = _minute_buckets.setdefault(key, [])
            # purge >60s
            i = 0
            while i < len(arr) and now - arr[i] > 60:
                i += 1
            if i:
                del arr[:i]
            if len(arr) >= limit_min:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    f"Limite excedido ({limit_min}/min) — tente em instantes")
            day_n = _day_buckets.get(key, 0)
            if day_n >= limit_day:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    f"Limite diário excedido ({limit_day}/dia)")
            arr.append(now)
            _day_buckets[key] = day_n + 1
        return user
    return _dep


# Atalhos prontos pra cada categoria
def require_admin():
    return require_roles("administrador")


def require_admin_or_gestor():
    return require_roles("administrador", "gestor")


def require_finance():
    return require_roles("administrador", "gestor", "financeiro", "auditor")


def require_ai_access():
    return require_roles("administrador", "gestor", "auditor")
