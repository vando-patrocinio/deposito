"""Mapa interativo FTTH — rede_IA.

Elementos da rede:
- CTOs (já existem em `ctos`) — pontos com lat/lng
- CE (Caixa de Emenda) — splice closures que agrupam CTOs próximas
- Cabos — polylines entre CE↔CTO ou CTO↔CTO, com tipo (6FO, 12FO, 24FO, drop)
- Drops — conexões individuais cliente↔CTO

Coleções novas:
- `network_ces`: {id, name, lat, lng, capacity_fo, parent_ce_id?, address, type, status}
- `network_cables`: {id, type, fo_count, segments[{lat,lng}], from_id, to_id, length_m, status}
- `network_positions`: overrides de posição manual {entity_id, type, lat, lng}

Endpoints:
- GET  /map/data              → tudo agregado para o front
- POST /ces                   → cria CE manualmente
- PUT  /ces/{id}              → edita CE
- DELETE /ces/{id}
- POST /cables                → cria cabo
- PUT  /cables/{id}
- DELETE /cables/{id}
- POST /map/auto-generate-ces → rede_IA cria CEs por geo-clustering
- POST /map/positions         → grava reposicionamento manual
- GET  /map/cto-health/{id}   → média de sinal das ONUs daquela CTO/VLAN
"""
import logging
import math
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role, get_current_user
from database import db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rede-ia", tags=["rede_ia_map"])

CABLE_TYPES = ("drop", "6fo", "12fo", "24fo", "48fo", "96fo")
CE_TYPES = ("primaria", "secundaria", "terciaria", "emenda_aerea", "emenda_subterranea")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class CEIn(BaseModel):
    name: str
    lat: float
    lng: float
    capacity_fo: int = 24
    type: str = "secundaria"
    parent_ce_id: Optional[str] = None
    address: str = ""
    notes: str = ""


class CableSegment(BaseModel):
    lat: float
    lng: float


class CableIn(BaseModel):
    type: str = "12fo"  # drop | 6fo | 12fo | 24fo | 48fo | 96fo
    from_id: str  # ce-xxx ou cto-xxx
    from_type: str  # "ce" | "cto"
    to_id: str
    to_type: str
    segments: List[CableSegment] = []
    length_m: Optional[float] = None
    notes: str = ""


class PositionIn(BaseModel):
    entity_id: str
    entity_type: str  # cto | ce
    lat: float
    lng: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _company(user: dict) -> str:
    return user.get("_active_company") or user.get("company_id") or DEMO_COMPANY_ID


def _haversine_m(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    """Distância em metros entre 2 pontos GPS."""
    R = 6371000.0
    phi1 = math.radians(a_lat)
    phi2 = math.radians(b_lat)
    dphi = math.radians(b_lat - a_lat)
    dlam = math.radians(b_lng - a_lng)
    sa = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(sa))


async def _cto_health(company_id: str, cto: Dict[str, Any]) -> Dict[str, Any]:
    """Agrega sinal das ONUs SmartOLT que casam com a CTO.

    Critério: zone_name regex match com nome/número/sigla da CTO.
    Retorna: {score, status, total, warning, critical, avg_rx_dbm}
    """
    number = cto.get("number")
    sigla = cto.get("sigla")
    cto_name = cto.get("name") or ""
    if not (number and sigla):
        return {"status": "unknown", "score": 100, "total": 0,
                "warning": 0, "critical": 0}

    patterns = [
        cto_name,
        f"CTO[\\s\\-_]*0*{number}(?!\\d)" if isinstance(number, int) else None,
        f"_{sigla}",
    ]
    patterns = [p for p in patterns if p]
    or_filt = [{"zone_name": {"$regex": p, "$options": "i"}} for p in patterns]

    onus = await db.smartolt_onus.find(
        {"company_id": company_id, "$or": or_filt},
        {"_id": 0, "signal_text": 1, "rx_power": 1, "status": 1},
    ).limit(100).to_list(100)

    total = len(onus)
    if total == 0:
        return {"status": "no_data", "score": 100, "total": 0,
                "warning": 0, "critical": 0}

    warning = 0
    critical = 0
    rx_values: List[float] = []
    for o in onus:
        sig = (o.get("signal_text") or "").lower()
        if sig in ("critical", "alarm"):
            critical += 1
        elif sig in ("warning",):
            warning += 1
        rx = o.get("rx_power")
        if isinstance(rx, (int, float)) and -40 < rx < 0:
            rx_values.append(float(rx))

    score = max(0, 100 - (critical * 30 + warning * 10))
    if critical > 0 or score < 40:
        status = "critical"
    elif warning > 0 or score < 70:
        status = "warning"
    else:
        status = "ok"

    return {
        "status": status, "score": score, "total": total,
        "warning": warning, "critical": critical,
        "avg_rx_dbm": (sum(rx_values) / len(rx_values)) if rx_values else None,
    }


