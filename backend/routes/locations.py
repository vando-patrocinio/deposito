"""Endpoints de localização ao vivo, trajeto, dwell-analysis."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import (
    DEMO_COMPANY_ID,
    build_stay_clusters,
    get_current_user,
    is_super_admin,
    llm_evaluate_dwell,
    now_iso,
    resolve_geofence_for,
    tenant_filter,
)
from database import db

router = APIRouter(prefix="/api/locations", tags=["locations"])


class LocationPing(BaseModel):
    collaborator_id: str
    lat: float
    lng: float
    accuracy: Optional[float] = None
    speed: Optional[float] = None
    heading: Optional[float] = None


@router.post("")
async def post_location(p: LocationPing):
    coll = await db.collaborators.find_one({"id": p.collaborator_id}, {"_id": 0, "id": 1, "company_id": 1})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    doc = {
        "id": uuid.uuid4().hex[:14],
        "collaborator_id": p.collaborator_id,
        "company_id": coll.get("company_id") or DEMO_COMPANY_ID,
        "lat": float(p.lat),
        "lng": float(p.lng),
        "accuracy": float(p.accuracy) if p.accuracy is not None else None,
        "speed": float(p.speed) if p.speed is not None else None,
        "heading": float(p.heading) if p.heading is not None else None,
        "recorded_at": now_iso(),
        "source": "live",
    }
    await db.location_logs.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/live")
async def live_locations(active_minutes: int = 360,
                         user: dict = Depends(get_current_user)):
    """Última posição de cada colaborador nos últimos N minutos (default 6h).

    iter225 — agora consulta TANTO `location_logs` (legado) QUANTO
    `tech_locations` (PWA tech-tracking). Antes só lia o primeiro, o
    que fazia o LiveMap aparecer "parado" quando o técnico usava o
    PWA — todos os pings dele iam para `tech_locations` e o LiveMap
    ficava em branco. Mesclamos por colaborador e usamos o ping mais
    recente.
    """
    since = (datetime.now(timezone.utc) - timedelta(minutes=active_minutes)).isoformat()
    # Limita aos colaboradores do tenant
    cids: list[str] = []
    if not is_super_admin(user):
        async for c in db.collaborators.find(tenant_filter(user), {"_id": 0, "id": 1}):
            cids.append(c["id"])

    # ---- 1) location_logs ----
    match: dict = {"recorded_at": {"$gte": since}}
    if cids:
        match["collaborator_id"] = {"$in": cids}
    pipeline = [
        {"$match": match},
        {"$sort": {"recorded_at": -1}},
        {"$group": {"_id": "$collaborator_id", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
    ]
    by_cid: dict[str, dict] = {}
    async for d in db.location_logs.aggregate(pipeline):
        d.pop("_id", None)
        by_cid[d.get("collaborator_id")] = d

    # ---- 2) tech_locations (PWA tech-tracking) ----
    tmatch: dict = {"captured_at": {"$gte": since}}
    if cids:
        tmatch["collab_id"] = {"$in": cids}
    tpipeline = [
        {"$match": tmatch},
        {"$sort": {"captured_at": -1}},
        {"$group": {"_id": "$collab_id", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
    ]
    async for d in db.tech_locations.aggregate(tpipeline):
        d.pop("_id", None)
        cid = d.get("collab_id")
        # Normaliza pro formato do LiveMap (mesmas chaves)
        norm = {
            "collaborator_id": cid,
            "lat": d.get("lat"),
            "lng": d.get("lng"),
            "accuracy": d.get("accuracy"),
            "speed": d.get("speed"),
            "heading": d.get("heading"),
            "recorded_at": d.get("captured_at"),
            "source": "tech_pwa",
        }
        existing = by_cid.get(cid)
        if (not existing) or (norm["recorded_at"] > existing.get("recorded_at", "")):
            by_cid[cid] = norm

    return list(by_cid.values())


@router.get("/dwell-analysis")
async def dwell_analysis_endpoint(hours: int = 8, radius_m: float = 60.0, min_dur_min: int = 30,
                                  use_ai: bool = True, user: dict = Depends(get_current_user)):
    cid_company = None if is_super_admin(user) else (user.get("company_id") or DEMO_COMPANY_ID)
    return await dwell_analysis(hours, radius_m, min_dur_min, use_ai, company_id=cid_company)


async def dwell_analysis(hours: int = 8, radius_m: float = 60.0, min_dur_min: int = 30,
                         use_ai: bool = True, company_id: Optional[str] = None):
    """Analisa localização para detectar permanências longas (>= min_dur_min) e fora-da-cerca.
    Se `company_id` for passado, restringe ao tenant; caso contrário (job interno), cross-tenant."""
    hours = max(1, min(int(hours), 48))
    radius_m = max(15.0, min(float(radius_m), 500.0))
    min_dur_min = max(5, min(int(min_dur_min), 240))
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    coll_filter: dict = {} if not company_id else {"company_id": company_id}
    colls = await db.collaborators.find(
        coll_filter,
        {"_id": 0, "id": 1, "name": 1, "company_id": 1, "clock_in_enabled": 1},
    ).to_list(2000)
    name_by_id = {c["id"]: c.get("name") or c["id"] for c in colls}
    company_by_id = {c["id"]: c.get("company_id") or DEMO_COMPANY_ID for c in colls}
    # Colaborador que NÃO bate ponto (terceirizado/MEI) tem cercas salvas
    # mas elas NÃO devem gerar alerta "fora da cerca" no LiveMap — apenas
    # serve pra fechamento de OS. Reproduz a lógica do CadastroPanel.
    clock_enabled_by_id = {c["id"]: bool(c.get("clock_in_enabled", True))
                            for c in colls}
    allowed_ids = set(name_by_id.keys())

    match_live: dict = {"recorded_at": {"$gte": since}}
    if company_id:
        match_live["collaborator_id"] = {"$in": list(allowed_ids)}
    pipeline_live = [
        {"$match": match_live},
        {"$sort": {"recorded_at": -1}},
        {"$group": {"_id": "$collaborator_id", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
    ]
    live_by_id: dict[str, dict] = {}
    async for d in db.location_logs.aggregate(pipeline_live):
        d.pop("_id", None)
        live_by_id[d["collaborator_id"]] = d

    items: list[dict] = []
    for cid, live in live_by_id.items():
        track = await db.location_logs.find(
            {"collaborator_id": cid, "recorded_at": {"$gte": since}},
            {"_id": 0, "lat": 1, "lng": 1, "recorded_at": 1},
        ).sort("recorded_at", 1).to_list(20000)
        stays_all = build_stay_clusters(track, radius_m=radius_m, min_dur_min=min_dur_min)
        current = stays_all[-1] if stays_all else None
        cur_dur = current["duration_min"] if current else 0

        fence, dist = await resolve_geofence_for(cid, float(live["lat"]), float(live["lng"]))
        out_of_fence = (fence is None)
        any_fences = await db.geofences.count_documents({"collaborator_id": cid, "active": True})
        has_fences = any_fences > 0
        if not has_fences:
            out_of_fence = False
        # Colaborador desligado de bater ponto → cercas servem só pra
        # fechamento de OS (anti-fraude), NÃO geram alerta de geofence.
        if not clock_enabled_by_id.get(cid, True):
            out_of_fence = False

        # Label de precisão do GPS (pro card no LiveMap)
        # — usa o `accuracy` reportado pelo navigator.geolocation do app
        acc = live.get("accuracy")
        if acc is None:
            accuracy_label = "desconhecida"
        elif acc <= 50:
            accuracy_label = "exata"     # GPS chip ativo
        elif acc <= 500:
            accuracy_label = "aproximada"  # WiFi / cell tower
        else:
            accuracy_label = "imprecisa"

        items.append({
            "collaborator_id": cid,
            "name": name_by_id.get(cid, cid),
            "current_location": {
                "lat": float(live["lat"]), "lng": float(live["lng"]),
                "recorded_at": live.get("recorded_at"),
                "accuracy": live.get("accuracy"),
                "accuracy_label": accuracy_label,
            },
            "current_dwell_min": cur_dur,
            "current_cluster_center": {"lat": current["center_lat"], "lng": current["center_lng"]} if current else None,
            "out_of_fence": out_of_fence,
            "has_fences": has_fences,
            "nearest_fence_distance_m": round(dist, 1) if dist is not None else None,
            "stays": [s for s in stays_all if s["is_alert"]],
            "ai_evaluation": None,
        })

    flagged = [i for i in items if i["current_dwell_min"] >= min_dur_min or i["out_of_fence"]]
    ai_map: dict[str, dict] = {}
    if use_ai and flagged:
        ai_map = await llm_evaluate_dwell(flagged)
    for i in items:
        i["ai_evaluation"] = ai_map.get(i["collaborator_id"])

    alerts = []
    for i in items:
        cid_company = company_by_id.get(i["collaborator_id"], DEMO_COMPANY_ID)
        if i["current_dwell_min"] >= min_dur_min:
            alerts.append({
                "id": f"dwell:{i['collaborator_id']}",
                "level": "warning" if i["current_dwell_min"] < (2 * min_dur_min) else "danger",
                "collaborator_id": i["collaborator_id"],
                "company_id": cid_company,
                "title": f"{i['name']} parado(a) há {i['current_dwell_min']} min",
                "message": (i.get("ai_evaluation") or {}).get("summary")
                           or "Permanência prolongada no mesmo local.",
            })
        if i["out_of_fence"]:
            alerts.append({
                "id": f"fence:{i['collaborator_id']}",
                "level": "danger",
                "collaborator_id": i["collaborator_id"],
                "company_id": cid_company,
                "title": f"{i['name']} fora da cerca",
                "message": (
                    f"Distância da cerca mais próxima: {i['nearest_fence_distance_m']} m"
                    if i["nearest_fence_distance_m"] is not None
                    else "Posição atual não está dentro de nenhuma cerca cadastrada."
                ),
            })

    return {
        "generated_at": now_iso(),
        "hours": hours,
        "radius_m": radius_m,
        "stationary_threshold_min": min_dur_min,
        "use_ai": bool(use_ai),
        "items": items,
        "alerts": alerts,
    }


# iter215 — Limiares para limpeza do trajeto antes de plotar:
#  • Pings com accuracy pior que MAX_ACC_M são descartados (GPS preso em
#    prédio dá pontos "atravessando quarteirões"). 400m descarta WiFi
#    location ruim mas mantém pings WiFi razoáveis (mesma constante que o
#    POST `/public/ping` usa pra aceitar pings em `tech_locations`).
#  • Gap > GAP_S entre pings consecutivos → quebra em segmento novo
#    (evita reta voando entre dois pontos quando o tracker ficou off).
#  • Distância > DIST_M entre 2 pings consecutivos (independente do gap
#    temporal) → também quebra em segmento (salta sem trajetória real).
TRAIL_MAX_ACC_M = 1500.0  # iter215 — relaxado: GPS urbano às vezes 800–1200m
TRAIL_GAP_S = 900         # iter215 — 15min (antes 5min era muito agressivo)
TRAIL_JUMP_M = 2000.0     # iter215 — 2km (carro pode pular ~1.5km em 1 ping)

import logging as _logging
_trail_logger = _logging.getLogger("ponto.locations.trail")


def _haversine_m(a_lat: float, a_lng: float,
                  b_lat: float, b_lng: float) -> float:
    from math import asin, cos, radians, sin, sqrt
    f1, f2 = radians(a_lat), radians(b_lat)
    df = radians(b_lat - a_lat)
    dl = radians(b_lng - a_lng)
    a = sin(df / 2) ** 2 + cos(f1) * cos(f2) * sin(dl / 2) ** 2
    return 2 * 6371000 * asin(sqrt(a))


def _clean_and_split_trail(docs: List[Dict[str, Any]]
                            ) -> List[List[Dict[str, Any]]]:
    """Limpa e quebra um trail em segmentos contínuos.

    - Descarta pings com `accuracy > TRAIL_MAX_ACC_M`.
    - Inicia novo segmento quando gap temporal > TRAIL_GAP_S
      OU distância entre pings consecutivos > TRAIL_JUMP_M.
    Retorna apenas segmentos com >= 2 pontos.
    """
    sessions: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    last_dt = None
    last_pt = None
    for d in docs:
        acc = d.get("accuracy")
        if acc is not None and acc > TRAIL_MAX_ACC_M:
            continue
        try:
            cur_dt = datetime.fromisoformat(
                d["recorded_at"].replace("Z", "+00:00"))
        except Exception:
            continue
        break_seg = False
        if last_dt is not None and last_pt is not None:
            dt_s = (cur_dt - last_dt).total_seconds()
            try:
                dist = _haversine_m(last_pt["lat"], last_pt["lng"],
                                       d["lat"], d["lng"])
            except Exception:
                dist = 0
            if dt_s > TRAIL_GAP_S or dist > TRAIL_JUMP_M:
                break_seg = True
        if break_seg and len(current) >= 2:
            sessions.append(current)
            current = []
        elif break_seg:
            current = []
        current.append({"lat": d["lat"], "lng": d["lng"],
                          "recorded_at": d["recorded_at"]})
        last_dt = cur_dt
        last_pt = d
    if len(current) >= 2:
        sessions.append(current)
    return sessions


async def _fetch_merged_track(cid: str, since: str) -> List[Dict[str, Any]]:
    """iter225 — Mescla pings de `location_logs` (legado) + `tech_locations`
    (PWA tech-tracking). Devolve ordenado por timestamp ascendente, com
    todas as chaves usadas pelo frontend (`lat`, `lng`, `accuracy`,
    `recorded_at`).
    """
    docs = await db.location_logs.find(
        {"collaborator_id": cid, "recorded_at": {"$gte": since}},
        {"_id": 0},
    ).sort("recorded_at", 1).to_list(10000)
    tdocs = await db.tech_locations.find(
        {"collab_id": cid, "captured_at": {"$gte": since}},
        {"_id": 0},
    ).sort("captured_at", 1).to_list(10000)
    for d in tdocs:
        docs.append({
            "collaborator_id": cid,
            "lat": d.get("lat"),
            "lng": d.get("lng"),
            "accuracy": d.get("accuracy"),
            "speed": d.get("speed"),
            "heading": d.get("heading"),
            "recorded_at": d.get("captured_at"),
            "source": "tech_pwa",
        })
    docs.sort(key=lambda x: x.get("recorded_at") or "")
    return docs


@router.get("/{cid}/track")
async def track_collaborator(cid: str, hours: int = 24):
    """Trajeto de um colaborador nas últimas N horas (default 24h).

    iter225 — agora mescla `location_logs` + `tech_locations`.
    """
    since = (datetime.now(timezone.utc) - timedelta(hours=int(hours))).isoformat()
    return await _fetch_merged_track(cid, since)


@router.get("/{cid}/track/snap")
async def track_collaborator_snap(cid: str, hours: int = 24):
    """iter215 — Trajeto "colado" nas vias do OSM via OSRM match.

    Higieniza o trail antes de plotar (descarta pings imprecisos,
    quebra em segmentos quando há gap temporal/jump espacial) — assim o
    traço para de "voar quadras" quando o GPS perdeu sinal. Em seguida
    chama OSRM Match por sessão e devolve `segments_snapped`. Quando o
    OSRM falha pra um segmento, o frontend faz fallback pro polyline
    reto (mas só dentro daquele segmento, sem atravessar gaps).

    iter225 — agora mescla `location_logs` + `tech_locations` (PWA).
    """
    from routes.tech_tracking import _snap_to_road

    since = (datetime.now(timezone.utc) - timedelta(hours=int(hours))).isoformat()
    docs = await _fetch_merged_track(cid, since)

    sessions = _clean_and_split_trail(docs)

    # iter215 — Fallback "best-effort": se o filtro descartou TUDO mas
    # ainda temos pings brutos, devolve tudo como UM segmento contínuo.
    # Garante que o gestor veja ALGUMA coisa em vez de tela vazia.
    if not sessions and len(docs) >= 2:
        sessions = [[
            {"lat": d["lat"], "lng": d["lng"],
             "recorded_at": d.get("recorded_at")}
            for d in docs
            if d.get("lat") is not None and d.get("lng") is not None
        ]]
        sessions = [s for s in sessions if len(s) >= 2]

    # Chama OSRM Match pra cada sessão. Em paralelo.
    import asyncio
    snapped_segments = await asyncio.gather(
        *[_snap_to_road(seg) for seg in sessions],
        return_exceptions=False,
    )
    fallbacks = sum(1 for s in snapped_segments if not s)
    if sessions and fallbacks:
        _trail_logger.info(
            "[trail/snap] cid=%s sessions=%d snap_failed=%d (frontend fallback)",
            cid, len(sessions), fallbacks,
        )
    # Pontos brutos por segmento (frontend usa quando o snap volta vazio).
    segments_raw = [[{"lat": p["lat"], "lng": p["lng"]} for p in seg]
                       for seg in sessions]
    snapped_segments = [s if s else [] for s in snapped_segments]
    return {
        "points": docs,
        "segments_raw": segments_raw,
        "segments_snapped": snapped_segments,
        "filtered": {
            "max_accuracy_m": TRAIL_MAX_ACC_M,
            "gap_s": TRAIL_GAP_S,
            "jump_m": TRAIL_JUMP_M,
            "kept_segments": len(sessions),
        },
    }


@router.delete("/{cid}")
async def clear_track(cid: str, hours: Optional[int] = None):
    """Limpa o histórico de localização (útil para testes)."""
    q: dict = {"collaborator_id": cid}
    if hours is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=int(hours))).isoformat()
        q["recorded_at"] = {"$lt": cutoff}
    res = await db.location_logs.delete_many(q)
    return {"deleted": res.deleted_count}
