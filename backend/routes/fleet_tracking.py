"""
fleet_tracking.py — Rastreamento veicular em tempo real (Fleet Phase 1 MVP)

Arquitetura:
  [TK103 tracker no carro] ──TCP──▶ [Gateway TCP em VPS pública]
                                       │
                                       │ HTTPS POST + shared token
                                       ▼
                                  [/api/fleet-tracking/ingest]
                                       │
                                       ▼
                                  MongoDB (fleet_positions)
                                       ▲
                                       │ polling 5s
                                  Frontend Leaflet map

Multi-tenant:
  • company_id     → SaaS owner (a operadora ISP que usa o SmartProv)
  • fleet_tenant_id → cliente final que está revendido (NULL = frota própria)
  Cada usuário só vê os veículos do company_id dele, e clientes white-label
  só veem fleet_tenant_id = ao seu.

Collections:
  fleet_vehicles_tracking — placa, imei, modelo, fleet_tenant_id, driver_collab_id
  fleet_positions          — histórico (lat,lng,speed,heading,ts,imei,ignition,…)
  fleet_geofences          — polígonos/círculos (alerta entra/sai)
  fleet_commands           — fila p/ gateway enviar ao tracker
  fleet_events             — alarmes (geofence,speed,panic,low_batt,sos)
  fleet_tenants            — clientes white-label (revenda)

Endpoints públicos (ingest do gateway):
  POST /api/fleet-tracking/ingest      → recebe posição
  GET  /api/fleet-tracking/commands/{imei} → gateway puxa comandos pendentes
  POST /api/fleet-tracking/commands/{id}/ack → gateway confirma

Endpoints autenticados:
  CRUD /api/fleet-tracking/vehicles
  GET  /api/fleet-tracking/positions/live    — última posição de cada veículo
  GET  /api/fleet-tracking/positions/{vid}/history?from=&to=
  CRUD /api/fleet-tracking/geofences
  CRUD /api/fleet-tracking/tenants
  POST /api/fleet-tracking/vehicles/{vid}/command (block/unblock/audio/locate)
  GET  /api/fleet-tracking/events
  GET  /api/fleet-tracking/reports/summary
"""
from __future__ import annotations

import logging
import math
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, List, Literal

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, get_current_user, is_super_admin
from database import db

logger = logging.getLogger("ponto.fleet_tracking")
router = APIRouter(prefix="/api/fleet-tracking", tags=["fleet-tracking"])

# Token compartilhado entre o Gateway TCP e o backend.
# Definido em backend/.env como FLEET_INGEST_TOKEN. Gateway envia
# Authorization: Bearer <token>.
INGEST_TOKEN = os.environ.get("FLEET_INGEST_TOKEN", "")


# ───────────────────────────────────────────────────────────────────────
# Bootstrap (índices)
# ───────────────────────────────────────────────────────────────────────
async def ensure_indexes() -> None:
    """Cria índices necessários — chamado no startup do server."""
    try:
        # TTL: posições órfãs expiram em 30 dias
        await db.fleet_orphan_positions.create_index(
            "received_at_dt", expireAfterSeconds=30 * 24 * 3600)
        # Histórico de posições: índice por veículo + ts (consultas history)
        await db.fleet_positions.create_index([("vehicle_id", 1), ("ts", -1)])
        # IMEI único nos veículos rastreados
        await db.fleet_vehicles_tracking.create_index(
            "imei", unique=True, sparse=True)
        # Events por empresa + ts
        await db.fleet_events.create_index([("company_id", 1), ("ts", -1)])
        logger.info("[fleet-tracking] indexes ensured")
    except Exception as e:
        logger.warning("[fleet-tracking] ensure_indexes falhou: %s", e)


# ───────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────
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
    ok = (is_super_admin(user)
          or role in ("gestor", "administrador", "admin", "super_admin")
          or any(r in {"gestor", "admin", "super_admin", "gestor_frota"}
                  for r in roles))
    if not ok:
        raise HTTPException(403, "Apenas gestor/admin.")


def _fleet_tenant_filter(user: dict) -> dict:
    """Se usuário tem fleet_tenant_id atribuído, só vê veículos do tenant dele.
    Caso contrário (gestor/admin SaaS), vê todos do company_id."""
    cid = _cid(user)
    base = {"company_id": cid}
    user_tenant = user.get("fleet_tenant_id")
    if user_tenant:
        base["fleet_tenant_id"] = user_tenant
    return base


