"""Endpoints de auth + users (gerenciamento de usuários do sistema)."""

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import (
    ChangeMyPasswordIn,
    LoginIn,
    SetPasswordIn,
    UserIn,
    create_access_token,
    hash_password,
    is_locked_out,
    record_login_attempt,
    verify_password,
)
from core import (
    DEMO_COMPANY_ID,
    can_grant_super_admin,
    get_current_user,
    is_super_admin,
    now_iso,
    require_role,
    tenant_filter,
)
from database import db
from access_tags import (
    TAGS as ACCESS_TAGS_CATALOG,
    sanitize_tags,
    effective_tags,
    DEFAULT_TAGS_BY_ROLE,
)
from services.rate_limit import limiter, get_limit

router = APIRouter(prefix="/api", tags=["auth", "users"])
logger = logging.getLogger("users")


class AdminLogin(BaseModel):
    password: str


@router.post("/auth/admin-login")
async def admin_login(payload: AdminLogin):
    """LEGADO: aceita só senha do .env. Mantido para retrocompatibilidade."""
    expected = os.environ.get("ADMIN_PASSWORD", "admin123")
    if payload.password != expected:
        raise HTTPException(401, "Senha inválida")
    user = await db.users.find_one({"email": "admin@example.com"}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(500, "Usuário admin não encontrado — re-inicie o backend")
    cid = user.get("company_id") or DEMO_COMPANY_ID
    token = create_access_token(user["id"], user["email"], user["role"], company_id=cid)
    return {"ok": True, "role": user["role"], "access_token": token, "user": user}


@router.post("/auth/login")
@limiter.limit(get_limit("auth_login"))
async def login(request: Request, payload: LoginIn):
    email = payload.email.lower().strip()
    if await is_locked_out(db, email):
        raise HTTPException(429, "Muitas tentativas falhadas. Aguarde 15 minutos.")
    user = await db.users.find_one({"email": email})
    if not user or not user.get("active", True) or not verify_password(payload.password, user["password_hash"]):
        await record_login_attempt(db, email, success=False)
        raise HTTPException(401, "E-mail ou senha incorretos")
    await record_login_attempt(db, email, success=True)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # CTO 12/06/2026 — Password reset pending: força troca antes de continuar.
    must_change = bool(user.get("password_reset_pending"))
    # Session singleton: gera novo SID e grava no user. Qualquer JWT anterior
    # com SID diferente vira inválido no get_current_user.
    sid = uuid.uuid4().hex
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"active_session_id": sid, "last_login_at": now_iso()}},
    )
    token = create_access_token(user["id"], user["email"], user["role"],
                                  company_id=cid, session_id=sid,
                                  is_super_admin=is_super_admin(user))
    user.pop("_id", None)
    user.pop("password_hash", None)
    user["active_session_id"] = sid
    # Flags computadas (não persistir, são derivadas)
    user["is_super_admin"] = is_super_admin(user)
    user["can_grant_super_admin"] = can_grant_super_admin(user)
    return {
        "ok": True, "access_token": token, "user": user,
        "must_change_password": must_change,
    }


# ───────────────────────────────────────────────────────────────────────
# CTO 12/06/2026 — Password Recovery via WhatsApp
# ───────────────────────────────────────────────────────────────────────

class ForgotPasswordIn(BaseModel):
    email: str


@router.post("/auth/forgot-password")
async def forgot_password(payload: ForgotPasswordIn, request: Request):
    """Reset de senha self-service via WhatsApp do colaborador vinculado.

    Sempre retorna 200 OK genérico (anti-enumeração). Erros reais só em
    rate limit (429). Detalhes do fluxo em services/password_recovery.py.
    """
    ip = (request.client.host if request.client else "") or "unknown"
    from services.password_recovery import forgot_password_flow
    return await forgot_password_flow(payload.email, ip)


class ChangePasswordForcedIn(BaseModel):
    new_password: str


@router.post("/auth/change-password-forced")
async def change_password_forced(
    payload: ChangePasswordForcedIn,
    user: dict = Depends(get_current_user),
):
    """Chamado pelo frontend QUANDO `must_change_password=true` retornou no
    login. Troca a senha e limpa o flag `password_reset_pending`.

    Só funciona se o flag estiver setado (segurança extra — impede uso fora
    do fluxo de recovery).
    """
    if not user.get("password_reset_pending"):
        raise HTTPException(
            400,
            "Esta rota só é chamada quando há uma troca pendente após "
            "recuperação de senha.",
        )
    from services.password_recovery import consume_password_reset_pending
    await consume_password_reset_pending(user["id"], payload.new_password)
    return {"ok": True, "message": "Senha alterada com sucesso."}





