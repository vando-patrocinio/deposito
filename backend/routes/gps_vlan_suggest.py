"""
GPS → OLT/VLAN suggestion (iter211bb)

Para um par de coordenadas, descobre qual SmartOLT atende a região
(usando o prefixo do nome RIO_HUAWEI / MAGE_ZTE / PENHA_HUAWEI / etc),
e retorna a sugestão de VLAN.

Lógica:
  1. Reverse-geocode lat/lng → city/suburb (via Nominatim).
  2. Normaliza nome (sem acento, upper, sem espaços).
  3. Carrega lista de OLTs únicas em `smartolt_onus`. Cada OLT tem nome
     no padrão `<REGIAO>_<VENDOR>` (RIO_HUAWEI etc).
  4. Match: prefixo da OLT bate com city/suburb? → retorna o nome da OLT.
  5. Carrega bairros cadastrados que tenham `olt_name` igual; retorna
     a VLAN deles. Se múltiplos, devolve a lista.
  6. Sem match → fallback VLAN=1 ("sem SmartOLT").

Endpoint:
  GET /api/rede-ia/public/suggest-vlan-from-gps?lat=&lng=&collab_id=
"""
from __future__ import annotations

import asyncio
import logging
import unicodedata
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Query

from core import DEMO_COMPANY_ID, get_current_user
from database import db

logger = logging.getLogger("rede_ia.gps_vlan")
router = APIRouter(prefix="/api/rede-ia", tags=["rede-ia-helpers"])

NOMINATIM_REV = "https://nominatim.openstreetmap.org/reverse"
_FALLBACK_VLAN = 1


def _norm(s: str) -> str:
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(s))
    only = "".join(c for c in nfkd if not unicodedata.combining(c))
    return only.upper().replace(" ", "").replace("-", "")


async def _reverse_geocode(lat: float, lng: float) -> dict:
    """Chama Nominatim com timeout curto."""
    try:
        async with httpx.AsyncClient(timeout=5.0,
                                      headers={"User-Agent": "SmartProv/1.0"}) as c:
            r = await c.get(NOMINATIM_REV, params={
                "format": "json", "lat": lat, "lon": lng,
                "addressdetails": 1, "zoom": 14,
                "accept-language": "pt-BR",
            })
            r.raise_for_status()
            return r.json() or {}
    except Exception as e:
        logger.warning("[gps-vlan] reverse-geocode falhou: %s", e)
        return {}


async def _list_olts(company_id: str) -> list[str]:
    """OLT names únicos cadastrados em smartolt_onus."""
    pipe = [{"$group": {"_id": "$olt_name"}}]
    out = []
    async for r in db.smartolt_onus.aggregate(pipe):
        n = r.get("_id")
        if n:
            out.append(n)
    return out


@router.get("/public/suggest-vlan-from-gps")
async def suggest_vlan_from_gps(
    lat: float = Query(...),
    lng: float = Query(...),
    collab_id: Optional[str] = Query(default=None),
):
    """Sugere VLAN/OLT baseado no GPS — endpoint público (Lousa Mobile)."""
    # Company resolution: tenta via collab_id; senão fallback demo.
    cid = DEMO_COMPANY_ID
    if collab_id:
        col = await db.collaborators.find_one({"id": collab_id}, {"_id": 0, "company_id": 1})
        if col and col.get("company_id"):
            cid = col["company_id"]

    # 1) Reverse geocode + 2) lista OLTs em paralelo
    geo_task = asyncio.create_task(_reverse_geocode(lat, lng))
    olts_task = asyncio.create_task(_list_olts(cid))
    geo, olts = await asyncio.gather(geo_task, olts_task)

    addr = geo.get("address") or {}
    city = addr.get("city") or addr.get("town") or addr.get("municipality") or ""
    suburb = (addr.get("suburb") or addr.get("neighbourhood")
              or addr.get("village") or "")
    display = geo.get("display_name") or ""

    norm_city = _norm(city)
    norm_suburb = _norm(suburb)

    matched_olt: Optional[str] = None
    # Pass 1: prefix bate EXATAMENTE com city OU suburb
    for olt in olts:
        prefix = olt.split("_", 1)[0] if "_" in olt else olt
        np = _norm(prefix)
        if not np:
            continue
        if np == norm_city or np == norm_suburb:
            matched_olt = olt
            break
    # Pass 2: city ou suburb COMEÇA com o prefixo (ex: "RIODEJANEIRO" começa com "RIO")
    if not matched_olt:
        for olt in olts:
            prefix = olt.split("_", 1)[0] if "_" in olt else olt
            np = _norm(prefix)
            if not np or len(np) < 3:
                continue
            if norm_city.startswith(np) or norm_suburb.startswith(np):
                matched_olt = olt
                break

    suggested_vlan = _FALLBACK_VLAN
    bairro_match = None
    if matched_olt:
        # Tenta achar bairros cadastrados pra esta OLT
        bairros_cur = db.bairros_vlan_map.find(
            {"company_id": cid, "olt_name": matched_olt},
            {"_id": 0, "bairro": 1, "vlan": 1, "olt_name": 1, "sigla": 1},
        ).sort("vlan", 1)
        bairros = await bairros_cur.to_list(50)
        # Preferência: bairro cujo nome bate com city/suburb
        for b in bairros:
            nb = _norm(b.get("bairro") or "")
            if nb and (nb == norm_city or nb == norm_suburb):
                bairro_match = b
                break
        if not bairro_match and bairros:
            bairro_match = bairros[0]
        if bairro_match and bairro_match.get("vlan"):
            suggested_vlan = int(bairro_match["vlan"])

    return {
        "lat": lat, "lng": lng,
        "city": city, "suburb": suburb,
        "matched_olt": matched_olt,
        "suggested_vlan": suggested_vlan,
        "bairro_match": bairro_match,
        "reason": (
            "smartolt"  if matched_olt and bairro_match
            else "olt-without-bairro" if matched_olt
            else "no-match-fallback-vlan-1"
        ),
    }


@router.get("/suggest-vlan-from-gps")
async def suggest_vlan_authenticated(
    lat: float = Query(...),
    lng: float = Query(...),
    user: dict = Depends(get_current_user),
):
    """Variante autenticada (admin/gestor) — apenas reutiliza a lógica pública."""
    _ = user  # apenas garante auth
    return await suggest_vlan_from_gps(lat=lat, lng=lng, collab_id=None)
