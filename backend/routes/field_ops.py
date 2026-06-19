"""Smart Field Ops — camada OFICIAL de conexão App Colaborador Externo ↔ SmartProv.

REGRA CENTRAL (ordem CTO 06/2026): o App é a mão, o SmartProv é o cérebro.
Nada aqui cria banco paralelo, API paralela ou regra paralela. Todos os
endpoints deste módulo:

  • Exigem JWT (get_current_user) — zero bypass, zero mock.
  • Resolvem o colaborador REAL vinculado ao usuário (users.collaborator_id
    ou e-mail batendo com collaborators.email).
  • Aplicam company_id em TODA query (zero dado cruzado entre empresas).
  • Validam ownership: técnico só enxerga/age em OS dele (cross → 404).
  • Têm rate limit (slowapi) e gravam audit_log.
  • Emitem eventos `field.*` no event_bus (motor_ia_events) — alimentam
    Lousa, Presidente IA, Álvaro IA, estoque, CTO, DRE e auditoria.
  • REUTILIZAM as regras existentes da Lousa/Estoque: start/finish delegam
    para routes.lousa.public_open_ticket / public_finalize_ticket (todas as
    travas de checklist, fotos, sinal, CTO/porta e toggles continuam valendo).

Toggles por empresa em aihub_settings key="field_ops_toggles"
(defaults DESLIGADOS — decisão CTO: gestor liga quando quiser).

Contrato completo: /app/docs/SMART_FIELD_OPS_CONNECTION.md
"""

from services.exception_sanitizer import safe_detail  # SECURITY_LOCK ART.13
NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "operacoes",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, get_current_user, is_super_admin, now_iso
from database import db
from services.event_bus import EventType, emit_event
from services.rate_limit import get_limit, limiter

logger = logging.getLogger("ponto.field_ops")
router = APIRouter(prefix="/api/field", tags=["field_ops"])

SP_TZ = ZoneInfo("America/Sao_Paulo")

# ---------------------------------------------------------------------------
# Toggles por empresa (defaults desligados — decisão CTO 06/2026)
# ---------------------------------------------------------------------------
FIELD_DEFAULTS: Dict[str, Any] = {
    # Bloqueia abertura de OS se a vistoria semanal da frota estiver pendente
    "vehicle_inspection_required": False,
    "vehicle_inspection_max_age_days": 7,
    # Bloqueia início/finalização de OS sem GPS (lat/lng)
    "gps_required": False,
    # Bloqueia registro de material quando o saldo do técnico não cobre.
    # Default OFF — comportamento padrão do SmartProv permite saldo negativo
    # para dar visibilidade à QUEBRA (iter168).
    "block_material_without_stock": False,
    # Valor padrão (R$) do equipamento em comodato p/ impacto financeiro
    # de retiradas (recuperado = valor recuperado; não devolvido = perda).
    "equipment_default_cost": 250.0,
}

_PRIVILEGED_ROLES = ("administrador", "gestor", "auditor")

_indexes_ready = False


async def _ensure_indexes() -> None:
    global _indexes_ready
    if _indexes_ready:
        return
    try:
        await db.field_vehicle_inspections.create_index(
            [("company_id", 1), ("collaborator_id", 1), ("created_at", -1)])
        await db.field_equipment_returns.create_index(
            [("company_id", 1), ("created_at", -1)])
        await db.audit_log.create_index([("company_id", 1), ("kind", 1)])
        _indexes_ready = True
    except Exception as e:
        logger.warning("[field_ops] ensure_indexes: %s", e)


