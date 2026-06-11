"""
user_magic_links.py — CTO P0 11/06/2026

Sistema de Magic Link por usuário, com RESERVA pré-armada.

Modelo:
  - Cada usuário possui SEMPRE 2 tokens (status=active e status=reserve).
  - O usuário acessa via `?ml=<token>` que faz login direto.
  - Quando o admin clica "Renovar Link" (ou o ativo é usado em login bem-sucedido
    se rotate_on_use=True), o ATIVO é revogado, o RESERVA vira ATIVO, e um
    novo RESERVA é gerado. Troca de chave em 1 clique.

Coleção:
  user_magic_links
    {
      id (uuid),
      user_id,
      company_id,
      token            (random 32 url-safe),
      status           ('active' | 'reserve' | 'revoked'),
      generation       (int, monotonic por user),
      created_at, used_at?, revoked_at?, revoked_by?,
      reason?          ('initial' | 'rotation' | 'auto_promotion')
    }

Endpoints:
  GET    /api/users/{uid}/magic-link           — retorna ativo + reserva
  POST   /api/users/{uid}/magic-link/rotate    — rotaciona (gera novo)
  POST   /api/auth/magic-login                 — body {token} → JWT
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import create_access_token
from core import DEMO_COMPANY_ID, is_super_admin, now_iso, require_role
from database import db
from services.rate_limit import limiter, get_limit

log = logging.getLogger("ponto.user_magic_links")
router = APIRouter(prefix="/api", tags=["user-magic-links"])

COL = "user_magic_links"


def _gen_token() -> str:
    """32 char URL-safe (~190 bits). Visualmente curto, criptograficamente forte."""
    return secrets.token_urlsafe(24)


async def _ensure_indexes() -> None:
    """Índices defensivos (idempotente)."""
    try:
        await db[COL].create_index("token", unique=True)
        await db[COL].create_index([("user_id", 1), ("status", 1)])
    except Exception as e:  # pragma: no cover
        log.warning("ensure_indexes %s: %s", COL, e)


async def _next_generation(user_id: str) -> int:
    last = await db[COL].find_one(
        {"user_id": user_id}, {"_id": 0, "generation": 1},
        sort=[("generation", -1)],
    )
    return int((last or {}).get("generation", 0)) + 1


async def _bootstrap_for_user(user_id: str, company_id: str) -> None:
    """Garante que user tem 1 ativo + 1 reserva. Idempotente."""
    active = await db[COL].find_one({"user_id": user_id, "status": "active"})
    reserve = await db[COL].find_one({"user_id": user_id, "status": "reserve"})
    if active and reserve:
        return
    gen = await _next_generation(user_id)
    if not active:
        await db[COL].insert_one({
            "id": f"mlk-{uuid.uuid4().hex[:14]}",
            "user_id": user_id,
            "company_id": company_id,
            "token": _gen_token(),
            "status": "active",
            "generation": gen,
            "created_at": now_iso(),
            "reason": "initial",
        })
        gen += 1
    if not reserve:
        await db[COL].insert_one({
            "id": f"mlk-{uuid.uuid4().hex[:14]}",
            "user_id": user_id,
            "company_id": company_id,
            "token": _gen_token(),
            "status": "reserve",
            "generation": gen,
            "created_at": now_iso(),
            "reason": "initial",
        })


async def _can_manage(actor: dict, target_uid: str) -> Optional[dict]:
    """Retorna o user-alvo se actor pode gerenciar. Senão None."""
    target = await db.users.find_one({"id": target_uid}, {"password_hash": 0})
    if not target:
        return None
    if is_super_admin(actor):
        return target
    if (actor.get("company_id") or DEMO_COMPANY_ID) != (target.get("company_id") or DEMO_COMPANY_ID):
        return None
    return target


# ─────────────────── GET status ───────────────────
@router.get("/users/{uid}/magic-link")
async def get_magic_link(uid: str, user: dict = Depends(require_role("auditor"))):
    target = await _can_manage(user, uid)
    if not target:
        raise HTTPException(404, "Usuário não encontrado")
    await _ensure_indexes()
    await _bootstrap_for_user(uid, target.get("company_id") or DEMO_COMPANY_ID)
    active = await db[COL].find_one(
        {"user_id": uid, "status": "active"},
        {"_id": 0}, sort=[("generation", -1)],
    )
    reserve = await db[COL].find_one(
        {"user_id": uid, "status": "reserve"},
        {"_id": 0}, sort=[("generation", -1)],
    )
    return {
        "user_id": uid,
        "user_email": target.get("email"),
        "user_name": target.get("name"),
        "active": active,
        "reserve": reserve,
    }


# ─────────────────── Rotate ───────────────────
class RotateIn(BaseModel):
    reason: Optional[str] = None


@router.post("/users/{uid}/magic-link/rotate")
async def rotate_magic_link(
    uid: str,
    payload: RotateIn = RotateIn(),
    user: dict = Depends(require_role("auditor")),
):
    """Rotaciona o link:
      1. ATIVO atual → REVOGADO (revoked_at, revoked_by)
      2. RESERVA atual → ATIVO
      3. Gera novo RESERVA
    Idempotência via generation. Quase-atômico (3 steps em sequência).
    """
    target = await _can_manage(user, uid)
    if not target:
        raise HTTPException(404, "Usuário não encontrado")
    await _ensure_indexes()
    cid = target.get("company_id") or DEMO_COMPANY_ID

    now = now_iso()
    actor = user.get("email") or user.get("id") or "system"

    # 1. Revoga ATIVO atual (se existe)
    await db[COL].update_many(
        {"user_id": uid, "status": "active"},
        {"$set": {
            "status": "revoked",
            "revoked_at": now,
            "revoked_by": actor,
            "revoked_reason": payload.reason or "rotation",
        }},
    )
    # 2. Promove o reserva mais recente para ATIVO
    reserve = await db[COL].find_one(
        {"user_id": uid, "status": "reserve"},
        sort=[("generation", -1)],
    )
    if reserve:
        await db[COL].update_one(
            {"_id": reserve["_id"]},
            {"$set": {
                "status": "active",
                "promoted_at": now,
                "promoted_by": actor,
                "promoted_reason": payload.reason or "rotation",
            }},
        )
    else:
        # Se não há reserva (caso raro), cria um active novo direto
        gen = await _next_generation(uid)
        await db[COL].insert_one({
            "id": f"mlk-{uuid.uuid4().hex[:14]}",
            "user_id": uid,
            "company_id": cid,
            "token": _gen_token(),
            "status": "active",
            "generation": gen,
            "created_at": now,
            "reason": "rotation_no_reserve",
        })
    # 3. Gera novo RESERVA
    gen = await _next_generation(uid)
    await db[COL].insert_one({
        "id": f"mlk-{uuid.uuid4().hex[:14]}",
        "user_id": uid,
        "company_id": cid,
        "token": _gen_token(),
        "status": "reserve",
        "generation": gen,
        "created_at": now,
        "reason": "rotation",
    })

    # Audit log
    try:
        await db.audit_log.insert_one({
            "id": f"aud-{uuid.uuid4().hex[:14]}",
            "actor_email": actor,
            "action": "magic_link.rotate",
            "target_user_id": uid,
            "target_email": target.get("email"),
            "company_id": cid,
            "reason": payload.reason,
            "created_at": now,
        })
    except Exception:
        pass

    # Retorna o novo estado
    active = await db[COL].find_one(
        {"user_id": uid, "status": "active"},
        {"_id": 0}, sort=[("generation", -1)],
    )
    reserve_new = await db[COL].find_one(
        {"user_id": uid, "status": "reserve"},
        {"_id": 0}, sort=[("generation", -1)],
    )
    return {
        "ok": True,
        "user_id": uid,
        "rotated_at": now,
        "active": active,
        "reserve": reserve_new,
    }


# ─────────────────── Magic login ───────────────────
class MagicLoginIn(BaseModel):
    token: str


@router.post("/auth/magic-login")
async def magic_login(payload: MagicLoginIn, request: Request = None):
    token = (payload.token or "").strip()
    if not token or len(token) < 12:
        raise HTTPException(400, "Token inválido")

    doc = await db[COL].find_one({"token": token, "status": "active"})
    if not doc:
        raise HTTPException(401, "Link inválido ou expirado. Peça ao admin para gerar um novo.")

    user = await db.users.find_one({"id": doc["user_id"]}, {"password_hash": 0})
    if not user or not user.get("active", True):
        raise HTTPException(401, "Usuário desativado")

    # Marca uso
    await db[COL].update_one(
        {"_id": doc["_id"]},
        {"$set": {"used_at": now_iso()},
         "$inc": {"use_count": 1}},
    )

    cid = user.get("company_id") or DEMO_COMPANY_ID
    jwt = create_access_token(
        user_id=user["id"],
        email=user["email"],
        role=user["role"],
        company_id=cid,
        is_super_admin=bool(user.get("is_super_admin")),
    )
    user.pop("_id", None)
    return {"ok": True, "access_token": jwt, "user": user}
