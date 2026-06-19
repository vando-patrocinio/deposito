"""
security_home.py — Módulo de Segurança Residencial (estilo Verisure).

Arquitetura espelha o Fleet Tracking:
  [Central JFL/Intelbras/Bosch] ──TCP/Contact ID──▶ [Gateway VPS]
                                                       │ HTTPS
                                                       ▼
                                              POST /api/security-home/ingest
                                                       │
                                                       ▼
                                                  MongoDB

Coleções:
  security_sites         — imóvel monitorado (casa, comércio, escritório)
                            {id, tenant_id, company_id, name, address,
                             plant_image_url, panel_id (Contact ID account),
                             active}
  security_zones         — agrupamentos lógicos dentro do site
                            (ex: "Térreo", "Quartos", "Garagem", "Externa")
  security_sensors       — sensores físicos
                            {id, site_id, zone_id, kind, label,
                             plant_x, plant_y (0..1 normalizados),
                             contact_zone (nº da zona na central),
                             state: ok|triggered|trouble|bypassed}
  security_alarms        — eventos disparados (Contact ID parsed)
                            {id, site_id, kind, severity, sensor_id,
                             contact_id_event, ts, acked,
                             acked_by, acked_at, resolution}
  security_arm_states    — histórico arm/disarm
                            {id, site_id, state: armed_away|armed_stay|disarmed,
                             changed_by, source: portal|panel|app, ts}
  security_panel_commands — fila pra gateway (arm/disarm/bypass)

Multi-tenant: security_tenant_id (revenda); company_id (SaaS owner).

Endpoints públicos (gateway):
  POST /api/security-home/ingest      — recebe evento Contact ID
  GET  /api/security-home/commands/{panel_id}   — gateway puxa
  POST /api/security-home/commands/{id}/ack

Endpoints autenticados (gestor/admin do SmartProv):
  CRUD /api/security-home/sites
  CRUD /api/security-home/sites/{id}/zones
  CRUD /api/security-home/sites/{id}/sensors
  POST /api/security-home/sites/{id}/arm
  POST /api/security-home/sites/{id}/disarm
  GET  /api/security-home/alarms
  POST /api/security-home/alarms/{id}/ack
  CRUD /api/security-home/tenants

Endpoints do PORTAL cliente final (token security_portal):
  POST /api/security-portal/auth/login
  GET  /api/security-portal/me
  GET  /api/security-portal/sites
  GET  /api/security-portal/sites/{id}/sensors
  POST /api/security-portal/sites/{id}/arm | /disarm | /panic
  GET  /api/security-portal/alarms
"""
from __future__ import annotations


from services.exception_sanitizer import safe_detail  # SECURITY_LOCK ART.13
NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "shield",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, List, Literal

import jwt
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, EmailStr, Field

from auth import hash_password, verify_password, _jwt_secret
from core import DEMO_COMPANY_ID, get_current_user, is_super_admin
from database import db

logger = logging.getLogger("ponto.security_home")
from rbac import mock_guard as _mock_guard

router = APIRouter(
    prefix="/api/security-home",
    tags=["security-home"],
    dependencies=[Depends(_mock_guard("security_home"))],
)
portal_router = APIRouter(prefix="/api/security-portal",
                            tags=["security-portal"])

INGEST_TOKEN = os.environ.get("SECURITY_INGEST_TOKEN", "")
JWT_ALGO = "HS256"
PORTAL_TOKEN_TTL_DAYS = 30


# ───────────────────────────── helpers ─────────────────────────────
def _cid(user: dict) -> str:
    if is_super_admin(user):
        return (user.get("_active_company") or user.get("company_id")
                or DEMO_COMPANY_ID)
    return user.get("company_id") or DEMO_COMPANY_ID


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_manager(user: dict):
    role = (user.get("role") or "").lower()
    roles = user.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    if not (is_super_admin(user)
            or role in ("gestor", "administrador", "admin", "super_admin")
            or any(r in {"gestor", "admin", "super_admin"} for r in roles)):
        raise HTTPException(403, "Apenas gestor/admin.")


def _tenant_filter(user: dict) -> dict:
    base = {"company_id": _cid(user)}
    tenant = user.get("security_tenant_id")
    if tenant:
        base["security_tenant_id"] = tenant
    return base


def _check_ingest_token(authorization: Optional[str]):
    if not INGEST_TOKEN:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Token ausente")
    if authorization.split(" ", 1)[1].strip() != INGEST_TOKEN:
        raise HTTPException(401, "Token inválido")