def _haversine_m(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    R = 6371000.0
    la1, lo1 = math.radians(a_lat), math.radians(a_lng)
    la2, lo2 = math.radians(b_lat), math.radians(b_lng)
    dla = la2 - la1
    dlo = lo2 - lo1
    a = (math.sin(dla / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def _point_in_polygon(lat: float, lng: float, polygon: list) -> bool:
    """Ray casting. polygon = [[lat,lng], …]."""
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        yi, xi = polygon[i][0], polygon[i][1]
        yj, xj = polygon[j][0], polygon[j][1]
        if ((yi > lat) != (yj > lat)) and \
            (lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


# ───────────────────────────────────────────────────────────────────────
# Models
# ───────────────────────────────────────────────────────────────────────
class VehicleIn(BaseModel):
    placa: str = Field(..., min_length=4, max_length=10)
    imei: str = Field(..., min_length=10, max_length=20)  # IMEI do rastreador
    tracker_model: str = "TK103"
    tracker_password: str = "123456"           # Senha p/ enviar comandos
    sim_phone: Optional[str] = None             # p/ SMS fallback
    modelo: Optional[str] = None
    marca: Optional[str] = None
    cor: Optional[str] = None
    ano: Optional[int] = None
    driver_collaborator_id: Optional[str] = None  # link com colaboradores
    fleet_tenant_id: Optional[str] = None        # cliente white-label
    speed_limit_kmh: int = 80                     # alerta acima disso
    notes: Optional[str] = None
    active: bool = True


class PositionIn(BaseModel):
    """Payload que o Gateway TCP envia para o backend."""
    imei: str
    lat: float
    lng: float
    speed_kmh: float = 0.0
    heading: float = 0.0
    altitude: float = 0.0
    ignition: Optional[bool] = None  # ACC on/off
    fix_valid: bool = True            # True se GPS pegou satélites
    sats: int = 0
    battery_pct: Optional[float] = None
    timestamp: Optional[str] = None   # ISO; default = agora
    raw: Optional[str] = None          # frame original (debug)


class GeofenceIn(BaseModel):
    name: str
    kind: Literal["circle", "polygon"] = "circle"
    center_lat: Optional[float] = None     # circle
    center_lng: Optional[float] = None
    radius_m: Optional[float] = None       # circle
    polygon: Optional[List[List[float]]] = None  # polygon: [[lat,lng],…]
    vehicle_ids: List[str] = []             # vazio = todos do tenant
    fleet_tenant_id: Optional[str] = None
    alert_on: Literal["entry", "exit", "both"] = "both"
    active: bool = True


class TenantIn(BaseModel):
    name: str
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    monthly_fee: float = 0.0


class CommandIn(BaseModel):
    kind: Literal["block", "unblock", "locate_now", "audio_listen",
                  "set_speed_limit", "reset"] = "locate_now"
    payload: Optional[dict] = None


# ───────────────────────────────────────────────────────────────────────
# INGEST (chamado pelo Gateway TCP)
# ───────────────────────────────────────────────────────────────────────
def _check_ingest_token(authorization: Optional[str]):
    if not INGEST_TOKEN:
        # Em desenvolvimento, permite sem token. Em prod sempre exige.
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Token ausente")
    if authorization.split(" ", 1)[1].strip() != INGEST_TOKEN:
        raise HTTPException(401, "Token inválido")


@router.post("/ingest")
async def ingest_position(
    pos: PositionIn,
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """Recebe posição vinda do Gateway TCP.
    Identifica veículo pelo IMEI (busca em qualquer company_id)."""
    _check_ingest_token(authorization)

    veh = await db.fleet_vehicles_tracking.find_one(
        {"imei": pos.imei}, {"_id": 0})
    if not veh:
        # IMEI desconhecido — registra órfão pra gestor poder vincular depois
        now = datetime.now(timezone.utc)
        await db.fleet_orphan_positions.insert_one({
            "imei": pos.imei, "lat": pos.lat, "lng": pos.lng,
            "speed_kmh": pos.speed_kmh, "ts": pos.timestamp or _now_iso(),
            "received_at": now.isoformat(),
            "received_at_dt": now,  # usado pelo TTL index (30d)
        })
        return {"ok": False, "reason": "imei-not-registered",
                "hint": "Cadastre o IMEI em fleet_vehicles_tracking"}

    ts = pos.timestamp or _now_iso()
    doc = {
        "id": f"pos-{uuid.uuid4().hex[:14]}",
        "vehicle_id": veh["id"],
        "company_id": veh["company_id"],
        "fleet_tenant_id": veh.get("fleet_tenant_id"),
        "imei": pos.imei,
        "lat": pos.lat, "lng": pos.lng,
        "speed_kmh": pos.speed_kmh, "heading": pos.heading,
        "altitude": pos.altitude,
        "ignition": pos.ignition, "fix_valid": pos.fix_valid,
        "sats": pos.sats, "battery_pct": pos.battery_pct,
        "ts": ts, "received_at": _now_iso(),
    }
    await db.fleet_positions.insert_one(doc)

    # Atualiza última posição no veículo (snapshot pra listagens rápidas)
    await db.fleet_vehicles_tracking.update_one(
        {"id": veh["id"]},
        {"$set": {
            "last_position": {
                "lat": pos.lat, "lng": pos.lng,
                "speed_kmh": pos.speed_kmh, "heading": pos.heading,
                "ignition": pos.ignition, "ts": ts,
            },
            "last_seen_at": _now_iso(),
        }},
    )

    # Avalia alertas (speed, geofence)
    await _evaluate_alerts(veh, doc)

    return {"ok": True, "vehicle_id": veh["id"]}


async def _evaluate_alerts(veh: dict, pos: dict):
    """Gera eventos quando: velocidade > limite OU dentro/fora de geofence."""
    cid = veh["company_id"]
    vid = veh["id"]

    # Speed alert
    limit = float(veh.get("speed_limit_kmh") or 80)
    if pos["speed_kmh"] > limit:
        await _emit_event(cid, vid, "speed", {
            "speed_kmh": pos["speed_kmh"], "limit_kmh": limit,
            "lat": pos["lat"], "lng": pos["lng"],
        })

    # Geofence
    fences = db.fleet_geofences.find({
        "company_id": cid, "active": True,
        "$or": [
            {"vehicle_ids": vid},
            {"vehicle_ids": []},  # vazio = todos
        ],
    })
    async for f in fences:
        inside = False
        if f.get("kind") == "circle":
            d = _haversine_m(pos["lat"], pos["lng"],
                             f["center_lat"], f["center_lng"])
            inside = d <= float(f["radius_m"])
        elif f.get("kind") == "polygon" and f.get("polygon"):
            inside = _point_in_polygon(pos["lat"], pos["lng"], f["polygon"])

        # Carrega estado anterior (in/out) por veículo+geofence
        state_key = f"{vid}:{f['id']}"
        prev = await db.fleet_geofence_state.find_one({"key": state_key},
                                                       {"_id": 0})
        prev_inside = prev.get("inside") if prev else None

        if prev_inside is None:
            # primeira observação — só persiste sem emitir
            await db.fleet_geofence_state.update_one(
                {"key": state_key},
                {"$set": {"key": state_key, "inside": inside,
                          "updated_at": _now_iso()}},
                upsert=True,
            )
            continue
        if prev_inside == inside:
            continue
        # Transição!
        event_kind = "geofence_entry" if inside else "geofence_exit"
        alert_on = f.get("alert_on", "both")
        if alert_on == "both" or (alert_on == "entry" and inside) \
           or (alert_on == "exit" and not inside):
            await _emit_event(cid, vid, event_kind, {
                "geofence_id": f["id"], "geofence_name": f.get("name"),
                "lat": pos["lat"], "lng": pos["lng"],
            })
        await db.fleet_geofence_state.update_one(
            {"key": state_key},
            {"$set": {"inside": inside, "updated_at": _now_iso()}},
        )


async def _emit_event(cid: str, vid: str, kind: str, payload: dict):
    ev = {
        "id": f"ev-{uuid.uuid4().hex[:14]}",
        "company_id": cid, "vehicle_id": vid,
        "kind": kind, "payload": payload,
        "ts": _now_iso(), "acked": False,
    }
    await db.fleet_events.insert_one(ev)
    logger.info("[fleet-tracking] event %s for %s: %s", kind, vid, payload)


@router.get("/commands/{imei}")
async def gateway_pull_commands(
    imei: str,
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """Gateway TCP puxa comandos pendentes para um IMEI."""
    _check_ingest_token(authorization)
    cur = db.fleet_commands.find(
        {"imei": imei, "status": "pending"},
        {"_id": 0, "id": 1, "kind": 1, "payload": 1, "tracker_password": 1},
    ).sort("created_at", 1).limit(10)
    return await cur.to_list(10)


@router.post("/commands/{cmd_id}/ack")
async def gateway_ack_command(
    cmd_id: str,
    result: dict,
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """Gateway confirma execução do comando (sucesso ou falha)."""
    _check_ingest_token(authorization)
    await db.fleet_commands.update_one(
        {"id": cmd_id},
        {"$set": {
            "status": "ack" if result.get("ok") else "failed",
            "result": result, "acked_at": _now_iso(),
        }},
    )
    return {"ok": True}


# ───────────────────────────────────────────────────────────────────────
# CRUD Veículos (autenticado)
# ───────────────────────────────────────────────────────────────────────
@router.get("/vehicles")
async def list_vehicles(user: dict = Depends(get_current_user)):
    cur = db.fleet_vehicles_tracking.find(_fleet_tenant_filter(user),
                                          {"_id": 0}).sort("placa", 1)
    return await cur.to_list(2000)


# iter233 — Wizard "GPS plug-and-play"
@router.get("/gateway-info")
async def gateway_info(user: dict = Depends(get_current_user)):
    """Devolve host/porta do Gateway TCP para o wizard gerar o SMS
    de configuração do GPS (APN, server, porta, interval) já pronto."""
    import os
    host = (os.environ.get("FLEET_GATEWAY_HOST")
              or os.environ.get("INGEST_PUBLIC_HOST")
              or "gps.ligo.system")
    port = int(os.environ.get("FLEET_GATEWAY_PORT")
                or os.environ.get("INGEST_PORT") or 5023)
    return {"host": host, "port": port}


@router.get("/vehicles/{vid}/last-ping")
async def vehicle_last_ping(vid: str,
                             user: dict = Depends(get_current_user)):
    """Wizard usa em polling pra detectar quando o GPS conecta. Retorna
    o `last_position` se houver, OU `false` se ainda não chegou nenhum
    ping. Também conta posições órfãs do mesmo IMEI (se o usuário errou
    o IMEI no cadastro)."""
    cid = _cid(user)
    veh = await db.fleet_vehicles_tracking.find_one(
        {"id": vid, "company_id": cid},
        {"_id": 0, "imei": 1, "last_position": 1, "last_seen_at": 1})
    if not veh:
        raise HTTPException(404, "Veículo não encontrado")
    orphan = await db.fleet_orphan_positions.count_documents(
        {"imei": veh["imei"]})
    return {
        "connected": bool(veh.get("last_position")),
        "last_position": veh.get("last_position"),
        "last_seen_at": veh.get("last_seen_at"),
        "orphan_pings_same_imei": orphan,
    }


@router.post("/vehicles")
async def create_vehicle(payload: VehicleIn,
                          user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = _cid(user)
    # Garante IMEI único globalmente
    dup = await db.fleet_vehicles_tracking.find_one({"imei": payload.imei},
                                                     {"_id": 0, "id": 1})
    if dup:
        raise HTTPException(409, f"IMEI {payload.imei} já cadastrado")
    vid = f"fv-{uuid.uuid4().hex[:12]}"
    doc = payload.model_dump()
    doc.update({
        "id": vid, "company_id": cid,
        "created_at": _now_iso(), "created_by": user.get("id"),
        "last_position": None, "last_seen_at": None,
    })
    await db.fleet_vehicles_tracking.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/vehicles/{vid}")
async def update_vehicle(vid: str, payload: VehicleIn,
                          user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = _cid(user)
    upd = payload.model_dump(exclude_unset=True)
    upd["updated_at"] = _now_iso()
    r = await db.fleet_vehicles_tracking.update_one(
        {"id": vid, "company_id": cid}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(404, "Veículo não encontrado")
    return {"ok": True}


@router.delete("/vehicles/{vid}")
async def delete_vehicle(vid: str, user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = _cid(user)
    r = await db.fleet_vehicles_tracking.delete_one(
        {"id": vid, "company_id": cid})
    if r.deleted_count == 0:
        raise HTTPException(404, "Veículo não encontrado")
    return {"ok": True}


# ───────────────────────────────────────────────────────────────────────
# Posições / Live + Histórico
# ───────────────────────────────────────────────────────────────────────
@router.get("/positions/live")
async def live_positions(user: dict = Depends(get_current_user)):
    """Última posição de cada veículo. Frontend faz polling 5s."""
    cur = db.fleet_vehicles_tracking.find(
        _fleet_tenant_filter(user),
        {"_id": 0, "id": 1, "placa": 1, "modelo": 1, "marca": 1,
         "cor": 1, "tracker_model": 1, "last_position": 1, "last_seen_at": 1,
         "driver_collaborator_id": 1, "fleet_tenant_id": 1,
         "speed_limit_kmh": 1, "active": 1},
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
                online = (now - dt).total_seconds() < 300  # 5min
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
async def position_history(
    vid: str,
    from_ts: Optional[str] = Query(None, alias="from"),
    to_ts: Optional[str] = Query(None, alias="to"),
    limit: int = 5000,
    user: dict = Depends(get_current_user),
):
    # Garante tenant isolation
    veh = await db.fleet_vehicles_tracking.find_one(
        {"id": vid, **_fleet_tenant_filter(user)}, {"_id": 0, "id": 1})
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
        q, {"_id": 0, "lat": 1, "lng": 1, "speed_kmh": 1, "heading": 1,
            "ignition": 1, "ts": 1},
    ).sort("ts", 1).limit(limit)
    points = await cur.to_list(limit)

    # Calcula KM total + duração + paradas
    total_km = 0.0
    moving_seconds = 0.0
    stops = 0
    if len(points) >= 2:
        for i in range(1, len(points)):
            d = _haversine_m(points[i - 1]["lat"], points[i - 1]["lng"],
                             points[i]["lat"], points[i]["lng"])
            total_km += d / 1000.0
            try:
                t1 = datetime.fromisoformat(
                    points[i - 1]["ts"].replace("Z", "+00:00"))
                t2 = datetime.fromisoformat(
                    points[i]["ts"].replace("Z", "+00:00"))
                ds = (t2 - t1).total_seconds()
                if points[i]["speed_kmh"] > 3 and ds < 600:
                    moving_seconds += ds
                elif points[i]["speed_kmh"] <= 3 and ds > 120:
                    stops += 1
            except Exception:
                pass

    return {
        "vehicle_id": vid,
        "points": points,
        "stats": {
            "total_points": len(points),
            "total_km": round(total_km, 2),
            "moving_minutes": round(moving_seconds / 60, 1),
            "stops": stops,
        },
    }


# ───────────────────────────────────────────────────────────────────────
# Geofences
# ───────────────────────────────────────────────────────────────────────
@router.get("/geofences")
async def list_geofences(user: dict = Depends(get_current_user)):
    cur = db.fleet_geofences.find(_fleet_tenant_filter(user), {"_id": 0})
    return await cur.to_list(500)


@router.post("/geofences")
async def create_geofence(payload: GeofenceIn,
                           user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = _cid(user)
    if payload.kind == "circle" and (payload.center_lat is None
                                       or payload.center_lng is None
                                       or not payload.radius_m):
        raise HTTPException(400, "Círculo exige center_lat, center_lng e radius_m")
    if payload.kind == "polygon" and (not payload.polygon
                                        or len(payload.polygon) < 3):
        raise HTTPException(400, "Polígono exige no mínimo 3 pontos")
    gid = f"gf-{uuid.uuid4().hex[:12]}"
    doc = payload.model_dump()
    doc.update({"id": gid, "company_id": cid, "created_at": _now_iso()})
    await db.fleet_geofences.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/geofences/{gid}")
async def delete_geofence(gid: str, user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = _cid(user)
    r = await db.fleet_geofences.delete_one({"id": gid, "company_id": cid})
    if r.deleted_count == 0:
        raise HTTPException(404, "Geofence não encontrada")
    return {"ok": True}


# ───────────────────────────────────────────────────────────────────────
# Commands (block, audio, etc.)
# ───────────────────────────────────────────────────────────────────────
@router.post("/vehicles/{vid}/command")
async def send_command(vid: str, payload: CommandIn,
                        user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = _cid(user)
    veh = await db.fleet_vehicles_tracking.find_one(
        {"id": vid, "company_id": cid}, {"_id": 0})
    if not veh:
        raise HTTPException(404, "Veículo não encontrado")
    cmd = {
        "id": f"cmd-{uuid.uuid4().hex[:14]}",
        "company_id": cid, "vehicle_id": vid,
        "imei": veh["imei"], "tracker_password": veh.get("tracker_password", "123456"),
        "kind": payload.kind, "payload": payload.payload or {},
        "status": "pending",
        "created_at": _now_iso(), "created_by": user.get("id"),
    }
    await db.fleet_commands.insert_one(cmd)
    cmd.pop("_id", None)
    return cmd


@router.get("/vehicles/{vid}/commands")
async def list_vehicle_commands(vid: str,
                                  user: dict = Depends(get_current_user)):
    cid = _cid(user)
    cur = db.fleet_commands.find(
        {"vehicle_id": vid, "company_id": cid}, {"_id": 0},
    ).sort("created_at", -1).limit(100)
    return await cur.to_list(100)


# ───────────────────────────────────────────────────────────────────────
# Tenants (white-label)
# ───────────────────────────────────────────────────────────────────────
@router.get("/tenants")
async def list_tenants(user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = _cid(user)
    cur = db.fleet_tenants.find({"company_id": cid}, {"_id": 0})
    return await cur.to_list(500)


@router.post("/tenants")
async def create_tenant(payload: TenantIn,
                         user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = _cid(user)
    tid = f"ft-{uuid.uuid4().hex[:12]}"
    doc = payload.model_dump()
    doc.update({"id": tid, "company_id": cid, "created_at": _now_iso(),
                 "active": True})
    await db.fleet_tenants.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/tenants/{tid}")
async def delete_tenant(tid: str, user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = _cid(user)
    r = await db.fleet_tenants.delete_one({"id": tid, "company_id": cid})
    if r.deleted_count == 0:
        raise HTTPException(404)
    return {"ok": True}


# ───────────────────────────────────────────────────────────────────────
# Events + Reports
# ───────────────────────────────────────────────────────────────────────
@router.get("/events")
async def list_events(
    kind: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    limit: int = 200,
    user: dict = Depends(get_current_user),
):
    cid = _cid(user)
    q: dict = {"company_id": cid}
    if kind:
        q["kind"] = kind
    if vehicle_id:
        q["vehicle_id"] = vehicle_id
    cur = db.fleet_events.find(q, {"_id": 0}).sort("ts", -1).limit(limit)
    return await cur.to_list(limit)


@router.get("/reports/summary")
async def reports_summary(
    days: int = Query(7, ge=1, le=90),
    user: dict = Depends(get_current_user),
):
    """Sumário de cada veículo nos últimos N dias: km, tempo movimento, paradas."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    vehicles = await db.fleet_vehicles_tracking.find(
        _fleet_tenant_filter(user), {"_id": 0, "id": 1, "placa": 1, "modelo": 1},
    ).to_list(2000)

    rows = []
    for v in vehicles:
        cur = db.fleet_positions.find(
            {"vehicle_id": v["id"], "ts": {"$gte": since}},
            {"_id": 0, "lat": 1, "lng": 1, "speed_kmh": 1, "ts": 1},
        ).sort("ts", 1)
        points = await cur.to_list(20000)
        km = 0.0
        moving_s = 0.0
        stops = 0
        for i in range(1, len(points)):
            d = _haversine_m(points[i-1]["lat"], points[i-1]["lng"],
                              points[i]["lat"], points[i]["lng"])
            km += d / 1000
            try:
                t1 = datetime.fromisoformat(points[i-1]["ts"].replace("Z","+00:00"))
                t2 = datetime.fromisoformat(points[i]["ts"].replace("Z","+00:00"))
                ds = (t2 - t1).total_seconds()
                if points[i]["speed_kmh"] > 3 and ds < 600:
                    moving_s += ds
                elif points[i]["speed_kmh"] <= 3 and ds > 120:
                    stops += 1
            except Exception:
                pass
        rows.append({
            "vehicle_id": v["id"], "placa": v["placa"],
            "modelo": v.get("modelo"),
            "km": round(km, 1),
            "moving_hours": round(moving_s / 3600, 1),
            "stops": stops,
            "points": len(points),
        })
    rows.sort(key=lambda r: -r["km"])
    return {"days": days, "rows": rows}
