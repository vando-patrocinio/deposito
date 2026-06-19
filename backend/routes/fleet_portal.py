"""
fleet_portal.py — Portal white-label do cliente final (Fase 2 iter212a)

Cada cliente revenda (registrado em `fleet_tenants`) pode criar usuários
isolados que veem apenas SEUS veículos via uma URL pública: `/fleet-portal`.

Diferente do app principal:
  • Login dedicado por e-mail/senha do PORTAL (collection `fleet_portal_users`)
  • JWT contém `fleet_tenant_id` (não tem `company_id` operacional)
  • Read-only: ver veículos, mapa real-time, histórico, cercas. SEM comandos.

Coleção:
  fleet_portal_users:
    {id, email (unique), password_hash, name, company_id, fleet_tenant_id,
     created_at, active}

Endpoints (todos sob /api/fleet-portal):
  POST /auth/login            → {access_token, tenant}
  GET  /me                    → user info do portal
  GET  /vehicles              → veículos do tenant
  GET  /positions/live        → última posição
  GET  /positions/{vid}/history
  GET  /events
  GET  /geofences
  GET  /reports/summary

Admin (do SmartProv) cria/gerencia usuários do portal via:
  POST /api/fleet-tracking/tenants/{tid}/portal-users   (cria)
  GET  /api/fleet-tracking/tenants/{tid}/portal-users   (lista)
  DEL  /api/fleet-tracking/portal-users/{uid}            (remove)
"""
from __future__ import annotations


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
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Literal

import jwt
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, EmailStr

from auth import hash_password, verify_password, _jwt_secret
from core import get_current_user
from database import db

logger = logging.getLogger("ponto.fleet_portal")
router = APIRouter(prefix="/api/fleet-portal", tags=["fleet-portal"])

JWT_ALGO = "HS256"
TOKEN_TTL_DAYS = 30


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _issue_portal_token(user: dict) -> str:
    payload = {
        "sub": user["id"],
        "email": user["email"],
        "name": user.get("name", ""),
        "company_id": user["company_id"],
        "fleet_tenant_id": user["fleet_tenant_id"],
        "type": "fleet_portal",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc)
                     + timedelta(days=TOKEN_TTL_DAYS)).timestamp()),
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
    if payload.get("type") != "fleet_portal":
        raise HTTPException(403, "Token não é do portal")
    return payload


# ───────────────────────────────────────────────────────────────────────
# Models
# ───────────────────────────────────────────────────────────────────────
class LoginIn(BaseModel):
    email: EmailStr
    password: str


class PortalUserIn(BaseModel):
    email: EmailStr
    password: str
    name: str = ""


class PortalCommandIn(BaseModel):
    kind: Literal["block", "unblock", "locate_now"] = "block"
    reason: Optional[str] = None


# ───────────────────────────────────────────────────────────────────────
# Login
# ───────────────────────────────────────────────────────────────────────
@router.post("/auth/login")
async def portal_login(payload: LoginIn):
    user = await db.fleet_portal_users.find_one(
        {"email": payload.email.lower().strip(), "active": True},
        {"_id": 0})
    if not user or not verify_password(payload.password,
                                          user.get("password_hash", "")):
        raise HTTPException(401, "E-mail ou senha inválidos")
    tenant = await db.fleet_tenants.find_one(
        {"id": user["fleet_tenant_id"]}, {"_id": 0})
    token = _issue_portal_token(user)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user["id"], "email": user["email"],
                  "name": user.get("name", "")},
        "tenant": tenant,
    }


@router.get("/me")
async def portal_me(u: dict = Depends(get_portal_user)):
    tenant = await db.fleet_tenants.find_one(
        {"id": u["fleet_tenant_id"]}, {"_id": 0})
    return {"user": {"id": u["sub"], "email": u["email"],
                       "name": u.get("name", "")},
             "tenant": tenant}


# ───────────────────────────────────────────────────────────────────────
# Read-only endpoints (espelham fleet-tracking, mas com filtro por tenant)
# ───────────────────────────────────────────────────────────────────────
def _tenant_q(u: dict) -> dict:
    return {"company_id": u["company_id"],
            "fleet_tenant_id": u["fleet_tenant_id"]}


@router.get("/vehicles")
async def vehicles(u: dict = Depends(get_portal_user)):
    cur = db.fleet_vehicles_tracking.find(_tenant_q(u), {"_id": 0}) \
        .sort("placa", 1)
    return await cur.to_list(2000)


@router.get("/positions/live")
async def positions_live(u: dict = Depends(get_portal_user)):
    cur = db.fleet_vehicles_tracking.find(
        _tenant_q(u),
        {"_id": 0, "id": 1, "placa": 1, "modelo": 1, "marca": 1,
         "cor": 1, "last_position": 1, "last_seen_at": 1, "active": 1},
    )
    items = await cur.to_list(2000)
    now = datetime.now(timezone.utc)
    out = []
    for v in items:
        lp = v.get("last_position")
        last_seen = v.get("last_seen_at")
        online = False
        if last_seen:
            try:
                dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                online = (now - dt).total_seconds() < 300
            except Exception:
                pass
        out.append({**v, "online": online,
                     "lat": lp.get("lat") if lp else None,
                     "lng": lp.get("lng") if lp else None,
                     "speed_kmh": lp.get("speed_kmh") if lp else None,
                     "heading": lp.get("heading") if lp else None,
                     "ignition": lp.get("ignition") if lp else None,
                     "ts": lp.get("ts") if lp else None})
    return out


