"""CTO 13/06/2026 — Password Recovery (modo simples autorizado opção A).

Fluxo (autorizado pelo CTO em 13/06/2026, substitui fluxo OTP/WhatsApp anterior):
1. User clica "Esqueci a senha" → POST /api/auth/forgot-password {email}
2. Backend:
   - Lookup user pelo e-mail (case-insensitive)
   - Se existir e estiver ativo → reseta password_hash para "123456"
   - Seta password_reset_pending=True → força troca no próximo login
   - Responde com mensagem direta confirmando o reset
3. User loga com 123456 → API retorna must_change_password=true
4. Frontend força modal de troca de senha antes de liberar o app
5. POST /api/auth/change-password-forced limpa o flag

⚠️ DECISÃO CTO: simplicidade total — qualquer usuário (inclusive super admin)
pode resetar via esse fluxo. Risco aceito pelo CTO em 13/06/2026.

Rate limit: 5 tentativas/hora por email/IP (Mongo collection
password_reset_attempts) — única proteção contra abuso.
Audit log: db.audit_log_password_resets.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import HTTPException

from auth import hash_password
from database import db

logger = logging.getLogger("password_recovery")

# Senha de reset fixa (autorizada pelo CTO opção A em 13/06/2026)
DEFAULT_RESET_PASSWORD = "123456"
RATE_LIMIT_PER_HOUR = 5


async def _check_rate_limit(email: str, ip: str) -> None:
    """Permite max N requests/hora por email OU ip. Lança 429 se excedido."""
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    cutoff = one_hour_ago.isoformat()
    count_email = await db.password_reset_attempts.count_documents({
        "email": email,
        "created_at": {"$gte": cutoff},
    })
    count_ip = await db.password_reset_attempts.count_documents({
        "ip": ip,
        "created_at": {"$gte": cutoff},
    })
    if count_email >= RATE_LIMIT_PER_HOUR or count_ip >= RATE_LIMIT_PER_HOUR:
        raise HTTPException(
            429,
            "Muitas tentativas de recuperação. Aguarde 1 hora ou procure "
            "o auditor.",
        )


async def _audit(
    email: str, ip: str, user_id: Optional[str], outcome: str,
    reason: Optional[str] = None,
) -> None:
    """Grava no audit log."""
    try:
        await db.audit_log_password_resets.insert_one({
            "email": email,
            "ip": ip,
            "user_id": user_id,
            "outcome": outcome,
            "reason": reason,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:  # noqa: BLE001
        logger.warning("[pwd-recovery] audit log falhou: %s", e)


async def forgot_password_flow(email: str, ip: str) -> dict:
    """Reseta a senha do usuário para `123456` (modo simples opção A).

    - 200 com mensagem confirmando o reset se o usuário existir e estiver ativo.
    - 200 genérico se o usuário não existir (anti-enumeração).
    - 429 se rate limit excedido.
    """
    email = (email or "").lower().strip()
    if not email or "@" not in email:
        return _generic_response()

    await _check_rate_limit(email, ip)

    # Registra tentativa
    await db.password_reset_attempts.insert_one({
        "email": email,
        "ip": ip,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    user = await db.users.find_one(
        {"email": email},
        {"_id": 0, "id": 1, "email": 1, "active": 1, "name": 1},
    )
    if not user:
        await _audit(email, ip, None, "no_such_user")
        return _generic_response()

    if not user.get("active", True):
        await _audit(email, ip, user["id"], "user_inactive")
        return _generic_response()

    # Reset direto para 123456 + força troca no próximo login
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "password_hash": hash_password(DEFAULT_RESET_PASSWORD),
            "password_reset_pending": True,
            "password_reset_at": datetime.now(timezone.utc).isoformat(),
            "locked_until": None,
            "failed_attempts": 0,
            "session_id": None,  # invalida sessões antigas
        }},
    )
    # Limpa locks de brute-force em coleções separadas
    for coll in ("auth_failed_attempts", "auth_locks"):
        try:
            await getattr(db, coll).delete_many({"email": email})
        except Exception:
            pass

    await _audit(email, ip, user["id"], "success_reset_to_default")

    return {
        "ok": True,
        "reset": True,
        "message": (
            f"Sua senha foi redefinida para *{DEFAULT_RESET_PASSWORD}*. "
            "Faça login e você será obrigado a escolher uma nova senha."
        ),
    }


def _generic_response() -> dict:
    """Resposta genérica anti-enumeração (sempre 200 OK)."""
    return {
        "ok": True,
        "reset": False,
        "message": (
            "Se a conta existir, a senha foi redefinida para 123456. "
            "Faça login e você será obrigado a trocar a senha."
        ),
    }


async def consume_password_reset_pending(user_id: str, new_password: str
                                            ) -> None:
    """Após login forçado, troca senha e limpa o flag."""
    if not new_password or len(new_password) < 6:
        raise HTTPException(400, "Senha precisa ter pelo menos 6 caracteres")
    await db.users.update_one(
        {"id": user_id},
        {"$set": {
            "password_hash": hash_password(new_password),
            "password_reset_pending": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, "$unset": {"password_reset_at": ""}},
    )
