"""lousa_map.py — Mapa de serviços (bolhas) com pinos por técnico.

Endpoints:
  - GET  /api/lousa/map/services?period=today|yesterday|7d|custom&start=&end=&status=open|closed|all
        → Retorna tickets com lat/lng + agrupamento por técnico (cor + label).
        Geocoda on-demand os tickets sem coords (max 10 por request).
  - POST /api/lousa/map/geocode-now → trigger manual de geocoding em background.

Worker:
  - `start_geocode_worker()` roda a cada 60 min: pega tickets dos últimos 30
    dias sem `latitude/longitude` e tenta geocodar (rate-limit Nominatim:
    1 req/s, então no máximo 60 tickets por ciclo).

Schema usado:
  tickets:
    - client_snapshot.address      (texto livre)
    - client_snapshot.neighborhood (bairro)
    - client_snapshot.city         (cidade)
    - latitude / longitude         (preenchido sob demanda)
    - assigned_collaborator_id     (técnico atribuído)
    - status                       (pendente, em_execucao, executada, …)
    - scheduled_time / opened_at / closed_at
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core import DEMO_COMPANY_ID, get_current_user, geocode_address, is_super_admin
from database import db

logger = logging.getLogger("ponto.lousa_map")
router = APIRouter(prefix="/api/lousa/map", tags=["lousa-map"])

# Paleta de 16 cores MUITO distintas (ColorBrewer Qualitative + ajustes).
# Critério: cada cor é facilmente diferenciada da próxima a 10m de distância.
# Evita pares próximos (azul/ciano, vermelho/rosa, verde/lima) no índice
# adjacente — usa wrap-around hash pra distribuir.
COLLAB_COLORS = [
    "#e6194b",  # vermelho carmim
    "#3cb44b",  # verde puro
    "#4363d8",  # azul royal
    "#f58231",  # laranja queimado
    "#911eb4",  # roxo
    "#42d4f4",  # ciano
    "#f032e6",  # magenta
    "#9a6324",  # marrom
    "#800000",  # bordô
    "#469990",  # teal escuro
    "#808000",  # oliva
    "#000075",  # azul marinho
    "#e6beff",  # lavanda
    "#aaffc3",  # menta
    "#ffd8b1",  # pêssego
    "#fabed4",  # rosa claro
]


def _color_for(collab_id: Optional[str]) -> str:
    """Cor determinística por collaborator_id — hash MD5 (estável).
    NOTA: pode dar colisões na paleta quando há muitos técnicos.
    A função `_assign_colors_by_order` abaixo é preferida quando temos
    a lista completa de colaboradores no contexto.
    """
    if not collab_id:
        return "#64748b"  # cinza pra não atribuído
    h = int(hashlib.md5(collab_id.encode("utf-8")).hexdigest(), 16)
    return COLLAB_COLORS[h % len(COLLAB_COLORS)]


def _assign_colors_by_order(collab_ids: List[str]) -> Dict[str, str]:
    """Atribui cores SEQUENCIALMENTE pela ordem da lista (estável).
    Garante que os N primeiros técnicos tenham cores 100% distintas
    (sem colisões da paleta como acontece com hash).
    """
    out: Dict[str, str] = {}
    for i, cid in enumerate(sorted(set(collab_ids))):
        out[cid] = COLLAB_COLORS[i % len(COLLAB_COLORS)]
    return out


def _cid(user: dict) -> str:
    if is_super_admin(user):
        return user.get("_active_company") or user.get("company_id") or DEMO_COMPANY_ID
    return user.get("company_id") or DEMO_COMPANY_ID


def _period_range(period: str, start: Optional[str],
                  end: Optional[str]) -> tuple[datetime, datetime]:
    """Resolve a janela de tempo a partir de `period` + start/end opcional."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "today":
        return today_start, today_start + timedelta(days=1)
    if period == "yesterday":
        return today_start - timedelta(days=1), today_start
    if period == "7d":
        return today_start - timedelta(days=7), today_start + timedelta(days=1)
    if period == "30d":
        return today_start - timedelta(days=30), today_start + timedelta(days=1)
    if period == "custom" and start and end:
        try:
            s = datetime.fromisoformat(start)
            e = datetime.fromisoformat(end)
            return s, e + timedelta(days=1)
        except Exception as ex:
            raise HTTPException(400, f"start/end inválidos: {ex}")
    # default: hoje
    return today_start, today_start + timedelta(days=1)


def _ticket_address_str(t: dict) -> str:
    """Concatena partes do endereço do ticket pra geocoding."""
    snap = t.get("client_snapshot") or {}
    parts = []
    addr = snap.get("address") or t.get("address") or ""
    if addr:
        parts.append(str(addr).strip())
    bairro = snap.get("neighborhood") or t.get("neighborhood") or ""
    if bairro:
        parts.append(str(bairro).strip())
    city = snap.get("city") or t.get("city") or ""
    if city:
        parts.append(str(city).strip())
    if not parts:
        return ""
    return ", ".join([p for p in parts if p])


