"""
treasury.py — IA Tesoureira (CTO P0 11/06/2026)
Endpoints da gestão de pagamentos via Asaas Sandbox.
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "treasury-team",
    "domain": "treasury",
    "criticality": "high",
    "emits_events": True,
    "event_types": [
        "treasury.payment_created", "treasury.payment_approved",
        "treasury.payment_sent", "treasury.payment_paid",
        "treasury.payment_failed", "treasury.payment_blocked",
    ],
    "company_id_required": True,
}

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, is_super_admin, now_iso, require_role
from database import db
from services import asaas_client
from services.treasurer_ai import (
    DECISION_APPROVE_AUTO, DECISION_BLOCK, DECISION_REQUIRE_HUMAN, review_payment,
)

log = logging.getLogger("treasury")
router = APIRouter(prefix="/api/treasury", tags=["treasury"])


def _enabled() -> bool:
    v = (os.environ.get("TREASURY_SANDBOX_ENABLED") or "false").lower()
    return v in ("1", "true", "yes", "on")


def _check_sandbox_guard():
    """Iter235: renomeado conceitualmente para _check_treasury_guard.
    A política agora é:
    - TREASURY_SANDBOX_ENABLED=true → tesouraria ativa (em qualquer ambiente)
    - Produção real exige ASAAS_ENV=producao + ASAAS_PROD_ENABLED=true
      (verificado dentro do asaas_client._request — falha rápido lá).
    """
    if not _enabled():
        raise HTTPException(503, "Treasury bloqueada (TREASURY_SANDBOX_ENABLED!=true)")
    # Produção: apenas exige kill-switch quando ASAAS_ENV=producao
    if asaas_client.is_production() and not _prod_kill_switch():
        raise HTTPException(
            503,
            "ASAAS_ENV=producao detectado, mas ASAAS_PROD_ENABLED!=true. "
            "Defina ASAAS_PROD_ENABLED=true em backend/.env após validar a chave de produção.")


def _prod_kill_switch() -> bool:
    v = (os.environ.get("ASAAS_PROD_ENABLED") or "false").strip().lower()
    return v in ("1", "true", "yes", "on")


async def _audit(action: str, payment_id: str, actor: str, cid: str, extra: Optional[Dict] = None):
    try:
        await db.payment_audit_logs.insert_one({
            "id": f"aud-{uuid.uuid4().hex[:14]}",
            "company_id": cid,
            "payment_id": payment_id,
            "action": action,
            "actor": actor,
            "created_at": now_iso(),
            **(extra or {}),
        })
    except Exception as e:
        log.warning("audit falhou: %s", e)


async def _emit_event(event_type: str, cid: str, payload: Dict):
    try:
        await db.system_events.insert_one({
            "id": f"evt-{uuid.uuid4().hex[:14]}",
            "company_id": cid,
            "event_type": event_type,
            "payload": payload,
            "created_at": now_iso(),
        })
    except Exception:
        pass


# ─────────── Models ───────────
class PayeeIn(BaseModel):
    name: str
    document: str
    pix_key: str
    pix_key_type: str = "CPF"
    bank_account: Optional[Dict[str, Any]] = None
    allowed_methods: List[str] = Field(default_factory=lambda: ["PIX"])
    allowed_categories: List[str] = Field(default_factory=list)
    max_amount_auto: float = 500
    category: Optional[str] = None
    risk_level: str = "low"


class PaymentIn(BaseModel):
    payee_id: str
    amount_brl: float
    scheduled_for: str  # ISO date YYYY-MM-DD
    due_date: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    # ── Pix (default) ──
    pix_key: Optional[str] = None  # se vazio, usa do payee
    # ── Boleto (iter235) ──
    method: str = "pix"  # "pix" | "bill"
    identification_field: Optional[str] = None  # linha digitável boleto
    bar_code: Optional[str] = None              # código de barras boleto


class ApproveIn(BaseModel):
    reason: Optional[str] = None


# ─────────── Payees ───────────
@router.post("/payees")
async def create_payee(p: PayeeIn, user: dict = Depends(require_role("gestor"))):
    _check_sandbox_guard()
    cid = user.get("company_id") or DEMO_COMPANY_ID
    pid = f"payee-{uuid.uuid4().hex[:12]}"
    doc = {
        "company_id": cid, "payee_id": pid, "active": True, **p.model_dump(),
        "created_at": now_iso(), "created_by": user.get("email"),
    }
    await db.whitelisted_payees.insert_one(doc)
    await _audit("payee_created", pid, user.get("email") or "?", cid)
    doc.pop("_id", None)
    return doc


@router.get("/payees")
async def list_payees(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    rows = await db.whitelisted_payees.find(
        {"company_id": cid}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    return {"payees": rows, "count": len(rows)}


# ─────────── Payments ───────────
@router.post("/payments")
async def create_payment(p: PaymentIn, user: dict = Depends(require_role("gestor"))):
    _check_sandbox_guard()
    cid = user.get("company_id") or DEMO_COMPANY_ID

    # Idempotência: rejeita se mesmo (payee+valor+data) ativo já existe
    existing = await db.scheduled_payments.find_one({
        "company_id": cid, "payee_id": p.payee_id,
        "amount_brl": p.amount_brl, "scheduled_for": p.scheduled_for,
        "status": {"$nin": ["cancelled", "failed", "expired"]},
    })
    if existing:
        raise HTTPException(409, f"Pagamento equivalente já existe ({existing['payment_id']})")

    payee = await db.whitelisted_payees.find_one({"payee_id": p.payee_id, "company_id": cid})
    pix_key = p.pix_key or (payee or {}).get("pix_key")

    # Validação por método
    method = (p.method or "pix").lower()
    if method == "bill":
        if not p.identification_field and not p.bar_code:
            raise HTTPException(400,
                "Pagamento via boleto exige identification_field (linha digitável) OU bar_code.")
    elif method == "pix":
        if not pix_key:
            raise HTTPException(400, "Pagamento via Pix exige pix_key no payment ou no payee.")
    else:
        raise HTTPException(400, f"method inválido: {method}. Use 'pix' ou 'bill'.")

    payment_id = f"pay-{uuid.uuid4().hex[:14]}"
    doc = {
        "company_id": cid, "payment_id": payment_id,
        "payee_id": p.payee_id, "payee_name": (payee or {}).get("name"),
        "payee_document": (payee or {}).get("document"),
        "method": method,
        "pix_key": pix_key, "pix_key_type": (payee or {}).get("pix_key_type", "CPF"),
        "identification_field": p.identification_field,
        "bar_code": p.bar_code,
        "amount_brl": p.amount_brl, "scheduled_for": p.scheduled_for,
        "due_date": p.due_date, "category": p.category, "description": p.description,
        "provider": "asaas", "provider_transfer_id": None,
        "provider_bill_id": None,
        "status": "draft",
        "created_by": user.get("email"), "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.scheduled_payments.insert_one(doc)
    await _audit("payment_created", payment_id, user.get("email") or "?", cid,
                 {"amount_brl": p.amount_brl})
    await _emit_event("treasury.payment_created", cid, {"payment_id": payment_id, "amount": p.amount_brl})
    doc.pop("_id", None)
    return doc


@router.get("/payments")
async def list_payments(status_eq: Optional[str] = None, limit: int = 100,
                        user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if status_eq:
        q["status"] = status_eq
    rows = await db.scheduled_payments.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return {"payments": rows, "count": len(rows)}


@router.get("/payments/{payment_id}")
async def get_payment(payment_id: str, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.scheduled_payments.find_one({"payment_id": payment_id, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Pagamento não encontrado")
    return doc


@router.get("/payments/{payment_id}/decision")
async def get_payment_decision(payment_id: str, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.treasurer_ai_decisions.find_one(
        {"payment_id": payment_id, "company_id": cid},
        {"_id": 0}, sort=[("created_at", -1)],
    )
    return {"decision": doc}


@router.get("/payments/{payment_id}/audit")
async def get_payment_audit(payment_id: str, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    rows = await db.payment_audit_logs.find(
        {"payment_id": payment_id, "company_id": cid}, {"_id": 0}
    ).sort("created_at", 1).to_list(500)
    return {"audit": rows, "count": len(rows)}


@router.get("/safety")
async def safety_status(user: dict = Depends(require_role("gestor"))):
    """Banner config exibido na UI — confirma ambiente, kill-switch e auto-aprovação."""
    env = "producao" if asaas_client.is_production() else "sandbox"
    return {
        "environment": env,
        "is_production": asaas_client.is_production(),
        "prod_kill_switch_enabled": _prod_kill_switch(),
        "prod_ready": asaas_client.is_production() and _prod_kill_switch() and bool(os.environ.get("ASAAS_API_KEY")) and bool(os.environ.get("ASAAS_WEBHOOK_TOKEN")),
        "treasury_enabled": _enabled(),
        "auto_approval_enabled": (os.environ.get("TREASURY_AUTO_APPROVAL_ENABLED") or "false").lower() in ("1", "true", "yes", "on"),
        "auto_approval_max_brl": float(os.environ.get("TREASURY_AUTO_APPROVAL_MAX_BRL", "500")),
        "daily_auto_cap_brl": float(os.environ.get("TREASURY_DAILY_AUTO_CAP_BRL", "2000")),
        "human_required_above_brl": float(os.environ.get("TREASURY_HUMAN_REQUIRED_ABOVE_BRL", "3000")),
        "anomaly_threshold_pct": float(os.environ.get("TREASURY_ANOMALY_THRESHOLD_PCT", "30")),
        "has_asaas_key": bool(os.environ.get("ASAAS_API_KEY")),
        "has_webhook_token": bool(os.environ.get("ASAAS_WEBHOOK_TOKEN")),
    }


@router.post("/payments/{payment_id}/ai-review")
async def ai_review(payment_id: str, user: dict = Depends(require_role("gestor"))):
    _check_sandbox_guard()
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.scheduled_payments.find_one({"payment_id": payment_id, "company_id": cid})
    if not doc:
        raise HTTPException(404, "Pagamento não encontrado")

    decision = await review_payment(doc)
    decision_doc = {
        "id": f"aidec-{uuid.uuid4().hex[:12]}",
        "company_id": cid, "payment_id": payment_id,
        **decision, "created_at": now_iso(),
    }
    await db.treasurer_ai_decisions.insert_one(decision_doc)

    new_status = doc["status"]
    if decision["decision"] == DECISION_BLOCK:
        new_status = "blocked_risk"
    elif decision["decision"] == DECISION_REQUIRE_HUMAN:
        new_status = "pending_human_approval"
    elif decision["decision"] == DECISION_APPROVE_AUTO:
        new_status = "approved"

    await db.scheduled_payments.update_one(
        {"payment_id": payment_id},
        {"$set": {
            "status": new_status,
            "ai_decision": decision["decision"],
            "ai_risk_score": decision["risk_score"],
            "updated_at": now_iso(),
            **({"approved_at": now_iso(), "approval_kind": "auto"} if decision["decision"] == DECISION_APPROVE_AUTO else {}),
        }},
    )
    await _audit(f"ai_review:{decision['decision']}", payment_id, "treasurer-ai", cid,
                 {"risk_score": decision["risk_score"]})
    if decision["decision"] == DECISION_BLOCK:
        await _emit_event("treasury.payment_blocked", cid, {"payment_id": payment_id})
    decision_doc.pop("_id", None)
    return {"new_status": new_status, "decision": decision_doc}


@router.post("/payments/{payment_id}/approve")
async def approve_payment(payment_id: str, body: ApproveIn = ApproveIn(),
                          user: dict = Depends(require_role("gestor"))):
    _check_sandbox_guard()
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.scheduled_payments.find_one({"payment_id": payment_id, "company_id": cid})
    if not doc:
        raise HTTPException(404, "Pagamento não encontrado")
    if doc["status"] in ("paid", "sent_to_bank", "cancelled", "failed"):
        raise HTTPException(409, f"Pagamento já em estado terminal: {doc['status']}")
    # Acima de R$ 3000 exige super_admin
    if doc["amount_brl"] > float(os.environ.get("TREASURY_HUMAN_REQUIRED_ABOVE_BRL", "3000")):
        if not is_super_admin(user):
            raise HTTPException(403, "Aprovação obrigatória do CTO/dono (super_admin) para valor acima do teto")

    await db.scheduled_payments.update_one(
        {"payment_id": payment_id},
        {"$set": {
            "status": "approved",
            "approved_at": now_iso(),
            "approved_by": user.get("email"),
            "approval_kind": "human",
            "approval_reason": body.reason,
            "updated_at": now_iso(),
        }},
    )
    await _audit("payment_approved_human", payment_id, user.get("email") or "?", cid)
    await _emit_event("treasury.payment_approved", cid, {"payment_id": payment_id})
    return {"ok": True, "payment_id": payment_id, "new_status": "approved"}


@router.post("/payments/{payment_id}/cancel")
async def cancel_payment(payment_id: str, user: dict = Depends(require_role("gestor"))):
    _check_sandbox_guard()
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.scheduled_payments.find_one({"payment_id": payment_id, "company_id": cid})
    if not doc:
        raise HTTPException(404, "Pagamento não encontrado")
    # Tenta cancelar no Asaas se já foi enviado
    asaas_result = None
    if doc.get("provider_transfer_id"):
        asaas_result = await asaas_client.cancel_transfer_if_possible(doc["provider_transfer_id"])
    await db.scheduled_payments.update_one(
        {"payment_id": payment_id},
        {"$set": {"status": "cancelled", "cancelled_at": now_iso(),
                  "cancelled_by": user.get("email"), "updated_at": now_iso()}},
    )
    await _audit("payment_cancelled", payment_id, user.get("email") or "?", cid,
                 {"asaas_cancel_response": asaas_result})
    return {"ok": True, "asaas_cancel": asaas_result}


@router.post("/payments/{payment_id}/send")
async def send_payment(payment_id: str, user: dict = Depends(require_role("gestor"))):
    """Envia ao Asaas. Idempotente. Ramifica entre Pix e Boleto."""
    _check_sandbox_guard()
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.scheduled_payments.find_one({"payment_id": payment_id, "company_id": cid})
    if not doc:
        raise HTTPException(404, "Pagamento não encontrado")
    if doc["status"] != "approved":
        raise HTTPException(409, f"Só envia pagamentos APROVADOS. Atual: {doc['status']}")
    # Idempotência por provider id (Pix ou Boleto)
    if doc.get("provider_transfer_id"):
        return {"ok": True, "already_sent": True, "method": "pix",
                "transfer_id": doc["provider_transfer_id"]}
    if doc.get("provider_bill_id"):
        return {"ok": True, "already_sent": True, "method": "bill",
                "bill_id": doc["provider_bill_id"]}

    method = (doc.get("method") or "pix").lower()

    if method == "bill":
        result = await asaas_client.create_bill_payment(
            identification_field=doc.get("identification_field"),
            bar_code=doc.get("bar_code"),
            value=doc["amount_brl"],
            due_date=doc.get("due_date"),
            schedule_date=doc.get("scheduled_for"),
            description=doc.get("description") or f"Boleto {doc.get('payee_name','')}",
            external_reference=payment_id,
        )
    else:
        result = await asaas_client.create_transfer_pix(
            value=doc["amount_brl"],
            pix_key=doc["pix_key"],
            pix_key_type=doc.get("pix_key_type", "CPF"),
            schedule_date=doc.get("scheduled_for"),
            description=doc.get("description") or f"Pagamento {doc.get('payee_name','')}",
            external_reference=payment_id,
        )

    if not result.get("ok"):
        await db.scheduled_payments.update_one(
            {"payment_id": payment_id},
            {"$set": {"status": "failed", "last_error": result, "updated_at": now_iso()}},
        )
        await _audit("payment_send_failed", payment_id, user.get("email") or "?", cid, {"error": result, "method": method})
        await _emit_event("treasury.payment_failed", cid, {"payment_id": payment_id, "method": method, "error": result})
        return {"ok": False, "method": method, "asaas": result}

    provider_id = result.get("id")
    update_fields: Dict[str, Any] = {
        "status": "sent_to_bank",
        "sent_at": now_iso(),
        "sent_by": user.get("email"),
        "asaas_response": {k: v for k, v in result.items() if k != "ok"},
        "updated_at": now_iso(),
    }
    if method == "bill":
        update_fields["provider_bill_id"] = provider_id
    else:
        update_fields["provider_transfer_id"] = provider_id
    await db.scheduled_payments.update_one({"payment_id": payment_id}, {"$set": update_fields})
    await _audit("payment_sent", payment_id, user.get("email") or "?", cid,
                 {"provider_id": provider_id, "method": method})
    await _emit_event("treasury.payment_sent", cid,
                      {"payment_id": payment_id, "provider_id": provider_id, "method": method})
    return {"ok": True, "method": method, "provider_id": provider_id, "asaas_status": result.get("status")}


# ─────────── Boleto: utilidades ───────────
class BillSimulateIn(BaseModel):
    identification_field: Optional[str] = None
    bar_code: Optional[str] = None


@router.post("/bill/simulate")
async def bill_simulate(p: BillSimulateIn, user: dict = Depends(require_role("gestor"))):
    """Valida linha digitável/cód de barras antes de criar pagamento.
    Retorna valor, vencimento e cedente — útil pra UI confirmar com o gestor."""
    _check_sandbox_guard()
    if not p.identification_field and not p.bar_code:
        raise HTTPException(400, "Informe identification_field ou bar_code.")
    return await asaas_client.simulate_bill_payment(
        identification_field=p.identification_field,
        bar_code=p.bar_code,
    )


@router.get("/balance")
async def asaas_balance(user: dict = Depends(require_role("gestor"))):
    """Consulta saldo da conta Asaas (sandbox/homologação/produção)."""
    _check_sandbox_guard()
    return await asaas_client.get_balance()


# ─────────── Webhook ───────────
@router.post("/webhooks/asaas")
async def asaas_webhook(request: Request):
    token = request.headers.get("asaas-access-token") or request.query_params.get("token") or ""
    if not asaas_client.verify_webhook_token(token):
        raise HTTPException(401, "Webhook token inválido")
    payload = await request.json()
    # Persistir bruto
    await db.payment_bank_events.insert_one({
        "id": f"bnk-{uuid.uuid4().hex[:14]}",
        "received_at": now_iso(),
        "payload": payload,
    })
    transfer = payload.get("transfer") or payload.get("bill") or payload
    asaas_id = transfer.get("id")
    event = payload.get("event") or transfer.get("status")
    if asaas_id:
        new_status = None
        # Eventos de transferência Pix
        if event in ("TRANSFER_DONE", "DONE"):
            new_status = "paid"
        elif event in ("TRANSFER_FAILED", "FAILED"):
            new_status = "failed"
        elif event in ("TRANSFER_CANCELLED", "CANCELLED"):
            new_status = "cancelled"
        # Eventos de boleto (Bill Payment)
        elif event in ("PAYMENT_BILL_PAID", "BILL_PAID", "PAID"):
            new_status = "paid"
        elif event in ("PAYMENT_BILL_FAILED", "BILL_FAILED"):
            new_status = "failed"
        elif event in ("PAYMENT_BILL_CANCELLED", "BILL_CANCELLED"):
            new_status = "cancelled"
        if new_status:
            # Casa por provider_transfer_id OU provider_bill_id
            res = await db.scheduled_payments.update_one(
                {"$or": [
                    {"provider_transfer_id": asaas_id},
                    {"provider_bill_id": asaas_id},
                ]},
                {"$set": {"status": new_status, "updated_at": now_iso(),
                          "last_webhook_event": event}},
            )
            if res.modified_count and new_status == "paid":
                doc = await db.scheduled_payments.find_one({"$or": [
                    {"provider_transfer_id": asaas_id},
                    {"provider_bill_id": asaas_id},
                ]})
                if doc:
                    await _emit_event("treasury.payment_paid", doc["company_id"],
                                      {"payment_id": doc["payment_id"],
                                       "method": doc.get("method", "pix")})
    return {"ok": True}


# ─────────── KPIs ───────────
@router.get("/kpis")
async def kpis(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    def _q(status: str, since: Optional[str] = None) -> Dict[str, Any]:
        q: Dict[str, Any] = {"company_id": cid, "status": status}
        if since:
            q["created_at"] = {"$gte": since}
        return q

    async def _sum(query: Dict) -> float:
        async for r in db.scheduled_payments.aggregate(
            [{"$match": query}, {"$group": {"_id": None, "s": {"$sum": "$amount_brl"}}}]
        ):
            return float(r.get("s") or 0)
        return 0.0

    saldo = await asaas_client.get_balance() if os.environ.get("ASAAS_API_KEY") else {"ok": False}

    async def _by(field: str):
        out = {}
        async for r in db.scheduled_payments.aggregate([
            {"$match": {"company_id": cid, "status": {"$in": ["sent_to_bank", "paid"]}}},
            {"$group": {"_id": f"${field}", "s": {"$sum": "$amount_brl"}}},
            {"$sort": {"s": -1}},
            {"$limit": 10},
        ]):
            out[str(r["_id"] or "—")] = float(r["s"])
        return out

    forecast = {}
    for days in (7, 15, 30):
        end = (now + timedelta(days=days)).date().isoformat()
        forecast[f"{days}d"] = await _sum({
            "company_id": cid,
            "status": {"$in": ["approved", "scheduled", "pending_human_approval", "sent_to_bank"]},
            "scheduled_for": {"$lte": end},
        })

    return {
        "today_scheduled": await _sum(_q("approved", today_start)) + await _sum(_q("scheduled", today_start)),
        "today_paid": await _sum(_q("paid", today_start)),
        "pending_approval": await _sum(_q("pending_human_approval")),
        "blocked_risk": await _sum(_q("blocked_risk")),
        "failed": await _sum(_q("failed")),
        "by_category": await _by("category"),
        "by_payee": await _by("payee_name"),
        "saldo_asaas": saldo,
        "outflow_forecast": forecast,
    }


@router.get("/outflow-forecast")
async def outflow_forecast(user: dict = Depends(require_role("gestor"))):
    return (await kpis(user))["outflow_forecast"]
