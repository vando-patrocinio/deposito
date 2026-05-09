"""Helpers compartilhados (puros, sem rotas) usados pelos modules de routes/.

Reúne: constantes, helpers de tempo, geocálculo, LLM, parsing, clusters,
get_settings/save_settings, dependências de autenticação.

Importa de `database.py` o objeto `db` para evitar import circular com server.py.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from emergentintegrations.llm.chat import ImageContent, LlmChat, UserMessage
from fastapi import HTTPException
from pydantic import BaseModel

from auth import make_dependencies
from database import db

DEMO_COMPANY_ID = "co-demo"
SUPER_ADMIN_EMAILS_ENV = "SUPER_ADMIN_EMAILS"


def is_super_admin(user: dict) -> bool:
    """Super admin (allowlist do .env) tem visão cross-tenant."""
    if not user:
        return False
    emails = {e.strip().lower() for e in (os.environ.get(SUPER_ADMIN_EMAILS_ENV) or "").split(",") if e.strip()}
    return (user.get("email") or "").strip().lower() in emails


def tenant_filter(user: dict) -> dict:
    """Filtro Mongo para escopo de tenant.
    - Super admin SEM `_active_company` → sem filtro (cross-tenant)
    - Super admin COM `_active_company` → escopa àquela empresa (drill-down)
    - Demais → escopa à própria company_id
    """
    if is_super_admin(user):
        active = (user or {}).get("_active_company")
        return {"company_id": active} if active else {}
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return {"company_id": cid}


def effective_company_id(user: dict) -> Optional[str]:
    """Retorna o company_id efetivo, considerando override de super admin.
    None significa cross-tenant (apenas super admin sem override)."""
    if is_super_admin(user):
        return user.get("_active_company") or None
    return user.get("company_id") or DEMO_COMPANY_ID


def tenant_id_of(user: dict) -> str:
    """Tenant id efetivo do usuário (super admin = demo, mas pode ser sobrescrito por header)."""
    return user.get("company_id") or DEMO_COMPANY_ID

logger = logging.getLogger("ponto")

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
DEFAULT_FACE_MODEL = ("openai", "gpt-4o")
GEOCODE_URL = "https://nominatim.openstreetmap.org/search"
PHOTON_URL = "https://photon.komoot.io/api/"
USER_AGENT = "PontoDoColaborador/1.0 (suporte@ponto.local)"

GEOFENCE_REQUIRED = {"Entrada", "Saída"}
EVENT_TYPES = ["Entrada", "Início intervalo", "Fim intervalo", "Saída"]

PUBLIC_BLOCK = "Não foi possível validar este registro no momento. Procure o gestor responsável."
PUBLIC_FACE_FAIL = "Não conseguimos validar seu rosto. Tente novamente em local bem iluminado, sem óculos escuros ou máscara."
PUBLIC_FENCE_FAIL = "Você está fora da área permitida para registrar este ponto."


# -------------------------------------------------------------------------
# Models compartilhados
# -------------------------------------------------------------------------
class Settings(BaseModel):
    id: str = "global"
    resend_api_key: Optional[str] = None
    sender_email: Optional[str] = None
    sender_name: Optional[str] = "Ponto do Colaborador"
    openai_api_key: Optional[str] = None
    monthly_email_enabled: bool = True
    auto_audit: bool = True
    location_ping_interval_sec: int = 15
    he_monthly_budget_brl: float = 0.0
    he_alert_threshold_pct: float = 30.0


class Company(BaseModel):
    """Tenant/empresa cliente do SaaS."""
    id: str
    name: str
    slug: str
    owner_email: str
    plan: str = "monthly_99"  # PontoIA Pro
    status: str = "trialing"  # trialing | active | past_due | cancelled
    trial_ends_at: Optional[str] = None
    paid_until: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    last_session_id: Optional[str] = None
    max_collaborators: int = 25
    created_at: str
    updated_at: str


# -------------------------------------------------------------------------
# Helpers de tempo
# -------------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def now_hhmm() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M")


def strip_data_url(b64: str) -> tuple[str, str]:
    if b64.startswith("data:"):
        m = re.match(r"data:(image/[^;]+);base64,(.*)", b64, flags=re.S)
        if m:
            return m.group(1), m.group(2)
    return "image/jpeg", b64


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# -------------------------------------------------------------------------
# Settings (por tenant)
# -------------------------------------------------------------------------
async def get_settings(company_id: Optional[str] = None) -> Settings:
    sid = company_id or DEMO_COMPANY_ID
    doc = await db.settings.find_one({"id": sid}, {"_id": 0})
    if not doc:
        # legacy: tenta ler "global" e migra
        legacy = await db.settings.find_one({"id": "global"}, {"_id": 0})
        if legacy:
            legacy["id"] = sid
            await db.settings.update_one({"id": sid}, {"$set": legacy}, upsert=True)
            return Settings(**legacy)
        s = Settings(id=sid)
        await db.settings.insert_one(s.model_dump())
        return s
    return Settings(**doc)


async def save_settings(payload: dict, company_id: Optional[str] = None) -> Settings:
    sid = company_id or DEMO_COMPANY_ID
    payload["id"] = sid
    await db.settings.update_one({"id": sid}, {"$set": payload}, upsert=True)
    return await get_settings(sid)


# -------------------------------------------------------------------------
# Geocoding
# -------------------------------------------------------------------------
class GeocodeResult(BaseModel):
    lat: float
    lng: float
    display_name: str


async def geocode_address(address: str) -> GeocodeResult:
    async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": USER_AGENT}) as c:
        r = await c.get(GEOCODE_URL, params={"q": address, "format": "json", "limit": 1, "addressdetails": 0})
        r.raise_for_status()
        data = r.json()
        if not data:
            raise HTTPException(status_code=400, detail=f"Endereço não localizado: {address}")
        first = data[0]
        return GeocodeResult(lat=float(first["lat"]), lng=float(first["lon"]), display_name=first.get("display_name", address))


# -------------------------------------------------------------------------
# IA Vision
# -------------------------------------------------------------------------
async def llm_chat(session_id: str, system: str) -> LlmChat:
    s = await get_settings()
    key = s.openai_api_key or EMERGENT_LLM_KEY
    if not key:
        raise HTTPException(status_code=500, detail="Nenhuma chave de IA configurada (Emergent ou OpenAI).")
    chat = LlmChat(api_key=key, session_id=session_id, system_message=system).with_model(*DEFAULT_FACE_MODEL)
    return chat


def parse_json_response(raw: str) -> dict:
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, flags=re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


# -------------------------------------------------------------------------
# Geofence resolver
# -------------------------------------------------------------------------
async def resolve_geofence_for(cid: str, lat: float, lng: float) -> tuple[Optional[dict], Optional[float]]:
    fences = await db.geofences.find({"collaborator_id": cid, "active": True}, {"_id": 0}).to_list(100)
    if not fences:
        return None, None
    best = None
    best_d = None
    for f in fences:
        d = haversine_m(lat, lng, f["lat"], f["lng"])
        if best_d is None or d < best_d:
            best, best_d = f, d
    if best and best_d is not None and best_d <= float(best.get("radius", 15)):
        return best, best_d
    return None, best_d


# -------------------------------------------------------------------------
# Clusters de permanência (dwell)
# -------------------------------------------------------------------------
def build_stay_clusters(points: list[dict], radius_m: float = 60.0, min_dur_min: int = 30) -> list[dict]:
    if not points:
        return []
    clusters: list[dict] = []
    cur = None
    for p in points:
        try:
            lat, lng = float(p["lat"]), float(p["lng"])
            t = p["recorded_at"]
        except Exception:
            continue
        if cur is None:
            cur = {"lat_sum": lat, "lng_sum": lng, "n": 1, "start": t, "end": t,
                   "center_lat": lat, "center_lng": lng, "points": 1}
            continue
        d = haversine_m(lat, lng, cur["center_lat"], cur["center_lng"])
        if d <= radius_m:
            cur["lat_sum"] += lat
            cur["lng_sum"] += lng
            cur["n"] += 1
            cur["end"] = t
            cur["center_lat"] = cur["lat_sum"] / cur["n"]
            cur["center_lng"] = cur["lng_sum"] / cur["n"]
            cur["points"] += 1
        else:
            clusters.append(cur)
            cur = {"lat_sum": lat, "lng_sum": lng, "n": 1, "start": t, "end": t,
                   "center_lat": lat, "center_lng": lng, "points": 1}
    if cur is not None:
        clusters.append(cur)

    out = []
    for c in clusters:
        try:
            start_dt = datetime.fromisoformat(c["start"].replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(c["end"].replace("Z", "+00:00"))
            dur_min = max(1, int(round((end_dt - start_dt).total_seconds() / 60)))
        except Exception:
            dur_min = 0
        out.append({
            "center_lat": round(c["center_lat"], 6),
            "center_lng": round(c["center_lng"], 6),
            "start": c["start"], "end": c["end"],
            "duration_min": dur_min,
            "points": c["points"],
            "is_alert": dur_min >= int(min_dur_min),
        })
    return out


# Cache 60s para evaluação IA do mapa
_dwell_ai_cache: dict[str, Any] = {"ts": 0.0, "data": {}}


async def llm_evaluate_dwell(items: list[dict]) -> dict[str, dict]:
    if not items:
        return {}
    now_ts = datetime.now(timezone.utc).timestamp()
    cache_key = ",".join(sorted(f"{i['collaborator_id']}:{i.get('current_dwell_min',0)}:{int(bool(i.get('out_of_fence')))}" for i in items))
    if (now_ts - _dwell_ai_cache.get("ts", 0)) < 60 and _dwell_ai_cache.get("key") == cache_key:
        return _dwell_ai_cache.get("data", {})
    try:
        chat = await llm_chat(
            session_id=f"dwell-{int(now_ts)}",
            system=("Você é um analista de operações de campo. Avalie de forma OBJETIVA e CURTA "
                    "o risco de produtividade de cada colaborador, considerando: tempo parado em um "
                    "mesmo ponto e se está fora da cerca geográfica do trabalho. Responda EXCLUSIVAMENTE em JSON."),
        )
    except Exception:
        return {}
    payload = [{
        "collaborator_id": i["collaborator_id"],
        "name": i.get("name"),
        "current_dwell_min": i.get("current_dwell_min", 0),
        "out_of_fence": bool(i.get("out_of_fence")),
        "nearest_fence_distance_m": i.get("nearest_fence_distance_m"),
    } for i in items]
    prompt = (
        "Itens a avaliar (JSON):\n" + json.dumps(payload, ensure_ascii=False) + "\n\n"
        "Para CADA item retorne um objeto com as chaves: collaborator_id (string), risk ('baixo'|'medio'|'alto'), "
        "summary (string curta em pt-BR, 1 linha), suggested_action (string em pt-BR, 1 linha). "
        "Responda no formato: {\"results\":[{...}, {...}]}. Não inclua texto fora do JSON."
    )
    try:
        resp = await chat.send_message(UserMessage(text=prompt))
        data = parse_json_response(resp)
        results = (data or {}).get("results") or []
        out: dict[str, dict] = {}
        for r in results:
            cid = r.get("collaborator_id")
            if not cid:
                continue
            out[cid] = {
                "risk": (r.get("risk") or "baixo").lower(),
                "summary": r.get("summary") or "",
                "suggested_action": r.get("suggested_action") or "",
            }
        _dwell_ai_cache["ts"] = now_ts
        _dwell_ai_cache["key"] = cache_key
        _dwell_ai_cache["data"] = out
        return out
    except Exception as e:
        logger.warning("[dwell-ai] falha: %s", e)
        return {}


# -------------------------------------------------------------------------
# Auth deps
# -------------------------------------------------------------------------
def _get_db():
    return db


get_current_user, require_role = make_dependencies(_get_db)
