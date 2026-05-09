"""Endpoints de clock-records, collaborators, geofences, timesheets.

Inclui também `dashboard_overtime` (mês simples) que é importado lazy
pelo routes/dashboard.py para tendência/range.
"""
from __future__ import annotations

import base64
import calendar
import io
import logging
import os
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import resend
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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

logger = logging.getLogger("ponto")
router = APIRouter(prefix="/api", tags=["clock"])


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
    company: str = "Operação SP"
    schedule: WorkSchedule = Field(default_factory=WorkSchedule)
    overtime_policy: OvertimePolicy = Field(default_factory=OvertimePolicy)
    city: Optional[str] = None
    state: Optional[str] = None
    praca_id: Optional[str] = None
    is_test_mode: bool = False  # ADMIN: marca colaborador como TESTE — bypassa cerca/selfie
    clock_in_enabled: bool = True  # CLT bate ponto. False = freelancer/MEI/3rd party — Lousa direta sem ponto.


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
    lat: float
    lng: float
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
async def list_collaborators(request: __import__('fastapi').Request):
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
    return await db.collaborators.find(q, {"_id": 0, "reference_face": 0}).to_list(500)


@router.get("/collaborators/{cid}")
async def get_collaborator(cid: str):
    doc = await db.collaborators.find_one({"id": cid}, {"_id": 0, "reference_face": 0})
    if not doc:
        raise HTTPException(404, "Colaborador não encontrado")
    return doc


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
    cid = f"col-{uuid.uuid4().hex[:8]}"
    now = now_iso()
    coll = Collaborator(id=cid, **payload.model_dump(), created_at=now, updated_at=now)
    doc = coll.model_dump()
    doc["company_id"] = cid_company
    try:
        await db.collaborators.insert_one(doc)
    except Exception as e:
        raise HTTPException(400, f"Erro ao criar (CPF duplicado?): {e}")
    out = coll.model_dump(exclude={"reference_face"})
    out["company_id"] = cid_company
    return out


