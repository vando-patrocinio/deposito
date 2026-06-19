"""Endpoints de clock-records, collaborators, geofences, timesheets.

Inclui também `dashboard_overtime` (mês simples) que é importado lazy
pelo routes/dashboard.py para tendência/range.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import base64
import calendar
import io
import logging
import os
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import resend
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core import (
    DEMO_COMPANY_ID,
    EVENT_TYPES,
    GEOFENCE_REQUIRED,
    PUBLIC_BLOCK,
    PUBLIC_FACE_FAIL,
    PUBLIC_FENCE_FAIL,
    effective_company_id,
    geocode_address,
    get_current_user,
    get_settings,
    haversine_m,
    is_super_admin,
    llm_chat,
    now_hhmm,
    now_iso,
    parse_json_response,
    require_role,
    resolve_geofence_for,
    strip_data_url,
    tenant_filter,
    today_str,
)
from database import db
from cargo import (
    ALL_CARGOS as CARGOS_VALID,
    clock_in_enabled_for,
    is_atendimento_cargo,
)

logger = logging.getLogger("ponto")
router = APIRouter(prefix="/api", tags=["clock"])


# -------------------------------------------------------------------------
# Helpers — regras automáticas derivadas de `cargo`
# -------------------------------------------------------------------------
def _apply_cargo_rules(payload: "CollaboratorIn", user: dict) -> None:
    """Aplica regras do cargo ao payload. NAO mexe em `clock_in_enabled`
    - o gestor decide via formulario do Cadastro (toggle de ponto).
    - Aux. Administrativo / Atendente -> libera Atendimento WhatsApp
      (somente se o solicitante for auditor/admin).
    Mutaciona o `payload` in-place.
    """
    if not payload.cargo:
        return
    if payload.cargo not in CARGOS_VALID:
        return
    if is_atendimento_cargo(payload.cargo) and user.get("role") in ("auditor", "admin"):
        payload.can_attend_whatsapp = True


def _apply_cargo_rules_dict(data: dict, user: dict) -> None:
    """Versão do `_apply_cargo_rules` para dict. NÃO mexe em
    `clock_in_enabled` — admin tem prioridade absoluta sobre default."""
    cargo = data.get("cargo")
    if not cargo or cargo not in CARGOS_VALID:
        return
    if is_atendimento_cargo(cargo) and user.get("role") in ("auditor", "admin"):
        data["can_attend_whatsapp"] = True


# -------------------------------------------------------------------------
# Models
# -------------------------------------------------------------------------
class WorkSchedule(BaseModel):
    entrada: str = "08:00"
    inicio_intervalo: str = "12:00"
    fim_intervalo: str = "13:00"
    saida: str = "17:00"


class OvertimePolicy(BaseModel):
    mode: str = "banco"
    hourly_rate_brl: float = Field(default=0.0, ge=0.0)
    weekday_multiplier: float = Field(default=1.5, ge=1.0)
    sunday_multiplier: float = Field(default=2.0, ge=1.0)


class CollaboratorIn(BaseModel):
    name: str
    cpf: str
    email: EmailStr
    phone: str
    role: str = "Colaborador de Campo"
    cargo: Optional[str] = None  # tecnico/reparador/instalador/associado/auxiliar_administrativo/atendente
    company: str = "Operação SP"
    schedule: WorkSchedule = Field(default_factory=WorkSchedule)
    overtime_policy: OvertimePolicy = Field(default_factory=OvertimePolicy)
    city: Optional[str] = None
    state: Optional[str] = None
    praca_id: Optional[str] = None
    praca_ids_extra: list[str] = Field(default_factory=list)
    # Dados RH (cabeçalho do espelho de ponto — Portaria 671/2021)
    pis: Optional[str] = None  # PIS/PASEP — obrigatório no cartão de ponto
    admitted_at: Optional[str] = None  # data de admissão ISO YYYY-MM-DD
    matricula: Optional[str] = None  # nº de matrícula interno
    is_test_mode: bool = False  # ADMIN: marca colaborador como TESTE — bypassa cerca/selfie
    clock_in_enabled: Optional[bool] = None  # CTO 13/06/2026 — None = "não tocou", preserva valor anterior. True/False = mudança explícita. Default no POST quando None: True (CLT). Lousa só libera se True.
    active: bool = True  # False = colaborador inativo (desligado, em férias longas, etc)
    can_attend_whatsapp: bool = False  # AUDITOR: libera o menu "Atendimento IA" para o colaborador acessar conversas WhatsApp
    requires_vehicle: bool = False  # Frota: técnico/instalador que precisa operar veículo (gera vistoria semanal)
    current_vehicle_id: Optional[str] = None  # ID do veículo vinculado atualmente (auto-atualizado pelo /fleet/assign)
    fleet_block_reason: Optional[str] = None  # Bloqueio frota (transferência pendente, sinistro etc)
    profile_id: Optional[str] = None  # CTO 12/06/2026: perfil de acesso RBAC (access_profiles). Espalha para o User vinculado.


class Collaborator(CollaboratorIn):
    id: str
    avatar_data_url: Optional[str] = None
    reference_face: Optional[str] = None
    created_at: str
    updated_at: str


class GeofenceIn(BaseModel):
    name: str
    type: str
    address: str
    radius: float = 15.0
    lat: Optional[float] = None
    lng: Optional[float] = None


class Geofence(GeofenceIn):
    id: str
    collaborator_id: str
    lat: float
    lng: float
    active: bool = True
    created_at: str


class GeofenceUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    address: Optional[str] = None
    radius: Optional[float] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    active: Optional[bool] = None


class ClockRecordIn(BaseModel):
    collaborator_id: str
    type: str
    selfie_base64: str
    # lat/lng opcionais — se o navegador bloquear geolocalização, o frontend
    # manda null e o backend trata como "fora da cerca" / "Bloqueado" com
    # mensagem clara, em vez de 422 Unprocessable Entity (sem feedback ao usuário).
    lat: Optional[float] = None
    lng: Optional[float] = None
    public_ip: Optional[str] = None
    offline_created_at: Optional[str] = None
    force_close_open_tickets: bool = False
    client_time_ms: Optional[int] = None  # epoch ms do dispositivo (para sincronização)


async def _has_open_ticket(collaborator_id: str) -> Optional[dict]:
    """Helper local que verifica se o colaborador tem bolha em aberto na lousa."""
    return await db.tickets.find_one(
        {"assigned_collaborator_id": collaborator_id,
         "status": {"$in": ["aberta", "aguardando_atendimento"]}},
        {"_id": 0, "id": 1, "client_snapshot": 1, "status": 1},
    )


async def _force_close_active_tickets(collaborator_id: str) -> int:
    """Move todas bolhas pendentes/abertas do técnico para 'aguardando_atendimento'
    e cria notificação para o gestor. Retorna quantidade encerradas."""
    open_tickets = await db.tickets.find(
        {"assigned_collaborator_id": collaborator_id,
         "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]}},
        {"_id": 0, "id": 1, "company_id": 1},
    ).to_list(500)
    if not open_tickets:
        return 0
    ids = [t["id"] for t in open_tickets]
    await db.tickets.update_many(
        {"id": {"$in": ids}},
        {"$set": {"status": "aguardando_atendimento", "closed_at": now_iso(),
                  "admin_action": "saida_com_pendencia",
                  "admin_notes": "Encerradas pelo colaborador ao bater Saída"}},
    )
    coll = await db.collaborators.find_one({"id": collaborator_id}, {"_id": 0, "name": 1, "company_id": 1})
    notif = {
        "id": f"ntf-{uuid.uuid4().hex[:10]}",
        "type": "ticket_unfinished_on_exit",
        "title": f"⚠️ Saída com {len(ids)} nota(s) em aberto",
        "message": f"{(coll or {}).get('name', 'Técnico')} bateu o ponto de Saída deixando {len(ids)} nota(s) sem finalizar.",
        "collaborator_id": collaborator_id, "ticket_id": None,
        "company_id": (coll or {}).get("company_id") or DEMO_COMPANY_ID,
        "severity": "critical", "read_by": [], "created_at": now_iso(),
    }
    await db.notifications.insert_one(notif)
    return len(ids)


# -------------------------------------------------------------------------
# Face validation helpers (usam IA)
# -------------------------------------------------------------------------
async def validate_face_visible(image_b64: str) -> dict:
    from emergentintegrations.llm.chat import ImageContent, UserMessage
    _, pure = strip_data_url(image_b64)
    chat = await llm_chat(
        session_id=f"face-detect-{uuid.uuid4()}",
        system=(
            "Você é um validador de selfies para registro de ponto. "
            "Analise a imagem e responda APENAS com um JSON válido contendo as chaves: "
            "face_detected (bool), face_clear (bool, se está nítido e bem iluminado), "
            "confidence (0..1), reason (string em português curta). "
            "face_detected=true apenas se um rosto humano frontal estiver claramente visível."
        ),
    )
    msg = UserMessage(text="Valide esta selfie:", file_contents=[ImageContent(image_base64=pure)])
    raw = await chat.send_message(msg)
    parsed = parse_json_response(str(raw))
    return {
        "face_detected": bool(parsed.get("face_detected", False)),
        "face_clear": bool(parsed.get("face_clear", False)),
        "confidence": float(parsed.get("confidence", 0.0) or 0.0),
        "reason": str(parsed.get("reason", "") or ""),
    }


async def compare_faces(reference_b64: str, candidate_b64: str) -> dict:
    from emergentintegrations.llm.chat import ImageContent, UserMessage
    _, ref = strip_data_url(reference_b64)
    _, cand = strip_data_url(candidate_b64)
    chat = await llm_chat(
        session_id=f"face-cmp-{uuid.uuid4()}",
        system=(
            "Você compara duas fotos de rosto para autenticar um colaborador. "
            "Responda APENAS um JSON com as chaves: same_person (bool), confidence (0..1), reason (string curta). "
            "Considere mesma pessoa se traços faciais coincidem, mesmo com variações de iluminação/ângulo."
        ),
    )
    msg = UserMessage(
        text="Foto 1 (cadastro) e Foto 2 (atual). Mesma pessoa?",
        file_contents=[ImageContent(image_base64=ref), ImageContent(image_base64=cand)],
    )
    raw = await chat.send_message(msg)
    parsed = parse_json_response(str(raw))
    return {
        "same_person": bool(parsed.get("same_person", False)),
        "confidence": float(parsed.get("confidence", 0.0) or 0.0),
        "reason": str(parsed.get("reason", "") or ""),
    }


# -------------------------------------------------------------------------
# Collaborators
# -------------------------------------------------------------------------
async def _scope_for_request(request_user: Optional[dict]) -> dict:
    """Retorna filtro de tenant baseado no usuário autenticado (se houver).
    Endpoints públicos do PWA (sem auth) → sem filtro extra (já filtra por id)."""
    if not request_user:
        return {}
    return tenant_filter(request_user)


@router.get("/collaborators")
async def list_collaborators(request: Request):
    """Lista colaboradores. Se autenticado, filtra por tenant; senão, lista todos
    (compat com PWA mobile que ainda usa este endpoint para popular dropdown legado).
    Respeita o header X-Active-Company para drill-down de super admin.
    """
    user = None
    try:
        from auth import decode_token
        auth = (request.headers.get("Authorization") or "")
        if auth.startswith("Bearer "):
            payload = decode_token(auth[7:])
            user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
            if user:
                user["company_id"] = payload.get("company_id") or user.get("company_id") or DEMO_COMPANY_ID
                active = (request.headers.get("X-Active-Company") or "").strip()
                if active:
                    user["_active_company"] = active
    except Exception:
        user = None
    q = tenant_filter(user) if user else {}
    # Lousas virtuais (SALA etc) não aparecem em listagens convencionais.
    q["is_virtual"] = {"$ne": True}
    return await db.collaborators.find(q, {"_id": 0, "reference_face": 0}).to_list(500)


@router.get("/collaborators/me")
async def get_my_collaborator(user: dict = Depends(get_current_user)):
    """Retorna o documento de Collaborator vinculado ao USER logado.

    Mapeia o user → collaborator por:
    1. user.collaborator_id (se foi vinculado explicitamente)
    2. user.email batendo com collaborator.email (case-insensitive)
    3. user.cpf batendo com collaborator.cpf (se ambos cadastrados)

    Usado pelo app mobile do colaborador depois do login email+senha.

    CTO 13/06/2026 — log estruturado pra audit quando lookup falha
    (frustra muito o user em prod quando o link some por limpeza de DB).
    """
    cid_company = (user.get("company_id") or DEMO_COMPANY_ID)
    explicit = user.get("collaborator_id")
    if explicit:
        doc = await db.collaborators.find_one(
            {"id": explicit, "company_id": cid_company},
            {"_id": 0, "reference_face": 0},
        )
        if doc:
            return doc
    em = (user.get("email") or "").lower().strip()
    if em:
        doc = await db.collaborators.find_one(
            {"company_id": cid_company,
             "email": {"$regex": f"^{em}$", "$options": "i"}},
            {"_id": 0, "reference_face": 0},
        )
        if doc:
            return doc
    cpf = (user.get("cpf") or "").strip().replace(".", "").replace("-", "")
    if cpf and len(cpf) == 11:
        doc = await db.collaborators.find_one(
            {"company_id": cid_company, "cpf": cpf},
            {"_id": 0, "reference_face": 0},
        )
        if doc:
            return doc

    # CTO 13/06/2026 — log forense pra investigar "Sessão expirada" no PWA
    import logging
    logging.getLogger("clock").warning(
        "[collaborators/me] vínculo órfão: user_id=%s email=%s "
        "explicit_collab_id=%s company_id=%s — nenhum match nos 3 caminhos",
        user.get("id"), em, explicit, cid_company,
    )
    raise HTTPException(404, "Nenhum colaborador vinculado a esse usuário")


@router.get("/collaborators/{cid}")
async def get_collaborator(cid: str):
    doc = await db.collaborators.find_one({"id": cid}, {"_id": 0, "reference_face": 0})
    if not doc:
        raise HTTPException(404, "Colaborador não encontrado")
    return doc


# ---------------------------------------------------------------------------
# CTO 13/06/2026 — Diagnóstico de colaborador por link único.
# Quando o gestor relata "técnico abriu o link e o app fica vazio", esse
# endpoint mostra o estado REAL daquele ID em prod (sem precisar shell).
# Permissão: gestor / auditor / super admin.
# ---------------------------------------------------------------------------
@router.get("/collaborators/{cid}/diag")
async def diagnose_collaborator(
    cid: str,
    user: dict = Depends(require_role("gestor")),
):
    """Retorna o estado COMPLETO de um collaborator + diagnóstico do link único.

    Resposta sempre 200 — campos `exists`/`reasons` indicam o que está faltando.
    """
    doc = await db.collaborators.find_one({"id": cid}, {"_id": 0, "reference_face": 0})
    reasons: list[str] = []

    if not doc:
        # Talvez o ID tenha sido truncado ou migrado. Tenta achar por prefix.
        prefix_matches = await db.collaborators.find(
            {"id": {"$regex": f"^{cid}"}},
            {"_id": 0, "id": 1, "name": 1, "active": 1, "company_id": 1},
        ).limit(5).to_list(5)
        return {
            "cid_requested": cid,
            "exists": False,
            "reasons": [
                f"Nenhum colaborador com id='{cid}'.",
                "Possível causa: ID truncado no link compartilhado, "
                "colaborador deletado, ou migrado pra outra tenant.",
            ],
            "prefix_matches": prefix_matches,
        }

    if not doc.get("active", True):
        reasons.append("Colaborador está INATIVO (active=false).")
    if not doc.get("name"):
        reasons.append("Sem `name` no documento.")
    if not doc.get("company_id"):
        reasons.append("Sem `company_id` — não pertence a nenhuma tenant.")
    if not doc.get("schedule") or not isinstance(doc.get("schedule"), dict):
        reasons.append(
            "Sem `schedule` configurado (entrada/saída) — "
            "a UI vai renderizar 'undefined / undefined' sem fallback.")
    else:
        sch = doc["schedule"]
        if not sch.get("entrada"):
            reasons.append("`schedule.entrada` vazio.")
        if not sch.get("saida"):
            reasons.append("`schedule.saida` vazio.")
    if not doc.get("praca_id"):
        reasons.append(
            "Sem `praca_id` — UI mostra '—' no campo Praça (não é bloqueante).")

    # Verifica user vinculado (pra login email+senha alternativo)
    user_doc = await db.users.find_one(
        {"$or": [{"collaborator_id": cid},
                 {"email": (doc.get("email") or "").lower()}]},
        {"_id": 0, "id": 1, "email": 1, "role": 1, "active": 1,
         "must_change_password": 1},
    )

    # Conta ponto recente (últimos 7d)
    from datetime import timedelta
    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    recent_clock = await db.clock_records.count_documents(
        {"collaborator_id": cid, "date": {"$gte": seven_days_ago}})

    # Conta tickets abertos
    open_tickets = await db.tickets.count_documents(
        {"assigned_collaborator_id": cid,
         "status": {"$in": ["pendente", "aberta"]}})

    return {
        "cid_requested": cid,
        "exists": True,
        "active": doc.get("active", True),
        "reasons": reasons,
        "collaborator": {
            "id": doc.get("id"),
            "name": doc.get("name"),
            "email": doc.get("email"),
            "phone": doc.get("phone"),
            "company_id": doc.get("company_id"),
            "role": doc.get("role"),
            "cargo": doc.get("cargo"),
            "praca_id": doc.get("praca_id"),
            "schedule": doc.get("schedule"),
            "clock_in_enabled": doc.get("clock_in_enabled"),
            "active": doc.get("active", True),
        },
        "user_link": user_doc,
        "recent_clock_records_7d": recent_clock,
        "open_tickets": open_tickets,
        "link_unico_url_pattern": f"/?cid={cid}",
    }




# ---------------------------------------------------------------------------
# Grant mobile access — cria/atualiza User vinculado ao Collaborator para
# que ele possa logar no app mobile via email+senha (em vez do link único).
# Gera senha aleatória curta e retorna pro gestor copiar/enviar via WhatsApp.
# ---------------------------------------------------------------------------
@router.post("/collaborators/{cid}/grant-mobile-access")
async def grant_mobile_access(
    cid: str,
    user: dict = Depends(require_role("gestor")),
):
    import secrets
    import string
    from auth import hash_password

    collab = await db.collaborators.find_one(
        {"id": cid}, {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1,
                      "company_id": 1, "role": 1, "active": 1},
    )
    if not collab:
        raise HTTPException(404, "Colaborador não encontrado")
    if not collab.get("active", True):
        raise HTTPException(400, "Colaborador inativo — reative antes")

    email = (collab.get("email") or "").strip().lower()
    if not email:
        # Sem email cadastrado → gera email-placeholder com phone
        phone = (collab.get("phone") or "").strip()
        digits = "".join([c for c in phone if c.isdigit()])
        if not digits:
            raise HTTPException(
                400, "Colaborador não tem email nem telefone — cadastre antes",
            )
        email = f"tec{digits}@local.app"

    # Senha curta amigável (10 chars: 6 letras+4 dígitos)
    alphabet = string.ascii_lowercase
    pwd_letters = "".join(secrets.choice(alphabet) for _ in range(6))
    pwd_digits = "".join(secrets.choice(string.digits) for _ in range(4))
    new_password = pwd_letters + pwd_digits
    pwd_hash = hash_password(new_password)

    cid_company = collab.get("company_id") or DEMO_COMPANY_ID
    now = now_iso()

    existing = await db.users.find_one({"email": email})
    if existing:
        # Atualiza o user existente: reset de senha + vincula collaborator_id
        await db.users.update_one(
            {"id": existing["id"]},
            {"$set": {
                "password_hash": pwd_hash,
                "collaborator_id": cid,
                "company_id": cid_company,
                "active": True,
                "mobile_access_granted_at": now,
                "active_session_id": None,  # força re-login
                "updated_at": now,
            }},
        )
        action = "reset"
        user_id = existing["id"]
    else:
        # Cria user novo
        user_id = f"usr-{uuid.uuid4().hex[:10]}"
        new_user = {
            "id": user_id,
            "email": email,
            "name": collab.get("name") or "Colaborador",
            "password_hash": pwd_hash,
            "role": "colaborador",
            "roles": ["colaborador"],
            "company_id": cid_company,
            "collaborator_id": cid,
            "active": True,
            "mobile_access_granted_at": now,
            "created_at": now,
            "created_by": user.get("id"),
        }
        await db.users.insert_one(new_user)
        action = "created"

    # Marca o collaborator pra refletir na UI
    await db.collaborators.update_one(
        {"id": cid},
        {"$set": {
            "has_mobile_access": True,
            "mobile_access_email": email,
            "mobile_access_granted_at": now,
        }},
    )

    return {
        "ok": True,
        "action": action,
        "user_id": user_id,
        "email": email,
        "password": new_password,  # plain text — gestor copia/envia
        "collaborator_name": collab.get("name"),
        "phone": collab.get("phone"),
        "company_id": cid_company,
    }


@router.post("/collaborators/migrate-cargo")
async def migrate_cargo(user: dict = Depends(require_role("administrador"))):
    """Aplica heurística para preencher `cargo` em colaboradores legados.

    Idempotente — só toca em docs onde `cargo` está vazio. Heurística:
      - role contém "atendente"  → atendente
      - role contém "admin" (não 'administra') → auxiliar_administrativo
      - role contém "reparador"  → reparador
      - role contém "instalador" → instalador
      - role contém "associado"  → associado
      - resto → tecnico (default seguro)

    Também sincroniza `clock_in_enabled` e `can_attend_whatsapp` conforme
    as regras de cargo.
    """
    from cargo import infer_cargo_from_legacy
    cid_company = effective_company_id(user) or DEMO_COMPANY_ID
    filt = {"company_id": cid_company,
             "$or": [{"cargo": {"$exists": False}},
                       {"cargo": None}, {"cargo": ""}]}
    updated = 0
    async for c in db.collaborators.find(filt, {"_id": 0, "id": 1, "role": 1}):
        cargo = infer_cargo_from_legacy(c.get("role"))
        await db.collaborators.update_one(
            {"id": c["id"], "company_id": cid_company},
            {"$set": {
                "cargo": cargo,
                "clock_in_enabled": clock_in_enabled_for(cargo),
                "updated_at": now_iso(),
            }},
        )
        updated += 1
    return {"updated": updated}

async def _validate_profile_assignment(
    profile_id: str, company_id: str, requester: dict,
) -> dict:
    """Valida que profile_id existe no tenant + aplica guard Super Admin.

    - Profile_id deve existir em `access_profiles` do tenant.
    - Se o perfil é Super Admin, apenas requester com flag is_super_admin
      legado OU já vinculado ao perfil Super Admin pode atribuir.
    Retorna o doc do profile validado.
    """
    from services.access_profiles import get_profile, user_has_super_admin_profile
    p = await get_profile(profile_id, company_id)
    if not p:
        raise HTTPException(404, "Perfil de acesso não encontrado neste tenant")
    if p.get("is_super_admin_profile") or p.get("key") == "super_admin":
        allowed = is_super_admin(requester) or await user_has_super_admin_profile(requester)
        if not allowed:
            raise HTTPException(
                403,
                "Apenas um Super Admin pode atribuir o perfil Super Admin a "
                "um colaborador.",
            )
    return p




@router.post("/collaborators")
async def create_collaborator(payload: CollaboratorIn, user: dict = Depends(require_role("gestor"))):
    cid_company = effective_company_id(user) or DEMO_COMPANY_ID
    # Limite do plano
    co = await db.companies.find_one({"id": cid_company}, {"_id": 0, "max_collaborators": 1})
    if co:
        cur = await db.collaborators.count_documents({"company_id": cid_company})
        max_c = int(co.get("max_collaborators", 25))
        if cur >= max_c:
            raise HTTPException(402, f"Limite do plano atingido ({max_c} colaboradores). Faça upgrade do plano.")
    # Regra de negócio: só AUDITOR pode liberar acesso ao Atendimento WhatsApp.
    # Gestor cria o colaborador, mas o flag só pode ser ligado por auditor.
    if payload.can_attend_whatsapp and user.get("role") not in ("auditor", "admin"):
        payload.can_attend_whatsapp = False
    # Aplica regras automáticas derivadas do `cargo`
    _apply_cargo_rules(payload, user)
    # CTO 12/06/2026 — valida profile_id se informado e aplica guard Super Admin
    if payload.profile_id:
        await _validate_profile_assignment(payload.profile_id, cid_company, user)
    # CTO 13/06/2026 — Default POST quando clock_in_enabled=None: aplica regra
    # do cargo (associado=False, resto=True). Gestor pode marcar False
    # explicitamente no form (ex.: estagiário/PJ).
    if payload.clock_in_enabled is None:
        payload.clock_in_enabled = clock_in_enabled_for(payload.cargo)
    cid = f"col-{uuid.uuid4().hex[:8]}"
    now = now_iso()
    coll = Collaborator(id=cid, **payload.model_dump(), created_at=now, updated_at=now)
    doc = coll.model_dump()
    doc["company_id"] = cid_company
    try:
        await db.collaborators.insert_one(doc)
    except Exception as e:
        raise HTTPException(400, f"Erro ao criar (CPF duplicado?): {e}")
    # CTO 12/06/2026 — atribui code LIGO-NNNN ao novo colaborador
    try:
        from services.collaborator_code import get_or_assign_code
        new_code = await get_or_assign_code(cid, cid_company)
        if new_code:
            doc["code"] = new_code
    except Exception as e:  # noqa: BLE001
        logger.warning("[create_collaborator] code falhou: %s", e)
    out = coll.model_dump(exclude={"reference_face"})
    out["company_id"] = cid_company
    out["code"] = doc.get("code")
    return out


@router.put("/collaborators/{cid}")
async def update_collaborator(cid: str, payload: CollaboratorIn, user: dict = Depends(require_role("gestor"))):
    # Tenant scope
    if not is_super_admin(user):
        existing = await db.collaborators.find_one({"id": cid}, {"company_id": 1})
        if not existing or existing.get("company_id") != user.get("company_id"):
            raise HTTPException(404, "Colaborador não encontrado")
    prev = await db.collaborators.find_one({"id": cid},
                                           {"_id": 0, "active": 1, "name": 1,
                                            "company_id": 1,
                                            "cargo": 1,
                                            "can_attend_whatsapp": 1})
    data = payload.model_dump()
    data["updated_at"] = now_iso()
    # CTO 11/06/2026: blindagem contra payload incompleto que perderia o cargo.
    # Se o cliente NÃO passou `cargo` (None) mas o doc atual TEM cargo, mantém.
    # Sem isso, toggles parciais (ex.: Bate ponto: OFF) apagavam "tecnico" e o
    # colaborador aparecia como "COLABORADOR EXTERNO" no painel.
    if data.get("cargo") in (None, "", "null") and (prev or {}).get("cargo"):
        data["cargo"] = prev["cargo"]
    # CTO 12/06/2026: blindagem similar para profile_id — toggles parciais
    # (toggleClockInEnabled, etc.) enviam payload completo do CollaboratorIn
    # com profile_id=None por default, o que zeraria o vínculo. Só zera de
    # fato se o cliente passou explicitamente uma string vazia "".
    cur_pid = await db.collaborators.find_one(
        {"id": cid}, {"_id": 0, "profile_id": 1},
    )
    cur_pid_val = (cur_pid or {}).get("profile_id")
    if data.get("profile_id") is None and cur_pid_val:
        data["profile_id"] = cur_pid_val
    elif data.get("profile_id") == "":
        data["profile_id"] = None
    # Marca quando foi desativado (para o KPI de perdas pendentes)
    if data.get("active") is False and (prev or {}).get("active") is not False:
        data["deactivated_at"] = now_iso()
    # CTO 13/06/2026 — BLINDAGEM clock_in_enabled (igual cargo e profile_id):
    # se cliente NÃO mandou o flag (None), preserva o valor atual no DB.
    # Sem isso, edits parciais (toggle de cargo, mudança de nome) sobrescreviam
    # `clock_in_enabled` de False pra True silenciosamente — o que fazia o app
    # do colaborador sumir o botão "Você não bate ponto" e abrir tela de ponto.
    if data.get("clock_in_enabled") is None:
        prev_clock = await db.collaborators.find_one(
            {"id": cid}, {"_id": 0, "clock_in_enabled": 1},
        )
        prev_val = (prev_clock or {}).get("clock_in_enabled")
        data["clock_in_enabled"] = True if prev_val is None else bool(prev_val)
    # Permissão: SÓ auditor pode mexer no flag can_attend_whatsapp.
    # Se gestor tentar mudar, mantemos o valor anterior (silenciosamente).
    if user.get("role") not in ("auditor", "admin"):
        prev_flag = bool((prev or {}).get("can_attend_whatsapp"))
        data["can_attend_whatsapp"] = prev_flag
    # Reaplica regras de cargo (mesma lógica do POST)
    _apply_cargo_rules_dict(data, user)
    # CTO 12/06/2026 — valida profile_id se mudou e aplica guard Super Admin
    company_id = (prev or {}).get("company_id") or user.get("company_id") or DEMO_COMPANY_ID
    if "profile_id" in data:
        new_pid = data.get("profile_id") or None
        # Busca o profile_id atual no Mongo para comparar (prev no select acima
        # não inclui profile_id, então busca diretamente)
        cur = await db.collaborators.find_one(
            {"id": cid}, {"_id": 0, "profile_id": 1},
        )
        prev_pid = (cur or {}).get("profile_id")
        if new_pid != prev_pid:
            # Atribuição/troca: valida o NOVO perfil (se não nulo)
            if new_pid:
                await _validate_profile_assignment(new_pid, company_id, user)
            # Revogação de Super Admin: também exige Super Admin no solicitante
            if prev_pid:
                from services.access_profiles import (
                    is_super_admin_profile_id,
                    user_has_super_admin_profile,
                )
                if await is_super_admin_profile_id(prev_pid, company_id):
                    allowed = is_super_admin(user) or await user_has_super_admin_profile(user)
                    if not allowed:
                        raise HTTPException(
                            403,
                            "Apenas um Super Admin pode revogar o perfil Super "
                            "Admin de um colaborador.",
                        )
    res = await db.collaborators.update_one({"id": cid}, {"$set": data})
    if res.matched_count == 0:
        raise HTTPException(404, "Colaborador não encontrado")
    # Sincroniza permissão com User vinculado (se houver) — assim a sidebar
    # do colaborador vê o menu "Atendimento IA" imediatamente após salvar.
    # CTO 13/06/2026 — vínculo expandido: não basta `collaborator_id == cid`,
    # tem que olhar `email` e `mobile_access_email` também. Sem isso, users
    # criados antes do vínculo explícito (collaborator_id=null) ficavam
    # desincronizados. Bug real PROD: Jefferson colab admin não pegava role.
    def _user_link_filter() -> dict:
        emails = []
        for e in (
            (prev or {}).get("email"), data.get("email"),
            (prev or {}).get("mobile_access_email"),
            data.get("mobile_access_email"),
        ):
            if e:
                el = str(e).strip().lower()
                if el and el not in emails:
                    emails.append(el)
        ors: list = [{"collaborator_id": cid}]
        if emails:
            ors.append({"email": {"$in": emails}})
            ors.append({"mobile_access_email": {"$in": emails}})
        return {"company_id": company_id, "$or": ors}

    try:
        await db.users.update_many(
            _user_link_filter(),
            {"$set": {
                "can_attend_whatsapp": bool(data.get("can_attend_whatsapp")),
                "updated_at": now_iso(),
            }},
        )
    except Exception as _e:
        logger.warning("[collab] sync can_attend_whatsapp falhou: %s", _e)
    # CTO 12/06/2026 — espalha o profile_id (e suas access_tags) para o User vinculado.
    # CTO 13/06/2026 — TAMBÉM atualiza o legacy `role` baseado no profile,
    # pois o RBAC de várias rotas (/api/propostas, /api/saas/*, etc.) ainda
    # checa role e não access_tags. Sem isso, gestor coloca colab no perfil
    # "Administrador" mas continua 403 pra qualquer recurso só-gestor.
    if "profile_id" in data:
        try:
            new_pid = data.get("profile_id") or None
            update_fields: dict = {"profile_id": new_pid, "updated_at": now_iso()}
            if new_pid:
                from services.access_profiles import get_profile
                p = await get_profile(new_pid, company_id)
                if p:
                    update_fields["access_tags"] = list(p.get("access_tags") or [])
                    # Mapeia role legado a partir do profile:
                    # 1) is_super_admin=true → administrador
                    # 2) role_mapping explícito vence (gestor/atendimento/etc.)
                    # 3) Nome canônico ("Administrador"/"Super Admin"/"Gestor"
                    #    /"Atendimento"/"Auditor"/"Financeiro") → role correspondente
                    # 4) caso contrário, NÃO troca role (preserva o atual).
                    mapped_role: str | None = None
                    if p.get("is_super_admin"):
                        mapped_role = "administrador"
                    elif p.get("role_mapping"):
                        mapped_role = str(p["role_mapping"]).lower().strip()
                    else:
                        name_norm = (p.get("name") or "").lower().strip()
                        canon = {
                            "super admin": "administrador",
                            "administrador": "administrador",
                            "admin": "administrador",
                            "gestor": "gestor",
                            "atendimento": "atendimento",
                            "auditor": "auditor",
                            "financeiro": "financeiro",
                            "tecnico": "tecnico",
                            "técnico": "tecnico",
                            "colaborador": "colaborador",
                        }
                        mapped_role = canon.get(name_norm)
                    if mapped_role:
                        update_fields["role"] = mapped_role
            await db.users.update_many(
                _user_link_filter(),
                {"$set": update_fields},
            )
        except Exception as _e:  # noqa: BLE001
            logger.warning("[collab] sync profile_id falhou: %s", _e)
    # Notifica gestor se desativou e há pertences ativos pendentes de devolução
    if data.get("active") is False and (prev or {}).get("active") is not False:
        try:
            await _notify_pending_assets_on_deactivation(prev or {}, cid)
        except Exception as _e:
            logger.warning("[assets] notify pending falhou: %s", _e)
    return await get_collaborator(cid)


async def _notify_pending_assets_on_deactivation(prev: dict, cid: str) -> None:
    """Cria notificação para o gestor quando um colaborador desativado tem
    pertences ativos não devolvidos."""
    company_id = prev.get("company_id") or "co-demo"
    pending = await db.collaborator_assets.count_documents(
        {"company_id": company_id, "collaborator_id": cid, "status": "ativo"})
    if pending == 0:
        return
    await db.notifications.insert_one({
        "id": f"notif-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "type": "assets_pending_return",
        "audience_role": "gestor",
        "title": f"⚠ {prev.get('name', 'Colaborador')} foi desativado com {pending} pertence(s) ativo(s)",
        "body": "Cobrança/devolução pendente. Acesse Cadastro → Pertences para iniciar o processo.",
        "data": {"collaborator_id": cid, "pending_count": pending},
        "created_at": now_iso(),
        "read_by": [],
    })


@router.delete("/collaborators/{cid}")
async def delete_collaborator(cid: str, user: dict = Depends(require_role("gestor"))):
    if not is_super_admin(user):
        existing = await db.collaborators.find_one({"id": cid}, {"company_id": 1})
        if not existing or existing.get("company_id") != user.get("company_id"):
            raise HTTPException(404, "Colaborador não encontrado")
    await db.collaborators.delete_one({"id": cid})
    await db.geofences.delete_many({"collaborator_id": cid})
    await db.clock_records.delete_many({"collaborator_id": cid})
    return {"ok": True}


@router.post("/collaborators/{cid}/reset-face")
async def reset_collaborator_face(cid: str, reset_device: bool = False):
    """Limpa o avatar/face de referência em TODOS os locais ligados a este
    colaborador (simétrico ao upload de foto e à 1ª selfie do ponto):
      - collaborators.{reference_face, avatar_data_url, foto_id, foto_id_updated_at}
      - users.avatar_url (do user vinculado pelo email/google_email)
    Se `reset_device=True`, zera também device_id + vínculo Google + sessões.

    Importante: só afeta o colaborador identificado por `cid`.
    """
    coll = await db.collaborators.find_one(
        {"id": cid},
        {"_id": 0, "id": 1, "email": 1, "google_email": 1, "company_id": 1},
    )
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")

    update = {
        "reference_face": None,
        "avatar_data_url": None,
        "foto_id": None,
        "foto_id_updated_at": None,
        "updated_at": now_iso(),
    }
    if reset_device:
        update["device_id"] = None
        update["google_email"] = None
        update["google_name"] = None
        update["google_picture"] = None
    await db.collaborators.update_one({"id": cid}, {"$set": update})

    # Propaga limpeza no users.avatar_url do user vinculado (chat/lousa/ranking)
    email = (coll.get("google_email") or coll.get("email") or "").lower().strip()
    user_updated = False
    if email:
        ur = await db.users.update_one(
            {"email": email},
            {"$set": {"avatar_url": None, "updated_at": now_iso()}},
        )
        user_updated = ur.matched_count > 0

    sessions_invalidated = 0
    if reset_device:
        deleted = await db.collaborator_sessions.delete_many({"collaborator_id": cid})
        sessions_invalidated = deleted.deleted_count
    return {
        "ok": True,
        "reset_device": bool(reset_device),
        "sessions_invalidated": sessions_invalidated,
        "user_avatar_cleared": user_updated,
        "message": "Avatar e foto de referência removidos." + (
            " Dispositivo e vínculo Google também resetados." if reset_device else ""
        ),
    }


@router.post("/collaborators/{cid}/photo")
async def upload_collaborator_photo(cid: str, payload: dict):
    """Sobe a foto do crachá (`foto_id`) do colaborador.

    Body JSON: {"photo_data_url": "data:image/jpeg;base64,..."}.
    Atualiza simultaneamente:
      - collaborator.avatar_data_url (base64) — usada em todo o sistema
      - collaborator.foto_id          (mesmo conteúdo, semântica de "foto crachá")
      - collaborator.foto_id_updated_at
    Se houver `user` vinculado pelo google_email, atualiza também `users.avatar_url`
    pra deixar consistente no chat, ranking, lousa, etc.
    """
    data_url = (payload or {}).get("photo_data_url") or ""
    if not data_url.startswith("data:image/"):
        raise HTTPException(400, "Forneça `photo_data_url` em formato data:image/...;base64,...")
    # Limite de ~3MB (data URL chega a ~33% maior que o binário)
    if len(data_url) > 4_500_000:
        raise HTTPException(413, "Imagem muito grande — máx ~3MB.")
    now = now_iso()
    update = {
        "avatar_data_url": data_url,
        "foto_id": data_url,
        "foto_id_updated_at": now,
        "updated_at": now,
    }
    res = await db.collaborators.update_one({"id": cid}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(404, "Colaborador não encontrado")
    # Propaga pro user vinculado (mesmo email) — chat, lousa, ranking, etc.
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0, "google_email": 1, "email": 1})
    email = (coll or {}).get("google_email") or (coll or {}).get("email")
    user_updated = False
    if email:
        ur = await db.users.update_one(
            {"email": email.lower().strip()},
            {"$set": {"avatar_url": data_url, "updated_at": now}},
        )
        user_updated = ur.matched_count > 0
    return {"ok": True, "user_updated": user_updated, "foto_id_updated_at": now}


# -------------------------------------------------------------------------
# Geofences
# -------------------------------------------------------------------------
@router.get("/collaborators/{cid}/geofences")
async def list_geofences(cid: str):
    return await db.geofences.find({"collaborator_id": cid, "active": True}, {"_id": 0}).to_list(100)


@router.post("/collaborators/{cid}/geofences")
async def create_geofence(cid: str, payload: GeofenceIn):
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    if payload.lat is not None and payload.lng is not None:
        lat, lng, display = float(payload.lat), float(payload.lng), payload.address
    else:
        geo = await geocode_address(payload.address)
        lat, lng, display = geo.lat, geo.lng, geo.display_name
    gid = f"geo-{uuid.uuid4().hex[:8]}"
    doc = Geofence(
        id=gid, collaborator_id=cid, name=payload.name, type=payload.type,
        address=display, lat=lat, lng=lng, radius=payload.radius or 15.0,
        active=True, created_at=now_iso(),
    ).model_dump()
    doc["company_id"] = coll.get("company_id") or DEMO_COMPANY_ID
    await db.geofences.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/geofences/{gid}")
async def update_geofence(gid: str, payload: GeofenceUpdate):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(400, "Nada para atualizar.")
    res = await db.geofences.update_one({"id": gid}, {"$set": data})
    if res.matched_count == 0:
        raise HTTPException(404, "Cerca não encontrada")
    return await db.geofences.find_one({"id": gid}, {"_id": 0})


@router.delete("/geofences/{gid}")
async def delete_geofence(gid: str):
    await db.geofences.update_one({"id": gid}, {"$set": {"active": False}})
    return {"ok": True}


class DuplicateFenceIn(BaseModel):
    target_collaborator_ids: list[str] = Field(..., min_length=1)


@router.post("/geofences/{gid}/duplicate")
async def duplicate_geofence(gid: str, payload: DuplicateFenceIn):
    """Clona uma cerca para um ou mais colaboradores.
    Pula colaborador-alvo que já tenha cerca ativa com o mesmo `name`.
    """
    src = await db.geofences.find_one({"id": gid, "active": True}, {"_id": 0})
    if not src:
        raise HTTPException(404, "Cerca de origem não encontrada ou inativa")
    targets = await db.collaborators.find(
        {"id": {"$in": payload.target_collaborator_ids}},
        {"_id": 0, "id": 1, "name": 1, "company_id": 1},
    ).to_list(500)
    if not targets:
        raise HTTPException(404, "Nenhum colaborador-alvo encontrado")
    created: list[dict] = []
    skipped: list[dict] = []
    for t in targets:
        if t["id"] == src["collaborator_id"]:
            skipped.append({"collaborator_id": t["id"], "reason": "mesmo_colaborador"})
            continue
        dup = await db.geofences.find_one(
            {"collaborator_id": t["id"], "active": True, "name": src["name"]},
            {"_id": 0, "id": 1},
        )
        if dup:
            skipped.append({"collaborator_id": t["id"], "reason": "ja_existe", "existing_id": dup["id"]})
            continue
        new_doc = {
            "id": f"geo-{uuid.uuid4().hex[:8]}",
            "collaborator_id": t["id"],
            "company_id": t.get("company_id") or src.get("company_id") or DEMO_COMPANY_ID,
            "name": src["name"],
            "type": src["type"],
            "address": src["address"],
            "lat": src["lat"],
            "lng": src["lng"],
            "radius": src["radius"],
            "active": True,
            "created_at": now_iso(),
            "duplicated_from": gid,
        }
        await db.geofences.insert_one(new_doc)
        new_doc.pop("_id", None)
        created.append({"collaborator_id": t["id"], "collaborator_name": t["name"], "fence_id": new_doc["id"]})
    return {"ok": True, "created": created, "skipped": skipped, "source_fence_id": gid}


# -------------------------------------------------------------------------
# Clock records
# -------------------------------------------------------------------------
def _next_expected_event(records_today: list[dict]) -> str:
    valid = [r for r in records_today if r["status"] not in ("Recusado", "Bloqueado")]
    valid = sorted(valid, key=lambda r: r["time"])
    if not valid:
        return "Entrada"
    last = valid[-1]["type"]
    return {
        "Entrada": "Início intervalo",
        "Início intervalo": "Fim intervalo",
        "Fim intervalo": "Saída",
        "Saída": "Entrada",
    }.get(last, "Entrada")


@router.get("/collaborators/{cid}/today")
async def collaborator_today(cid: str):
    today = today_str()
    records = await db.clock_records.find({"collaborator_id": cid, "date": today}, {"_id": 0}).to_list(100)
    return {"date": today, "next_expected": _next_expected_event(records), "records": records}


def _build_record(*, rid, cid, ev, today, hhmm, geofence, distance, status, note,
                  internal_reason, public_block, selfie_url, face_validation, public_ip, audit,
                  company_id=None) -> dict:
    geofence_required = ev in GEOFENCE_REQUIRED
    return {
        "id": rid, "protocol": rid, "collaborator_id": cid, "type": ev,
        "company_id": company_id or DEMO_COMPANY_ID,
        "date": today, "time": hhmm, "server_time": hhmm,
        "geofence_id": geofence["id"] if geofence else None,
        "geofence_name": geofence["name"] if geofence else None,
        "inside_fence": bool(geofence) if geofence_required else None,
        "geo_status": (
            "Dentro da cerca" if geofence else ("Fora da cerca" if geofence_required else "Cerca não exigida")
        ),
        "distance_m": round(distance, 2) if distance is not None else None,
        "status": status, "selfie_url": selfie_url, "public_ip": public_ip,
        "location_source": "GPS + internet/rede",
        "note": note, "public_block_message": public_block, "internal_block_reason": internal_reason,
        "face_validation": face_validation, "audit": audit, "created_at": now_iso(),
    }


@router.post("/clock-records")
async def create_clock_record(payload: ClockRecordIn, request: Request):
    if payload.type not in EVENT_TYPES:
        raise HTTPException(400, "Tipo de evento inválido.")
    coll = await db.collaborators.find_one({"id": payload.collaborator_id})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    # Bloqueio por cargo: Associado não bate ponto
    if not clock_in_enabled_for(coll.get("cargo")):
        raise HTTPException(
            403,
            f"⛔ Cargo {coll.get('cargo')!r} não bate ponto. "
            "Apenas Técnico, Reparador, Instalador e cargos administrativos "
            "podem registrar ponto.",
        )

    # ---- TIME SYNC: valida horário do dispositivo vs servidor (se configurado) ----
    # Pulado apenas para admin/auditor logado (modo teste de sessão admin).
    # Colaborador com is_test_mode AINDA valida drift (pula só cerca/selfie).
    company_id = coll.get("company_id") or "co-demo"
    settings_doc = await db.settings.find_one({"id": company_id}, {"_id": 0}) or {}
    skip_time_sync = False
    try:
        from auth import decode_token
        _ah = (request.headers.get("Authorization") or "")
        if _ah.startswith("Bearer "):
            _pj = decode_token(_ah[7:])
            _au = await db.users.find_one({"id": _pj["sub"]}, {"_id": 0, "role": 1})
            if _au and _au.get("role") in ("administrador", "auditor"):
                skip_time_sync = True
    except Exception:
        pass
    if settings_doc.get("time_sync_enabled") and payload.client_time_ms and not skip_time_sync:
        from datetime import datetime as _dt, timezone as _tz
        server_ms = int(_dt.now(_tz.utc).timestamp() * 1000)
        drift_s = abs(server_ms - payload.client_time_ms) / 1000
        max_drift = int(settings_doc.get("time_sync_max_drift_seconds", 60))
        if drift_s > max_drift:
            raise HTTPException(
                412,
                f"Horário do dispositivo dessincronizado ({int(drift_s)}s de diferença, "
                f"máximo permitido: {max_drift}s). Sincronize o relógio do dispositivo.",
            )

    # ---- TEST MODE (admin OR collaborator marked as test) ----
    is_admin_test = False
    admin_actor = None
    # 1. Colaborador marcado como teste no cadastro → bypassa cerca/selfie sempre
    if coll.get("is_test_mode"):
        is_admin_test = True
        admin_actor = "colaborador_teste"
    # 1b. Colaborador NÃO-CLT (clock_in_enabled=false) → também bypassa cerca/selfie.
    # Em teoria ele nem bate ponto (app esconde a tela), mas se chamar via API direta
    # ou via admin, não devemos exigir cerca/selfie de quem foi cadastrado como externo.
    if not is_admin_test and coll.get("clock_in_enabled") is False:
        is_admin_test = True
        admin_actor = "colaborador_externo"
    # 2. Admin/auditor logado → também bypassa
    if not is_admin_test:
        try:
            from auth import decode_token
            auth_header = (request.headers.get("Authorization") or "")
            if auth_header.startswith("Bearer "):
                payload_jwt = decode_token(auth_header[7:])
                admin_user = await db.users.find_one(
                    {"id": payload_jwt["sub"]}, {"_id": 0, "role": 1, "email": 1, "name": 1},
                )
                if admin_user and admin_user.get("role") in ("administrador", "auditor"):
                    is_admin_test = True
                    admin_actor = admin_user.get("email") or admin_user.get("name") or "admin"
        except Exception:
            pass

    # ---- LOUSA STATE MACHINE ----
    # Não permite "Início intervalo" se houver bolha aberta
    if payload.type == "Início intervalo":
        open_tk = await _has_open_ticket(payload.collaborator_id)
        if open_tk:
            raise HTTPException(
                412,
                f"Você tem uma nota aberta ('{open_tk['client_snapshot']['name']}'). "
                f"Finalize-a antes de bater Início intervalo.",
            )
    # Saída: se tem bolha aberta E técnico não confirmou encerrar → 409 (frontend pergunta)
    if payload.type == "Saída":
        open_tk = await _has_open_ticket(payload.collaborator_id)
        if open_tk and not payload.force_close_open_tickets:
            raise HTTPException(
                409,
                "Você tem nota(s) em aberto. Confirme com 'force_close_open_tickets=true' "
                "para encerrar e bater Saída.",
            )

    today = today_str()
    hhmm = now_hhmm()
    rid = f"PTO-{uuid.uuid4().hex[:10].upper()}"
    audit = [{"at": now_iso(), "actor": coll.get("name", "colaborador"), "action": "Tentativa de registro"}]
    if is_admin_test:
        audit.append({"at": now_iso(), "actor": admin_actor, "action": "MODO TESTE ADMIN — cerca ignorada"})

    face_check = {}
    if is_admin_test:
        # Modo teste admin: pula validação facial
        face_check = {"face_detected": True, "face_clear": True, "confidence": 1.0,
                      "reason": "Bypass admin test mode"}
        audit.append({"at": now_iso(), "actor": admin_actor, "action": "validate_face: SKIPPED (admin test)"})
    else:
        try:
            face_check = await validate_face_visible(payload.selfie_base64)
        except Exception as e:
            logger.exception("Erro IA validação facial")
            face_check = {"face_detected": False, "face_clear": False, "confidence": 0.0, "reason": f"erro IA: {e}"}
        audit.append({"at": now_iso(), "actor": "IA", "action": f"validate_face: {face_check}"})

    if not face_check.get("face_detected") or not face_check.get("face_clear"):
        rec = _build_record(
            rid=rid, cid=payload.collaborator_id, ev=payload.type, today=today, hhmm=hhmm,
            geofence=None, distance=None, status="Bloqueado", note=PUBLIC_FACE_FAIL,
            internal_reason=f"face_validation: {face_check.get('reason') or 'rosto não detectado'}",
            public_block=PUBLIC_FACE_FAIL, selfie_url=None, face_validation=face_check,
            public_ip=payload.public_ip, audit=audit, company_id=coll.get("company_id"),
        )
        await db.clock_records.insert_one(rec)
        rec.pop("_id", None)
        return rec

    face_match = {}
    if not is_admin_test and coll.get("reference_face"):
        try:
            face_match = await compare_faces(coll["reference_face"], payload.selfie_base64)
        except Exception as e:
            logger.exception("Erro IA comparação")
            face_match = {"same_person": False, "confidence": 0.0, "reason": f"erro IA: {e}"}
        audit.append({"at": now_iso(), "actor": "IA", "action": f"compare_faces: {face_match}"})
        if not face_match.get("same_person") or float(face_match.get("confidence", 0)) < 0.55:
            rec = _build_record(
                rid=rid, cid=payload.collaborator_id, ev=payload.type, today=today, hhmm=hhmm,
                geofence=None, distance=None, status="Bloqueado", note=PUBLIC_BLOCK,
                internal_reason=f"face_mismatch: {face_match.get('reason')}",
                public_block=PUBLIC_BLOCK, selfie_url=None,
                face_validation={"detect": face_check, "compare": face_match},
                public_ip=payload.public_ip, audit=audit, company_id=coll.get("company_id"),
            )
            await db.clock_records.insert_one(rec)
            rec.pop("_id", None)
            return rec

    fence, distance = await resolve_geofence_for(payload.collaborator_id, payload.lat, payload.lng)
    # ---- PRAÇA "NOTA": cerca virtual dinâmica no endereço da bolha ativa ou da próxima ----
    if not fence and coll.get("praca_id") == "NOTA":
        # Tenta usar endereço da bolha aberta primeiro, senão a próxima pendente.
        # Sem coordenadas do dispositivo, não dá pra calcular distância à nota.
        if payload.lat is None or payload.lng is None:
            target_ticket = None
        else:
            target_ticket = await db.tickets.find_one(
                {"assigned_collaborator_id": payload.collaborator_id,
                 "status": {"$in": ["aberta", "aguardando_atendimento"]}},
                {"_id": 0, "client_snapshot": 1, "id": 1, "client_name": 1},
            )
            if not target_ticket:
                target_ticket = await db.tickets.find_one(
                    {"assigned_collaborator_id": payload.collaborator_id, "status": "pendente"},
                    {"_id": 0, "client_snapshot": 1, "id": 1},
                    sort=[("position", 1)],
                )
        snap = (target_ticket or {}).get("client_snapshot") or {}
        if snap.get("latitude") and snap.get("longitude") and payload.lat is not None and payload.lng is not None:
            settings = await db.settings.find_one({"id": coll.get("company_id") or "co-demo"}, {"_id": 0}) or {}
            radius = int(settings.get("nota_fence_radius_m", 80))
            from math import asin, cos, radians, sin, sqrt
            R = 6371000.0
            lat1, lon1, lat2, lon2 = map(radians, [payload.lat, payload.lng, snap["latitude"], snap["longitude"]])
            dlat, dlon = lat2 - lat1, lon2 - lon1
            a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
            dist_to_note = round(2 * R * asin(sqrt(a)))
            if dist_to_note <= radius:
                fence = {
                    "id": f"nota-dyn-{target_ticket['id']}",
                    "name": f"Endereço da nota: {snap.get('name', '')[:30]}",
                    "lat": snap["latitude"], "lng": snap["longitude"],
                    "radius_m": radius,
                    "collaborator_id": payload.collaborator_id,
                    "active": True,
                }
                distance = dist_to_note
                audit.append({
                    "at": now_iso(), "actor": "sistema",
                    "action": f"praca=NOTA → cerca dinâmica em '{snap.get('name','')}': {dist_to_note}m de {radius}m"
                })
    geofence_required = payload.type in GEOFENCE_REQUIRED
    # ADMIN TEST: ignora exigência de cerca
    if geofence_required and not fence and not is_admin_test:
        # Mensagem específica quando o navegador bloqueou geolocalização
        if payload.lat is None or payload.lng is None:
            internal_reason = "geolocalização indisponível (navegador bloqueou ou sem permissão)"
            public_block = "Permita a localização do navegador para bater ponto"
        else:
            internal_reason = f"fora_da_cerca distância={distance}m"
            public_block = PUBLIC_FENCE_FAIL
        rec = _build_record(
            rid=rid, cid=payload.collaborator_id, ev=payload.type, today=today, hhmm=hhmm,
            geofence=None, distance=distance, status="Bloqueado", note=public_block,
            internal_reason=internal_reason,
            public_block=public_block, selfie_url=payload.selfie_base64,
            face_validation={"detect": face_check, "compare": face_match},
            public_ip=payload.public_ip, audit=audit, company_id=coll.get("company_id"),
        )
        await db.clock_records.insert_one(rec)
        rec.pop("_id", None)
        return rec

    rec = _build_record(
        rid=rid, cid=payload.collaborator_id, ev=payload.type, today=today, hhmm=hhmm,
        geofence=fence, distance=distance, status="Válido", note="",
        internal_reason="", public_block="", selfie_url=payload.selfie_base64,
        face_validation={"detect": face_check, "compare": face_match},
        public_ip=payload.public_ip, audit=audit, company_id=coll.get("company_id"),
    )
    # iter215an — Regra global de atendimento por ponto: ao bater "Início
    # intervalo" ou "Saída", se o colaborador tem usuário com role
    # afetada (gestor/administrador/vendedor) e conversas humanas abertas,
    # bloqueamos OU transferimos pra outro humano online.
    if not is_admin_test and payload.type in ("Início intervalo", "Saída"):
        try:
            from services.atendente_duty import enforce_offduty_clock_event
            allowed, duty_msg, target_user, n_moved = (
                await enforce_offduty_clock_event(
                    company_id=coll.get("company_id") or DEMO_COMPANY_ID,
                    collaborator=coll,
                    event_type=payload.type,
                )
            )
            if not allowed:
                raise HTTPException(409, {
                    "code": "NO_ATTENDANT_AVAILABLE",
                    "message": duty_msg,
                    "event_type": payload.type,
                })
            if n_moved > 0:
                audit.append({
                    "at": now_iso(), "actor": "sistema",
                    "action": (
                        f"atendimento: {duty_msg} "
                        f"(destino={target_user.get('name') or target_user.get('id')})"
                        if target_user else duty_msg
                    ),
                })
                rec["audit"] = audit
                rec["duty_handover"] = {
                    "transferred": n_moved,
                    "to_user_id": target_user["id"] if target_user else None,
                    "to_user_name": (target_user.get("name")
                                       if target_user else None),
                    "reason": duty_msg,
                }
        except HTTPException:
            raise
        except Exception as _de:
            logger.warning("[clock] duty enforcement falhou: %s", _de)
    if is_admin_test:
        rec["admin_test_mode"] = True
        rec["test_actor"] = admin_actor
        if not fence:
            rec["geo_status"] = "🧪 Teste admin — cerca ignorada"
    await db.clock_records.insert_one(rec)
    update: dict[str, Any] = {"updated_at": now_iso()}
    if not coll.get("reference_face"):
        # Primeira selfie aprovada vira a foto de referência + avatar oficial.
        # Simétrico ao upload manual de foto (POST /collaborators/{id}/photo):
        # também popula foto_id e propaga pra users.avatar_url do user vinculado.
        update["reference_face"] = payload.selfie_base64
        update["avatar_data_url"] = payload.selfie_base64
        update["foto_id"] = payload.selfie_base64
        update["foto_id_updated_at"] = now_iso()
    await db.collaborators.update_one({"id": payload.collaborator_id}, {"$set": update})

    # Se preencheu a foto agora (1ª selfie), propaga pro user vinculado
    if "foto_id" in update:
        email = ((coll.get("google_email") or coll.get("email")) or "").lower().strip()
        if email:
            await db.users.update_one(
                {"email": email},
                {"$set": {"avatar_url": payload.selfie_base64,
                            "updated_at": now_iso()}},
            )

    # Após Saída com confirmação → força-encerra bolhas e notifica gestor
    if payload.type == "Saída" and payload.force_close_open_tickets:
        moved = await _force_close_active_tickets(payload.collaborator_id)
        rec["closed_open_tickets"] = moved

    rec.pop("_id", None)
    return rec


@router.get("/clock-records")
async def list_clock_records(collaborator_id: Optional[str] = None, status: Optional[str] = None,
                             date_from: Optional[str] = None, date_to: Optional[str] = None):
    q: dict[str, Any] = {}
    if collaborator_id:
        q["collaborator_id"] = collaborator_id
    if status:
        q["status"] = status
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    return await db.clock_records.find(q, {"_id": 0, "selfie_url": 0}).sort([("date", -1), ("time", -1)]).to_list(1000)


@router.get("/clock-records/{rid}")
async def get_clock_record(rid: str):
    doc = await db.clock_records.find_one({"id": rid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Registro não encontrado")
    return doc


@router.post("/clock-records/{rid}/approve")
async def approve_record(rid: str):
    res = await db.clock_records.update_one(
        {"id": rid},
        {"$set": {"status": "Válido"},
         "$push": {"audit": {"at": now_iso(), "actor": "Gestor", "action": "Aprovado"}}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Registro não encontrado")
    return await get_clock_record(rid)


@router.post("/clock-records/{rid}/reject")
async def reject_record(rid: str):
    res = await db.clock_records.update_one(
        {"id": rid},
        {"$set": {"status": "Recusado"},
         "$push": {"audit": {"at": now_iso(), "actor": "Gestor", "action": "Recusado"}}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Registro não encontrado")
    return await get_clock_record(rid)


# -------------------------------------------------------------------------
# Timesheet (cálculo do espelho)
# -------------------------------------------------------------------------
def _hm_to_min(hhmm: str) -> int:
    if not hhmm or ":" not in hhmm:
        return 0
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _night_minutes(start_min: int, end_min: int) -> int:
    """Quantos minutos do intervalo [start_min, end_min) caem na janela
    noturna CLT (22:00 às 05:00 do dia seguinte). Aceita end < start (atravessou meia-noite)."""
    if end_min <= start_min:
        end_min += 24 * 60  # cruzou meia-noite
    # janela noturna em minutos cumulativos a partir de 00:00 do "dia" (00–05 + 22–29)
    night_windows = [(0, 5 * 60), (22 * 60, 29 * 60)]
    total = 0
    for ns, ne in night_windows:
        a = max(start_min, ns)
        b = min(end_min, ne)
        if b > a:
            total += (b - a)
    return total


def _origin_tag(r: dict) -> str:
    """Letra de origem CLT (Portaria 671/2021):
       (I) Incluído manualmente / (P) Pré-assinalado /
       (M) Coletor REP-P Mobile/Web / (C) Coletor REP-P físico."""
    if r.get("manually_edited"):
        return "I"
    if r.get("auto_filled") or r.get("preassinalado"):
        return "P"
    if r.get("rep_collector") or r.get("origin") == "coletor":
        return "C"
    return "M"


def _format_previsto(schedule: WorkSchedule, is_weekend: bool, is_sunday: bool) -> str:
    """Formata o horário previsto (ex: '08:00-12:00 13:00-17:00' ou 'FOLGA')."""
    if is_sunday:
        return "FOLGA DSR"
    if is_weekend:
        return "—"
    parts = []
    if schedule.entrada and schedule.inicio_intervalo:
        parts.append(f"{schedule.entrada}-{schedule.inicio_intervalo}")
    if schedule.fim_intervalo and schedule.saida:
        parts.append(f"{schedule.fim_intervalo}-{schedule.saida}")
    if not parts and schedule.entrada and schedule.saida:
        parts.append(f"{schedule.entrada}-{schedule.saida}")
    return " ".join(parts) if parts else "—"


def _calc_day(records: list[dict], schedule: WorkSchedule, *, is_weekend: bool = False,
              is_sunday: bool = False, is_holiday_day: bool = False) -> dict:
    valid = sorted([r for r in records if r["status"] in ("Válido", "Offline sincronizado")], key=lambda r: r["time"])
    by_type = {r["type"]: r for r in valid}
    total = 0
    interval = 0
    if "Entrada" in by_type and "Saída" in by_type:
        total = max(0, _hm_to_min(by_type["Saída"]["time"]) - _hm_to_min(by_type["Entrada"]["time"]))
        if "Início intervalo" in by_type and "Fim intervalo" in by_type:
            interval = max(0, _hm_to_min(by_type["Fim intervalo"]["time"]) - _hm_to_min(by_type["Início intervalo"]["time"]))
    if is_weekend or is_holiday_day:
        expected = 0
    else:
        expected = max(0, _hm_to_min(schedule.saida) - _hm_to_min(schedule.entrada) -
                       (_hm_to_min(schedule.fim_intervalo) - _hm_to_min(schedule.inicio_intervalo)))
    worked = max(0, total - interval)
    balance = worked - expected

    # ----- Hora noturna (22h-05h CLT) -----
    noturno = 0
    if "Entrada" in by_type and "Saída" in by_type:
        ent = _hm_to_min(by_type["Entrada"]["time"])
        sai = _hm_to_min(by_type["Saída"]["time"])
        noturno = _night_minutes(ent, sai)
        if "Início intervalo" in by_type and "Fim intervalo" in by_type:
            ii = _hm_to_min(by_type["Início intervalo"]["time"])
            fi = _hm_to_min(by_type["Fim intervalo"]["time"])
            noturno = max(0, noturno - _night_minutes(ii, fi))

    # ----- Extras separadas em diurna e noturna -----
    if is_holiday_day or is_sunday:
        overtime_min = worked
        overtime_kind = "sunday_or_holiday" if worked > 0 else None
    elif is_weekend:
        overtime_min = worked
        overtime_kind = "weekday" if worked > 0 else None
    else:
        overtime_min = max(0, worked - expected)
        overtime_kind = "weekday" if overtime_min > 0 else None

    # Aproxima a parcela noturna do extra: proporcional do total trabalhado
    if worked > 0 and overtime_min > 0:
        noturno_share = noturno / worked
        extra_noturna = round(overtime_min * noturno_share)
        extra_diurna = overtime_min - extra_noturna
    else:
        extra_noturna = 0
        extra_diurna = 0

    # ----- Falta / Atraso (saldo negativo em dia útil) -----
    falta_atraso = 0
    if not (is_weekend or is_holiday_day) and balance < 0:
        falta_atraso = -balance  # positivo no relatório (minutos faltantes)

    # ----- Abono (folga, DSR, feriado não trabalhado = previsto computado) -----
    abono = 0
    if (is_holiday_day or is_sunday) and worked == 0:
        # Marca abono igual à jornada padrão de um dia útil (proxy)
        abono = max(0, _hm_to_min(schedule.saida) - _hm_to_min(schedule.entrada) -
                    (_hm_to_min(schedule.fim_intervalo) - _hm_to_min(schedule.inicio_intervalo)))

    missing = []
    if not (is_weekend or is_holiday_day):
        if "Entrada" not in by_type:
            missing.append("Entrada")
        if "Saída" not in by_type:
            missing.append("Saída")
    if is_holiday_day:
        status = "Feriado" if worked == 0 else "Feriado trabalhado"
    elif is_sunday:
        status = "Folga DSR" if worked == 0 else "Domingo trabalhado"
    elif is_weekend:
        status = "Folga" if worked == 0 else "Folga trabalhada"
    else:
        status = "Incompleto" if missing else ("Débito" if balance < 0 else "Extra" if balance > 0 else "Regular")

    # Origens das marcações (I/P/M/C — Portaria 671/2021)
    origens = {}
    for tp, key in [("Entrada", "entrada"), ("Início intervalo", "inicio_intervalo"),
                     ("Fim intervalo", "fim_intervalo"), ("Saída", "saida")]:
        if tp in by_type:
            origens[key] = _origin_tag(by_type[tp])

    return {
        "entrada": by_type.get("Entrada", {}).get("time"),
        "saida": by_type.get("Saída", {}).get("time"),
        "inicio_intervalo": by_type.get("Início intervalo", {}).get("time"),
        "fim_intervalo": by_type.get("Fim intervalo", {}).get("time"),
        "worked": worked, "interval": interval, "expected": expected, "balance": balance,
        "overtime_min": overtime_min, "overtime_kind": overtime_kind,
        "noturno_min": noturno,
        "extra_diurna_min": extra_diurna,
        "extra_noturna_min": extra_noturna,
        "falta_atraso_min": falta_atraso,
        "abono_min": abono,
        "origens": origens,
        "status": status, "missing": missing,
    }


@router.get("/timesheets/{cid}/{year}/{month}")
async def timesheet(cid: str, year: int, month: int):
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    schedule = WorkSchedule(**coll.get("schedule", {}))
    policy = OvertimePolicy(**coll.get("overtime_policy", {}))
    last_day = calendar.monthrange(year, month)[1]
    df = f"{year:04d}-{month:02d}-01"
    dt = f"{year:04d}-{month:02d}-{last_day:02d}"
    records = await db.clock_records.find(
        {"collaborator_id": cid, "date": {"$gte": df, "$lte": dt}},
        {"_id": 0, "selfie_url": 0, "face_validation": 0},
    ).sort([("date", 1), ("time", 1)]).to_list(2000)
    by_date: dict[str, list[dict]] = {}
    for r in records:
        by_date.setdefault(r["date"], []).append(r)

    # ----- Feriados (sistema centralizado /api/feriados) -----
    # Busca todos os feriados da empresa que caem no mês. Filtra por praça:
    # - Se feriado.praca_ids está vazio → vale para TODOS (nacional/empresa)
    # - Se tem IDs → só vale se uma das praças do colaborador estiver na lista
    company_id = coll.get("company_id") or DEMO_COMPANY_ID
    coll_praca_ids: list[str] = []
    if coll.get("praca_id") and coll["praca_id"] != "NOTA":
        coll_praca_ids.append(coll["praca_id"])
    for pid in (coll.get("praca_ids_extra") or []):
        if pid and pid != "NOTA" and pid not in coll_praca_ids:
            coll_praca_ids.append(pid)

    holidays_map: dict[str, dict] = {}
    fers = await db.feriados.find(
        {"company_id": company_id,
         "data": {"$regex": f"^{year:04d}-{month:02d}"}},
        {"_id": 0},
    ).to_list(200)
    for f in fers:
        f_pracas = f.get("praca_ids") or []
        # Filtro: vale se não tem restrição OU se intersecta com praças do colab
        if f_pracas and not any(p in coll_praca_ids for p in f_pracas):
            continue
        d = f.get("data")
        if d:
            holidays_map[d] = {
                "date": d,
                "name": f.get("nome"),
                "scope": f.get("tipo", "nacional"),
                "source": "feriados_central",
            }
    today_s = today_str()
    days = []
    total_worked = 0
    total_balance = 0
    total_ot_weekday = 0
    total_ot_sunday_holiday = 0
    total_noturno = 0
    total_extra_diurna = 0
    total_extra_noturna = 0
    total_falta_atraso = 0
    total_abono = 0
    banco_saldo_acumulado = 0
    for d_num in range(1, last_day + 1):
        d_str = f"{year:04d}-{month:02d}-{d_num:02d}"
        day_records = by_date.get(d_str, [])
        is_future = d_str > today_s
        is_today = d_str == today_s
        weekday = date(year, month, d_num).weekday()
        is_weekend = weekday >= 5
        is_sunday = weekday == 6
        holiday_info = holidays_map.get(d_str)
        is_holiday_day = bool(holiday_info)
        previsto_str = _format_previsto(schedule, is_weekend, is_sunday)
        if is_holiday_day:
            previsto_str = "FERIADO"
        if is_future:
            days.append({
                "date": d_str, "entrada": None, "saida": None, "inicio_intervalo": None, "fim_intervalo": None,
                "worked": 0, "interval": 0, "expected": 0, "balance": 0,
                "overtime_min": 0, "overtime_kind": None,
                "noturno_min": 0, "extra_diurna_min": 0, "extra_noturna_min": 0,
                "falta_atraso_min": 0, "abono_min": 0,
                "previsto": previsto_str,
                "banco_total_min": 0, "banco_saldo_min": banco_saldo_acumulado,
                "origens": {},
                "status": "Futuro", "missing": [],
                "is_future": True, "is_today": False, "is_weekend": is_weekend,
                "is_holiday": is_holiday_day, "holiday": holiday_info,
                "weekday": weekday, "records": [],
            })
            continue
        calc = _calc_day(day_records, schedule, is_weekend=is_weekend, is_sunday=is_sunday, is_holiday_day=is_holiday_day)
        total_worked += calc["worked"]
        total_balance += calc["balance"]
        total_noturno += calc["noturno_min"]
        total_extra_diurna += calc["extra_diurna_min"]
        total_extra_noturna += calc["extra_noturna_min"]
        total_falta_atraso += calc["falta_atraso_min"]
        total_abono += calc["abono_min"]
        if calc.get("overtime_kind") == "weekday":
            total_ot_weekday += calc["overtime_min"]
        elif calc.get("overtime_kind") == "sunday_or_holiday":
            total_ot_sunday_holiday += calc["overtime_min"]
        banco_total_dia = calc["balance"]
        banco_saldo_acumulado += banco_total_dia
        days.append({
            "date": d_str, **calc,
            "previsto": previsto_str,
            "banco_total_min": banco_total_dia,
            "banco_saldo_min": banco_saldo_acumulado,
            "is_future": False, "is_today": is_today, "is_weekend": is_weekend,
            "is_holiday": is_holiday_day, "holiday": holiday_info,
            "weekday": weekday, "records": day_records,
            "manually_edited": any(r.get("manually_edited") for r in day_records),
        })
    rate = float(policy.hourly_rate_brl or 0.0)
    paid_overtime_brl = 0.0
    total_overtime_min = total_ot_weekday + total_ot_sunday_holiday
    if policy.mode == "pago" and rate > 0:
        paid_overtime_brl = (
            (total_ot_weekday / 60.0) * rate * float(policy.weekday_multiplier or 1.5)
            + (total_ot_sunday_holiday / 60.0) * rate * float(policy.sunday_multiplier or 2.0)
        )
    return {
        "collaborator": {
            "id": coll["id"], "name": coll.get("name") or "—",
            "cpf": coll.get("cpf") or "",
            "email": coll.get("email") or "",
            "schedule": coll.get("schedule", {}),
            "overtime_policy": policy.model_dump(),
            "city": coll.get("city"), "state": coll.get("state"),
            "pis": coll.get("pis"),
            "matricula": coll.get("matricula"),
            "admitted_at": coll.get("admitted_at"),
            "hire_date": coll.get("hire_date"),
            "role": coll.get("role"),
            "praca_id": coll.get("praca_id"),
            "company_id": coll.get("company_id"),
        },
        "year": year, "month": month, "days": days,
        "total_worked_min": total_worked,
        "total_balance_min": total_balance,
        "total_overtime_min": total_overtime_min,
        "total_overtime_weekday_min": total_ot_weekday,
        "total_overtime_sunday_holiday_min": total_ot_sunday_holiday,
        "total_noturno_min": total_noturno,
        "total_extra_diurna_min": total_extra_diurna,
        "total_extra_noturna_min": total_extra_noturna,
        "total_falta_atraso_min": total_falta_atraso,
        "total_abono_min": total_abono,
        "banco_saldo_final_min": banco_saldo_acumulado,
        "paid_overtime_brl": round(paid_overtime_brl, 2),
        "policy_mode": policy.mode,
        "hourly_rate_brl": rate,
    }


@router.get("/dashboard/overtime/{year}/{month}")
async def dashboard_overtime(year: int, month: int, company_id: Optional[str] = None):
    """Resumo de horas extras do mês para todos os colaboradores.
    Se `company_id` informado, restringe ao tenant; caso contrário, cross-tenant."""
    coll_q: dict = {} if not company_id else {"company_id": company_id}
    colls = await db.collaborators.find(coll_q, {"_id": 0}).to_list(1000)
    rows = []
    total_pay = 0.0
    total_ot_min = 0
    for c in colls:
        try:
            sheet = await timesheet(c["id"], year, month)
        except HTTPException:
            continue
        except Exception as exc:
            # Defensive: colaborador com dado corrompido não deve derrubar
            # o relatório consolidado do dashboard inteiro.
            import logging
            logging.getLogger("ponto.clock").warning(
                "[dashboard_overtime] skip cid=%s err=%s",
                c.get("id"), exc)
            continue
        rows.append({
            "collaborator_id": c["id"], "name": c["name"],
            "policy_mode": sheet["policy_mode"],
            "total_overtime_min": sheet["total_overtime_min"],
            "total_overtime_weekday_min": sheet["total_overtime_weekday_min"],
            "total_overtime_sunday_holiday_min": sheet["total_overtime_sunday_holiday_min"],
            "paid_overtime_brl": sheet["paid_overtime_brl"],
            "hourly_rate_brl": sheet["hourly_rate_brl"],
            "balance_min": sheet["total_balance_min"],
        })
        total_pay += sheet["paid_overtime_brl"]
        total_ot_min += sheet["total_overtime_min"]
    top3 = sorted([r for r in rows if r["total_overtime_min"] > 0],
                  key=lambda r: r["total_overtime_min"], reverse=True)[:3]
    top3_paid = sorted([r for r in rows if r["policy_mode"] == "pago" and r["paid_overtime_brl"] > 0],
                       key=lambda r: r["paid_overtime_brl"], reverse=True)[:3]
    return {
        "year": year, "month": month,
        "total_paid_brl": round(total_pay, 2), "total_overtime_min": total_ot_min,
        "rows": rows, "top3_overtime": top3, "top3_paid": top3_paid,
    }


# -------------------------------------------------------------------------
# Manual entries / batch fix / delete
# -------------------------------------------------------------------------
class ManualEntry(BaseModel):
    collaborator_id: str
    type: str
    date: str
    time: str
    reason: str
    actor: str = "Gestor"


@router.post("/clock-records/manual")
async def create_or_replace_manual(payload: ManualEntry):
    return await _do_manual_entry(payload)


async def _do_manual_entry(payload: ManualEntry) -> dict:
    if payload.type not in EVENT_TYPES:
        raise HTTPException(400, "Tipo de evento inválido.")
    coll = await db.collaborators.find_one({"id": payload.collaborator_id}, {"_id": 0})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    if not payload.reason or len(payload.reason.strip()) < 3:
        raise HTTPException(400, "Justificativa obrigatória (min 3 caracteres).")
    existing = await db.clock_records.find_one(
        {"collaborator_id": payload.collaborator_id, "date": payload.date,
         "type": payload.type, "status": {"$nin": ["Recusado", "Bloqueado"]}},
        {"_id": 0},
    )
    audit_entry = {
        "at": now_iso(), "actor": payload.actor or "Gestor",
        "action": ("Edição manual" if existing else "Criação manual"),
        "from_time": existing["time"] if existing else None,
        "to_time": payload.time, "reason": payload.reason.strip(),
    }
    if existing:
        await db.clock_records.update_one(
            {"id": existing["id"]},
            {
                "$set": {
                    "time": payload.time, "server_time": payload.time, "status": "Válido",
                    "manually_edited": True, "last_edited_at": now_iso(),
                    "last_edited_by": payload.actor or "Gestor", "last_edit_reason": payload.reason.strip(),
                },
                "$push": {"audit": audit_entry},
            },
        )
        return await db.clock_records.find_one({"id": existing["id"]}, {"_id": 0})
    rid = f"MAN-{uuid.uuid4().hex[:10].upper()}"
    # busca colaborador para herdar company_id
    coll_doc = await db.collaborators.find_one({"id": payload.collaborator_id}, {"_id": 0, "company_id": 1})
    new_doc = {
        "id": rid, "protocol": rid, "collaborator_id": payload.collaborator_id,
        "company_id": (coll_doc or {}).get("company_id") or DEMO_COMPANY_ID,
        "type": payload.type, "date": payload.date, "time": payload.time, "server_time": payload.time,
        "geofence_id": None, "geofence_name": None, "inside_fence": None,
        "geo_status": "Cerca não exigida (manual)", "distance_m": None,
        "status": "Válido", "selfie_url": None, "public_ip": None, "location_source": "manual",
        "note": payload.reason.strip(), "public_block_message": "", "internal_block_reason": "",
        "face_validation": {}, "manually_edited": True, "last_edited_at": now_iso(),
        "last_edited_by": payload.actor or "Gestor", "last_edit_reason": payload.reason.strip(),
        "audit": [audit_entry], "created_at": now_iso(),
    }
    await db.clock_records.insert_one(new_doc)
    new_doc.pop("_id", None)
    return new_doc


class BatchFixRequest(BaseModel):
    collaborator_id: str
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    reason: str
    actor: str = "Gestor"
    overwrite_existing: bool = False


@router.post("/clock-records/manual/batch-fix-schedule")
async def batch_fix_schedule(payload: BatchFixRequest):
    if not payload.reason or len(payload.reason.strip()) < 3:
        raise HTTPException(400, "Justificativa obrigatória (min 3 caracteres).")
    coll = await db.collaborators.find_one({"id": payload.collaborator_id}, {"_id": 0})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    schedule = WorkSchedule(**coll.get("schedule", {}))
    sched_map = {
        "Entrada": schedule.entrada,
        "Início intervalo": schedule.inicio_intervalo,
        "Fim intervalo": schedule.fim_intervalo,
        "Saída": schedule.saida,
    }
    last_day = calendar.monthrange(payload.year, payload.month)[1]
    today_s = today_str()
    created = 0
    skipped = 0
    days_affected: list[str] = []
    for d_num in range(1, last_day + 1):
        d_str = f"{payload.year:04d}-{payload.month:02d}-{d_num:02d}"
        if d_str > today_s:
            continue
        wd = date(payload.year, payload.month, d_num).weekday()
        if wd >= 5:
            continue
        day_records = await db.clock_records.find(
            {"collaborator_id": payload.collaborator_id, "date": d_str,
             "status": {"$nin": ["Recusado", "Bloqueado"]}},
            {"_id": 0},
        ).to_list(50)
        existing_types = {r["type"] for r in day_records}
        for ev_type, ev_time in sched_map.items():
            if ev_type in existing_types and not payload.overwrite_existing:
                skipped += 1
                continue
            try:
                await _do_manual_entry(ManualEntry(
                    collaborator_id=payload.collaborator_id, type=ev_type, date=d_str,
                    time=ev_time, reason=payload.reason.strip(), actor=payload.actor or "Gestor",
                ))
                created += 1
                if d_str not in days_affected:
                    days_affected.append(d_str)
            except HTTPException:
                skipped += 1
    return {
        "ok": True, "created_or_updated": created, "skipped": skipped,
        "days_affected": days_affected,
        "message": f"{created} marcação(ões) preenchida(s) em {len(days_affected)} dia(s).",
    }


@router.delete("/clock-records/{rid}")
async def delete_clock_record(rid: str, reason: Optional[str] = None):
    audit_entry = {"at": now_iso(), "actor": "Gestor", "action": "Removido manualmente", "reason": reason or "—"}
    res = await db.clock_records.update_one(
        {"id": rid},
        {
            "$set": {"status": "Recusado", "manually_edited": True, "last_edited_at": now_iso(),
                     "last_edited_by": "Gestor", "last_edit_reason": reason or ""},
            "$push": {"audit": audit_entry},
        },
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Registro não encontrado")
    return {"ok": True}


# -------------------------------------------------------------------------
# PDF + Email do espelho
# -------------------------------------------------------------------------
def _format_min(mins: int) -> str:
    sign = "-" if mins < 0 else ""
    a = abs(mins)
    return f"{sign}{a // 60}h{a % 60:02d}"


def _build_timesheet_email_html(coll, year, month, days, total_worked, total_balance) -> str:
    rows = "".join(
        f"<tr><td style='padding:6px;border-top:1px solid #e2e8f0'>{d['date']}</td>"
        f"<td style='padding:6px;border-top:1px solid #e2e8f0'>{d.get('entrada') or '—'}</td>"
        f"<td style='padding:6px;border-top:1px solid #e2e8f0'>{d.get('inicio_intervalo') or '—'} / {d.get('fim_intervalo') or '—'}</td>"
        f"<td style='padding:6px;border-top:1px solid #e2e8f0'>{d.get('saida') or '—'}</td>"
        f"<td style='padding:6px;border-top:1px solid #e2e8f0'>{_format_min(d['worked'])}</td>"
        f"<td style='padding:6px;border-top:1px solid #e2e8f0'>{_format_min(d['balance'])}</td>"
        f"<td style='padding:6px;border-top:1px solid #e2e8f0'>{d['status']}</td></tr>"
        for d in days
    )
    return f"""
    <div style="font-family:Inter,Arial,sans-serif;color:#0f172a;max-width:720px;margin:auto">
      <h2 style="margin:0 0 6px">Espelho de ponto — {month:02d}/{year}</h2>
      <p style="margin:0 0 18px;color:#64748b">Olá {coll['name']}, segue seu espelho mensal auditado.</p>
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr style="background:#f1f5f9;text-align:left">
          <th style="padding:8px">Data</th><th style="padding:8px">Entrada</th><th style="padding:8px">Intervalo</th>
          <th style="padding:8px">Saída</th><th style="padding:8px">Trabalhado</th><th style="padding:8px">Saldo</th><th style="padding:8px">Status</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="margin-top:18px"><strong>Total trabalhado:</strong> {_format_min(total_worked)} • <strong>Saldo do mês:</strong> {_format_min(total_balance)}</p>
      <p style="color:#94a3b8;font-size:12px">Em caso de divergência, procure seu gestor responsável.</p>
    </div>
    """


def _fmt_hhmm_signed(mins: int) -> str:
    """Formata minutos como HH:MM com sinal (estilo Control iD)."""
    if mins == 0:
        return "00:00"
    sign = "-" if mins < 0 else ""
    a = abs(int(mins))
    return f"{sign}{a // 60:02d}:{a % 60:02d}"


def _fmt_marca(time_str: str | None, origens: dict, key: str) -> str:
    """Formata uma marcação como 'HH:MM (X)' onde X = I/P/M/C."""
    if not time_str:
        return "—"
    tag = origens.get(key)
    return f"{time_str} ({tag})" if tag else time_str


def _logo_flowable(logo_src: str | None, max_w_cm: float = 2.4, max_h_cm: float = 2.0):
    """Carrega um logo (data URL base64 ou URL http) e devolve um Image
    Flowable do ReportLab. Falha silenciosa → retorna None.
    """
    if not logo_src or not isinstance(logo_src, str):
        return None
    try:
        if logo_src.startswith("data:"):
            # data:image/png;base64,XXXX
            header, _, b64 = logo_src.partition(",")
            if not b64:
                return None
            raw = base64.b64decode(b64)
            buf = io.BytesIO(raw)
        elif logo_src.startswith("http://") or logo_src.startswith("https://"):
            # ART.6 — usa safe_fetch (bloqueia IP privado/metadata/loopback)
            from services.safe_fetch import safe_fetch, SSRFBlocked
            try:
                data = safe_fetch(logo_src, timeout=3)
            except SSRFBlocked:
                return None
            buf = io.BytesIO(data)
        else:
            return None
        img = Image(buf, width=max_w_cm * cm, height=max_h_cm * cm, kind="proportional")
        return img
    except Exception:
        return None



def _timesheet_elements(coll, year, month, days, total_worked, total_balance,
                          company=None, praca=None, totals_extra=None, styles=None,
                          print_id=None):
    """Gera lista de elementos Platypus do espelho — formato Control iD fiel.
    A4 PORTRAIT, 1 página, header azul, bloco identificação sem bordas,
    cabeçalho de jornada SEG-DOM, tabela sem zebra, prefixo (P)/(I)/(M)/(C)
    nas marcações, linha TOTAIS, legenda + Portaria 671 + 2 assinaturas."""
    if styles is None:
        styles = getSampleStyleSheet()
    elements = []
    company = company or {}
    praca = praca or {}
    totals_extra = totals_extra or {}

    # Praça é a "filial" do colaborador — TEM PRIORIDADE TOTAL sobre a matriz
    # para todos os dados que aparecem no espelho. Só cai pra company se a
    # praça não tiver o campo cadastrado.
    eff_name = (praca.get("name_business") or praca.get("name")
                or company.get("name") or "SmartProv")
    company_name = eff_name.upper()
    company_cnpj = praca.get("cnpj") or company.get("cnpj") or "—"
    company_ie = (praca.get("inscricao_estadual") or company.get("inscricao_estadual")
                  or company.get("ie") or "—")
    # Logo: praça primeiro, depois branding/company
    company_logo = (praca.get("logo_url") or praca.get("logo_data_url")
                    or company.get("logo_data_url") or company.get("logo_url"))

    last_day_str = f"{calendar.monthrange(year, month)[1]:02d}/{month:02d}/{year}"
    periodo = f"01/{month:02d}/{year} ATÉ {last_day_str}"
    emitido_em = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")

    # ---------- HEADER (clean / white com logo opcional) ----------
    logo_cell = _logo_flowable(company_logo, max_w_cm=2.4, max_h_cm=2.0)
    info_para = Paragraph(
        f"<font color='#0f172a' size='9'><b>Empresa:</b> {company_name}</font><br/>"
        f"<font color='#334155' size='8'><b>CNPJ:</b> {company_cnpj}</font><br/>"
        f"<font color='#334155' size='8'><b>IE:</b> {company_ie}</font>",
        styles["Normal"],
    )
    right_para = Paragraph(
        f"<para alignment='right'><font color='#334155' size='8'>"
        f"<b>Cartão de Ponto</b><br/>"
        f"Página 1 de 1<br/>"
        f"Emitido em {emitido_em}</font></para>",
        styles["Normal"],
    )
    if logo_cell is not None:
        hdr_rows = [[logo_cell, info_para, right_para]]
        col_widths = [2.6 * cm, 10.9 * cm, 6.3 * cm]
    else:
        hdr_rows = [[info_para, right_para]]
        col_widths = [13.5 * cm, 6.3 * cm]
    hdr_t = Table(hdr_rows, colWidths=col_widths, hAlign="LEFT")
    hdr_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE" if logo_cell is not None else "TOP"),
        ("ALIGN", (-1, 0), (-1, 0), "RIGHT"),
    ]))
    elements.append(hdr_t)
    elements.append(Spacer(1, 4))

    # ---------- IDENTIFICAÇÃO DO FUNCIONÁRIO (sem borda, 2 colunas) ----------
    cpf_val = coll.get("cpf") or "—"
    pis_val = coll.get("pis") or "—"

    admit_raw = coll.get("admitted_at") or coll.get("hire_date") or ""
    admit = "—"
    try:
        if admit_raw and len(admit_raw) >= 10:
            yy, mm, dd = admit_raw[:10].split("-")
            admit = f"{dd}/{mm}/{yy}"
    except Exception:
        pass
    matricula = coll.get("matricula") or "—"
    role_val = (coll.get("role") or "").strip().upper() or "—"

    id_left = (
        f"<font size='8'><b>NOME:</b> {coll.get('name', '—').upper()}</font><br/>"
        f"<font size='8'><b>FUNÇÃO:</b> {role_val}</font><br/>"
        f"<font size='8'><b>PIS:</b> {pis_val}</font>"
    )
    id_right = (
        f"<font size='8'><b>CPF:</b> {cpf_val}</font><br/>"
        f"<font size='8'><b>ADMISSÃO:</b> {admit}</font><br/>"
        f"<font size='8'><b>MATRÍCULA:</b> {matricula}</font>"
    )
    id_t = Table([[Paragraph(id_left, styles["Normal"]),
                    Paragraph(id_right, styles["Normal"])]],
                  colWidths=[10 * cm, 9.8 * cm], hAlign="LEFT")
    id_t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(id_t)

    # ---------- PERÍODO DE VALIDADE ----------
    elements.append(Paragraph(
        f"<font size='8'><b>PERÍODO DE VALIDADE DESTE CARTÃO DE PONTO:</b> {periodo}</font>",
        styles["Normal"],
    ))
    elements.append(Spacer(1, 4))

    # ---------- HORÁRIO DE TRABALHO SEMANAL (compacto — 1 linha) ----------
    schedule = coll.get("schedule") or {}
    ent1 = schedule.get("entrada", "08:00")
    sai1 = schedule.get("inicio_intervalo", "12:00")
    ent2 = schedule.get("fim_intervalo", "13:00")
    sai2 = schedule.get("saida", "17:00")
    wk_label = f"{ent1}–{sai1} · {ent2}–{sai2}"
    wk_rows = [
        ["HORÁRIO DE TRABALHO (Segunda a Sexta)", wk_label, "Sábado", "FOLGA", "Domingo", "FOLGA DSR"],
    ]
    wk_t = Table(wk_rows, colWidths=[6.5 * cm, 4 * cm, 1.5 * cm, 1.8 * cm, 1.8 * cm, 4.2 * cm], hAlign="LEFT")
    wk_t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#e5e7eb")),
        ("BACKGROUND", (2, 0), (2, 0), colors.HexColor("#e5e7eb")),
        ("BACKGROUND", (4, 0), (4, 0), colors.HexColor("#e5e7eb")),
        ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, 0), "Helvetica-Bold"),
        ("FONTNAME", (4, 0), (4, 0), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#9ca3af")),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    elements.append(wk_t)
    elements.append(Spacer(1, 4))

    # ---------- TABELA DIÁRIA — 14 COLUNAS (fiel: SEM cor de header, SEM zebra) ----------
    headers = [
        "DIA", "PREVISTO",
        "ENT.1", "SAÍ.1", "ENT.2", "SAÍ.2",
        "TOTAL\nNORMAIS", "TOTAL\nNOTURNO",
        "FALTA E\nATRASO", "ABONO",
        "EXTRA\nDIURNA", "EXTRA\nNOTURNA",
        "BANCO\nHORAS", "BANCO\nSALDO",
    ]
    rows = [headers]
    for d in days:
        dnum = d["date"][-2:]
        origens = d.get("origens") or {}
        prev = d.get("previsto") or "—"
        # No exemplo, o PREVISTO mostra prefixo (P) — Pré-assinalado
        if prev not in ("—", "FOLGA DSR", "FERIADO") and not d.get("is_future"):
            # Concatena (P) ao final do intervalo previsto (estilo Control iD)
            prev = prev + " (P)"

        if d.get("is_future"):
            row = [dnum, prev, "—", "—", "—", "—",
                    "", "", "", "", "", "", "", "—"]
        else:
            row = [
                dnum, prev,
                _fmt_marca(d.get("entrada"), origens, "entrada"),
                _fmt_marca(d.get("inicio_intervalo"), origens, "inicio_intervalo"),
                _fmt_marca(d.get("fim_intervalo"), origens, "fim_intervalo"),
                _fmt_marca(d.get("saida"), origens, "saida"),
                _fmt_hhmm_signed(d.get("worked", 0)) if d.get("worked", 0) else "00:00",
                _fmt_hhmm_signed(d.get("noturno_min", 0)) if d.get("noturno_min", 0) else "00:00",
                _fmt_hhmm_signed(d.get("falta_atraso_min", 0)) if d.get("falta_atraso_min", 0) else "00:00",
                _fmt_hhmm_signed(d.get("abono_min", 0)) if d.get("abono_min", 0) else "00:00",
                _fmt_hhmm_signed(d.get("extra_diurna_min", 0)) if d.get("extra_diurna_min", 0) else "00:00",
                _fmt_hhmm_signed(d.get("extra_noturna_min", 0)) if d.get("extra_noturna_min", 0) else "00:00",
                _fmt_hhmm_signed(d.get("balance", 0)) if d.get("balance", 0) else "00:00",
                _fmt_hhmm_signed(d.get("banco_saldo_min", 0)),
            ]
        rows.append(row)

    # Linha TOTAIS
    rows.append([
        "TOTAIS", "", "", "", "", "",
        _fmt_hhmm_signed(total_worked),
        _fmt_hhmm_signed(totals_extra.get("noturno", 0)),
        _fmt_hhmm_signed(totals_extra.get("falta_atraso", 0)),
        _fmt_hhmm_signed(totals_extra.get("abono", 0)),
        _fmt_hhmm_signed(totals_extra.get("extra_diurna", 0)),
        _fmt_hhmm_signed(totals_extra.get("extra_noturna", 0)),
        _fmt_hhmm_signed(total_balance),
        _fmt_hhmm_signed(total_balance),
    ])

    # Larguras (cm) — A4 portrait útil ≈ 19,8cm
    col_widths = [
        0.7, 2.6,         # dia, previsto
        1.4, 1.4, 1.4, 1.4,  # ent/sai
        1.3, 1.3, 1.3, 1.2, 1.3, 1.3, 1.3, 1.5,  # totalizadores
    ]
    table = Table(rows, repeatRows=1, hAlign="LEFT",
                  colWidths=[w * cm for w in col_widths])
    style = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 5.8),
        ("FONTSIZE", (0, 1), (-1, -1), 5.8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.black),
        ("LINEABOVE", (0, 0), (-1, 0), 0.75, colors.black),
        ("LINEBELOW", (0, -1), (-1, -1), 0.75, colors.black),
        ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.black),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 0.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0.6),
        ("LEFTPADDING", (0, 0), (-1, -1), 1),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
    ]
    # Linhas de Sáb/Dom/Feriado em cinza claro (igual ao exemplo onde aparece "Folga")
    for i, d in enumerate(days, start=1):
        if d.get("is_holiday") or d.get("is_weekend"):
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f3f4f6")))
    table.setStyle(TableStyle(style))
    elements.append(table)
    elements.append(Spacer(1, 6))

    # ---------- LEGENDA (texto compacto) ----------
    elements.append(Paragraph(
        "<font size='6'><b>(I)</b>=Incluído manualmente · <b>(P)</b>=Pré-assinalado · "
        "<b>(M)</b>=Coletor REP-P Mobile/Web · <b>(C)</b>=Coletor REP-P físico (iDFace/iDFlex)</font>",
        styles["Normal"],
    ))
    elements.append(Paragraph(
        "<font size='6' color='#475569'>Documento em conformidade com a Portaria nº 671/2021 "
        "do Ministério do Trabalho e Emprego (CLT art. 74, §2º). Adicional noturno 22h–05h "
        "conforme art. 73 CLT.</font>",
        styles["Normal"],
    ))
    if print_id:
        elements.append(Paragraph(
            f"<font size='6' color='#94a3b8'><b>ID DE IMPRESSÃO:</b> {print_id}</font>",
            styles["Normal"],
        ))
    elements.append(Spacer(1, 10))

    # ---------- ASSINATURAS ----------
    sig_rows = [
        ["_" * 38, "", "_" * 38],
        [
            Paragraph(f"<font size='7'><b>{coll.get('name', '—').upper()}</b><br/>"
                       f"CPF: {cpf_val} · Colaborador</font>", styles["Normal"]),
            "",
            Paragraph(f"<font size='7'><b>{company_name}</b><br/>"
                       f"CNPJ: {company_cnpj} · Responsável RH</font>",
                       styles["Normal"]),
        ],
    ]
    sig_table = Table(sig_rows, colWidths=[9 * cm, 2 * cm, 9 * cm], hAlign="CENTER")
    sig_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
    ]))
    elements.append(sig_table)

    return elements


def _build_timesheet_pdf(coll, year, month, days, total_worked, total_balance,
                          company=None, praca=None, totals_extra=None,
                          print_id=None) -> bytes:
    """PDF individual de espelho de ponto — formato Control iD / Portaria 671/2021-MTE.
    A4 PORTRAIT, 1 página. Reproduz fielmente o exemplo Control iD: header azul,
    bloco identificação sem bordas, tabela sem zebra, prefixo (P) no PREVISTO,
    legenda I/P/M/C + Portaria 671 no rodapé, 2 assinaturas."""
    buf = io.BytesIO()
    pdf_title = f"SmartProv — Cartão de Ponto ({(coll.get('name') or '').strip()} {month:02d}/{year})".strip()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=0.6 * cm, rightMargin=0.6 * cm,
        topMargin=0.6 * cm, bottomMargin=0.6 * cm,
        title=pdf_title, author="SmartProv",
        subject="Espelho de Ponto — Portaria 671/2021-MTE",
        creator="SmartProv",
    )
    elements = _timesheet_elements(coll, year, month, days, total_worked, total_balance,
                                     company=company, praca=praca, totals_extra=totals_extra,
                                     print_id=print_id)
    doc.build(elements)
    buf.seek(0)
    return buf.read()


def _build_collective_pdf(items: list[dict], year: int, month: int,
                            company: dict = None, print_id_prefix: str | None = None) -> bytes:
    """PDF coletivo: itera por colaboradores, gera as páginas e separa com PageBreak.
    items: [{coll, days, total_worked_min, total_balance_min, totals_extra, praca}]
    print_id_prefix: ID base que aparece no rodapé de cada página (sufixado pelo nome do colab)."""
    from reportlab.platypus import PageBreak
    buf = io.BytesIO()
    pdf_title = f"SmartProv — Cartões de Ponto ({month:02d}/{year})"
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=0.6 * cm, rightMargin=0.6 * cm,
        topMargin=0.6 * cm, bottomMargin=0.6 * cm,
        title=pdf_title, author="SmartProv",
        subject="Espelho de Ponto — Portaria 671/2021-MTE",
        creator="SmartProv",
    )
    all_elements = []
    for idx, it in enumerate(items):
        if idx > 0:
            all_elements.append(PageBreak())
        page_id = None
        if print_id_prefix:
            cname = (it["coll"].get("name") or "").upper().replace(" ", "_")
            page_id = f"{print_id_prefix}#{cname}"
        all_elements.extend(_timesheet_elements(
            it["coll"], year, month, it["days"],
            it["total_worked_min"], it["total_balance_min"],
            company=company, praca=it.get("praca"),
            totals_extra=it.get("totals_extra"),
            print_id=page_id,
        ))
    doc.build(all_elements)
    buf.seek(0)
    return buf.read()


async def send_timesheet_email(coll: dict, year: int, month: int) -> dict:
    import asyncio as _asyncio
    s = await get_settings()
    if not s.resend_api_key:
        return {"sent": False, "reason": "Resend API key não configurada", "to": coll["email"]}
    resend.api_key = s.resend_api_key
    sender = s.sender_email or os.environ.get("SENDER_EMAIL") or "onboarding@resend.dev"
    sender_name = s.sender_name or "Ponto do Colaborador"
    sheet = await timesheet(coll["id"], year, month)
    cid = coll.get("company_id") or DEMO_COMPANY_ID
    company_doc = await db.companies.find_one({"id": cid}, {"_id": 0}) or {}
    praca_doc = None
    if coll.get("praca_id"):
        praca_doc = await db.pracas.find_one({"id": coll["praca_id"]}, {"_id": 0}) or None
    html = _build_timesheet_email_html(coll, year, month, sheet["days"], sheet["total_worked_min"], sheet["total_balance_min"])
    pdf_bytes = _build_timesheet_pdf(coll, year, month, sheet["days"],
                                       sheet["total_worked_min"], sheet["total_balance_min"],
                                       company=company_doc, praca=praca_doc,
                                       totals_extra={
                                           "noturno": sheet.get("total_noturno_min", 0),
                                           "extra_diurna": sheet.get("total_extra_diurna_min", 0),
                                           "extra_noturna": sheet.get("total_extra_noturna_min", 0),
                                           "falta_atraso": sheet.get("total_falta_atraso_min", 0),
                                           "abono": sheet.get("total_abono_min", 0),
                                       })
    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
    params = {
        "from": f"{sender_name} <{sender}>",
        "to": [coll["email"]], "subject": f"Espelho de ponto — {month:02d}/{year}",
        "html": html,
        "attachments": [{
            "filename": f"espelho-{coll['id']}-{year}-{month:02d}.pdf",
            "content": pdf_b64,
        }],
    }
    try:
        result = await _asyncio.to_thread(resend.Emails.send, params)
        return {"sent": True, "to": coll["email"], "id": result.get("id"), "year": year, "month": month}
    except Exception as e:
        logger.exception("Falha envio resend")
        return {"sent": False, "reason": str(e), "to": coll["email"]}


async def _get_requester_optional(request: Request) -> Optional[dict]:
    """Lê user a partir de Authorization header OU cookie access_token.
    Retorna None se não houver — endpoint segue funcionando, só sem nome
    no filename do PDF."""
    token = None
    auth = (request.headers.get("Authorization") or "")
    if auth.startswith("Bearer "):
        token = auth[7:]
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        from auth import decode_token  # lazy import (já usado em outras funções deste arquivo)
        payload = decode_token(token)
        return await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
    except Exception:
        return None


def print_id_value(coll: dict, praca: dict | None, requester: dict | None) -> str:
    """Mesmo helper de filename, mas sem '.pdf' — usado como ID de Impressão
    impresso dentro do PDF e gravado em db.print_audit."""
    fname = _format_pdf_filename(coll, praca, requester, 0, 0)
    return fname.replace(".pdf", "")


def _format_pdf_filename(coll: dict, praca: dict | None, requester: dict | None,
                          year: int, month: int) -> str:
    """Gera nome de arquivo padrão:
       PRIMEIRO_SEGUNDO_PRACA_REQUESTERFIRSTNAME_YYYYMMDD-HHMM.pdf
    Tudo em uppercase, sem acentos, sem espaços (use _)."""
    import re
    import unicodedata

    def _slug(s: str) -> str:
        if not s:
            return "SEM_NOME"
        # remove acentos
        s = "".join(
            c for c in unicodedata.normalize("NFD", s)
            if unicodedata.category(c) != "Mn"
        )
        # mantém letras/números/underscore, troca espaços por _
        s = re.sub(r"[^A-Za-z0-9_\s]", "", s).strip()
        s = re.sub(r"\s+", "_", s)
        return s.upper() or "SEM_NOME"

    # Nome do colaborador — pega primeiro + segundo nome
    full_name = (coll.get("name") or "").strip()
    parts = full_name.split()
    if len(parts) >= 2:
        coll_name = f"{parts[0]}_{parts[1]}"
    elif parts:
        coll_name = parts[0]
    else:
        coll_name = "SEM_NOME"

    # Praça (apenas a principal). Se não houver, usa SEM_PRACA
    praca_name = (praca.get("name") if praca else None) or "SEM_PRACA"

    # Quem pediu o PDF — primeiro nome
    requester_name = "ANONIMO"
    if requester:
        rn = (requester.get("name") or requester.get("email", "").split("@")[0] or "").strip()
        rp = rn.split()
        if rp:
            requester_name = rp[0]

    # Data + hora local de Brasília (BRT = UTC-3)
    from datetime import timedelta
    now_brt = datetime.now(timezone.utc) - timedelta(hours=3)
    stamp = now_brt.strftime("%Y%m%d-%H%M")

    return f"{_slug(coll_name)}_{_slug(praca_name)}_{_slug(requester_name)}_{stamp}.pdf"


@router.get("/timesheets/{cid}/{year}/{month}/pdf")
async def timesheet_pdf(cid: str, year: int, month: int, request: Request):
    sheet = await timesheet(cid, year, month)
    coll = sheet["collaborator"]
    company_id = coll.get("company_id") or DEMO_COMPANY_ID
    company_doc = await db.companies.find_one({"id": company_id}, {"_id": 0}) or {}
    # Mescla branding (CNPJ/IE/nome fantasia ficam lá) por cima do company doc
    branding_doc = await db.company_branding.find_one({"company_id": company_id}, {"_id": 0}) or {}
    if branding_doc:
        merged = dict(company_doc)
        if branding_doc.get("company_name"):
            merged["name"] = branding_doc["company_name"]
        for k in ("cnpj", "inscricao_estadual", "address", "city", "state", "phone", "email"):
            if branding_doc.get(k):
                merged[k] = branding_doc[k]
        company_doc = merged
    praca_doc = None
    if coll.get("praca_id"):
        praca_doc = await db.pracas.find_one({"id": coll["praca_id"]}, {"_id": 0}) or None
    pdf_bytes = _build_timesheet_pdf(
        coll, year, month, sheet["days"],
        sheet["total_worked_min"], sheet["total_balance_min"],
        company=company_doc, praca=praca_doc,
        totals_extra={
            "noturno": sheet.get("total_noturno_min", 0),
            "extra_diurna": sheet.get("total_extra_diurna_min", 0),
            "extra_noturna": sheet.get("total_extra_noturna_min", 0),
            "falta_atraso": sheet.get("total_falta_atraso_min", 0),
            "abono": sheet.get("total_abono_min", 0),
        },
        print_id=print_id_value(coll, praca_doc, requester_for_id := await _get_requester_optional(request)),
    )
    filename = _format_pdf_filename(coll, praca_doc, requester_for_id, year, month)
    # Persiste o ID de impressão (auditoria)
    await db.print_audit.insert_one({
        "id": filename.replace(".pdf", ""),
        "type": "timesheet",
        "collaborator_id": coll.get("id"),
        "collaborator_name": coll.get("name"),
        "praca_id": (praca_doc or {}).get("id"),
        "praca_name": (praca_doc or {}).get("name"),
        "year": year, "month": month,
        "requested_by_user_id": (requester_for_id or {}).get("id"),
        "requested_by_user_name": (requester_for_id or {}).get("name"),
        "company_id": company_id,
        "ip": (request.client.host if request.client else None),
        "user_agent": request.headers.get("user-agent", "")[:300],
        "at": now_iso(),
    })
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/timesheets-collective/{year}/{month}/pdf")
async def collective_timesheet_pdf(year: int, month: int, request: Request):
    """PDF coletivo: 1 página por colaborador ativo com clock_in_enabled.
    Útil para o fechamento mensal do RH."""
    company_id = DEMO_COMPANY_ID
    company_doc = await db.companies.find_one({"id": company_id}, {"_id": 0}) or {}
    branding_doc = await db.company_branding.find_one({"company_id": company_id}, {"_id": 0}) or {}
    if branding_doc:
        merged = dict(company_doc)
        if branding_doc.get("company_name"):
            merged["name"] = branding_doc["company_name"]
        for k in ("cnpj", "inscricao_estadual", "address", "city", "state", "phone", "email"):
            if branding_doc.get(k):
                merged[k] = branding_doc[k]
        company_doc = merged
    colls = await db.collaborators.find(
        {"company_id": company_id, "active": True, "clock_in_enabled": True},
        {"_id": 0},
    ).sort("name", 1).to_list(length=500)
    if not colls:
        raise HTTPException(404, "Nenhum colaborador ativo encontrado")
    items = []
    for coll in colls:
        try:
            sheet = await timesheet(coll["id"], year, month)
        except Exception:
            continue
        praca_doc = None
        if coll.get("praca_id"):
            praca_doc = await db.pracas.find_one({"id": coll["praca_id"]}, {"_id": 0}) or None
        items.append({
            "coll": sheet["collaborator"],
            "days": sheet["days"],
            "total_worked_min": sheet["total_worked_min"],
            "total_balance_min": sheet["total_balance_min"],
            "totals_extra": {
                "noturno": sheet.get("total_noturno_min", 0),
                "extra_diurna": sheet.get("total_extra_diurna_min", 0),
                "extra_noturna": sheet.get("total_extra_noturna_min", 0),
                "falta_atraso": sheet.get("total_falta_atraso_min", 0),
                "abono": sheet.get("total_abono_min", 0),
            },
            "praca": praca_doc,
        })
    pdf_bytes = _build_collective_pdf(items, year, month, company=company_doc,
                                         print_id_prefix=None)
    # Filename coletivo: ESPELHO_COLETIVO_<EMPRESA>_<USUARIO>_<DATA-HORA>.pdf
    import re
    import unicodedata
    def _slug(s):
        if not s:
            return "SEM_NOME"
        s = "".join(c for c in unicodedata.normalize("NFD", s)
                    if unicodedata.category(c) != "Mn")
        s = re.sub(r"[^A-Za-z0-9_\s]", "", s).strip()
        return (re.sub(r"\s+", "_", s).upper() or "SEM_NOME")
    requester = await _get_requester_optional(request)
    requester_name = "ANONIMO"
    if requester:
        rn = (requester.get("name") or requester.get("email", "").split("@")[0] or "").strip()
        rp = rn.split()
        if rp:
            requester_name = rp[0]
    from datetime import timedelta
    now_brt = datetime.now(timezone.utc) - timedelta(hours=3)
    stamp = now_brt.strftime("%Y%m%d-%H%M")
    empresa = (company_doc.get("name") or "EMPRESA")
    filename = f"ESPELHO_COLETIVO_{_slug(empresa)}_{_slug(requester_name)}_{stamp}.pdf"
    print_id = filename.replace(".pdf", "")
    # Re-monta com print_id agora que temos o filename
    pdf_bytes = _build_collective_pdf(items, year, month, company=company_doc,
                                         print_id_prefix=print_id)
    await db.print_audit.insert_one({
        "id": print_id,
        "type": "timesheet_collective",
        "count_collaborators": len(items),
        "year": year, "month": month,
        "requested_by_user_id": (requester or {}).get("id"),
        "requested_by_user_name": (requester or {}).get("name"),
        "company_id": company_id,
        "ip": (request.client.host if request.client else None),
        "user_agent": request.headers.get("user-agent", "")[:300],
        "at": now_iso(),
    })
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )




@router.post("/timesheets/send/{cid}")
async def send_timesheet_now(cid: str, year: int, month: int):
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    return await send_timesheet_email(coll, year, month)


@router.get("/timesheets/print-audit")
async def list_print_audit(limit: int = 50, user: dict = Depends(require_role("gestor"))):
    """Histórico de impressões/downloads/envios de espelho de ponto.
    Cada entrada tem o ID de impressão, quem pediu, quando, IP e User-Agent."""
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    cursor = db.print_audit.find(
        {"company_id": company_id},
        {"_id": 0},
    ).sort("at", -1).limit(max(1, min(limit, 500)))
    items = await cursor.to_list(length=500)
    return {"items": items, "total": len(items)}