# ---------------------------------------------------------------------------
# Helpers de segurança / contexto
# ---------------------------------------------------------------------------
def _company_of(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


def _is_privileged(user: dict) -> bool:
    return user.get("role") in _PRIVILEGED_ROLES or is_super_admin(user)


async def _resolve_collab(user: dict, cid_param: Optional[str] = None):
    """Resolve o colaborador REAL do usuário logado.

    Retorna (collab_doc, read_only). `read_only=True` quando um gestor/admin
    está visualizando o app de OUTRO colaborador (modo gestor somente
    leitura — mesma regra da Lousa).
    """
    company = _company_of(user)
    own = None
    own_cid = user.get("collaborator_id")
    if own_cid:
        own = await db.collaborators.find_one(
            {"id": own_cid, "company_id": company}, {"_id": 0})
    if not own and user.get("email"):
        own = await db.collaborators.find_one(
            {"email": (user["email"] or "").lower(), "company_id": company},
            {"_id": 0})

    if cid_param and (not own or cid_param != own.get("id")):
        if not _is_privileged(user):
            raise HTTPException(
                403, "Você não tem permissão para acessar dados de outro colaborador")
        target = await db.collaborators.find_one(
            {"id": cid_param, "company_id": company}, {"_id": 0})
        if not target:
            raise HTTPException(404, "Colaborador não encontrado")
        return target, True

    if not own:
        raise HTTPException(
            403,
            "Seu usuário não está vinculado a um colaborador. "
            "Peça ao gestor para vincular em Cadastro > Colaboradores.")
    return own, False


def _require_write(read_only: bool) -> None:
    if read_only:
        raise HTTPException(
            403, "Modo gestor é somente leitura — ações de campo são do técnico.")


async def _owned_ticket(ticket_id: str, collab: dict, company: str) -> dict:
    """Ownership + tenant: OS de outro técnico ou outra empresa → 404
    (não vazamos a existência)."""
    t = await db.tickets.find_one(
        {"id": ticket_id, "company_id": company}, {"_id": 0})
    if not t or t.get("assigned_collaborator_id") != collab["id"]:
        raise HTTPException(404, "OS não encontrada")
    return t


async def _toggles(company: str) -> Dict[str, Any]:
    doc = await db.aihub_settings.find_one(
        {"company_id": company, "key": "field_ops_toggles"},
        {"_id": 0, "value": 1})
    saved = (doc or {}).get("value") or {}
    return {**FIELD_DEFAULTS, **{k: v for k, v in saved.items() if k in FIELD_DEFAULTS}}


async def _audit(company: str, kind: str, user: dict, collab_id: str,
                 ticket_id: Optional[str] = None, **extra) -> None:
    try:
        await db.audit_log.insert_one({
            "id": f"audit-{uuid.uuid4().hex[:12]}",
            "company_id": company,
            "kind": kind,
            "source": "field_ops",
            "user_id": user.get("id"),
            "user_email": user.get("email"),
            "collaborator_id": collab_id,
            "ticket_id": ticket_id,
            "created_at": now_iso(),
            **extra,
        })
    except Exception as e:
        logger.warning("[field_ops] audit fail kind=%s: %s", kind, e)


async def _emit(event_type: str, company: str, user: dict,
                payload: Dict[str, Any], severity: str = "media") -> None:
    await emit_event(event_type, company_id=company, user_id=user.get("id"),
                     source="field_ops", severity=severity, payload=payload)


async def _log_lousa(ticket_id: str, action: str, collab: dict,
                     details: str, company: str) -> None:
    """Atualiza a timeline da Lousa (ticket_logs) — gestor enxerga tudo."""
    try:
        from routes.lousa import _log_ticket_action
        await _log_ticket_action(
            ticket_id=ticket_id, action=action,
            actor_id=collab["id"], actor_name=collab.get("name", "Técnico"),
            actor_role="colaborador", details=details, company_id=company)
    except Exception as e:
        logger.warning("[field_ops] lousa log fail: %s", e)


def _today_range_utc() -> tuple[str, str]:
    now_sp = datetime.now(SP_TZ)
    start_sp = now_sp.replace(hour=0, minute=0, second=0, microsecond=0)
    end_sp = start_sp + timedelta(days=1)
    return (start_sp.astimezone(timezone.utc).isoformat(),
            end_sp.astimezone(timezone.utc).isoformat())


_TICKET_LIST_PROJ = {
    "_id": 0, "completion_data": 0, "field_photos": 0,
    "client_snapshot.test_history": 0,
}


async def _vehicle_pending(company: str, collab_id: str,
                           tg: Dict[str, Any]) -> Optional[dict]:
    """Retorna info da pendência de vistoria semanal, ou None se ok/desligado."""
    if not tg.get("vehicle_inspection_required"):
        return None
    max_age = int(tg.get("vehicle_inspection_max_age_days") or 7)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age)).isoformat()
    last = await db.field_vehicle_inspections.find_one(
        {"company_id": company, "collaborator_id": collab_id,
         "created_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1, "created_at": 1}, sort=[("created_at", -1)])
    if last:
        return None
    return {
        "code": "VEHICLE_INSPECTION_PENDING",
        "message": (f"Vistoria semanal da frota pendente (obrigatória a cada "
                    f"{max_age} dias). Faça a vistoria no app antes de abrir OS."),
    }


def _gps_gate(tg: Dict[str, Any], lat: Optional[float], lng: Optional[float],
              action: str) -> None:
    if tg.get("gps_required") and (lat is None or lng is None):
        raise HTTPException(412, {
            "code": "GPS_REQUIRED",
            "message": f"GPS obrigatório para {action}. Ative a localização no aparelho.",
        })


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class StartIn(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class ArriveIn(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = None


class PhotoIn(BaseModel):
    data_url: str = Field(..., min_length=20, max_length=11_000_000)
    label: Optional[str] = None
    kind: str = "evidencia"


class SignalTestIn(BaseModel):
    dbm: float = Field(..., ge=-60, le=10)
    phase: Literal["before", "after"] = "before"
    notes: Optional[str] = None


class FieldUsedItem(BaseModel):
    consumable_id: str
    quantity: int = Field(..., gt=0)


class MaterialUsedIn(BaseModel):
    items: List[FieldUsedItem] = Field(..., min_length=1)


class FinishIn(BaseModel):
    completion_data: Dict[str, Any]
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    outcome: str = "sucesso"
    bad_signal_auth_id: Optional[str] = None


class RescheduleIn(BaseModel):
    new_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    new_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    motivo: str = Field(..., min_length=5)


class BlockReasonIn(BaseModel):
    motivo: str = Field(..., min_length=5)
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class VehicleInspectionIn(BaseModel):
    plate: str = Field(..., min_length=4, max_length=10)
    km: float = Field(..., ge=0)
    photo_front: str = Field(..., min_length=20)
    photo_rear: str = Field(..., min_length=20)
    photo_left: str = Field(..., min_length=20)
    photo_right: str = Field(..., min_length=20)
    vehicle_model: Optional[str] = None
    notes: Optional[str] = None


class EquipmentReturnIn(BaseModel):
    ticket_id: Optional[str] = None
    mac: Optional[str] = None
    sn: Optional[str] = None
    recovered: bool
    physical_state: Literal["bom", "danificado", "inutilizado"] = "bom"
    notes: Optional[str] = None
    # Onda 2.6 (16/02/2026) — reason obrigatório quando há mudança de owner.
    reason: Optional[Dict[str, Any]] = None  # {"code": ..., "details": ...}


class FieldSettingsIn(BaseModel):
    vehicle_inspection_required: Optional[bool] = None
    vehicle_inspection_max_age_days: Optional[int] = Field(default=None, ge=1, le=60)
    gps_required: Optional[bool] = None
    block_material_without_stock: Optional[bool] = None
    equipment_default_cost: Optional[float] = Field(default=None, ge=0)


# ---------------------------------------------------------------------------
# GET /api/field/me
# ---------------------------------------------------------------------------
@router.get("/me")
@limiter.limit(get_limit("field_read"))
async def field_me(request: Request, cid: Optional[str] = None,
                   user: dict = Depends(get_current_user)):
    await _ensure_indexes()
    collab, read_only = await _resolve_collab(user, cid)
    company = _company_of(user)
    comp = await db.companies.find_one({"id": company}, {"_id": 0, "name": 1})
    return {
        "user": {"id": user["id"], "email": user["email"],
                 "name": user.get("name"), "role": user.get("role")},
        "collaborator": {"id": collab["id"], "name": collab.get("name"),
                         "email": collab.get("email"),
                         "role": collab.get("role"),
                         "praca_id": collab.get("praca_id"),
                         "clock_in_enabled": collab.get("clock_in_enabled", True)},
        "company_id": company,
        "company_name": (comp or {}).get("name"),
        "read_only": read_only,
    }


# ---------------------------------------------------------------------------
# GET /api/field/dashboard
# ---------------------------------------------------------------------------
@router.get("/dashboard")
@limiter.limit(get_limit("field_read"))
async def field_dashboard(request: Request, cid: Optional[str] = None,
                          user: dict = Depends(get_current_user)):
    await _ensure_indexes()
    collab, read_only = await _resolve_collab(user, cid)
    company = _company_of(user)
    collab_id = collab["id"]
    start, end = _today_range_utc()
    now = now_iso()

    tickets = await db.tickets.find(
        {"company_id": company, "assigned_collaborator_id": collab_id,
         "$or": [
             {"status": "aberta"},
             {"status": "pendente"},
             {"status": {"$in": ["finalizada", "encerrada"]},
              "closed_at": {"$gte": start, "$lt": end}},
         ]},
        _TICKET_LIST_PROJ).sort("scheduled_time", 1).to_list(200)

    # Pendentes de HOJE (grade BR) + abertas + finalizadas hoje
    os_today = [t for t in tickets
                if t["status"] == "aberta"
                or (t["status"] == "pendente"
                    and start <= (t.get("scheduled_time") or "") < end)
                or t["status"] in ("finalizada", "encerrada")]
    active = next((t for t in os_today if t["status"] == "aberta"), None)
    pendentes = [t for t in os_today if t["status"] == "pendente"]
    next_os = pendentes[0] if pendentes else None
    atrasadas = [t for t in pendentes if (t.get("scheduled_time") or "") < now]
    finalizadas = [t for t in os_today
                   if t["status"] in ("finalizada", "encerrada")]

    # Estoque do técnico (consumíveis + ONTs)
    stock_doc = await db.stok_stock.find_one(
        {"company_id": company, "location": collab_id}, {"_id": 0}) or {}
    consumable_count = sum(
        v for k, v in stock_doc.items()
        if isinstance(v, (int, float)) and k not in ("company_id", "location"))
    ont_count = await db.stok_onts.count_documents(
        {"company_id": company, "location_type": "tecnico",
         "location_id": collab_id})

    # Ponto (mesma regra da Lousa)
    ponto = None
    try:
        from routes.lousa import _today_clock_state
        ponto = await _today_clock_state(collab_id)
    except Exception as e:
        logger.warning("[field_ops] clock state fail: %s", e)

    # Frota
    tg = await _toggles(company)
    last_insp = await db.field_vehicle_inspections.find_one(
        {"company_id": company, "collaborator_id": collab_id},
        {"_id": 0, "id": 1, "plate": 1, "km": 1, "created_at": 1},
        sort=[("created_at", -1)])
    vehicle_pending = await _vehicle_pending(company, collab_id, tg)

    # GPS ativo (ping nos últimos 10 min)
    gps_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    last_ping = await db.tech_locations.find_one(
        {"company_id": company, "collab_id": collab_id},
        {"_id": 0, "captured_at": 1}, sort=[("captured_at", -1)])
    gps_active = bool(last_ping and (last_ping.get("captured_at") or "") >= gps_cutoff)

    return {
        "collaborator_id": collab_id,
        "collaborator_name": collab.get("name"),
        "read_only": read_only,
        "os_today": os_today,
        "active_os": active,
        "next_os": next_os,
        "counts": {
            "today": len(os_today),
            "pendentes": len(pendentes),
            "atrasadas": len(atrasadas),
            "finalizadas_hoje": len(finalizadas),
        },
        "stock": {"consumable_total": consumable_count, "ont_count": ont_count},
        "ponto": ponto,
        "vehicle": {
            "inspection_required": bool(tg.get("vehicle_inspection_required")),
            "pending": bool(vehicle_pending),
            "last_inspection": last_insp,
        },
        "gps_active": gps_active,
        "last_gps_at": (last_ping or {}).get("captured_at"),
        "toggles": tg,
    }


# ---------------------------------------------------------------------------
# GET /api/field/os/today
# ---------------------------------------------------------------------------
@router.get("/os/today")
@limiter.limit(get_limit("field_read"))
async def field_os_today(request: Request, cid: Optional[str] = None,
                         user: dict = Depends(get_current_user)):
    collab, read_only = await _resolve_collab(user, cid)
    company = _company_of(user)
    start, end = _today_range_utc()
    tickets = await db.tickets.find(
        {"company_id": company, "assigned_collaborator_id": collab["id"],
         "$or": [
             {"status": "aberta"},
             {"status": "pendente",
              "scheduled_time": {"$gte": start, "$lt": end}},
             {"status": {"$in": ["finalizada", "encerrada"]},
              "closed_at": {"$gte": start, "$lt": end}},
         ]},
        _TICKET_LIST_PROJ).sort("scheduled_time", 1).to_list(100)
    return {"items": tickets, "count": len(tickets), "read_only": read_only}


# ---------------------------------------------------------------------------
# GET /api/field/os/{id} — detalhe completo (dados REAIS do SmartProv)
# ---------------------------------------------------------------------------
@router.get("/os/{ticket_id}")
@limiter.limit(get_limit("field_read"))
async def field_os_detail(ticket_id: str, request: Request,
                          cid: Optional[str] = None,
                          user: dict = Depends(get_current_user)):
    collab, read_only = await _resolve_collab(user, cid)
    company = _company_of(user)
    t = await _owned_ticket(ticket_id, collab, company)

    # Fotos: só metadados (data_url pesado fica fora da resposta)
    photos_meta = [{"id": p.get("id"), "kind": p.get("kind"),
                    "label": p.get("label"), "at": p.get("at")}
                   for p in (t.get("field_photos") or [])]
    t.pop("field_photos", None)
    cd = t.get("completion_data") or {}
    if isinstance(cd, dict) and cd.get("fotos"):
        cd = {**cd, "fotos_count": len(cd["fotos"])}
        cd.pop("fotos", None)
        t["completion_data"] = cd

    # Histórico da OS (timeline da Lousa)
    logs = await db.ticket_logs.find(
        {"ticket_id": ticket_id}, {"_id": 0}).sort("at", -1).to_list(30)

    # Cliente (assinante real)
    subscriber = None
    if t.get("client_id"):
        subscriber = await db.subscribers.find_one(
            {"id": t["client_id"], "company_id": company},
            {"_id": 0, "id": 1, "name": 1, "address": 1, "phone": 1,
             "plan": 1, "plan_name": 1, "pppoe_user": 1, "status": 1,
             "cpf": 1, "neighborhood": 1})

    # CTO vinculada (porta do cliente ou da finalização)
    cto = None
    cto_port = None
    try:
        from routes.stok import _find_client_cto_port
        link = await _find_client_cto_port(company, t.get("client_id") or "")
        if link:
            cto_port = link.get("port_number")
            cto = await db.ctos.find_one(
                {"id": link["cto_id"], "company_id": company},
                {"_id": 0, "id": 1, "name": 1, "address": 1, "gps": 1,
                 "capacity": 1, "splitter": 1, "vlan": 1, "network_type": 1})
    except Exception as e:
        logger.warning("[field_ops] cto lookup fail: %s", e)
    if not cto and cd.get("cto_id"):
        cto = await db.ctos.find_one(
            {"id": cd["cto_id"], "company_id": company},
            {"_id": 0, "id": 1, "name": 1, "address": 1, "gps": 1,
             "capacity": 1, "splitter": 1, "vlan": 1, "network_type": 1})
        cto_port = cd.get("cto_port_number")

    # Equipamento do cliente (ONU/MAC/SN) — rastreabilidade do estoque
    client_name = (t.get("client_snapshot") or {}).get("name") or ""
    equipment = []
    if client_name:
        equipment = await db.stok_onts.find(
            {"company_id": company, "client_name": client_name},
            {"_id": 0, "mac": 1, "scan_sn": 1, "model": 1, "status": 1}
        ).to_list(3)

    # Toggles de validação da finalização (mesmas regras da Lousa)
    validation_toggles = {}
    try:
        from routes.os_validation_toggles import _load as _load_os_toggles
        validation_toggles = await _load_os_toggles(company)
    except Exception:
        pass

    return {
        "ticket": t,
        "photos": photos_meta,
        "signal_tests": t.get("field_signal_tests") or [],
        "materials": t.get("field_materials") or [],
        "history": logs,
        "subscriber": subscriber,
        "cto": cto,
        "cto_port": cto_port,
        "equipment": equipment,
        "validation_toggles": validation_toggles,
        "read_only": read_only,
    }


# ---------------------------------------------------------------------------
# POST /api/field/os/{id}/start — delega p/ Lousa (todas as travas valem)
# ---------------------------------------------------------------------------
@router.post("/os/{ticket_id}/start")
@limiter.limit(get_limit("field_action"))
async def field_os_start(request: Request, ticket_id: str, payload: StartIn,
                         user: dict = Depends(get_current_user)):
    collab, read_only = await _resolve_collab(user)
    _require_write(read_only)
    company = _company_of(user)
    await _owned_ticket(ticket_id, collab, company)
    tg = await _toggles(company)
    _gps_gate(tg, payload.latitude, payload.longitude, "iniciar a OS")
    pend = await _vehicle_pending(company, collab["id"], tg)
    if pend:
        raise HTTPException(412, pend)

    from routes.lousa import PublicOpenIn, public_open_ticket
    result = await public_open_ticket(
        ticket_id, PublicOpenIn(collaborator_id=collab["id"]), request)

    if payload.latitude is not None and payload.longitude is not None:
        await db.tickets.update_one(
            {"id": ticket_id},
            {"$set": {"field_start_location": {
                "lat": payload.latitude, "lng": payload.longitude,
                "at": now_iso()}}})

    await _audit(company, "FIELD_OS_STARTED", user, collab["id"], ticket_id)
    await _emit(EventType.FIELD_OS_STARTED, company, user, {
        "ticket_id": ticket_id, "collaborator_id": collab["id"],
        "collaborator_name": collab.get("name"),
        "client": (result.get("client_snapshot") or {}).get("name"),
        "type": result.get("type"),
    })
    return {"ok": True, "ticket": result}


# ---------------------------------------------------------------------------
# POST /api/field/os/{id}/arrive — cheguei no local (GPS sempre obrigatório)
# ---------------------------------------------------------------------------
@router.post("/os/{ticket_id}/arrive")
@limiter.limit(get_limit("field_action"))
async def field_os_arrive(request: Request, ticket_id: str, payload: ArriveIn,
                          user: dict = Depends(get_current_user)):
    collab, read_only = await _resolve_collab(user)
    _require_write(read_only)
    company = _company_of(user)
    t = await _owned_ticket(ticket_id, collab, company)
    if t["status"] not in ("pendente", "aberta"):
        raise HTTPException(400, "OS não está em andamento")
    now = now_iso()
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {"field_arrived_at": now,
                  "field_arrive_location": {
                      "lat": payload.latitude, "lng": payload.longitude,
                      "accuracy": payload.accuracy, "at": now},
                  "updated_at": now}})
    await _log_lousa(ticket_id, "chegada_local", collab,
                     "Técnico chegou ao local do cliente (GPS registrado)",
                     company)
    await _audit(company, "FIELD_OS_ARRIVED", user, collab["id"], ticket_id,
                 lat=payload.latitude, lng=payload.longitude)
    await _emit(EventType.FIELD_OS_ARRIVED, company, user, {
        "ticket_id": ticket_id, "collaborator_id": collab["id"],
        "lat": payload.latitude, "lng": payload.longitude,
    })
    return {"ok": True, "arrived_at": now}


# ---------------------------------------------------------------------------
# POST /api/field/os/{id}/photo
# ---------------------------------------------------------------------------
@router.post("/os/{ticket_id}/photo")
@limiter.limit(get_limit("field_action"))
async def field_os_photo(request: Request, ticket_id: str, payload: PhotoIn,
                         user: dict = Depends(get_current_user)):
    collab, read_only = await _resolve_collab(user)
    _require_write(read_only)
    company = _company_of(user)
    t = await _owned_ticket(ticket_id, collab, company)
    existing = len(t.get("field_photos") or [])
    if existing >= 40:
        raise HTTPException(400, "Limite de 40 fotos por OS atingido")
    photo_id = f"fph-{uuid.uuid4().hex[:10]}"
    now = now_iso()
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$push": {"field_photos": {
            "id": photo_id, "kind": payload.kind, "label": payload.label,
            "data_url": payload.data_url, "by": collab["id"], "at": now}},
         "$set": {"updated_at": now}})
    await _log_lousa(ticket_id, "foto_anexada", collab,
                     f"Foto anexada ({payload.label or payload.kind})", company)
    await _audit(company, "FIELD_PHOTO_UPLOADED", user, collab["id"],
                 ticket_id, photo_id=photo_id, kind=payload.kind)
    await _emit(EventType.FIELD_PHOTO_UPLOADED, company, user, {
        "ticket_id": ticket_id, "collaborator_id": collab["id"],
        "photo_id": photo_id, "kind": payload.kind, "label": payload.label,
    }, severity="baixa")
    return {"ok": True, "photo_id": photo_id, "total": existing + 1}