@router.post("/auth/logout")
async def logout(user: dict = Depends(get_current_user)):
    """Logout "soft": zera active_session_id no documento do user.

    NOTA (14/05/2026): após removermos o single-session-per-user check em
    auth.py, o JWT continua válido até `exp` mesmo após o logout. Este
    endpoint serve principalmente para:
      (1) o frontend chamar antes de limpar o localStorage (cleanup);
      (2) atualizar `last_logout_at` para auditoria;
      (3) reservar a coluna `active_session_id` para futura feature
          "Encerrar outras sessões" (que vai consultar este campo).
    Em outras palavras: o token NÃO vira inválido aqui — só o frontend
    descarta sua cópia. Padrão de SaaS B2B (Slack, Gmail, Notion).
    """
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"active_session_id": None, "last_logout_at": now_iso()}},
    )
    return {"ok": True}


class GoogleLoginIn(BaseModel):
    session_id: str


@router.post("/auth/google-login")
async def google_login(payload: GoogleLoginIn):
    """Login do sistema via Emergent-managed Google Auth.
    Aceita session_id do redirect Google e busca o usuário (gestor/auditor) por email.
    Atualiza o cadastro com google_email + google_picture (avatar) na 1ª vez.

    Super-admin allowlist (SUPER_ADMIN_EMAILS no .env): se o e-mail Google estiver
    nessa lista, o sistema SEMPRE aceita — auto-cria como auditor se não existir,
    e reativa se estiver desativado.
    """
    import httpx
    from datetime import datetime, timezone
    sid = (payload.session_id or "").strip()
    if not sid:
        raise HTTPException(400, "session_id obrigatório")
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(
                "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
                headers={"X-Session-ID": sid},
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(401, f"Sessão Google inválida: {e.response.status_code}")
    except Exception:
        raise HTTPException(502, "Falha ao validar com o serviço de autenticação")
    google_email = (data.get("email") or "").strip().lower()
    google_name = data.get("name") or ""
    google_picture = data.get("picture") or ""
    if not google_email:
        raise HTTPException(401, "E-mail Google não retornado")

    # Super-admin allowlist (do .env)
    super_admins = {
        e.strip().lower() for e in (os.environ.get("SUPER_ADMIN_EMAILS") or "").split(",") if e.strip()
    }
    is_super = google_email in super_admins

    user = await db.users.find_one({"email": google_email})
    if not user:
        user = await db.users.find_one({"google_email": google_email})

    if not user and is_super:
        # Auto-provisionamento do super admin (atribui à empresa Demo)
        import uuid as _uuid
        new_uid = f"usr-{_uuid.uuid4().hex[:10]}"
        user = {
            "id": new_uid,
            "email": google_email,
            "name": google_name or "Super Admin",
            "role": "auditor",
            # senha aleatória não utilizável — login só via Google
            "password_hash": hash_password(_uuid.uuid4().hex),
            "active": True,
            "company_id": DEMO_COMPANY_ID,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "auto_created": True,
            "google_email": google_email,
        }
        await db.users.insert_one(user)
        logger = logging.getLogger("ponto")
        logger.info("[google-login] Super admin auto-provisionado: %s (%s)", google_email, new_uid)

    if not user:
        raise HTTPException(404, f"Nenhum usuário cadastrado com o e-mail {google_email}. Procure o auditor.")

    # Super-admin: força ativo
    if is_super and not user.get("active", True):
        await db.users.update_one({"id": user["id"]}, {"$set": {"active": True}})
        user["active"] = True

    if not user.get("active", True):
        raise HTTPException(403, "Usuário desativado. Peça ao auditor para reativar.")

    update = {
        "google_email": google_email,
        "google_name": google_name,
        "google_picture": google_picture,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.update_one({"id": user["id"]}, {"$set": update})
    user.update(update)
    user.pop("_id", None)
    user.pop("password_hash", None)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    token = create_access_token(user["id"], user["email"], user["role"], company_id=cid)
    return {"ok": True, "access_token": token, "user": user, "super_admin": is_super}


@router.get("/auth/me")
async def auth_me(user: dict = Depends(get_current_user)):
    # Anexa flags computadas para o frontend
    user["is_super_admin"] = is_super_admin(user)
    user["can_grant_super_admin"] = can_grant_super_admin(user)
    # White-label: anexa company_name do doc da empresa (db.companies)
    # para o frontend não exibir "Empresa Demo" hard-coded
    try:
        cid = user.get("company_id")
        if cid and not user.get("company_name"):
            co = await db.companies.find_one(
                {"id": cid}, {"_id": 0, "name": 1, "slug": 1})
            if co:
                user["company_name"] = co.get("name")
                user["company_slug"] = co.get("slug")
    except Exception:
        pass
    return user


@router.post("/auth/change-my-password")
async def change_my_password(payload: ChangeMyPasswordIn, user: dict = Depends(get_current_user)):
    full = await db.users.find_one({"id": user["id"]})
    if not full or not verify_password(payload.current_password, full["password_hash"]):
        raise HTTPException(401, "Senha atual incorreta")
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"password_hash": hash_password(payload.new_password), "updated_at": now_iso()}},
    )
    return {"ok": True}


