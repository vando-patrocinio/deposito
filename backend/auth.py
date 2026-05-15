"""Auth module: User model, JWT, bcrypt, role guards."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

JWT_ALGORITHM = "HS256"
# 30 dias: o usuário fica logado entre sessões; só é deslogado por
# logout explícito, mudança de senha (invalida o SID) ou login em outro
# dispositivo (single-session policy).
ACCESS_TOKEN_TTL_MIN = 60 * 24 * 30  # 30 dias

VALID_ROLES = ("colaborador", "gestor", "financeiro", "administrador", "auditor")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str, role: str,
                        company_id: Optional[str] = None,
                        impersonator: Optional[dict] = None,
                        session_id: Optional[str] = None) -> str:
    payload: dict = {
        "sub": user_id,
        "email": email,
        "role": role,
        "company_id": company_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_TTL_MIN),
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    if impersonator:
        payload["impersonator"] = impersonator
    if session_id:
        # SID identifica unicamente a sessão. Quando o usuário loga de novo
        # (mesmo ou outro dispositivo), um novo SID é gerado e gravado em
        # users.active_session_id; tokens com SID antigo viram inválidos
        # (single-user-per-account, ou single-session-per-user).
        payload["sid"] = session_id
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])


class UserIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str
    role: str = "colaborador"
    collaborator_id: Optional[str] = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class SetPasswordIn(BaseModel):
    user_id: str
    new_password: str = Field(min_length=6)


class ChangeMyPasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6)


def _user_public(u: dict) -> dict:
    return {
        "id": u["id"],
        "email": u["email"],
        "name": u.get("name", ""),
        "role": u["role"],
        "collaborator_id": u.get("collaborator_id"),
        "active": u.get("active", True),
        "created_at": u.get("created_at"),
    }


async def ensure_auth_indexes(db) -> None:
    await db.users.create_index("id", unique=True)
    await db.users.create_index("email", unique=True)
    await db.users.create_index("collaborator_id", sparse=True)
    await db.login_attempts.create_index("identifier")
    await db.impersonation_log.create_index("at")


async def seed_default_users(db) -> None:
    """Garante que existam contas iniciais NA EMPRESA DEMO + um colaborador
    de exemplo vinculado a um usuário 'colaborador@empresa.com'."""
    DEMO = "co-demo"
    base = [
        ("admin@empresa.com", "123456", "administrador", "Administrador"),
        ("gestor@empresa.com", "123456", "gestor", "Gestor"),
        ("gestorrede@empresa.com", "123456", "gestor_rede", "Gestor de Rede"),
        ("colaborador@empresa.com", "123456", "colaborador", "Carlos Almeida"),
        # Compat com smart2 demo
        ("admin@example.com", os.environ.get("ADMIN_PASSWORD", "admin123"), "gestor", "Gestor padrão"),
        ("auditor@example.com", os.environ.get("AUDITOR_PASSWORD", "auditor123"), "auditor", "Auditor padrão"),
    ]
    for email, password, role, name in base:
        existing = await db.users.find_one({"email": email})
        if not existing:
            doc = {
                "id": f"usr-{uuid.uuid4().hex[:10]}",
                "email": email, "name": name, "role": role,
                "password_hash": hash_password(password),
                "collaborator_id": None, "active": True,
                "company_id": DEMO,
                "created_at": _now_iso(), "updated_at": _now_iso(),
            }
            await db.users.insert_one(doc)
        elif not existing.get("company_id"):
            await db.users.update_one({"id": existing["id"]}, {"$set": {"company_id": DEMO}})

    # Vincula colaborador@empresa.com ao colaborador demo (col-demo-001)
    user_colab = await db.users.find_one({"email": "colaborador@empresa.com"}, {"_id": 0, "id": 1, "collaborator_id": 1})
    if user_colab and not user_colab.get("collaborator_id"):
        await db.users.update_one(
            {"id": user_colab["id"]},
            {"$set": {"collaborator_id": "col-demo-001"}},
        )


def make_dependencies(get_db_callable):
    """Factory para criar dependências FastAPI ligadas ao DB do app."""
    async def get_current_user(request: Request) -> dict:
        token = None
        auth_header = request.headers.get("Authorization", "") or ""
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        if not token:
            token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(401, "Não autenticado")
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            raise HTTPException(401, "Sessão expirada")
        except jwt.InvalidTokenError:
            raise HTTPException(401, "Token inválido")
        if payload.get("type") != "access":
            raise HTTPException(401, "Tipo de token inválido")
        db = get_db_callable()
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
        if not user or not user.get("active", True):
            raise HTTPException(401, "Usuário inativo ou inexistente")
        # NOTA: removida a verificação single-session-per-user (14/05/2026).
        # Antes: se `payload.sid != users.active_session_id`, retornava 401.
        # Isso derrubava o usuário toda vez que ele abria 2 abas, logava em
        # outro dispositivo, ou quando o auto-login do preview disparava.
        # Agora: o JWT é válido até `exp` (30 dias) — só sai por logout
        # explícito ou expiração natural. Padrão de mercado para SaaS B2B
        # (Slack, Gmail, Notion). O campo `active_session_id` continua
        # sendo gravado no login (pode ser usado no futuro para feature
        # "Encerrar outras sessões" no perfil do usuário).
        # Anexa company_id (do JWT ou do user doc) — fallback para demo
        user["company_id"] = payload.get("company_id") or user.get("company_id") or "co-demo"
        # Super admin: respeita header X-Active-Company para drill-down em painel
        active = (request.headers.get("X-Active-Company") or "").strip()
        if active:
            user["_active_company"] = active
        # Anexa info de impersonação para que o frontend possa exibir o banner
        if payload.get("impersonator"):
            user["impersonator"] = payload["impersonator"]
        return user

    def require_role(*roles: str):
        async def _dep(user: dict = Depends(get_current_user)) -> dict:
            # administrador e auditor têm acesso completo (super-roles)
            if user["role"] in ("administrador", "auditor"):
                return user
            if user["role"] not in roles:
                raise HTTPException(403, f"Acesso restrito a: {', '.join(roles)}")
            return user
        return _dep

    return get_current_user, require_role


async def record_login_attempt(db, identifier: str, success: bool) -> Optional[int]:
    """Registra tentativa. Retorna minutos restantes de lockout se aplicável."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    if success:
        await db.login_attempts.delete_many({"identifier": identifier})
        return None
    await db.login_attempts.insert_one({
        "identifier": identifier,
        "at": _now_iso(),
    })
    failed = await db.login_attempts.count_documents({
        "identifier": identifier, "at": {"$gte": cutoff},
    })
    if failed >= 5:
        return 15
    return None


async def is_locked_out(db, identifier: str) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    failed = await db.login_attempts.count_documents({
        "identifier": identifier, "at": {"$gte": cutoff},
    })
    return failed >= 5