# ---------------------------------------------------------------------------
# POST /api/field/os/{id}/signal-test
# ---------------------------------------------------------------------------
@router.post("/os/{ticket_id}/signal-test")
@limiter.limit(get_limit("field_action"))
async def field_os_signal(request: Request, ticket_id: str,
                          payload: SignalTestIn,
                          user: dict = Depends(get_current_user)):
    collab, read_only = await _resolve_collab(user)
    _require_write(read_only)
    company = _company_of(user)
    await _owned_ticket(ticket_id, collab, company)
    now = now_iso()
    entry = {"id": f"fst-{uuid.uuid4().hex[:10]}", "phase": payload.phase,
             "dbm": payload.dbm, "notes": payload.notes,
             "by": collab["id"], "at": now}
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$push": {"field_signal_tests": entry}, "$set": {"updated_at": now}})
    label = "antes" if payload.phase == "before" else "depois"
    await _log_lousa(ticket_id, "sinal_registrado", collab,
                     f"Sinal {label}: {payload.dbm} dBm", company)
    await _audit(company, "FIELD_SIGNAL_REGISTERED", user, collab["id"],
                 ticket_id, dbm=payload.dbm, phase=payload.phase)
    await _emit(EventType.FIELD_SIGNAL_REGISTERED, company, user, {
        "ticket_id": ticket_id, "collaborator_id": collab["id"],
        "dbm": payload.dbm, "phase": payload.phase,
    }, severity="alta" if payload.dbm < -27 else "media")
    return {"ok": True, "entry": entry}


