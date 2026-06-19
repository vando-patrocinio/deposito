"""Oportunidades IA — busca de prospects (empresas e condomínios) em raio
geográfico ao redor do escritório, usando dados públicos do OpenStreetMap
e análise por Claude Sonnet 4.6 via OpenRouter.

Fluxo:
  1. Geocodifica endereço base via Nominatim (OSM, sem chave)
  2. Busca prédios residenciais/comerciais via Overpass API em raio km
  3. Filtra e agrega (estima nº de unidades por levels × footprint)
  4. Envia resumo ao Claude pra ranquear oportunidades

Endpoints:
  - POST /api/customer/loyalty-ai/nearby-opportunities/scan
    body: { address?, radius_km?, force? }
  - GET  /api/customer/loyalty-ai/nearby-opportunities → último resultado

iter215m — não usa Emergent LLM Key; usa motor_ia.chat_completion (OpenRouter).
"""
from __future__ import annotations


from services.exception_sanitizer import safe_detail  # SECURITY_LOCK ART.13
NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, require_role
from database import db
from services.motor_ia import chat_completion

logger = logging.getLogger("ponto.loyalty_opp_ai")
router = APIRouter(
    prefix="/api/customer/loyalty-ai/nearby-opportunities",
    tags=["loyalty-ai-opportunities"],
)

DEFAULT_ADDRESS = "Av. Vicente de Carvalho, 909, Rio de Janeiro, RJ"
DEFAULT_RADIUS_KM = 5.0
MODEL_NAME = "anthropic/claude-sonnet-4.6"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "SmartProv-ISP-Loyalty/1.0 (admin@smartprov.com)"