# ---------------------------------------------------------------------------
# Map data
# ---------------------------------------------------------------------------
@router.get("/map/data")
async def get_map_data(user: dict = Depends(get_current_user)):
    """Retorna tudo necessário para renderizar o mapa Leaflet."""
    cid = _company(user)

    ctos_raw = await db.ctos.find(
        {"company_id": cid, "status": {"$in": ["approved", "pending_validation"]}},
        {"_id": 0},
    ).to_list(1000)
    ces = await db.network_ces.find({"company_id": cid}, {"_id": 0}).to_list(500)
    cables = await db.network_cables.find({"company_id": cid}, {"_id": 0}).to_list(2000)

    # Aplica overrides de posição manual
    overrides = await db.network_positions.find({"company_id": cid}, {"_id": 0}).to_list(2000)
    pos_map = {f"{o['entity_type']}:{o['entity_id']}": (o["lat"], o["lng"]) for o in overrides}

    ctos = []
    for c in ctos_raw:
        gps = c.get("gps") or {}
        key = f"cto:{c['id']}"
        if key in pos_map:
            lat, lng = pos_map[key]
        else:
            lat, lng = gps.get("lat"), gps.get("lng")
        if lat is None or lng is None:
            continue
        health = await _cto_health(cid, c)
        used = len([p for p in (c.get("ports") or []) if p.get("status") == "used"])
        ctos.append({
            "id": c["id"], "name": c["name"], "lat": lat, "lng": lng,
            "vlan": c.get("vlan"), "sigla": c.get("sigla"),
            "capacity": c.get("capacity"),
            "used_ports": used,
            "address": c.get("address"),
            "status": c.get("status"),
            "network_type": c.get("network_type"),
            "splitter": c.get("splitter"),
            "health": health,
            "moved_manually": key in pos_map,
            "photo_thumb": bool(c.get("photo_data_url")),
        })

    # Aplica overrides nas CEs também
    ces_out = []
    for ce in ces:
        key = f"ce:{ce['id']}"
        if key in pos_map:
            ce["lat"], ce["lng"] = pos_map[key]
            ce["moved_manually"] = True
        else:
            ce["moved_manually"] = False
        ces_out.append(ce)

    # Estatísticas agregadas por VLAN para o painel lateral
    vlans: Dict[int, Dict[str, Any]] = {}
    for c in ctos:
        v = c.get("vlan")
        if v is None:
            continue
        bucket = vlans.setdefault(v, {
            "vlan": v, "sigla": c.get("sigla"), "cto_count": 0,
            "critical": 0, "warning": 0, "ok": 0,
            "avg_score": 0, "scores": [],
        })
        bucket["cto_count"] += 1
        bucket["scores"].append(c["health"].get("score", 100))
        st = c["health"].get("status")
        if st in bucket:
            bucket[st] += 1
    for v, b in vlans.items():
        scores = b.pop("scores")
        b["avg_score"] = round(sum(scores) / len(scores)) if scores else 100

    return {
        "ctos": ctos,
        "ces": ces_out,
        "cables": cables,
        "vlans": list(vlans.values()),
        "center": _compute_center(ctos),
    }


def _compute_center(ctos: List[Dict[str, Any]]) -> Dict[str, float]:
    """Retorna o centro geográfico médio das CTOs (para fitBounds)."""
    if not ctos:
        return {"lat": -22.9068, "lng": -43.1729}  # Rio fallback
    lats = [c["lat"] for c in ctos]
    lngs = [c["lng"] for c in ctos]
    return {"lat": sum(lats) / len(lats), "lng": sum(lngs) / len(lngs)}


