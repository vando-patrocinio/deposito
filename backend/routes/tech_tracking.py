"""Tracking de GPS dos técnicos no campo (iter157).

Recebe pings de GPS do app mobile e devolve o trajeto do dia para
renderizar como rastro no Mapa da Rede.

Endpoints (todos públicos — uso pelo app `/?cid=col-xxx`):

POST /api/tech-tracking/public/ping/{collab_id}
    body: {lat, lng, accuracy, speed, heading, captured_at?}
    → grava o ping (apenas se accuracy <= 100m).

GET  /api/tech-tracking/public/trail/{collab_id}?date=YYYY-MM-DD
    → retorna lista ordenada de pings do dia + bbox.

GET  /api/tech-tracking/trail/{collab_id}?date=YYYY-MM-DD  (autenticado)
    → idem para o painel do gestor.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from core import get_current_user, now_iso
from database import db

logger = logging.getLogger("ponto.tech_tracking")
router = APIRouter(prefix="/api/tech-tracking", tags=["tech-tracking"])


# Accuracy: descarta amostras ruins. Mobile com GPS chega <20m, WiFi 30-100m,
# Cell tower 500-2000m. 100m é um bom corte para não poluir.
MAX_ACCURACY_M = 100.0
# Distância mínima entre pings para considerar um novo registro (m).
# Evita "engasgo" parado no mesmo lugar enchendo banco. 8m ~= largura de rua.
MIN_DISTANCE_M = 8.0
# Tempo máximo entre pings sem registrar nada (s). Mesmo parado registramos
# 1 ping por minuto pra manter histórico de presença.
HEARTBEAT_S = 60.0


class PingIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy: float = Field(default=0.0, ge=0)
    speed: Optional[float] = None       # m/s (do Geolocation API)
    heading: Optional[float] = None     # graus (0=N, 90=E)
    captured_at: Optional[str] = None   # ISO; default = now


def _haversine_m(a_lat: float, a_lng: float,
                    b_lat: float, b_lng: float) -> float:
    from math import asin, cos, radians, sin, sqrt
    φ1, φ2 = radians(a_lat), radians(b_lat)
    dφ = radians(b_lat - a_lat)
    dλ = radians(b_lng - a_lng)
    a = sin(dφ / 2) ** 2 + cos(φ1) * cos(φ2) * sin(dλ / 2) ** 2
    return 2 * 6371000 * asin(sqrt(a))


async def _resolve_company(collab_id: str) -> Dict[str, Any]:
    coll = await db.collaborators.find_one(
        {"id": collab_id}, {"_id": 0, "company_id": 1, "name": 1},
    )
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    return coll


def _day_range(date_str: Optional[str]) -> tuple[str, str]:
    """Retorna [start_iso, end_iso] do dia (UTC) — default hoje."""
    if date_str:
        try:
            base = datetime.strptime(date_str, "%Y-%m-%d").replace(
                tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(400, "Data inválida (use YYYY-MM-DD)")
    else:
        base = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0)
    start = base.isoformat()
    end = base.replace(hour=23, minute=59, second=59, microsecond=999000)
    return start, end.isoformat()


@router.post("/public/ping/{collab_id}")
async def public_ping(collab_id: str, body: PingIn):
    """Recebe ping de GPS do app mobile do técnico."""
    if body.accuracy and body.accuracy > MAX_ACCURACY_M:
        return {"ok": False, "reason": "accuracy_too_low",
                "accuracy": body.accuracy, "max": MAX_ACCURACY_M}
    coll = await _resolve_company(collab_id)
    cid = coll.get("company_id")
    now_dt = datetime.now(timezone.utc)
    captured_at = body.captured_at or now_dt.isoformat()

    # Verifica o último ping pra evitar pontos muito próximos / repetidos
    last = await db.tech_locations.find_one(
        {"company_id": cid, "collab_id": collab_id},
        sort=[("captured_at", -1)],
        projection={"_id": 0, "lat": 1, "lng": 1, "captured_at": 1},
    )
    if last:
        try:
            dist = _haversine_m(last["lat"], last["lng"], body.lat, body.lng)
            last_dt = datetime.fromisoformat(last["captured_at"])
            dt_s = (now_dt - last_dt).total_seconds()
            # Mesmo lugar e tempo curto → não grava (HEARTBEAT garante 1/min)
            if dist < MIN_DISTANCE_M and dt_s < HEARTBEAT_S:
                return {"ok": True, "skipped": "min_distance",
                        "dist_m": round(dist, 1)}
        except Exception:
            pass

    doc = {
        "company_id": cid,
        "collab_id": collab_id,
        "collab_name": coll.get("name"),
        "lat": body.lat,
        "lng": body.lng,
        "accuracy": body.accuracy or None,
        "speed": body.speed,
        "heading": body.heading,
        "captured_at": captured_at,
        "received_at": now_iso(),
    }
    await db.tech_locations.insert_one(doc)
    return {"ok": True, "saved": True,
            "ts": captured_at}


async def _load_trail(cid: str, collab_id: str, date_str: Optional[str]
                        ) -> Dict[str, Any]:
    start, end = _day_range(date_str)
    pts = await db.tech_locations.find(
        {"company_id": cid, "collab_id": collab_id,
         "captured_at": {"$gte": start, "$lte": end}},
        {"_id": 0, "lat": 1, "lng": 1, "accuracy": 1,
         "speed": 1, "heading": 1, "captured_at": 1},
    ).sort("captured_at", 1).to_list(5000)
    if not pts:
        return {"points": [], "total": 0,
                "bbox": None, "distance_m": 0,
                "first": None, "last": None}
    # Distância total percorrida (Haversine somado)
    total = 0.0
    for i in range(1, len(pts)):
        try:
            total += _haversine_m(pts[i-1]["lat"], pts[i-1]["lng"],
                                       pts[i]["lat"], pts[i]["lng"])
        except Exception:
            pass
    lats = [p["lat"] for p in pts]
    lngs = [p["lng"] for p in pts]
    return {
        "points": pts,
        "total": len(pts),
        "bbox": {"south": min(lats), "west": min(lngs),
                  "north": max(lats), "east": max(lngs)},
        "distance_m": round(total, 1),
        "first": pts[0]["captured_at"],
        "last": pts[-1]["captured_at"],
    }


@router.get("/public/trail/{collab_id}")
async def public_trail(collab_id: str,
                          date: Optional[str] = Query(None)):
    """Trajeto do dia (sem JWT) — usado pelo próprio app."""
    coll = await _resolve_company(collab_id)
    return await _load_trail(coll.get("company_id"), collab_id, date)


@router.get("/trail/{collab_id}")
async def admin_trail(collab_id: str,
                         date: Optional[str] = Query(None),
                         user: dict = Depends(get_current_user)):
    """Trajeto do dia (autenticado) — para painel do gestor."""
    coll = await _resolve_company(collab_id)
    return await _load_trail(coll.get("company_id"), collab_id, date)


@router.get("/trail/{collab_id}/snap")
async def admin_trail_snapped(collab_id: str,
                                  date: Optional[str] = Query(None),
                                  user: dict = Depends(get_current_user)):
    """Trail casado nas vias (auditoria do gestor)."""
    coll = await _resolve_company(collab_id)
    trail = await _load_trail(coll.get("company_id"), collab_id, date)
    if not trail.get("points"):
        return {**trail, "snapped": None}
    snapped = await _snap_to_road(trail["points"])
    return {**trail, "snapped": snapped}


@router.get("/fleet/day")
async def fleet_day_summary(date: Optional[str] = Query(None),
                                  user: dict = Depends(get_current_user)):
    """iter159 — Resumo do dia: lista todos os técnicos com pings no dia
    + KPIs por técnico (km percorridos, tempo de campo, paradas, primeira
    e última atividade).
    """
    cid = user.get("company_id")
    start, end = _day_range(date)
    # Aggregation: por collab_id calcula primeiro/último ping e total
    pipeline = [
        {"$match": {"company_id": cid,
                       "captured_at": {"$gte": start, "$lte": end}}},
        {"$sort": {"captured_at": 1}},
        {"$group": {
            "_id": "$collab_id",
            "name": {"$first": "$collab_name"},
            "first": {"$first": "$captured_at"},
            "last": {"$last": "$captured_at"},
            "count": {"$sum": 1},
            "points": {"$push": {"lat": "$lat", "lng": "$lng",
                                       "captured_at": "$captured_at",
                                       "speed": "$speed"}},
        }},
    ]
    items: List[Dict[str, Any]] = []
    async for g in db.tech_locations.aggregate(pipeline):
        pts = g.get("points") or []
        # Calcula distância e paradas (intervalos > 5 min sem movimento > 30m)
        total_m = 0.0
        stops = 0
        last_move_dt = None
        last_move_pos = None
        for i, p in enumerate(pts):
            if i == 0:
                last_move_pos = (p["lat"], p["lng"])
                try:
                    last_move_dt = datetime.fromisoformat(p["captured_at"])
                except Exception:
                    last_move_dt = None
                continue
            try:
                d = _haversine_m(pts[i-1]["lat"], pts[i-1]["lng"],
                                      p["lat"], p["lng"])
                total_m += d
                if d > 30 and last_move_pos:
                    try:
                        now_dt = datetime.fromisoformat(p["captured_at"])
                        if last_move_dt and (now_dt - last_move_dt).total_seconds() > 300:
                            stops += 1
                        last_move_dt = now_dt
                        last_move_pos = (p["lat"], p["lng"])
                    except Exception:
                        pass
            except Exception:
                pass
        # Duração do dia em segundos
        try:
            dur_s = (datetime.fromisoformat(g["last"])
                       - datetime.fromisoformat(g["first"])).total_seconds()
        except Exception:
            dur_s = 0
        items.append({
            "collab_id": g["_id"],
            "name": g.get("name") or g["_id"],
            "first": g["first"],
            "last": g["last"],
            "count": g["count"],
            "distance_m": round(total_m, 1),
            "duration_s": int(dur_s),
            "stops": stops,
        })
    items.sort(key=lambda x: -x["distance_m"])
    return {"date": start[:10], "items": items,
              "total_techs": len(items),
              "total_distance_m": round(sum(it["distance_m"] for it in items), 1)}



async def _snap_to_road(points: List[Dict[str, Any]]) -> Optional[List[List[float]]]:
    """Chama OSRM match para "colar" pontos GPS nas vias do OSM.

    Retorna lista de pares [lat, lng] formando a geometria casada na rede
    viária. None se falhar ou não tiver pontos suficientes.

    Limites:
    - OSRM público aceita até 100 coords por request.
    - Damos um timeout curto (5s) — se OSRM estiver lento, o frontend
      cai pro polyline reto (sem perda funcional).
    """
    if len(points) < 2:
        return None
    import httpx
    # OSRM público (Project-OSRM). Substitua por instance própria para
    # produção com alto volume.
    base = "https://router.project-osrm.org/match/v1/driving/"
    snapped: List[List[float]] = []
    # Chunks de até 100 pts (max OSRM)
    CHUNK = 100
    async with httpx.AsyncClient(timeout=5.0) as cli:
        for start in range(0, len(points), CHUNK - 1):
            chunk = points[start:start + CHUNK]
            if len(chunk) < 2:
                break
            coords = ";".join(f"{p['lng']:.6f},{p['lat']:.6f}" for p in chunk)
            # radiuses ajuda OSRM com pontos imprecisos. OSRM público
            # rejeita > 25m — usamos 25 fixo (suficiente p/ pings de GPS bons)
            radiuses = ";".join("25" for _ in chunk)
            url = (f"{base}{coords}?overview=full&geometries=geojson"
                   f"&radiuses={radiuses}&tidy=true&gaps=ignore")
            try:
                r = await cli.get(url)
                if r.status_code != 200:
                    return None
                data = r.json()
                if data.get("code") != "Ok":
                    return None
                for m in data.get("matchings", []) or []:
                    geom = (m.get("geometry") or {}).get("coordinates") or []
                    for lng, lat in geom:
                        snapped.append([lat, lng])
            except Exception as e:  # noqa: BLE001
                logger.debug("[tech-tracking] snap-to-road falhou: %s", e)
                return None
    return snapped or None


@router.get("/public/trail/{collab_id}/snap")
async def public_trail_snapped(collab_id: str,
                                  date: Optional[str] = Query(None)):
    """iter158 — Trail "colado" nas vias do OSM via OSRM match.

    Retorna o trail original + uma chave `snapped` (lista de [lat,lng])
    representando o caminho real percorrido nas ruas. Útil para visualizar
    o trajeto cobrindo as ruas em vez de retas ligando os pings.
    """
    coll = await _resolve_company(collab_id)
    trail = await _load_trail(coll.get("company_id"), collab_id, date)
    if not trail.get("points"):
        return {**trail, "snapped": None}
    snapped = await _snap_to_road(trail["points"])
    return {**trail, "snapped": snapped}