@router.put("/collaborators/{cid}")
async def update_collaborator(cid: str, payload: CollaboratorIn, user: dict = Depends(require_role("gestor"))):
    # Tenant scope
    if not is_super_admin(user):
        existing = await db.collaborators.find_one({"id": cid}, {"company_id": 1})
        if not existing or existing.get("company_id") != user.get("company_id"):
            raise HTTPException(404, "Colaborador não encontrado")
    data = payload.model_dump()
    data["updated_at"] = now_iso()
    res = await db.collaborators.update_one({"id": cid}, {"$set": data})
    if res.matched_count == 0:
        raise HTTPException(404, "Colaborador não encontrado")
    return await get_collaborator(cid)


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
    update = {
        "reference_face": None,
        "avatar_data_url": None,
        "updated_at": now_iso(),
    }
    if reset_device:
        update["device_id"] = None
        update["google_email"] = None
        update["google_name"] = None
        update["google_picture"] = None
    res = await db.collaborators.update_one({"id": cid}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(404, "Colaborador não encontrado")
    sessions_invalidated = 0
    if reset_device:
        deleted = await db.collaborator_sessions.delete_many({"collaborator_id": cid})
        sessions_invalidated = deleted.deleted_count
    return {
        "ok": True,
        "reset_device": bool(reset_device),
        "sessions_invalidated": sessions_invalidated,
        "message": "Avatar e foto de referência removidos." + (
            " Dispositivo e vínculo Google também resetados." if reset_device else ""
        ),
    }


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
async def create_clock_record(payload: ClockRecordIn, request: __import__('fastapi').Request):
    if payload.type not in EVENT_TYPES:
        raise HTTPException(400, "Tipo de evento inválido.")
    coll = await db.collaborators.find_one({"id": payload.collaborator_id})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")

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
                f"Você tem nota(s) em aberto. Confirme com 'force_close_open_tickets=true' "
                f"para encerrar e bater Saída.",
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
    nota_fence_used = False
    if not fence and coll.get("praca_id") == "NOTA":
        # Tenta usar endereço da bolha aberta primeiro, senão a próxima pendente
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
        if snap.get("latitude") and snap.get("longitude"):
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
                nota_fence_used = True
                audit.append({
                    "at": now_iso(), "actor": "sistema",
                    "action": f"praca=NOTA → cerca dinâmica em '{snap.get('name','')}': {dist_to_note}m de {radius}m"
                })
    geofence_required = payload.type in GEOFENCE_REQUIRED
    # ADMIN TEST: ignora exigência de cerca
    if geofence_required and not fence and not is_admin_test:
        rec = _build_record(
            rid=rid, cid=payload.collaborator_id, ev=payload.type, today=today, hhmm=hhmm,
            geofence=None, distance=distance, status="Bloqueado", note=PUBLIC_FENCE_FAIL,
            internal_reason=f"fora_da_cerca distância={distance}m",
            public_block=PUBLIC_FENCE_FAIL, selfie_url=payload.selfie_base64,
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
    if is_admin_test:
        rec["admin_test_mode"] = True
        rec["test_actor"] = admin_actor
        if not fence:
            rec["geo_status"] = "🧪 Teste admin — cerca ignorada"
    await db.clock_records.insert_one(rec)
    update: dict[str, Any] = {"updated_at": now_iso()}
    if not coll.get("reference_face"):
        update["reference_face"] = payload.selfie_base64
        update["avatar_data_url"] = payload.selfie_base64
    await db.collaborators.update_one({"id": payload.collaborator_id}, {"$set": update})

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
    if is_holiday_day or is_sunday:
        overtime_min = worked
        overtime_kind = "sunday_or_holiday" if worked > 0 else None
    elif is_weekend:
        overtime_min = worked
        overtime_kind = "weekday" if worked > 0 else None
    else:
        overtime_min = max(0, worked - expected)
        overtime_kind = "weekday" if overtime_min > 0 else None
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
    return {
        "entrada": by_type.get("Entrada", {}).get("time"),
        "saida": by_type.get("Saída", {}).get("time"),
        "inicio_intervalo": by_type.get("Início intervalo", {}).get("time"),
        "fim_intervalo": by_type.get("Fim intervalo", {}).get("time"),
        "worked": worked, "interval": interval, "expected": expected, "balance": balance,
        "overtime_min": overtime_min, "overtime_kind": overtime_kind,
        "status": status, "missing": missing,
    }


@router.get("/timesheets/{cid}/{year}/{month}")
async def timesheet(cid: str, year: int, month: int):
    from routes.admin import get_cached_holidays  # lazy
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
    holidays_list = await get_cached_holidays(year, "national")
    holidays_map = {h["date"]: {**h, "scope": "national"} for h in holidays_list}
    if coll.get("praca_id"):
        praca = await db.pracas.find_one({"id": coll["praca_id"]}, {"_id": 0})
        if praca:
            for h in praca.get("holidays_extra", []) or []:
                d = h.get("date")
                if d and d.startswith(f"{year:04d}-{month:02d}"):
                    if d not in holidays_map:
                        holidays_map[d] = {**h, "scope": h.get("scope", "municipal")}
    today_s = today_str()
    days = []
    total_worked = 0
    total_balance = 0
    total_ot_weekday = 0
    total_ot_sunday_holiday = 0
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
        if is_future:
            days.append({
                "date": d_str, "entrada": None, "saida": None, "inicio_intervalo": None, "fim_intervalo": None,
                "worked": 0, "interval": 0, "expected": 0, "balance": 0,
                "overtime_min": 0, "overtime_kind": None,
                "status": "Futuro", "missing": [],
                "is_future": True, "is_today": False, "is_weekend": is_weekend,
                "is_holiday": is_holiday_day, "holiday": holiday_info,
                "weekday": weekday, "records": [],
            })
            continue
        calc = _calc_day(day_records, schedule, is_weekend=is_weekend, is_sunday=is_sunday, is_holiday_day=is_holiday_day)
        total_worked += calc["worked"]
        total_balance += calc["balance"]
        if calc.get("overtime_kind") == "weekday":
            total_ot_weekday += calc["overtime_min"]
        elif calc.get("overtime_kind") == "sunday_or_holiday":
            total_ot_sunday_holiday += calc["overtime_min"]
        days.append({
            "date": d_str, **calc,
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
            "id": coll["id"], "name": coll["name"], "cpf": coll["cpf"], "email": coll["email"],
            "schedule": coll.get("schedule", {}),
            "overtime_policy": policy.model_dump(),
            "city": coll.get("city"), "state": coll.get("state"),
        },
        "year": year, "month": month, "days": days,
        "total_worked_min": total_worked,
        "total_balance_min": total_balance,
        "total_overtime_min": total_overtime_min,
        "total_overtime_weekday_min": total_ot_weekday,
        "total_overtime_sunday_holiday_min": total_ot_sunday_holiday,
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


def _build_timesheet_pdf(coll, year, month, days, total_worked, total_balance) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.6 * cm, bottomMargin=1.6 * cm)
    styles = getSampleStyleSheet()
    elements = []
    elements.append(Paragraph(f"<b>Espelho de Ponto — {month:02d}/{year}</b>", styles["Title"]))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(f"<b>Colaborador:</b> {coll['name']}", styles["Normal"]))
    elements.append(Paragraph(f"<b>CPF:</b> {coll.get('cpf', '—')} &nbsp;&nbsp; <b>E-mail:</b> {coll.get('email', '—')}", styles["Normal"]))
    elements.append(Spacer(1, 12))
    headers = ["Data", "Entrada", "Início Int.", "Fim Int.", "Saída", "Trabalhado", "Saldo", "Status"]
    rows = [headers]
    for d in days:
        rows.append([
            d["date"], d.get("entrada") or "—",
            d.get("inicio_intervalo") or "—", d.get("fim_intervalo") or "—",
            d.get("saida") or "—",
            _format_min(d["worked"]), _format_min(d["balance"]), d["status"],
        ])
    rows.append(["", "", "", "", "Totais:", _format_min(total_worked), _format_min(total_balance), ""])
    table = Table(rows, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8fafc")]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e2e8f0")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 14))
    elements.append(Paragraph("<i>Em caso de divergência, procure seu gestor responsável.</i>", styles["Italic"]))
    doc.build(elements)
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
    html = _build_timesheet_email_html(coll, year, month, sheet["days"], sheet["total_worked_min"], sheet["total_balance_min"])
    pdf_bytes = _build_timesheet_pdf(coll, year, month, sheet["days"], sheet["total_worked_min"], sheet["total_balance_min"])
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


@router.get("/timesheets/{cid}/{year}/{month}/pdf")
async def timesheet_pdf(cid: str, year: int, month: int):
    sheet = await timesheet(cid, year, month)
    coll = sheet["collaborator"]
    pdf_bytes = _build_timesheet_pdf(coll, year, month, sheet["days"], sheet["total_worked_min"], sheet["total_balance_min"])
    filename = f"espelho-{coll['id']}-{year}-{month:02d}.pdf"
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