# ---------------------------------------------------------------------------
# CE CRUD
# ---------------------------------------------------------------------------
@router.post("/ces")
async def create_ce(body: CEIn,
                     user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    if body.type not in CE_TYPES:
        raise HTTPException(400, f"Tipo inválido. Use: {CE_TYPES}")
    cid = _company(user)
    doc = {
        "id": f"ce-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "name": body.name,
        "lat": body.lat, "lng": body.lng,
        "capacity_fo": body.capacity_fo,
        "type": body.type,
        "parent_ce_id": body.parent_ce_id,
        "address": body.address,
        "notes": body.notes,
        "status": "active",
        "created_at": now_iso(), "updated_at": now_iso(),
        "created_by": user.get("name"),
    }
    await db.network_ces.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/ces/{ce_id}")
async def update_ce(ce_id: str, body: CEIn,
                     user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    cid = _company(user)
    upd = body.model_dump()
    upd["updated_at"] = now_iso()
    r = await db.network_ces.update_one(
        {"id": ce_id, "company_id": cid}, {"$set": upd},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "CE não encontrada")
    return {"ok": True}


@router.delete("/ces/{ce_id}")
async def delete_ce(ce_id: str,
                     user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    cid = _company(user)
    # remove cabos ligados
    await db.network_cables.delete_many({"company_id": cid,
                                            "$or": [{"from_id": ce_id}, {"to_id": ce_id}]})
    r = await db.network_ces.delete_one({"id": ce_id, "company_id": cid})
    if r.deleted_count == 0:
        raise HTTPException(404, "CE não encontrada")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Cable CRUD
# ---------------------------------------------------------------------------
@router.post("/cables")
async def create_cable(body: CableIn,
                        user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    if body.type not in CABLE_TYPES:
        raise HTTPException(400, f"Tipo inválido. Use: {CABLE_TYPES}")
    cid = _company(user)
    fo_map = {"drop": 1, "6fo": 6, "12fo": 12, "24fo": 24, "48fo": 48, "96fo": 96}
    doc = {
        "id": f"cab-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "type": body.type,
        "fo_count": fo_map.get(body.type, 12),
        "from_id": body.from_id, "from_type": body.from_type,
        "to_id": body.to_id, "to_type": body.to_type,
        "segments": [s.model_dump() for s in body.segments],
        "length_m": body.length_m,
        "notes": body.notes,
        "status": "active",
        "created_at": now_iso(), "updated_at": now_iso(),
        "created_by": user.get("name"),
    }
    await db.network_cables.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/cables/{cable_id}")
async def update_cable(cable_id: str, body: CableIn,
                        user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    cid = _company(user)
    fo_map = {"drop": 1, "6fo": 6, "12fo": 12, "24fo": 24, "48fo": 48, "96fo": 96}
    upd = body.model_dump()
    upd["fo_count"] = fo_map.get(body.type, 12)
    upd["segments"] = [s if isinstance(s, dict) else s.model_dump() for s in body.segments]
    upd["updated_at"] = now_iso()
    r = await db.network_cables.update_one(
        {"id": cable_id, "company_id": cid}, {"$set": upd},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Cabo não encontrado")
    return {"ok": True}


@router.delete("/cables/{cable_id}")
async def delete_cable(cable_id: str,
                        user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    cid = _company(user)
    r = await db.network_cables.delete_one({"id": cable_id, "company_id": cid})
    if r.deleted_count == 0:
        raise HTTPException(404, "Cabo não encontrado")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Position overrides (drag to reposition)
# ---------------------------------------------------------------------------
@router.post("/map/positions")
async def save_position(body: PositionIn,
                         user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    if body.entity_type not in ("cto", "ce"):
        raise HTTPException(400, "Entity type deve ser 'cto' ou 'ce'")
    cid = _company(user)
    doc = {
        "company_id": cid,
        "entity_id": body.entity_id,
        "entity_type": body.entity_type,
        "lat": body.lat,
        "lng": body.lng,
        "updated_at": now_iso(),
        "updated_by": user.get("name"),
    }
    await db.network_positions.update_one(
        {"company_id": cid, "entity_id": body.entity_id, "entity_type": body.entity_type},
        {"$set": doc}, upsert=True,
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Auto-generate CEs (rede_IA)
# ---------------------------------------------------------------------------
@router.post("/map/auto-generate-ces")
async def auto_generate_ces(radius_m: float = Query(200.0, ge=50, le=2000),
                             user: dict = Depends(require_role("administrador", "gestor", "gestor_rede"))):
    """Agrupa CTOs próximas em CEs automaticamente (cluster geográfico).

    Algoritmo: para cada CTO sem CE atribuída, encontra vizinhas no raio
    `radius_m`. Cria 1 CE no centroide do cluster.
    Também cria cabos `24fo` ligando CE → CTOs do cluster.
    """
    cid = _company(user)
    ctos = await db.ctos.find(
        {"company_id": cid, "status": "approved", "gps.lat": {"$ne": None}},
        {"_id": 0, "id": 1, "name": 1, "gps": 1, "sigla": 1, "vlan": 1},
    ).to_list(1000)

    if not ctos:
        return {"ok": False, "msg": "Nenhuma CTO aprovada com GPS"}

    # Cabos existentes: skipa CTOs já conectadas
    existing_to_ids = set()
    async for cab in db.network_cables.find({"company_id": cid}, {"_id": 0, "to_id": 1}):
        existing_to_ids.add(cab["to_id"])

    visited: set = set()
    new_ces: List[Dict[str, Any]] = []
    new_cables: List[Dict[str, Any]] = []

    for i, c in enumerate(ctos):
        if c["id"] in visited:
            continue
        gps = c.get("gps") or {}
        if gps.get("lat") is None:
            continue
        cluster = [c]
        visited.add(c["id"])
        for j in range(i + 1, len(ctos)):
            c2 = ctos[j]
            if c2["id"] in visited:
                continue
            gps2 = c2.get("gps") or {}
            if gps2.get("lat") is None:
                continue
            d = _haversine_m(gps["lat"], gps["lng"], gps2["lat"], gps2["lng"])
            if d <= radius_m and c.get("sigla") == c2.get("sigla"):
                cluster.append(c2)
                visited.add(c2["id"])

        # Centroide
        lat_c = sum((cl.get("gps") or {}).get("lat", 0) for cl in cluster) / len(cluster)
        lng_c = sum((cl.get("gps") or {}).get("lng", 0) for cl in cluster) / len(cluster)
        ce_doc = {
            "id": f"ce-{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "name": f"CE-{c.get('sigla','GEN')}-{len(new_ces)+1:03d}",
            "lat": lat_c, "lng": lng_c,
            "capacity_fo": 24,
            "type": "secundaria",
            "parent_ce_id": None,
            "address": "",
            "notes": f"Auto-gerada pela rede_IA · cluster com {len(cluster)} CTOs",
            "status": "active",
            "auto_generated": True,
            "created_at": now_iso(), "updated_at": now_iso(),
            "created_by": "rede_IA (automático)",
        }
        new_ces.append(ce_doc)

        # Cria cabos CE → cada CTO
        for cl in cluster:
            if cl["id"] in existing_to_ids:
                continue
            gps_cl = cl.get("gps") or {}
            new_cables.append({
                "id": f"cab-{uuid.uuid4().hex[:10]}",
                "company_id": cid,
                "type": "24fo",
                "fo_count": 24,
                "from_id": ce_doc["id"], "from_type": "ce",
                "to_id": cl["id"], "to_type": "cto",
                "segments": [
                    {"lat": ce_doc["lat"], "lng": ce_doc["lng"]},
                    {"lat": gps_cl["lat"], "lng": gps_cl["lng"]},
                ],
                "length_m": _haversine_m(ce_doc["lat"], ce_doc["lng"],
                                            gps_cl["lat"], gps_cl["lng"]),
                "notes": "Auto-gerado pela rede_IA",
                "status": "active",
                "auto_generated": True,
                "created_at": now_iso(), "updated_at": now_iso(),
                "created_by": "rede_IA (automático)",
            })

    if new_ces:
        await db.network_ces.insert_many(new_ces)
    if new_cables:
        await db.network_cables.insert_many(new_cables)

    return {
        "ok": True,
        "ces_created": len(new_ces),
        "cables_created": len(new_cables),
        "ctos_clustered": len(visited),
        "radius_m": radius_m,
    }
