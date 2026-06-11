"""routes/provider_site.py — Site público do provedor (landing page).

Endpoints públicos (sem auth — usado pelo site do cliente):
  GET   /api/site/config      — config do site (hero, contatos, redes)
  GET   /api/site/plans       — planos visíveis (show_on_prospects_page=true)
  POST  /api/site/leads       — captura de lead do form do site

Endpoints admin (auth):
  PUT   /api/site/config      — salva config
  GET   /api/site/leads       — lista leads recebidos
  PUT   /api/site/leads/{id}  — atualiza status do lead
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
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, EmailStr

from core import DEMO_COMPANY_ID, get_current_user, is_super_admin
from database import db

logger = logging.getLogger("ponto.site")
router = APIRouter(prefix="/api/site", tags=["provider-site"])


# === Config padrão (se não houver no DB) ============================
DEFAULT_CONFIG = {
    "company_id": DEMO_COMPANY_ID,
    "site_name": "SmartProv Fibra",
    "cnpj": "",
    "anatel": "",
    "phone_0800": "0800 000 0000",
    "phone_whatsapp": "5500000000000",  # E.164 sem +
    "email": "contato@smartprov.com.br",
    "instagram_url": "",
    "facebook_url": "",
    "support_portal_url": "",  # central do assinante (Asaas / outro)
    "central_url": "",          # 2ª via boleto / minha conta
    "hero_kicker": "NAVEGUE COM ATÉ 1000 MEGA",
    "hero_title": "Internet Rápida de verdade!",
    "hero_subtitle": "Fibra ótica pura, sem limite de velocidade.",
    "hero_cta": "CONHEÇA NOSSOS PLANOS",
    "hero_image_url": "",
    "primary_color": "#0ea5e9",
    "secondary_color": "#f97316",
    "logo_url": "",
    "combos": [
        {"name": "Disney+", "icon_url": "", "description": "Streaming Disney"},
        {"name": "HBO Max", "icon_url": "", "description": "Streaming HBO"},
        {"name": "Globoplay", "icon_url": "", "description": "Streaming Globo"},
        {"name": "Deezer", "icon_url": "", "description": "Música ilimitada"},
        {"name": "Sky+", "icon_url": "", "description": "TV digital"},
        {"name": "Telefone Fixo", "icon_url": "", "description": "Ligações ilimitadas"},
        {"name": "Celular", "icon_url": "", "description": "Plano móvel"},
    ],
    "google_reviews_url": "",
    "app_android_url": "",
    "app_ios_url": "",
    "footer_text": "",
    "active_regions": ["principal"],
    "default_region": "principal",
}


def _cid(user: dict) -> str:
    if is_super_admin(user):
        return (user.get("_active_company") or user.get("company_id")
                or DEMO_COMPANY_ID)
    return user.get("company_id") or DEMO_COMPANY_ID


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ===========================================================================
# Helper: resolve company_id pra rota pública (por hostname/domínio)
# ===========================================================================
async def _resolve_public_company(host: str | None = None) -> str:
    """Em SaaS multi-tenant, mapeia hostname → company_id.

    Por enquanto retorna a empresa demo. Quando tivermos custom domains,
    leríamos uma collection `tenant_domains` com (host → company_id).
    """
    # TODO: implementar quando tivermos custom domains
    return DEMO_COMPANY_ID


# ===========================================================================
# GET config (público — site do cliente acessa)
# ===========================================================================
@router.get("/config")
async def get_public_config(request: Request):
    """Retorna config do site. Público — sem auth."""
    cid = await _resolve_public_company(request.headers.get("host"))
    doc = await db.site_config.find_one({"company_id": cid}, {"_id": 0})
    if not doc:
        return {**DEFAULT_CONFIG, "company_id": cid}
    return {**DEFAULT_CONFIG, **doc}


# ===========================================================================
# PUT config (admin — gestor edita pelo painel)
# ===========================================================================
class SiteConfigIn(BaseModel):
    site_name: Optional[str] = None
    cnpj: Optional[str] = None
    anatel: Optional[str] = None
    phone_0800: Optional[str] = None
    phone_whatsapp: Optional[str] = None
    email: Optional[str] = None
    instagram_url: Optional[str] = None
    facebook_url: Optional[str] = None
    support_portal_url: Optional[str] = None
    central_url: Optional[str] = None
    hero_kicker: Optional[str] = None
    hero_title: Optional[str] = None
    hero_subtitle: Optional[str] = None
    hero_cta: Optional[str] = None
    hero_image_url: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    logo_url: Optional[str] = None
    combos: Optional[list[dict]] = None
    google_reviews_url: Optional[str] = None
    app_android_url: Optional[str] = None
    app_ios_url: Optional[str] = None
    footer_text: Optional[str] = None


@router.put("/config")
async def update_config(
    payload: SiteConfigIn, user: dict = Depends(get_current_user)
):
    role = (user.get("role") or "").lower()
    if role not in ("gestor", "administrador") and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador.")
    cid = _cid(user)

    update = {k: v for k, v in payload.dict().items() if v is not None}
    update["updated_at"] = _now().isoformat()
    update["updated_by"] = user.get("name") or user.get("email")
    update["company_id"] = cid

    await db.site_config.update_one(
        {"company_id": cid}, {"$set": update}, upsert=True,
    )
    doc = await db.site_config.find_one({"company_id": cid}, {"_id": 0})
    return {"ok": True, "config": {**DEFAULT_CONFIG, **(doc or {})}}


# ===========================================================================
# GET plans públicos (apenas com show_on_prospects_page=true)
# ===========================================================================
@router.get("/plans")
async def get_public_plans(request: Request):
    cid = await _resolve_public_company(request.headers.get("host"))
    cursor = db.plans.find(
        {"company_id": cid, "active": {"$ne": False},
          "show_on_prospects_page": True},
        {"_id": 0, "id": 1, "name": 1, "speed_down_mbps": 1,
          "speed_up_mbps": 1, "monthly_price": 1, "description": 1,
          "speed_label": 1, "vod_packages": 1, "plan_type": 1},
    ).sort("monthly_price", 1)
    items = await cursor.to_list(50)
    return {"items": items, "count": len(items)}


# ===========================================================================
# POST leads (público — form do site)
# ===========================================================================
class SiteLeadIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=160)
    email: Optional[EmailStr] = None
    phone: str = Field(..., min_length=8, max_length=32)
    plan_interest: Optional[str] = None   # nome ou id do plano
    address: Optional[str] = None
    region: Optional[str] = None
    message: Optional[str] = None


@router.post("/leads")
async def create_lead(payload: SiteLeadIn, request: Request):
    """Captura lead do form do site. Sem auth (público)."""
    cid = await _resolve_public_company(request.headers.get("host"))
    digits = "".join(c for c in payload.phone if c.isdigit())
    if len(digits) < 8:
        raise HTTPException(400, "Telefone inválido")

    doc = {
        "id": f"lead-{uuid.uuid4().hex[:12]}",
        "company_id": cid,
        "name": payload.name.strip(),
        "email": (payload.email or None),
        "phone": payload.phone.strip(),
        "phone_digits": digits,
        "plan_interest": payload.plan_interest,
        "address": payload.address,
        "region": payload.region,
        "message": payload.message,
        "status": "new",   # new | contacted | converted | discarded
        "source": "site_landing",
        "ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent", "")[:300],
        "created_at": _now().isoformat(),
    }
    await db.site_leads.insert_one(doc)
    doc.pop("_id", None)
    # TODO: notificar gestor via WhatsApp/Email (hook futuro)
    return {"ok": True, "lead_id": doc["id"]}


# ===========================================================================
# GET leads (admin — gestor vê)
# ===========================================================================
@router.get("/leads")
async def list_leads(
    status: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    cid = _cid(user)
    q: dict[str, Any] = {"company_id": cid}
    if status: q["status"] = status
    items = await db.site_leads.find(q, {"_id": 0}).sort(
        "created_at", -1).limit(500).to_list(500)
    # Normaliza apenas address — outros campos preservados no formato original
    from utils.normalize import norm_string
    for it in items:
        if it.get("address") is not None and not isinstance(it["address"], str):
            it["address"] = norm_string(it["address"])
    counts = {
        "new": await db.site_leads.count_documents(
            {"company_id": cid, "status": "new"}),
        "contacted": await db.site_leads.count_documents(
            {"company_id": cid, "status": "contacted"}),
        "converted": await db.site_leads.count_documents(
            {"company_id": cid, "status": "converted"}),
        "discarded": await db.site_leads.count_documents(
            {"company_id": cid, "status": "discarded"}),
    }
    return {"items": items, "count": len(items), "counts": counts}


class LeadUpdateIn(BaseModel):
    status: str  # new | contacted | converted | discarded
    notes: Optional[str] = None


@router.put("/leads/{lead_id}")
async def update_lead(
    lead_id: str, payload: LeadUpdateIn,
    user: dict = Depends(get_current_user),
):
    cid = _cid(user)
    if payload.status not in ("new", "contacted", "converted", "discarded"):
        raise HTTPException(400, "Status inválido")
    update = {
        "status": payload.status,
        "updated_at": _now().isoformat(),
        "updated_by": user.get("name") or user.get("email"),
    }
    if payload.notes: update["notes"] = payload.notes
    r = await db.site_leads.update_one(
        {"id": lead_id, "company_id": cid}, {"$set": update})
    if r.matched_count == 0:
        raise HTTPException(404, "Lead não encontrado")
    return {"ok": True}