async def _geocode_ticket(t: dict) -> Optional[tuple[float, float]]:
    """Tenta geocodar um ticket e persistir no banco. Retorna (lat, lng)
    ou None. Best-effort — falhas são silenciosas."""
    addr = _ticket_address_str(t)
    if not addr:
        return None
    try:
        res = await geocode_address(addr)
        await db.tickets.update_one(
            {"id": t["id"]},
            {"$set": {
                "latitude": res.lat,
                "longitude": res.lng,
                "geocoded_at": datetime.now(timezone.utc).isoformat(),
                "geocoded_address": res.display_name,
            }},
        )
        return res.lat, res.lng
    except HTTPException as e:
        logger.info("[lousa-map] geocode skip %s: %s",
                    t.get("id"), e.detail)
        # Marca como tentado pra não retentar sem stop
        await db.tickets.update_one(
            {"id": t["id"]},
            {"$set": {"geocode_failed_at": datetime.now(timezone.utc).isoformat(),
                      "geocode_failed_reason": str(e.detail)[:200]}},
        )
        return None
    except Exception as e:
        logger.warning("[lousa-map] geocode err %s: %s", t.get("id"), e)
        return None


# ---------------------------------------------------------------------------
# Endpoint principal: mapa de serviços
# ---------------------------------------------------------------------------
@router.get("/services")
async def map_services(
    period: str = Query(default="today",
                        pattern="^(today|yesterday|7d|30d|custom)$"),
    start: Optional[str] = None,
    end: Optional[str] = None,
    status: str = Query(default="all",
                        pattern="^(all|open|closed)$"),
    geocode_max: int = Query(default=10, ge=0, le=30),
    user: dict = Depends(get_current_user),
):
    """Retorna tickets do período com lat/lng + cor por técnico.

    Geocodifica até `geocode_max` tickets sem coords on-demand (1s/req).
    O restante é geocodado pelo worker noturno.
    """
    cid = _cid(user)
    start_dt, end_dt = _period_range(period, start, end)

    # Filtro Mongo: tickets do período pelo scheduled_time (mais robusto)
    status_map = {
        "open": {"$in": ["pendente", "em_execucao", "agendada"]},
        "closed": {"$in": ["executada", "cancelada", "finalizada"]},
    }
    filt: Dict[str, Any] = {"company_id": cid}
    # Por scheduled_time (ISO) — compara strings funciona pq formato é Z-aware
    filt["scheduled_time"] = {
        "$gte": start_dt.isoformat(),
        "$lt": end_dt.isoformat(),
    }
    if status in status_map:
        filt["status"] = status_map[status]

    proj = {
        "_id": 0,
        "id": 1, "type": 1, "priority": 1,
        "status": 1, "scheduled_time": 1,
        "assigned_collaborator_id": 1,
        "client_snapshot": 1,
        "latitude": 1, "longitude": 1,
        "atlaz_protocolo": 1, "atlaz_filial": 1,
        "opened_at": 1, "closed_at": 1,
        "outcome": 1, "geocoded_address": 1,
    }
    raw = await db.tickets.find(filt, proj).sort("scheduled_time", 1).to_list(1000)
    total = len(raw)

    # Geocoda on-demand os primeiros N sem coords
    geocoded_now = 0
    if geocode_max > 0:
        to_geocode = [t for t in raw
                      if not (t.get("latitude") and t.get("longitude"))]
        # Respeita rate-limit Nominatim: 1 req/s
        for t in to_geocode[:geocode_max]:
            coords = await _geocode_ticket(t)
            if coords:
                t["latitude"], t["longitude"] = coords
                geocoded_now += 1
            await asyncio.sleep(1.0)

    # Resolve nomes/cores dos colaboradores
    collab_ids = {t.get("assigned_collaborator_id") for t in raw
                  if t.get("assigned_collaborator_id")}
    collab_map: Dict[str, dict] = {}
    if collab_ids:
        async for c in db.collaborators.find(
            {"id": {"$in": list(collab_ids)}, "company_id": cid},
            {"_id": 0, "id": 1, "name": 1, "avatar_url": 1},
        ):
            collab_map[c["id"]] = c

    # Atribui cores sequencialmente baseado em ordem alfabética do NOME do
    # colaborador (estável + sem colisões da paleta — diferente do hash MD5).
    sorted_collabs = sorted(
        collab_map.values(),
        key=lambda c: (c.get("name") or "").lower(),
    )
    color_by_collab: Dict[str, str] = {}
    for i, c in enumerate(sorted_collabs):
        color_by_collab[c["id"]] = COLLAB_COLORS[i % len(COLLAB_COLORS)]

    # Constrói payload
    pins: List[Dict[str, Any]] = []
    skipped_no_coords = 0
    for t in raw:
        lat = t.get("latitude")
        lng = t.get("longitude")
        if not (lat and lng):
            skipped_no_coords += 1
            continue
        snap = t.get("client_snapshot") or {}
        cid_collab = t.get("assigned_collaborator_id")
        collab = collab_map.get(cid_collab) if cid_collab else None
        pins.append({
            "id": t.get("id"),
            "lat": float(lat),
            "lng": float(lng),
            "color": color_by_collab.get(cid_collab) or "#64748b",
            "collaborator_id": cid_collab,
            "collaborator_name": (collab.get("name") if collab
                                  else "Sem técnico"),
            "client_name": snap.get("name") or "",
            "address": snap.get("address") or "",
            "neighborhood": snap.get("neighborhood") or "",
            "city": snap.get("city") or "",
            "phone": snap.get("phone") or "",
            "status": t.get("status"),
            "type": t.get("type"),
            "priority": t.get("priority"),
            "scheduled_time": t.get("scheduled_time"),
            "atlaz_protocolo": t.get("atlaz_protocolo"),
            "atlaz_filial": t.get("atlaz_filial"),
        })

    # Legenda: agrupa por colaborador → cor + contagem
    legend_map: Dict[str, dict] = {}
    for p in pins:
        key = p["collaborator_id"] or "_unassigned"
        if key not in legend_map:
            legend_map[key] = {
                "collaborator_id": p["collaborator_id"],
                "collaborator_name": p["collaborator_name"],
                "color": p["color"],
                "count": 0,
            }
        legend_map[key]["count"] += 1
    legend = sorted(legend_map.values(),
                    key=lambda x: -x["count"])

    # Centro do mapa: média dos pins ou Brasil default
    if pins:
        center_lat = sum(p["lat"] for p in pins) / len(pins)
        center_lng = sum(p["lng"] for p in pins) / len(pins)
    else:
        center_lat, center_lng = -15.78, -47.93  # Brasília

    return {
        "pins": pins,
        "legend": legend,
        "stats": {
            "total_tickets": total,
            "with_coords": len(pins),
            "without_coords": skipped_no_coords,
            "geocoded_this_request": geocoded_now,
            "period": period,
            "status": status,
        },
        "center": {"lat": center_lat, "lng": center_lng},
    }


