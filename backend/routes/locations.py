"""Endpoints de localização ao vivo, trajeto, dwell-analysis."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

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
    """Última posição de cada colaborador nos últimos N minutos (default 6h)."""
    since = (datetime.now(timezone.utc) - timedelta(minutes=active_minutes)).isoformat()
    # Limita aos colaboradores do tenant
    cids: list[str] = []
    if not is_super_admin(user):
        async for c in db.collaborators.find(tenant_filter(user), {"_id": 0, "id": 1}):
            cids.append(c["id"])
    match: dict = {"recorded_at": {"$gte": since}}
    if cids:
        match["collaborator_id"] = {"$in": cids}
    pipeline = [
        {"$match": match},
        {"$sort": {"recorded_at": -1}},
        {"$group": {"_id": "$collaborator_id", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
    ]
    out = []
    async for d in db.location_logs.aggregate(pipeline):
        d.pop("_id", None)
        out.append(d)
    return out


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
    colls = await db.collaborators.find(coll_filter, {"_id": 0, "id": 1, "name": 1, "company_id": 1}).to_list(2000)
    name_by_id = {c["id"]: c.get("name") or c["id"] for c in colls}
    company_by_id = {c["id"]: c.get("company_id") or DEMO_COMPANY_ID for c in colls}
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

        items.append({
            "collaborator_id": cid,
            "name": name_by_id.get(cid, cid),
            "current_location": {
                "lat": float(live["lat"]), "lng": float(live["lng"]),
                "recorded_at": live.get("recorded_at"),
                "accuracy": live.get("accuracy"),
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


@router.get("/{cid}/track")
async def track_collaborator(cid: str, hours: int = 24):
    """Trajeto de um colaborador nas últimas N horas (default 24h)."""
    since = (datetime.now(timezone.utc) - timedelta(hours=int(hours))).isoformat()
    docs = await db.location_logs.find(
        {"collaborator_id": cid, "recorded_at": {"$gte": since}},
        {"_id": 0},
    ).sort("recorded_at", 1).to_list(10000)
    return docs


@router.delete("/{cid}")
async def clear_track(cid: str, hours: Optional[int] = None):
    """Limpa o histórico de localização (útil para testes)."""
    q: dict = {"collaborator_id": cid}
    if hours is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=int(hours))).isoformat()
        q["recorded_at"] = {"$lt": cutoff}
    res = await db.location_logs.delete_many(q)
    return {"deleted": res.deleted_count}
