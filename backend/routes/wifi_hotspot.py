"""wifi_hotspot.py — Hotspot Wi-Fi multi-tenant (portal cativo).

Este módulo foi reconstruído com base nas collections já existentes em
MongoDB (`wifi_venues`, `wifi_visitors`, `wifi_sessions`, `wifi_campaigns`)
que sobreviveram a um rollback do código fonte. Não toca nas collections
de troca de SSID (`wifi_change_logs`/`wifi_read_logs`) — esse continua
no `wifi.py`.

Conceitos:
  - Venue (espaço/loja): ponto físico que oferece WiFi grátis. Tem slug
    único, tempo de sessão (min), branding (cores/logo) e flags
    `require_phone/email/cpf` no captive portal.
  - Visitor (visitante): pessoa única identificada por phone/email/cpf
    (chave: phone normalizado). Aparece no funil de vendas com
    `source='wifi_hotspot_{venue_slug}'` automaticamente.
  - Session: sessão de internet liberada. Tem `release_token` opaco que
    o roteador (Mikrotik / UniFi) consulta pra confirmar liberação.
  - Campaign: banner+CTA exibido no captive portal. Métricas
    impressions/clicks. Pode ser por venue ou global.

Endpoints (todos sob `/api/wifi-hotspot`):
  Admin (autenticado, role gestor):
    GET    /venues               — lista venues
    POST   /venues               — cria venue
    PUT    /venues/{id}          — edita
    DELETE /venues/{id}          — desativa (soft delete)
    GET    /visitors             — lista leads (filtros)
    GET    /sessions             — lista sessões ativas/históricas
    GET    /campaigns            — lista campanhas
    POST   /campaigns            — cria campanha
    PUT    /campaigns/{id}       — edita
    DELETE /campaigns/{id}       — desativa
    GET    /stats                — KPIs (visitors, sessions, conversão)

  Público (portal cativo):
    GET    /public/venue/{slug}             — info pública (branding+flags)
    POST   /public/venue/{slug}/connect     — visitante envia dados
    GET    /public/session/{token}/status   — roteador valida release_token
    POST   /public/campaign/{id}/click      — registra clique no banner

Sincronização CRM:
  Ao receber `connect` com um phone válido, o visitor é UPSERT em
  `wifi_visitors` (chave: company+phone) e um lead é criado em
  `sales_leads` (chave: phone+source). O timestamp `synced_funnel_at`
  marca quando o sync rodou.
"""
from __future__ import annotations

import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, get_current_user, require_role
from database import db

logger = logging.getLogger("ponto.wifi_hotspot")
router = APIRouter(prefix="/api/wifi-hotspot", tags=["wifi-hotspot"])


# ───────────────────────── Helpers ─────────────────────────

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_company(user: Dict[str, Any]) -> str:
    """Retorna company_id do usuário, com fallback demo."""
    return user.get("company_id") or DEMO_COMPANY_ID


def _slugify(s: str) -> str:
    """Slug ASCII safe (a-z0-9-)."""
    import unicodedata
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-zA-Z0-9-]+", "-", s).strip("-").lower()
    return s or "venue"


def _norm_phone(raw: str) -> str:
    """Mantém só dígitos. Garante 13 dígitos com 55 prefix se for BR."""
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 11 and d.startswith(("1", "2", "3", "4", "5", "6", "7", "8", "9")):
        return f"55{d}"
    if len(d) == 10:
        return f"55{d}"
    return d


def _parse_user_agent(ua: str) -> Dict[str, str]:
    """Parse simples — sem dependência externa.

    Identifica os principais OS/Browser sem precisar de `user-agents` lib.
    """
    ua = (ua or "").lower()
    os_name = "Outro"
    if "android" in ua:
        os_name = "Android"
    elif "iphone" in ua or "ios" in ua or "ipad" in ua:
        os_name = "iOS"
    elif "windows" in ua:
        os_name = "Windows"
    elif "mac os" in ua or "macintosh" in ua:
        os_name = "macOS"
    elif "linux" in ua:
        os_name = "Linux"

    browser = "Outro"
    if "chrome/" in ua and "edg/" not in ua:
        browser = "Chrome"
    elif "edg/" in ua:
        browser = "Edge"
    elif "firefox/" in ua:
        browser = "Firefox"
    elif "safari/" in ua and "chrome/" not in ua:
        browser = "Safari"

    device = "mobile" if ("mobile" in ua or "android" in ua or "iphone" in ua) else "desktop"
    return {"os": os_name, "browser": browser, "device_type": device, "raw": ua[:160]}