@router.post("/auth/impersonate/{target_id}")
async def impersonate_user(target_id: str, user: dict = Depends(get_current_user)):
    if user.get("impersonator"):
        raise HTTPException(400, "Você já está em modo impersonation. Saia antes de iniciar outra.")
    if user["role"] != "auditor":
        raise HTTPException(403, "Apenas auditores podem usar impersonation.")
    target = await db.users.find_one({"id": target_id})
    if not target or not target.get("active", True):
        raise HTTPException(404, "Usuário-alvo não encontrado ou inativo")
    # Impersonation só dentro do mesmo tenant (super admin pode cross)
    if target.get("company_id") != user.get("company_id") and not is_super_admin(user):
        raise HTTPException(403, "Não é possível impersonar usuário de outra empresa")
    if target["id"] == user["id"]:
        raise HTTPException(400, "Você já está logado como você mesmo")
    impersonator_claim = {"id": user["id"], "email": user["email"], "role": user["role"], "name": user.get("name", "")}
    target_cid = target.get("company_id") or DEMO_COMPANY_ID
    token = create_access_token(target["id"], target["email"], target["role"], company_id=target_cid, impersonator=impersonator_claim)
    await db.impersonation_log.insert_one({
        "id": uuid.uuid4().hex[:14], "at": now_iso(),
        "auditor_id": user["id"], "auditor_email": user["email"],
        "target_id": target["id"], "target_email": target["email"], "target_role": target["role"],
        "company_id": target_cid,
        "action": "start",
    })
    target.pop("_id", None)
    target.pop("password_hash", None)
    target["impersonator"] = impersonator_claim
    return {"ok": True, "access_token": token, "user": target}


@router.post("/auth/end-impersonation")
async def end_impersonation(user: dict = Depends(get_current_user)):
    imp = user.get("impersonator")
    if not imp:
        raise HTTPException(400, "Você não está em modo impersonation")
    auditor = await db.users.find_one({"id": imp["id"]}, {"_id": 0, "password_hash": 0})
    if not auditor:
        raise HTTPException(404, "Auditor original não encontrado")
    cid = auditor.get("company_id") or DEMO_COMPANY_ID
    token = create_access_token(auditor["id"], auditor["email"], auditor["role"], company_id=cid)
    await db.impersonation_log.insert_one({
        "id": uuid.uuid4().hex[:14], "at": now_iso(),
        "auditor_id": auditor["id"], "auditor_email": auditor["email"],
        "target_id": user["id"], "target_email": user["email"], "target_role": user["role"],
        "company_id": cid,
        "action": "end",
    })
    return {"ok": True, "access_token": token, "user": auditor}


@router.get("/auth/impersonation-log")
async def get_impersonation_log(limit: int = 100, user: dict = Depends(require_role("auditor"))):
    q = {} if is_super_admin(user) else {"company_id": user.get("company_id") or DEMO_COMPANY_ID}
    docs = await db.impersonation_log.find(q, {"_id": 0}).sort("at", -1).to_list(int(limit))
    return docs


