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

import base64
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
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
class PayeeAddress(BaseModel):
    cep: Optional[str] = None
    street: Optional[str] = None
    number: Optional[str] = None
    complement: Optional[str] = None
    neighborhood: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None


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
    # iter238 — Fornecedores IA
    address: Optional[PayeeAddress] = None
    whatsapp: Optional[str] = None  # E.164 ou BR pra envio de comprovante
    default_account_id: Optional[str] = None  # conta padrão pra pagar
    email: Optional[str] = None
    notes: Optional[str] = None
    auto_send_receipt: bool = True  # após pagar, dispara comprovante WA automaticamente


class PayeeUpdate(BaseModel):
    name: Optional[str] = None
    document: Optional[str] = None
    pix_key: Optional[str] = None
    pix_key_type: Optional[str] = None
    address: Optional[PayeeAddress] = None
    whatsapp: Optional[str] = None
    default_account_id: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None
    auto_send_receipt: Optional[bool] = None
    active: Optional[bool] = None
    category: Optional[str] = None
    allowed_methods: Optional[List[str]] = None
    risk_level: Optional[str] = None
    max_amount_auto: Optional[float] = None


class PaymentIn(BaseModel):
    payee_id: str
    amount_brl: float
    scheduled_for: str  # ISO date YYYY-MM-DD
    due_date: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    # CTO 2026-02 (ordem CEO): "gastos são feitos dentro das filiais".
    # O pagamento é apontado para uma filial específica no momento do
    # registro (não no cadastro do fornecedor). Permite ratear gastos.
    filial_id: Optional[str] = None
    # ── Pix (default) ──
    pix_key: Optional[str] = None  # se vazio, usa do payee
    pix_key_type: Optional[str] = None  # sobrescreve tipo do payee se enviado
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