@router.get("/positions/{vid}/history")
async def history(vid: str, from_ts: str = "", to_ts: str = "",
                   limit: int = 5000,
                   u: dict = Depends(get_portal_user)):
    veh = await db.fleet_vehicles_tracking.find_one(
        {"id": vid, **_tenant_q(u)}, {"_id": 0, "id": 1})
    if not veh:
        raise HTTPException(404, "Veículo não encontrado")
    q: dict = {"vehicle_id": vid}
    if from_ts or to_ts:
        q["ts"] = {}
        if from_ts:
            q["ts"]["$gte"] = from_ts
        if to_ts:
            q["ts"]["$lte"] = to_ts
    cur = db.fleet_positions.find(
        q, {"_id": 0, "lat": 1, "lng": 1, "speed_kmh": 1,
            "heading": 1, "ts": 1},
    ).sort("ts", 1).limit(limit)
    return {"points": await cur.to_list(limit)}


@router.get("/events")
async def events(u: dict = Depends(get_portal_user)):
    # Eventos de veículos do tenant
    veh_ids = [v["id"] async for v in db.fleet_vehicles_tracking.find(
        _tenant_q(u), {"_id": 0, "id": 1})]
    if not veh_ids:
        return []
    cur = db.fleet_events.find(
        {"vehicle_id": {"$in": veh_ids}}, {"_id": 0},
    ).sort("ts", -1).limit(200)
    return await cur.to_list(200)


# ───────────────────────────────────────────────────────────────────────
# COMANDOS (cliente final aciona block/unblock direto — modelo B simples)
# ───────────────────────────────────────────────────────────────────────
@router.post("/vehicles/{vid}/command")
async def portal_send_command(vid: str, payload: PortalCommandIn,
                                u: dict = Depends(get_portal_user)):
    """Cliente final envia comando ao seu próprio veículo.

    Só permite block/unblock/locate_now (sem audio_listen, set_speed, reset).
    Registra origin='portal' + portal_user_id pra auditoria."""
    veh = await db.fleet_vehicles_tracking.find_one(
        {"id": vid, **_tenant_q(u)}, {"_id": 0})
    if not veh:
        raise HTTPException(404, "Veículo não encontrado")
    cmd = {
        "id": f"cmd-{uuid.uuid4().hex[:14]}",
        "company_id": veh["company_id"], "vehicle_id": vid,
        "imei": veh["imei"],
        "tracker_password": veh.get("tracker_password", "123456"),
        "kind": payload.kind,
        "payload": {"reason": payload.reason} if payload.reason else {},
        "status": "pending",
        "origin": "portal",
        "portal_user_id": u["sub"],
        "portal_user_email": u["email"],
        "created_at": _now_iso(),
    }
    await db.fleet_commands.insert_one(cmd)
    cmd.pop("_id", None)
    return {"id": cmd["id"], "kind": cmd["kind"], "status": "pending"}


@router.get("/vehicles/{vid}/commands")
async def portal_list_commands(vid: str,
                                 u: dict = Depends(get_portal_user)):
    veh = await db.fleet_vehicles_tracking.find_one(
        {"id": vid, **_tenant_q(u)}, {"_id": 0, "id": 1})
    if not veh:
        raise HTTPException(404)
    cur = db.fleet_commands.find(
        {"vehicle_id": vid}, {"_id": 0},
    ).sort("created_at", -1).limit(50)
    return await cur.to_list(50)


# ───────────────────────────────────────────────────────────────────────
# Admin: criar usuários do portal (a partir do app principal)
# Esses endpoints ficam SOB /api/fleet-tracking/ porque exigem auth normal.
# ───────────────────────────────────────────────────────────────────────
admin_router = APIRouter(prefix="/api/fleet-tracking",
                           tags=["fleet-tracking-portal-admin"])


def _require_manager(user: dict):
    from core import is_super_admin
    role = (user.get("role") or "").lower()
    roles = user.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    if not (is_super_admin(user)
            or role in ("gestor", "administrador", "admin")
            or any(r in {"gestor", "admin"} for r in roles)):
        raise HTTPException(403, "Apenas gestor/admin.")


@admin_router.post("/tenants/{tid}/portal-users")
async def create_portal_user(tid: str, payload: PortalUserIn,
                              user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = user.get("company_id") or "co-demo"
    tenant = await db.fleet_tenants.find_one({"id": tid, "company_id": cid})
    if not tenant:
        raise HTTPException(404, "Cliente (tenant) não encontrado")
    email = payload.email.lower().strip()
    if await db.fleet_portal_users.find_one({"email": email}):
        raise HTTPException(409, "E-mail já cadastrado")
    uid = f"fpu-{uuid.uuid4().hex[:12]}"
    doc = {
        "id": uid, "email": email, "name": payload.name.strip(),
        "password_hash": hash_password(payload.password),
        "company_id": cid, "fleet_tenant_id": tid,
        "active": True, "created_at": _now_iso(),
        "created_by": user.get("id"),
    }
    await db.fleet_portal_users.insert_one(doc)
    return {"id": uid, "email": email, "name": doc["name"]}


@admin_router.get("/tenants/{tid}/portal-users")
async def list_portal_users(tid: str,
                              user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = user.get("company_id") or "co-demo"
    cur = db.fleet_portal_users.find(
        {"fleet_tenant_id": tid, "company_id": cid},
        {"_id": 0, "password_hash": 0},
    ).sort("created_at", -1)
    return await cur.to_list(500)


@admin_router.delete("/portal-users/{uid}")
async def delete_portal_user(uid: str,
                              user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = user.get("company_id") or "co-demo"
    r = await db.fleet_portal_users.delete_one(
        {"id": uid, "company_id": cid})
    if r.deleted_count == 0:
        raise HTTPException(404)
    return {"ok": True}


async def ensure_indexes() -> None:
    try:
        await db.fleet_portal_users.create_index("email", unique=True)
    except Exception as e:
        logger.warning("[fleet-portal] ensure_indexes falhou: %s", e)