async def _geocode(address: str) -> tuple[float, float, str]:
    """Geocodifica endereço via Nominatim. Retorna (lat, lng, display_name)."""
    async with httpx.AsyncClient(timeout=20) as cli:
        r = await cli.get(NOMINATIM_URL, params={
            "q": address, "format": "json", "limit": 1, "addressdetails": 1,
        }, headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR"})
    if r.status_code >= 400:
        raise HTTPException(502, f"Nominatim HTTP {r.status_code}")
    data = r.json()
    if not data:
        raise HTTPException(404, f"Endereço não encontrado: {address}")
    item = data[0]
    return float(item["lat"]), float(item["lon"]), item.get("display_name", "")


def _build_overpass_query(lat: float, lon: float, radius_m: int) -> str:
    """Query Overpass QL pra residências + comerciais + escolas/hospitais."""
    return f"""[out:json][timeout:60];
(
  way["building"~"apartments|residential|dormitory"](around:{radius_m},{lat},{lon});
  way["building"="commercial"](around:{radius_m},{lat},{lon});
  way["building"="office"](around:{radius_m},{lat},{lon});
  way["building"="industrial"](around:{radius_m},{lat},{lon});
  way["building"="retail"](around:{radius_m},{lat},{lon});
  way["amenity"~"hospital|clinic|school|university|college"](around:{radius_m},{lat},{lon});
  way["shop"="mall"](around:{radius_m},{lat},{lon});
  node["office"](around:{radius_m},{lat},{lon});
);
out tags center 500;"""


async def _overpass(lat: float, lon: float, radius_m: int) -> list[dict]:
    """Executa query Overpass e retorna lista de elementos."""
    query = _build_overpass_query(lat, lon, radius_m)
    async with httpx.AsyncClient(timeout=90) as cli:
        r = await cli.post(OVERPASS_URL, data={"data": query},
                            headers={"User-Agent": USER_AGENT})
    if r.status_code >= 400:
        raise HTTPException(502, f"Overpass HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    return data.get("elements") or []


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em km entre 2 pontos (haversine)."""
    from math import radians, sin, cos, asin, sqrt
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (sin(dlat / 2) ** 2
         + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2)
    return 2 * 6371 * asin(sqrt(a))


def _classify_element(el: dict, origin: tuple[float, float]) -> Optional[dict]:
    """Normaliza um elemento Overpass para dict de prospect."""
    tags = el.get("tags") or {}
    name = (tags.get("name") or "").strip()
    if not name or len(name) < 3:
        return None
    bld = (tags.get("building") or "").lower()
    amen = (tags.get("amenity") or "").lower()
    shop = (tags.get("shop") or "").lower()
    office = (tags.get("office") or "").lower()
    center = el.get("center") or {}
    lat, lon = center.get("lat"), center.get("lon")
    if lat is None and el.get("type") == "node":
        lat, lon = el.get("lat"), el.get("lon")
    if lat is None or lon is None:
        return None
    dist = round(_haversine_km(origin[0], origin[1], lat, lon), 2)

    # Categorização
    category = "outros"
    estimated_units = None
    levels = None
    try:
        levels = int(tags.get("building:levels") or 0) or None
    except (ValueError, TypeError):
        pass

    if bld in ("apartments", "residential", "dormitory"):
        category = "condominio_residencial"
        # Estimativa de unidades: levels × 4 apt/andar (média RJ urbano)
        if levels:
            estimated_units = levels * 4
    elif bld == "commercial" or office:
        category = "predio_comercial"
        if levels:
            estimated_units = levels  # salas comerciais
    elif bld == "industrial":
        category = "industrial"
    elif bld == "retail" or shop == "mall":
        category = "varejo_shopping"
    elif amen in ("hospital", "clinic"):
        category = "saude"
    elif amen in ("school", "university", "college"):
        category = "educacao"

    return {
        "name": name,
        "category": category,
        "building_type": bld or None,
        "amenity": amen or None,
        "shop": shop or None,
        "office_type": office or None,
        "levels": levels,
        "estimated_units": estimated_units,
        "address": (
            f"{tags.get('addr:street', '')} {tags.get('addr:housenumber', '')}".strip()
            or None
        ),
        "city": tags.get("addr:city"),
        "phone": tags.get("phone") or tags.get("contact:phone"),
        "website": tags.get("website") or tags.get("contact:website"),
        "lat": lat,
        "lon": lon,
        "distance_km": dist,
        "operator": tags.get("operator"),
    }


def _build_ai_prompt(origin_addr: str, radius_km: float,
                     prospects: list[dict]) -> str:
    # Agrega por categoria pra dar contexto
    by_cat: dict[str, int] = {}
    for p in prospects:
        by_cat[p["category"]] = by_cat.get(p["category"], 0) + 1

    # Top 50 condomínios maiores (com units estimadas)
    condos = sorted(
        [p for p in prospects if p["category"] == "condominio_residencial"],
        key=lambda x: -(x.get("estimated_units") or 0),
    )[:30]
    # Empresas relevantes
    empresas = [p for p in prospects if p["category"] in (
        "predio_comercial", "industrial", "varejo_shopping",
        "saude", "educacao",
    )][:50]

    return f"""Você é um especialista em PROSPECÇÃO B2B/B2C pra provedor de
internet em Rio de Janeiro. Analise as oportunidades reais coletadas via
OpenStreetMap num raio de {radius_km}km do endereço:

**Origem:** {origin_addr}

**Resumo da coleta** (total: {len(prospects)} prospects):
{json.dumps(by_cat, indent=2, ensure_ascii=False)}

**TOP 30 condomínios residenciais (ordenados por unidades estimadas):**
{json.dumps(condos, indent=2, ensure_ascii=False)}

**Empresas/instituições relevantes (até 50):**
{json.dumps(empresas, indent=2, ensure_ascii=False)}

# RESPOSTA EM JSON (sem markdown, sem ```json):

{{
  "summary": "Resumo executivo da oportunidade na região em 2-3 frases.",
  "market_score": <0-100>,
  "top_condominios": [
    {{
      "name": "string",
      "address_or_distance": "string",
      "estimated_units": <int|null>,
      "priority": "alta|media|baixa",
      "rationale": "por que essa é uma boa oportunidade",
      "approach_strategy": "como abordar (síndico, MDU, oferta corporate, etc)",
      "estimated_revenue_potential": "ex: R$5k-10k MRR"
    }}
  ],
  "top_empresas": [
    {{
      "name": "string",
      "category": "saude|educacao|comercial|industrial|varejo",
      "address_or_distance": "string",
      "priority": "alta|media|baixa",
      "rationale": "string",
      "approach_strategy": "string",
      "estimated_revenue_potential": "string"
    }}
  ],
  "regional_insights": [
    "insight 1 sobre a região (ex: 'concentração alta de prédios em Penha')",
    "insight 2"
  ],
  "action_plan_30d": [
    {{"week": 1, "focus": "...", "actions": ["...", "..."]}},
    {{"week": 2, "focus": "...", "actions": ["..."]}},
    {{"week": 3, "focus": "...", "actions": ["..."]}},
    {{"week": 4, "focus": "...", "actions": ["..."]}}
  ]
}}

REGRAS:
- top_condominios: filtre só os com estimated_units >= 100 ou que pareçam grandes.
  Se não houver dados de unidades, use o nome + nível pra inferir porte.
- top_empresas: máx 8, foque em B2B real (escolas, hospitais, shoppings, etc).
- Seja CONCRETO: cite os nomes EXATOS retornados nos dados, sem inventar.
- Foque em ISP fibra/MDU residencial e dedicado corporate.
"""


def _parse_json_response(text: str) -> Optional[dict]:
    import re as _re
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _re.search(r"\{.*\}", text, _re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


class ScanBody(BaseModel):
    address: str = DEFAULT_ADDRESS
    radius_km: float = DEFAULT_RADIUS_KM


@router.post("/scan")
async def scan_opportunities(
    body: ScanBody = ScanBody(),  # noqa: B008
    user: dict = Depends(require_role("gestor")),
):
    """Executa scan completo: geocoding → Overpass → Claude. Salva no cache."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    radius_m = int(body.radius_km * 1000)
    if radius_m < 500 or radius_m > 20000:
        raise HTTPException(400, "radius_km deve estar entre 0.5 e 20.")

    # 1) Geocoding
    try:
        lat, lon, display_name = await _geocode(body.address)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, safe_detail(502, e, "Falha geocoding:"))

    # 2) Overpass — pode demorar até 1min
    try:
        elements = await _overpass(lat, lon, radius_m)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, safe_detail(502, e, "Falha Overpass:"))

    # 3) Normaliza prospects
    origin = (lat, lon)
    prospects: list[dict] = []
    for el in elements:
        p = _classify_element(el, origin)
        if p:
            prospects.append(p)

    if not prospects:
        raise HTTPException(404, "Nenhum prospect encontrado na região.")

    # 4) Claude analisa
    prompt = _build_ai_prompt(display_name or body.address,
                                body.radius_km, prospects)
    try:
        result = await chat_completion(
            company_id=cid,
            messages=[
                {"role": "system", "content": (
                    "Você é um analista B2B sênior de ISP. "
                    "Devolva SEMPRE JSON puro, sem markdown."
                )},
                {"role": "user", "content": prompt},
            ],
            model=MODEL_NAME,
            temperature=0.4,
            max_tokens=8000,
            json_mode=True,
            purpose="general",
            agent="loyalty_opportunities_ai",
        )
    except RuntimeError as e:
        raise HTTPException(
            500,
            f"OpenRouter não configurado. {e}. "
            "Configure a chave em Configurações → AI Keys.",
        )
    except Exception as e:
        logger.exception("[opp-ai] Falha chamando Claude")
        raise HTTPException(502, safe_detail(502, e, "Falha LLM:"))

    text = result.get("content") or ""
    insights = _parse_json_response(text)
    if not insights:
        logger.error("[opp-ai] resposta inválida: %s", text[:500])
        raise HTTPException(502, "LLM retornou formato inválido.")

    now_iso = datetime.now(timezone.utc).isoformat()
    doc = {
        "company_id": cid,
        "generated_at": now_iso,
        "generated_by": user.get("email") or user.get("id"),
        "origin_address": body.address,
        "origin_lat": lat,
        "origin_lon": lon,
        "origin_display_name": display_name,
        "radius_km": body.radius_km,
        "model": result.get("model") or MODEL_NAME,
        "provider": result.get("provider") or "openrouter",
        "raw_count": len(prospects),
        "prospects": prospects,
        "insights": insights,
    }
    await db.loyalty_opportunities_ai.insert_one(doc)
    return {
        "ok": True,
        "generated_at": now_iso,
        "origin": {
            "address": body.address,
            "lat": lat, "lon": lon,
            "display_name": display_name,
        },
        "radius_km": body.radius_km,
        "model": doc["model"],
        "provider": doc["provider"],
        "raw_count": len(prospects),
        "prospects": prospects,
        "insights": insights,
    }


@router.get("")
async def latest_opportunities(user: dict = Depends(require_role("gestor"))):
    """Retorna o último scan salvo (cache)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.loyalty_opportunities_ai.find_one(
        {"company_id": cid}, {"_id": 0},
        sort=[("generated_at", -1)],
    )
    if not doc:
        return {"cached": False}
    try:
        gen = datetime.fromisoformat(
            doc["generated_at"].replace("Z", "+00:00"))
        if gen.tzinfo is None:
            gen = gen.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - gen).total_seconds() / 3600
    except Exception:
        age_h = 999
    return {
        "cached": True,
        "age_hours": round(age_h, 1),
        **doc,
    }
