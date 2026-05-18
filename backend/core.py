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
from pydantic import BaseModel, Field

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
    sender_name: Optional[str] = "SmartProv"
    openai_api_key: Optional[str] = None
    monthly_email_enabled: bool = True
    auto_audit: bool = True
    location_ping_interval_sec: int = 15
    he_monthly_budget_brl: float = 0.0
    he_alert_threshold_pct: float = 30.0
    # ---- Tempos de referência por tipo de serviço (em minutos) ----
    sla_reparo_minutes: int = 60
    sla_instalacao_minutes: int = 120
    sla_retirada_minutes: int = 30
    sla_prioridade_minutes: int = 45
    sla_preventiva_minutes: int = 90
    sla_venda_minutes: int = 60
    sla_warning_pct: int = 80           # % do tempo onde alerta amarelo dispara (legado, mantido p/ compat)
    sla_yellow_minutes: int = 15        # 🟡 Bolha pisca AMARELO quando faltam X min p/ estourar
    sla_red_after_minutes: int = 0      # 🔴 Bolha pisca VERMELHO X min APÓS estourar (0 = imediato)
    sla_pending_grace_minutes: int = Field(default=60, ge=0, le=1440)  # bolhas sem horário marcado: SLA começa após X min de criação
    sla_blink_when_overdue: bool = True
    # ---- Sincronização de horário (servidor Brasil) ----
    time_sync_enabled: bool = False             # bloqueia ações se relógio do dispositivo dessincronizado
    time_sync_max_drift_seconds: int = Field(default=60, ge=1, le=86400)  # diferença máxima permitida em segundos
    time_sync_timezone: str = "America/Sao_Paulo"  # fuso usado como referência
    # ---- Grade fixa de horários da lousa ----
    lousa_grid_start_hour: int = 8       # hora de início da grade (ex: 8 = 08:00)
    lousa_grid_end_hour: int = 18        # hora de fim da grade (ex: 18 = 18:00, exclusiva)
    lousa_grid_slot_minutes: int = 60    # duração de cada slot em minutos (60=1h, 30=30min)
    lousa_grid_max_per_slot: int = 2     # máximo de bolhas por slot/horário
    # ---- Cerca virtual dinâmica (praça=Nota) ----
    nota_fence_radius_m: int = 80        # raio em metros da cerca dinâmica no endereço da bolha
    # ---- OpenRouter (LLM provider alternativo) ----
    openrouter_enabled: bool = False
    openrouter_api_key: Optional[str] = None
    openrouter_model: str = "deepseek/deepseek-v4-flash"
    # ---- Online indicator threshold ----
    online_threshold_minutes: int = 5    # técnico online se houve clock-record ou ping nos últimos N min


class Company(BaseModel):
    """Tenant/empresa cliente do SaaS."""
    id: str
    name: str
    slug: str
    owner_email: str
    plan: str = "monthly_99"  # SmartProv Pro
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
# Fuso de exibição/registro: o backend é UTC-only para timestamps ISO (boa
# prática), mas para os campos legíveis pelo usuário (`time` HH:MM, `date`
# YYYY-MM-DD) precisamos casar com o relógio que o app mostra (ServerClock,
# canto superior direito). O ServerClock usa toLocaleTimeString("pt-BR",
# timeZone="America/Sao_Paulo"). Sem esse alinhamento, todo registro de ponto
# era persistido em UTC e ficava 3h adiantado vs. o que o técnico vê na tela.
import os
try:
    from zoneinfo import ZoneInfo
    APP_TZ = ZoneInfo(os.environ.get("APP_TZ", "America/Sao_Paulo"))
except Exception:  # zoneinfo indisponível em algumas distros
    APP_TZ = timezone.utc


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_str() -> str:
    """Data atual no FUSO LOCAL DO APP (não UTC) — usada para particionar
    registros do dia. Garante que '2026-05-09 23:30 BR' não vire '2026-05-10' UTC.
    """
    return datetime.now(APP_TZ).strftime("%Y-%m-%d")