@router.post("/geocode-now")
async def geocode_now(
    max_count: int = Query(default=60, ge=1, le=500),
    user: dict = Depends(get_current_user),
):
    """Dispara geocoding em batch (bloqueante, mas rápido pra batches pequenos).
    Útil pro gestor 'turbinar' o cache antes da reunião matinal.
    """
    cid = _cid(user)
    role = (user.get("role") or "").lower()
    if role not in ("gestor", "administrador", "auditor", "financeiro") \
            and not is_super_admin(user):
        raise HTTPException(403, "Apenas staff pode disparar geocoding em batch.")

    # Tickets sem coords que NÃO falharam ainda (ou falharam há mais de 24h)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    cur = db.tickets.find(
        {
            "company_id": cid,
            "$or": [
                {"latitude": None},
                {"latitude": {"$exists": False}},
            ],
            "$and": [{
                "$or": [
                    {"geocode_failed_at": {"$exists": False}},
                    {"geocode_failed_at": {"$lt": cutoff}},
                ]
            }],
        },
        {"_id": 0, "id": 1, "client_snapshot": 1, "address": 1,
         "neighborhood": 1, "city": 1},
    ).limit(max_count)
    pending = await cur.to_list(max_count)

    ok = 0
    fail = 0
    for t in pending:
        coords = await _geocode_ticket(t)
        if coords:
            ok += 1
        else:
            fail += 1
        await asyncio.sleep(1.0)  # Nominatim 1 req/s

    return {
        "processed": ok + fail,
        "geocoded": ok,
        "failed": fail,
        "remaining_estimate": await db.tickets.count_documents({
            "company_id": cid,
            "$or": [{"latitude": None},
                    {"latitude": {"$exists": False}}],
        }),
    }


