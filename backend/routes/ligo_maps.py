"""Ligo Maps — GIS/OSP para documentação de planta externa FTTH.

Inspirado no UpperX Fibra. Permite documentar a rede óptica
geograficamente:
- CTO (Caixa de Terminação Óptica)
- CEO (Caixa de Emenda Óptica)
- POP / Data Center
- Splitter
- Cabos (linhas conectando 2 pontos)
- Postes / Caixas de passagem

Cada ativo tem lat/lng + atributos (modelo, capacidade, status).
Cabos são `LineString` com lista de waypoints (caminho real seguindo
a rua, não linha reta).

Coleções:
- `ligo_map_assets`: pontos da rede (CTO/CEO/POP/Splitter/Poste)
- `ligo_map_cables`: cabos entre pontos (LineString + atributos)
- `ligo_map_regions`: áreas/cidades operacionais (polígono)

Sincronização campo↔escritório usa `updated_at` + last-write-wins.
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

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, require_role
from database import db

logger = logging.getLogger("ponto.ligo_maps")
router = APIRouter(prefix="/api/ligo-maps", tags=["ligo-maps"])


# Tipos de ativos suportados (cores e ícones definidos no frontend)
ASSET_TYPES = {"cto", "ceo", "pop", "splitter", "post", "junction"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
class AssetIn(BaseModel):
    type: str = Field(..., description="cto|ceo|pop|splitter|post|junction")
    label: str
    lat: float
    lng: float
    capacity: Optional[int] = None  # nº de portas (CTO) ou fibras (CEO)
    model: Optional[str] = None
    notes: Optional[str] = None
    status: str = "online"  # online | warning | offline | planned
    region: Optional[str] = None  # nome da cidade/área


class AssetUpdate(BaseModel):
    label: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    capacity: Optional[int] = None
    model: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    region: Optional[str] = None


class CableIn(BaseModel):
    from_asset_id: str
    to_asset_id: str
    fibers: int = 12  # capacidade (6/12/24/48/72/96/144FO)
    label: Optional[str] = None
    waypoints: Optional[List[List[float]]] = None  # [[lat,lng], ...]
    status: str = "online"
    region: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints — Assets
# ---------------------------------------------------------------------------
@router.get("/assets")
async def list_assets(
    region: Optional[str] = None,
    include_deleted: bool = False,
    user: dict = Depends(require_role("gestor", "tecnico", "administrador")),
):
    """Lista todos os ativos georreferenciados da empresa."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if not include_deleted:
        q["deleted_at"] = {"$in": [None, ""]}
    if region:
        q["region"] = region
    cursor = db.ligo_map_assets.find(q, {"_id": 0})
    items: List[Dict[str, Any]] = []
    async for a in cursor:
        items.append(a)
    return {"type": "FeatureCollection", "items": items,
             "count": len(items)}


@router.post("/assets")
async def create_asset(
    payload: AssetIn,
    user: dict = Depends(require_role("gestor", "tecnico", "administrador")),
):
    """Cria um novo ativo (CTO/CEO/POP/etc) no mapa."""
    if payload.type not in ASSET_TYPES:
        raise HTTPException(400,
            f"Tipo inválido. Aceitos: {', '.join(ASSET_TYPES)}")
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = {
        "id": _gen_id("asset"),
        "company_id": cid,
        "type": payload.type,
        "label": payload.label,
        "lat": payload.lat,
        "lng": payload.lng,
        "capacity": payload.capacity,
        "model": payload.model,
        "notes": payload.notes,
        "status": payload.status,
        "region": payload.region,
        "created_at": _now(),
        "created_by": user.get("name") or user.get("email") or "?",
        "updated_at": _now(),
    }
    await db.ligo_map_assets.insert_one(dict(doc))
    return doc


