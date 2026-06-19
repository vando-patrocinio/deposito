"""routes/payment_charges.py — Módulo 3 (Gateway de Pagamentos).

API gateway-agnostic. Roteia pra Asaas/Cora/Sicoob conforme configurado
no plano do assinante (ou override por chamada).

Endpoints internos (UI):
  POST   /api/payments/customers/{subscriber_id}/sync — cria customer no gw
  POST   /api/payments/charges                         — emite boleto/Pix
  GET    /api/payments/charges                         — lista cobranças
  GET    /api/payments/charges/{id}                    — detalhe + status refresh
  POST   /api/payments/charges/{id}/cancel             — cancela
  POST   /api/payments/charges/{id}/refund             — estorna
  GET    /api/payments/gateways/status                 — quais gateways tem creds

Webhook público (chamado pelo Asaas):
  POST   /api/payments/webhook/asaas
"""
from __future__ import annotations


from services.exception_sanitizer import safe_detail  # SECURITY_LOCK ART.13
NERVOUS_METADATA = {
    "owner": "billing-team",
    "domain": "financeiro",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["subscriber.updated"],
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timezone, date as date_t
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, get_current_user, is_super_admin
from database import db
from services.payment_gateways import (
    get_gateway, list_gateways, GatewayError, ChargeIn, CustomerIn,
)

logger = logging.getLogger("ponto.payments")
router = APIRouter(prefix="/api/payments", tags=["payment-gateways"])


def _cid(user: dict) -> str:
    if is_super_admin(user):
        return (user.get("_active_company") or user.get("company_id")
                or DEMO_COMPANY_ID)
    return user.get("company_id") or DEMO_COMPANY_ID


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ===========================================================================
# Status dos gateways (UI mostra "configurar credenciais" se vazio)
# ===========================================================================
@router.get("/gateways/status")
async def gateways_status(user: dict = Depends(get_current_user)):
    out = []
    for name in list_gateways():
        try:
            gw = get_gateway(name)
            out.append({
                "name": name,
                "configured": gw.is_configured(),
                "env": getattr(gw, "env", None),
                "env_var_key": gw.env_var_key,
                "env_var_token": gw.env_var_token,
            })
        except Exception as e:
            out.append({"name": name, "configured": False, "error": str(e)})
    return {"items": out}


# ===========================================================================
# Sync customer no gateway (cria o cliente Asaas e grava o id no subscriber)
# ===========================================================================
class CustomerSyncIn(BaseModel):
    gateway: str = "asaas"
    force: bool = False  # recria mesmo se já tem id


@router.post("/customers/{subscriber_id}/sync")
async def sync_customer(
    subscriber_id: str,
    payload: CustomerSyncIn,
    user: dict = Depends(get_current_user),
):
    role = (user.get("role") or "").lower()
    if role not in ("gestor", "administrador", "financeiro") and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador/financeiro.")
    cid = _cid(user)

    sub = await db.subscribers.find_one(
        {"id": subscriber_id, "company_id": cid}, {"_id": 0})
    if not sub:
        raise HTTPException(404, "Assinante não encontrado")

    gw_field = f"{payload.gateway}_customer_id"
    existing_id = sub.get(gw_field)
    if existing_id and not payload.force:
        return {"ok": True, "gateway_customer_id": existing_id,
                "already_exists": True}

    try:
        gw = get_gateway(payload.gateway)
        customer = CustomerIn(
            name=sub.get("name") or sub.get("customer_name") or "—",
            cpf_cnpj=(sub.get("cpf_cnpj") or sub.get("cpf")
                       or sub.get("cnpj") or "").replace(".", "").replace("-", "").replace("/", ""),
            email=sub.get("email"),
            phone=sub.get("phone"),
            mobile_phone=sub.get("mobile_phone") or sub.get("phone"),
            postal_code=(sub.get("postal_code") or sub.get("cep") or "").replace("-", ""),
            address=sub.get("address") or sub.get("street"),
            address_number=str(sub.get("address_number") or sub.get("number") or ""),
            complement=sub.get("complement"),
            province=sub.get("province") or sub.get("district") or sub.get("neighborhood"),
            external_reference=subscriber_id,
        )
        if not customer.cpf_cnpj:
            raise HTTPException(400, "Assinante sem CPF/CNPJ")
        gateway_customer_id = await gw.create_customer(customer)
    except GatewayError as e:
        raise HTTPException(502, safe_detail(502, e, "Gateway error:"))

    await db.subscribers.update_one(
        {"id": subscriber_id},
        {"$set": {gw_field: gateway_customer_id,
                   f"{payload.gateway}_synced_at": _now().isoformat()}},
    )
    try:
        from services.event_bus import emit_event
        await emit_event(
            "subscriber.updated",
            company_id=(sub or {}).get("company_id"),
            source="payment_charges",
            payload={},
        )
    except Exception:
        pass
    return {"ok": True, "gateway_customer_id": gateway_customer_id,
            "created": True}


# ===========================================================================
# Criar cobrança (boleto/Pix)
# ===========================================================================
class ChargeCreateIn(BaseModel):
    subscriber_id: str
    invoice_id: Optional[str] = None  # link com fatura local
    gateway: str = "asaas"
    billing_type: str = "UNDEFINED"   # BOLETO | PIX | UNDEFINED
    due_date: date_t
    amount: float = Field(..., gt=0)
    description: str
    fine_pct: float = 2.0    # multa padrão
    interest_pct: float = 1.0  # juros 1%/mês padrão


@router.post("/charges")
async def create_charge(
    payload: ChargeCreateIn,
    user: dict = Depends(get_current_user),
):
    role = (user.get("role") or "").lower()
    if role not in ("gestor", "administrador", "financeiro") and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador/financeiro.")
    cid = _cid(user)

    sub = await db.subscribers.find_one(
        {"id": payload.subscriber_id, "company_id": cid}, {"_id": 0})
    if not sub:
        raise HTTPException(404, "Assinante não encontrado")

    # Garante customer sincronizado no gateway
    gw_field = f"{payload.gateway}_customer_id"
    gateway_customer_id = sub.get(gw_field)
    if not gateway_customer_id:
        # Sync automático
        try:
            gw = get_gateway(payload.gateway)
            customer = CustomerIn(
                name=sub.get("name") or "—",
                cpf_cnpj=(sub.get("cpf_cnpj") or sub.get("cpf")
                           or sub.get("cnpj") or "").replace(".", "")
                                                       .replace("-", "")
                                                       .replace("/", ""),
                email=sub.get("email"),
                phone=sub.get("phone"),
                external_reference=payload.subscriber_id,
            )
            if not customer.cpf_cnpj:
                raise HTTPException(400, "Assinante sem CPF/CNPJ. "
                                          "Cadastre antes de emitir cobrança.")
            gateway_customer_id = await gw.create_customer(customer)
            await db.subscribers.update_one(
                {"id": payload.subscriber_id},
                {"$set": {gw_field: gateway_customer_id,
                           f"{payload.gateway}_synced_at": _now().isoformat()}},
            )
            try:
                from services.event_bus import emit_event
                await emit_event(
                    "subscriber.updated",
                    company_id=cid,
                    source="payment_charges",
                    payload={},
                )
            except Exception:
                pass
        except GatewayError as e:
            raise HTTPException(502, safe_detail(502, e, "Gateway error (sync customer):"))

    # Cria a cobrança
    try:
        gw = get_gateway(payload.gateway)
        charge_in = ChargeIn(
            customer_gateway_id=gateway_customer_id,
            billing_type=payload.billing_type,  # type: ignore
            due_date=payload.due_date,
            amount=payload.amount,
            description=payload.description,
            external_reference=payload.invoice_id or payload.subscriber_id,
            fine_pct=payload.fine_pct,
            interest_pct=payload.interest_pct,
        )
        charge_out = await gw.create_charge(charge_in)
    except GatewayError as e:
        raise HTTPException(502, safe_detail(502, e, "Gateway error:"))

    # Persiste
    doc = {
        "id": f"chg-{uuid.uuid4().hex[:12]}",
        "company_id": cid,
        "subscriber_id": payload.subscriber_id,
        "invoice_id": payload.invoice_id,
        "gateway": payload.gateway,
        "gateway_charge_id": charge_out.gateway_charge_id,
        "billing_type": charge_out.billing_type,
        "amount": charge_out.amount,
        "due_date": charge_out.due_date,
        "status": charge_out.status,
        "boleto_url": charge_out.boleto_url,
        "boleto_digitable_line": charge_out.boleto_digitable_line,
        "pix_qr_code": charge_out.pix_qr_code,
        "pix_qr_code_image_url": charge_out.pix_qr_code_image_url,
        "pix_copy_paste": charge_out.pix_copy_paste,
        "created_at": _now().isoformat(),
        "updated_at": _now().isoformat(),
        "created_by": user.get("name") or user.get("email"),
    }
    await db.payment_charges.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "charge": doc}