# ---------------------------------------------------------------------------
# Search endpoint: busca livre de endereço (até 5 sugestões, Brasil)
# ---------------------------------------------------------------------------
@router.get("/search-address")
async def search_address(
    q: str = Query(..., min_length=3, max_length=200),
    user: dict = Depends(get_current_user),
):
    """Busca de endereço livre — retorna até 5 candidatos via Nominatim.

    Usado pra "Pesquisar endereço" no mapa de serviços: atendente cola um
    endereço informado pelo cliente, escolhe o mais próximo do que o
    cliente disse e o mapa centraliza ali com um pino azul temporário.

    Limites:
      - q mín 3 chars
      - Resultados restritos a Brasil
      - Cache local em `geocode_cache` (TTL 7d) — economiza Nominatim
    """
    import hashlib as _hash
    import httpx as _httpx
    qn = q.strip()
    if len(qn) < 3:
        raise HTTPException(400, "Mínimo 3 caracteres.")

    # Cache: chave = sha1(q minúscula)
    qkey = _hash.sha1(qn.lower().encode("utf-8")).hexdigest()
    cache_doc = await db.geocode_cache.find_one(
        {"_id": qkey}, {"_id": 0})
    if cache_doc:
        # TTL 7d
        ts = cache_doc.get("ts")
        try:
            tdt = datetime.fromisoformat(ts)
            if (datetime.now(timezone.utc) - tdt).days < 7:
                return {"results": cache_doc.get("results", []),
                        "cached": True}
        except Exception:
            pass

    # Nominatim: até 5 candidatos
    user_agent = "SmartProv-LousaMap/1.0 (compat; +smartprov.app)"
    try:
        async with _httpx.AsyncClient(
            timeout=10.0,
            headers={"User-Agent": user_agent},
        ) as c:
            r = await c.get("https://nominatim.openstreetmap.org/search",
                            params={
                                "q": qn,
                                "format": "json",
                                "limit": 5,
                                "addressdetails": 1,
                                "countrycodes": "br",
                                "accept-language": "pt-BR",
                            })
            r.raise_for_status()
            data = r.json() or []
    except Exception as e:
        logger.warning("[lousa-map] search-address err: %s", e)
        raise HTTPException(502, f"Falha ao consultar Nominatim: {e}")

    results = []
    for item in data:
        addr = item.get("address") or {}
        # Monta uma linha de display curta (sem verbose do "display_name")
        parts = [
            addr.get("road") or "",
            addr.get("house_number") or "",
            addr.get("suburb") or addr.get("neighbourhood") or "",
            addr.get("city") or addr.get("town")
                or addr.get("municipality") or "",
            addr.get("state") or "",
        ]
        short = ", ".join([p for p in parts if p]) or item.get("display_name")
        try:
            results.append({
                "lat": float(item["lat"]),
                "lng": float(item["lon"]),
                "label": short,
                "full": item.get("display_name", ""),
                "type": item.get("type") or item.get("class") or "",
                "neighborhood": addr.get("suburb")
                                or addr.get("neighbourhood") or "",
                "city": addr.get("city") or addr.get("town")
                        or addr.get("municipality") or "",
                "state": addr.get("state") or "",
            })
        except (KeyError, ValueError):
            continue

    # Salva cache
    try:
        await db.geocode_cache.update_one(
            {"_id": qkey},
            {"$set": {"results": results, "q": qn,
                       "ts": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    except Exception:
        pass

    return {"results": results, "cached": False}


# ---------------------------------------------------------------------------
# Worker: geocoda em background a cada 60 min
# ---------------------------------------------------------------------------
_worker_task: Optional[asyncio.Task] = None
WORKER_INTERVAL_SEC = 3600  # 1h
WORKER_BATCH_SIZE = 60       # max 60 tickets/ciclo (60s @ 1 req/s)


async def _worker_loop() -> None:
    """Loop noturno: geocodifica tickets sem coords (todos os tenants)."""
    logger.info("[lousa-map] worker iniciado (interval=%ds, batch=%d)",
                WORKER_INTERVAL_SEC, WORKER_BATCH_SIZE)
    # Primeira execução em 5min pra deixar app subir tranquilo
    await asyncio.sleep(300)
    while True:
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            cur = db.tickets.find(
                {
                    "$or": [
                        {"latitude": None},
                        {"latitude": {"$exists": False}},
                    ],
                    "$and": [{
                        "$or": [
                            {"geocode_failed_at": {"$exists": False}},
                            {"geocode_failed_at": {"$lt": cutoff}},
                        ]
                    }],
                },
                {"_id": 0, "id": 1, "client_snapshot": 1,
                 "address": 1, "neighborhood": 1, "city": 1},
            ).sort("scheduled_time", -1).limit(WORKER_BATCH_SIZE)
            batch = await cur.to_list(WORKER_BATCH_SIZE)
            if not batch:
                logger.info("[lousa-map] worker — nenhum ticket pra geocodar")
            else:
                ok = 0
                for t in batch:
                    if await _geocode_ticket(t):
                        ok += 1
                    await asyncio.sleep(1.0)
                logger.info("[lousa-map] worker batch ok=%d/%d", ok, len(batch))
        except Exception as e:
            logger.exception("[lousa-map] worker err: %s", e)
        await asyncio.sleep(WORKER_INTERVAL_SEC)


async def start_worker() -> None:
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker_loop())


async def stop_worker() -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