def now_hhmm() -> str:
    """Hora HH:MM no FUSO LOCAL DO APP — bate com o ServerClock exibido no app."""
    return datetime.now(APP_TZ).strftime("%H:%M")


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
    """Geocode com viés pra Brasil e detalhes de endereço (rua/bairro/cidade).
    Usar `countrycodes=br` melhora muito a precisão pra endereços daqui.
    """
    async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": USER_AGENT}) as c:
        r = await c.get(GEOCODE_URL, params={
            "q": address,
            "format": "json",
            "limit": 1,
            "addressdetails": 1,
            "countrycodes": "br",
            "accept-language": "pt-BR",
        })
        r.raise_for_status()
        data = r.json()
        if not data:
            raise HTTPException(status_code=400, detail=f"Endereço não localizado: {address}")
        first = data[0]
        return GeocodeResult(lat=float(first["lat"]), lng=float(first["lon"]),
                                 display_name=first.get("display_name", address))


# -------------------------------------------------------------------------
# IA Vision
# -------------------------------------------------------------------------
async def llm_chat(session_id: str, system: str) -> LlmChat:
    # 1. NOVO Motor IA centralizado (tab Sistemas → Motor IA, multi-tenant via motor_ia_config)
    try:
        from database import db as _db
        mcfg = await _db.motor_ia_config.find_one(
            {"company_id": DEMO_COMPANY_ID}, {"_id": 0},
        )
        if mcfg and mcfg.get("enabled") and mcfg.get("openrouter_api_key"):
            return _OpenRouterChat(
                api_key=mcfg["openrouter_api_key"],
                model=mcfg.get("default_text_model") or "openai/gpt-4o-mini",
                system=system,
                session_id=session_id,
                fallbacks=mcfg.get("fallback_models") or [],
            )
    except Exception as e:
        import logging
        logging.getLogger("app").warning("motor_ia_config check failed: %s", e)

    # 2. Settings legado (ainda suportado para compat)
    s = await get_settings()
    if s.openrouter_enabled and s.openrouter_api_key:
        try:
            return _OpenRouterChat(
                api_key=s.openrouter_api_key,
                model=s.openrouter_model or "deepseek/deepseek-v4-flash",
                system=system,
                session_id=session_id,
            )
        except Exception as e:
            # Fallback para Emergent se OpenRouter falhar na inicialização
            import logging
            logging.getLogger("app").warning("OpenRouter init failed, falling back to Emergent: %s", e)
    key = s.openai_api_key or EMERGENT_LLM_KEY
    if not key:
        raise HTTPException(status_code=500, detail="Nenhuma chave de IA configurada (Emergent ou OpenAI).")
    chat = LlmChat(api_key=key, session_id=session_id, system_message=system).with_model(*DEFAULT_FACE_MODEL)
    return chat


class _OpenRouterChat:
    """Adapter mínimo que imita a interface .send_message(UserMessage) usada no app."""
    def __init__(self, api_key: str, model: str, system: str, session_id: str,
                  fallbacks: Optional[list] = None):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": os.environ.get("PUBLIC_BASE_URL", "https://app.local"),
                "X-Title": "SmartProv Lousa",
            },
        )
        self._model = model
        self._fallbacks = [m for m in (fallbacks or []) if m and m != model]
        self._messages = [{"role": "system", "content": system}]
        self._session_id = session_id

    def with_model(self, *_args, **_kwargs):  # compat: ignora, OpenRouter usa self._model
        return self

    async def send_message(self, msg) -> str:
        # msg é UserMessage(text=...) do emergentintegrations
        text = getattr(msg, "text", str(msg))
        self._messages.append({"role": "user", "content": text})
        kwargs: dict = {
            "model": self._model,
            "messages": self._messages,
            "max_tokens": 800,
            "temperature": 0.4,
        }
        if self._fallbacks:
            # OpenRouter aceita no máximo 3 modelos no array (1 principal + 2 fallbacks).
            models_arr = [self._model, *self._fallbacks][:3]
            kwargs["extra_body"] = {"models": models_arr}
        resp = await self._client.chat.completions.create(**kwargs)
        out = (resp.choices[0].message.content or "").strip()
        self._messages.append({"role": "assistant", "content": out})
        return out


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
async def resolve_geofence_for(cid: str, lat: Optional[float], lng: Optional[float]) -> tuple[Optional[dict], Optional[float]]:
    # Sem coordenadas (ex.: navegador bloqueou geo) → equivalente a "fora da cerca"
    if lat is None or lng is None:
        return None, None
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
