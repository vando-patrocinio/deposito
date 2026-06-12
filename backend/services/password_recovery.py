"""CTO 12/06/2026 — Password Recovery via WhatsApp.

Fluxo (autorizado opção A pelo CTO):
1. User clica "Esqueci a senha" → POST /api/auth/forgot-password {email}
2. Backend:
   - Lookup user; se órfão (sem collaborator_id) → erro genérico (não vaza)
   - Lookup colaborador → pega phone
   - Se Super Admin → bloqueia (segurança)
   - Gera senha aleatória 8 chars (alphanumeric sem ambíguos)
   - Salva hash + flag password_reset_pending=True
   - Envia plaintext via WhatsApp para o phone do colaborador
3. User loga com nova senha → API retorna must_change_password=true
4. Frontend força modal de troca de senha antes do uso
5. POST /api/auth/change-password-forced limpa o flag

Rate limit: 3 tentativas/hora por email (Mongo collection password_reset_attempts).
Audit log: db.audit_log_password_resets.
"""
from __future__ import annotations

import logging
import secrets
import string
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import HTTPException

from auth import hash_password
from database import db

logger = logging.getLogger("password_recovery")

# Alphabet sem caracteres ambíguos (sem 0/O/1/l/I)
PASSWORD_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789abcdefghjkmnpqrstuvwxyz"
RATE_LIMIT_PER_HOUR = 3


def _generate_password(length: int = 8) -> str:
    """Gera senha aleatória cryptographically secure."""
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def _normalize_phone(phone: str) -> Optional[str]:
    """Normaliza phone para formato Baileys (apenas dígitos com DDI BR=55)."""
    if not phone:
        return None
    digits = "".join(c for c in str(phone) if c.isdigit())
    if not digits:
        return None
    # Se não começa com 55, adiciona DDI Brasil
    if not digits.startswith("55"):
        digits = "55" + digits
    if len(digits) < 12:  # 55 + DDD(2) + número(8min)
        return None
    return digits


async def _check_rate_limit(email: str, ip: str) -> None:
    """Permite max 3 requests/hora por email OU ip. Lança 429 se excedido."""
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
    """Executa o fluxo completo. Sempre retorna 200 genérico (anti-enum).

    Casos que disparam erro real:
    - 429 rate limit excedido
    """
    email = (email or "").lower().strip()
    if not email or "@" not in email:
        # Não vaza: retorna OK genérico
        return _generic_response()

    await _check_rate_limit(email, ip)

    # Registra tentativa (mesmo se user não existir, pra evitar enum por timing)
    attempt_doc = {
        "email": email,
        "ip": ip,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.password_reset_attempts.insert_one(attempt_doc)

    user = await db.users.find_one(
        {"email": email},
        {"_id": 0, "id": 1, "email": 1, "company_id": 1, "collaborator_id": 1,
         "is_super_admin": 1, "profile_id": 1, "active": 1, "name": 1},
    )
    if not user:
        await _audit(email, ip, None, "no_such_user")
        return _generic_response()

    if not user.get("active", True):
        await _audit(email, ip, user["id"], "user_inactive")
        return _generic_response()

    # Bloqueia Super Admin (não pode resetar via WhatsApp)
    if user.get("is_super_admin"):
        await _audit(email, ip, user["id"], "blocked_super_admin_flag")
        return _generic_response()

    # Bloqueia se perfil for Super Admin
    if user.get("profile_id"):
        from services.access_profiles import is_super_admin_profile_id
        cid = user.get("company_id") or "co-demo"
        if await is_super_admin_profile_id(user["profile_id"], cid):
            await _audit(email, ip, user["id"], "blocked_super_admin_profile")
            return _generic_response()

    # Precisa colaborador vinculado
    coll_id = user.get("collaborator_id")
    if not coll_id:
        await _audit(email, ip, user["id"], "no_collaborator_linked")
        return _generic_response()

    coll = await db.collaborators.find_one(
        {"id": coll_id},
        {"_id": 0, "id": 1, "phone": 1, "name": 1, "company_id": 1},
    )
    if not coll:
        await _audit(email, ip, user["id"], "collaborator_not_found")
        return _generic_response()

    phone_norm = _normalize_phone(coll.get("phone"))
    if not phone_norm:
        await _audit(email, ip, user["id"], "no_phone_or_invalid")
        return _generic_response()

    # Gera nova senha + persiste hash + flag
    new_pwd = _generate_password()
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "password_hash": hash_password(new_pwd),
            "password_reset_pending": True,
            "password_reset_at": datetime.now(timezone.utc).isoformat(),
        }},
    )

    # Envia via WhatsApp Baileys
    msg = (
        f"🔐 *Recuperação de senha — Ligo*\n\n"
        f"Olá, {coll.get('name') or user.get('name') or 'colaborador'}!\n\n"
        f"Sua nova senha temporária é:\n\n"
        f"*{new_pwd}*\n\n"
        f"⚠️ Por segurança, você será obrigado a trocá-la no próximo login.\n\n"
        f"Se você NÃO solicitou essa recuperação, avise o auditor "
        f"imediatamente."
    )

    try:
        from services.wa.sidecar import _sidecar_post_silent
        result = await _sidecar_post_silent(
            "/send",
            {
                "phone": phone_norm,
                "text": msg,
                "company_id": coll.get("company_id") or user.get("company_id"),
            },
        )
        if not result.get("ok", True):
            logger.warning("[pwd-recovery] WhatsApp send falhou: %s", result)
            await _audit(email, ip, user["id"], "whatsapp_send_failed",
                          reason=str(result.get("error")))
            # Mantém password reset (user pode pedir o admin pra mostrar)
            # mas log adicionado pro audit detectar.
        else:
            await _audit(email, ip, user["id"], "success",
                          reason=f"sent_to_{phone_norm[:6]}***")
    except Exception as e:  # noqa: BLE001
        logger.exception("[pwd-recovery] WhatsApp send exception: %s", e)
        await _audit(email, ip, user["id"], "whatsapp_exception",
                      reason=str(e))

    return _generic_response()


def _generic_response() -> dict:
    """Resposta genérica anti-enumeração (sempre 200 OK)."""
    return {
        "ok": True,
        "message": (
            "Se a conta estiver vinculada a um colaborador com telefone "
            "cadastrado, uma nova senha será enviada via WhatsApp em "
            "instantes."
        ),
    }


async def consume_password_reset_pending(user_id: str, new_password: str
                                            ) -> None:
    """Após login forçado, troca senha e limpa o flag."""
    if not new_password or len(new_password) < 8:
        raise HTTPException(400, "Senha precisa ter pelo menos 8 caracteres")
    await db.users.update_one(
        {"id": user_id},
        {"$set": {
            "password_hash": hash_password(new_password),
            "password_reset_pending": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, "$unset": {"password_reset_at": ""}},
    )