@router.patch("/assets/{asset_id}")
async def update_asset(
    asset_id: str, payload: AssetUpdate,
    user: dict = Depends(require_role("gestor", "tecnico", "administrador")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    update = {k: v for k, v in payload.dict(exclude_none=True).items()}
    update["updated_at"] = _now()
    update["updated_by"] = user.get("name") or user.get("email")
    r = await db.ligo_map_assets.update_one(
        {"id": asset_id, "company_id": cid}, {"$set": update})
    if r.matched_count == 0:
        raise HTTPException(404, "Ativo não encontrado.")
    return await db.ligo_map_assets.find_one(
        {"id": asset_id}, {"_id": 0})


@router.delete("/assets/{asset_id}")
async def delete_asset(
    asset_id: str,
    user: dict = Depends(require_role("gestor", "administrador")),
):
    """Soft-delete: marca `deleted_at` em vez de apagar.

    Cabos conectados também são marcados como deletados (cascata).
    Use `POST /restore/asset/{id}` para desfazer.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    now = _now()
    actor = user.get("name") or user.get("email") or "?"
    # Soft-delete em cascata
    await db.ligo_map_cables.update_many(
        {"company_id": cid,
         "$or": [{"from_asset_id": asset_id}, {"to_asset_id": asset_id}],
         "deleted_at": {"$in": [None, ""]}},
        {"$set": {"deleted_at": now, "deleted_by": actor,
                   "deleted_with_asset": asset_id}},
    )
    r = await db.ligo_map_assets.update_one(
        {"id": asset_id, "company_id": cid,
         "deleted_at": {"$in": [None, ""]}},
        {"$set": {"deleted_at": now, "deleted_by": actor}},
    )
    return {"deleted": r.matched_count, "soft_delete": True}


@router.post("/restore/asset/{asset_id}")
async def restore_asset(
    asset_id: str,
    user: dict = Depends(require_role("gestor", "administrador")),
):
    """Restaura um ativo soft-deletado + os cabos que foram apagados em
    cascata junto com ele."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    r1 = await db.ligo_map_assets.update_one(
        {"id": asset_id, "company_id": cid},
        {"$set": {"deleted_at": None, "deleted_by": None}},
    )
    if r1.matched_count == 0:
        raise HTTPException(404, "Ativo não encontrado.")
    # Restaura cabos que foram derrubados COM esse asset
    r2 = await db.ligo_map_cables.update_many(
        {"company_id": cid, "deleted_with_asset": asset_id},
        {"$set": {"deleted_at": None, "deleted_by": None,
                   "deleted_with_asset": None}},
    )
    return {"restored": True, "cables_restored": r2.modified_count}


# ---------------------------------------------------------------------------
# Endpoints — Cables
# ---------------------------------------------------------------------------
@router.get("/cables")
async def list_cables(
    region: Optional[str] = None,
    include_deleted: bool = False,
    user: dict = Depends(require_role("gestor", "tecnico", "administrador")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if not include_deleted:
        q["deleted_at"] = {"$in": [None, ""]}
    if region:
        q["region"] = region
    cursor = db.ligo_map_cables.find(q, {"_id": 0})
    items: List[Dict[str, Any]] = []
    async for c in cursor:
        items.append(c)
    return {"items": items, "count": len(items)}


@router.post("/cables")
async def create_cable(
    payload: CableIn,
    user: dict = Depends(require_role("gestor", "tecnico", "administrador")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # Verifica que ambos os pontos existem
    a = await db.ligo_map_assets.find_one(
        {"id": payload.from_asset_id, "company_id": cid}, {"_id": 0})
    b = await db.ligo_map_assets.find_one(
        {"id": payload.to_asset_id, "company_id": cid}, {"_id": 0})
    if not a or not b:
        raise HTTPException(404, "Asset origem/destino não encontrado.")
    # Calcula waypoints default (linha reta) se não fornecido
    waypoints = payload.waypoints or [[a["lat"], a["lng"]],
                                        [b["lat"], b["lng"]]]
    doc = {
        "id": _gen_id("cable"),
        "company_id": cid,
        "from_asset_id": payload.from_asset_id,
        "to_asset_id": payload.to_asset_id,
        "fibers": payload.fibers,
        "label": payload.label or f"{a['label']} → {b['label']}",
        "waypoints": waypoints,
        "status": payload.status,
        "region": payload.region or a.get("region"),
        "created_at": _now(),
        "created_by": user.get("name") or user.get("email"),
        "updated_at": _now(),
    }
    await db.ligo_map_cables.insert_one(dict(doc))
    return doc


class CableUpdate(BaseModel):
    fibers: Optional[int] = None
    label: Optional[str] = None
    waypoints: Optional[List[List[float]]] = None
    status: Optional[str] = None
    region: Optional[str] = None


@router.patch("/cables/{cable_id}")
async def update_cable(
    cable_id: str, payload: CableUpdate,
    user: dict = Depends(require_role("gestor", "tecnico", "administrador")),
):
    """Atualiza um cabo (usado principalmente para salvar waypoints
    editados via drag no mapa)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    update = {k: v for k, v in payload.dict(exclude_none=True).items()}
    update["updated_at"] = _now()
    update["updated_by"] = user.get("name") or user.get("email")
    r = await db.ligo_map_cables.update_one(
        {"id": cable_id, "company_id": cid}, {"$set": update})
    if r.matched_count == 0:
        raise HTTPException(404, "Cabo não encontrado.")
    doc = await db.ligo_map_cables.find_one({"id": cable_id}, {"_id": 0})
    return doc


@router.delete("/cables/{cable_id}")
async def delete_cable(
    cable_id: str,
    user: dict = Depends(require_role("gestor", "administrador")),
):
    """Soft-delete do cabo. Use `POST /restore/cable/{id}` para desfazer."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    actor = user.get("name") or user.get("email") or "?"
    r = await db.ligo_map_cables.update_one(
        {"id": cable_id, "company_id": cid,
         "deleted_at": {"$in": [None, ""]}},
        {"$set": {"deleted_at": _now(), "deleted_by": actor}},
    )
    return {"deleted": r.matched_count, "soft_delete": True}


@router.post("/restore/cable/{cable_id}")
async def restore_cable(
    cable_id: str,
    user: dict = Depends(require_role("gestor", "administrador")),
):
    """Restaura um cabo soft-deletado."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    r = await db.ligo_map_cables.update_one(
        {"id": cable_id, "company_id": cid},
        {"$set": {"deleted_at": None, "deleted_by": None}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Cabo não encontrado.")
    return {"restored": True}


@router.get("/trash")
async def list_trash(
    user: dict = Depends(require_role("gestor", "administrador")),
):
    """Lista assets e cabos soft-deletados (últimos 50 de cada)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    assets = await db.ligo_map_assets.find(
        {"company_id": cid, "deleted_at": {"$ne": None, "$exists": True}},
        {"_id": 0},
    ).sort("deleted_at", -1).limit(50).to_list(50)
    cables = await db.ligo_map_cables.find(
        {"company_id": cid, "deleted_at": {"$ne": None, "$exists": True}},
        {"_id": 0},
    ).sort("deleted_at", -1).limit(50).to_list(50)
    return {"assets": assets, "cables": cables,
             "total": len(assets) + len(cables)}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
@router.get("/stats")
async def stats(
    user: dict = Depends(require_role("gestor", "tecnico", "administrador")),
):
    """KPIs do mapa (Visão Geral)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    by_type: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    regions: set = set()
    total = 0
    async for a in db.ligo_map_assets.find(
            {"company_id": cid}, {"type": 1, "status": 1, "region": 1, "_id": 0}):
        total += 1
        by_type[a.get("type") or "?"] = by_type.get(a.get("type") or "?", 0) + 1
        by_status[a.get("status") or "online"] = \
            by_status.get(a.get("status") or "online", 0) + 1
        if a.get("region"):
            regions.add(a["region"])
    cables = await db.ligo_map_cables.count_documents({"company_id": cid})
    splices = await db.ligo_map_splices.count_documents({"company_id": cid})
    return {
        "total_assets": total, "total_cables": cables,
        "total_splices": splices,
        "by_type": by_type, "by_status": by_status,
        "regions": sorted(regions), "regions_count": len(regions),
    }


# ---------------------------------------------------------------------------
# Importar rede existente (CTOs/clientes do SmartProv)
# ---------------------------------------------------------------------------
@router.post("/import-from-network")
async def import_from_network(
    user: dict = Depends(require_role("gestor", "administrador")),
):
    """Importa CTOs de `cto_ports` e clientes de `subscribers` para o mapa.

    Lê todos os documentos com `lat`/`lng` válidos e cria assets
    correspondentes (CTOs como `cto`, clientes como `junction`). É
    idempotente: usa `import_ref` para detectar duplicações.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    added_ctos = 0
    added_subs = 0
    skipped = 0

    # CTOs do banco existente
    async for cto in db.cto_ports.find(
            {"company_id": cid,
             "lat": {"$exists": True, "$ne": None},
             "lng": {"$exists": True, "$ne": None}},
            {"_id": 0}):
        if not cto.get("lat") or not cto.get("lng"):
            continue
        existing = await db.ligo_map_assets.find_one({
            "company_id": cid, "import_ref": f"cto:{cto.get('id')}",
        })
        if existing:
            skipped += 1
            continue
        await db.ligo_map_assets.insert_one({
            "id": _gen_id("asset"),
            "company_id": cid,
            "type": "cto",
            "label": cto.get("label") or cto.get("name")
                or f"CTO {cto.get('id', '')[:8]}",
            "lat": float(cto["lat"]), "lng": float(cto["lng"]),
            "capacity": cto.get("ports_total") or cto.get("capacity"),
            "status": "online",
            "region": cto.get("branch") or cto.get("region"),
            "import_ref": f"cto:{cto.get('id')}",
            "created_at": _now(),
            "created_by": "import:cto_ports",
            "updated_at": _now(),
        })
        added_ctos += 1

    # Clientes ativos com lat/lng
    async for sub in db.subscribers.find(
            {"company_id": cid,
             "status": {"$in": ["ATIVO", "ativo"]},
             "lat": {"$exists": True, "$ne": None},
             "lng": {"$exists": True, "$ne": None}},
            {"_id": 0, "id": 1, "name": 1, "lat": 1, "lng": 1,
             "branch": 1, "plan_name": 1}):
        if not sub.get("lat") or not sub.get("lng"):
            continue
        existing = await db.ligo_map_assets.find_one({
            "company_id": cid, "import_ref": f"sub:{sub.get('id')}",
        })
        if existing:
            skipped += 1
            continue
        await db.ligo_map_assets.insert_one({
            "id": _gen_id("asset"),
            "company_id": cid,
            "type": "junction",          # cliente final → ponto de junção
            "label": sub.get("name") or "Cliente",
            "lat": float(sub["lat"]), "lng": float(sub["lng"]),
            "model": sub.get("plan_name"),
            "status": "online",
            "region": sub.get("branch"),
            "import_ref": f"sub:{sub.get('id')}",
            "created_at": _now(),
            "created_by": "import:subscribers",
            "updated_at": _now(),
        })
        added_subs += 1

    return {
        "added_ctos": added_ctos, "added_subscribers": added_subs,
        "skipped": skipped, "total_added": added_ctos + added_subs,
    }


# ---------------------------------------------------------------------------
# FASE 2 — Diagrama de Fusões (Splice Diagram)
# ---------------------------------------------------------------------------
class SpliceIn(BaseModel):
    ceo_asset_id: str   # qual CEO/POP contém essa fusão
    cable_in_id: str
    fiber_in: int       # número da fibra de entrada (1..N)
    cable_out_id: str
    fiber_out: int
    loss_db: Optional[float] = None  # atenuação medida (OTDR)
    notes: Optional[str] = None


@router.get("/splices")
async def list_splices(
    ceo_asset_id: Optional[str] = None,
    user: dict = Depends(require_role("gestor", "tecnico", "administrador")),
):
    """Lista fusões. Se `ceo_asset_id` informado, filtra por CEO."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if ceo_asset_id:
        q["ceo_asset_id"] = ceo_asset_id
    items: List[Dict[str, Any]] = []
    async for s in db.ligo_map_splices.find(q, {"_id": 0}):
        items.append(s)
    return {"items": items, "count": len(items)}


@router.post("/splices")
async def create_splice(
    payload: SpliceIn,
    user: dict = Depends(require_role("gestor", "tecnico", "administrador")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # Validar cabos
    in_cable = await db.ligo_map_cables.find_one(
        {"id": payload.cable_in_id, "company_id": cid}, {"_id": 0})
    out_cable = await db.ligo_map_cables.find_one(
        {"id": payload.cable_out_id, "company_id": cid}, {"_id": 0})
    if not in_cable or not out_cable:
        raise HTTPException(404, "Cabo não encontrado.")
    if payload.fiber_in < 1 or payload.fiber_in > in_cable["fibers"]:
        raise HTTPException(400,
            f"fiber_in fora do range 1..{in_cable['fibers']}")
    if payload.fiber_out < 1 or payload.fiber_out > out_cable["fibers"]:
        raise HTTPException(400,
            f"fiber_out fora do range 1..{out_cable['fibers']}")
    # Idempotente: não duplica
    existing = await db.ligo_map_splices.find_one({
        "company_id": cid,
        "ceo_asset_id": payload.ceo_asset_id,
        "cable_in_id": payload.cable_in_id, "fiber_in": payload.fiber_in,
        "cable_out_id": payload.cable_out_id, "fiber_out": payload.fiber_out,
    })
    if existing:
        existing.pop("_id", None)
        return existing
    doc = {
        "id": _gen_id("splice"),
        "company_id": cid,
        "ceo_asset_id": payload.ceo_asset_id,
        "cable_in_id": payload.cable_in_id,
        "fiber_in": payload.fiber_in,
        "cable_out_id": payload.cable_out_id,
        "fiber_out": payload.fiber_out,
        "loss_db": payload.loss_db,
        "notes": payload.notes,
        "created_at": _now(),
        "created_by": user.get("name") or user.get("email"),
    }
    await db.ligo_map_splices.insert_one(dict(doc))
    return doc


@router.delete("/splices/{splice_id}")
async def delete_splice(
    splice_id: str,
    user: dict = Depends(require_role("gestor", "tecnico", "administrador")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    r = await db.ligo_map_splices.delete_one(
        {"id": splice_id, "company_id": cid})
    return {"deleted": r.deleted_count}


# ---------------------------------------------------------------------------
# FASE 3 — Export As-Built (KMZ + PDF resumo)
# ---------------------------------------------------------------------------
@router.get("/export/kml")
async def export_kml(
    region: Optional[str] = None,
    user: dict = Depends(require_role("gestor", "tecnico", "administrador")),
):
    """Exporta a rede em KML (Google Earth). Texto puro, pronto pra
    abrir no Earth/Maps."""
    from fastapi.responses import Response
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if region:
        q["region"] = region
    assets = [a async for a in db.ligo_map_assets.find(q, {"_id": 0})]
    cables = [c async for c in db.ligo_map_cables.find(q, {"_id": 0})]

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        '<Document>',
        f'<name>Ligo Maps — {region or "Rede Completa"}</name>',
        '<Style id="cto"><IconStyle><color>ff4ba023</color>'
        '<scale>1.2</scale></IconStyle></Style>',
        '<Style id="ceo"><IconStyle><color>ff7a1d4b</color>'
        '<scale>1.2</scale></IconStyle></Style>',
        '<Style id="cable"><LineStyle><color>ff237a4b</color>'
        '<width>3</width></LineStyle></Style>',
    ]
    for a in assets:
        parts.append(
            f'<Placemark><name>{a.get("label", "")}</name>'
            f'<description>{a.get("type", "")} · '
            f'{a.get("model", "") or ""} · {a.get("status", "")}'
            f'</description>'
            f'<styleUrl>#{a.get("type", "cto")}</styleUrl>'
            f'<Point><coordinates>{a["lng"]},{a["lat"]},0'
            f'</coordinates></Point></Placemark>'
        )
    for c in cables:
        coords = " ".join(f"{w[1]},{w[0]},0" for w in c.get("waypoints", []))
        parts.append(
            f'<Placemark><name>{c.get("label", "")}</name>'
            f'<description>{c.get("fibers", 12)}FO · '
            f'{c.get("status", "")}</description>'
            f'<styleUrl>#cable</styleUrl>'
            f'<LineString><coordinates>{coords}</coordinates>'
            f'</LineString></Placemark>'
        )
    parts.append('</Document></kml>')
    kml = "\n".join(parts)
    return Response(content=kml, media_type="application/vnd.google-earth.kml+xml",
                     headers={"Content-Disposition":
                                'attachment; filename="ligo-rede.kml"'})


@router.get("/export/summary")
async def export_summary(
    user: dict = Depends(require_role("gestor", "tecnico", "administrador")),
):
    """Resumo As-Built em JSON (pronto pra renderizar PDF no frontend)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    assets = [a async for a in db.ligo_map_assets.find(
        {"company_id": cid}, {"_id": 0})]
    cables = [c async for c in db.ligo_map_cables.find(
        {"company_id": cid}, {"_id": 0})]
    splices = [s async for s in db.ligo_map_splices.find(
        {"company_id": cid}, {"_id": 0})]
    # Métricas
    by_type: Dict[str, int] = {}
    for a in assets:
        by_type[a["type"]] = by_type.get(a["type"], 0) + 1
    total_fiber_meters = 0
    for c in cables:
        wp = c.get("waypoints") or []
        # Distância haversine somada por trecho
        for i in range(len(wp) - 1):
            total_fiber_meters += _haversine_m(wp[i], wp[i + 1])
    return {
        "company_id": cid,
        "generated_at": _now(),
        "assets_total": len(assets), "by_type": by_type,
        "cables_total": len(cables),
        "splices_total": len(splices),
        "total_cable_length_m": round(total_fiber_meters),
        "total_cable_length_km": round(total_fiber_meters / 1000, 2),
        "assets": assets, "cables": cables, "splices": splices,
    }


def _haversine_m(p1, p2) -> float:
    """Distância em metros entre 2 [lat, lng]."""
    import math
    R = 6371000.0
    lat1, lng1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lng2 = math.radians(p2[0]), math.radians(p2[1])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))
