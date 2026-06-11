"""billing.py — Módulo 1: Billing Engine (CORE) do SmartProv.

Substitui o sync passivo do Atlaz por geração NATIVA de faturas a partir
de assinantes ativos + planos ativos. Mantém compatibilidade com a coleção
`subscriber_invoices` já consumida por:
  - Ligo IA (`consult_subscriber_invoices`, `next_due_invoice`)
  - Relatórios financeiros (Recebimentos, DRE, Aging)
  - Disparos de boleto / cobrança

Diferencia origem por campo `source`:
  - `atlaz_faturas` (legado, mantido até migração completa)
  - `native_billing` (novo, gerado por este módulo)

Régua de cobrança (dunning) configurável por empresa em `billing_dunning_rules`:
  - D-3  → lembrete amigável
  - D+1  → 1ª cobrança (aviso de atraso)
  - D+5  → 2ª cobrança (com juros opcional)
  - D+10 → bloqueio (suspensão preventiva — flag enviada ao RADIUS/Mikrotik)
  - D+30 → notificação final (cancelamento contratual)

Cada evento de régua é registrado em `billing_dunning_events` para auditoria.

Endpoints (todos prefixados com /api/billing):
  - GET  /invoices                 — lista + filtros (status, range datas, sid)
  - GET  /invoices/{id}            — detalhe + dunning_events do invoice
  - POST /invoices                 — criação manual (gestor)
  - POST /invoices/{id}/mark-paid  — marca como paga
  - POST /invoices/{id}/cancel     — cancela
  - DELETE /invoices/{id}          — apaga (admin only)
  - POST /generate-batch           — gera faturas mensais para todos ativos
  - GET  /generate-batch/preview   — preview sem persistir (count, total)
  - GET  /dunning-rules            — lê regras configuradas (com defaults)
  - PUT  /dunning-rules            — atualiza regras
  - POST /dunning-rules/run        — executa régua de cobrança agora (manual)
  - GET  /dunning-events           — lista eventos da régua
  - GET  /stats                    — KPIs (MRR, Open, Paid, Overdue, etc)
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "billing-team",
    "domain": "financeiro",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["invoice.updated"],
    "company_id_required": True,
}

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, get_current_user, is_super_admin, now_iso
from database import db

logger = logging.getLogger("ponto.billing")

router = APIRouter(prefix="/api/billing", tags=["billing"])


# ---------------------------------------------------------------------------
# Constantes & helpers
# ---------------------------------------------------------------------------
INVOICE_STATUSES = ("open", "paid", "overdue", "canceled", "pending")
DEFAULT_DUE_DAY = 10

# Régua de cobrança DEFAULT — usada se a empresa nunca configurou regras.
# offset_days: dias relativos à `due_date` (negativo = antes; positivo = depois).
# action: tipo de ação que o worker dispara (apenas logging por enquanto;
# integração com WhatsApp/SMS é o próximo passo).
DEFAULT_DUNNING_RULES = [
    {"id": "rule-d-3",  "offset_days": -3,
     "label": "Lembrete amigável (D-3)",
     "channel": "whatsapp", "action": "reminder", "enabled": True,
     "template": "Olá {nome}! Sua fatura de {valor} vence em 3 dias ({vencimento}). Pague no prazo e mantenha sua conexão ativa.",
     "apply_fees": False},
    {"id": "rule-d1",  "offset_days": 1,
     "label": "1ª Cobrança (D+1)",
     "channel": "whatsapp", "action": "first_notice", "enabled": True,
     "template": "Olá {nome}, identificamos que sua fatura de {valor} venceu ontem. Regularize hoje para evitar interrupção.",
     "apply_fees": False},
    {"id": "rule-d5",  "offset_days": 5,
     "label": "2ª Cobrança (D+5)",
     "channel": "whatsapp", "action": "second_notice", "enabled": True,
     "template": "Olá {nome}, sua fatura está com 5 dias de atraso. Multa e juros já estão aplicados. Valor atualizado: {valor_atualizado}.",
     "apply_fees": True, "fee_percent": 2.0, "interest_percent_per_month": 1.0},
    {"id": "rule-d10", "offset_days": 10,
     "label": "Bloqueio Preventivo (D+10)",
     "channel": "system", "action": "suspend", "enabled": True,
     "template": "AVISO: Sua conexão foi suspensa por inadimplência. Regularize para reativar.",
     "apply_fees": True, "fee_percent": 2.0, "interest_percent_per_month": 1.0},
    {"id": "rule-d30", "offset_days": 30,
     "label": "Notificação Final (D+30)",
     "channel": "whatsapp", "action": "final_notice", "enabled": True,
     "template": "ÚLTIMO AVISO: Sua fatura está com 30 dias de atraso. Sem regularização imediata, o contrato será encerrado.",
     "apply_fees": True, "fee_percent": 2.0, "interest_percent_per_month": 1.0},
]


def _require_manager(user: dict) -> None:
    """Gestão de Billing: gestor, administrador, financeiro, auditor, super_admin."""
    if user.get("role") in ("gestor", "administrador", "auditor", "financeiro"):
        return
    if is_super_admin(user):
        return
    raise HTTPException(403, "Apenas gestor/administrador/financeiro/auditor.")


def _today() -> date:
    return datetime.utcnow().date()


async def _resolve_primary_phone(company_id: str,
                                   subscriber_id: str) -> Optional[str]:
    """Resolve o telefone primário do assinante.

    Ordem de busca:
    1) `subscriber_phones` collection (fonte canônica desde a migração) —
       prioriza `is_primary=True`, depois o mais antigo.
    2) Embedded `subscriber.phones[]` (legado / cadastros novos pelo form).

    Retorna `normalized_number` (5521…) ou `raw_number` ou `phone` se primeiro vazio.
    """
    # Primário explícito
    doc = await db.subscriber_phones.find_one(
        {"company_id": company_id, "subscriber_id": subscriber_id,
         "is_primary": True},
        {"_id": 0, "normalized_number": 1, "raw_number": 1, "phone": 1},
        sort=[("created_at", 1)],
    )
    if not doc:
        # Qualquer telefone (mais antigo primeiro)
        doc = await db.subscriber_phones.find_one(
            {"company_id": company_id, "subscriber_id": subscriber_id},
            {"_id": 0, "normalized_number": 1, "raw_number": 1, "phone": 1},
            sort=[("created_at", 1)],
        )
    if doc:
        return doc.get("normalized_number") or doc.get("raw_number") or doc.get("phone")
    # Fallback embedded
    sub = await db.subscribers.find_one(
        {"company_id": company_id, "id": subscriber_id},
        {"_id": 0, "phones": 1},
    )
    if sub and sub.get("phones"):
        first = sub["phones"][0] or {}
        return first.get("number") or first.get("raw_number") or first.get("phone")
    return None


def _parse_date(s: Optional[str]) -> Optional[date]:
    """Aceita 'YYYY-MM-DD' ou ISO completo. Retorna None se inválido."""
    if not s:
        return None
    try:
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def _compute_due_date(competence_year: int, competence_month: int,
                      due_day: int) -> str:
    """Calcula vencimento dado competência (YYYY-MM) + due_day do assinante.

    Ajusta automaticamente para o último dia válido do mês se due_day > dias_mes.
    Ex: due_day=31 em fev → cai pro dia 28/29 do mesmo mês.
    """
    # Próximo mês competente: se due_day já passou na referência, gera pro mês
    # seguinte. Aqui assumimos que a fatura é gerada no mês de competência.
    y, m = competence_year, competence_month
    # Última data válida do mês
    if m == 12:
        next_month_first = date(y + 1, 1, 1)
    else:
        next_month_first = date(y, m + 1, 1)
    last_day = (next_month_first - timedelta(days=1)).day
    effective_day = min(due_day, last_day)
    return date(y, m, effective_day).isoformat()


def _compute_overdue_amount(invoice: Dict[str, Any], today: date,
                             fee_percent: float = 2.0,
                             interest_percent_per_month: float = 1.0) -> float:
    """Calcula valor atualizado com multa + juros pro-rata por dia.

    Fórmula padrão BR (multa 2% + juros 1%/mês = 0.0333%/dia).
    """
    amount = float(invoice.get("amount") or 0)
    due = _parse_date(invoice.get("due_date"))
    if not due or today <= due or amount <= 0:
        return amount
    days_late = (today - due).days
    fee = amount * (fee_percent / 100.0)
    daily_rate = (interest_percent_per_month / 100.0) / 30.0
    interest = amount * daily_rate * days_late
    return round(amount + fee + interest, 2)


def _normalize_invoice(inv: Dict[str, Any]) -> Dict[str, Any]:
    """Limpa _id e adiciona campos derivados (overdue, days_late, etc)."""
    inv.pop("_id", None)
    today = _today()
    due = _parse_date(inv.get("due_date"))
    paid = inv.get("paid_date") or inv.get("paid_at")
    status = inv.get("status") or "open"
    # Derivação de overdue: se status=open e due já passou → overdue
    if status == "open" and due and today > due and not paid:
        inv["status"] = "overdue"
        status = "overdue"
    inv["days_late"] = (today - due).days if (due and today > due and status != "paid") else 0
    inv["amount_with_fees"] = (
        _compute_overdue_amount(inv, today) if status == "overdue"
        else float(inv.get("amount") or 0)
    )
    inv.setdefault("source", "native_billing")
    inv.setdefault("currency", "BRL")
    return inv


# ---------------------------------------------------------------------------
# Pydantic
# ---------------------------------------------------------------------------
class InvoiceIn(BaseModel):
    subscriber_id: str
    competence: str = Field(..., description="YYYY-MM (ex: 2026-02)")
    amount: float = Field(..., ge=0)
    due_date: Optional[str] = None  # YYYY-MM-DD. Default = competence + due_day
    description: Optional[str] = None


class GenerateBatchIn(BaseModel):
    competence: str = Field(..., description="YYYY-MM (ex: 2026-02)")
    dry_run: bool = Field(default=False, description="Se True não persiste, apenas retorna preview.")


class MarkPaidIn(BaseModel):
    paid_amount: Optional[float] = None
    paid_date: Optional[str] = None
    payment_method: Optional[str] = None  # boleto/pix/cartao/dinheiro/transferencia
    notes: Optional[str] = None


class DunningRulesIn(BaseModel):
    rules: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Endpoints — Invoices CRUD
# ---------------------------------------------------------------------------
@router.get("/invoices")
async def list_invoices(
    status: Optional[str] = None,
    subscriber_id: Optional[str] = None,
    competence: Optional[str] = None,
    due_from: Optional[str] = None,
    due_to: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 200,
    skip: int = 0,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Lista faturas da empresa do usuário com filtros opcionais."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if status:
        if status not in INVOICE_STATUSES:
            raise HTTPException(400, f"Status inválido: {status}")
        q["status"] = status
    if subscriber_id:
        q["subscriber_id"] = subscriber_id
    if competence:
        q["competence"] = competence
    if source:
        q["source"] = source
    if due_from or due_to:
        q["due_date"] = {}
        if due_from:
            q["due_date"]["$gte"] = due_from
        if due_to:
            q["due_date"]["$lte"] = due_to
    total = await db.subscriber_invoices.count_documents(q)
    cursor = db.subscriber_invoices.find(q, {"_id": 0}).sort(
        [("due_date", -1), ("created_at", -1)],
    ).skip(max(0, skip)).limit(min(1000, max(1, limit)))
    items = [_normalize_invoice(d) async for d in cursor]
    return {"items": items, "total": total, "limit": limit, "skip": skip}


@router.get("/invoices/{inv_id}")
async def get_invoice(inv_id: str, user: dict = Depends(get_current_user)):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    inv = await db.subscriber_invoices.find_one({"company_id": cid, "id": inv_id}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Fatura não encontrada.")
    # Dunning events do invoice
    events_cur = db.billing_dunning_events.find(
        {"company_id": cid, "invoice_id": inv_id}, {"_id": 0},
    ).sort("ts", -1).limit(100)
    events = [e async for e in events_cur]
    return {"invoice": _normalize_invoice(inv), "dunning_events": events}


@router.post("/invoices", status_code=201)
async def create_invoice(payload: InvoiceIn,
                          user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    sub = await db.subscribers.find_one(
        {"company_id": cid, "id": payload.subscriber_id}, {"_id": 0},
    )
    if not sub:
        raise HTTPException(404, "Assinante não encontrado.")
    # Calcula due_date se não enviado
    due_date = payload.due_date
    if not due_date:
        try:
            cy, cm = payload.competence.split("-")
            due_day = int(sub.get("due_day") or DEFAULT_DUE_DAY)
            due_date = _compute_due_date(int(cy), int(cm), due_day)
        except (ValueError, TypeError):
            raise HTTPException(400, "Competence inválida (use YYYY-MM).")
    inv = {
        "id": f"binv-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "subscriber_id": sub.get("id"),
        "subscriber_external_id": sub.get("external_code"),
        "subscriber_name": sub.get("name"),
        "subscriber_document": sub.get("document"),
        "subscriber_phone": await _resolve_primary_phone(cid, sub.get("id")),
        "competence": payload.competence,
        "amount": float(payload.amount),
        "amount_paid": 0,
        "due_date": due_date,
        "issue_date": now_iso()[:10],
        "status": "open",
        "description": payload.description or f"Mensalidade {sub.get('plan_name') or sub.get('plan_speed') or ''}".strip(),
        "plan_id": sub.get("plan_id"),
        "plan_name": sub.get("plan_name"),
        "source": "native_billing",
        "currency": "BRL",
        "created_at": now_iso(),
        "created_by": user.get("email"),
    }
    await db.subscriber_invoices.insert_one(dict(inv))
    try:
        from services.event_bus import emit_event
        await emit_event(
            "invoice.created",
            company_id=(sub or {}).get("company_id"),
            source="billing",
            payload={},
        )
    except Exception:
        pass
    # Sprint 19 — emit overdue se já passou da data
    try:
        from services.event_emitters import emit_business
        from datetime import datetime
        is_overdue = (due_date and due_date < datetime.utcnow()
                       .strftime("%Y-%m-%d"))
        if is_overdue:
            await emit_business(
                kind="payment.overdue", actor=user,
                payload={"invoice_id": inv["id"],
                           "subscriber_id": sub.get("id"),
                           "amount": float(payload.amount),
                           "due_date": due_date},
                severity="media", source="billing.create_invoice")
    except Exception:
        pass
    return _normalize_invoice(inv)


@router.post("/invoices/{inv_id}/mark-paid")
async def mark_paid(inv_id: str, payload: MarkPaidIn,
                     user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    inv = await db.subscriber_invoices.find_one(
        {"company_id": cid, "id": inv_id}, {"_id": 0},
    )
    if not inv:
        raise HTTPException(404, "Fatura não encontrada.")
    if inv.get("status") == "paid":
        return _normalize_invoice(inv)
    paid_amount = payload.paid_amount if payload.paid_amount is not None else float(inv.get("amount") or 0)
    paid_date = payload.paid_date or now_iso()[:10]
    upd = {
        "status": "paid",
        "amount_paid": float(paid_amount),
        "paid_date": paid_date,
        "paid_at": now_iso(),
        "paid_by": user.get("email"),
        "payment_method": payload.payment_method,
        "payment_notes": payload.notes,
    }
    await db.subscriber_invoices.update_one(
        {"company_id": cid, "id": inv_id}, {"$set": upd},
    )
    try:
        from services.event_bus import emit_event
        await emit_event(
            "invoice.updated",
            company_id=cid,
            source="billing",
            payload={},
        )
    except Exception:
        pass
    updated = await db.subscriber_invoices.find_one(
        {"company_id": cid, "id": inv_id}, {"_id": 0},
    )
    # Sprint 19 — emit payment.received
    try:
        from services.event_emitters import emit_business
        await emit_business(
            kind="payment.received", actor=user,
            payload={"invoice_id": inv_id,
                       "subscriber_id": inv.get("subscriber_id"),
                       "amount": float(paid_amount)},
            severity="baixa", source="billing.mark_paid")
    except Exception:
        pass
    return _normalize_invoice(updated)


@router.post("/invoices/{inv_id}/cancel")
async def cancel_invoice(inv_id: str, user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    res = await db.subscriber_invoices.update_one(
        {"company_id": cid, "id": inv_id, "status": {"$ne": "paid"}},
        {"$set": {"status": "canceled", "canceled_at": now_iso(),
                  "canceled_by": user.get("email")}},
    )
    try:
        from services.event_bus import emit_event
        await emit_event(
            "invoice.updated",
            company_id=cid,
            source="billing",
            payload={},
        )
    except Exception:
        pass
    if res.matched_count == 0:
        raise HTTPException(404, "Fatura não encontrada ou já paga.")
    inv = await db.subscriber_invoices.find_one(
        {"company_id": cid, "id": inv_id}, {"_id": 0},
    )
    return _normalize_invoice(inv)


@router.delete("/invoices/{inv_id}")
async def delete_invoice(inv_id: str, user: dict = Depends(get_current_user)):
    if not is_super_admin(user) and user.get("role") != "administrador":
        raise HTTPException(403, "Apenas administrador/super_admin.")
    cid = user.get("company_id") or DEMO_COMPANY_ID
    r = await db.subscriber_invoices.delete_one({"company_id": cid, "id": inv_id})
    if r.deleted_count == 0:
        raise HTTPException(404, "Fatura não encontrada.")
    return {"deleted": True, "id": inv_id}


# ---------------------------------------------------------------------------
# Geração em lote
# ---------------------------------------------------------------------------
@router.post("/generate-batch")
async def generate_batch(payload: GenerateBatchIn,
                          user: dict = Depends(get_current_user)):
    """Gera faturas mensais para todos os assinantes ATIVOS da empresa.

    Idempotente: assinante que já tem fatura nativa para essa competência é
    pulado. Ignora assinantes sem `plan_id` (plano cancelado/sem preço).
    """
    _require_manager(user)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    try:
        cy, cm = payload.competence.split("-")
        cy_int, cm_int = int(cy), int(cm)
        if not (1 <= cm_int <= 12):
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(400, "Competence inválida (use YYYY-MM).")
    # Carrega ativos com plano vinculado
    cursor = db.subscribers.find(
        {"company_id": cid, "status": "ATIVO", "plan_id": {"$exists": True, "$ne": None}},
        {"_id": 0, "id": 1, "name": 1, "external_code": 1, "document": 1,
         "due_day": 1, "plan_id": 1, "plan_name": 1, "plan_price": 1, "phones": 1},
    )
    subs = await cursor.to_list(20000)
    if not subs:
        return {"competence": payload.competence, "subscribers_evaluated": 0,
                "invoices_created": 0, "skipped_existing": 0,
                "skipped_no_price": 0, "total_amount": 0, "dry_run": payload.dry_run}
    # Bulk-load primary phones de TODOS os subscribers de uma vez (1 query,
    # muito mais rápido que 1 lookup por subscriber em loop de 20k items).
    sub_ids = [s.get("id") for s in subs if s.get("id")]
    phones_map: Dict[str, str] = {}
    if sub_ids:
        # 1ª passada: primary phones
        async for ph in db.subscriber_phones.find(
            {"company_id": cid, "subscriber_id": {"$in": sub_ids},
             "is_primary": True},
            {"_id": 0, "subscriber_id": 1, "normalized_number": 1, "raw_number": 1},
        ):
            sid_ph = ph.get("subscriber_id")
            if sid_ph and sid_ph not in phones_map:
                phones_map[sid_ph] = ph.get("normalized_number") or ph.get("raw_number")
        # 2ª passada: assinantes sem primary, qualquer telefone
        missing = [sid for sid in sub_ids if sid not in phones_map]
        if missing:
            async for ph in db.subscriber_phones.find(
                {"company_id": cid, "subscriber_id": {"$in": missing}},
                {"_id": 0, "subscriber_id": 1, "normalized_number": 1, "raw_number": 1},
                sort=[("created_at", 1)],
            ):
                sid_ph = ph.get("subscriber_id")
                if sid_ph and sid_ph not in phones_map:
                    phones_map[sid_ph] = ph.get("normalized_number") or ph.get("raw_number")
    # Faturas já existentes nesta competência (qualquer source)
    existing = set()
    async for row in db.subscriber_invoices.find(
        {"company_id": cid, "competence": payload.competence},
        {"_id": 0, "subscriber_id": 1},
    ):
        sid = row.get("subscriber_id")
        if sid:
            existing.add(sid)
    created = 0
    skipped_existing = 0
    skipped_no_price = 0
    total_amount = 0.0
    bulk_docs: List[Dict[str, Any]] = []
    now_str = now_iso()
    for sub in subs:
        sid = sub.get("id")
        if not sid:
            continue
        if sid in existing:
            skipped_existing += 1
            continue
        price = sub.get("plan_price")
        if not price or float(price) <= 0:
            skipped_no_price += 1
            continue
        due_day = int(sub.get("due_day") or DEFAULT_DUE_DAY)
        try:
            due_date = _compute_due_date(cy_int, cm_int, due_day)
        except (ValueError, TypeError):
            skipped_no_price += 1
            continue
        amount = float(price)
        # Resolve phone via map; se nao existir, tenta fallback embedded
        phone = phones_map.get(sid)
        if not phone and sub.get("phones"):
            phone = (sub["phones"][0] or {}).get("number")
        bulk_docs.append({
            "id": f"binv-{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "subscriber_id": sid,
            "subscriber_external_id": sub.get("external_code"),
            "subscriber_name": sub.get("name"),
            "subscriber_document": sub.get("document"),
            "subscriber_phone": phone,
            "competence": payload.competence,
            "amount": amount,
            "amount_paid": 0,
            "due_date": due_date,
            "issue_date": now_str[:10],
            "status": "open",
            "description": f"Mensalidade {sub.get('plan_name') or ''} — {payload.competence}".strip(),
            "plan_id": sub.get("plan_id"),
            "plan_name": sub.get("plan_name"),
            "source": "native_billing",
            "currency": "BRL",
            "created_at": now_str,
            "created_by": user.get("email"),
            "batch_id": f"batch-{payload.competence}-{uuid.uuid4().hex[:6]}",
        })
        total_amount += amount
        created += 1
    if not payload.dry_run and bulk_docs:
        # Faz em chunks de 1000 pra não estourar BSON
        for i in range(0, len(bulk_docs), 1000):
            chunk = bulk_docs[i:i + 1000]
            await db.subscriber_invoices.insert_many(chunk, ordered=False)
        # Log de auditoria
        await db.billing_runs.insert_one({
            "id": f"brun-{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "type": "generate_batch",
            "competence": payload.competence,
            "subscribers_evaluated": len(subs),
            "invoices_created": created,
            "skipped_existing": skipped_existing,
            "skipped_no_price": skipped_no_price,
            "total_amount": round(total_amount, 2),
            "actor": user.get("email"),
            "ts": now_str,
        })
    return {
        "competence": payload.competence,
        "subscribers_evaluated": len(subs),
        "invoices_created": created,
        "skipped_existing": skipped_existing,
        "skipped_no_price": skipped_no_price,
        "total_amount": round(total_amount, 2),
        "dry_run": payload.dry_run,
    }


@router.get("/generate-batch/preview")
async def generate_batch_preview(competence: str,
                                  user: dict = Depends(get_current_user)):
    """Equivale ao POST com dry_run=True via querystring (UX)."""
    _require_manager(user)
    return await generate_batch(GenerateBatchIn(competence=competence, dry_run=True), user)


# ---------------------------------------------------------------------------
# Dunning rules CRUD
# ---------------------------------------------------------------------------
@router.get("/dunning-rules")
async def get_dunning_rules(user: dict = Depends(get_current_user)):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.billing_dunning_rules.find_one(
        {"company_id": cid}, {"_id": 0},
    )
    if not doc:
        return {"company_id": cid, "rules": DEFAULT_DUNNING_RULES,
                "using_defaults": True}
    return {"company_id": cid, "rules": doc.get("rules") or DEFAULT_DUNNING_RULES,
            "using_defaults": False,
            "updated_at": doc.get("updated_at"),
            "updated_by": doc.get("updated_by")}


@router.put("/dunning-rules")
async def update_dunning_rules(payload: DunningRulesIn,
                                user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # Validação leve dos campos obrigatórios em cada regra
    for r in payload.rules:
        if not isinstance(r, dict):
            raise HTTPException(400, "Cada regra deve ser um objeto.")
        if "offset_days" not in r:
            raise HTTPException(400, f"Regra sem offset_days: {r}")
    await db.billing_dunning_rules.update_one(
        {"company_id": cid},
        {"$set": {"rules": payload.rules, "updated_at": now_iso(),
                  "updated_by": user.get("email")}},
        upsert=True,
    )
    return {"ok": True, "rules": payload.rules}


# ---------------------------------------------------------------------------
# Dunning engine
# ---------------------------------------------------------------------------
async def _evaluate_dunning_for_company(cid: str,
                                          actor_email: Optional[str] = None,
                                          dry_run: bool = False) -> Dict[str, Any]:
    """Executa régua de cobrança em todas as faturas open/overdue da empresa.

    Retorna stats agregados. Eventos não-dry-run são persistidos em
    `billing_dunning_events`. NÃO envia mensagens reais ainda — apenas
    registra os eventos. A integração com WhatsApp será habilitada por uma
    flag no próximo iter.
    """
    rules_doc = await db.billing_dunning_rules.find_one(
        {"company_id": cid}, {"_id": 0},
    )
    rules = (rules_doc or {}).get("rules") or DEFAULT_DUNNING_RULES
    rules = [r for r in rules if r.get("enabled", True)]
    if not rules:
        return {"company_id": cid, "rules_active": 0, "invoices_evaluated": 0,
                "events_triggered": 0, "by_action": {}}
    today = _today()
    # Considera todas as faturas open/overdue (não pagas, não canceladas)
    cur = db.subscriber_invoices.find(
        {"company_id": cid,
         "status": {"$in": ["open", "overdue", "pending"]}},
        {"_id": 0},
    )
    invoices = await cur.to_list(20000)
    events: List[Dict[str, Any]] = []
    by_action: Dict[str, int] = {}
    suspended_subs: List[str] = []
    for inv in invoices:
        due = _parse_date(inv.get("due_date"))
        if not due:
            continue
        days_diff = (today - due).days  # positivo = atrasado
        for rule in rules:
            offset = int(rule.get("offset_days") or 0)
            if days_diff != offset:
                continue
            # Dedup: já existe evento desse rule pra esse invoice?
            existing = await db.billing_dunning_events.find_one({
                "company_id": cid, "invoice_id": inv.get("id"),
                "rule_id": rule.get("id"),
            }, {"_id": 0, "id": 1})
            if existing:
                continue
            action = rule.get("action") or "notify"
            updated_amount = _compute_overdue_amount(
                inv, today,
                fee_percent=float(rule.get("fee_percent") or 0),
                interest_percent_per_month=float(rule.get("interest_percent_per_month") or 0),
            ) if rule.get("apply_fees") else float(inv.get("amount") or 0)
            ev = {
                "id": f"dunev-{uuid.uuid4().hex[:10]}",
                "company_id": cid,
                "invoice_id": inv.get("id"),
                "subscriber_id": inv.get("subscriber_id"),
                "subscriber_name": inv.get("subscriber_name"),
                "subscriber_phone": inv.get("subscriber_phone"),
                "rule_id": rule.get("id"),
                "rule_label": rule.get("label"),
                "action": action,
                "channel": rule.get("channel"),
                "amount_original": float(inv.get("amount") or 0),
                "amount_updated": updated_amount,
                "due_date": inv.get("due_date"),
                "days_late": days_diff,
                "template_rendered": _render_template(
                    rule.get("template") or "", inv, updated_amount),
                "sent": False,  # próximo iter: WhatsApp send marca True
                "ts": now_iso(),
                "actor": actor_email,
            }
            events.append(ev)
            by_action[action] = by_action.get(action, 0) + 1
            if action == "suspend":
                suspended_subs.append(inv.get("subscriber_id"))
    if not dry_run and events:
        await db.billing_dunning_events.insert_many(events, ordered=False)
        # Action 'suspend' marca financial_status do subscriber
        if suspended_subs:
            await db.subscribers.update_many(
                {"company_id": cid, "id": {"$in": [s for s in suspended_subs if s]}},
                {"$set": {"financial_status": "INADIMPLENTE",
                          "suspended_at": now_iso(),
                          "suspended_reason": "billing_dunning_d10"}},
            )
            try:
                from services.event_bus import emit_event
                await emit_event(
                    "subscriber.bulk_updated",
                    company_id=(existing or {}).get("company_id"),
                    source="billing",
                    payload={},
                )
            except Exception:
                pass
        # Status de invoice → overdue (se ainda open)
        for inv in invoices:
            due = _parse_date(inv.get("due_date"))
            if due and today > due and inv.get("status") == "open":
                await db.subscriber_invoices.update_one(
                    {"company_id": cid, "id": inv.get("id"), "status": "open"},
                    {"$set": {"status": "overdue"}},
                )
    return {
        "company_id": cid,
        "rules_active": len(rules),
        "invoices_evaluated": len(invoices),
        "events_triggered": len(events),
        "by_action": by_action,
        "dry_run": dry_run,
    }


def _render_template(template: str, inv: Dict[str, Any],
                      amount_updated: float) -> str:
    """Renderiza placeholders {nome}, {valor}, {valor_atualizado}, {vencimento}."""
    if not template:
        return ""
    amount = float(inv.get("amount") or 0)
    return (template
            .replace("{nome}", str(inv.get("subscriber_name") or "Cliente"))
            .replace("{valor}", f"R$ {amount:.2f}".replace(".", ","))
            .replace("{valor_atualizado}", f"R$ {amount_updated:.2f}".replace(".", ","))
            .replace("{vencimento}", str(inv.get("due_date") or "—"))
            .replace("{competencia}", str(inv.get("competence") or "—")))


@router.post("/dunning-rules/run")
async def run_dunning_now(dry_run: bool = False,
                          user: dict = Depends(get_current_user)):
    _require_manager(user)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _evaluate_dunning_for_company(cid, user.get("email"), dry_run)


@router.get("/dunning-events")
async def list_dunning_events(
    invoice_id: Optional[str] = None,
    subscriber_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 200,
    user: dict = Depends(get_current_user),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if invoice_id:
        q["invoice_id"] = invoice_id
    if subscriber_id:
        q["subscriber_id"] = subscriber_id
    if action:
        q["action"] = action
    cur = db.billing_dunning_events.find(q, {"_id": 0}).sort("ts", -1).limit(min(2000, max(1, limit)))
    items = [e async for e in cur]
    return {"items": items, "count": len(items)}


# ---------------------------------------------------------------------------
# Stats — KPIs do dashboard de Faturamento
# ---------------------------------------------------------------------------
@router.get("/stats")
async def billing_stats(
    competence: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """Retorna KPIs agregados de faturamento da empresa.

    Filtra por competência se informada; caso contrário considera tudo.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    base_q: Dict[str, Any] = {"company_id": cid}
    if competence:
        base_q["competence"] = competence
    pipeline = [
        {"$match": base_q},
        {"$group": {
            "_id": "$status",
            "count": {"$sum": 1},
            "total_amount": {"$sum": {"$ifNull": ["$amount", 0]}},
            "total_paid": {"$sum": {"$ifNull": ["$amount_paid", 0]}},
        }},
    ]
    by_status: Dict[str, Dict[str, Any]] = {}
    total_count = 0
    total_open_amount = 0.0
    total_paid_amount = 0.0
    total_invoiced = 0.0
    async for row in db.subscriber_invoices.aggregate(pipeline):
        st = row["_id"] or "unknown"
        by_status[st] = {
            "count": row["count"],
            "total_amount": round(row.get("total_amount") or 0, 2),
            "total_paid": round(row.get("total_paid") or 0, 2),
        }
        total_count += row["count"]
        total_invoiced += row.get("total_amount") or 0
        if st == "paid":
            total_paid_amount += row.get("total_paid") or 0
        elif st in ("open", "overdue", "pending"):
            total_open_amount += row.get("total_amount") or 0
    # MRR: soma de monthly_price dos assinantes ativos
    mrr_pipeline = [
        {"$match": {"company_id": cid, "status": "ATIVO",
                    "plan_price": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": None, "mrr": {"$sum": "$plan_price"},
                    "active_count": {"$sum": 1}}},
    ]
    mrr = 0.0
    active_count = 0
    async for row in db.subscribers.aggregate(mrr_pipeline):
        mrr = row.get("mrr") or 0
        active_count = row.get("active_count") or 0
    # Default counts pros 5 status canônicos pra UI nunca ficar undefined
    for st in INVOICE_STATUSES:
        by_status.setdefault(st, {"count": 0, "total_amount": 0, "total_paid": 0})
    return {
        "company_id": cid,
        "competence": competence,
        "by_status": by_status,
        "total_count": total_count,
        "total_invoiced": round(total_invoiced, 2),
        "total_paid_amount": round(total_paid_amount, 2),
        "total_open_amount": round(total_open_amount, 2),
        "collection_rate": round((total_paid_amount / total_invoiced * 100) if total_invoiced > 0 else 0, 2),
        "mrr": round(mrr, 2),
        "active_subscribers": active_count,
    }


