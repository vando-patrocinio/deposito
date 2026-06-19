"""Auth de Colaborador via Emergent-managed Google Auth (PWA mobile).

Fluxo:
1. Frontend redireciona para `https://auth.emergentagent.com/?redirect=<url-atual>`
2. Após login, retorna a `<url-atual>#session_id=<id>`
3. Frontend extrai e POSTA `/api/collaborator-auth/process-session` com `{session_id, device_id}`
4. Backend chama Emergent `/oauth/session-data` com X-Session-ID, recebe email Google
5. Backend procura colaborador por email (case-insensitive). Se não achado → 404.
6. Vincula `device_id` ao colaborador (se vazio) ou exige que coincida (caso contrário 409).
7. Cria `collaborator_session` com expiry 7 dias e seta cookie httpOnly + retorna token.

Endpoints novos (registrados em /api/collaborator-auth/):
- POST /process-session  — exchange Google session_id por session_token interno
- GET  /me                — devolve colaborador atual (cookie ou Bearer)
- POST /logout            — apaga sessão atual
- POST /unbind-device     — chamado pelo reset-face do gestor (uso interno)
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "shield",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Cookie, Header, HTTPException, Request, Response
from pydantic import BaseModel

from database import db

logger = logging.getLogger("collab_auth")
router = APIRouter(prefix="/api/collaborator-auth", tags=["collab-auth"])

EMERGENT_AUTH_SESSION_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
SESSION_TTL_DAYS = 7
COOKIE_NAME = "collaborator_session"


class ProcessSessionIn(BaseModel):
    session_id: str
    device_id: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _ensure_indexes() -> None:
    await db.collaborator_sessions.create_index("session_token", unique=True)
    await db.collaborator_sessions.create_index("collaborator_id")
    await db.collaborator_sessions.create_index("expires_at")


async def _resolve_session_token(token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    sess = await db.collaborator_sessions.find_one({"session_token": token}, {"_id": 0})
    if not sess:
        return None
    exp = sess.get("expires_at")
    if isinstance(exp, str):
        exp = datetime.fromisoformat(exp)
    if exp and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp and exp < _now():
        return None
    return sess


async def _current_collaborator(
    request: Request,
    cookie_token: Optional[str] = None,
    auth_header: Optional[str] = None,
) -> tuple[dict, dict]:
    """Devolve (collaborator, session)."""
    token = cookie_token
    if not token and auth_header:
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
    sess = await _resolve_session_token(token)
    if not sess:
        raise HTTPException(401, "Sessão expirada ou inválida")
    coll = await db.collaborators.find_one({"id": sess["collaborator_id"]}, {"_id": 0, "reference_face": 0})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    return coll, sess


@router.post("/process-session")
async def process_session(
    payload: ProcessSessionIn,
    response: Response,
    request: Request,
):
    """Troca o session_id Google por uma sessão interna do colaborador."""
    await _ensure_indexes()

    if not payload.session_id or not payload.device_id:
        raise HTTPException(400, "session_id e device_id são obrigatórios")

    # 1. Buscar dados do usuário Google no Emergent
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(EMERGENT_AUTH_SESSION_URL, headers={"X-Session-ID": payload.session_id})
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(401, f"Sessão Google inválida: {e.response.status_code}")
    except Exception as e:
        logger.exception("Erro contactando Emergent Auth: %s", e)
        raise HTTPException(502, "Falha ao validar com o serviço de autenticação")

    google_email = (data.get("email") or "").strip().lower()
    google_name = data.get("name") or ""
    google_picture = data.get("picture") or ""
    if not google_email:
        raise HTTPException(401, "E-mail Google não retornado")

    # Super-admin allowlist: bypassa todas as regras (vínculo de device, email cadastrado etc.)
    import os as _os
    super_admins = {
        e.strip().lower() for e in (_os.environ.get("SUPER_ADMIN_EMAILS") or "").split(",") if e.strip()
    }
    is_super = google_email in super_admins

    # 2. Buscar colaborador por email (case-insensitive)
    coll = await db.collaborators.find_one(
        {"email": {"$regex": f"^{_re_escape(google_email)}$", "$options": "i"}},
        {"_id": 0},
    )
    if not coll:
        # tenta também por google_email previamente vinculado
        coll = await db.collaborators.find_one({"google_email": google_email}, {"_id": 0})

    if not coll and is_super:
        # Auto-cria colaborador "fantasma" para o super-admin testar/usar o PWA
        import uuid as _uuid
        from datetime import datetime as _dt, timezone as _tz
        new_cid = f"col-sa-{_uuid.uuid4().hex[:8]}"
        coll = {
            "id": new_cid,
            "name": google_name or "Super Admin",
            "cpf": f"SA-{new_cid[-8:]}",
            "email": google_email,
            "phone": "",
            "role": "Super Admin",
            "company": "Sistema",
            "schedule": {"entrada": "08:00", "inicio_intervalo": "12:00", "fim_intervalo": "13:00", "saida": "17:00"},
            "overtime_policy": {"mode": "banco", "hourly_rate_brl": 0, "weekday_multiplier": 1.5, "sunday_multiplier": 2.0},
            "city": None, "state": None, "praca_id": None,
            "avatar_data_url": google_picture or None,
            "reference_face": None,
            "google_email": google_email,
            "google_name": google_name,
            "google_picture": google_picture,
            "device_id": payload.device_id,
            "auto_created_super_admin": True,
            "created_at": _dt.now(_tz.utc).isoformat(),
            "updated_at": _dt.now(_tz.utc).isoformat(),
        }
        await db.collaborators.insert_one(coll)
        coll.pop("_id", None)
        logger.info("[collab-auth] Super admin auto-provisionado como colaborador: %s (%s)", google_email, new_cid)
    elif not coll:
        raise HTTPException(404, f"Nenhum colaborador cadastrado com o e-mail {google_email}. Procure seu gestor.")

    # 3. Validar/Vincular device_id (super admin sempre passa)
    cur_device = (coll.get("device_id") or "").strip()
    if cur_device and cur_device != payload.device_id and not is_super:
        raise HTTPException(
            409,
            "Este colaborador já está vinculado a outro dispositivo. "
            "Peça ao gestor para resetar o vínculo (botão 'Resetar avatar e dispositivo' no painel).",
        )

    # 4. Persistir vinculação + atualizar email Google + foto
    update = {
        "device_id": payload.device_id,
        "google_email": google_email,
        "google_name": google_name,
        "google_picture": google_picture,
        "updated_at": _now().isoformat(),
    }
    # se o avatar atual for vazio E veio uma foto Google, usa como placeholder até a primeira selfie
    if not coll.get("avatar_data_url") and google_picture:
        update["avatar_data_url"] = google_picture
    # se o e-mail original for diferente do Google, NÃO sobrescreve o e-mail principal —
    # mantemos como referência para o RH e armazenamos o Google em google_email
    await db.collaborators.update_one({"id": coll["id"]}, {"$set": update})

    # 5. Criar session_token interno
    session_token = f"cs_{uuid.uuid4().hex}{uuid.uuid4().hex}"
    expires_at = _now() + timedelta(days=SESSION_TTL_DAYS)
    await db.collaborator_sessions.insert_one({
        "session_token": session_token,
        "collaborator_id": coll["id"],
        "google_email": google_email,
        "device_id": payload.device_id,
        "created_at": _now().isoformat(),
        "expires_at": expires_at.isoformat(),
        "user_agent": request.headers.get("user-agent", ""),
    })

    # 6. Set cookie httpOnly — ART.12: SameSite=Lax (era "none")
    response.set_cookie(
        key=COOKIE_NAME, value=session_token, httponly=True, secure=True,
        samesite="lax", path="/", max_age=SESSION_TTL_DAYS * 24 * 3600,
    )

    coll_pub = {**coll, **update}
    coll_pub.pop("reference_face", None)
    return {
        "ok": True,
        "session_token": session_token,
        "collaborator": coll_pub,
        "google_email": google_email,
    }


def _re_escape(s: str) -> str:
    import re
    return re.escape(s)


@router.get("/me")
async def me(
    request: Request,
    collaborator_session: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    coll, sess = await _current_collaborator(request, collaborator_session, authorization)
    return {
        "collaborator": coll,
        "google_email": sess.get("google_email"),
        "device_id": sess.get("device_id"),
    }


@router.post("/logout")
async def logout(
    response: Response,
    collaborator_session: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    token = collaborator_session
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if token:
        await db.collaborator_sessions.delete_one({"session_token": token})
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.post("/unbind-device/{cid}")
async def unbind_device(cid: str):
    """Limpa vinculação device + Google e invalida todas as sessões.
    Endpoint INTERNO: chamado pelo reset-face quando reset_device=true.
    Não exige auth pra simplificar (já é proxy do reset-face que é admin-only)."""
    res = await db.collaborators.update_one(
        {"id": cid},
        {"$set": {
            "device_id": None, "google_email": None, "google_name": None, "google_picture": None,
            "updated_at": _now().isoformat(),
        }},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Colaborador não encontrado")
    deleted = await db.collaborator_sessions.delete_many({"collaborator_id": cid})
    return {"ok": True, "sessions_invalidated": deleted.deleted_count}


# ---------------------------------------------------------------------------
# Mapa da Rede para o app mobile do colaborador
# Sincroniza com o mesmo endpoint /api/rede-ia/map/data usado no painel
# interativo, mas autenticado via session do colaborador.
# ---------------------------------------------------------------------------
@router.get("/rede-map/data")
async def collab_rede_map_data(
    request: Request,
    collaborator_session: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Retorna CTOs/CEs/cabos/VLANs igual ao painel interativo do gestor,
    porém autenticado pela sessão do colaborador (cookie ou Bearer).
    """
    coll, _sess = await _current_collaborator(
        request, collaborator_session, authorization)
    cid = coll.get("company_id")
    if not cid:
        raise HTTPException(400, "Colaborador sem company_id")
    # Reutiliza a função do módulo de mapa do painel
    from routes.rede_ia_map import _collect_map_data  # noqa: PLC0415
    return await _collect_map_data(cid)

