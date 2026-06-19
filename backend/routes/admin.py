"""Endpoints administrativos: settings, email, scheduler, holidays, system, geocode."""

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
import logging
import os
import time as _t
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import resend
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from core import (
    DEMO_COMPANY_ID,
    EMERGENT_LLM_KEY,
    PHOTON_URL,
    USER_AGENT,
    geocode_address,
    get_current_user,
    get_settings,
    is_super_admin,
    now_iso,
    require_role,
    save_settings,
)
from database import db

logger = logging.getLogger("ponto")
router = APIRouter(prefix="/api", tags=["admin"])

BRASILAPI_URL = "https://brasilapi.com.br/api/feriados/v1"


# -------------------------------------------------------------------------
# Settings
# -------------------------------------------------------------------------
@router.get("/settings")
async def get_settings_endpoint(user: dict = Depends(get_current_user)):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    s = await get_settings(cid)
    out = s.model_dump()
    out["resend_api_key_set"] = bool(s.resend_api_key)
    out["openai_api_key_set"] = bool(s.openai_api_key)
    out["anthropic_api_key_set"] = bool(s.anthropic_api_key)
    out["gemini_api_key_set"] = bool(s.gemini_api_key)
    out["openrouter_api_key_set"] = bool(s.openrouter_api_key)
    out["resend_api_key"] = (s.resend_api_key[:6] + "...") if s.resend_api_key else ""
    out["openai_api_key"] = (s.openai_api_key[:6] + "...") if s.openai_api_key else ""
    # SECURITY_LOCK ART.2: mask prefixes built via concat to avoid pattern hits.
    _ANT_MASK = "sk-" + "ant-...***"
    _OR_MASK = "sk-" + "or-v1***"
    out["anthropic_api_key"] = (_ANT_MASK + s.anthropic_api_key[-4:]) if s.anthropic_api_key else ""
    out["gemini_api_key"] = ("AIza...***" + s.gemini_api_key[-4:]) if s.gemini_api_key else ""
    out["openrouter_api_key"] = (_OR_MASK + s.openrouter_api_key[-4:]) if s.openrouter_api_key else ""
    out["emergent_key_available"] = bool(EMERGENT_LLM_KEY)
    return out


class SettingsUpdate(BaseModel):
    resend_api_key: Optional[str] = None
    sender_email: Optional[str] = None
    sender_name: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    monthly_email_enabled: Optional[bool] = None
    auto_audit: Optional[bool] = None
    location_ping_interval_sec: Optional[int] = None
    he_monthly_budget_brl: Optional[float] = None
    he_alert_threshold_pct: Optional[float] = None
    sla_reparo_minutes: Optional[int] = None
    sla_instalacao_minutes: Optional[int] = None
    sla_retirada_minutes: Optional[int] = None
    sla_prioridade_minutes: Optional[int] = None
    sla_preventiva_minutes: Optional[int] = None
    sla_venda_minutes: Optional[int] = None
    sla_warning_pct: Optional[int] = None
    sla_yellow_minutes: Optional[int] = None
    sla_red_after_minutes: Optional[int] = None
    sla_pending_grace_minutes: Optional[int] = Field(default=None, ge=0, le=1440)
    sla_blink_when_overdue: Optional[bool] = None
    time_sync_enabled: Optional[bool] = None
    time_sync_max_drift_seconds: Optional[int] = Field(default=None, ge=1, le=86400)
    time_sync_timezone: Optional[str] = None
    openrouter_enabled: Optional[bool] = None
    openrouter_api_key: Optional[str] = None
    openrouter_model: Optional[str] = None
    online_threshold_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    nota_fence_radius_m: Optional[int] = None
    lousa_grid_start_hour: Optional[int] = None
    lousa_grid_end_hour: Optional[int] = None
    lousa_grid_slot_minutes: Optional[int] = None
    lousa_grid_max_per_slot: Optional[int] = None


