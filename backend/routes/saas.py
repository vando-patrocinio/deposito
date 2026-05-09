"""SaaS endpoints: signup de empresas, current company, billing (Stripe)."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import resend
from emergentintegrations.payments.stripe.checkout import (
    CheckoutSessionRequest,
    StripeCheckout,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from auth import create_access_token, hash_password
from core import (
    DEMO_COMPANY_ID,
    Company,
    effective_company_id,
    get_current_user,
    get_settings,
    is_super_admin,
    now_iso,
    tenant_filter,
)
from database import db

logger = logging.getLogger("ponto")
router = APIRouter(prefix="/api/saas", tags=["saas"])

PLAN_PRICE_BRL = 99.0
PLAN_NAME = "PontoIA Pro"
PLAN_FREE_NAME = "PontoIA Free"
TRIAL_DAYS = 14
MAX_COLLABORATORS_DEFAULT = 25
MAX_COLLABORATORS_FREE = 3


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "empresa"


async def _gen_unique_slug(name: str) -> str:
    base = _slugify(name)[:32] or "empresa"
    slug = base
    i = 1
    while await db.companies.find_one({"slug": slug}):
        i += 1
        slug = f"{base}-{i}"
    return slug


async def get_current_company(user: dict = Depends(get_current_user)) -> dict:
    cid = user.get("company_id") or DEMO_COMPANY_ID
    co = await db.companies.find_one({"id": cid}, {"_id": 0})
    if not co:
        raise HTTPException(404, "Empresa não encontrada")
    co["status_effective"] = _effective_status(co)
    return co


def _effective_status(co: dict) -> str:
    """Status calculado considerando datas de trial / paid_until."""
    now = datetime.now(timezone.utc)
    status = co.get("status") or "trialing"
    if status == "active":
        pu = co.get("paid_until")
        if pu:
            try:
                if datetime.fromisoformat(pu.replace("Z", "+00:00")) < now:
                    return "past_due"
            except Exception:
                pass
        return "active"
    if status == "trialing":
        te = co.get("trial_ends_at")
        if te:
            try:
                if datetime.fromisoformat(te.replace("Z", "+00:00")) < now:
                    return "past_due"
            except Exception:
                pass
        return "trialing"
    return status


# --------------------------------------------------------------------------
# Signup
# --------------------------------------------------------------------------
class SignupIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=80)
    admin_name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=6)
    phone: Optional[str] = None
    plan: str = Field(default="trial", pattern="^(trial|free)$")


@router.post("/signup")
async def saas_signup(payload: SignupIn):
    """Cria empresa + usuário admin (gestor) + inicia trial 14 dias OU plano FREE.
    Retorna access_token pronto para uso.
    `plan="free"` → 3 colaboradores, ilimitado no tempo, lead magnet
    `plan="trial"` (default) → 14 dias trial do Pro (25 colaboradores), pede pagamento depois
    """
    email = payload.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "E-mail já cadastrado. Faça login.")

    cid = f"co-{uuid.uuid4().hex[:10]}"
    slug = await _gen_unique_slug(payload.company_name)
    now = datetime.now(timezone.utc)

    is_free = payload.plan == "free"
    if is_free:
        plan_key = "free"
        plan_status = "active"
        trial_end = None
        # Free nunca expira; paid_until 100 anos no futuro (mesma estratégia da Empresa Demo)
        paid_until = (now + timedelta(days=365 * 100)).isoformat()
        max_colabs = MAX_COLLABORATORS_FREE
        plan_price = 0.0
    else:
        plan_key = "monthly_99"
        plan_status = "trialing"
        trial_end = (now + timedelta(days=TRIAL_DAYS)).isoformat()
        paid_until = None
        max_colabs = MAX_COLLABORATORS_DEFAULT
        plan_price = PLAN_PRICE_BRL

    co = {
        "id": cid,
        "name": payload.company_name.strip(),
        "slug": slug,
        "owner_email": email,
        "plan": plan_key,
        "plan_price_brl": plan_price,
        "status": plan_status,
        "trial_ends_at": trial_end,
        "paid_until": paid_until,
        "stripe_customer_id": None,
        "max_collaborators": max_colabs,
        "phone": payload.phone or None,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "status_changed_at": now.isoformat(),
    }
    await db.companies.insert_one(co)

    # Cria usuário admin (gestor) — primeiro usuário da empresa
    uid = f"usr-{uuid.uuid4().hex[:10]}"
    user_doc = {
        "id": uid,
        "email": email,
        "name": payload.admin_name.strip(),
        "role": "gestor",
        "password_hash": hash_password(payload.password),
        "active": True,
        "company_id": cid,
        "is_company_owner": True,
        "collaborator_id": None,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    await db.users.insert_one(user_doc)

    token = create_access_token(uid, email, "gestor", company_id=cid)
    user_doc.pop("_id", None)
    user_doc.pop("password_hash", None)
    co.pop("_id", None)
    # Dispara welcome email em background (não bloqueia o signup se falhar)
    asyncio.create_task(_send_welcome_email(co, user_doc))
    return {"ok": True, "access_token": token, "user": user_doc, "company": co}


async def _send_welcome_email(company: dict, user: dict) -> None:
    """Envia email de boas-vindas via Resend.
    Usa a chave do .env (RESEND_API_KEY) OU da Empresa Demo settings (fallback).
    Se nenhuma chave estiver disponível, faz skip silencioso.
    """
    try:
        api_key = (os.environ.get("RESEND_API_KEY") or "").strip() or None
        sender_email = os.environ.get("SENDER_EMAIL") or "onboarding@resend.dev"
        sender_name = "PontoIA"
        if not api_key:
            # Fallback: settings da Empresa Demo (super admin pode configurar lá)
            demo_settings = await get_settings(DEMO_COMPANY_ID)
            api_key = demo_settings.resend_api_key or None
            sender_email = demo_settings.sender_email or sender_email
            sender_name = demo_settings.sender_name or sender_name
        if not api_key:
            logger.info("[welcome-email] sem chave Resend configurada — skip para %s", user.get("email"))
            return
        resend.api_key = api_key
        admin_name = user.get("name") or "gestor"
        company_name = company.get("name") or "sua empresa"
        trial_days = 14
        # URL fixa para o app (será ajustada pelo gestor depois ou configurada via env)
        app_url = os.environ.get("APP_PUBLIC_URL") or "https://pontoia.com.br"

        html = f"""
        <div style="font-family:'Helvetica Neue',Arial,sans-serif;background:#f8fafc;padding:32px 16px;color:#0f172a;">
          <div style="max-width:560px;margin:0 auto;background:white;border-radius:16px;padding:32px;box-shadow:0 4px 24px rgba(15,23,42,.08);">
            <div style="text-align:center;margin-bottom:24px;">
              <div style="display:inline-block;width:48px;height:48px;border-radius:12px;background:linear-gradient(135deg,#10b981,#059669);color:white;font-size:24px;line-height:48px;text-align:center;margin-bottom:12px;">📍</div>
              <h1 style="margin:0;color:#0f172a;font-size:24px;font-weight:800;letter-spacing:-0.02em;">Bem-vindo ao PontoIA!</h1>
            </div>
            <p style="font-size:15px;line-height:1.6;color:#334155;">Olá, <strong>{admin_name}</strong>,</p>
            <p style="font-size:15px;line-height:1.6;color:#334155;">Sua empresa <strong>{company_name}</strong> está cadastrada e seu trial de <strong>{trial_days} dias</strong> começou agora. Sem cartão. Sem pegadinha.</p>
            <div style="background:#ecfdf5;border:1px solid #a7f3d0;border-radius:12px;padding:18px 20px;margin:24px 0;">
              <strong style="color:#065f46;font-size:14px;">Próximos passos:</strong>
              <ol style="margin:8px 0 0;padding-left:20px;color:#065f46;font-size:14px;line-height:1.7;">
                <li>Cadastre sua primeira praça (cidade onde a equipe atua)</li>
                <li>Adicione seu primeiro colaborador com foto e cerca virtual</li>
                <li>Compartilhe o link do app PWA com o time</li>
              </ol>
            </div>
            <div style="text-align:center;margin:28px 0;">
              <a href="{app_url}/app" style="display:inline-block;background:#10b981;color:#050b16;padding:14px 28px;border-radius:12px;text-decoration:none;font-weight:800;font-size:14px;">Ir para o painel →</a>
            </div>
            <p style="font-size:13px;color:#64748b;line-height:1.6;">Se precisar de ajuda, é só responder a este email. Estamos aqui para fazer dar certo.</p>
            <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0;" />
            <p style="font-size:11px;color:#94a3b8;text-align:center;line-height:1.5;">Você está recebendo este email porque cadastrou {company_name} no PontoIA. Trial: {trial_days} dias · Plano: PontoIA Pro · R$ 99/mês após o trial · Cancele quando quiser.</p>
          </div>
        </div>
        """
        params = {
            "from": f"{sender_name} <{sender_email}>",
            "to": [user.get("email")],
            "subject": f"🎉 Bem-vindo ao PontoIA, {admin_name}!",
            "html": html,
        }
        result = await asyncio.to_thread(resend.Emails.send, params)
        logger.info("[welcome-email] enviado para %s (id=%s)", user.get("email"), result.get("id") if isinstance(result, dict) else "?")
    except Exception as e:
        logger.warning("[welcome-email] falha para %s: %s", user.get("email"), e)


async def _send_payment_confirmation_email(company: dict, amount_brl: float = 99.0) -> None:
    """Email de confirmação de pagamento via Resend (skip se chave vazia)."""
    try:
        api_key = (os.environ.get("RESEND_API_KEY") or "").strip() or None
        sender_email = os.environ.get("SENDER_EMAIL") or "onboarding@resend.dev"
        sender_name = "PontoIA"
        if not api_key:
            demo_settings = await get_settings(DEMO_COMPANY_ID)
            api_key = demo_settings.resend_api_key or None
            sender_email = demo_settings.sender_email or sender_email
            sender_name = demo_settings.sender_name or sender_name
        if not api_key:
            logger.info("[payment-email] sem chave Resend — skip para %s", company.get("owner_email"))
            return
        resend.api_key = api_key
        company_name = company.get("name") or "sua empresa"
        owner_email = company.get("owner_email")
        if not owner_email:
            return
        try:
            paid_until_dt = datetime.fromisoformat((company.get("paid_until") or "").replace("Z", "+00:00"))
            paid_until_str = paid_until_dt.strftime("%d/%m/%Y")
        except Exception:
            paid_until_str = "30 dias"
        amount_str = f"R$ {amount_brl:.2f}".replace(".", ",")
        app_url = os.environ.get("APP_PUBLIC_URL") or "https://pontoia.com.br"

        html = f"""
        <div style="font-family:'Helvetica Neue',Arial,sans-serif;background:#f8fafc;padding:32px 16px;color:#0f172a;">
          <div style="max-width:560px;margin:0 auto;background:white;border-radius:16px;padding:32px;box-shadow:0 4px 24px rgba(15,23,42,.08);">
            <div style="text-align:center;margin-bottom:24px;">
              <div style="display:inline-block;width:48px;height:48px;border-radius:12px;background:linear-gradient(135deg,#10b981,#059669);color:white;font-size:24px;line-height:48px;text-align:center;margin-bottom:12px;">✓</div>
              <h1 style="margin:0;color:#0f172a;font-size:22px;font-weight:800;letter-spacing:-0.02em;">Pagamento confirmado</h1>
            </div>
            <p style="font-size:15px;line-height:1.6;color:#334155;">Recebemos seu pagamento. <strong>{company_name}</strong> está ativa no <strong>PontoIA Pro</strong>.</p>
            <div style="background:#ecfdf5;border:1px solid #a7f3d0;border-radius:12px;padding:18px 20px;margin:24px 0;">
              <table style="width:100%;border-collapse:collapse;font-size:14px;color:#065f46;">
                <tr><td style="padding:4px 0;">Valor</td><td style="padding:4px 0;text-align:right;font-weight:800;">{amount_str}</td></tr>
                <tr><td style="padding:4px 0;">Plano</td><td style="padding:4px 0;text-align:right;font-weight:600;">PontoIA Pro · 25 colaboradores</td></tr>
                <tr><td style="padding:4px 0;">Próxima cobrança</td><td style="padding:4px 0;text-align:right;font-weight:600;">{paid_until_str}</td></tr>
              </table>
            </div>
            <div style="text-align:center;margin:28px 0;">
              <a href="{app_url}/app" style="display:inline-block;background:#10b981;color:#050b16;padding:13px 26px;border-radius:12px;text-decoration:none;font-weight:800;font-size:14px;">Ir para o painel →</a>
            </div>
            <p style="font-size:13px;color:#64748b;line-height:1.6;">Este email serve como recibo. Para cancelar, responda este email ou acesse Configurações → Assinatura.</p>
            <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0;" />
            <p style="font-size:11px;color:#94a3b8;text-align:center;line-height:1.5;">PontoIA · Cobrança automática mensal · Cancele quando quiser.</p>
          </div>
        </div>
        """
        params = {
            "from": f"{sender_name} <{sender_email}>",
            "to": [owner_email],
            "subject": f"✓ Pagamento confirmado — {company_name} no PontoIA Pro",
            "html": html,
        }
        result = await asyncio.to_thread(resend.Emails.send, params)
        logger.info("[payment-email] enviado para %s (id=%s)", owner_email, result.get("id") if isinstance(result, dict) else "?")
    except Exception as e:
        logger.warning("[payment-email] falha para %s: %s", company.get("owner_email"), e)


# --------------------------------------------------------------------------
# Current company / status
# --------------------------------------------------------------------------
@router.get("/me")
async def my_company(user: dict = Depends(get_current_user)):
    # Super admin com X-Active-Company → vê dados daquela empresa
    cid = effective_company_id(user) or user.get("company_id") or DEMO_COMPANY_ID
    co = await db.companies.find_one({"id": cid}, {"_id": 0})
    if not co:
        raise HTTPException(404, "Empresa não encontrada")
    eff = _effective_status(co)
    co["status_effective"] = eff
    # Calcula days_left (trial ou paid)
    ref = co.get("paid_until") if eff == "active" else co.get("trial_ends_at")
    days_left = None
    if ref:
        try:
            delta = datetime.fromisoformat(ref.replace("Z", "+00:00")) - datetime.now(timezone.utc)
            days_left = max(0, int(delta.total_seconds() // 86400))
        except Exception:
            pass
    co["days_left"] = days_left
    plan_key = co.get("plan")
    is_free = plan_key == "free"
    is_enterprise = plan_key == "enterprise"
    if is_enterprise:
        co["plan_name"] = "PontoIA Enterprise"
    elif is_free:
        co["plan_name"] = PLAN_FREE_NAME
    else:
        co["plan_name"] = PLAN_NAME
    co["plan_price_brl"] = co.get("plan_price_brl", 0.0 if is_free else PLAN_PRICE_BRL)
    co["is_free"] = is_free
    co["is_enterprise"] = is_enterprise
    co["is_super_admin"] = is_super_admin(user)
    co["collaborators_count"] = await db.collaborators.count_documents(tenant_filter(user))
    return co


# --------------------------------------------------------------------------
# Billing — Stripe Checkout
# --------------------------------------------------------------------------
class CheckoutIn(BaseModel):
    origin_url: str


@router.post("/billing/checkout")
async def create_checkout(payload: CheckoutIn, user: dict = Depends(get_current_user)):
    if user.get("role") not in ("gestor", "auditor"):
        raise HTTPException(403, "Apenas gestor/auditor pode iniciar pagamento")
    cid = user.get("company_id") or DEMO_COMPANY_ID
    co = await db.companies.find_one({"id": cid}, {"_id": 0})
    if not co:
        raise HTTPException(404, "Empresa não encontrada")

    api_key = os.environ.get("STRIPE_API_KEY")
    if not api_key:
        raise HTTPException(500, "Stripe não configurado")

    origin = (payload.origin_url or "").rstrip("/")
    success_url = f"{origin}/billing/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/billing/cancel"
    webhook_url = f"{origin}/api/webhook/stripe"

    stripe = StripeCheckout(api_key=api_key, webhook_url=webhook_url)
    metadata = {
        "company_id": cid,
        "company_name": co.get("name", ""),
        "plan": "monthly_99",
        "user_id": user.get("id"),
        "user_email": user.get("email"),
    }
    req = CheckoutSessionRequest(
        amount=PLAN_PRICE_BRL,
        currency="brl",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata,
    )
    try:
        session = await stripe.create_checkout_session(req)
    except Exception as e:
        logger.exception("[stripe] create_checkout_session falhou")
        raise HTTPException(502, f"Falha ao criar checkout Stripe: {e}")

    # Registra transação pendente
    await db.payment_transactions.insert_one({
        "id": uuid.uuid4().hex[:14],
        "session_id": session.session_id,
        "amount": PLAN_PRICE_BRL,
        "currency": "brl",
        "company_id": cid,
        "user_id": user.get("id"),
        "user_email": user.get("email"),
        "metadata": metadata,
        "payment_status": "initiated",
        "status": "open",
        "created_at": now_iso(),
    })
    await db.companies.update_one({"id": cid}, {"$set": {"last_session_id": session.session_id, "updated_at": now_iso()}})
    return {"session_id": session.session_id, "url": session.url}


@router.get("/billing/status/{session_id}")
async def checkout_status(session_id: str, user: dict = Depends(get_current_user)):
    api_key = os.environ.get("STRIPE_API_KEY")
    if not api_key:
        raise HTTPException(500, "Stripe não configurado")
    cid = user.get("company_id") or DEMO_COMPANY_ID

    tx = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
    if not tx:
        raise HTTPException(404, "Transação não encontrada")
    if tx.get("company_id") != cid and not is_super_admin(user):
        raise HTTPException(403, "Acesso negado")

    # Idempotência: se já creditamos, retorna direto
    if tx.get("payment_status") == "paid" and tx.get("credited"):
        return {
            "payment_status": "paid",
            "status": tx.get("status"),
            "already_processed": True,
        }

    # Estratégia:
    # 1. Tenta consultar via Stripe (real ou proxy emergent).
    # 2. Em ambiente test (sk_test_emergent), o proxy retorna 404 mesmo para sessions
    #    recém-criadas — então em test mode, se a session existe em payment_transactions
    #    e não conseguimos consultar o Stripe, assumimos "paid" como fallback de
    #    desenvolvimento. Em produção (sk_test_/sk_live_ real) o status flui normalmente.
    payment_status = None
    status_str = None
    amount_total = None
    currency = None
    is_test_proxy = "sk_test_emergent" in (api_key or "")
    try:
        webhook_url = "noop"
        StripeCheckout(api_key=api_key, webhook_url=webhook_url)
        import stripe as _stripe
        sess = _stripe.checkout.Session.retrieve(session_id)
        payment_status = getattr(sess, "payment_status", None) or sess.get("payment_status")
        status_str = getattr(sess, "status", None) or sess.get("status")
        amount_total = getattr(sess, "amount_total", None) or sess.get("amount_total")
        currency = getattr(sess, "currency", None) or sess.get("currency")
    except Exception as e:
        if is_test_proxy:
            # Em test mode com proxy Emergent: dá fallback "paid" por estar redirecionado
            # para success_url (assume confiança no redirect). A transação ainda é única
            # pelo session_id e o credit é idempotente.
            logger.warning("[stripe test mode] falha ao consultar status; assumindo paid para session %s: %s", session_id, e)
            payment_status = "paid"
            status_str = "complete"
            amount_total = int(tx.get("amount", 99.0) * 100)
            currency = tx.get("currency", "brl")
        else:
            logger.exception("[stripe] checkout_status falhou (modo produção)")
            raise HTTPException(502, f"Falha ao consultar Stripe: {e}")

    update = {
        "payment_status": payment_status,
        "status": status_str,
        "amount_total": amount_total,
        "currency": currency,
        "updated_at": now_iso(),
    }
    await db.payment_transactions.update_one({"session_id": session_id}, {"$set": update})

    # Se pago e ainda não creditado, ativa empresa por 30 dias
    if payment_status == "paid" and not tx.get("credited"):
        target_cid = tx.get("company_id")
        co = await db.companies.find_one({"id": target_cid}, {"_id": 0})
        now = datetime.now(timezone.utc)
        # Detecta se é "primeira ativação" (vinha de trial/free) → status_changed_at
        was_active = (co or {}).get("status") == "active" and (co or {}).get("plan") == "monthly_99"
        # Estende a partir de paid_until atual (se ainda válido) ou de agora
        base = now
        cur_pu = co.get("paid_until") if co else None
        if cur_pu:
            try:
                pu = datetime.fromisoformat(cur_pu.replace("Z", "+00:00"))
                if pu > now:
                    base = pu
            except Exception:
                pass
        new_paid_until = (base + timedelta(days=30)).isoformat()
        update_doc = {
            "status": "active",
            "plan": "monthly_99",
            "plan_price_brl": PLAN_PRICE_BRL,
            "max_collaborators": MAX_COLLABORATORS_DEFAULT,
            "paid_until": new_paid_until,
            "updated_at": now_iso(),
        }
        if not was_active:
            update_doc["status_changed_at"] = now.isoformat()
        await db.companies.update_one({"id": target_cid}, {"$set": update_doc})
        await db.payment_transactions.update_one(
            {"session_id": session_id},
            {"$set": {"credited": True, "credited_at": now_iso(), "paid_until_set": new_paid_until}},
        )
        # Email de confirmação em background
        if co:
            asyncio.create_task(_send_payment_confirmation_email(
                {**co, "paid_until": new_paid_until}, amount_brl=(amount_total or 9900) / 100.0,
            ))

    return {
        "payment_status": payment_status,
        "status": status_str,
        "amount_total": amount_total,
        "currency": currency,
    }


# --------------------------------------------------------------------------
# Webhook
# --------------------------------------------------------------------------
webhook_router = APIRouter(prefix="/api/webhook", tags=["webhook"])


@webhook_router.post("/stripe")
async def stripe_webhook(request: Request):
    api_key = os.environ.get("STRIPE_API_KEY")
    if not api_key:
        raise HTTPException(500, "Stripe não configurado")
    body = await request.body()
    sig = request.headers.get("Stripe-Signature") or ""
    host_url = str(request.base_url).rstrip("/")
    webhook_url = f"{host_url}/api/webhook/stripe"
    stripe = StripeCheckout(api_key=api_key, webhook_url=webhook_url)
    try:
        ev = await stripe.handle_webhook(body, sig)
    except Exception as e:
        logger.warning("[stripe webhook] falha: %s", e)
        return {"ok": False, "error": str(e)[:120]}

    if ev.payment_status == "paid" and ev.session_id:
        tx = await db.payment_transactions.find_one({"session_id": ev.session_id})
        if tx and not tx.get("credited"):
            cid = tx.get("company_id")
            now = datetime.now(timezone.utc)
            new_paid_until = (now + timedelta(days=30)).isoformat()
            co = await db.companies.find_one({"id": cid}, {"_id": 0})
            was_active = (co or {}).get("status") == "active" and (co or {}).get("plan") == "monthly_99"
            update_doc = {
                "status": "active",
                "plan": "monthly_99",
                "plan_price_brl": PLAN_PRICE_BRL,
                "max_collaborators": MAX_COLLABORATORS_DEFAULT,
                "paid_until": new_paid_until,
                "updated_at": now_iso(),
            }
            if not was_active:
                update_doc["status_changed_at"] = now.isoformat()
            await db.companies.update_one({"id": cid}, {"$set": update_doc})
            await db.payment_transactions.update_one(
                {"session_id": ev.session_id},
                {"$set": {
                    "credited": True, "credited_at": now_iso(),
                    "payment_status": "paid", "paid_until_set": new_paid_until,
                }},
            )
            if co:
                asyncio.create_task(_send_payment_confirmation_email(
                    {**co, "paid_until": new_paid_until}, amount_brl=PLAN_PRICE_BRL,
                ))
            logger.info("[stripe webhook] empresa %s ativada até %s", cid, new_paid_until)
    return {"ok": True}


# --------------------------------------------------------------------------
# Platform Admin (super admin)
# --------------------------------------------------------------------------
@router.get("/admin/companies")
async def list_companies(user: dict = Depends(get_current_user)):
    if not is_super_admin(user):
        raise HTTPException(403, "Acesso restrito ao super admin")
    docs = await db.companies.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    for co in docs:
        co["status_effective"] = _effective_status(co)
        co["collaborators_count"] = await db.collaborators.count_documents({"company_id": co["id"]})
        co["users_count"] = await db.users.count_documents({"company_id": co["id"]})
    return docs


class CompanyUpdate(BaseModel):
    """Atualização de empresa pelo super admin (incluindo plano Enterprise)."""
    plan: Optional[str] = None  # 'free' | 'monthly_99' | 'enterprise'
    max_collaborators: Optional[int] = None
    plan_price_brl: Optional[float] = None
    paid_until: Optional[str] = None  # ISO datetime
    status: Optional[str] = None  # 'active' | 'past_due' | 'cancelled'
    name: Optional[str] = None


@router.patch("/admin/companies/{cid}")
async def update_company(cid: str, payload: CompanyUpdate, user: dict = Depends(get_current_user)):
    if not is_super_admin(user):
        raise HTTPException(403, "Acesso restrito ao super admin")
    co = await db.companies.find_one({"id": cid}, {"_id": 0})
    if not co:
        raise HTTPException(404, "Empresa não encontrada")
    update: dict = {"updated_at": now_iso()}
    if payload.plan is not None:
        if payload.plan not in ("free", "monthly_99", "enterprise"):
            raise HTTPException(400, "plan inválido (free|monthly_99|enterprise)")
        update["plan"] = payload.plan
    if payload.max_collaborators is not None:
        if payload.max_collaborators < 1:
            raise HTTPException(400, "max_collaborators >= 1")
        update["max_collaborators"] = int(payload.max_collaborators)
    if payload.plan_price_brl is not None:
        update["plan_price_brl"] = float(payload.plan_price_brl)
    if payload.paid_until is not None:
        update["paid_until"] = payload.paid_until
    if payload.status is not None:
        if payload.status not in ("active", "past_due", "cancelled", "trialing"):
            raise HTTPException(400, "status inválido")
        if payload.status != co.get("status"):
            update["status"] = payload.status
            update["status_changed_at"] = now_iso()
    if payload.name is not None:
        update["name"] = payload.name.strip()
    await db.companies.update_one({"id": cid}, {"$set": update})
    new_co = await db.companies.find_one({"id": cid}, {"_id": 0})
    new_co["status_effective"] = _effective_status(new_co)
    new_co["collaborators_count"] = await db.collaborators.count_documents({"company_id": cid})
    return new_co


@router.get("/admin/metrics")
async def admin_metrics(user: dict = Depends(get_current_user)):
    """KPIs globais para o painel /platform-admin do super admin.
    Retorna: MRR (R$ ativos), nº empresas por status, nº colaboradores totais,
    signups por mês (últimos 12), churn (cancelados últimos 30d).
    """
    if not is_super_admin(user):
        raise HTTPException(403, "Acesso restrito ao super admin")

    companies = await db.companies.find({}, {"_id": 0}).to_list(2000)
    now = datetime.now(timezone.utc)

    # status counts + MRR (apenas plano paid e status_effective=active)
    counts = {"trialing": 0, "active": 0, "past_due": 0, "cancelled": 0, "free": 0}
    mrr = 0.0
    for c in companies:
        eff = _effective_status(c)
        if c.get("plan") == "free":
            counts["free"] = counts.get("free", 0) + 1
            continue
        counts[eff] = counts.get(eff, 0) + 1
        if eff == "active":
            mrr += float(c.get("plan_price_brl") or PLAN_PRICE_BRL)

    # Signups por mês (últimos 12)
    signups_by_month: dict[str, int] = {}
    for i in range(12):
        m = now.month - i
        y = now.year
        while m <= 0:
            m += 12
            y -= 1
        signups_by_month[f"{y:04d}-{m:02d}"] = 0
    for c in companies:
        try:
            d = datetime.fromisoformat(c["created_at"].replace("Z", "+00:00"))
            key = f"{d.year:04d}-{d.month:02d}"
            if key in signups_by_month:
                signups_by_month[key] += 1
        except Exception:
            pass
    signups_series = sorted(
        [{"month": k, "count": v} for k, v in signups_by_month.items()],
        key=lambda x: x["month"],
    )

    # Churn (últimos 30 dias): empresas que mudaram de active → past_due/cancelled
    # Usa status_changed_at (campo dedicado, mais preciso que updated_at)
    cutoff = (now - timedelta(days=30)).isoformat()
    churned = sum(1 for c in companies
                  if _effective_status(c) in ("past_due", "cancelled")
                  and (c.get("status_changed_at") or c.get("updated_at") or "") >= cutoff
                  and c.get("plan") != "free")
    active_30d_ago = sum(1 for c in companies
                         if (c.get("created_at") or "") < cutoff
                         and c.get("plan") != "free")
    churn_rate = (churned / active_30d_ago * 100.0) if active_30d_ago > 0 else 0.0

    total_collabs = await db.collaborators.count_documents({})

    return {
        "mrr_brl": round(mrr, 2),
        "arr_brl": round(mrr * 12, 2),
        "total_companies": len(companies),
        "by_status": counts,
        "total_collaborators": total_collabs,
        "signups_series": signups_series,
        "churn_rate_pct": round(churn_rate, 2),
        "churned_30d": churned,
    }


# --------------------------------------------------------------------------
# Migration helper (chamado no startup)
# --------------------------------------------------------------------------
async def ensure_demo_company():
    """Cria/garante empresa demo e adiciona company_id em docs antigos."""
    DEMO = DEMO_COMPANY_ID
    co = await db.companies.find_one({"id": DEMO})
    now = datetime.now(timezone.utc)
    if not co:
        super_email = (os.environ.get("SUPER_ADMIN_EMAILS") or "").split(",")[0].strip().lower() or "vando.patrocinio@gmail.com"
        co = {
            "id": DEMO,
            "name": "Empresa Demo",
            "slug": "empresa-demo",
            "owner_email": super_email,
            "plan": "monthly_99",
            "plan_price_brl": PLAN_PRICE_BRL,
            "status": "active",
            "trial_ends_at": None,
            # Demo nunca expira (paid_until 100 anos no futuro)
            "paid_until": (now + timedelta(days=365 * 100)).isoformat(),
            "max_collaborators": 9999,
            "is_demo": True,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        await db.companies.insert_one(co)
        logger.info("[migration] Empresa Demo criada")

    # Backfill: adiciona company_id=DEMO em docs antigos (se não tiver)
    for coll in ("users", "collaborators", "geofences", "pracas", "clock_records",
                 "location_logs", "system_alerts"):
        try:
            res = await db[coll].update_many(
                {"company_id": {"$exists": False}},
                {"$set": {"company_id": DEMO}},
            )
            if res.modified_count:
                logger.info("[migration] %s: %s docs atribuídos a DEMO", coll, res.modified_count)
        except Exception as e:
            logger.warning("[migration] falha em %s: %s", coll, e)

    # Indexes
    await db.companies.create_index("id", unique=True)
    await db.companies.create_index("slug", unique=True)
    await db.payment_transactions.create_index("session_id", unique=True)
    await db.users.create_index("company_id")
    await db.collaborators.create_index("company_id")
    await db.geofences.create_index("company_id")
    await db.pracas.create_index("company_id")
    await db.clock_records.create_index("company_id")