@router.get("/runs")
async def list_billing_runs(limit: int = 50,
                              user: dict = Depends(get_current_user)):
    """Histórico de execuções (generate-batch e dunning-runs)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cur = db.billing_runs.find({"company_id": cid}, {"_id": 0}).sort("ts", -1).limit(min(500, max(1, limit)))
    return {"items": [r async for r in cur]}


@router.post("/invoices/backfill-phones")
async def backfill_phones(user: dict = Depends(get_current_user)):
    """Preenche `subscriber_phone` em faturas que estão sem.

    Útil pra faturas legadas vindas do sync Atlaz que ficaram sem telefone
    (~3% dos cadastros), e pra faturas geradas antes da correção do
    resolver (iter138 hotfix). Roda em batches, idempotente.
    """
    _require_manager(user)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # Faturas com phone vazio
    cur = db.subscriber_invoices.find(
        {"company_id": cid,
         "$or": [{"subscriber_phone": None}, {"subscriber_phone": ""}]},
        {"_id": 0, "id": 1, "subscriber_id": 1, "subscriber_external_id": 1},
    )
    invoices_to_fix = await cur.to_list(50000)
    if not invoices_to_fix:
        return {"checked": 0, "updated": 0, "skipped_no_subscriber": 0}
    # Bulk-load phones from subscriber_phones (priorizando is_primary)
    sub_ids = list({i.get("subscriber_id") for i in invoices_to_fix if i.get("subscriber_id")})
    phones_map: Dict[str, str] = {}
    if sub_ids:
        async for ph in db.subscriber_phones.find(
            {"company_id": cid, "subscriber_id": {"$in": sub_ids}},
            {"_id": 0, "subscriber_id": 1, "is_primary": 1,
             "normalized_number": 1, "raw_number": 1},
            sort=[("is_primary", -1), ("created_at", 1)],
        ):
            sid_ph = ph.get("subscriber_id")
            if sid_ph and sid_ph not in phones_map:
                phones_map[sid_ph] = ph.get("normalized_number") or ph.get("raw_number")
    # Fallback: atlaz_clients_cache via external_id (cobre o caso de subscribers
    # importados que ainda nao foram migrados pra subscriber_phones)
    ext_ids = list({i.get("subscriber_external_id")
                    for i in invoices_to_fix
                    if i.get("subscriber_external_id")
                    and i.get("subscriber_id") not in phones_map})
    if ext_ids:
        async for c in db.atlaz_clients_cache.find(
            {"company_id": cid, "external_id": {"$in": [str(e) for e in ext_ids]},
             "phone": {"$nin": [None, ""]}},
            {"_id": 0, "external_id": 1, "phone": 1, "mobile": 1},
        ):
            # Marca via external_id (será mapeado abaixo)
            phones_map[f"ext:{c.get('external_id')}"] = c.get("phone") or c.get("mobile")
    # Aplica updates
    from pymongo import UpdateOne
    ops = []
    updated = 0
    skipped = 0
    for inv in invoices_to_fix:
        sid = inv.get("subscriber_id")
        ext = inv.get("subscriber_external_id")
        phone = phones_map.get(sid) or (phones_map.get(f"ext:{ext}") if ext else None)
        if not phone:
            skipped += 1
            continue
        ops.append(UpdateOne(
            {"company_id": cid, "id": inv.get("id")},
            {"$set": {"subscriber_phone": phone}},
        ))
        updated += 1
    if ops:
        # Chunks de 1000
        for i in range(0, len(ops), 1000):
            await db.subscriber_invoices.bulk_write(ops[i:i + 1000], ordered=False)
    return {"checked": len(invoices_to_fix), "updated": updated,
            "skipped_no_subscriber": skipped,
            "subscribers_with_phone": len([k for k in phones_map if not k.startswith("ext:")]),
            "atlaz_cache_phones": len([k for k in phones_map if k.startswith("ext:")])}