@router.get("/users")
async def list_users(user: dict = Depends(require_role("auditor"))):
    q = tenant_filter(user)
    docs = await db.users.find(q, {"_id": 0, "password_hash": 0}).to_list(500)
    # CTO 12/06/2026 — anexa code do colaborador vinculado pra exibir no form
    col_ids = [d["collaborator_id"] for d in docs if d.get("collaborator_id")]
    code_map: dict = {}
    if col_ids:
        async for c in db.collaborators.find(
            {"id": {"$in": col_ids}},
            {"_id": 0, "id": 1, "code": 1, "name": 1},
        ):
            code_map[c["id"]] = {"code": c.get("code"), "name": c.get("name")}
    # CTO 12/06/2026 — RBAC Super Admin: só Super Admin vê outros Super Admin.
    # Se solicitante NÃO é Super Admin (perfil nem flag legado), oculta users
    # vinculados ao perfil seed 'super_admin'.
    from services.access_profiles import user_has_super_admin_profile
    requester_is_super = is_super_admin(user) or await user_has_super_admin_profile(user)
    if not requester_is_super:
        super_pids = set()
        async for p in db.access_profiles.find(
            {"$or": [{"key": "super_admin"}, {"is_super_admin_profile": True}]},
            {"_id": 0, "id": 1},
        ):
            super_pids.add(p["id"])
        if super_pids:
            docs = [
                d for d in docs
                if d.get("profile_id") not in super_pids
                and not d.get("is_super_admin")
            ]
    # Anexa tags efetivas (já considerando o papel) para o frontend
    for d in docs:
        d["effective_tags"] = effective_tags(d)
        col_id = d.get("collaborator_id")
        if col_id and col_id in code_map:
            d["collaborator_code"] = code_map[col_id].get("code")
            d["collaborator_name"] = code_map[col_id].get("name")
    return docs


@router.get("/users/unlinked")
async def list_unlinked_users(user: dict = Depends(require_role("gestor"))):
    """CTO 12/06/2026 — Lista usuários do tenant SEM collaborator_id vinculado.
    Usado pelo CadastroPanel para o gestor escolher manualmente qual user
    associar a um colaborador.

    Aplica o mesmo filtro de visibilidade Super Admin (gestor comum NÃO vê
    users com perfil Super Admin).
    """
    q = tenant_filter(user)
    q["$or"] = [{"collaborator_id": None}, {"collaborator_id": {"$exists": False}}]
    docs = await db.users.find(
        q, {"_id": 0, "id": 1, "email": 1, "name": 1, "role": 1,
             "active": 1, "profile_id": 1, "is_super_admin": 1},
    ).to_list(500)

    # Filtro RBAC visual: oculta users com Super Admin profile/flag dos não-super.
    from services.access_profiles import user_has_super_admin_profile
    requester_is_super = is_super_admin(user) or await user_has_super_admin_profile(user)
    if not requester_is_super:
        super_pids = set()
        async for p in db.access_profiles.find(
            {"$or": [{"key": "super_admin"}, {"is_super_admin_profile": True}]},
            {"_id": 0, "id": 1},
        ):
            super_pids.add(p["id"])
        if super_pids:
            docs = [
                d for d in docs
                if d.get("profile_id") not in super_pids
                and not d.get("is_super_admin")
            ]
    return docs


@router.post("/collaborators/{cid}/link-user/{uid}")
async def link_user_to_collaborator(
    cid: str, uid: str,
    user: dict = Depends(require_role("gestor")),
):
    """CTO 12/06/2026 — Vincula um User existente a um Colaborador.

    - Valida tenant (user/collab devem estar na mesma empresa do solicitante).
    - Valida unicidade: collaborator só pode ter 1 user, user só pode ter 1 collab.
    - Após linkar: se o colaborador tem profile_id, espalha para o user.
    - Se o user tem perfil Super Admin, exige solicitante Super Admin.
    """
    cid_company = user.get("company_id") or DEMO_COMPANY_ID
    if is_super_admin(user):
        cid_company = (user.get("_active_company") or cid_company)

    coll = await db.collaborators.find_one(
        {"id": cid}, {"_id": 0, "id": 1, "name": 1, "company_id": 1, "profile_id": 1},
    )
    if not coll or (not is_super_admin(user) and coll.get("company_id") != cid_company):
        raise HTTPException(404, "Colaborador não encontrado neste tenant")

    target_user = await db.users.find_one({"id": uid}, {"_id": 0})
    if not target_user:
        raise HTTPException(404, "Usuário não encontrado")
    if not is_super_admin(user) and target_user.get("company_id") != cid_company:
        raise HTTPException(404, "Usuário não encontrado neste tenant")

    # Guard Super Admin: se o user-alvo tem perfil/flag Super Admin, só Super Admin linka
    from services.access_profiles import user_has_super_admin_profile, is_super_admin_profile_id
    if target_user.get("is_super_admin") or (
        target_user.get("profile_id")
        and await is_super_admin_profile_id(
            target_user["profile_id"], target_user.get("company_id") or cid_company,
        )
    ):
        allowed = is_super_admin(user) or await user_has_super_admin_profile(user)
        if not allowed:
            raise HTTPException(
                403,
                "Apenas um Super Admin pode vincular um usuário Super Admin "
                "a um colaborador.",
            )

    # Unicidade
    if target_user.get("collaborator_id") and target_user["collaborator_id"] != cid:
        raise HTTPException(409, "Este usuário já está vinculado a outro colaborador")
    existing = await db.users.find_one(
        {"collaborator_id": cid, "id": {"$ne": uid}},
        {"_id": 0, "email": 1, "name": 1},
    )
    if existing:
        raise HTTPException(
            409,
            f"Este colaborador já está vinculado ao usuário "
            f"{existing.get('name')} <{existing.get('email')}>.",
        )

    update: dict = {
        "collaborator_id": cid,
        "updated_at": now_iso(),
    }
    # Se colaborador já tem profile_id, propaga para o user
    if coll.get("profile_id"):
        from services.access_profiles import get_profile
        p = await get_profile(coll["profile_id"], coll.get("company_id") or cid_company)
        if p:
            update["profile_id"] = p["id"]
            update["access_tags"] = list(p.get("access_tags") or [])

    await db.users.update_one({"id": uid}, {"$set": update})

    # Garante code LIGO-NNNN no colaborador
    try:
        from services.collaborator_code import get_or_assign_code
        await get_or_assign_code(cid, coll.get("company_id") or cid_company)
    except Exception as e:  # noqa: BLE001
        logger.warning("[link_user] code falhou: %s", e)

    doc = await db.users.find_one({"id": uid}, {"_id": 0, "password_hash": 0})
    return {"ok": True, "user": doc, "collaborator_id": cid}