# ───────────────────────────── models ─────────────────────────────
SensorKind = Literal[
    "magnetic", "pir", "active_ir", "glass_break", "shock",
    "panic", "smoke", "co", "flood", "temperature", "camera",
]

ArmState = Literal["armed_away", "armed_stay", "disarmed", "panic"]


class SiteIn(BaseModel):
    name: str
    address: Optional[str] = ""
    panel_id: str = Field(..., min_length=2, max_length=10,
                            description="Conta do painel (Contact ID account)")
    panel_model: Optional[str] = ""
    panel_password: str = "1234"
    plant_image_url: Optional[str] = None
    security_tenant_id: Optional[str] = None
    active: bool = True
    notes: Optional[str] = ""


class ZoneIn(BaseModel):
    name: str
    color: str = "#3b82f6"


class SensorIn(BaseModel):
    label: str
    kind: SensorKind = "magnetic"
    contact_zone: int = Field(..., ge=1, le=999,
                                description="Nº da zona na central de alarme")
    zone_id: Optional[str] = None
    plant_x: float = 0.5   # 0..1
    plant_y: float = 0.5
    notes: Optional[str] = ""


class ContactIdIn(BaseModel):
    """Payload que o gateway envia após parsear o frame Contact ID.

    Formato Ademco Contact ID: ACCT MT QXYZ GG CCC S
      ACCT = conta (panel_id) 4 dígitos
      MT   = msg type (18 ou 98)
      Q    = 1=new event, 3=restore
      XYZ  = código do evento (130=burglary, 110=fire, 120=panic, etc)
      GG   = partição
      CCC  = zona (0=sistema, 999=usuário)
    """
    panel_id: str
    qualifier: int = 1            # 1=novo evento, 3=restore
    event_code: int               # 130, 110, 120, …
    partition: int = 0
    zone: int = 0
    raw: Optional[str] = None
    timestamp: Optional[str] = None


class PortalLoginIn(BaseModel):
    email: EmailStr
    password: str


class PortalUserIn(BaseModel):
    email: EmailStr
    password: str
    name: str = ""


# ───────────────────────────── índices ─────────────────────────────
async def ensure_indexes() -> None:
    try:
        await db.security_sites.create_index([("company_id", 1), ("panel_id", 1)],
                                               unique=True, sparse=True)
        await db.security_alarms.create_index([("site_id", 1), ("ts", -1)])
        await db.security_arm_states.create_index([("site_id", 1), ("ts", -1)])
        await db.security_portal_users.create_index("email", unique=True)
        logger.info("[security-home] indexes ensured")
    except Exception as e:
        logger.warning("[security-home] ensure_indexes falhou: %s", e)


# ────────────────────── INGEST (gateway Contact ID) ──────────────────────
# Map de códigos Contact ID mais comuns
CONTACT_ID_MAP = {
    110: {"kind": "fire", "severity": "critical", "label": "Incêndio"},
    111: {"kind": "smoke", "severity": "high", "label": "Fumaça"},
    120: {"kind": "panic", "severity": "critical", "label": "Pânico"},
    121: {"kind": "duress", "severity": "critical", "label": "Senha de coação"},
    122: {"kind": "panic_silent", "severity": "critical", "label": "Pânico silencioso"},
    123: {"kind": "panic_audible", "severity": "critical", "label": "Pânico audível"},
    130: {"kind": "burglary", "severity": "high", "label": "Invasão"},
    131: {"kind": "perimeter", "severity": "high", "label": "Perímetro"},
    132: {"kind": "interior", "severity": "high", "label": "Interior"},
    133: {"kind": "24h_aux", "severity": "high", "label": "24h auxiliar"},
    134: {"kind": "entry_exit", "severity": "medium", "label": "Entrada/Saída"},
    137: {"kind": "tamper", "severity": "high", "label": "Tamper (violação)"},
    140: {"kind": "general", "severity": "medium", "label": "Alarme geral"},
    150: {"kind": "flood", "severity": "medium", "label": "Inundação/Vazamento"},
    151: {"kind": "gas", "severity": "high", "label": "Vazamento de gás"},
    154: {"kind": "water", "severity": "medium", "label": "Água"},
    301: {"kind": "ac_loss", "severity": "low", "label": "Sem energia AC"},
    302: {"kind": "low_battery", "severity": "low", "label": "Bateria fraca"},
    354: {"kind": "comm_fail", "severity": "medium", "label": "Falha comunicação"},
    401: {"kind": "armed_away", "severity": "info", "label": "Armado total"},
    441: {"kind": "armed_stay", "severity": "info", "label": "Armado parcial"},
    402: {"kind": "disarmed", "severity": "info", "label": "Desarmado"},
}


