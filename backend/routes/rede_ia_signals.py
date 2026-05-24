"""rede_ia_signals.py — Mancha de clientes com sinal ruim no mapa.

Endpoint:
  - GET /api/rede-ia/map/signal-points?status=warning|critical|all&geocode_max=15
        Retorna lista de pontos (lat, lng, status, signal_dbm, label) das
        ONUs SmartOLT com sinal Warning/Critical.
        Geocodifica on-demand até `geocode_max` ONUs sem coords.

Estratégia de geocoding (ONUs raramente têm lat/lng cadastrado):
  1. Se ONU tem `latitude`/`longitude` cacheado, usa.
  2. Senão, tenta parsing do nome da ONU (padrão da empresa:
     "RuaApto_Numero_..." ou "Bairro_Numero_Nome") e geocoda.
  3. Salva lat/lng no próprio `smartolt_onus` (cache permanente).

Worker noturno reaproveita o do lousa_map (não recriamos worker novo —
chamamos o batch periodicamente via cron já existente).
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core import DEMO_COMPANY_ID, get_current_user, geocode_address, is_super_admin
from database import db

logger = logging.getLogger("ponto.rede_ia_signals")
router = APIRouter(prefix="/api/rede-ia/map", tags=["rede-ia-signals"])


def _cid(user: dict) -> str:
    if is_super_admin(user):
        return (user.get("_active_company") or user.get("company_id")
                or DEMO_COMPANY_ID)
    return user.get("company_id") or DEMO_COMPANY_ID


def _parse_onu_address(onu: dict, company_default_city: str = "") -> str:
    """Tenta extrair um endereço pesquisável do nome da ONU.

    Padrões reais observados na base demo:
      - "ComCoelho811_Ap201_LuizCarlos" → Coelho 811, Comendador Coelho
      - "CapCruz1045_Cs05_Carl9s"       → Cruz 1045, Capitão Cruz
      - "RodNova120_Ronan"              → Nova 120
    Estratégia: pega a 1ª parte (até o "_"), separa letras de números e
    retorna "{rua-aproximada} {numero}, {cidade}".
    """
    name = (onu.get("name") or "").strip()
    if not name:
        return ""
    parts = name.split("_")
    first = parts[0]
    # Separa letras maiúsculas seguidas de número
    m = re.match(r"([A-ZÁÉÍÓÚÂÊÔÃÕÇa-záéíóúâêôãõç]+)(\d+)", first)
    if not m:
        return name + (", " + company_default_city if company_default_city else "")
    street_token, number = m.group(1), m.group(2)
    # Insere espaços antes de cada maiúscula no token (camelCase → "Cap Cruz")
    street_human = re.sub(r"(?<!^)(?=[A-Z])", " ", street_token)
    parts_out = [f"Rua {street_human} {number}"]
    if company_default_city:
        parts_out.append(company_default_city)
    return ", ".join(parts_out)


async def _company_default_city(cid: str) -> str:
    """Retorna a cidade mais frequente nos endereços dos subscribers
    da empresa — usada como cidade default pra geocoding de ONUs."""
    try:
        pipeline = [
            {"$match": {"company_id": cid,
                         "city": {"$nin": [None, ""]}}},
            {"$group": {"_id": "$city", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}},
            {"$limit": 1},
        ]
        async for d in db.subscriber_addresses.aggregate(pipeline):
            return d["_id"]
    except Exception:
        pass
    return ""


async def _geocode_onu(onu: dict, default_city: str) -> Optional[tuple[float, float]]:
    """Geocoda 1 ONU e persiste no banco. Best-effort."""
    addr = _parse_onu_address(onu, default_city)
    if not addr:
        return None
    try:
        res = await geocode_address(addr)
        await db.smartolt_onus.update_one(
            {"unique_external_id": onu["unique_external_id"]},
            {"$set": {
                "latitude": res.lat,
                "longitude": res.lng,
                "geocoded_at": datetime.now(timezone.utc).isoformat(),
                "geocoded_address": res.display_name,
            }},
        )
        return res.lat, res.lng
    except HTTPException as e:
        await db.smartolt_onus.update_one(
            {"unique_external_id": onu["unique_external_id"]},
            {"$set": {
                "geocode_failed_at": datetime.now(timezone.utc).isoformat(),
                "geocode_failed_reason": str(e.detail)[:200],
            }},
        )
        return None
    except Exception as e:
        logger.info("[signals] geocode err %s: %s",
                    onu.get("unique_external_id"), e)
        return None


@router.get("/signal-points")
async def signal_points(
    status: str = Query(default="all",
                        pattern="^(all|warning|critical)$"),
    geocode_max: int = Query(default=15, ge=0, le=60),
    user: dict = Depends(get_current_user),
):
    """Pontos no mapa de ONUs com sinal ruim/crítico.

    Retorno: pontos pequenos pra desenhar "mancha" de clientes com
    sinal degradado/crítico.
    """
    cid = _cid(user)

    # Filtro de signal_text
    if status == "warning":
        text_filter = {"$in": ["Warning"]}
    elif status == "critical":
        text_filter = {"$in": ["Critical"]}
    else:
        text_filter = {"$in": ["Warning", "Critical"]}

    raw = await db.smartolt_onus.find(
        {"company_id": cid, "signal_text": text_filter},
        {"_id": 0, "unique_external_id": 1, "name": 1, "sn": 1,
         "signal_text": 1, "signal_1310": 1, "signal_1490": 1,
         "latitude": 1, "longitude": 1, "status": 1, "olt_name": 1,
         "zone_name": 1, "geocode_failed_at": 1,
         "onu_type_name": 1},
    ).to_list(3000)

    # Geocoding on-demand — só primeiros N sem coords (e que não falharam recente)
    geocoded_now = 0
    if geocode_max > 0:
        default_city = await _company_default_city(cid)
        cutoff = (datetime.now(timezone.utc).timestamp() - 86400)
        to_gc = []
        for o in raw:
            if o.get("latitude") and o.get("longitude"):
                continue
            failed = o.get("geocode_failed_at")
            if failed:
                try:
                    fdt = datetime.fromisoformat(failed).timestamp()
                    if fdt > cutoff:
                        continue  # falhou há <24h
                except Exception:
                    pass
            to_gc.append(o)
        for o in to_gc[:geocode_max]:
            coords = await _geocode_onu(o, default_city)
            if coords:
                o["latitude"], o["longitude"] = coords
                geocoded_now += 1
            await asyncio.sleep(1.0)  # Nominatim 1 req/s

    # Constrói pontos finais
    points: List[Dict[str, Any]] = []
    for o in raw:
        lat = o.get("latitude")
        lng = o.get("longitude")
        if not (lat and lng):
            continue
        points.append({
            "id": o["unique_external_id"],
            "lat": float(lat),
            "lng": float(lng),
            "status": (o.get("signal_text") or "").lower(),
            "signal_1490": o.get("signal_1490"),
            "signal_1310": o.get("signal_1310"),
            "name": o.get("name") or "",
            "sn": o.get("sn") or o.get("unique_external_id"),
            "olt": o.get("olt_name") or "",
            "zone": o.get("zone_name") or "",
            "model": o.get("onu_type_name") or "",
            "online": (o.get("status") == "Online"),
        })

    return {
        "points": points,
        "stats": {
            "total_with_issue": len(raw),
            "warning": sum(1 for o in raw if o.get("signal_text") == "Warning"),
            "critical": sum(1 for o in raw if o.get("signal_text") == "Critical"),
            "with_coords": len(points),
            "without_coords": len(raw) - len(points),
            "geocoded_this_request": geocoded_now,
        },
    }


@router.post("/signal-points/geocode-batch")
async def signal_points_geocode_batch(
    max_count: int = Query(default=60, ge=1, le=300),
    user: dict = Depends(get_current_user),
):
    """Batch geocode pra acelerar o cache. Apenas staff."""
    cid = _cid(user)
    role = (user.get("role") or "").lower()
    if role not in ("gestor", "administrador") and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador.")

    cutoff = (datetime.now(timezone.utc).timestamp() - 86400)
    cur = db.smartolt_onus.find(
        {
            "company_id": cid,
            "signal_text": {"$in": ["Warning", "Critical"]},
            "$or": [
                {"latitude": None},
                {"latitude": {"$exists": False}},
            ],
        },
        {"_id": 0, "unique_external_id": 1, "name": 1,
         "geocode_failed_at": 1},
    )
    pending: List[dict] = []
    async for o in cur:
        if len(pending) >= max_count:
            break
        failed = o.get("geocode_failed_at")
        if failed:
            try:
                fdt = datetime.fromisoformat(failed).timestamp()
                if fdt > cutoff:
                    continue
            except Exception:
                pass
        pending.append(o)

    default_city = await _company_default_city(cid)
    ok = 0
    fail = 0
    for o in pending:
        if await _geocode_onu(o, default_city):
            ok += 1
        else:
            fail += 1
        await asyncio.sleep(1.0)

    remaining = await db.smartolt_onus.count_documents({
        "company_id": cid,
        "signal_text": {"$in": ["Warning", "Critical"]},
        "$or": [{"latitude": None}, {"latitude": {"$exists": False}}],
    })
    return {"processed": ok + fail, "geocoded": ok, "failed": fail,
            "remaining_estimate": remaining}


# ---------------------------------------------------------------------------
# Outage Detector — trigger manual + status
# ---------------------------------------------------------------------------
@router.post("/outage/detect-now")
async def outage_detect_now(user: dict = Depends(get_current_user)):
    """Dispara detecção de outage agora (em vez de esperar o worker de 10min).
    Apenas staff. Útil pra debug ou após manutenção em campo."""
    cid = _cid(user)
    role = (user.get("role") or "").lower()
    if role not in ("gestor", "administrador") and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador.")
    from services.rede_ia_outage_detector import detect_now
    return await detect_now(cid)


@router.get("/outage/active")
async def outage_active(user: dict = Depends(get_current_user)):
    """Lista outages atualmente ABERTOS (auto-gerados pelo detector)."""
    cid = _cid(user)
    items = await db.tickets.find(
        {"company_id": cid, "type": "OUTAGE_AUTO",
         "status": {"$in": ["pendente", "em_execucao", "agendada", "aberta"]}},
        {"_id": 0, "id": 1, "outage_olt": 1, "outage_zone": 1,
         "outage_count_open": 1, "outage_count_current": 1,
         "outage_avg_signal": 1, "created_at": 1,
         "latitude": 1, "longitude": 1, "outage_cluster_key": 1},
    ).sort("created_at", -1).to_list(100)
    return {"items": items, "count": len(items)}