def _urlquote(s: str) -> str:
    """Quote pra wa.me — escape básico (não pode importar urllib top-level
    porque o módulo já está enxuto, fica local)."""
    from urllib.parse import quote
    return quote(s or "", safe="")


def _public_venue(v: Dict[str, Any]) -> Dict[str, Any]:
    """Snapshot público do venue — esconde `router_secret`."""
    return {
        "id": v.get("id"),
        "slug": v.get("slug"),
        "name": v.get("name"),
        "address": v.get("address"),
        "type": v.get("type", "ligo"),
        "session_minutes": v.get("session_minutes", 60),
        "require_phone": v.get("require_phone", True),
        "require_email": v.get("require_email", False),
        "require_cpf": v.get("require_cpf", False),
        "whatsapp_number": v.get("whatsapp_number"),
        "whatsapp_message_template": v.get("whatsapp_message_template"),
        "brand": v.get("brand") or {},
        "active": v.get("active", True),
    }


# ───────────────────────── Pydantic ─────────────────────────

class VenueBrand(BaseModel):
    color_primary: str = "#6B2BFB"
    color_accent: str = "#FF6A1A"
    logo_url: Optional[str] = None
    background_url: Optional[str] = None
    welcome_title: str = "Bem-vindo ao WiFi grátis"
    welcome_subtitle: str = "Conecte-se em poucos segundos"


class VenueIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    address: Optional[str] = None
    type: str = "ligo"  # ligo | parceiro
    session_minutes: int = Field(60, ge=10, le=1440)
    require_phone: bool = True
    require_email: bool = False
    require_cpf: bool = False
    # iter216b — WhatsApp gating: número que recebe a msg do cliente.
    # Se vazio, sessão libera direto (sem proteção anti-bloqueio).
    whatsapp_number: Optional[str] = None
    whatsapp_message_template: Optional[str] = None
    brand: Optional[VenueBrand] = None
    active: bool = True


class CampaignIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=140)
    subtitle: str = ""
    banner_url: Optional[str] = None
    cta_label: str = "Saiba mais"
    cta_url: Optional[str] = None
    venue_id: Optional[str] = None  # None = global pra todos venues
    active_from: Optional[str] = None
    active_to: Optional[str] = None
    active: bool = True


class ConnectIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    phone: Optional[str] = None
    email: Optional[str] = None
    cpf: Optional[str] = None
    ad_id: Optional[str] = None


# ───────────────────────── Admin: Venues ─────────────────────────

@router.get("/venues")
async def list_venues(
    include_inactive: bool = False,
    user: dict = Depends(require_role("gestor")),
):
    cid = _user_company(user)
    q: Dict[str, Any] = {"company_id": cid}
    if not include_inactive:
        q["active"] = True
    items = await db.wifi_venues.find(q, {"_id": 0, "router_secret": 0}) \
        .sort("created_at", -1).to_list(500)
    return {"items": items, "count": len(items)}


@router.post("/venues")
async def create_venue(body: VenueIn,
                       user: dict = Depends(require_role("gestor"))):
    cid = _user_company(user)
    slug_base = _slugify(body.name)
    slug = slug_base
    n = 2
    while await db.wifi_venues.find_one({"company_id": cid, "slug": slug}):
        slug = f"{slug_base}-{n}"
        n += 1
    doc = {
        "id": f"wv-venue-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "slug": slug,
        "name": body.name,
        "address": body.address,
        "type": body.type,
        "session_minutes": body.session_minutes,
        "require_phone": body.require_phone,
        "require_email": body.require_email,
        "require_cpf": body.require_cpf,
        "brand": (body.brand.model_dump() if body.brand else VenueBrand().model_dump()),
        "active": body.active,
        "created_at": _utcnow(),
        "router_secret": secrets.token_urlsafe(24),
    }
    await db.wifi_venues.insert_one(doc)
    return {"ok": True, "venue": _public_venue(doc), "router_secret": doc["router_secret"]}