# ---------------------------------------------------------------------------
# POST /api/field/os/{id}/material-used — baixa REAL no estoque do técnico
# ---------------------------------------------------------------------------
@router.post("/os/{ticket_id}/material-used")
@limiter.limit(get_limit("field_action"))
async def field_os_material(request: Request, ticket_id: str,
                            payload: MaterialUsedIn,
                            user: dict = Depends(get_current_user)):
    collab, read_only = await _resolve_collab(user)
    _require_write(read_only)
    company = _company_of(user)
    t = await _owned_ticket(ticket_id, collab, company)

    from routes.stok import (CONSUMABLE_BY_ID, UsedItem, _check_tech_has_stock,
                             _decrement_tech_stock, _notify_negative_stock)
    used: List[UsedItem] = []
    for it in payload.items:
        if it.consumable_id not in CONSUMABLE_BY_ID:
            raise HTTPException(400, f"Material inválido: {it.consumable_id}")
        used.append(UsedItem(consumable_id=it.consumable_id,
                             quantity=it.quantity))

    tg = await _toggles(company)
    shortages = await _check_tech_has_stock(
        company, collab["id"], collab.get("name", "Técnico"), used)
    if shortages and tg.get("block_material_without_stock"):
        raise HTTPException(409, {
            "code": "INSUFFICIENT_STOCK",
            "message": "Estoque insuficiente para os materiais informados.",
            "shortages": shortages,
        })

    desc = await _decrement_tech_stock(company, collab["id"], used)
    now = now_iso()
    items_doc = [{"consumable_id": u.consumable_id,
                  "name": CONSUMABLE_BY_ID[u.consumable_id]["name"],
                  "unit": CONSUMABLE_BY_ID[u.consumable_id]["unit"],
                  "quantity": u.quantity} for u in used]
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$push": {"field_materials": {
            "id": f"fmt-{uuid.uuid4().hex[:10]}", "items": items_doc,
            "by": collab["id"], "at": now}},
         "$set": {"updated_at": now}})
    await db.stok_history.insert_one({
        "id": f"sh-{uuid.uuid4().hex[:12]}", "company_id": company,
        "type": "field_material_used", "technician_id": collab["id"],
        "technician_name": collab.get("name"), "ticket_id": ticket_id,
        "client_name": (t.get("client_snapshot") or {}).get("name"),
        "items": items_doc, "at": now,
    })
    if shortages:
        try:
            await _notify_negative_stock(company, shortages, ticket_id=ticket_id)
        except Exception:
            pass
    await _log_lousa(ticket_id, "material_usado", collab,
                     desc or "Materiais registrados", company)
    await _audit(company, "FIELD_MATERIAL_USED", user, collab["id"],
                 ticket_id, items=items_doc)
    await _emit(EventType.FIELD_MATERIAL_USED, company, user, {
        "ticket_id": ticket_id, "collaborator_id": collab["id"],
        "items": items_doc, "shortages": shortages,
    })
    await _emit(EventType.FIELD_STOCK_UPDATED, company, user, {
        "collaborator_id": collab["id"], "reason": "material_used",
        "ticket_id": ticket_id,
    }, severity="baixa")
    return {"ok": True, "description": desc, "shortages": shortages}