# ===========================================================================
# Lista / detalhe / refresh
# ===========================================================================
@router.get("/charges")
async def list_charges(
    subscriber_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(100, le=500),
    user: dict = Depends(get_current_user),
):
    cid = _cid(user)
    q: dict[str, Any] = {"company_id": cid}
    if subscriber_id: q["subscriber_id"] = subscriber_id
    if status: q["status"] = status
    items = await db.payment_charges.find(q, {"_id": 0}).sort(
        "created_at", -1).limit(limit).to_list(limit)
    return {"items": items, "count": len(items)}


@router.get("/charges/{charge_id}")
async def get_charge(
    charge_id: str, refresh: bool = False,
    user: dict = Depends(get_current_user),
):
    cid = _cid(user)
    doc = await db.payment_charges.find_one(
        {"id": charge_id, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Cobrança não encontrada")
    if refresh:
        try:
            gw = get_gateway(doc["gateway"])
            fresh = await gw.get_charge(doc["gateway_charge_id"])
            await db.payment_charges.update_one(
                {"id": charge_id},
                {"$set": {"status": fresh.status,
                           "updated_at": _now().isoformat()}},
            )
            doc["status"] = fresh.status
            doc["updated_at"] = _now().isoformat()
        except GatewayError as e:
            doc["refresh_error"] = str(e)
    return doc


@router.post("/charges/{charge_id}/cancel")
async def cancel_charge(
    charge_id: str, user: dict = Depends(get_current_user),
):
    role = (user.get("role") or "").lower()
    if role not in ("gestor", "administrador", "financeiro") and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador/financeiro.")
    cid = _cid(user)
    doc = await db.payment_charges.find_one(
        {"id": charge_id, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Cobrança não encontrada")
    try:
        gw = get_gateway(doc["gateway"])
        r = await gw.cancel_charge(doc["gateway_charge_id"])
    except GatewayError as e:
        raise HTTPException(502, safe_detail(502, e, "Gateway error:"))
    new_status = r.get("status") or "CANCELED"
    await db.payment_charges.update_one(
        {"id": charge_id},
        {"$set": {"status": new_status, "updated_at": _now().isoformat()}},
    )
    return {"ok": True, "status": new_status}


@router.post("/charges/{charge_id}/refund")
async def refund_charge(
    charge_id: str,
    value: Optional[float] = None,
    user: dict = Depends(get_current_user),
):
    role = (user.get("role") or "").lower()
    if role not in ("gestor", "administrador", "financeiro") and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador/financeiro.")
    cid = _cid(user)
    doc = await db.payment_charges.find_one(
        {"id": charge_id, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Cobrança não encontrada")
    try:
        gw = get_gateway(doc["gateway"])
        r = await gw.refund_charge(doc["gateway_charge_id"], value)
    except GatewayError as e:
        raise HTTPException(502, safe_detail(502, e, "Gateway error:"))
    new_status = r.get("status") or "REFUNDED"
    await db.payment_charges.update_one(
        {"id": charge_id},
        {"$set": {"status": new_status, "updated_at": _now().isoformat()}},
    )
    return {"ok": True, "status": new_status}


# ===========================================================================
# Webhook do Asaas (público — autenticado por token)
# ===========================================================================
@router.post("/webhook/asaas")
async def webhook_asaas(request: Request):
    body = await request.body()
    headers = dict(request.headers)
    try:
        gw = get_gateway("asaas")
    except GatewayError:
        raise HTTPException(503, "Asaas gateway não disponível")

    if not gw.verify_webhook(headers, body):
        logger.warning("[payments] webhook Asaas com token inválido")
        raise HTTPException(401, "Invalid webhook token")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Payload JSON inválido")

    try:
        ev = gw.parse_webhook(payload)
    except GatewayError as e:
        raise HTTPException(400, safe_detail(400, e))

    # Atualiza a cobrança local pelo gateway_charge_id
    doc = await db.payment_charges.find_one(
        {"gateway": "asaas", "gateway_charge_id": ev.charge_id}, {"_id": 0})

    log_entry = {
        "id": f"phlog-{uuid.uuid4().hex[:10]}",
        "gateway": "asaas",
        "event_type": ev.event_type,
        "charge_id": ev.charge_id,
        "status": ev.status,
        "matched_local_id": (doc or {}).get("id"),
        "company_id": (doc or {}).get("company_id"),
        "received_at": _now().isoformat(),
    }
    await db.payment_webhooks.insert_one(log_entry)

    if not doc:
        # Cobrança feita diretamente no painel Asaas — registra mas não bate
        # com nada local. Retorna 200 pra Asaas não reenviar.
        return {"ok": True, "ignored": True, "reason": "charge_not_found"}

    await db.payment_charges.update_one(
        {"id": doc["id"]},
        {"$set": {"status": ev.status,
                   "updated_at": _now().isoformat(),
                   "last_event": ev.event_type}},
    )

    # Se temos invoice_id local, marca fatura como paga
    if ev.status in ("RECEIVED", "CONFIRMED") and doc.get("invoice_id"):
        await db.invoices.update_one(
            {"id": doc["invoice_id"]},
            {"$set": {"status": "paid",
                       "paid_at": _now().isoformat(),
                       "paid_via": f"asaas:{doc['billing_type']}",
                       "paid_charge_id": doc["id"]}},
        )

    return {"ok": True, "event": ev.event_type,
            "charge_id": ev.charge_id, "status": ev.status}