@router.delete("/collaborators/{cid}/link-user")
async def unlink_user_from_collaborator(
    cid: str,
    user: dict = Depends(require_role("auditor")),
):
    """Remove o vínculo user↔colaborador (zera users.collaborator_id).
    Não deleta nem o user nem o colaborador, só desvincula.

    Requer AUDITOR (mesma escala do delete_user) — gestor não pode quebrar
    o vínculo unilateralmente.
    """
    coll = await db.collaborators.find_one(
        {"id": cid}, {"_id": 0, "id": 1, "company_id": 1},
    )
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    if not is_super_admin(user) and coll.get("company_id") != user.get("company_id"):
        raise HTTPException(404, "Colaborador não encontrado neste tenant")

    res = await db.users.update_many(
        {"collaborator_id": cid},
        {"$set": {"collaborator_id": None, "updated_at": now_iso()}},
    )
    return {"ok": True, "unlinked": res.modified_count}



@router.get("/access-tags/catalog")
async def access_tags_catalog(user: dict = Depends(get_current_user)):
    """Catálogo público (para auditor montar a tela). Retorna lista de tags
    com label/categoria/ícone, defaults por papel e a lista do user atual."""
    return {
        "tags": ACCESS_TAGS_CATALOG,
        "defaults_by_role": DEFAULT_TAGS_BY_ROLE,
        "current_user_tags": effective_tags(user),
    }


@router.get("/access-tags/audit")
async def access_tags_audit(user: dict = Depends(require_role("auditor"))):
    """iter211v — REGRA DE PARIDADE: toda aba/sub-aba declarada em
    `NAV_GROUPS` (frontend) precisa ter tag correspondente em
    `access_tags.py` (backend). Este endpoint expõe a divergência em
    tempo real para auditores.

    Resposta:
        nav_total:        total de ids únicos em NAV_GROUPS
        catalog_total:    total de tags no catálogo
        missing_in_catalog: ids do sidebar que NÃO existem como tag
                            (precisa adicionar em access_tags.py).
        extra_in_catalog:  tags sem aba no sidebar (legado/sub-painel —
                            geralmente OK).
        in_sync:           True se nenhuma aba está faltando tag.
    """
    from nav_tabs_registry import audit_against_catalog, parse_nav_tabs
    audit = audit_against_catalog([t["key"] for t in ACCESS_TAGS_CATALOG])
    audit["nav_groups"] = {
        label: [{"id": tid, "parent_id": pid} for tid, pid in entries]
        for label, entries in parse_nav_tabs().items()
    }
    return audit