# ---------------------------------------------------------------------------
# POST /api/field/os/{id}/finish — delega p/ Lousa (checklist/fotos/sinal/CTO)
# ---------------------------------------------------------------------------
@router.post("/os/{ticket_id}/finish")
@limiter.limit(get_limit("field_action"))
async def field_os_finish(request: Request, ticket_id: str, payload: FinishIn,
                          background_tasks: BackgroundTasks,
                          user: dict = Depends(get_current_user)):
    collab, read_only = await _resolve_collab(user)
    _require_write(read_only)
    company = _company_of(user)
    await _owned_ticket(ticket_id, collab, company)
    tg = await _toggles(company)
    _gps_gate(tg, payload.latitude, payload.longitude, "finalizar a OS")

    from routes.lousa import (CompletionData, PublicFinalizeIn,
                              public_finalize_ticket)
    try:
        cd = CompletionData(**(payload.completion_data or {}))
    except Exception as e:
        raise HTTPException(422, safe_detail(422, e, "completion_data inválido:"))
    fin = PublicFinalizeIn(
        collaborator_id=collab["id"], completion_data=cd,
        latitude=payload.latitude if payload.latitude is not None else 0.0,
        longitude=payload.longitude if payload.longitude is not None else 0.0,
        outcome=payload.outcome,
        bad_signal_auth_id=payload.bad_signal_auth_id)
    result = await public_finalize_ticket(
        ticket_id, fin, background_tasks, request)

    await _audit(company, "FIELD_OS_FINISHED", user, collab["id"], ticket_id,
                 outcome=payload.outcome)
    await _emit(EventType.FIELD_OS_FINISHED, company, user, {
        "ticket_id": ticket_id, "collaborator_id": collab["id"],
        "collaborator_name": collab.get("name"), "outcome": payload.outcome,
        "sinal": (payload.completion_data or {}).get("sinal"),
    }, severity="media")
    # Isabella Field President: nota de instalação/reparo + causa raiz
    isabella_score = None
    try:
        from services.isabella_field import score_finish
        isabella_score = await score_finish(company, collab, ticket_id,
                                            payload.outcome)
    except Exception as e:
        logger.warning("[field_ops] isabella score_finish fail: %s", e)
    return {"ok": True, "result": result, "isabella_score": isabella_score}


# ---------------------------------------------------------------------------
# POST /api/field/os/{id}/reschedule — técnico PROPÕE; gestor confirma
# ---------------------------------------------------------------------------
@router.post("/os/{ticket_id}/reschedule")
@limiter.limit(get_limit("field_action"))
async def field_os_reschedule(request: Request, ticket_id: str,
                              payload: RescheduleIn,
                              user: dict = Depends(get_current_user)):
    collab, read_only = await _resolve_collab(user)
    _require_write(read_only)
    company = _company_of(user)
    t = await _owned_ticket(ticket_id, collab, company)
    if t["status"] not in ("pendente", "aberta"):
        raise HTTPException(400, "OS não pode mais ser reagendada")
    snap = t.get("client_snapshot") or {}
    req_id = f"mcr-{uuid.uuid4().hex[:12]}"
    now = now_iso()
    await db.lousa_manager_callback_requests.insert_one({
        "id": req_id, "company_id": company, "kind": "reschedule",
        "ticket_id": ticket_id, "ticket_type": t.get("type"),
        "collaborator_id": collab["id"],
        "collaborator_name": collab.get("name", "Técnico"),
        "client_name": snap.get("name") or "",
        "client_phone": snap.get("phone") or "",
        "client_address": snap.get("address") or "",
        "motivo": payload.motivo,
        "proposed_date": payload.new_date, "proposed_time": payload.new_time,
        "status": "pending", "created_at": now, "requested_at": now,
    })
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {"needs_manager_action": True,
                  "reschedule_requested": True,
                  "reschedule_request_id": req_id,
                  "updated_at": now}})
    try:
        await db.notifications.insert_one({
            "id": f"notif-{uuid.uuid4().hex[:10]}", "company_id": company,
            "type": "field_reschedule_request", "severity": "warning",
            "title": "Reagendamento solicitado pelo técnico",
            "body": (f"{collab.get('name', 'Técnico')} propôs reagendar a OS de "
                     f"{snap.get('name') or 'cliente'} para "
                     f"{payload.new_date} {payload.new_time}. "
                     f"Motivo: {payload.motivo[:120]}"),
            "ticket_id": ticket_id, "callback_request_id": req_id,
            "target_roles": ["gestor", "administrador"], "read_by": [],
            "created_at": now,
        })
    except Exception:
        pass
    await _log_lousa(ticket_id, "reagendamento_solicitado", collab,
                     f"Propôs {payload.new_date} {payload.new_time} — {payload.motivo}",
                     company)
    await _audit(company, "FIELD_OS_RESCHEDULE_REQUESTED", user, collab["id"],
                 ticket_id, new_date=payload.new_date, new_time=payload.new_time)
    await _emit(EventType.FIELD_OS_RESCHEDULED, company, user, {
        "ticket_id": ticket_id, "collaborator_id": collab["id"],
        "proposed_date": payload.new_date, "proposed_time": payload.new_time,
        "motivo": payload.motivo,
    })
    return {"ok": True, "request_id": req_id,
            "message": "Reagendamento enviado ao gestor para confirmação."}


# ---------------------------------------------------------------------------
# POST /api/field/os/{id}/block-reason — justificar impedimento
# ---------------------------------------------------------------------------
@router.post("/os/{ticket_id}/block-reason")
@limiter.limit(get_limit("field_action"))
async def field_os_block_reason(request: Request, ticket_id: str,
                                payload: BlockReasonIn,
                                user: dict = Depends(get_current_user)):
    collab, read_only = await _resolve_collab(user)
    _require_write(read_only)
    company = _company_of(user)
    t = await _owned_ticket(ticket_id, collab, company)
    if t["status"] not in ("pendente", "aberta"):
        raise HTTPException(400, "OS não está em andamento")
    snap = t.get("client_snapshot") or {}
    req_id = f"mcr-{uuid.uuid4().hex[:12]}"
    now = now_iso()
    await db.lousa_manager_callback_requests.insert_one({
        "id": req_id, "company_id": company, "kind": "blocked",
        "ticket_id": ticket_id, "ticket_type": t.get("type"),
        "collaborator_id": collab["id"],
        "collaborator_name": collab.get("name", "Técnico"),
        "client_name": snap.get("name") or "",
        "client_phone": snap.get("phone") or "",
        "client_address": snap.get("address") or "",
        "motivo": payload.motivo,
        "latitude": payload.latitude, "longitude": payload.longitude,
        "status": "pending", "created_at": now, "requested_at": now,
    })
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {"needs_manager_action": True,
                  "manager_callback_required": True,
                  "manager_callback_request_id": req_id,
                  "manager_callback_motivo": payload.motivo,
                  "manager_callback_requested_by": collab["id"],
                  "manager_callback_requested_at": now,
                  "updated_at": now}})
    try:
        await db.notifications.insert_one({
            "id": f"notif-{uuid.uuid4().hex[:10]}", "company_id": company,
            "type": "manager_callback_required", "severity": "warning",
            "title": "Impedimento registrado pelo técnico",
            "body": (f"{collab.get('name', 'Técnico')} registrou impedimento na OS de "
                     f"{snap.get('name') or 'cliente'}: {payload.motivo[:140]}"),
            "ticket_id": ticket_id, "callback_request_id": req_id,
            "target_roles": ["gestor", "administrador"], "read_by": [],
            "created_at": now,
        })
    except Exception:
        pass
    await _log_lousa(ticket_id, "impedimento_registrado", collab,
                     payload.motivo[:200], company)
    await _audit(company, "FIELD_OS_BLOCKED", user, collab["id"], ticket_id,
                 motivo=payload.motivo[:200])
    await _emit(EventType.FIELD_OS_BLOCKED, company, user, {
        "ticket_id": ticket_id, "collaborator_id": collab["id"],
        "motivo": payload.motivo,
    }, severity="alta")
    return {"ok": True, "request_id": req_id,
            "message": "Impedimento registrado — gestor foi notificado."}


