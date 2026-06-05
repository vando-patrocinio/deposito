"""
parceria.py — Módulo de Parcerias Comerciais (loyalty/voucher).

Conceito:
  Provedor (Ligo) faz parceria com comércios locais (pizzaria, farmácia…).
  Cada assinante Ligo tem um QR slave único. O parceiro abre o app/portal,
  escaneia o QR do cliente, o sistema valida elegibilidade (assinante
  adimplente com > 30 dias de contrato) e registra a redenção da promoção.
  Mensalmente a Ligo reembolsa o parceiro (R$X por redenção válida).

Coleções:
  parcerias_partners       — comércio parceiro
                              {id, name, category, logo_url, address,
                               city, neighborhood, phone, website,
                               description, color, reimbursement_rate_default,
                               active, monthly_due_total, contract_signed_at}
  parcerias_promotions     — promoções/cupons publicados
                              {id, partner_id, title, description, image,
                               offer_summary (ex: "Pizza por R$1"),
                               reimbursement_value (R$ Ligo paga ao parceiro
                                 por redenção),
                               max_uses_per_client, period (day|week|month|
                                 year|campaign|none),
                               starts_at, ends_at, active, total_budget,
                               total_redemptions, total_due}
  parcerias_partner_users  — login do parceiro
                              {id, partner_id, email (unique), password_hash,
                               name, role (owner|staff), invite_token,
                               active}
  parcerias_redemptions    — uso/redenção
                              {id, partner_id, promotion_id, client_id
                               (subscriber id), client_name, client_pppoe,
                               redeemed_at, partner_user_email,
                               reimbursement_value, paid, paid_at,
                               voucher_code (referência exibida no app)}
  client_qr_tokens         — QR slave por cliente
                              {client_id, token (24+ chars), created_at,
                               last_rotated_at}
  client_portal_users      — login do app cliente (reusa subscribers.email
                              mas senha é separada — bcrypt)
                              {id, subscriber_id, email (unique),
                               password_hash, active, created_at}

Endpoints públicos (gateway → backend):
  GET  /api/parcerias/public/showcase         vitrine pública (sem auth)
  POST /api/parcerias/public/lead             captura lead

Endpoints autenticados (SmartProv gestor):
  CRUD /api/parcerias/partners
  CRUD /api/parcerias/promotions
  GET  /api/parcerias/redemptions
  POST /api/parcerias/redemptions/{id}/mark-paid
  POST /api/parcerias/partners/{id}/users     criar acesso do parceiro
  GET  /api/parcerias/partners/{id}/payout-summary

Endpoints do PORTAL DO PARCEIRO (?portal=parceiro):
  POST /api/parceiro-portal/auth/login
  GET  /api/parceiro-portal/me
  GET  /api/parceiro-portal/promotions
  POST /api/parceiro-portal/scan              valida QR + aplica
  GET  /api/parceiro-portal/redemptions

Endpoints do PORTAL DO CLIENTE (?portal=cliente):
  POST /api/cliente-portal/auth/login
  POST /api/cliente-portal/auth/quick-login   email + cpf curto (assinantes)
  GET  /api/cliente-portal/me                 retorna assinante + QR token
  GET  /api/cliente-portal/promotions         promos públicas visíveis
  GET  /api/cliente-portal/my-redemptions
  POST /api/cliente-portal/qr/rotate          regenera token (segurança)
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, List, Literal

import jwt
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, EmailStr, Field

from auth import hash_password, verify_password, _jwt_secret
from core import DEMO_COMPANY_ID, get_current_user, is_super_admin
from database import db

logger = logging.getLogger("ponto.parceria")
router = APIRouter(prefix="/api/parcerias", tags=["parcerias"])
partner_router = APIRouter(prefix="/api/parceiro-portal",
                            tags=["parceiro-portal"])
client_router = APIRouter(prefix="/api/cliente-portal",
                           tags=["cliente-portal"])

JWT_ALGO = "HS256"
PARTNER_TTL_DAYS = 30
CLIENT_TTL_DAYS = 30
QR_TOKEN_PREFIX = "LIGO:"


# ─────────────────────── helpers ────────────────────────
def _cid(user: dict) -> str:
    if is_super_admin(user):
        return (user.get("_active_company") or user.get("company_id")
                or DEMO_COMPANY_ID)
    return user.get("company_id") or DEMO_COMPANY_ID


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_manager(user: dict):
    role = (user.get("role") or "").lower()
    roles = user.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    if not (is_super_admin(user)
            or role in ("gestor", "administrador", "admin", "super_admin")
            or any(r in {"gestor", "admin", "super_admin"} for r in roles)):
        raise HTTPException(403, "Apenas gestor/admin.")


async def _ensure_client_qr_token(subscriber_id: str) -> str:
    doc = await db.client_qr_tokens.find_one({"client_id": subscriber_id},
                                                {"_id": 0})
    if doc and doc.get("token"):
        return doc["token"]
    token = secrets.token_urlsafe(24)
    await db.client_qr_tokens.update_one(
        {"client_id": subscriber_id},
        {"$set": {"client_id": subscriber_id, "token": token,
                    "created_at": _now_iso(),
                    "last_rotated_at": _now_iso()}},
        upsert=True,
    )
    return token


def _slugify(text: str) -> str:
    """Gera slug url-safe a partir do nome do parceiro."""
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", text or "") \
        .encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:60] or "parceiro"


async def _ensure_unique_slug(name: str, cid: str,
                                exclude_id: Optional[str] = None) -> str:
    base = _slugify(name)
    slug = base
    n = 1
    while True:
        q = {"slug": slug, "company_id": cid}
        if exclude_id:
            q["id"] = {"$ne": exclude_id}
        if not await db.parcerias_partners.find_one(q):
            return slug
        n += 1
        slug = f"{base}-{n}"


async def _partner_avg_rating(partner_id: str) -> dict:
    pipe = [{"$match": {"partner_id": partner_id}},
            {"$group": {"_id": None,
                          "avg": {"$avg": "$stars"},
                          "count": {"$sum": 1}}}]
    agg = await db.parcerias_ratings.aggregate(pipe).to_list(1)
    if not agg:
        return {"avg": 0, "count": 0}
    return {"avg": round(agg[0]["avg"] or 0, 2),
             "count": agg[0]["count"]}


async def _promo_avg_rating(promotion_id: str) -> dict:
    pipe = [{"$match": {"promotion_id": promotion_id}},
            {"$group": {"_id": None,
                          "avg": {"$avg": "$stars"},
                          "count": {"$sum": 1}}}]
    agg = await db.parcerias_ratings.aggregate(pipe).to_list(1)
    if not agg:
        return {"avg": 0, "count": 0}
    return {"avg": round(agg[0]["avg"] or 0, 2),
             "count": agg[0]["count"]}


# ─────────────────────── eligibility ────────────────────────
async def _check_eligibility(subscriber: dict, promotion: dict) -> dict:
    """Regra padrão: assinante ATIVO, adimplente e com > 30 dias de
    ativação. Retorna {ok, reason}. Limites por promoção também são
    aplicados aqui."""
    status = (subscriber.get("status") or "").upper()
    if status not in ("ATIVO", "ATIVA"):
        return {"ok": False, "reason": f"Cliente com status {status}"}

    fin = (subscriber.get("financial_status") or "").lower()
    if fin in ("inadimplente", "atrasado", "bloqueado", "atraso"):
        return {"ok": False, "reason": "Cliente em débito (inadimplente)"}

    act = subscriber.get("activation_date") or subscriber.get("created_at")
    if act:
        try:
            d = act if isinstance(act, datetime) else datetime.fromisoformat(
                act.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            days_active = (_now() - d).days
            if days_active < 30:
                return {"ok": False,
                          "reason":
                            f"Contrato muito recente "
                            f"({days_active}d, mínimo 30d)"}
        except Exception:
            pass

    # Janela da promoção
    starts = promotion.get("starts_at")
    ends = promotion.get("ends_at")
    if starts:
        try:
            s = datetime.fromisoformat(starts.replace("Z", "+00:00"))
            if _now() < s:
                return {"ok": False, "reason": "Promoção ainda não começou"}
        except Exception:
            pass
    if ends:
        try:
            e = datetime.fromisoformat(ends.replace("Z", "+00:00"))
            if _now() > e:
                return {"ok": False, "reason": "Promoção encerrada"}
        except Exception:
            pass

    # Limite por cliente
    max_uses = int(promotion.get("max_uses_per_client") or 0)
    period = promotion.get("period") or "campaign"
    if max_uses > 0:
        q = {"client_id": subscriber["id"],
             "promotion_id": promotion["id"]}
        if period == "day":
            since = _now() - timedelta(days=1)
            q["redeemed_at"] = {"$gte": since.isoformat()}
        elif period == "week":
            since = _now() - timedelta(days=7)
            q["redeemed_at"] = {"$gte": since.isoformat()}
        elif period == "month":
            since = _now() - timedelta(days=30)
            q["redeemed_at"] = {"$gte": since.isoformat()}
        elif period == "year":
            since = _now() - timedelta(days=365)
            q["redeemed_at"] = {"$gte": since.isoformat()}
        used = await db.parcerias_redemptions.count_documents(q)
        if used >= max_uses:
            return {"ok": False,
                      "reason":
                        f"Limite atingido ({used}/{max_uses} por "
                        f"{period})"}

    return {"ok": True, "reason": "Cliente elegível"}


# ────────────────────────── models ──────────────────────────
PromoPeriod = Literal["day", "week", "month", "year", "campaign", "none"]


class PartnerIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    category: str = "Outros"                # Pizzaria, Farmácia, Oficina…
    logo_url: Optional[str] = ""
    cover_url: Optional[str] = ""
    address: Optional[str] = ""
    city: Optional[str] = ""
    neighborhood: Optional[str] = ""
    phone: Optional[str] = ""
    website: Optional[str] = ""
    description: Optional[str] = ""
    color: Optional[str] = "#dc2626"        # destaque na vitrine
    reimbursement_rate_default: float = 0.0
    contract_signed_at: Optional[str] = None
    active: bool = True


class PromotionIn(BaseModel):
    partner_id: str
    title: str = Field(..., min_length=2, max_length=160)
    offer_summary: str = Field(..., min_length=2, max_length=160)
    description: Optional[str] = ""
    image_url: Optional[str] = ""
    # iter231 — categoria do produto/serviço da promoção. Independente
    # da categoria do parceiro (a pizzaria pode ter promoção de "bebida"
    # ou "sobremesa"). Frontend manda string livre, normalizamos.
    product_category: Optional[str] = ""
    reimbursement_value: float = Field(..., ge=0)
    discount_pct: float = Field(0, ge=0, le=100)
    original_price: float = 0
    promo_price: float = 0
    max_uses_per_client: int = 1
    period: PromoPeriod = "month"
    starts_at: Optional[str] = None
    ends_at: Optional[str] = None
    total_budget: float = 0
    terms: Optional[str] = ""
    active: bool = True


class PartnerUserIn(BaseModel):
    email: EmailStr
    password: str
    name: str = ""
    role: Literal["owner", "staff"] = "owner"


class PortalLoginIn(BaseModel):
    email: EmailStr
    password: str


class ScanIn(BaseModel):
    qr_token: str
    promotion_id: str
    note: Optional[str] = ""


class ClientQuickLoginIn(BaseModel):
    email: EmailStr
    document: Optional[str] = ""    # CPF curto pra confirmar identidade


# ─────────────────────── índices ────────────────────────
async def ensure_indexes() -> None:
    try:
        await db.parcerias_partner_users.create_index("email", unique=True)
        await db.client_qr_tokens.create_index("client_id", unique=True)
        await db.client_qr_tokens.create_index("token", unique=True)
        await db.parcerias_redemptions.create_index(
            [("partner_id", 1), ("redeemed_at", -1)])
        await db.parcerias_redemptions.create_index(
            [("client_id", 1), ("promotion_id", 1), ("redeemed_at", -1)])
        await db.client_portal_users.create_index("email", unique=True)
        await db.parcerias_partners.create_index(
            [("company_id", 1), ("slug", 1)], unique=True, sparse=True)
        await db.parcerias_ratings.create_index(
            [("redemption_id", 1)], unique=True)
        await db.parcerias_ratings.create_index(
            [("partner_id", 1), ("created_at", -1)])
        await db.parcerias_ratings.create_index(
            [("promotion_id", 1)])
        logger.info("[parcerias] indexes ensured")
    except Exception as e:
        logger.warning("[parcerias] ensure_indexes falhou: %s", e)


# ═══════════════════════ ADMIN CRUD ═══════════════════════
@router.get("/partners")
async def list_partners(user: dict = Depends(get_current_user)):
    cur = db.parcerias_partners.find({"company_id": _cid(user)},
                                        {"_id": 0}).sort("name", 1)
    return await cur.to_list(2000)


@router.post("/partners")
async def create_partner(payload: PartnerIn,
                          user: dict = Depends(get_current_user)):
    _require_manager(user)
    pid = f"pa-{uuid.uuid4().hex[:12]}"
    cid = _cid(user)
    slug = await _ensure_unique_slug(payload.name, cid)
    magic_token = secrets.token_urlsafe(28)
    doc = payload.model_dump()
    doc.update({"id": pid, "company_id": cid, "slug": slug,
                 "magic_token": magic_token,
                 "created_at": _now_iso(), "created_by": user.get("id"),
                 "monthly_due_total": 0.0})
    await db.parcerias_partners.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.post("/partners/{pid}/rotate-magic-link")
async def rotate_magic_link(pid: str,
                              user: dict = Depends(get_current_user)):
    """Gera novo magic link e invalida o anterior."""
    _require_manager(user)
    new_token = secrets.token_urlsafe(28)
    r = await db.parcerias_partners.update_one(
        {"id": pid, "company_id": _cid(user)},
        {"$set": {"magic_token": new_token,
                    "magic_rotated_at": _now_iso()}})
    if r.matched_count == 0:
        raise HTTPException(404)
    return {"magic_token": new_token}


@router.put("/partners/{pid}")
async def update_partner(pid: str, payload: PartnerIn,
                          user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = _cid(user)
    upd = payload.model_dump(exclude_unset=True)
    upd["updated_at"] = _now_iso()
    # Recalcula slug se nome mudou
    if "name" in upd and upd["name"]:
        existing = await db.parcerias_partners.find_one(
            {"id": pid, "company_id": cid}, {"name": 1, "slug": 1})
        if existing and existing.get("name") != upd["name"]:
            upd["slug"] = await _ensure_unique_slug(
                upd["name"], cid, exclude_id=pid)
    r = await db.parcerias_partners.update_one(
        {"id": pid, "company_id": cid}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(404)
    return {"ok": True}


@router.delete("/partners/{pid}")
async def delete_partner(pid: str,
                          user: dict = Depends(get_current_user)):
    _require_manager(user)
    r = await db.parcerias_partners.delete_one(
        {"id": pid, "company_id": _cid(user)})
    if r.deleted_count == 0:
        raise HTTPException(404)
    await db.parcerias_promotions.update_many(
        {"partner_id": pid}, {"$set": {"active": False}})
    return {"ok": True}


@router.get("/promotions")
async def list_promotions(partner_id: Optional[str] = None,
                            user: dict = Depends(get_current_user)):
    q = {"company_id": _cid(user)}
    if partner_id:
        q["partner_id"] = partner_id
    cur = db.parcerias_promotions.find(q, {"_id": 0}).sort("created_at", -1)
    rows = await cur.to_list(2000)
    return rows


@router.post("/promotions")
async def create_promotion(payload: PromotionIn,
                            user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = _cid(user)
    partner = await db.parcerias_partners.find_one(
        {"id": payload.partner_id, "company_id": cid})
    if not partner:
        raise HTTPException(404, "Parceiro não encontrado")
    pid = f"pr-{uuid.uuid4().hex[:12]}"
    doc = payload.model_dump()
    doc.update({"id": pid, "company_id": cid,
                 "partner_name": partner["name"],
                 "partner_category": partner.get("category", ""),
                 "partner_color": partner.get("color", "#dc2626"),
                 "partner_logo": partner.get("logo_url", ""),
                 "total_redemptions": 0, "total_due": 0.0,
                 "created_at": _now_iso(),
                 "created_by": user.get("id")})
    await db.parcerias_promotions.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/promotions/{pid}")
async def update_promotion(pid: str, payload: PromotionIn,
                            user: dict = Depends(get_current_user)):
    _require_manager(user)
    upd = payload.model_dump(exclude_unset=True)
    upd["updated_at"] = _now_iso()
    r = await db.parcerias_promotions.update_one(
        {"id": pid, "company_id": _cid(user)}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(404)
    return {"ok": True}


@router.delete("/promotions/{pid}")
async def delete_promotion(pid: str,
                            user: dict = Depends(get_current_user)):
    _require_manager(user)
    r = await db.parcerias_promotions.update_one(
        {"id": pid, "company_id": _cid(user)},
        {"$set": {"active": False, "deleted_at": _now_iso()}})
    if r.matched_count == 0:
        raise HTTPException(404)
    return {"ok": True}


@router.get("/redemptions")
async def list_redemptions(partner_id: Optional[str] = None,
                            paid: Optional[bool] = None,
                            limit: int = 500,
                            user: dict = Depends(get_current_user)):
    q = {"company_id": _cid(user)}
    if partner_id:
        q["partner_id"] = partner_id
    if paid is not None:
        q["paid"] = paid
    cur = db.parcerias_redemptions.find(q, {"_id": 0}) \
        .sort("redeemed_at", -1).limit(limit)
    return await cur.to_list(limit)


@router.post("/redemptions/{rid}/mark-paid")
async def mark_paid(rid: str, user: dict = Depends(get_current_user)):
    _require_manager(user)
    r = await db.parcerias_redemptions.update_one(
        {"id": rid, "company_id": _cid(user), "paid": False},
        {"$set": {"paid": True, "paid_at": _now_iso(),
                    "paid_by": user.get("email", "")}})
    if r.matched_count == 0:
        raise HTTPException(404, "Redenção já paga ou inexistente")
    return {"ok": True}


@router.get("/partners/{pid}/payout-summary")
async def payout_summary(pid: str,
                          user: dict = Depends(get_current_user)):
    cid = _cid(user)
    partner = await db.parcerias_partners.find_one(
        {"id": pid, "company_id": cid}, {"_id": 0})
    if not partner:
        raise HTTPException(404)
    total = await db.parcerias_redemptions.count_documents(
        {"partner_id": pid, "company_id": cid})
    pending = await db.parcerias_redemptions.count_documents(
        {"partner_id": pid, "company_id": cid, "paid": False})
    pipe = [{"$match": {"partner_id": pid, "company_id": cid,
                          "paid": False}},
            {"$group": {"_id": None,
                          "due": {"$sum": "$reimbursement_value"}}}]
    agg = await db.parcerias_redemptions.aggregate(pipe).to_list(1)
    due = agg[0]["due"] if agg else 0.0
    return {"partner": partner, "total_redemptions": total,
             "pending_redemptions": pending,
             "amount_due": round(due, 2)}


@router.post("/partners/{pid}/users")
async def create_partner_user(pid: str, payload: PartnerUserIn,
                                user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = _cid(user)
    partner = await db.parcerias_partners.find_one(
        {"id": pid, "company_id": cid})
    if not partner:
        raise HTTPException(404, "Parceiro não encontrado")
    email = payload.email.lower().strip()
    if await db.parcerias_partner_users.find_one({"email": email}):
        raise HTTPException(409, "E-mail já cadastrado")
    uid = f"pau-{uuid.uuid4().hex[:12]}"
    doc = {"id": uid, "email": email, "name": payload.name.strip(),
            "role": payload.role,
            "password_hash": hash_password(payload.password),
            "partner_id": pid, "partner_name": partner["name"],
            "company_id": cid, "active": True,
            "created_at": _now_iso(), "created_by": user.get("id")}
    await db.parcerias_partner_users.insert_one(doc)
    return {"id": uid, "email": email, "name": doc["name"]}


@router.get("/partners/{pid}/users")
async def list_partner_users(pid: str,
                              user: dict = Depends(get_current_user)):
    _require_manager(user)
    cur = db.parcerias_partner_users.find(
        {"partner_id": pid, "company_id": _cid(user)},
        {"_id": 0, "password_hash": 0}).sort("created_at", -1)
    return await cur.to_list(200)


@router.get("/uploads/{fname}")
async def serve_partner_upload(fname: str):
    """Serve imagens de promoções enviadas pelo parceiro."""
    from fastapi.responses import FileResponse
    import os
    safe = os.path.basename(fname)
    fpath = os.path.join("/app/backend/uploads/parcerias", safe)
    if not os.path.exists(fpath):
        raise HTTPException(404)
    return FileResponse(fpath)


# ═══════════════════════ PUBLIC SHOWCASE ═══════════════════════
# iter235 — Landing comercial /seja-parceiro: lead capture
class PartnerApplicationIn(BaseModel):
    business_name: str = Field(..., min_length=2, max_length=160)
    contact_name: str = Field(..., min_length=2, max_length=120)
    whatsapp: str = Field(..., min_length=8, max_length=24)
    email: Optional[str] = ""
    city: Optional[str] = ""
    segment: Optional[str] = ""
    monthly_clients: Optional[str] = ""
    has_physical_store: bool = True
    notes: Optional[str] = ""


@router.post("/public/apply")
async def public_partner_apply(payload: PartnerApplicationIn):
    """Recebe lead de empresa que quer ser parceira (landing comercial).
    Grava em `parcerias_partner_applications` pro admin avaliar."""
    doc = payload.model_dump()
    doc.update({
        "id": "pap-" + uuid.uuid4().hex[:14],
        "status": "pending",
        "created_at": _now_iso(),
    })
    await db.parcerias_partner_applications.insert_one(doc)
    return {"ok": True, "id": doc["id"]}


@router.get("/public/showcase")
async def public_showcase(company_id: Optional[str] = None,
                            category: Optional[str] = None,
                            city: Optional[str] = None):
    cid = company_id or DEMO_COMPANY_ID
    pq = {"company_id": cid, "active": True}
    if category:
        pq["category"] = category
    if city:
        pq["city"] = city
    partners = await db.parcerias_partners.find(
        pq, {"_id": 0, "magic_token": 0}) \
        .sort("name", 1).to_list(500)
    if not partners:
        return {"partners": [], "promotions": [], "categories": []}

    ids = [p["id"] for p in partners]
    proms = await db.parcerias_promotions.find(
        {"partner_id": {"$in": ids}, "active": True},
        {"_id": 0}).sort("created_at", -1).to_list(500)
    # Enriquece com avg rating por promoção
    for pr in proms:
        rt = await _promo_avg_rating(pr["id"])
        pr["rating_avg"] = rt["avg"]
        pr["rating_count"] = rt["count"]
    # Enriquece partners com rating
    for pa in partners:
        rt = await _partner_avg_rating(pa["id"])
        pa["rating_avg"] = rt["avg"]
        pa["rating_count"] = rt["count"]
    cats = sorted({p.get("category", "Outros") for p in partners})
    return {"partners": partners, "promotions": proms,
             "categories": cats}


def _mask_client_name(name: str) -> str:
    """Anonimiza parcialmente: 'Maria Cliente Ligo' → 'Maria C.'"""
    parts = (name or "").strip().split()
    if not parts:
        return "Cliente Ligo"
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[-1][0].upper()}."


@router.get("/public/partner/{slug}")
async def public_partner_detail(slug: str,
                                  company_id: Optional[str] = None):
    """Página pública individual do parceiro. Retorna parceiro,
    promoções ativas, redenções recentes (mascaradas) e ratings."""
    cid = company_id or DEMO_COMPANY_ID
    partner = await db.parcerias_partners.find_one(
        {"slug": slug, "company_id": cid, "active": True},
        {"_id": 0, "magic_token": 0})
    if not partner:
        raise HTTPException(404, "Parceiro não encontrado")

    proms = await db.parcerias_promotions.find(
        {"partner_id": partner["id"], "active": True},
        {"_id": 0}).sort("created_at", -1).to_list(200)
    for pr in proms:
        rt = await _promo_avg_rating(pr["id"])
        pr["rating_avg"] = rt["avg"]
        pr["rating_count"] = rt["count"]

    # Redenções recentes — mascarar nome
    reds_raw = await db.parcerias_redemptions.find(
        {"partner_id": partner["id"]},
        {"_id": 0}).sort("redeemed_at", -1).limit(30).to_list(30)
    reds = [{
        "id": r["id"],
        "client_name": _mask_client_name(r.get("client_name", "")),
        "promotion_title": r.get("promotion_title", ""),
        "redeemed_at": r.get("redeemed_at"),
    } for r in reds_raw]

    # Últimas avaliações (com nome mascarado)
    ratings_raw = await db.parcerias_ratings.find(
        {"partner_id": partner["id"]}, {"_id": 0}) \
        .sort("created_at", -1).limit(30).to_list(30)
    ratings = [{
        "stars": rt["stars"],
        "comment": rt.get("comment", ""),
        "client_name": _mask_client_name(rt.get("client_name", "")),
        "promotion_title": rt.get("promotion_title", ""),
        "created_at": rt.get("created_at"),
    } for rt in ratings_raw]

    avg = await _partner_avg_rating(partner["id"])
    total_redemptions = await db.parcerias_redemptions.count_documents(
        {"partner_id": partner["id"]})

    return {"partner": partner, "promotions": proms,
             "recent_redemptions": reds, "ratings": ratings,
             "rating_avg": avg["avg"], "rating_count": avg["count"],
             "total_redemptions": total_redemptions}


# ═══════════════════════ PARTNER PORTAL ═══════════════════════
def _issue_partner_token(u: dict) -> str:
    payload = {"sub": u["id"], "email": u["email"],
                "name": u.get("name", ""),
                "partner_id": u["partner_id"],
                "partner_name": u.get("partner_name", ""),
                "company_id": u["company_id"],
                "role": u.get("role", "owner"),
                "type": "partner_portal",
                "iat": int(_now().timestamp()),
                "exp": int((_now() + timedelta(
                  days=PARTNER_TTL_DAYS)).timestamp())}
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGO)


async def get_partner_user(authorization: Optional[str] =
                             Header(None, alias="Authorization")) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Não autenticado")
    token = authorization.split(" ", 1)[1].strip()
    try:
        p = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGO])
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"Token inválido: {e}")
    if p.get("type") != "partner_portal":
        raise HTTPException(403, "Token não é do portal parceiro")
    return p


@partner_router.post("/auth/login")
async def partner_login(payload: PortalLoginIn):
    user = await db.parcerias_partner_users.find_one(
        {"email": payload.email.lower().strip(), "active": True},
        {"_id": 0})
    if not user or not verify_password(payload.password,
                                          user.get("password_hash", "")):
        raise HTTPException(401, "E-mail ou senha inválidos")
    partner = await db.parcerias_partners.find_one(
        {"id": user["partner_id"]}, {"_id": 0})
    token = _issue_partner_token(user)
    return {"access_token": token, "token_type": "bearer",
             "user": {"id": user["id"], "email": user["email"],
                       "name": user.get("name", ""),
                       "role": user.get("role", "owner")},
             "partner": partner}


@partner_router.post("/auth/magic")
async def partner_magic_login(payload: dict):
    """Login via magic link (link único enviado ao parceiro).
    Body: { magic_token: '...' }. Retorna JWT 30 dias."""
    tk = (payload or {}).get("magic_token", "").strip()
    if not tk:
        raise HTTPException(400, "magic_token obrigatório")
    partner = await db.parcerias_partners.find_one(
        {"magic_token": tk, "active": True}, {"_id": 0})
    if not partner:
        raise HTTPException(404, "Link inválido ou expirado")
    # Cria pseudo-user (sessão de magic link)
    pseudo = {"id": f"magic-{partner['id']}",
                "email": f"magic@{partner.get('slug', 'partner')}.ligo",
                "name": partner.get("name", ""),
                "role": "owner",
                "partner_id": partner["id"],
                "partner_name": partner["name"],
                "company_id": partner["company_id"]}
    token = _issue_partner_token(pseudo)
    return {"access_token": token, "token_type": "bearer",
             "user": {"id": pseudo["id"], "email": pseudo["email"],
                       "name": pseudo["name"], "role": "owner"},
             "partner": partner}


@partner_router.post("/upload-image")
async def partner_upload_image(payload: dict,
                                 u: dict = Depends(get_partner_user)):
    """Salva imagem base64 dentro de /uploads e retorna URL pública.
    Body: { data_url: 'data:image/jpeg;base64,...' }"""
    import base64
    import os
    data_url = (payload or {}).get("data_url", "")
    if not data_url.startswith("data:image"):
        raise HTTPException(400, "data_url inválido")
    header, b64 = data_url.split(",", 1)
    mime = header.split(";")[0].split(":")[1]
    ext = mime.split("/")[-1].lower().replace("jpeg", "jpg")
    if ext not in ("png", "jpg", "webp", "gif"):
        raise HTTPException(400, f"Formato não suportado: {ext}")
    try:
        data = base64.b64decode(b64)
    except Exception as e:
        raise HTTPException(400, f"base64 inválido: {e}") from e
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(400, "Imagem maior que 5MB")
    folder = "/app/backend/uploads/parcerias"
    os.makedirs(folder, exist_ok=True)
    fname = f"{u['partner_id']}-{secrets.token_hex(6)}.{ext}"
    fpath = os.path.join(folder, fname)
    with open(fpath, "wb") as f:
        f.write(data)
    url = f"/api/parcerias/uploads/{fname}"
    return {"url": url, "size": len(data)}


@partner_router.get("/me")
async def partner_me(u: dict = Depends(get_partner_user)):
    partner = await db.parcerias_partners.find_one(
        {"id": u["partner_id"]}, {"_id": 0})
    pending = await db.parcerias_redemptions.count_documents(
        {"partner_id": u["partner_id"], "paid": False})
    pipe = [{"$match": {"partner_id": u["partner_id"], "paid": False}},
            {"$group": {"_id": None,
                          "due": {"$sum": "$reimbursement_value"}}}]
    agg = await db.parcerias_redemptions.aggregate(pipe).to_list(1)
    due = agg[0]["due"] if agg else 0.0
    return {"user": {"id": u["sub"], "email": u["email"],
                      "name": u.get("name", ""),
                      "role": u.get("role", "owner")},
             "partner": partner,
             "pending_payout": round(due, 2),
             "pending_count": pending}


# iter230 — parceiro completa o próprio perfil pelo magic link
class PartnerProfileIn(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None       # WhatsApp
    address: Optional[str] = None
    city: Optional[str] = None
    neighborhood: Optional[str] = None
    description: Optional[str] = None
    logo_url: Optional[str] = None
    website: Optional[str] = None


@partner_router.put("/me")
async def partner_update_profile(payload: PartnerProfileIn,
                                    u: dict = Depends(get_partner_user)):
    """O próprio parceiro atualiza seus dados de perfil pelo app.
    Inclui WhatsApp, endereço e logo."""
    upd = {k: v for k, v in payload.model_dump(exclude_unset=True).items()
              if v is not None}
    if not upd:
        return {"ok": True, "updated": 0}
    upd["updated_at"] = _now_iso()
    upd["updated_by_partner"] = True
    r = await db.parcerias_partners.update_one(
        {"id": u["partner_id"]}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(404, "Parceiro não encontrado")
    # Se mudou nome/logo, propaga pras promoções já criadas
    if "name" in upd or "logo_url" in upd:
        propagate = {}
        if "name" in upd:
            propagate["partner_name"] = upd["name"]
        if "logo_url" in upd:
            propagate["partner_logo"] = upd["logo_url"]
        await db.parcerias_promotions.update_many(
            {"partner_id": u["partner_id"]}, {"$set": propagate})
    return {"ok": True, "updated": len(upd) - 2}


@partner_router.get("/promotions")
async def partner_promos(u: dict = Depends(get_partner_user)):
    cur = db.parcerias_promotions.find(
        {"partner_id": u["partner_id"], "active": True},
        {"_id": 0}).sort("created_at", -1)
    return await cur.to_list(500)


@partner_router.post("/scan")
async def partner_scan(payload: ScanIn,
                        u: dict = Depends(get_partner_user)):
    token = payload.qr_token.strip()
    if token.upper().startswith(QR_TOKEN_PREFIX):
        token = token[len(QR_TOKEN_PREFIX):]
    qr = await db.client_qr_tokens.find_one({"token": token},
                                               {"_id": 0})
    if not qr:
        raise HTTPException(404, "QR inválido ou não cadastrado")
    subscriber = await db.subscribers.find_one(
        {"id": qr["client_id"]}, {"_id": 0})
    if not subscriber:
        raise HTTPException(404, "Cliente não encontrado")

    promotion = await db.parcerias_promotions.find_one(
        {"id": payload.promotion_id, "partner_id": u["partner_id"],
         "active": True}, {"_id": 0})
    if not promotion:
        raise HTTPException(404, "Promoção não encontrada ou inativa")

    elig = await _check_eligibility(subscriber, promotion)
    if not elig["ok"]:
        return {"ok": False, "reason": elig["reason"],
                 "client": {"name": subscriber.get("name", ""),
                              "pppoe": subscriber.get("pppoe_user", "")}}

    rid = f"pr-r-{uuid.uuid4().hex[:14]}"
    voucher = f"V{secrets.token_hex(3).upper()}"
    red = {"id": rid, "company_id": u["company_id"],
            "partner_id": u["partner_id"],
            "partner_name": u.get("partner_name", ""),
            "promotion_id": promotion["id"],
            "promotion_title": promotion["title"],
            "client_id": subscriber["id"],
            "client_name": subscriber.get("name", ""),
            "client_pppoe": subscriber.get("pppoe_user", ""),
            "client_document": subscriber.get("document", ""),
            "partner_user_id": u["sub"],
            "partner_user_email": u["email"],
            "reimbursement_value": promotion["reimbursement_value"],
            "redeemed_at": _now_iso(),
            "voucher_code": voucher,
            "note": payload.note or "",
            "paid": False}
    await db.parcerias_redemptions.insert_one(red)
    await db.parcerias_promotions.update_one(
        {"id": promotion["id"]},
        {"$inc": {"total_redemptions": 1,
                    "total_due": promotion["reimbursement_value"]}})
    logger.info("[parcerias] scan ok partner=%s client=%s promo=%s",
                u["partner_id"], subscriber["id"], promotion["id"])
    return {"ok": True, "voucher_code": voucher,
             "client": {"id": subscriber["id"],
                          "name": subscriber.get("name", ""),
                          "pppoe": subscriber.get("pppoe_user", ""),
                          "city": _first_city(subscriber)},
             "promotion": {"title": promotion["title"],
                              "offer_summary": promotion.get(
                                "offer_summary", "")},
             "reimbursement_value": promotion["reimbursement_value"]}


def _first_city(s: dict) -> str:
    addrs = s.get("addresses") or []
    if addrs and isinstance(addrs, list):
        a = addrs[0] or {}
        return a.get("city", "") or ""
    return ""


@partner_router.get("/redemptions")
async def partner_redemptions(limit: int = 200,
                                u: dict = Depends(get_partner_user)):
    cur = db.parcerias_redemptions.find(
        {"partner_id": u["partner_id"]}, {"_id": 0}) \
        .sort("redeemed_at", -1).limit(limit)
    return await cur.to_list(limit)


# ─── Partner self-service: criar/editar promoções próprias ───
class PartnerPromoIn(BaseModel):
    title: str = Field(..., min_length=2, max_length=160)
    offer_summary: str = Field(..., min_length=2, max_length=160)
    description: Optional[str] = ""
    image_url: Optional[str] = ""
    # iter231 — categoria do produto/serviço da promoção
    product_category: Optional[str] = ""
    discount_pct: float = Field(0, ge=0, le=100)
    original_price: float = 0
    promo_price: float = 0
    reimbursement_value: float = Field(0, ge=0)
    max_uses_per_client: int = 1
    period: PromoPeriod = "month"
    terms: Optional[str] = ""
    active: bool = True


@partner_router.post("/promotions")
async def partner_create_promo(payload: PartnerPromoIn,
                                 u: dict = Depends(get_partner_user)):
    """Permite o próprio parceiro adicionar promoções a partir do
    portal dele. O reembolso (R$ que a Ligo paga) é zero por default
    — gestor pode ajustar depois no admin se necessário."""
    partner = await db.parcerias_partners.find_one(
        {"id": u["partner_id"]}, {"_id": 0})
    if not partner:
        raise HTTPException(404, "Parceiro não encontrado")
    pid = f"pr-{uuid.uuid4().hex[:12]}"
    doc = payload.model_dump()
    doc.update({"id": pid, "partner_id": u["partner_id"],
                 "company_id": u["company_id"],
                 "partner_name": partner["name"],
                 "partner_category": partner.get("category", ""),
                 "partner_color": partner.get("color", "#6b1fb1"),
                 "partner_logo": partner.get("logo_url", ""),
                 "total_redemptions": 0, "total_due": 0.0,
                 "created_at": _now_iso(),
                 "created_by_partner": True,
                 "created_by": u["sub"]})
    await db.parcerias_promotions.insert_one(doc)
    doc.pop("_id", None)
    return doc


@partner_router.put("/promotions/{pid}")
async def partner_update_promo(pid: str, payload: PartnerPromoIn,
                                 u: dict = Depends(get_partner_user)):
    upd = payload.model_dump(exclude_unset=True)
    upd["updated_at"] = _now_iso()
    r = await db.parcerias_promotions.update_one(
        {"id": pid, "partner_id": u["partner_id"]}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(404)
    return {"ok": True}


@partner_router.delete("/promotions/{pid}")
async def partner_delete_promo(pid: str,
                                 u: dict = Depends(get_partner_user)):
    r = await db.parcerias_promotions.update_one(
        {"id": pid, "partner_id": u["partner_id"]},
        {"$set": {"active": False, "deleted_at": _now_iso()}})
    if r.matched_count == 0:
        raise HTTPException(404)
    return {"ok": True}


@partner_router.get("/ratings")
async def partner_ratings(u: dict = Depends(get_partner_user),
                            limit: int = 100):
    cur = db.parcerias_ratings.find(
        {"partner_id": u["partner_id"]}, {"_id": 0}) \
        .sort("created_at", -1).limit(limit)
    rows = await cur.to_list(limit)
    avg = await _partner_avg_rating(u["partner_id"])
    return {"ratings": [{**r, "client_name":
                            _mask_client_name(r.get("client_name", ""))}
                          for r in rows],
             "avg": avg["avg"], "count": avg["count"]}


# ═══════════════════════ CLIENT PORTAL ═══════════════════════
def _issue_client_token(sub: dict, client_user_id: str = "") -> str:
    payload = {"sub": sub["id"], "email": sub.get("email", ""),
                "name": sub.get("name", ""),
                "company_id": sub.get("company_id", DEMO_COMPANY_ID),
                "type": "client_portal",
                "client_user_id": client_user_id,
                "iat": int(_now().timestamp()),
                "exp": int((_now() + timedelta(
                  days=CLIENT_TTL_DAYS)).timestamp())}
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGO)


async def get_client_user(authorization: Optional[str] =
                            Header(None, alias="Authorization")) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Não autenticado")
    token = authorization.split(" ", 1)[1].strip()
    try:
        p = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGO])
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"Token inválido: {e}")
    if p.get("type") != "client_portal":
        raise HTTPException(403, "Token não é do portal cliente")
    return p


def _normalize_doc(s: str) -> str:
    return "".join(c for c in (s or "") if c.isdigit())


@client_router.post("/auth/login")
async def client_login(payload: PortalLoginIn):
    """Login com senha cadastrada no portal cliente (recomendado)."""
    user = await db.client_portal_users.find_one(
        {"email": payload.email.lower().strip(), "active": True},
        {"_id": 0})
    if not user or not verify_password(payload.password,
                                          user.get("password_hash", "")):
        raise HTTPException(401, "E-mail ou senha inválidos")
    sub = await db.subscribers.find_one(
        {"id": user["subscriber_id"]}, {"_id": 0})
    if not sub:
        raise HTTPException(404, "Assinante não encontrado")
    qr_token = await _ensure_client_qr_token(sub["id"])
    return {"access_token": _issue_client_token(sub, user["id"]),
             "token_type": "bearer",
             "user": {"id": sub["id"], "email": sub.get("email", ""),
                       "name": sub.get("name", ""),
                       "qr_token": qr_token,
                       "qr_payload": f"{QR_TOKEN_PREFIX}{qr_token}"}}


@client_router.post("/auth/quick-login")
async def client_quick_login(payload: ClientQuickLoginIn):
    """Login rápido: e-mail do assinante + últimos 4 dígitos do CPF.
    Usado para clientes que ainda não criaram senha. Best-effort, sem
    bcrypt — apenas confirmação leve. Para produção, criar senha com
    /auth/set-password ou usar OTP via WhatsApp."""
    email = payload.email.lower().strip()
    sub = await db.subscribers.find_one(
        {"email": {"$regex": f"^{email}$", "$options": "i"}}, {"_id": 0})
    if not sub:
        raise HTTPException(404,
                              "E-mail não encontrado no cadastro de "
                              "assinantes")
    if payload.document:
        digits = _normalize_doc(sub.get("document"))
        if not digits.endswith(_normalize_doc(payload.document)[-4:]):
            raise HTTPException(401, "Documento não confere")
    qr_token = await _ensure_client_qr_token(sub["id"])
    return {"access_token": _issue_client_token(sub),
             "token_type": "bearer",
             "user": {"id": sub["id"], "email": sub.get("email", ""),
                       "name": sub.get("name", ""),
                       "qr_token": qr_token,
                       "qr_payload": f"{QR_TOKEN_PREFIX}{qr_token}"}}


@client_router.get("/me")
async def client_me(u: dict = Depends(get_client_user)):
    sub = await db.subscribers.find_one({"id": u["sub"]}, {"_id": 0})
    if not sub:
        raise HTTPException(404)
    qr_token = await _ensure_client_qr_token(sub["id"])
    elig_general = (sub.get("status", "").upper() in ("ATIVO", "ATIVA")
                     and (sub.get("financial_status") or "").lower() not in
                       ("inadimplente", "atrasado", "bloqueado"))
    return {"user": {"id": sub["id"], "name": sub.get("name", ""),
                       "email": sub.get("email", ""),
                       "pppoe_user": sub.get("pppoe_user", ""),
                       "plan_name": sub.get("plan_name", ""),
                       "status": sub.get("status", ""),
                       "financial_status": sub.get(
                         "financial_status", "")},
             "qr_token": qr_token,
             "qr_payload": f"{QR_TOKEN_PREFIX}{qr_token}",
             "is_eligible": elig_general}


@client_router.get("/promotions")
async def client_promotions(u: dict = Depends(get_client_user)):
    cur = db.parcerias_promotions.find(
        {"company_id": u["company_id"], "active": True},
        {"_id": 0}).sort("created_at", -1)
    return await cur.to_list(500)


@client_router.get("/my-redemptions")
async def my_redemptions(u: dict = Depends(get_client_user)):
    cur = db.parcerias_redemptions.find(
        {"client_id": u["sub"]}, {"_id": 0}) \
        .sort("redeemed_at", -1).limit(200)
    rows = await cur.to_list(200)
    for r in rows:
        rt = await db.parcerias_ratings.find_one(
            {"redemption_id": r["id"]}, {"_id": 0, "stars": 1})
        r["rating"] = rt["stars"] if rt else 0
    return rows


@client_router.post("/qr/rotate")
async def rotate_qr(u: dict = Depends(get_client_user)):
    token = secrets.token_urlsafe(24)
    await db.client_qr_tokens.update_one(
        {"client_id": u["sub"]},
        {"$set": {"token": token, "last_rotated_at": _now_iso()}},
        upsert=True)
    return {"qr_token": token, "qr_payload": f"{QR_TOKEN_PREFIX}{token}"}


class RatingIn(BaseModel):
    redemption_id: str
    stars: int = Field(..., ge=1, le=5)
    comment: Optional[str] = ""


@client_router.post("/rate")
async def rate_redemption(payload: RatingIn,
                            u: dict = Depends(get_client_user)):
    """Cliente avalia uma redenção que ele mesmo fez (1-5 estrelas)."""
    red = await db.parcerias_redemptions.find_one(
        {"id": payload.redemption_id, "client_id": u["sub"]}, {"_id": 0})
    if not red:
        raise HTTPException(404,
                              "Resgate não encontrado ou não pertence "
                              "a você")
    if await db.parcerias_ratings.find_one(
        {"redemption_id": payload.redemption_id}):
        raise HTTPException(409, "Resgate já foi avaliado")
    rid = f"rt-{uuid.uuid4().hex[:12]}"
    doc = {"id": rid, "redemption_id": payload.redemption_id,
            "client_id": u["sub"],
            "client_name": red.get("client_name", ""),
            "partner_id": red["partner_id"],
            "promotion_id": red["promotion_id"],
            "promotion_title": red.get("promotion_title", ""),
            "stars": int(payload.stars),
            "comment": (payload.comment or "")[:500],
            "company_id": red.get("company_id", DEMO_COMPANY_ID),
            "created_at": _now_iso()}
    await db.parcerias_ratings.insert_one(doc)
    return {"ok": True, "rating_id": rid}


# ─── Admin: criar acesso de cliente no portal ──────────────────
class ClientPortalUserIn(BaseModel):
    subscriber_id: str
    email: EmailStr
    password: str


@router.post("/client-portal-users")
async def create_client_portal_user(payload: ClientPortalUserIn,
                                      user: dict =
                                      Depends(get_current_user)):
    _require_manager(user)
    sub = await db.subscribers.find_one(
        {"id": payload.subscriber_id,
         "company_id": _cid(user)}, {"_id": 0})
    if not sub:
        raise HTTPException(404, "Assinante não encontrado")
    email = payload.email.lower().strip()
    if await db.client_portal_users.find_one({"email": email}):
        raise HTTPException(409, "E-mail já cadastrado no portal")
    uid = f"cpu-{uuid.uuid4().hex[:12]}"
    doc = {"id": uid, "subscriber_id": payload.subscriber_id,
            "company_id": _cid(user), "email": email,
            "password_hash": hash_password(payload.password),
            "active": True, "created_at": _now_iso(),
            "created_by": user.get("id")}
    await db.client_portal_users.insert_one(doc)
    await _ensure_client_qr_token(payload.subscriber_id)
    return {"id": uid, "email": email,
             "subscriber_id": payload.subscriber_id}
