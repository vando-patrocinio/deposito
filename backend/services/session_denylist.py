"""JWT session denylist — ART.7b SECURITY_LOCK.

Permite invalidar tokens server-side em logout / troca de senha.

Uso:
    from services.session_denylist import is_jti_revoked, revoke_jti

    # No login (já existente em auth.py), o token deve ter `jti` no payload.
    # No get_current_user, validar:
    if await is_jti_revoked(db, payload.get("jti")):
        raise HTTPException(401, "Session revoked")

    # No logout:
    await revoke_jti(db, jti, expires_at=token_exp)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


async def is_jti_revoked(db, jti: Optional[str]) -> bool:
    if not jti:
        return False
    doc = await db.session_denylist.find_one({"jti": jti}, {"_id": 0, "jti": 1})
    return bool(doc)


async def revoke_jti(db, jti: str, *, expires_at: Optional[str] = None,
                     reason: str = "logout") -> None:
    if not jti:
        return
    await db.session_denylist.update_one(
        {"jti": jti},
        {"$set": {
            "jti": jti,
            "revoked_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expires_at,
            "reason": reason,
        }},
        upsert=True,
    )


async def ensure_indexes(db) -> None:
    """Idempotente. Cria índice TTL se possível."""
    try:
        await db.session_denylist.create_index("jti", unique=True)
    except Exception:
        pass