# ---------------------------------------------------------------------------
# GET /api/field/stock/me + catálogo de materiais
# ---------------------------------------------------------------------------
@router.get("/stock/me")
@limiter.limit(get_limit("field_read"))
async def field_stock_me(request: Request, cid: Optional[str] = None,
                         user: dict = Depends(get_current_user)):
    collab, read_only = await _resolve_collab(user, cid)
    company = _company_of(user)
    from routes.stok import CONSUMABLE_BY_ID
    stock_doc = await db.stok_stock.find_one(
        {"company_id": company, "location": collab["id"]}, {"_id": 0}) or {}
    consumables = []
    for k, v in stock_doc.items():
        if k in ("company_id", "location") or not isinstance(v, (int, float)):
            continue
        item = CONSUMABLE_BY_ID.get(k) or {"name": k, "unit": "un"}
        consumables.append({"consumable_id": k, "name": item["name"],
                            "unit": item["unit"], "quantity": v})
    consumables.sort(key=lambda x: x["name"])
    onts = await db.stok_onts.find(
        {"company_id": company, "location_type": "tecnico",
         "location_id": collab["id"]},
        {"_id": 0, "mac": 1, "scan_sn": 1, "model": 1, "status": 1,
         "created_at": 1}).sort("created_at", -1).to_list(100)
    return {"collaborator_id": collab["id"], "consumables": consumables,
            "onts": onts, "ont_count": len(onts), "read_only": read_only}


@router.get("/materials/catalog")
@limiter.limit(get_limit("field_read"))
async def field_materials_catalog(request: Request,
                                  user: dict = Depends(get_current_user)):
    from routes.stok import CONSUMABLE_CATALOG
    return {"items": CONSUMABLE_CATALOG}


# ---------------------------------------------------------------------------
# Frota IA — vistoria semanal (KM + 4 fotos)
# ---------------------------------------------------------------------------
@router.post("/vehicle/inspection")
@limiter.limit(get_limit("field_action"))
async def field_vehicle_inspection(request: Request,
                                   payload: VehicleInspectionIn,
                                   user: dict = Depends(get_current_user)):
    await _ensure_indexes()
    collab, read_only = await _resolve_collab(user)
    _require_write(read_only)
    company = _company_of(user)
    now_dt = datetime.now(SP_TZ)
    insp_id = f"fvi-{uuid.uuid4().hex[:12]}"
    doc = {
        "id": insp_id, "company_id": company,
        "collaborator_id": collab["id"],
        "collaborator_name": collab.get("name"),
        "plate": payload.plate.strip().upper(),
        "vehicle_model": payload.vehicle_model,
        "km": payload.km,
        "photos": {"front": payload.photo_front, "rear": payload.photo_rear,
                   "left": payload.photo_left, "right": payload.photo_right},
        "notes": payload.notes,
        "week_key": f"{now_dt.isocalendar().year}-W{now_dt.isocalendar().week:02d}",
        "created_at": now_iso(),
    }
    await db.field_vehicle_inspections.insert_one(doc)
    await _audit(company, "FIELD_VEHICLE_INSPECTION_DONE", user, collab["id"],
                 plate=doc["plate"], km=payload.km, inspection_id=insp_id)
    await _emit(EventType.FIELD_VEHICLE_INSPECTION_DONE, company, user, {
        "inspection_id": insp_id, "collaborator_id": collab["id"],
        "plate": doc["plate"], "km": payload.km,
    })
    # Isabella: nota imediata + análise visual do Álvaro IA em background
    isabella_score = None
    try:
        from services.isabella_field import score_vehicle_inspection
        isabella_score = await score_vehicle_inspection(insp_id)
    except Exception as e:
        logger.warning("[field_ops] isabella vehicle score fail: %s", e)
    tg = await _toggles(company)
    max_age = int(tg.get("vehicle_inspection_max_age_days") or 7)
    return {"ok": True, "inspection_id": insp_id,
            "isabella_score": isabella_score,
            "next_due": (datetime.now(timezone.utc)
                         + timedelta(days=max_age)).isoformat()}


@router.get("/vehicle/status")
@limiter.limit(get_limit("field_read"))
async def field_vehicle_status(request: Request, cid: Optional[str] = None,
                               user: dict = Depends(get_current_user)):
    await _ensure_indexes()
    collab, read_only = await _resolve_collab(user, cid)
    company = _company_of(user)
    tg = await _toggles(company)
    last = await db.field_vehicle_inspections.find_one(
        {"company_id": company, "collaborator_id": collab["id"]},
        {"_id": 0, "photos": 0}, sort=[("created_at", -1)])
    pend = await _vehicle_pending(company, collab["id"], tg)
    max_age = int(tg.get("vehicle_inspection_max_age_days") or 7)
    next_due = None
    if last:
        try:
            next_due = (datetime.fromisoformat(last["created_at"])
                        + timedelta(days=max_age)).isoformat()
        except Exception:
            pass
    return {"required": bool(tg.get("vehicle_inspection_required")),
            "pending": bool(pend), "last_inspection": last,
            "next_due": next_due, "max_age_days": max_age,
            "read_only": read_only}