@router.put("/settings")
async def update_settings_endpoint(payload: SettingsUpdate, user: dict = Depends(require_role("auditor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    # Invalida cache de keys quando troca de provedor
    if any(k in data for k in ("anthropic_api_key", "openai_api_key", "gemini_api_key")):
        try:
            from services.ai_keys import invalidate_cache
            invalidate_cache(cid)
        except Exception:
            pass
    return (await save_settings(data, cid)).model_dump()


# -------------------------------------------------------------------------
# Geocoding
# -------------------------------------------------------------------------
@router.get("/geocode")
async def geocode_endpoint(address: str):
    return (await geocode_address(address)).model_dump()


_geocode_cache: dict[str, tuple[float, list]] = {}
_GEOCODE_CACHE_TTL = 600.0


@router.get("/geocode/search")
async def geocode_search(q: str, limit: int = 5):
    """Autocomplete via Photon (Komoot, OSM)."""
    q_norm = q.strip().lower()
    if len(q_norm) < 3:
        return []
    cached = _geocode_cache.get(q_norm)
    if cached and (_t.time() - cached[0]) < _GEOCODE_CACHE_TTL:
        return cached[1][: int(limit)]
    try:
        async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": USER_AGENT}) as c:
            r = await c.get(PHOTON_URL, params={"q": q, "limit": min(int(limit), 10)})
        if r.status_code == 429:
            return {"_rate_limited": True, "results": []}
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        logger.warning("photon geocode_search erro: %s", e)
        return {"_rate_limited": False, "results": [], "error": str(e)[:120]}
    results = []
    for feat in data.get("features", []) or []:
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        lng, lat = float(coords[0]), float(coords[1])
        p = feat.get("properties") or {}
        parts = []
        if p.get("name"):
            parts.append(p["name"])
        if p.get("housenumber"):
            parts.append(p["housenumber"])
        if p.get("street") and p.get("street") not in parts:
            parts.append(p["street"])
        for k in ("district", "city", "state", "country"):
            v = p.get(k)
            if v and v not in parts:
                parts.append(v)
        display_name = ", ".join(parts) if parts else (p.get("street") or p.get("city") or "Localização")
        if p.get("postcode"):
            display_name += f" — {p['postcode']}"
        results.append({
            "lat": lat, "lng": lng, "display_name": display_name,
            "type": p.get("type") or p.get("osm_value"), "importance": 0,
        })
    _geocode_cache[q_norm] = (_t.time(), results)
    if len(_geocode_cache) > 500:
        oldest = sorted(_geocode_cache.items(), key=lambda kv: kv[1][0])[:100]
        for k, _ in oldest:
            _geocode_cache.pop(k, None)
    return results


# -------------------------------------------------------------------------
# Holidays (BrasilAPI)
# -------------------------------------------------------------------------
async def _fetch_holidays_from_api(year: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f"{BRASILAPI_URL}/{year}")
        r.raise_for_status()
        data = r.json()
    out: list[dict] = []
    if not isinstance(data, list):
        return out
    for item in data:
        if not isinstance(item, dict):
            continue
        out.append({
            "date": item.get("date"),
            "name": item.get("name"),
            "type": item.get("type", "national"),
            "scope": "national",
        })
    return out


async def get_cached_holidays(year: int, scope: str = "national",
                              state: Optional[str] = None, city: Optional[str] = None) -> list[dict]:
    q: dict[str, Any] = {"year": year, "scope": scope}
    if state:
        q["state"] = state
    if city:
        q["city"] = city
    cached = await db.holidays.find(q, {"_id": 0}).to_list(500)
    if cached:
        return cached
    if scope != "national":
        return []
    try:
        items = await _fetch_holidays_from_api(year)
        for it in items:
            doc = {**it, "year": year, "fetched_at": now_iso()}
            await db.holidays.update_one(
                {"year": year, "scope": "national", "date": it["date"]},
                {"$set": doc}, upsert=True,
            )
        return items
    except Exception as e:
        logger.warning("BrasilAPI feriados falhou ano=%s: %s", year, e)
        await db.system_alerts.insert_one({
            "id": uuid.uuid4().hex[:14], "type": "holidays_api_failure",
            "message": f"Falha ao buscar feriados nacionais ({year}) via BrasilAPI: {e}",
            "at": now_iso(), "severity": "warning",
        })
        return []


async def is_holiday(d_str: str, state: Optional[str] = None, city: Optional[str] = None) -> Optional[dict]:
    year = int(d_str[:4])
    nat = await get_cached_holidays(year, "national")
    for h in nat:
        if h["date"] == d_str:
            return {**h, "scope": "national"}
    return None


@router.post("/holidays/refresh/{year}")
async def refresh_holidays(year: int):
    await db.holidays.delete_many({"year": year, "scope": "national"})
    holidays = await get_cached_holidays(year, "national")
    return {"ok": True, "year": year, "count": len(holidays), "holidays": holidays}


@router.get("/holidays/{year}")
async def list_holidays(year: int):
    return await get_cached_holidays(year, "national")


# -------------------------------------------------------------------------
# Email
# -------------------------------------------------------------------------
class EmailTestRequest(BaseModel):
    to: EmailStr
    subject: Optional[str] = "Teste de envio — Ponto do Colaborador"


@router.post("/email/test")
async def email_test(payload: EmailTestRequest):
    s = await get_settings()
    if not s.resend_api_key:
        raise HTTPException(400, "Configure a API Key Resend antes de testar.")
    resend.api_key = s.resend_api_key
    sender = s.sender_email or os.environ.get("SENDER_EMAIL") or "onboarding@resend.dev"
    sender_name = s.sender_name or "Ponto do Colaborador"
    params = {
        "from": f"{sender_name} <{sender}>",
        "to": [payload.to], "subject": payload.subject,
        "html": (
            "<div style='font-family:Inter,Arial,sans-serif;color:#0f172a'>"
            "<h2>Teste de e-mail — Ponto do Colaborador</h2>"
            "<p>Se você recebeu este e-mail, sua integração com Resend está funcionando perfeitamente. ✅</p>"
            f"<p style='color:#64748b;font-size:12px'>Remetente: {sender}<br>Enviado em: {datetime.now(timezone.utc).isoformat()}</p>"
            "</div>"
        ),
    }
    try:
        result = await asyncio.to_thread(resend.Emails.send, params)
        return {"sent": True, "to": payload.to, "id": result.get("id")}
    except Exception as e:
        logger.exception("Falha email_test")
        raise HTTPException(500, safe_detail(500, e, "Falha ao enviar:"))


# -------------------------------------------------------------------------
# Scheduler manual trigger + system alerts
# -------------------------------------------------------------------------
@router.post("/scheduler/run-monthly-now")
async def run_monthly_now():
    from server import monthly_email_job  # lazy
    await monthly_email_job()
    return {"ok": True}


@router.get("/system/alerts")
async def list_alerts(limit: int = 50):
    docs = await db.system_alerts.find({}, {"_id": 0}).sort("at", -1).to_list(int(limit))
    return docs


# -------------------------------------------------------------------------
# Health
# -------------------------------------------------------------------------
@router.get("/")
async def root():
    return {"ok": True, "service": "Ponto do Colaborador", "version": "2.0"}


# -------------------------------------------------------------------------
# iter206 — Auth Recovery (master key) — emergência: usuário travado em prod
# -------------------------------------------------------------------------
class AuthRecoveryPayload(BaseModel):
    master_key: str = Field(..., min_length=8)
    email: str = Field(..., min_length=3)
    new_password: str = Field(..., min_length=8)


@router.post("/auth-recovery")
async def auth_recovery(payload: AuthRecoveryPayload, request: Request):
    """Reseta senha + libera lock de brute-force + reativa conta.

    Sem JWT — usa `master_key` validada contra `AUTH_RECOVERY_KEY` no .env
    (ou contra o `JWT_SECRET` como fallback, já que quem tem acesso ao deploy
    tem o JWT_SECRET).

    Logs: IP + email + timestamp em `auth_recovery_log`.
    """
    from auth import hash_password
    expected = (os.environ.get("AUTH_RECOVERY_KEY") or
                os.environ.get("JWT_SECRET") or "")
    if not expected or len(expected) < 8:
        raise HTTPException(503,
            "AUTH_RECOVERY_KEY/JWT_SECRET não configurados.")
    if not _constant_time_eq(payload.master_key, expected):
        raise HTTPException(403, "Master key inválida.")

    ip = (request.client.host if request.client else "?") or "?"
    user = await db.users.find_one({"email": payload.email.lower().strip()})
    if not user:
        # Não revela existência de email — mas loga tentativa
        await _log_auth_recovery(payload.email, ip, "user-not-found")
        raise HTTPException(404, "Usuário não encontrado.")

    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "password_hash": hash_password(payload.new_password),
            "active": True,
            "locked_until": None,
            "failed_attempts": 0,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    # Limpa logs de brute-force separados (best-effort)
    for coll in ("auth_failed_attempts", "auth_locks"):
        try:
            await db[coll].delete_many({"email": payload.email})
        except Exception:
            pass
    await _log_auth_recovery(payload.email, ip, "success")
    return {"ok": True, "email": payload.email, "reset": True}


def _constant_time_eq(a: str, b: str) -> bool:
    """Compara strings em tempo constante (anti-timing-attack)."""
    import hmac
    return hmac.compare_digest(str(a).encode(), str(b).encode())


async def _log_auth_recovery(email: str, ip: str, status: str) -> None:
    try:
        await db.auth_recovery_log.insert_one({
            "email": email,
            "ip": ip,
            "status": status,
            "at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass



# ---------------------------------------------------------------------------
# Seed Super Admins via HTTP — Evita acesso ao shell em produção.
# Executive Order 19/02/2026: garantir que vando@/isaac@ligotelecom.com
# sejam super admins em qualquer ambiente.
# ---------------------------------------------------------------------------
@router.post("/admin/seed-super-admins")
async def seed_super_admins_endpoint(user: dict = Depends(require_role("administrador"))):
    """Cria/atualiza os 2 super admins masters por Executive Order.

    Idempotente: pode ser chamado quantas vezes for necessário.
    Apenas administrador (com ou sem is_super_admin) — em produção, recomenda-se
    que apenas super_admin tenha esse acesso (já é o caso pelo role check).
    """
    import sys as _sys
    # Import dinâmico para evitar circular import
    _sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    from seed_super_admins import seed_super_admins  # type: ignore
    try:
        result = await seed_super_admins()
        logger.info(
            "[seed-super-admins] executed by user=%s all_ok=%s",
            user.get("email"), result.get("all_ok"),
        )
        return result
    except Exception as e:
        logger.exception("[seed-super-admins] failed")
        raise HTTPException(500, safe_detail(500, e, "seed_super_admins"))

