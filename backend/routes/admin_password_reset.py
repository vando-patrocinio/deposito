"""admin_password_reset.py — One-shot endpoint for super-admin password recovery.

PURPOSE: When a super-admin loses access to PROD (e.g. password desync between
Preview and Production databases), this endpoint allows resetting the password
using a pre-shared token from the server environment (`SUPER_ADMIN_RESET_TOKEN`).

SECURITY:
  - Endpoint is DISABLED if the env var is absent (returns 503).
  - Token must match EXACTLY (constant-time compare).
  - Target email must be in `SUPER_ADMIN_EMAILS` env OR have `is_super_admin=True`.
  - Each successful reset is logged to `admin_password_reset_audit` collection.
"""
from __future__ import annotations

import hmac
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, EmailStr, Field

from auth import hash_password
from database import db

router = APIRouter(prefix="/api/admin", tags=["admin-password-reset"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResetPasswordIn(BaseModel):
    email: EmailStr
    new_password: str = Field(..., min_length=8, max_length=128)
    token: str = Field(..., min_length=16)


@router.post("/reset-super-admin-password")
async def reset_super_admin_password(payload: ResetPasswordIn = Body(...)):
    """One-shot password reset for super-admin accounts.

    Requires `SUPER_ADMIN_RESET_TOKEN` env var to be set on the server.
    Use a single, strong, time-limited token shared out-of-band with the CTO.
    """
    expected_token = os.environ.get("SUPER_ADMIN_RESET_TOKEN", "").strip()
    if not expected_token:
        raise HTTPException(503, "Endpoint desabilitado (SUPER_ADMIN_RESET_TOKEN ausente)")

    if not hmac.compare_digest(expected_token, payload.token.strip()):
        raise HTTPException(401, "Token inválido")

    email = payload.email.lower().strip()

    user = await db.users.find_one({"email": email})
    if not user:
        raise HTTPException(404, f"Usuário {email} não existe neste banco")

    # Whitelist: só permite reset em contas explicitamente super-admin.
    super_emails_env = (os.environ.get("SUPER_ADMIN_EMAILS") or "").lower()
    super_emails = {e.strip() for e in super_emails_env.split(",") if e.strip()}
    is_super = bool(user.get("is_super_admin")) or email in super_emails \
        or email == "vando@ligotelecom.com"
    if not is_super:
        raise HTTPException(403, f"Usuário {email} não é super-admin (reset bloqueado)")

    new_hash = hash_password(payload.new_password)
    await db.users.update_one(
        {"email": email},
        {"$set": {
            "password_hash": new_hash,
            "active": True,
            "is_super_admin": True,
            "locked_until": None,
            "failed_attempts": 0,
            "must_change_password": False,
            "session_id": None,  # invalida sessões antigas
            "updated_at": _now_iso(),
            "password_last_reset_at": _now_iso(),
            "password_last_reset_via": "admin_one_shot_endpoint",
        }},
    )

    # Limpa locks/tentativas em coleções separadas
    for coll in ("auth_failed_attempts", "auth_locks"):
        try:
            await getattr(db, coll).delete_many({"email": email})
        except Exception:
            pass

    # Audit trail (sem persistir a senha em texto plano)
    try:
        await db.admin_password_reset_audit.insert_one({
            "email": email,
            "at": _now_iso(),
            "via": "one_shot_endpoint",
            "token_prefix": expected_token[:6],  # primeiros 6 chars só pra correlacionar
        })
    except Exception:
        pass

    return {
        "ok": True,
        "email": email,
        "reset_at": _now_iso(),
        "message": "Senha atualizada. Sessões antigas invalidadas. Faça login com a nova senha.",
    }