# ---------------------------------------------------------------------------
# POST /api/field/equipment/return — retirada com impacto financeiro real
# ---------------------------------------------------------------------------
@router.post("/equipment/return")
@limiter.limit(get_limit("field_action"))
async def field_equipment_return(request: Request,
                                 payload: EquipmentReturnIn,
                                 user: dict = Depends(get_current_user)):
    await _ensure_indexes()
    collab, read_only = await _resolve_collab(user)
    _require_write(read_only)
    company = _company_of(user)
    if not payload.mac and not payload.sn:
        raise HTTPException(400, "Informe MAC ou SN do equipamento")

    ticket = None
    client_name = None
    client_id = None
    if payload.ticket_id:
        ticket = await _owned_ticket(payload.ticket_id, collab, company)
        client_name = (ticket.get("client_snapshot") or {}).get("name")
        client_id = ticket.get("client_id")

    # Localiza a ONT no estoque real
    ors: List[dict] = []
    mac = (payload.mac or "").strip().upper() or None
    sn = (payload.sn or "").strip().upper() or None
    if mac:
        ors.append({"mac": mac})
    if sn:
        ors += [{"scan_sn": sn}, {"sn": sn}]
    ont = await db.stok_onts.find_one(
        {"company_id": company, "$or": ors}, {"_id": 0})

    now = now_iso()
    new_status = ("retirada_com_tecnico" if payload.physical_state == "bom"
                  else "defeito_devolver_empresa")
    # Onda 2.6 — quando há recovery de equipamento existente, exige reason
    # e canaliza via transfer_engine (cliente→tecnico com manual=True para
    # cobrir cenários sem OS). Quando ONT não existe ainda, criamos no banco
    # como gênese (Onda 4) — sem trilha por enquanto.
    transfer_audit_id = None
    transfer_audit_hash = None
    if payload.recovered:
        if ont:
            if not payload.reason or not (payload.reason.get("code") or "").strip():
                raise HTTPException(400, {
                    "error": "transfer_reason_required",
                    "message": "equipment/return com recovered=true exige "
                               "payload.reason ({code,details?}).",
                })
            from services.transfer_engine import (
                execute_transfer, TransferEngineError,
            )
            try:
                tr = await execute_transfer(
                    company_id=company,
                    origin_type=("cliente" if ont.get("location_type") == "cliente"
                                  else "tecnico"),
                    origin_id=ont.get("location_id"),
                    destination_type="tecnico",
                    destination_id=collab["id"],
                    actor={"id": collab.get("id"),
                            "email": collab.get("email"),
                            "name": collab.get("name"),
                            "role": "tecnico",
                            "origin": "field_ops_equipment_return",
                            "physical_attendance": True},
                    reason=payload.reason,
                    mac=ont["mac"],
                    ticket_id=payload.ticket_id,
                    manual=(ont.get("location_type") != "cliente"),
                    extra_set_fields={
                        "status": new_status,
                        "field_returned_at": now,
                        "field_physical_state": payload.physical_state,
                    },
                )
                transfer_audit_id = tr["movement_id"]
                transfer_audit_hash = tr["audit_hash"]
            except TransferEngineError as e:
                raise HTTPException(400, {
                    "error": "transfer_blocked", "message": str(e)})
        else:
            # Equipamento recuperado mas não cadastrado — entra no estoque
            ont = {
                "company_id": company,
                "mac": mac or f"SEM-MAC-{uuid.uuid4().hex[:8].upper()}",
                "scan_sn": sn, "model": "Desconhecido",
                "location_type": "tecnico", "location_id": collab["id"],
                "client_name": None, "status": new_status,
                "created_by": "field_equipment_return",
                "source": "field_equipment_return",
                "field_physical_state": payload.physical_state,
                "created_at": now,
            }
            await db.stok_onts.insert_one(dict(ont))
        await db.stok_history.insert_one({
            "id": f"sh-{uuid.uuid4().hex[:12]}", "company_id": company,
            "type": "field_equipment_return", "technician_id": collab["id"],
            "technician_name": collab.get("name"),
            "ticket_id": payload.ticket_id, "mac": ont.get("mac"),
            "sn": sn or ont.get("scan_sn"),
            "physical_state": payload.physical_state,
            "client_name": client_name, "at": now,
        })

    # Impacto financeiro (comodato): recuperado = valor recuperado; senão perda
    tg = await _toggles(company)
    cost = float(tg.get("equipment_default_cost") or 0)
    if payload.recovered and payload.physical_state == "inutilizado":
        value_recovered, value_lost = 0.0, cost
    elif payload.recovered:
        value_recovered, value_lost = cost, 0.0
    else:
        value_recovered, value_lost = 0.0, cost

    ret_id = f"fer-{uuid.uuid4().hex[:12]}"
    await db.field_equipment_returns.insert_one({
        "id": ret_id, "company_id": company,
        "collaborator_id": collab["id"],
        "collaborator_name": collab.get("name"),
        "ticket_id": payload.ticket_id,
        "client_id": client_id, "client_name": client_name,
        "mac": mac or (ont or {}).get("mac"),
        "sn": sn or (ont or {}).get("scan_sn"),
        "recovered": payload.recovered,
        "physical_state": payload.physical_state,
        "value_recovered": value_recovered,
        "value_lost": value_lost,
        "notes": payload.notes,
        "created_at": now,
    })

    # Libera a porta da CTO do cliente (retirada → porta volta a free)
    freed_port = None
    if client_id:
        try:
            from routes.stok import _find_client_cto_port, _free_cto_port
            link = await _find_client_cto_port(company, client_id)
            if link:
                await _free_cto_port(
                    company, link["cto_id"], int(link["port_number"]),
                    user.get("email"), "field_equipment_return",
                    client_id=client_id, client_name=client_name,
                    actor_name=collab.get("name"),
                    ticket_id=payload.ticket_id)
                freed_port = {"cto_id": link["cto_id"],
                              "port_number": link["port_number"]}
        except Exception as e:
            logger.warning("[field_ops] free cto port fail: %s", e)

    # Pendência financeira → notifica o financeiro
    if value_lost > 0:
        try:
            await db.notifications.insert_one({
                "id": f"notif-{uuid.uuid4().hex[:10]}", "company_id": company,
                "type": "field_equipment_loss", "severity": "warning",
                "title": "Equipamento de comodato com pendência",
                "body": (f"Retirada registrada por {collab.get('name', 'técnico')}: "
                         f"equipamento {mac or sn} "
                         f"{'inutilizado' if payload.recovered else 'NÃO devolvido'}. "
                         f"Perda estimada: R$ {value_lost:.2f}"),
                "ticket_id": payload.ticket_id,
                "target_roles": ["financeiro", "gestor", "administrador"],
                "read_by": [], "created_at": now,
            })
        except Exception:
            pass

    if payload.ticket_id:
        await _log_lousa(payload.ticket_id, "equipamento_retirado", collab,
                         (f"Equipamento {mac or sn} — "
                          f"{'recuperado (' + payload.physical_state + ')' if payload.recovered else 'NÃO devolvido'}"),
                         company)
    await _audit(company, "FIELD_EQUIPMENT_RETURNED", user, collab["id"],
                 payload.ticket_id, return_id=ret_id, mac=mac, sn=sn,
                 recovered=payload.recovered,
                 value_recovered=value_recovered, value_lost=value_lost)
    await _emit(EventType.FIELD_EQUIPMENT_RETURNED, company, user, {
        "return_id": ret_id, "collaborator_id": collab["id"],
        "ticket_id": payload.ticket_id, "mac": mac, "sn": sn,
        "recovered": payload.recovered,
        "physical_state": payload.physical_state,
        "value_recovered": value_recovered, "value_lost": value_lost,
        "freed_port": freed_port,
    }, severity="alta" if value_lost > 0 else "media")
    await _emit(EventType.FIELD_STOCK_UPDATED, company, user, {
        "collaborator_id": collab["id"], "reason": "equipment_return",
        "mac": mac, "sn": sn,
    }, severity="baixa")
    return {"ok": True, "return_id": ret_id,
            "value_recovered": value_recovered, "value_lost": value_lost,
            "freed_port": freed_port,
            "equipment_in_stock": payload.recovered,
            "transfer_audit_id": transfer_audit_id,
            "transfer_audit_hash": transfer_audit_hash}


# ---------------------------------------------------------------------------
# Settings (toggles por empresa) — gestor/admin
# ---------------------------------------------------------------------------
@router.get("/settings")
@limiter.limit(get_limit("field_read"))
async def field_settings_get(request: Request,
                             user: dict = Depends(get_current_user)):
    return await _toggles(_company_of(user))


@router.put("/settings")
@limiter.limit(get_limit("field_action"))
async def field_settings_put(request: Request, payload: FieldSettingsIn,
                             user: dict = Depends(get_current_user)):
    if not _is_privileged(user):
        raise HTTPException(403, "Apenas gestor/administrador pode alterar")
    company = _company_of(user)
    current = await _toggles(company)
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    merged = {**current, **updates}
    await db.aihub_settings.update_one(
        {"company_id": company, "key": "field_ops_toggles"},
        {"$set": {"value": merged, "updated_at": now_iso(),
                  "updated_by": user.get("email")}},
        upsert=True)
    await _audit(company, "FIELD_SETTINGS_UPDATED", user,
                 user.get("collaborator_id") or "-", changes=updates)
    return merged


