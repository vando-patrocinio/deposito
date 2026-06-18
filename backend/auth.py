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
                        session_id: Optional[str] = None,
                        is_super_admin: bool = False) -> str:
    payload: dict = {
        "sub": user_id,
        "email": email,
        "role": role,
        "company_id": company_id,
        "is_super_admin": bool(is_super_admin),
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
    can_attend_whatsapp: bool = False
    access_tags: Optional[list] = None
    profile_id: Optional[str] = None   # CTO 12/06/2026 — perfil de acesso reutilizável


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
    role = u.get("role")
    # Admins, gestores e auditores SEMPRE podem atender WhatsApp.
    # Para outros papéis (colaborador), respeita o flag explícito.
    can_wa = u.get("can_attend_whatsapp")
    if can_wa is None:
        can_wa = role in ("administrador", "gestor", "auditor")
    # Tags efetivas (auditor/admin = todas; demais = persisted ou default)
    try:
        from access_tags import effective_tags
        tags = effective_tags(u)
    except Exception:
        tags = u.get("access_tags") or []
    return {
        "id": u["id"],
        "email": u["email"],
        "name": u.get("name", ""),
        "role": role,
        "collaborator_id": u.get("collaborator_id"),
        "active": u.get("active", True),
        "created_at": u.get("created_at"),
        "can_attend_whatsapp": bool(can_wa),
        "access_tags": tags,
    }


async def ensure_auth_indexes(db) -> None:
    await db.users.create_index("id", unique=True)
    await db.users.create_index("email", unique=True)
    await db.users.create_index("collaborator_id", sparse=True)
    await db.login_attempts.create_index("identifier")
    await db.impersonation_log.create_index("at")


async def seed_default_users(db) -> None:
    """Garante que existam contas iniciais NA EMPRESA DEMO + um colaborador
    de exemplo vinculado a um usuário 'colaborador@empresa.com'.

    iter206 — Para a conta do dono (`vando@ligotelecom.com`), faz reseed FORÇADO
    da senha em todo startup + limpa lock de brute-force + reativa. Isso garante
    que o usuário NUNCA fique trancado fora do app em produção depois de um
    deploy ou reset acidental.
    """
    DEMO = "co-demo"
    OWNER_EMAIL = "vando@ligotelecom.com"
    OWNER_PASSWORD = os.environ.get("OWNER_PASSWORD")
    base = [
        ("admin@empresa.com", "123456", "administrador", "Administrador"),
        ("gestor@empresa.com", "123456", "gestor", "Gestor"),
        ("gestorrede@empresa.com", "123456", "gestor_rede", "Gestor de Rede"),
        ("colaborador@empresa.com", "123456", "colaborador", "Carlos Almeida"),
        # Compat com smart2 demo
        ("admin@example.com", os.environ.get("ADMIN_PASSWORD", "admin123"), "gestor", "Gestor padrão"),
        ("auditor@example.com", os.environ.get("AUDITOR_PASSWORD", "auditor123"), "auditor", "Auditor padrão"),
        # iter180 — conta corporativa do super-admin (Vando · Ligo Telecom).
        # Senha vem do .env (OWNER_PASSWORD) — deploy readiness fix.
        (OWNER_EMAIL, OWNER_PASSWORD, "auditor", "Vando · Ligo Telecom"),
    ]
    for email, password, role, name in base:
        if not password:
            continue  # OWNER_PASSWORD ausente no env → pula seed do owner
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

    # iter206 — Reset forçado do owner em TODO startup (idempotente).
    # Cobre cenários: deploy novo, banco com hash bcrypt antigo/quebrado,
    # conta com lock de brute-force, conta desativada acidentalmente.
    owner = await db.users.find_one({"email": OWNER_EMAIL})
    if owner:
        await db.users.update_one(
            {"email": OWNER_EMAIL},
            {"$set": {
                "password_hash": hash_password(OWNER_PASSWORD),
                "active": True,
                "is_super_admin": True,
                "role": "auditor",
                "locked_until": None,
                "failed_attempts": 0,
                "updated_at": _now_iso(),
            }},
        )
        # Limpa registros de brute-force se existirem em coleções separadas
        try:
            await db.auth_failed_attempts.delete_many({"email": OWNER_EMAIL})
        except Exception:
            pass
        try:
            await db.auth_locks.delete_one({"email": OWNER_EMAIL})
        except Exception:
            pass

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

        # ---- PUBLIC ACCESS TOKEN (sem login) ----
        # Permite criar links públicos com poder admin pra abas específicas.
        # Token vem via header `X-Public-Token` ou query `?ptoken=xxx`.
        ptoken = (request.headers.get("X-Public-Token")
                  or request.query_params.get("ptoken") or "").strip()
        if not token and ptoken:
            db = get_db_callable()
            pdoc = await db.public_access_tokens.find_one(
                {"token": ptoken, "revoked_at": None}, {"_id": 0},
            )
            if not pdoc:
                raise HTTPException(401, "Link público inválido ou revogado")
            # Expiração opcional
            exp = pdoc.get("expires_at")
            if exp and exp < _now_iso():
                raise HTTPException(401, "Link público expirado")
            # Atualiza last_used + counter (best-effort)
            try:
                await db.public_access_tokens.update_one(
                    {"token": ptoken},
                    {"$set": {"last_used_at": _now_iso()},
                     "$inc": {"use_count": 1}},
                )
            except Exception:
                pass
            # Retorna user sintético com poderes admin pra empresa-alvo.
            return {
                "id": f"public-{ptoken[:8]}",
                "email": f"public+{ptoken[:8]}@smartprov.local",
                "name": pdoc.get("label") or "Acesso Público",
                "role": "administrador",
                "active": True,
                "company_id": pdoc.get("company_id") or "co-demo",
                "can_attend_whatsapp": True,
                "_public_token_id": pdoc.get("id"),
                "_public_token_scope": pdoc.get("scope") or "all",
            }

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
        # Default can_attend_whatsapp: admin/gestor/auditor true automaticamente;
        # outros papéis precisam do flag explícito no cadastro do usuário.
        if user.get("can_attend_whatsapp") is None:
            user["can_attend_whatsapp"] = user.get("role") in (
                "administrador", "gestor", "auditor",
            )
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
            # REGRA GLOBAL (CEO 18/06/2026): super_admin tem acesso FULL,
            # sempre, em qualquer endpoint protegido.
            if user.get("is_super_admin") is True:
                return user
            # administrador e auditor têm acesso completo (super-roles)
            if user["role"] in ("administrador", "auditor"):
                return user
            if user["role"] not in roles:
                raise HTTPException(403, f"Acesso restrito a: {', '.join(roles)}")
            return user
        return _dep

    def require_tag(*tags: str):
        """Exige que o usuário tenha PELO MENOS UMA das tags listadas em
        `access_tags`. Admins/Auditores/Super_admin sempre passam. Para outros papéis:
        - Se o user não tem `access_tags` setado (None/vazio), aplica
          o default do papel a partir de access_tags.DEFAULT_TAGS_BY_ROLE.
        - Se tem `access_tags` setado, verifica se intersecta com `tags`.
        """
        async def _dep(user: dict = Depends(get_current_user)) -> dict:
            # REGRA GLOBAL (CEO 18/06/2026): super_admin tem acesso FULL.
            if user.get("is_super_admin") is True:
                return user
            if user["role"] in ("administrador", "auditor"):
                return user
            try:
                from access_tags import effective_tags
                allowed = set(effective_tags(user))
            except Exception:
                allowed = set(user.get("access_tags") or [])
            if not (allowed & set(tags)):
                raise HTTPException(
                    403,
                    f"Acesso restrito. Tag necessária: {' ou '.join(tags)}.",
                )
            return user
        return _dep

    return get_current_user, require_role, require_tag


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