@router.post("/ingest")
async def ingest_contact_id(
    ev: ContactIdIn,
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    _check_ingest_token(authorization)

    site = await db.security_sites.find_one({"panel_id": ev.panel_id},
                                              {"_id": 0})
    if not site:
        # painel desconhecido
        return {"ok": False, "reason": "panel-not-registered"}

    meta = CONTACT_ID_MAP.get(ev.event_code, {
        "kind": f"code_{ev.event_code}",
        "severity": "medium",
        "label": f"Evento Contact ID {ev.event_code}",
    })
    is_restore = ev.qualifier == 3

    # Tenta achar o sensor pela zona
    sensor = None
    if ev.zone > 0:
        sensor = await db.security_sensors.find_one(
            {"site_id": site["id"], "contact_zone": ev.zone}, {"_id": 0})

    # Atualiza estado do sensor
    if sensor:
        new_state = "ok" if is_restore else "triggered"
        await db.security_sensors.update_one(
            {"id": sensor["id"]},
            {"$set": {"state": new_state, "last_event_at": _now_iso()}})

    # Eventos de arm/disarm atualizam o site
    if ev.event_code in (401, 441, 402):
        new_arm = ({401: "armed_away", 441: "armed_stay", 402: "disarmed"}
                     [ev.event_code])
        await db.security_sites.update_one(
            {"id": site["id"]},
            {"$set": {"arm_state": new_arm, "last_arm_changed": _now_iso()}})
        await db.security_arm_states.insert_one({
            "id": f"sas-{uuid.uuid4().hex[:12]}",
            "site_id": site["id"], "company_id": site["company_id"],
            "state": new_arm, "source": "panel",
            "ts": _now_iso(),
        })

    # Persiste o alarme
    alarm = {
        "id": f"alm-{uuid.uuid4().hex[:14]}",
        "site_id": site["id"],
        "company_id": site["company_id"],
        "security_tenant_id": site.get("security_tenant_id"),
        "kind": meta["kind"],
        "severity": meta["severity"] if not is_restore else "info",
        "label": meta["label"] + (" (restaurado)" if is_restore else ""),
        "event_code": ev.event_code,
        "qualifier": ev.qualifier,
        "partition": ev.partition,
        "contact_zone": ev.zone,
        "sensor_id": sensor["id"] if sensor else None,
        "is_restore": is_restore,
        "raw": ev.raw,
        "ts": ev.timestamp or _now_iso(),
        "received_at": _now_iso(),
        "acked": False,
    }
    await db.security_alarms.insert_one(alarm)
    logger.info("[security-home] alarm site=%s code=%d zone=%d %s",
                site["id"], ev.event_code, ev.zone, meta["label"])
    return {"ok": True, "alarm_id": alarm["id"]}


@router.get("/commands/{panel_id}")
async def gateway_pull_commands(
    panel_id: str,
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    _check_ingest_token(authorization)
    cur = db.security_panel_commands.find(
        {"panel_id": panel_id, "status": "pending"},
        {"_id": 0}).sort("created_at", 1).limit(10)
    return await cur.to_list(10)


@router.post("/commands/{cmd_id}/ack")
async def gateway_ack(cmd_id: str, result: dict,
                       authorization: Optional[str] =
                       Header(None, alias="Authorization")):
    _check_ingest_token(authorization)
    await db.security_panel_commands.update_one(
        {"id": cmd_id},
        {"$set": {"status": "ack" if result.get("ok") else "failed",
                    "result": result, "acked_at": _now_iso()}})
    return {"ok": True}


# ────────────────────── CRUD sites ──────────────────────
@router.get("/sites")
async def list_sites(user: dict = Depends(get_current_user)):
    cur = db.security_sites.find(_tenant_filter(user), {"_id": 0}) \
        .sort("name", 1)
    return await cur.to_list(2000)


@router.post("/sites")
async def create_site(payload: SiteIn,
                       user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = _cid(user)
    dup = await db.security_sites.find_one(
        {"company_id": cid, "panel_id": payload.panel_id})
    if dup:
        raise HTTPException(409, f"panel_id {payload.panel_id} já cadastrado")
    sid = f"sh-{uuid.uuid4().hex[:12]}"
    doc = payload.model_dump()
    doc.update({"id": sid, "company_id": cid,
                 "arm_state": "disarmed", "last_arm_changed": _now_iso(),
                 "created_at": _now_iso(), "created_by": user.get("id")})
    await db.security_sites.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/sites/{sid}")
async def update_site(sid: str, payload: SiteIn,
                       user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = _cid(user)
    upd = payload.model_dump(exclude_unset=True)
    upd["updated_at"] = _now_iso()
    r = await db.security_sites.update_one(
        {"id": sid, "company_id": cid}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(404)
    return {"ok": True}


@router.delete("/sites/{sid}")
async def delete_site(sid: str, user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = _cid(user)
    r = await db.security_sites.delete_one({"id": sid, "company_id": cid})
    if r.deleted_count == 0:
        raise HTTPException(404)
    # Cascata
    await db.security_sensors.delete_many({"site_id": sid})
    await db.security_zones.delete_many({"site_id": sid})
    return {"ok": True}


# ────────────────────── CRUD sensors ──────────────────────
@router.get("/sites/{sid}/sensors")
async def list_sensors(sid: str, user: dict = Depends(get_current_user)):
    cur = db.security_sensors.find({"site_id": sid}, {"_id": 0})
    return await cur.to_list(2000)


@router.post("/sites/{sid}/sensors")
async def create_sensor(sid: str, payload: SensorIn,
                          user: dict = Depends(get_current_user)):
    _require_manager(user)
    sensor_id = f"ssr-{uuid.uuid4().hex[:12]}"
    doc = payload.model_dump()
    doc.update({"id": sensor_id, "site_id": sid,
                 "company_id": _cid(user),
                 "state": "ok", "created_at": _now_iso()})
    await db.security_sensors.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/sensors/{sensor_id}")
async def update_sensor(sensor_id: str, payload: SensorIn,
                          user: dict = Depends(get_current_user)):
    _require_manager(user)
    upd = payload.model_dump(exclude_unset=True)
    r = await db.security_sensors.update_one(
        {"id": sensor_id}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(404)
    return {"ok": True}


@router.delete("/sensors/{sensor_id}")
async def delete_sensor(sensor_id: str,
                          user: dict = Depends(get_current_user)):
    _require_manager(user)
    await db.security_sensors.delete_one({"id": sensor_id})
    return {"ok": True}


# ────────────────────── Arm/Disarm/Panic (admin) ──────────────────────
@router.post("/sites/{sid}/arm")
async def admin_arm(sid: str,
                     mode: Literal["away", "stay"] = "away",
                     user: dict = Depends(get_current_user)):
    return await _change_arm_state(sid, f"armed_{mode}",
                                      source="admin",
                                      actor_id=user.get("id"),
                                      actor_email=user.get("email", ""))


@router.post("/sites/{sid}/disarm")
async def admin_disarm(sid: str,
                         user: dict = Depends(get_current_user)):
    return await _change_arm_state(sid, "disarmed",
                                      source="admin",
                                      actor_id=user.get("id"),
                                      actor_email=user.get("email", ""))


async def _change_arm_state(sid: str, new_state: str, source: str,
                              actor_id: str = "", actor_email: str = ""):
    site = await db.security_sites.find_one({"id": sid}, {"_id": 0})
    if not site:
        raise HTTPException(404)
    await db.security_sites.update_one(
        {"id": sid},
        {"$set": {"arm_state": new_state,
                    "last_arm_changed": _now_iso()}})
    state_id = f"sas-{uuid.uuid4().hex[:12]}"
    await db.security_arm_states.insert_one({
        "id": state_id, "site_id": sid, "company_id": site["company_id"],
        "state": new_state, "source": source,
        "actor_id": actor_id, "actor_email": actor_email,
        "ts": _now_iso(),
    })
    # Cria comando pro gateway enviar pra central
    cmd_kind = {"armed_away": "arm_away", "armed_stay": "arm_stay",
                 "disarmed": "disarm"}.get(new_state)
    if cmd_kind:
        await db.security_panel_commands.insert_one({
            "id": f"shc-{uuid.uuid4().hex[:12]}",
            "panel_id": site["panel_id"],
            "panel_password": site.get("panel_password", "1234"),
            "site_id": sid, "company_id": site["company_id"],
            "kind": cmd_kind, "status": "pending",
            "created_at": _now_iso(), "actor_email": actor_email,
        })
    return {"ok": True, "state": new_state}


# ────────────────────── Alarms list/ack ──────────────────────
@router.get("/alarms")
async def list_alarms(acked: Optional[bool] = None,
                       limit: int = 200,
                       user: dict = Depends(get_current_user)):
    q = {"company_id": _cid(user)}
    if acked is not None:
        q["acked"] = acked
    cur = db.security_alarms.find(q, {"_id": 0}).sort("ts", -1).limit(limit)
    return await cur.to_list(limit)


@router.post("/alarms/{alarm_id}/ack")
async def ack_alarm(alarm_id: str,
                      resolution: Optional[str] = "",
                      user: dict = Depends(get_current_user)):
    r = await db.security_alarms.update_one(
        {"id": alarm_id, "company_id": _cid(user)},
        {"$set": {"acked": True, "acked_by": user.get("email", ""),
                    "acked_at": _now_iso(), "resolution": resolution}})
    if r.matched_count == 0:
        raise HTTPException(404)
    return {"ok": True}


# ────────────────────── Tenants ──────────────────────
class TenantIn(BaseModel):
    name: str
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    monthly_fee: float = 0.0


@router.get("/tenants")
async def list_tenants(user: dict = Depends(get_current_user)):
    _require_manager(user)
    cur = db.security_tenants.find({"company_id": _cid(user)}, {"_id": 0})
    return await cur.to_list(500)


@router.post("/tenants")
async def create_tenant(payload: TenantIn,
                         user: dict = Depends(get_current_user)):
    _require_manager(user)
    tid = f"st-{uuid.uuid4().hex[:12]}"
    doc = payload.model_dump()
    doc.update({"id": tid, "company_id": _cid(user),
                 "active": True, "created_at": _now_iso()})
    await db.security_tenants.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ════════════════════════════════════════════════════════════════════
# PORTAL CLIENTE FINAL — /api/security-portal
# ════════════════════════════════════════════════════════════════════
def _issue_portal_token(user: dict) -> str:
    payload = {
        "sub": user["id"], "email": user["email"],
        "name": user.get("name", ""),
        "company_id": user["company_id"],
        "security_tenant_id": user["security_tenant_id"],
        "type": "security_portal",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc)
                     + timedelta(days=PORTAL_TOKEN_TTL_DAYS)).timestamp()),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGO)


async def get_portal_user(authorization: Optional[str] =
                            Header(None, alias="Authorization")) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Não autenticado")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGO])
    except jwt.PyJWTError as e:
        raise HTTPException(401, safe_detail(401, e, "Token inválido:"))
    if payload.get("type") != "security_portal":
        raise HTTPException(403, "Token não é do portal")
    return payload


def _portal_tenant_q(u: dict) -> dict:
    return {"company_id": u["company_id"],
            "security_tenant_id": u["security_tenant_id"]}


@portal_router.post("/auth/login")
async def portal_login(payload: PortalLoginIn):
    user = await db.security_portal_users.find_one(
        {"email": payload.email.lower().strip(), "active": True},
        {"_id": 0})
    if not user or not verify_password(payload.password,
                                          user.get("password_hash", "")):
        raise HTTPException(401, "E-mail ou senha inválidos")
    tenant = await db.security_tenants.find_one(
        {"id": user["security_tenant_id"]}, {"_id": 0})
    token = _issue_portal_token(user)
    return {"access_token": token, "token_type": "bearer",
             "user": {"id": user["id"], "email": user["email"],
                       "name": user.get("name", "")},
             "tenant": tenant}


@portal_router.get("/me")
async def portal_me(u: dict = Depends(get_portal_user)):
    tenant = await db.security_tenants.find_one(
        {"id": u["security_tenant_id"]}, {"_id": 0})
    return {"user": {"id": u["sub"], "email": u["email"],
                      "name": u.get("name", "")}, "tenant": tenant}


@portal_router.get("/sites")
async def portal_sites(u: dict = Depends(get_portal_user)):
    cur = db.security_sites.find(_portal_tenant_q(u), {"_id": 0})
    return await cur.to_list(500)


@portal_router.get("/sites/{sid}/sensors")
async def portal_sensors(sid: str, u: dict = Depends(get_portal_user)):
    site = await db.security_sites.find_one(
        {"id": sid, **_portal_tenant_q(u)}, {"_id": 0, "id": 1})
    if not site:
        raise HTTPException(404)
    cur = db.security_sensors.find({"site_id": sid}, {"_id": 0})
    return await cur.to_list(2000)


@portal_router.post("/sites/{sid}/arm")
async def portal_arm(sid: str, mode: Literal["away", "stay"] = "away",
                       u: dict = Depends(get_portal_user)):
    site = await db.security_sites.find_one(
        {"id": sid, **_portal_tenant_q(u)}, {"_id": 0})
    if not site:
        raise HTTPException(404)
    return await _change_arm_state(sid, f"armed_{mode}",
                                      source="portal",
                                      actor_id=u["sub"],
                                      actor_email=u["email"])


@portal_router.post("/sites/{sid}/disarm")
async def portal_disarm(sid: str, u: dict = Depends(get_portal_user)):
    site = await db.security_sites.find_one(
        {"id": sid, **_portal_tenant_q(u)}, {"_id": 0})
    if not site:
        raise HTTPException(404)
    return await _change_arm_state(sid, "disarmed",
                                      source="portal",
                                      actor_id=u["sub"],
                                      actor_email=u["email"])


@portal_router.post("/sites/{sid}/panic")
async def portal_panic(sid: str, u: dict = Depends(get_portal_user)):
    site = await db.security_sites.find_one(
        {"id": sid, **_portal_tenant_q(u)}, {"_id": 0})
    if not site:
        raise HTTPException(404)
    alarm = {
        "id": f"alm-{uuid.uuid4().hex[:14]}",
        "site_id": sid, "company_id": site["company_id"],
        "security_tenant_id": site.get("security_tenant_id"),
        "kind": "panic", "severity": "critical",
        "label": "🆘 PÂNICO acionado pelo cliente (portal)",
        "event_code": 120,
        "sensor_id": None, "is_restore": False,
        "ts": _now_iso(), "received_at": _now_iso(),
        "acked": False, "origin": "portal",
        "portal_user_email": u["email"], "portal_user_id": u["sub"],
    }
    await db.security_alarms.insert_one(alarm)
    logger.warning("[security-portal] PANIC by %s site=%s",
                    u["email"], sid)
    return {"ok": True, "alarm_id": alarm["id"]}


@portal_router.get("/alarms")
async def portal_alarms(u: dict = Depends(get_portal_user)):
    site_ids = [s["id"] async for s in db.security_sites.find(
        _portal_tenant_q(u), {"_id": 0, "id": 1})]
    if not site_ids:
        return []
    cur = db.security_alarms.find(
        {"site_id": {"$in": site_ids}}, {"_id": 0},
    ).sort("ts", -1).limit(200)
    return await cur.to_list(200)


# ─── Admin: criar usuários do portal de segurança ────────────────
@router.post("/tenants/{tid}/portal-users")
async def create_portal_user(tid: str, payload: PortalUserIn,
                              user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = _cid(user)
    tenant = await db.security_tenants.find_one({"id": tid, "company_id": cid})
    if not tenant:
        raise HTTPException(404)
    email = payload.email.lower().strip()
    if await db.security_portal_users.find_one({"email": email}):
        raise HTTPException(409, "E-mail já cadastrado")
    uid = f"spu-{uuid.uuid4().hex[:12]}"
    doc = {
        "id": uid, "email": email, "name": payload.name.strip(),
        "password_hash": hash_password(payload.password),
        "company_id": cid, "security_tenant_id": tid,
        "active": True, "created_at": _now_iso(),
        "created_by": user.get("id"),
    }
    await db.security_portal_users.insert_one(doc)
    return {"id": uid, "email": email, "name": doc["name"]}


@router.get("/tenants/{tid}/portal-users")
async def list_portal_users(tid: str,
                              user: dict = Depends(get_current_user)):
    _require_manager(user)
    cur = db.security_portal_users.find(
        {"security_tenant_id": tid, "company_id": _cid(user)},
        {"_id": 0, "password_hash": 0},
    ).sort("created_at", -1)
    return await cur.to_list(500)


@router.delete("/portal-users/{uid}")
async def delete_portal_user(uid: str,
                              user: dict = Depends(get_current_user)):
    _require_manager(user)
    r = await db.security_portal_users.delete_one(
        {"id": uid, "company_id": _cid(user)})
    if r.deleted_count == 0:
        raise HTTPException(404)
    return {"ok": True}