@router.patch("/payees/{payee_id}")
async def update_payee(payee_id: str, p: PayeeUpdate,
                        user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    existing = await db.whitelisted_payees.find_one({"payee_id": payee_id, "company_id": cid})
    if not existing:
        raise HTTPException(404, "Fornecedor não encontrado")
    update = {k: v for k, v in p.model_dump(exclude_none=True).items()}
    if "address" in update and update["address"] is not None:
        # mantém dict puro
        if hasattr(update["address"], "model_dump"):
            update["address"] = update["address"].model_dump()
    update["updated_at"] = now_iso()
    update["updated_by"] = user.get("email") or "?"
    await db.whitelisted_payees.update_one(
        {"payee_id": payee_id, "company_id": cid}, {"$set": update})
    doc = await db.whitelisted_payees.find_one(
        {"payee_id": payee_id, "company_id": cid}, {"_id": 0})
    await _audit("payee_updated", payee_id, user.get("email") or "?", cid,
                 {"fields": list(update.keys())})
    return doc


@router.delete("/payees/{payee_id}")
async def delete_payee(payee_id: str, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    existing = await db.whitelisted_payees.find_one({"payee_id": payee_id, "company_id": cid})
    if not existing:
        raise HTTPException(404, "Fornecedor não encontrado")
    # Verifica se tem pagamentos pendentes
    pending = await db.scheduled_payments.count_documents({
        "payee_id": payee_id, "company_id": cid,
        "status": {"$in": ["draft", "pending_human_approval", "approved", "sent_to_bank"]},
    })
    if pending > 0:
        raise HTTPException(409,
            f"Fornecedor tem {pending} pagamento(s) pendente(s). Inative em vez de deletar.")
    await db.whitelisted_payees.update_one(
        {"payee_id": payee_id, "company_id": cid},
        {"$set": {"active": False, "deleted_at": now_iso(),
                  "deleted_by": user.get("email") or "?"}})
    return {"ok": True}


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
    pix_key_type = p.pix_key_type or (payee or {}).get("pix_key_type", "CPF")

    # CTO 2026-02 (ordem CEO): validação da filial (quando informada).
    # Pagamento sem filial é permitido por compat — mas geramos warning.
    filial_doc = None
    if p.filial_id:
        filial_doc = await db.fin_filiais.find_one(
            {"id": p.filial_id, "company_id": cid},
            {"_id": 0, "id": 1, "name": 1, "active": 1},
        )
        if not filial_doc:
            raise HTTPException(404, f"Filial {p.filial_id} não encontrada.")
        if filial_doc.get("active") is False:
            raise HTTPException(400,
                f"Filial '{filial_doc.get('name')}' está inativa.")

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
        "pix_key": pix_key, "pix_key_type": pix_key_type,
        "identification_field": p.identification_field,
        "bar_code": p.bar_code,
        "amount_brl": p.amount_brl, "scheduled_for": p.scheduled_for,
        "due_date": p.due_date, "category": p.category, "description": p.description,
        # P0 CEO 2026-02: linkagem com filial onde o gasto é feito.
        "filial_id": p.filial_id,
        "filial_name": (filial_doc or {}).get("name") if filial_doc else None,
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
async def list_payments(status_eq: Optional[str] = None,
                        month: Optional[str] = None,        # YYYY-MM
                        month_from: Optional[str] = None,   # YYYY-MM
                        month_to: Optional[str] = None,     # YYYY-MM
                        filial_id: Optional[str] = None,    # P0 CEO 2026-02
                        limit: int = 500,
                        user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if status_eq:
        q["status"] = status_eq
    if filial_id:
        # "__none__" filtra pagamentos sem filial atribuída
        if filial_id == "__none__":
            q["$or"] = [{"filial_id": None}, {"filial_id": {"$exists": False}}]
        else:
            q["filial_id"] = filial_id
    if month or month_from or month_to:
        gte, lt = _month_bounds(month, month_from, month_to)
        if gte and lt:
            q["scheduled_for"] = {"$gte": gte, "$lt": lt}
    rows = await db.scheduled_payments.find(q, {"_id": 0}).sort("scheduled_for", 1).to_list(limit)
    return {"payments": rows, "count": len(rows)}


def _month_bounds(month: Optional[str], mfrom: Optional[str],
                  mto: Optional[str]) -> tuple:
    """Aceita month=YYYY-MM OU month_from/to=YYYY-MM. Retorna (>=gte, <lt) ISO."""
    def parse(s: str) -> Optional[datetime]:
        try:
            y, m = s.split("-")
            return datetime(int(y), int(m), 1)
        except Exception:
            return None
    if month:
        a = parse(month)
        if not a:
            return (None, None)
        b = a.replace(year=a.year + (1 if a.month == 12 else 0),
                      month=(a.month % 12) + 1)
        return (a.date().isoformat(), b.date().isoformat())
    a = parse(mfrom) if mfrom else None
    b = parse(mto) if mto else None
    if a and not b:
        b = a
    if b and not a:
        a = b
    if not a or not b:
        return (None, None)
    end = b.replace(year=b.year + (1 if b.month == 12 else 0),
                    month=(b.month % 12) + 1)
    return (a.date().isoformat(), end.date().isoformat())


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
                    await _auto_send_receipt_if_enabled(doc)
    return {"ok": True}


async def _auto_send_receipt_if_enabled(payment: Dict[str, Any]) -> None:
    """Se o fornecedor tem WhatsApp + auto_send_receipt=True, dispara comprovante."""
    try:
        payee = await db.whitelisted_payees.find_one({
            "payee_id": payment.get("payee_id"),
            "company_id": payment.get("company_id"),
        })
        if not payee:
            return
        if not payee.get("auto_send_receipt", True):
            return
        phone = payee.get("whatsapp")
        if not phone:
            return
        result = await send_receipt_whatsapp(payment, phone)
        await db.payment_audit_logs.insert_one({
            "id": f"aud-{uuid.uuid4().hex[:14]}",
            "company_id": payment.get("company_id"),
            "payment_id": payment.get("payment_id"),
            "action": "receipt_auto_sent",
            "actor": "system",
            "created_at": now_iso(),
            "phone": phone, "result": result,
        })
    except Exception as e:
        log.warning("auto_send_receipt falhou: %s", e)


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


# ════════════════════════════════════════════════════════════════════════════
# ITER236 — Reforma Contas a Pagar (CTO 12/06/2026)
# - Multi-conta com 1 conta padrão de pagamento
# - DDA Inbox (boletos recebidos aguardando aprovação)
# - Recorrência com início/fim/valor total
# - Envio de comprovante via WhatsApp (assinatura by SmartProv)
# - Pagamento manual Pix por telefone (chave PHONE)
# ════════════════════════════════════════════════════════════════════════════

from services.treasury_receipts import send_receipt_whatsapp, build_receipt_text  # noqa: E402


# ─────────────────────── 1. MULTI-CONTAS ───────────────────────────────────

class PaymentAccountIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    bank: Optional[str] = "Asaas"
    cnpj: Optional[str] = None
    pix_keys: List[str] = Field(default_factory=list)  # chaves Pix da própria conta
    description: Optional[str] = None
    is_default: bool = False


@router.get("/accounts")
async def list_accounts(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    docs = await db.treasury_accounts.find({"company_id": cid}, {"_id": 0}).to_list(500)
    if not docs:
        # auto-cria conta default Asaas
        d = {
            "account_id": f"acc-{uuid.uuid4().hex[:12]}", "company_id": cid,
            "name": "Conta Asaas principal", "bank": "Asaas",
            "is_default": True, "active": True,
            "created_at": now_iso(), "created_by": user.get("email") or "system",
        }
        await db.treasury_accounts.insert_one(d)
        d.pop("_id", None)
        docs = [d]
    return {"accounts": docs}


@router.post("/accounts")
async def create_account(p: PaymentAccountIn, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if p.is_default:
        await db.treasury_accounts.update_many(
            {"company_id": cid}, {"$set": {"is_default": False}})
    doc = {
        "account_id": f"acc-{uuid.uuid4().hex[:12]}", "company_id": cid,
        "name": p.name, "bank": p.bank, "cnpj": p.cnpj,
        "pix_keys": p.pix_keys, "description": p.description,
        "is_default": bool(p.is_default), "active": True,
        "created_at": now_iso(), "created_by": user.get("email") or "system",
    }
    await db.treasury_accounts.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.post("/accounts/{account_id}/set-default")
async def set_default_account(account_id: str, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.treasury_accounts.find_one({"account_id": account_id, "company_id": cid})
    if not doc:
        raise HTTPException(404, "Conta não encontrada")
    await db.treasury_accounts.update_many(
        {"company_id": cid}, {"$set": {"is_default": False}})
    await db.treasury_accounts.update_one(
        {"account_id": account_id}, {"$set": {"is_default": True}})
    return {"ok": True, "default_account_id": account_id}


@router.delete("/accounts/{account_id}")
async def delete_account(account_id: str, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.treasury_accounts.find_one({"account_id": account_id, "company_id": cid})
    if not doc:
        raise HTTPException(404, "Conta não encontrada")
    if doc.get("is_default"):
        raise HTTPException(400, "Não é possível excluir a conta padrão. Defina outra como padrão antes.")
    await db.treasury_accounts.update_one(
        {"account_id": account_id}, {"$set": {"active": False, "deleted_at": now_iso()}})
    return {"ok": True}


# ─────────────────────── 2. DDA INBOX ─────────────────────────────────────
# DDA: boletos que chegam à empresa via banco/registro. O Asaas em si não
# tem endpoint de "boletos a pagar do cliente"; quem alimenta este inbox é
# o gestor (manual via UI) ou um futuro conector bancário. O fluxo é:
#   recebido (DDA) → aprovado → vira scheduled_payment (boleto)
# Status: pending | approved | rejected | scheduled

class DDAInvoiceIn(BaseModel):
    payee_name: str
    payee_document: Optional[str] = None
    amount_brl: float
    due_date: str  # YYYY-MM-DD
    identification_field: Optional[str] = None
    bar_code: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    source: str = "manual"  # manual | bank_dda | upload | email
    raw_payload: Optional[Dict[str, Any]] = None


@router.get("/dda/inbox")
async def list_dda_inbox(status: Optional[str] = None,
                          user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if status:
        q["status"] = status
    docs = await db.dda_inbox.find(q, {"_id": 0}).sort("due_date", 1).to_list(500)
    counts = {
        "pending": await db.dda_inbox.count_documents({"company_id": cid, "status": "pending"}),
        "approved": await db.dda_inbox.count_documents({"company_id": cid, "status": "approved"}),
        "rejected": await db.dda_inbox.count_documents({"company_id": cid, "status": "rejected"}),
        "scheduled": await db.dda_inbox.count_documents({"company_id": cid, "status": "scheduled"}),
    }
    return {"inbox": docs, "counts": counts}


@router.post("/dda/inbox")
async def create_dda_invoice(p: DDAInvoiceIn, user: dict = Depends(require_role("gestor"))):
    if not p.identification_field and not p.bar_code:
        raise HTTPException(400,
            "É necessário identification_field (linha digitável) OU bar_code")
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = {
        "dda_id": f"dda-{uuid.uuid4().hex[:14]}", "company_id": cid,
        "payee_name": p.payee_name, "payee_document": p.payee_document,
        "amount_brl": float(p.amount_brl), "due_date": p.due_date,
        "identification_field": p.identification_field, "bar_code": p.bar_code,
        "description": p.description, "category": p.category,
        "source": p.source, "raw_payload": p.raw_payload,
        "status": "pending", "received_at": now_iso(),
        "received_by": user.get("email") or "system",
    }
    await db.dda_inbox.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.post("/dda/{dda_id}/approve")
async def approve_dda(dda_id: str, user: dict = Depends(require_role("gestor"))):
    """Aprova boleto DDA → cria scheduled_payment (boleto) automaticamente."""
    _check_sandbox_guard()
    cid = user.get("company_id") or DEMO_COMPANY_ID
    dda = await db.dda_inbox.find_one({"dda_id": dda_id, "company_id": cid})
    if not dda:
        raise HTTPException(404, "Boleto DDA não encontrado")
    if dda["status"] != "pending":
        raise HTTPException(409, f"Status já é {dda['status']}")

    # cria/usa payee virtual
    payee_id = f"payee-dda-{uuid.uuid4().hex[:10]}"
    payee_doc = {
        "company_id": cid, "payee_id": payee_id,
        "name": dda.get("payee_name") or "Beneficiário DDA",
        "document": dda.get("payee_document"),
        "allowed_methods": ["BILL"], "active": True,
        "created_at": now_iso(), "created_by": user.get("email") or "system",
        "from_dda": dda_id,
    }
    await db.whitelisted_payees.insert_one(payee_doc)

    payment_id = f"pay-{uuid.uuid4().hex[:14]}"
    payment_doc = {
        "company_id": cid, "payment_id": payment_id,
        "payee_id": payee_id, "payee_name": dda.get("payee_name"),
        "payee_document": dda.get("payee_document"),
        "method": "bill",
        "identification_field": dda.get("identification_field"),
        "bar_code": dda.get("bar_code"),
        "amount_brl": float(dda["amount_brl"]),
        "scheduled_for": dda["due_date"], "due_date": dda["due_date"],
        "category": dda.get("category") or "DDA",
        "description": dda.get("description") or f"Boleto DDA — {dda.get('payee_name')}",
        "provider": "asaas", "provider_transfer_id": None, "provider_bill_id": None,
        "status": "draft", "dda_id": dda_id,
        "created_by": user.get("email") or "system",
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.scheduled_payments.insert_one(payment_doc)
    await db.dda_inbox.update_one(
        {"dda_id": dda_id},
        {"$set": {"status": "scheduled", "approved_at": now_iso(),
                  "approved_by": user.get("email") or "?",
                  "linked_payment_id": payment_id}},
    )
    payment_doc.pop("_id", None)
    await _audit("dda_approved", payment_id, user.get("email") or "?", cid,
                 {"dda_id": dda_id})
    return {"ok": True, "dda_id": dda_id, "payment_id": payment_id, "payment": payment_doc}


@router.post("/dda/{dda_id}/reject")
async def reject_dda(dda_id: str, reason: Optional[str] = None,
                      user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    dda = await db.dda_inbox.find_one({"dda_id": dda_id, "company_id": cid})
    if not dda:
        raise HTTPException(404, "Boleto DDA não encontrado")
    await db.dda_inbox.update_one(
        {"dda_id": dda_id},
        {"$set": {"status": "rejected", "rejected_at": now_iso(),
                  "rejected_by": user.get("email") or "?", "rejection_reason": reason}},
    )
    return {"ok": True}


# ─────────────────────── 3. RECORRÊNCIAS ───────────────────────────────────
# Recorrência com período (início, fim) e valor TOTAL. O total é dividido
# em N parcelas mensais (frequency=monthly por padrão).

class RecurringIn(BaseModel):
    payee_id: str
    amount_total_brl: float  # valor total da recorrência (será dividido por N parcelas)
    start_date: str          # YYYY-MM-DD
    end_date: str            # YYYY-MM-DD
    frequency: str = "monthly"  # monthly | weekly | biweekly
    method: str = "pix"      # pix | bill
    description: Optional[str] = None
    category: Optional[str] = None
    pix_key: Optional[str] = None
    pay_day: int = 5         # dia do mês pra cobrar (1-28)
    auto_create_drafts: bool = True  # já gera todos os drafts na criação?


def _months_between(start: str, end: str) -> int:
    a = datetime.fromisoformat(start)
    b = datetime.fromisoformat(end)
    return max(1, (b.year - a.year) * 12 + (b.month - a.month) + 1)


@router.get("/recurring")
async def list_recurring(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    docs = await db.recurring_payments.find({"company_id": cid}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"recurring": docs}


@router.post("/recurring")
async def create_recurring(p: RecurringIn, user: dict = Depends(require_role("gestor"))):
    _check_sandbox_guard()
    cid = user.get("company_id") or DEMO_COMPANY_ID
    payee = await db.whitelisted_payees.find_one({"payee_id": p.payee_id, "company_id": cid})
    if not payee:
        raise HTTPException(404, "Beneficiário não encontrado")
    n = _months_between(p.start_date, p.end_date)
    parcel = round(float(p.amount_total_brl) / n, 2)
    rec_id = f"rec-{uuid.uuid4().hex[:12]}"
    rec = {
        "recurring_id": rec_id, "company_id": cid,
        "payee_id": p.payee_id, "payee_name": payee.get("name"),
        "amount_total_brl": float(p.amount_total_brl),
        "parcel_amount_brl": parcel, "installments": n,
        "start_date": p.start_date, "end_date": p.end_date,
        "frequency": p.frequency, "pay_day": p.pay_day,
        "method": p.method, "description": p.description, "category": p.category,
        "pix_key": p.pix_key or payee.get("pix_key"),
        "active": True, "status": "active",
        "generated_payment_ids": [],
        "created_at": now_iso(), "created_by": user.get("email") or "system",
    }
    await db.recurring_payments.insert_one(rec)

    payment_ids: List[str] = []
    if p.auto_create_drafts:
        start = datetime.fromisoformat(p.start_date)
        for i in range(n):
            month = start.month + i
            year = start.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            day = min(p.pay_day, 28)
            sched = f"{year:04d}-{month:02d}-{day:02d}"
            pid = f"pay-{uuid.uuid4().hex[:14]}"
            payment_doc = {
                "company_id": cid, "payment_id": pid,
                "payee_id": p.payee_id, "payee_name": payee.get("name"),
                "payee_document": payee.get("document"),
                "method": p.method,
                "pix_key": p.pix_key or payee.get("pix_key"),
                "pix_key_type": payee.get("pix_key_type", "CPF"),
                "amount_brl": parcel,
                "scheduled_for": sched, "due_date": sched,
                "category": p.category or "Recorrente",
                "description": f"{(p.description or 'Recorrência')} ({i+1}/{n})",
                "provider": "asaas", "provider_transfer_id": None, "provider_bill_id": None,
                "status": "draft", "recurring_id": rec_id, "installment_no": i + 1,
                "created_by": user.get("email") or "system",
                "created_at": now_iso(), "updated_at": now_iso(),
            }
            await db.scheduled_payments.insert_one(payment_doc)
            payment_ids.append(pid)
        await db.recurring_payments.update_one(
            {"recurring_id": rec_id},
            {"$set": {"generated_payment_ids": payment_ids}})
    rec.pop("_id", None)
    rec["generated_payment_ids"] = payment_ids
    return rec


@router.post("/recurring/{recurring_id}/cancel")
async def cancel_recurring(recurring_id: str,
                            user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    rec = await db.recurring_payments.find_one({"recurring_id": recurring_id, "company_id": cid})
    if not rec:
        raise HTTPException(404, "Recorrência não encontrada")
    # cancela drafts futuros vinculados
    today = datetime.now(timezone.utc).date().isoformat()
    await db.scheduled_payments.update_many(
        {"recurring_id": recurring_id, "status": "draft",
         "scheduled_for": {"$gte": today}},
        {"$set": {"status": "cancelled", "cancelled_at": now_iso(),
                  "cancel_reason": "Recorrência cancelada"}},
    )
    await db.recurring_payments.update_one(
        {"recurring_id": recurring_id},
        {"$set": {"active": False, "status": "cancelled",
                  "cancelled_at": now_iso()}},
    )
    return {"ok": True}


# ─────────────────────── 4. COMPROVANTE WHATSAPP ───────────────────────────

class SendReceiptIn(BaseModel):
    phone: str  # E.164 ou nacional BR


@router.post("/payments/{payment_id}/send-receipt")
async def send_payment_receipt(payment_id: str, p: SendReceiptIn,
                                user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    pay = await db.scheduled_payments.find_one({"payment_id": payment_id, "company_id": cid})
    if not pay:
        raise HTTPException(404, "Pagamento não encontrado")
    if pay.get("status") not in ("sent_to_bank", "paid"):
        raise HTTPException(409,
            f"Comprovante só pode ser enviado quando status=sent_to_bank ou paid. Atual: {pay.get('status')}")
    result = await send_receipt_whatsapp(pay, p.phone)
    await db.payment_audit_logs.insert_one({
        "id": f"aud-{uuid.uuid4().hex[:14]}", "company_id": cid,
        "payment_id": payment_id, "action": "receipt_whatsapp",
        "actor": user.get("email") or "?", "created_at": now_iso(),
        "phone": p.phone, "result": result,
    })
    return result


@router.get("/payments/{payment_id}/receipt-preview")
async def receipt_preview(payment_id: str, user: dict = Depends(require_role("gestor"))):
    """Retorna o TEXTO do comprovante que seria enviado (preview UI)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    pay = await db.scheduled_payments.find_one({"payment_id": payment_id, "company_id": cid})
    if not pay:
        raise HTTPException(404, "Pagamento não encontrado")
    return {"text": build_receipt_text(pay)}



# ─────────────────────── ITER237 — Por mês + auto-elegível + pago manual ─────

class AutoEligibleIn(BaseModel):
    eligible: bool


@router.post("/payments/{payment_id}/auto-eligible")
async def toggle_auto_eligible(payment_id: str, p: AutoEligibleIn,
                                user: dict = Depends(require_role("gestor"))):
    """Marca/desmarca o pagamento como elegível para auto-aprovação acima do
    teto normal (TREASURY_AUTO_APPROVAL_MAX_BRL). Permite ao CTO autorizar
    valores grandes a serem aprovados/enviados sem revisão humana adicional.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.scheduled_payments.find_one({"payment_id": payment_id, "company_id": cid})
    if not doc:
        raise HTTPException(404, "Pagamento não encontrado")
    await db.scheduled_payments.update_one(
        {"payment_id": payment_id},
        {"$set": {"auto_approval_eligible": bool(p.eligible),
                  "auto_eligible_marked_by": user.get("email") or "?",
                  "auto_eligible_marked_at": now_iso(),
                  "updated_at": now_iso()}},
    )
    await _audit("auto_eligible_toggled", payment_id,
                 user.get("email") or "?", cid, {"eligible": p.eligible})
    return {"ok": True, "auto_approval_eligible": bool(p.eligible)}


class MarkPaidManualIn(BaseModel):
    paid_at: Optional[str] = None
    note: Optional[str] = None


@router.post("/payments/{payment_id}/mark-paid-manual")
async def mark_paid_manual(payment_id: str, p: MarkPaidManualIn,
                            user: dict = Depends(require_role("gestor"))):
    """Marca o pagamento como PAGO manualmente (sem passar pelo Asaas).
    Útil para casos onde o pagamento foi feito por fora (ex: transferência
    bancária direta, dinheiro). Não conversa com o banco — apenas atualiza
    o status e cria registro de auditoria.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.scheduled_payments.find_one({"payment_id": payment_id, "company_id": cid})
    if not doc:
        raise HTTPException(404, "Pagamento não encontrado")
    if doc["status"] in ("paid", "cancelled"):
        raise HTTPException(409, f"Pagamento já está com status {doc['status']}")
    paid_at = p.paid_at or now_iso()
    await db.scheduled_payments.update_one(
        {"payment_id": payment_id},
        {"$set": {"status": "paid", "paid_at": paid_at,
                  "paid_manually": True, "paid_by": user.get("email") or "?",
                  "manual_note": p.note, "updated_at": now_iso()}},
    )
    await _audit("paid_manual", payment_id, user.get("email") or "?", cid,
                 {"note": p.note, "paid_at": paid_at})
    await _emit_event("treasury.payment_paid", cid,
                      {"payment_id": payment_id, "method": doc.get("method", "pix"),
                       "manual": True})
    # Auto-envio de comprovante WA se o fornecedor tem flag ativada
    doc_updated = await db.scheduled_payments.find_one({"payment_id": payment_id})
    if doc_updated:
        await _auto_send_receipt_if_enabled(doc_updated)
    return {"ok": True, "status": "paid", "paid_at": paid_at}


@router.get("/kpis-by-month")
async def kpis_by_month(month: Optional[str] = None,
                        month_from: Optional[str] = None,
                        month_to: Optional[str] = None,
                        user: dict = Depends(require_role("gestor"))):
    """KPIs por período. Aceita month=YYYY-MM (mês único) OU month_from+month_to.
    Padrão: mês atual."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if not month and not month_from and not month_to:
        now = datetime.now(timezone.utc)
        month = f"{now.year:04d}-{now.month:02d}"
    gte, lt = _month_bounds(month, month_from, month_to)
    if not gte:
        raise HTTPException(400, "Parâmetro de período inválido. Use month=YYYY-MM ou month_from+month_to.")

    base_q: Dict[str, Any] = {"company_id": cid,
                              "scheduled_for": {"$gte": gte, "$lt": lt}}

    async def _sum(extra: Dict) -> float:
        q = {**base_q, **extra}
        async for r in db.scheduled_payments.aggregate(
            [{"$match": q}, {"$group": {"_id": None, "s": {"$sum": "$amount_brl"}}}]
        ):
            return float(r.get("s") or 0)
        return 0.0

    async def _count(extra: Dict) -> int:
        return await db.scheduled_payments.count_documents({**base_q, **extra})

    paid = await _sum({"status": "paid"})
    pending = await _sum({"status": {"$in": ["draft", "pending_human_approval", "approved"]}})
    overdue_today = datetime.now(timezone.utc).date().isoformat()
    overdue = await _sum({"status": {"$in": ["draft", "pending_human_approval", "approved"]},
                          "scheduled_for": {"$gte": gte, "$lt": min(lt, overdue_today)}})
    return {
        "period": {"gte": gte, "lt": lt, "month": month,
                   "month_from": month_from, "month_to": month_to},
        "month": month,
        "totals": {
            "paid": paid, "pending": pending, "overdue": overdue,
            "blocked": await _sum({"status": "blocked_risk"}),
            "failed": await _sum({"status": "failed"}),
            "cancelled": await _sum({"status": "cancelled"}),
        },
        "counts": {
            "paid": await _count({"status": "paid"}),
            "pending": await _count({"status": {"$in": ["draft", "pending_human_approval", "approved"]}}),
            "sent": await _count({"status": "sent_to_bank"}),
            "total": await _count({}),
        },
    }


@router.get("/kpis-by-filial")
async def kpis_by_filial(month: Optional[str] = None,
                          month_from: Optional[str] = None,
                          month_to: Optional[str] = None,
                          user: dict = Depends(require_role("gestor"))):
    """KPIs de Contas a Pagar agrupados por FILIAL (P0 CEO 2026-02).

    Retorna, por filial e no período pedido:
      - total_paid: somatório efetivamente pago
      - total_pending: agendado/aprovado/aguarda CTO/rascunho
      - total_committed: paid + pending (gasto comprometido com a filial)
      - count_payments: número de pagamentos no período
    Inclui também um bucket especial 'Sem filial' para pagamentos legados
    sem filial_id, e o totalizador geral para o briefing executivo / Custom GPT.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if not month and not month_from and not month_to:
        now = datetime.now(timezone.utc)
        month = f"{now.year:04d}-{now.month:02d}"
    gte, lt = _month_bounds(month, month_from, month_to)
    if not gte:
        raise HTTPException(400, "Período inválido. Use month=YYYY-MM ou month_from+month_to.")

    base_q: Dict[str, Any] = {"company_id": cid,
                              "scheduled_for": {"$gte": gte, "$lt": lt}}
    PENDING_STATUSES = ["draft", "pending_human_approval", "approved", "sent_to_bank"]

    # 1) Mapa de filiais ativas (para nomes consistentes)
    filiais = await db.fin_filiais.find(
        {"company_id": cid}, {"_id": 0, "id": 1, "name": 1, "active": 1}
    ).to_list(500)
    filial_map = {f["id"]: f.get("name") or f["id"] for f in filiais}

    # 2) Agregação por filial × status
    agg = []
    async for r in db.scheduled_payments.aggregate([
        {"$match": base_q},
        {"$group": {
            "_id": {"filial_id": "$filial_id", "status": "$status"},
            "amount": {"$sum": "$amount_brl"},
            "count": {"$sum": 1},
        }},
    ]):
        agg.append(r)

    # Reduce em (filial_id) → buckets
    buckets: Dict[str, Dict[str, Any]] = {}
    for r in agg:
        fid = (r["_id"] or {}).get("filial_id") or "__none__"
        status = (r["_id"] or {}).get("status") or "draft"
        amt = float(r.get("amount") or 0)
        cnt = int(r.get("count") or 0)
        b = buckets.setdefault(fid, {
            "filial_id": fid if fid != "__none__" else None,
            "filial_name": filial_map.get(fid, "Sem filial") if fid != "__none__" else "Sem filial",
            "total_paid": 0.0, "total_pending": 0.0,
            "total_blocked": 0.0, "total_failed": 0.0,
            "total_committed": 0.0, "count_payments": 0,
        })
        b["count_payments"] += cnt
        if status == "paid":
            b["total_paid"] += amt
        elif status in PENDING_STATUSES:
            b["total_pending"] += amt
        elif status == "blocked_risk":
            b["total_blocked"] += amt
        elif status == "failed":
            b["total_failed"] += amt
        b["total_committed"] = b["total_paid"] + b["total_pending"]

    # Inclui filiais ATIVAS sem pagamento (saldo zero) para visibilidade
    for f in filiais:
        if f["id"] not in buckets and f.get("active") is not False:
            buckets[f["id"]] = {
                "filial_id": f["id"], "filial_name": f.get("name") or f["id"],
                "total_paid": 0.0, "total_pending": 0.0,
                "total_blocked": 0.0, "total_failed": 0.0,
                "total_committed": 0.0, "count_payments": 0,
            }

    rows = sorted(buckets.values(),
                  key=lambda x: x["total_committed"], reverse=True)

    totals = {
        "paid": sum(b["total_paid"] for b in rows),
        "pending": sum(b["total_pending"] for b in rows),
        "blocked": sum(b["total_blocked"] for b in rows),
        "failed": sum(b["total_failed"] for b in rows),
        "committed": sum(b["total_committed"] for b in rows),
        "count_payments": sum(b["count_payments"] for b in rows),
    }

    return {
        "_data_provenance": {
            "source": "scheduled_payments",
            "company_id": cid,
            "computed_at": now_iso(),
            "filter": {"scheduled_for_gte": gte, "scheduled_for_lt": lt},
            "filial_field": "filial_id",
            "synthetic_filtered": False,
        },
        "period": {"gte": gte, "lt": lt, "month": month,
                   "month_from": month_from, "month_to": month_to},
        "by_filial": rows,
        "totals": totals,
        "filial_count": len([b for b in rows if b["filial_id"] is not None]),
    }


@router.get("/dre-by-period")
async def dre_by_period(month: Optional[str] = None,
                         month_from: Optional[str] = None,
                         month_to: Optional[str] = None,
                         user: dict = Depends(require_role("gestor"))):
    """DRE/Custos: agrupa pagamentos PAGOS do período por categoria + por
    fornecedor, retornando estrutura pra gráfico de barras (formato DRE)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if not month and not month_from and not month_to:
        now = datetime.now(timezone.utc)
        month = f"{now.year:04d}-{now.month:02d}"
    gte, lt = _month_bounds(month, month_from, month_to)
    if not gte:
        raise HTTPException(400, "Período inválido. Use month=YYYY-MM ou month_from+month_to.")

    base_q: Dict[str, Any] = {"company_id": cid,
                              "scheduled_for": {"$gte": gte, "$lt": lt}}

    # Total pago (custo realizado) e total previsto (compromissado)
    async def _sum(extra: Dict) -> float:
        async for r in db.scheduled_payments.aggregate([
            {"$match": {**base_q, **extra}},
            {"$group": {"_id": None, "s": {"$sum": "$amount_brl"}}},
        ]):
            return float(r.get("s") or 0)
        return 0.0

    total_paid = await _sum({"status": "paid"})
    total_committed = await _sum({"status": {"$in": [
        "approved", "sent_to_bank", "pending_human_approval", "draft", "paid",
    ]}})

    async def _group_by(field: str, limit: int = 12):
        rows: List[Dict[str, Any]] = []
        async for r in db.scheduled_payments.aggregate([
            {"$match": {**base_q, "status": "paid"}},
            {"$group": {
                "_id": {"$ifNull": [f"${field}", "Sem categoria"]},
                "amount": {"$sum": "$amount_brl"},
                "count": {"$sum": 1},
            }},
            {"$sort": {"amount": -1}},
            {"$limit": limit},
        ]):
            rows.append({
                "label": r["_id"] or "Sem categoria",
                "amount": float(r.get("amount") or 0),
                "count": int(r.get("count") or 0),
                "pct": (float(r.get("amount") or 0) / total_paid * 100.0)
                       if total_paid > 0 else 0.0,
            })
        return rows

    return {
        "period": {"gte": gte, "lt": lt, "month": month,
                   "month_from": month_from, "month_to": month_to},
        "total_paid": total_paid,
        "total_committed": total_committed,
        "by_category": await _group_by("category"),
        "by_payee": await _group_by("payee_name"),
        "by_method": await _group_by("method"),
    }


# ════════════════════════════════════════════════════════════════════════════
# ITER239 — Config Card: template de comprovante WhatsApp + anexo PDF/logo
# ════════════════════════════════════════════════════════════════════════════
from services.treasury_receipts import (  # noqa: E402
    DEFAULT_SIGNATURE, DEFAULT_TEMPLATE, get_template, render_template,
)

ALLOWED_RECEIPT_MIMES = {"application/pdf", "image/png", "image/jpeg"}
MAX_RECEIPT_BYTES = 5 * 1024 * 1024  # 5 MB

# Sample payload usado pra preview do template (sem hit no DB de pagamentos)
_SAMPLE_PAYMENT = {
    "payee_name": "ACME Fornecimentos LTDA",
    "payee_document": "12.345.678/0001-90",
    "amount_brl": 1850.0,
    "method": "pix",
    "provider_transfer_id": "tx-exemplo-AB12CD34",
    "description": "NF 12345 — Internet dedicada Fev/2026",
    "category": "Telecom",
}


class ReceiptTemplateIn(BaseModel):
    template_text: Optional[str] = None
    signature: Optional[str] = None
    attach_pdf: Optional[bool] = None


def _strip_pdf(doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not doc:
        return {}
    out = {k: v for k, v in doc.items() if k != "pdf_b64"}
    out["has_pdf"] = bool((doc or {}).get("pdf_b64"))
    return out


@router.get("/config/receipt")
async def get_receipt_config(user: dict = Depends(require_role("gestor"))):
    """Retorna template atual (sem o binário do PDF)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.treasury_receipt_templates.find_one(
        {"company_id": cid}, {"_id": 0})
    if not doc:
        return {
            "company_id": cid,
            "template_text": DEFAULT_TEMPLATE,
            "signature": DEFAULT_SIGNATURE,
            "attach_pdf": False,
            "pdf_filename": None,
            "pdf_mimetype": None,
            "pdf_size_bytes": 0,
            "has_pdf": False,
            "is_default": True,
        }
    return {**_strip_pdf(doc), "is_default": False}


@router.put("/config/receipt")
async def update_receipt_config(p: ReceiptTemplateIn,
                                 user: dict = Depends(require_role("gestor"))):
    """Salva texto/assinatura/flag de anexo. NÃO mexe no PDF armazenado."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    update = {k: v for k, v in p.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(400, "Nenhum campo enviado.")
    update["company_id"] = cid
    update["updated_at"] = now_iso()
    update["updated_by"] = user.get("email") or "?"
    await db.treasury_receipt_templates.update_one(
        {"company_id": cid}, {"$set": update}, upsert=True)
    doc = await db.treasury_receipt_templates.find_one(
        {"company_id": cid}, {"_id": 0})
    return _strip_pdf(doc)


@router.post("/config/receipt/upload")
async def upload_receipt_pdf(file: UploadFile = File(...),
                              user: dict = Depends(require_role("gestor"))):
    """Recebe PDF/PNG/JPG e armazena base64 no template."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    mime = (file.content_type or "").lower()
    if mime not in ALLOWED_RECEIPT_MIMES:
        raise HTTPException(400, f"Tipo inválido: {mime}. Aceito: PDF, PNG, JPG.")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Arquivo vazio.")
    if len(raw) > MAX_RECEIPT_BYTES:
        raise HTTPException(413,
            f"Arquivo {len(raw)//1024}KB excede limite de {MAX_RECEIPT_BYTES//1024}KB.")
    b64 = base64.b64encode(raw).decode("ascii")
    await db.treasury_receipt_templates.update_one(
        {"company_id": cid},
        {"$set": {
            "company_id": cid,
            "pdf_b64": b64,
            "pdf_filename": file.filename or "comprovante.pdf",
            "pdf_mimetype": mime,
            "pdf_size_bytes": len(raw),
            "attach_pdf": True,
            "updated_at": now_iso(),
            "updated_by": user.get("email") or "?",
        }},
        upsert=True,
    )
    return {
        "ok": True,
        "filename": file.filename,
        "mimetype": mime,
        "size_bytes": len(raw),
        "attach_pdf": True,
    }


@router.delete("/config/receipt/pdf")
async def delete_receipt_pdf(user: dict = Depends(require_role("gestor"))):
    """Remove PDF/logo do template e desliga attach_pdf."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    res = await db.treasury_receipt_templates.update_one(
        {"company_id": cid},
        {"$unset": {"pdf_b64": "", "pdf_filename": "",
                    "pdf_mimetype": "", "pdf_size_bytes": ""},
         "$set": {"attach_pdf": False, "updated_at": now_iso(),
                  "updated_by": user.get("email") or "?"}},
    )
    if not res.matched_count:
        raise HTTPException(404, "Nenhum template configurado.")
    return {"ok": True}


@router.get("/config/receipt/preview")
async def preview_receipt_template(user: dict = Depends(require_role("gestor"))):
    """Renderiza o template com um pagamento de exemplo."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    tpl = await get_template(cid)
    sample = {
        **_SAMPLE_PAYMENT,
        "company_id": cid,
        "paid_at": now_iso(),
    }
    return {"text": render_template(sample, tpl),
            "has_pdf": bool(tpl.get("pdf_b64")),
            "pdf_filename": tpl.get("pdf_filename")}