@router.post("/users")
async def create_user(payload: UserIn, user: dict = Depends(require_role("auditor"))):
    if payload.role not in ("gestor", "auditor"):
        raise HTTPException(400, "Apenas usuários com papel 'gestor' ou 'auditor' podem ser criados aqui. Colaboradores que batem ponto são cadastrados na aba Cadastro.")
    email = payload.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "E-mail já cadastrado")
    cid = user.get("company_id") or DEMO_COMPANY_ID

    # CTO 12/06/2026 — Regra dura: usuário SÓ pode existir se vinculado a
    # colaborador. Whitelist apenas para usuários de serviço (admin de
    # plataforma, IA Isabella, etc).
    from routes.audit_users import SERVICE_USER_WHITELIST
    if not payload.collaborator_id and email not in SERVICE_USER_WHITELIST:
        raise HTTPException(
            400,
            "Todo usuário precisa estar vinculado a um cadastro de "
            "colaborador. Cadastre o colaborador primeiro em "
            "Cadastro → Colaboradores e tente novamente.",
        )

    if payload.collaborator_id:
        coll = await db.collaborators.find_one({"id": payload.collaborator_id, "company_id": cid})
        if not coll:
            raise HTTPException(404, "Colaborador vinculado não existe nesta empresa")
        # Unicidade: o colaborador só pode estar vinculado a 1 usuário.
        already = await db.users.find_one(
            {"collaborator_id": payload.collaborator_id},
            {"_id": 0, "email": 1, "name": 1},
        )
        if already:
            raise HTTPException(
                409,
                f"Este colaborador já está vinculado ao usuário "
                f"{already.get('name')} <{already.get('email')}>.",
            )
        # Garante que o colaborador tem code LIGO-NNNN (idempotente)
        try:
            from services.collaborator_code import get_or_assign_code
            await get_or_assign_code(payload.collaborator_id, cid)
        except Exception as e:  # noqa: BLE001
            logger.warning("[create_user] falha ao garantir code: %s", e)
    # Tags: prioridade = perfil > payload explícito > default do papel
    profile_doc = None
    # CTO 12/06/2026 — Herança passiva: se profile_id não foi passado mas o
    # colaborador vinculado já tem profile_id, herda dele.
    effective_profile_id = payload.profile_id
    if not effective_profile_id and payload.collaborator_id:
        coll_doc = await db.collaborators.find_one(
            {"id": payload.collaborator_id, "company_id": cid},
            {"_id": 0, "profile_id": 1},
        )
        effective_profile_id = (coll_doc or {}).get("profile_id")
    if effective_profile_id:
        from services.access_profiles import get_profile
        profile_doc = await get_profile(effective_profile_id, cid)
        if not profile_doc:
            raise HTTPException(404, "Perfil de acesso não encontrado")
        # Guard: atribuir perfil Super Admin exige que o solicitante
        # tenha o próprio perfil Super Admin OU seja super admin legado.
        if profile_doc.get("is_super_admin_profile"):
            from services.access_profiles import user_has_super_admin_profile
            allowed = is_super_admin(user) or await user_has_super_admin_profile(user)
            if not allowed:
                raise HTTPException(
                    403,
                    "Apenas um Super Admin pode atribuir o perfil Super Admin "
                    "a outro usuário.",
                )
    raw_tags = getattr(payload, "access_tags", None)
    if profile_doc:
        tags = list(profile_doc.get("access_tags") or [])
    elif raw_tags is not None:
        tags = sanitize_tags(raw_tags)
    else:
        tags = list(DEFAULT_TAGS_BY_ROLE.get(payload.role, []))
    doc = {
        "id": f"usr-{uuid.uuid4().hex[:10]}",
        "email": email, "name": payload.name, "role": payload.role,
        "password_hash": hash_password(payload.password),
        "collaborator_id": payload.collaborator_id, "active": True,
        "can_attend_whatsapp": bool(payload.can_attend_whatsapp),
        "access_tags": tags,
        "profile_id": effective_profile_id,
        "company_id": cid,
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.users.insert_one(doc)
    doc.pop("_id", None)
    doc.pop("password_hash", None)
    doc["effective_tags"] = effective_tags(doc)
    return doc


@router.put("/users/{uid}")
async def update_user(uid: str, payload: dict, user: dict = Depends(require_role("auditor"))):
    # Tenant scope: super admin pode tudo, demais só dentro da empresa
    if not is_super_admin(user):
        target = await db.users.find_one({"id": uid}, {"company_id": 1})
        if not target or target.get("company_id") != user.get("company_id"):
            raise HTTPException(404, "Usuário não encontrado")
    update: dict = {}
    if "name" in payload and payload["name"] is not None:
        update["name"] = payload["name"]
    if "role" in payload and payload["role"]:
        if payload["role"] not in ("gestor", "auditor"):
            raise HTTPException(400, "Apenas papéis 'gestor' ou 'auditor'. Colaboradores são cadastrados na aba Cadastro.")
        update["role"] = payload["role"]
    if "active" in payload:
        update["active"] = bool(payload["active"])
    if "collaborator_id" in payload:
        new_coll_id = payload["collaborator_id"] or None
        if new_coll_id:
            # Valida existência do colaborador no tenant do user-alvo.
            cid_target = (await db.users.find_one({"id": uid}, {"company_id": 1}) or {}).get("company_id") or user.get("company_id") or DEMO_COMPANY_ID
            coll = await db.collaborators.find_one({"id": new_coll_id, "company_id": cid_target})
            if not coll:
                raise HTTPException(404, "Colaborador vinculado não existe nesta empresa")
            # Unicidade: nenhum outro user pode ter esse collaborator_id.
            already = await db.users.find_one(
                {"collaborator_id": new_coll_id, "id": {"$ne": uid}},
                {"_id": 0, "email": 1, "name": 1},
            )
            if already:
                raise HTTPException(
                    409,
                    f"Este colaborador já está vinculado ao usuário "
                    f"{already.get('name')} <{already.get('email')}>.",
                )
            # Garante code LIGO-NNNN no colaborador vinculado
            try:
                from services.collaborator_code import get_or_assign_code
                await get_or_assign_code(new_coll_id, cid_target)
            except Exception as e:  # noqa: BLE001
                logger.warning("[update_user] falha garantir code: %s", e)
        else:
            # CTO 12/06/2026 — regra dura: não pode REMOVER o vínculo
            # de colaborador exceto pra usuários de serviço.
            from routes.audit_users import SERVICE_USER_WHITELIST
            target_email = (await db.users.find_one({"id": uid}, {"email": 1}) or {}).get("email") or ""
            if target_email.lower() not in SERVICE_USER_WHITELIST:
                raise HTTPException(
                    400,
                    "Não é possível remover o vínculo com o colaborador. "
                    "Para desativar o acesso deste usuário, marque-o como "
                    "inativo em vez de remover o vínculo.",
                )
        update["collaborator_id"] = new_coll_id
    if "can_attend_whatsapp" in payload:
        update["can_attend_whatsapp"] = bool(payload["can_attend_whatsapp"])
    if "access_tags" in payload:
        update["access_tags"] = sanitize_tags(payload.get("access_tags"))
    if "profile_id" in payload:
        # Mudou perfil → recarrega tags do perfil (sobrescreve access_tags acima)
        new_profile_id = payload.get("profile_id") or None
        cid_target = (await db.users.find_one({"id": uid}, {"company_id": 1}) or {}).get("company_id") or user.get("company_id") or DEMO_COMPANY_ID
        if new_profile_id:
            from services.access_profiles import get_profile
            p = await get_profile(new_profile_id, cid_target)
            if not p:
                raise HTTPException(404, "Perfil de acesso não encontrado")
            # Guard: trocar para o perfil Super Admin exige que o solicitante
            # tenha Super Admin (perfil ou flag legado).
            if p.get("is_super_admin_profile"):
                from services.access_profiles import user_has_super_admin_profile
                allowed = is_super_admin(user) or await user_has_super_admin_profile(user)
                if not allowed:
                    raise HTTPException(
                        403,
                        "Apenas um Super Admin pode atribuir o perfil Super "
                        "Admin a outro usuário.",
                    )
            update["profile_id"] = new_profile_id
            update["access_tags"] = list(p.get("access_tags") or [])
        else:
            # Guard simétrico: REMOVER perfil Super Admin de outro usuário
            # também exige Super Admin.
            current = await db.users.find_one({"id": uid}, {"_id": 0, "profile_id": 1})
            current_pid = (current or {}).get("profile_id")
            if current_pid:
                from services.access_profiles import is_super_admin_profile_id, user_has_super_admin_profile
                if await is_super_admin_profile_id(current_pid, cid_target):
                    allowed = is_super_admin(user) or await user_has_super_admin_profile(user)
                    if not allowed:
                        raise HTTPException(
                            403,
                            "Apenas um Super Admin pode revogar o perfil "
                            "Super Admin de outro usuário.",
                        )
            update["profile_id"] = None
    if "email" in payload and payload["email"]:
        new_email = str(payload["email"]).strip().lower()
        if "@" not in new_email or "." not in new_email:
            raise HTTPException(400, "E-mail inválido")
        existing = await db.users.find_one({"email": new_email, "id": {"$ne": uid}})
        if existing:
            raise HTTPException(400, "E-mail já está em uso por outro usuário")
        update["email"] = new_email
    if "password" in payload and payload["password"]:
        if len(str(payload["password"])) < 6:
            raise HTTPException(400, "Senha deve ter no mínimo 6 caracteres")
        update["password_hash"] = hash_password(str(payload["password"]))
    if not update:
        raise HTTPException(400, "Nada para atualizar")
    update["updated_at"] = now_iso()
    res = await db.users.update_one({"id": uid}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(404, "Usuário não encontrado")
    doc = await db.users.find_one({"id": uid}, {"_id": 0, "password_hash": 0})
    if doc:
        doc["effective_tags"] = effective_tags(doc)
    return doc


@router.post("/users/set-password")
async def admin_set_password(payload: SetPasswordIn, user: dict = Depends(require_role("auditor"))):
    if not is_super_admin(user):
        target = await db.users.find_one({"id": payload.user_id}, {"company_id": 1})
        if not target or target.get("company_id") != user.get("company_id"):
            raise HTTPException(404, "Usuário não encontrado")
    res = await db.users.update_one(
        {"id": payload.user_id},
        {"$set": {"password_hash": hash_password(payload.new_password), "updated_at": now_iso()}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Usuário não encontrado")
    return {"ok": True}


@router.delete("/users/{uid}")
async def delete_user(uid: str, user: dict = Depends(require_role("auditor"))):
    if uid == user["id"]:
        raise HTTPException(400, "Você não pode excluir a própria conta")
    if not is_super_admin(user):
        target = await db.users.find_one({"id": uid}, {"company_id": 1})
        if not target or target.get("company_id") != user.get("company_id"):
            raise HTTPException(404, "Usuário não encontrado")
    # Guard: deletar um usuário com perfil Super Admin exige Super Admin.
    target_doc = await db.users.find_one({"id": uid}, {"_id": 0, "profile_id": 1, "company_id": 1})
    target_pid = (target_doc or {}).get("profile_id")
    target_cid = (target_doc or {}).get("company_id")
    if target_pid and target_cid:
        from services.access_profiles import is_super_admin_profile_id, user_has_super_admin_profile
        if await is_super_admin_profile_id(target_pid, target_cid):
            allowed = is_super_admin(user) or await user_has_super_admin_profile(user)
            if not allowed:
                raise HTTPException(
                    403,
                    "Apenas um Super Admin pode excluir um usuário com "
                    "perfil Super Admin.",
                )
    res = await db.users.delete_one({"id": uid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Usuário não encontrado")
    return {"ok": True}


class SuperAdminToggleIn(BaseModel):
    is_super_admin: bool


@router.patch("/users/{uid}/super-admin")
async def toggle_super_admin(
    uid: str, payload: SuperAdminToggleIn,
    user: dict = Depends(get_current_user),
):
    """Ativa/desativa flag de super admin para um usuário.

    Regras (decisão de produto):
    - Apenas o grantor hardcoded (`vando@example.com`) pode usar este endpoint.
    - O próprio grantor não pode se auto-desativar (segurança contra lockout).
    """
    if not can_grant_super_admin(user):
        raise HTTPException(403, "Apenas o super admin titular pode conceder/revogar esse privilégio")
    target = await db.users.find_one({"id": uid}, {"_id": 0})
    if not target:
        raise HTTPException(404, "Usuário não encontrado")
    if target.get("email", "").strip().lower() == user.get("email", "").strip().lower() \
       and payload.is_super_admin is False:
        raise HTTPException(400, "Você não pode revogar seu próprio super admin")
    await db.users.update_one(
        {"id": uid},
        {"$set": {"is_super_admin": payload.is_super_admin,
                   "updated_at": now_iso(),
                   "super_admin_changed_by": user.get("email"),
                   "super_admin_changed_at": now_iso()}},
    )
    return {"ok": True, "user_id": uid, "is_super_admin": payload.is_super_admin}


@router.get("/users/super-admin/grantor-status")
async def grantor_status(user: dict = Depends(get_current_user)):
    """Retorna se o usuário atual pode operar o TIK de super admin.
    Frontend usa pra esconder/mostrar o componente."""
    return {
        "can_grant": can_grant_super_admin(user),
        "is_super_admin": is_super_admin(user),
    }