# ---------------------------------------------------------------------------
# GET /api/field/admin/overview — painel do gestor
# ---------------------------------------------------------------------------
@router.get("/admin/overview")
@limiter.limit(get_limit("field_read"))
async def field_admin_overview(request: Request,
                               user: dict = Depends(get_current_user)):
    if not _is_privileged(user):
        raise HTTPException(403, "Acesso restrito a gestor/administrador")
    await _ensure_indexes()
    company = _company_of(user)
    start, end = _today_range_utc()
    now = now_iso()
    tg = await _toggles(company)

    collabs = await db.collaborators.find(
        {"company_id": company},
        {"_id": 0, "id": 1, "name": 1, "role": 1}).to_list(150)
    collab_ids = [c["id"] for c in collabs]

    # OS de hoje (todas da empresa)
    tickets = await db.tickets.find(
        {"company_id": company,
         "$or": [
             {"status": "aberta"},
             {"status": "pendente",
              "scheduled_time": {"$gte": start, "$lt": end}},
             {"status": {"$in": ["finalizada", "encerrada"]},
              "closed_at": {"$gte": start, "$lt": end}},
         ]},
        {"_id": 0, "id": 1, "status": 1, "type": 1, "scheduled_time": 1,
         "closed_at": 1, "opened_at": 1, "assigned_collaborator_id": 1,
         "client_snapshot.name": 1, "needs_manager_action": 1}).to_list(800)

    abertas = [t for t in tickets if t["status"] == "aberta"]
    pendentes = [t for t in tickets if t["status"] == "pendente"]
    atrasadas = [t for t in pendentes if (t.get("scheduled_time") or "") < now]
    finalizadas = [t for t in tickets
                   if t["status"] in ("finalizada", "encerrada")]

    # Último GPS por técnico
    gps_rows = await db.tech_locations.aggregate([
        {"$match": {"company_id": company, "collab_id": {"$in": collab_ids}}},
        {"$sort": {"captured_at": -1}},
        {"$group": {"_id": "$collab_id",
                    "captured_at": {"$first": "$captured_at"},
                    "lat": {"$first": "$lat"}, "lng": {"$first": "$lng"}}},
    ]).to_list(200)
    gps_by_collab = {g["_id"]: g for g in gps_rows}
    gps_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()

    # Estoque por técnico
    stock_rows = await db.stok_stock.find(
        {"company_id": company, "location": {"$in": collab_ids}},
        {"_id": 0}).to_list(200)
    stock_by_collab = {s.get("location"): s for s in stock_rows}
    ont_rows = await db.stok_onts.aggregate([
        {"$match": {"company_id": company, "location_type": "tecnico",
                    "location_id": {"$in": collab_ids}}},
        {"$group": {"_id": "$location_id", "count": {"$sum": 1}}},
    ]).to_list(200)
    onts_by_collab = {o["_id"]: o["count"] for o in ont_rows}

    # Frota por técnico
    max_age = int(tg.get("vehicle_inspection_max_age_days") or 7)
    insp_cutoff = (datetime.now(timezone.utc)
                   - timedelta(days=max_age)).isoformat()
    insp_rows = await db.field_vehicle_inspections.aggregate([
        {"$match": {"company_id": company}},
        {"$sort": {"created_at": -1}},
        {"$group": {"_id": "$collaborator_id",
                    "created_at": {"$first": "$created_at"},
                    "plate": {"$first": "$plate"},
                    "km": {"$first": "$km"}}},
    ]).to_list(200)
    insp_by_collab = {i["_id"]: i for i in insp_rows}

    techs = []
    for c in collabs:
        cid_ = c["id"]
        mine = [t for t in tickets if t.get("assigned_collaborator_id") == cid_]
        if not mine and cid_ not in gps_by_collab and cid_ not in onts_by_collab:
            continue  # colaborador sem atividade de campo — não polui o painel
        active_t = next((t for t in mine if t["status"] == "aberta"), None)
        fin_mine = [t for t in mine
                    if t["status"] in ("finalizada", "encerrada")]
        gps = gps_by_collab.get(cid_)
        stock = stock_by_collab.get(cid_) or {}
        consumable_total = sum(
            v for k, v in stock.items()
            if isinstance(v, (int, float)) and k not in ("company_id", "location"))
        insp = insp_by_collab.get(cid_)
        techs.append({
            "collaborator_id": cid_, "name": c.get("name"),
            "active_os": ({"id": active_t["id"],
                           "client": (active_t.get("client_snapshot") or {}).get("name"),
                           "type": active_t.get("type"),
                           "opened_at": active_t.get("opened_at")}
                          if active_t else None),
            "os_today": len(mine),
            "finalizadas_hoje": len(fin_mine),
            "gps": ({"lat": gps["lat"], "lng": gps["lng"],
                     "captured_at": gps["captured_at"],
                     "active": (gps.get("captured_at") or "") >= gps_cutoff}
                    if gps else None),
            "stock": {"consumable_total": consumable_total,
                      "ont_count": onts_by_collab.get(cid_, 0)},
            "vehicle": {
                "last_inspection_at": (insp or {}).get("created_at"),
                "plate": (insp or {}).get("plate"),
                "pending": (bool(tg.get("vehicle_inspection_required"))
                            and not (insp and (insp.get("created_at") or "") >= insp_cutoff)),
            },
        })
    techs.sort(key=lambda x: (-(1 if x["active_os"] else 0),
                              -x["finalizadas_hoje"]))

    # Retiradas — pendentes + financeiro 30d
    retiradas_pend = await db.tickets.count_documents(
        {"company_id": company, "type": "retirada",
         "status": {"$in": ["pendente", "aberta"]}})
    cutoff_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    returns_30d = await db.field_equipment_returns.find(
        {"company_id": company, "created_at": {"$gte": cutoff_30d}},
        {"_id": 0}).sort("created_at", -1).to_list(200)
    value_recovered_30d = sum(r.get("value_recovered") or 0 for r in returns_30d)
    value_lost_30d = sum(r.get("value_lost") or 0 for r in returns_30d)

    # Truck Roll Avoidance (30d): reparos resolvidos remotamente
    tra_remote = await db.tickets.count_documents(
        {"company_id": company,
         "status": {"$in": ["finalizada", "encerrada"]},
         "closed_at": {"$gte": cutoff_30d},
         "completion_data.resolution_kind": "remote"})

    return {
        "counts": {
            "tecnicos_em_campo": sum(1 for t in techs if t["active_os"]),
            "os_andamento": len(abertas),
            "os_pendentes": len(pendentes),
            "os_atrasadas": len(atrasadas),
            "os_finalizadas_hoje": len(finalizadas),
            "aguardando_gestor": sum(
                1 for t in tickets if t.get("needs_manager_action")),
            "retiradas_pendentes": retiradas_pend,
        },
        "techs": techs,
        "atrasadas": [{"id": t["id"],
                       "client": (t.get("client_snapshot") or {}).get("name"),
                       "type": t.get("type"),
                       "scheduled_time": t.get("scheduled_time"),
                       "collaborator_id": t.get("assigned_collaborator_id")}
                      for t in atrasadas[:30]],
        "equipment_returns": {
            "items": returns_30d[:15],
            "value_recovered_30d": value_recovered_30d,
            "value_lost_30d": value_lost_30d,
        },
        "truck_roll_avoidance_30d": tra_remote,
        "toggles": tg,
    }