@router.put("/venues/{venue_id}")
async def update_venue(venue_id: str, body: VenueIn,
                       user: dict = Depends(require_role("gestor"))):
    cid = _user_company(user)
    upd = body.model_dump()
    if isinstance(upd.get("brand"), dict) is False and upd.get("brand"):
        upd["brand"] = upd["brand"].model_dump()
    upd["updated_at"] = _utcnow()
    r = await db.wifi_venues.find_one_and_update(
        {"company_id": cid, "id": venue_id},
        {"$set": upd},
        return_document=True,
        projection={"_id": 0, "router_secret": 0},
    )
    if not r:
        raise HTTPException(404, "Venue não encontrado.")
    return {"ok": True, "venue": _public_venue(r)}


@router.delete("/venues/{venue_id}")
async def delete_venue(venue_id: str,
                       user: dict = Depends(require_role("gestor"))):
    cid = _user_company(user)
    r = await db.wifi_venues.update_one(
        {"company_id": cid, "id": venue_id},
        {"$set": {"active": False, "deactivated_at": _utcnow()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Venue não encontrado.")
    return {"ok": True}


@router.post("/venues/{venue_id}/rotate-secret")
async def rotate_router_secret(venue_id: str,
                               user: dict = Depends(require_role("gestor"))):
    """Gera novo router_secret — usar com cuidado, invalida config atual."""
    cid = _user_company(user)
    new_secret = secrets.token_urlsafe(24)
    r = await db.wifi_venues.update_one(
        {"company_id": cid, "id": venue_id},
        {"$set": {"router_secret": new_secret, "updated_at": _utcnow()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Venue não encontrado.")
    return {"ok": True, "router_secret": new_secret}


# ───────────────────────── Admin: Visitors ─────────────────────────

@router.get("/visitors")
async def list_visitors(
    venue_id: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(100, le=500),
    user: dict = Depends(require_role("gestor")),
):
    cid = _user_company(user)
    q: Dict[str, Any] = {"company_id": cid}
    if venue_id:
        q["$or"] = [{"first_venue_id": venue_id}, {"last_venue_id": venue_id}]
    if search:
        rx = {"$regex": re.escape(search), "$options": "i"}
        q["$or"] = [
            {"name": rx}, {"phone": rx}, {"email": rx}, {"cpf": rx},
        ]
    items = await db.wifi_visitors.find(q, {"_id": 0}) \
        .sort("last_seen_at", -1).to_list(limit)
    return {"items": items, "count": len(items)}


# ───────────────────────── Admin: Sessions ─────────────────────────

@router.get("/sessions")
async def list_sessions(
    venue_id: Optional[str] = None,
    only_active: bool = False,
    limit: int = Query(100, le=500),
    user: dict = Depends(require_role("gestor")),
):
    cid = _user_company(user)
    q: Dict[str, Any] = {"company_id": cid}
    if venue_id:
        q["venue_id"] = venue_id
    if only_active:
        q["status"] = "active"
        q["expires_at"] = {"$gte": _utcnow()}
    items = await db.wifi_sessions.find(q, {"_id": 0, "release_token": 0}) \
        .sort("started_at", -1).to_list(limit)
    return {"items": items, "count": len(items)}


# ───────────────────────── Admin: Campaigns ─────────────────────────

@router.get("/campaigns")
async def list_campaigns(user: dict = Depends(require_role("gestor"))):
    cid = _user_company(user)
    items = await db.wifi_campaigns.find({"company_id": cid}, {"_id": 0}) \
        .sort("created_at", -1).to_list(200)
    return {"items": items, "count": len(items)}


@router.post("/campaigns")
async def create_campaign(body: CampaignIn,
                          user: dict = Depends(require_role("gestor"))):
    cid = _user_company(user)
    doc = {
        "id": f"wc-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        **body.model_dump(),
        "impressions": 0,
        "clicks": 0,
        "created_at": _utcnow(),
    }
    await db.wifi_campaigns.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "campaign": doc}


@router.put("/campaigns/{cid_param}")
async def update_campaign(cid_param: str, body: CampaignIn,
                          user: dict = Depends(require_role("gestor"))):
    cid = _user_company(user)
    upd = {**body.model_dump(), "updated_at": _utcnow()}
    r = await db.wifi_campaigns.find_one_and_update(
        {"company_id": cid, "id": cid_param},
        {"$set": upd}, return_document=True, projection={"_id": 0},
    )
    if not r:
        raise HTTPException(404, "Campanha não encontrada.")
    return {"ok": True, "campaign": r}


@router.delete("/campaigns/{cid_param}")
async def delete_campaign(cid_param: str,
                          user: dict = Depends(require_role("gestor"))):
    cid = _user_company(user)
    r = await db.wifi_campaigns.update_one(
        {"company_id": cid, "id": cid_param},
        {"$set": {"active": False, "deactivated_at": _utcnow()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Campanha não encontrada.")
    return {"ok": True}


# ───────────────────────── Admin: Stats ─────────────────────────

@router.get("/stats")
async def stats(user: dict = Depends(require_role("gestor"))):
    cid = _user_company(user)
    now = _utcnow()
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0,
                                                     second=0, microsecond=0)
    week_start = (today_start - timedelta(days=6)).isoformat()
    today_iso = today_start.isoformat()

    total_venues = await db.wifi_venues.count_documents(
        {"company_id": cid, "active": True})
    total_visitors = await db.wifi_visitors.count_documents(
        {"company_id": cid})
    sessions_active = await db.wifi_sessions.count_documents(
        {"company_id": cid, "status": "active", "expires_at": {"$gte": now}})
    sessions_today = await db.wifi_sessions.count_documents(
        {"company_id": cid, "started_at": {"$gte": today_iso}})
    sessions_week = await db.wifi_sessions.count_documents(
        {"company_id": cid, "started_at": {"$gte": week_start}})
    leads_synced = await db.wifi_visitors.count_documents(
        {"company_id": cid, "synced_funnel_at": {"$exists": True, "$ne": None}})
    conversion_pct = round(
        (leads_synced / total_visitors * 100) if total_visitors else 0, 1)

    return {
        "total_venues": total_venues,
        "total_visitors": total_visitors,
        "sessions_active": sessions_active,
        "sessions_today": sessions_today,
        "sessions_week": sessions_week,
        "leads_synced_to_funnel": leads_synced,
        "conversion_pct": conversion_pct,
    }


# ───────────────────────── Público: Captive Portal ─────────────────────────

@router.get("/public/showcase")
async def public_showcase_venues(limit: int = 100):
    """Vitrine pública: lista todos os venues ativos para o cliente Ligo
    descobrir pontos WiFi gratuitos próximos (cafés parceiros, eventos, lojas)."""
    cur = db.wifi_venues.find(
        {"active": True},
        {"_id": 0, "router_secret": 0},
    ).sort("name", 1).limit(int(limit))
    items = [_public_venue(v) async for v in cur]
    return {"items": items, "total": len(items)}


@router.get("/public/venue/{slug}")
async def public_venue_info(slug: str):
    """Info pública do venue — usado pela página captive."""
    v = await db.wifi_venues.find_one(
        {"slug": slug, "active": True}, {"_id": 0, "router_secret": 0})
    if not v:
        raise HTTPException(404, "Espaço não encontrado ou inativo.")
    # Pega campanha ativa (do venue ou global)
    now = _utcnow()
    camp = await db.wifi_campaigns.find_one(
        {
            "company_id": v["company_id"],
            "active": True,
            "$or": [{"venue_id": v["id"]}, {"venue_id": None}],
            "$and": [
                {"$or": [{"active_from": None}, {"active_from": {"$lte": now}}]},
                {"$or": [{"active_to": None}, {"active_to": {"$gte": now}}]},
            ],
        },
        {"_id": 0},
        sort=[("venue_id", -1), ("created_at", -1)],  # Prefere venue-specific
    )
    if camp:
        # Incrementa impression
        await db.wifi_campaigns.update_one({"id": camp["id"]},
                                           {"$inc": {"impressions": 1}})
    return {"venue": _public_venue(v), "campaign": camp}


@router.post("/public/venue/{slug}/connect")
async def public_connect(slug: str, body: ConnectIn, request: Request):
    """Visitante envia dados → cria visitor + session + sync funil."""
    v = await db.wifi_venues.find_one({"slug": slug, "active": True})
    if not v:
        raise HTTPException(404, "Espaço não encontrado ou inativo.")
    cid = v["company_id"]

    # Validações dos campos required do venue
    if v.get("require_phone", True) and not (body.phone or "").strip():
        raise HTTPException(400, "Telefone é obrigatório.")
    if v.get("require_email", False) and not (body.email or "").strip():
        raise HTTPException(400, "E-mail é obrigatório.")
    if v.get("require_cpf", False) and not (body.cpf or "").strip():
        raise HTTPException(400, "CPF é obrigatório.")

    phone_norm = _norm_phone(body.phone or "")
    email = (body.email or "").strip().lower() or None
    cpf = re.sub(r"\D", "", body.cpf or "") or None

    # UPSERT visitor (chave: phone se houver, senão email)
    visitor_key = {"company_id": cid}
    if phone_norm:
        visitor_key["phone"] = phone_norm
    elif email:
        visitor_key["email"] = email
    else:
        # Sem chave única — gera id novo
        visitor_key["_throwaway_id"] = uuid.uuid4().hex

    existing = await db.wifi_visitors.find_one(visitor_key, {"_id": 0})
    now = _utcnow()
    if existing:
        await db.wifi_visitors.update_one(
            {"id": existing["id"]},
            {"$set": {"last_seen_at": now, "last_venue_id": v["id"],
                      "name": body.name},
             "$inc": {"visits": 1}},
        )
        visitor_id = existing["id"]
    else:
        visitor_id = f"wv-{uuid.uuid4().hex[:10]}"
        await db.wifi_visitors.insert_one({
            "id": visitor_id,
            "company_id": cid,
            "name": body.name,
            "phone": phone_norm,
            "email": email,
            "cpf": cpf,
            "first_seen_at": now,
            "last_seen_at": now,
            "first_venue_id": v["id"],
            "last_venue_id": v["id"],
            "visits": 1,
            "tags": [f"lead-wifi-{v['slug']}"],
        })

    # Cria session — se venue tem whatsapp_number, fica PENDING até cliente
    # mandar a mensagem (anti-bloqueio WhatsApp: regra "cliente inicia").
    ua = request.headers.get("user-agent", "")
    session_id = f"wf-{uuid.uuid4().hex[:12]}"
    release_token = secrets.token_urlsafe(20)
    requires_whatsapp = bool(v.get("whatsapp_number"))
    unlock_code = secrets.token_hex(3).upper() if requires_whatsapp else None
    initial_status = "pending_whatsapp" if requires_whatsapp else "active"
    expires_at = (datetime.now(timezone.utc)
                  + timedelta(minutes=v.get("session_minutes", 60))).isoformat()
    await db.wifi_sessions.insert_one({
        "id": session_id,
        "company_id": cid,
        "venue_id": v["id"],
        "venue_slug": v["slug"],
        "visitor_id": visitor_id,
        "visitor_phone": phone_norm,
        "mac": request.headers.get("x-client-mac"),
        "ip": (request.client.host if request.client else None),
        "user_agent": ua[:240],
        "device": _parse_user_agent(ua),
        "started_at": now,
        "expires_at": expires_at,
        "ad_id": body.ad_id,
        "release_token": release_token,
        "unlock_code": unlock_code,
        "unlocked_at": None,
        "status": initial_status,
        "ad_impressions": 0,
        "ad_clicks": 0,
    })

    # Sync funnel (idempotente — UPSERT em sales_leads por phone+source)
    if phone_norm:
        source = f"wifi_hotspot_{v['slug']}"
        existing_lead = await db.sales_leads.find_one(
            {"company_id": cid, "phone": phone_norm, "source": source},
        )
        if not existing_lead:
            await db.sales_leads.insert_one({
                "id": f"lead-{uuid.uuid4().hex[:10]}",
                "company_id": cid,
                "name": body.name,
                "phone": phone_norm,
                "email": email,
                "source": source,
                "venue_id": v["id"],
                "venue_name": v["name"],
                "status": "new",
                "ts": now,
                "updated_at": now,
            })
        await db.wifi_visitors.update_one(
            {"id": visitor_id}, {"$set": {"synced_funnel_at": now}},
        )

    # Monta URL wa.me caso requer WhatsApp
    whatsapp_url = None
    if requires_whatsapp:
        venue_phone = re.sub(r"\D", "", v.get("whatsapp_number") or "")
        tpl = (v.get("whatsapp_message_template") or
               "Oi! Quero conectar no WiFi grátis da {venue}. Código: #{code}")
        msg = (tpl.replace("{venue}", v.get("name", ""))
                  .replace("{code}", unlock_code or "")
                  .replace("{name}", body.name or ""))
        whatsapp_url = (f"https://wa.me/{venue_phone}"
                        f"?text={_urlquote(msg)}")

    return {
        "ok": True,
        "session_id": session_id,
        "release_token": release_token,
        "expires_at": expires_at,
        "session_minutes": v.get("session_minutes", 60),
        "status": initial_status,
        "requires_whatsapp": requires_whatsapp,
        "unlock_code": unlock_code,
        "whatsapp_url": whatsapp_url,
    }


@router.get("/public/session/{token}/status")
async def session_status(token: str):
    """Endpoint pro roteador (Mikrotik / UniFi) e pro frontend captive consultar.

    Devolve `authorized:true` enquanto sessão estiver válida e o cliente
    JÁ tiver mandado mensagem no WhatsApp do venue (quando essa proteção
    estiver ativa).
    """
    sess = await db.wifi_sessions.find_one(
        {"release_token": token}, {"_id": 0, "release_token": 0})
    if not sess:
        return {"authorized": False, "reason": "token_not_found"}
    if sess["status"] == "pending_whatsapp":
        return {
            "authorized": False, "reason": "pending_whatsapp",
            "session_id": sess["id"],
        }
    if sess["status"] != "active":
        return {"authorized": False, "reason": "session_closed"}
    if sess["expires_at"] < _utcnow():
        # Auto-expira
        await db.wifi_sessions.update_one(
            {"id": sess["id"]}, {"$set": {"status": "expired"}})
        return {"authorized": False, "reason": "expired"}
    return {
        "authorized": True,
        "session_id": sess["id"],
        "expires_at": sess["expires_at"],
        "venue_slug": sess.get("venue_slug"),
    }


@router.post("/public/campaign/{campaign_id}/click")
async def click_campaign(campaign_id: str):
    """Registra clique no banner da campanha."""
    r = await db.wifi_campaigns.update_one(
        {"id": campaign_id}, {"$inc": {"clicks": 1}})
    if r.matched_count == 0:
        raise HTTPException(404, "Campanha não encontrada.")
    return {"ok": True}


# ───────────────────────── Hook: inbound WhatsApp ─────────────────────────

async def try_unlock_session_from_whatsapp(phone: str, text: str) -> Optional[Dict[str, Any]]:
    """Tenta liberar uma sessão WiFi pendente a partir de uma mensagem
    recebida no WhatsApp.

    Regra: a mensagem precisa conter o `unlock_code` (formato 6 hex chars)
    de uma sessão `pending_whatsapp` cujo `visitor_phone` bata com o phone
    de quem mandou. Retorna o doc da sessão liberada (sem _id) ou None.

    Chamado por `routes/whatsapp_baileys.py::inbound_webhook` após o salvar
    da mensagem — não bloqueia o fluxo padrão de IA/notificações.
    """
    phone_norm = _norm_phone(phone)
    text_up = (text or "").upper()
    # Acha sessão pending mais recente desse phone que tenha o código na msg
    pending = await db.wifi_sessions.find(
        {"visitor_phone": phone_norm, "status": "pending_whatsapp"},
        {"_id": 0},
    ).sort("started_at", -1).limit(5).to_list(5)
    for sess in pending:
        code = sess.get("unlock_code") or ""
        if code and code in text_up:
            now = _utcnow()
            await db.wifi_sessions.update_one(
                {"id": sess["id"]},
                {"$set": {"status": "active", "unlocked_at": now,
                          "unlocked_via": "whatsapp"}},
            )
            sess["status"] = "active"
            sess["unlocked_at"] = now
            logger.info(
                "[wifi-hotspot] sessão %s liberada via WhatsApp (phone=%s code=%s)",
                sess["id"], phone_norm[-4:] if phone_norm else "?", code,
            )
            return sess
    return None


# ───────────────────────── Jobs: abandonment ─────────────────────────

ABANDON_AFTER_MINUTES = 2
RETARGET_AFTER_HOURS = 48
RETARGET_MESSAGE = (
    "Oi {name}! 👋 Vi que você tentou conectar no WiFi grátis da {venue} "
    "ontem mas não chegou a mandar a mensagem. Tudo certo? "
    "Aproveita pra conhecer nossos planos de internet em casa — "
    "fibra óptica estável e atendimento de verdade. "
    "Te conto rapidinho?"
)


async def mark_abandoned_sessions_job() -> None:
    """Marca como `abandoned` qualquer sessão presa em `pending_whatsapp`
    há mais de ABANDON_AFTER_MINUTES. Roda a cada 2min via scheduler.
    """
    cutoff = (datetime.now(timezone.utc)
              - timedelta(minutes=ABANDON_AFTER_MINUTES)).isoformat()
    r = await db.wifi_sessions.update_many(
        {"status": "pending_whatsapp", "started_at": {"$lt": cutoff}},
        {"$set": {"status": "abandoned",
                  "abandoned_at": _utcnow(),
                  "retarget_queued": False}},
    )
    if r.modified_count:
        logger.info("[wifi-hotspot] %d sessões marcadas como abandoned",
                    r.modified_count)


async def retarget_abandoned_sessions_job() -> None:
    """Roda a cada hora. Procura sessões abandonadas há ~48h sem retarget
    ainda enviado e dispara WhatsApp via Baileys.

    Idempotente: marca `retarget_sent_at` ao despachar pra não duplicar.
    """
    now = datetime.now(timezone.utc)
    lower = (now - timedelta(hours=RETARGET_AFTER_HOURS + 1)).isoformat()
    upper = (now - timedelta(hours=RETARGET_AFTER_HOURS)).isoformat()
    candidates = await db.wifi_sessions.find(
        {
            "status": "abandoned",
            "abandoned_at": {"$gte": lower, "$lte": upper},
            "retarget_sent_at": {"$exists": False},
            "visitor_phone": {"$ne": None, "$nin": [""]},
        },
        {"_id": 0},
    ).limit(50).to_list(50)
    if not candidates:
        return

    try:
        from routes.whatsapp_baileys import _sidecar_post_silent
    except Exception as e:
        logger.warning("[wifi-hotspot] retarget skip — baileys indisponível: %s", e)
        return

    for sess in candidates:
        # Suprime se já enviamos retarget pra esse phone nos últimos 7d
        phone = sess.get("visitor_phone")
        recent = await db.wifi_sessions.find_one({
            "company_id": sess["company_id"],
            "visitor_phone": phone,
            "retarget_sent_at": {"$gte":
                (now - timedelta(days=7)).isoformat()},
        }, {"_id": 0, "id": 1})
        if recent:
            await db.wifi_sessions.update_one(
                {"id": sess["id"]},
                {"$set": {"retarget_sent_at": _utcnow(),
                          "retarget_status": "skipped_recent"}},
            )
            continue

        # Resolve venue + visitor
        venue = await db.wifi_venues.find_one({"id": sess["venue_id"]},
                                              {"_id": 0})
        visitor = await db.wifi_visitors.find_one(
            {"id": sess["visitor_id"]}, {"_id": 0})
        name = (visitor or {}).get("name", "").split(" ")[0] or "amigo(a)"
        venue_name = (venue or {}).get("name", "Ligo")
        text = RETARGET_MESSAGE.replace("{name}", name) \
                               .replace("{venue}", venue_name)

        # Dispara via Baileys sidecar
        try:
            sent = await _sidecar_post_silent("/send",
                                              {"phone": phone, "text": text})
            ok = bool(sent.get("ok"))
            # Persiste msg no histórico de conversas
            if ok:
                await db.aihub_wa_messages.insert_one({
                    "company_id": sess["company_id"],
                    "phone": phone,
                    "jid": f"{phone}@s.whatsapp.net",
                    "direction": "outbound",
                    "text": text,
                    "auto_reply": True,
                    "agent": "wifi_retarget_48h",
                    "delivery_status": "sent",
                    "external_id": sent.get("message_id"),
                    "created_at": _utcnow(),
                    "wifi_session_id": sess["id"],
                })
            await db.wifi_sessions.update_one(
                {"id": sess["id"]},
                {"$set": {"retarget_sent_at": _utcnow(),
                          "retarget_status": "sent" if ok else "failed",
                          "retarget_text": text}},
            )
            if ok:
                logger.info("[wifi-hotspot] retarget enviado pro phone=%s "
                            "(venue=%s, sess=%s)",
                            phone[-4:] if phone else "?", venue_name, sess["id"])
        except Exception as e:
            logger.warning("[wifi-hotspot] retarget falhou sess=%s err=%s",
                           sess["id"], e)
            await db.wifi_sessions.update_one(
                {"id": sess["id"]},
                {"$set": {"retarget_sent_at": _utcnow(),
                          "retarget_status": "error",
                          "retarget_error": str(e)[:200]}},
            )
