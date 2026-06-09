"""Módulo Financeiro — Fase 3: Contas a Pagar + Lançamentos (Fluxo de Caixa).

Coleções:
  • fin_bills_payable   — contas a pagar (despesas)
  • fin_cash_movements  — lançamentos do caixa (entrada/saída)

Comportamento:
  • Ao "marcar como paga" uma conta, cria automaticamente um cash_movement
    de saída e atualiza o saldo da conta caixa selecionada.
  • Job diário (auto-marker) marca como 'overdue' contas vencidas e não pagas.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso
from database import db
from routes.financeiro import require_finance

logger = logging.getLogger("ponto.financeiro_ops")
router = APIRouter(prefix="/api/financeiro", tags=["financeiro"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class BillIn(BaseModel):
    description: str = Field(..., min_length=1, max_length=300)
    amount: float = Field(..., gt=0)
    due_date: str  # YYYY-MM-DD
    supplier_id: Optional[str] = None
    category_id: Optional[str] = None
    payment_method_id: Optional[str] = None
    cash_account_id: Optional[str] = None
    filial_id: Optional[str] = None  # Phase 1: linkagem com filial
    notes: Optional[str] = None
    document_number: Optional[str] = None
    # Parcelamento — se installments_count > 1, cria N parcelas a partir de
    # due_date com intervalo de `installments_period_days` dias (default 30).
    # O valor `amount` é considerado o TOTAL e será dividido em N parcelas.
    installments_count: Optional[int] = Field(default=None, ge=1, le=120)
    installments_period_days: Optional[int] = Field(default=30, ge=1, le=365)
    # Se True, cada parcela recebe o valor `amount` (recorrência), em vez
    # de dividir o total. Ex.: aluguel mensal de R$ 1500 por 12 meses.
    installments_recurrent: bool = Field(default=False)


class BillUpdate(BaseModel):
    description: Optional[str] = None
    amount: Optional[float] = Field(None, gt=0)
    due_date: Optional[str] = None
    supplier_id: Optional[str] = None
    category_id: Optional[str] = None
    payment_method_id: Optional[str] = None
    cash_account_id: Optional[str] = None
    filial_id: Optional[str] = None
    notes: Optional[str] = None
    document_number: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(pending|paid|overdue|cancelled)$")


class PayBillPayload(BaseModel):
    cash_account_id: str
    payment_method_id: Optional[str] = None
    paid_amount: Optional[float] = None  # default = amount
    paid_at: Optional[str] = None  # default = now (ISO)
    notes: Optional[str] = None


class MovementIn(BaseModel):
    type: str = Field(..., pattern="^(income|expense)$")
    date: str  # YYYY-MM-DD
    amount: float = Field(..., gt=0)
    cash_account_id: str
    description: str = Field(..., min_length=1, max_length=300)
    category_id: Optional[str] = None
    supplier_id: Optional[str] = None
    payment_method_id: Optional[str] = None
    reference_id: Optional[str] = None
    reference_type: Optional[str] = None  # 'bill' | 'invoice' | 'manual'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def _update_balance(cid: str, cash_account_id: str, delta: float) -> None:
    """Atualiza current_balance da conta-caixa em delta (+ ou -)."""
    await db.fin_cash_accounts.update_one(
        {"id": cash_account_id, "company_id": cid},
        {"$inc": {"current_balance": delta}, "$set": {"updated_at": now_iso()}},
    )


# ===========================================================================
# CONTAS A PAGAR — CRUD
# ===========================================================================
@router.get("/bills")
async def list_bills(
    status: Optional[str] = Query(None),
    supplier_id: Optional[str] = Query(None),
    filial_id: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    user: dict = Depends(require_finance()),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if status:
        q["status"] = status
    if supplier_id:
        q["supplier_id"] = supplier_id
    if filial_id:
        # "__none__" filtra contas sem filial atribuída (caso "Sem filial")
        if filial_id == "__none__":
            q["$or"] = [{"filial_id": None}, {"filial_id": {"$exists": False}}]
        else:
            q["filial_id"] = filial_id
    if from_date or to_date:
        q["due_date"] = {}
        if from_date:
            q["due_date"]["$gte"] = from_date
        if to_date:
            q["due_date"]["$lte"] = to_date
    cur = db.fin_bills_payable.find(q, {"_id": 0}).sort([("due_date", 1)])
    return [doc async for doc in cur]


@router.post("/bills")
async def create_bill(payload: BillIn,
                      user: dict = Depends(require_finance())):
    """Cria 1 ou N contas a pagar.

    Se `installments_count > 1`, cria N parcelas a partir de `due_date` com
    intervalo de `installments_period_days` dias. Cada parcela é uma conta
    independente em `fin_bills_payable`, agrupadas por `installment_group_id`
    pra facilitar relatórios/desfazer.

    Modos:
      - `installments_recurrent=False` (padrão): valor total é dividido em N
        (ex.: R$ 1000 em 5x = 5 × R$ 200)
      - `installments_recurrent=True`: cada parcela tem o `amount` cheio
        (ex.: aluguel de R$ 1500 por 12 meses = 12 × R$ 1500)
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    data = payload.model_dump()
    n = int(data.pop("installments_count") or 1)
    period_days = int(data.pop("installments_period_days") or 30)
    recurrent = bool(data.pop("installments_recurrent"))

    total = float(data["amount"])
    base_date = datetime.strptime(data["due_date"], "%Y-%m-%d").date()

    group_id: Optional[str] = (f"installments-{uuid.uuid4().hex[:10]}"
                                  if n > 1 else None)

    docs: List[Dict[str, Any]] = []
    parcel_value = total if recurrent else round(total / n, 2)
    # Ajuste pra última parcela absorver o residual de centavos
    residual = round(total - parcel_value * n, 2) if not recurrent else 0.0

    for i in range(n):
        due = base_date + timedelta(days=period_days * i)
        due_iso = due.isoformat()
        amount_i = parcel_value
        if not recurrent and i == n - 1 and abs(residual) > 0.005:
            amount_i = round(parcel_value + residual, 2)

        status_ = "overdue" if due_iso < _today_str() else "pending"

        descr = data["description"]
        if n > 1:
            descr = f"{descr} ({i + 1}/{n})"

        doc = {
            **data,
            "id": f"bill-{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "description": descr,
            "amount": amount_i,
            "due_date": due_iso,
            "status": status_,
            "paid_at": None, "paid_amount": None,
            "installment_group_id": group_id,
            "installment_index": (i + 1) if n > 1 else None,
            "installment_total": n if n > 1 else None,
            "installment_recurrent": recurrent if n > 1 else None,
            "created_at": now_iso(), "updated_at": now_iso(),
        }
        docs.append(doc)

    if len(docs) == 1:
        await db.fin_bills_payable.insert_one(docs[0])
    else:
        await db.fin_bills_payable.insert_many(docs)

    for d in docs:
        d.pop("_id", None)
    if len(docs) == 1:
        return docs[0]
    return {
        "ok": True,
        "installment_group_id": group_id,
        "count": n,
        "total_amount": round(parcel_value * n + (residual if not recurrent else 0), 2)
                       if not recurrent else parcel_value * n,
        "bills": docs,
    }


@router.put("/bills/{bill_id}")
async def update_bill(bill_id: str, payload: BillUpdate,
                      user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(400, "Nada para atualizar")
    update["updated_at"] = now_iso()
    r = await db.fin_bills_payable.update_one(
        {"id": bill_id, "company_id": cid}, {"$set": update},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Conta não encontrada")
    return await db.fin_bills_payable.find_one(
        {"id": bill_id, "company_id": cid}, {"_id": 0},
    )


@router.delete("/bills/{bill_id}")
async def delete_bill(
    bill_id: str,
    delete_future_installments: bool = Query(False,
        description="Se True, apaga também todas as parcelas futuras "
                    "(ainda não pagas) do mesmo grupo de parcelamento."),
    user: dict = Depends(require_finance()),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    bill = await db.fin_bills_payable.find_one(
        {"id": bill_id, "company_id": cid}, {"_id": 0},
    )
    if not bill:
        raise HTTPException(404, "Conta não encontrada")
    # Se paga, reverte movimentação (estorna saldo)
    if bill.get("status") == "paid" and bill.get("cash_account_id") and bill.get("paid_amount"):
        await _update_balance(cid, bill["cash_account_id"], float(bill["paid_amount"]))
        await db.fin_cash_movements.delete_many({
            "company_id": cid, "reference_type": "bill", "reference_id": bill_id,
        })
    await db.fin_bills_payable.delete_one({"id": bill_id, "company_id": cid})

    extras_deleted = 0
    if delete_future_installments and bill.get("installment_group_id"):
        # Apaga TODAS as parcelas do mesmo grupo que AINDA não foram pagas
        # (status != 'paid'). Parcelas pagas são preservadas para não bagunçar
        # o histórico financeiro.
        future_q = {
            "company_id": cid,
            "installment_group_id": bill["installment_group_id"],
            "status": {"$ne": "paid"},
        }
        r = await db.fin_bills_payable.delete_many(future_q)
        extras_deleted = r.deleted_count

    return {
        "ok": True,
        "deleted_bill_id": bill_id,
        "future_installments_deleted": extras_deleted,
        "had_installment_group": bool(bill.get("installment_group_id")),
    }


@router.post("/bills/{bill_id}/pay")
async def pay_bill(bill_id: str, payload: PayBillPayload,
                   user: dict = Depends(require_finance())):
    """Marca uma conta como paga e cria movimentação de saída."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    bill = await db.fin_bills_payable.find_one(
        {"id": bill_id, "company_id": cid}, {"_id": 0},
    )
    if not bill:
        raise HTTPException(404, "Conta não encontrada")
    if bill.get("status") == "paid":
        raise HTTPException(400, "Conta já está paga")

    # Verifica conta caixa
    cash_acc = await db.fin_cash_accounts.find_one(
        {"id": payload.cash_account_id, "company_id": cid}, {"_id": 0},
    )
    if not cash_acc:
        raise HTTPException(400, "Conta caixa inválida")

    paid_amount = payload.paid_amount or bill["amount"]
    paid_at = payload.paid_at or now_iso()
    paid_date = paid_at[:10]

    # Cria movimentação de saída
    mov = {
        "id": f"mov-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "type": "expense",
        "date": paid_date,
        "amount": float(paid_amount),
        "cash_account_id": payload.cash_account_id,
        "category_id": bill.get("category_id"),
        "supplier_id": bill.get("supplier_id"),
        "payment_method_id": payload.payment_method_id or bill.get("payment_method_id"),
        "description": f"Pagto: {bill['description']}",
        "reference_id": bill_id,
        "reference_type": "bill",
        "created_at": now_iso(),
    }
    await db.fin_cash_movements.insert_one(mov)
    # Atualiza saldo da conta caixa (subtrai)
    await _update_balance(cid, payload.cash_account_id, -float(paid_amount))
    # Atualiza bill
    await db.fin_bills_payable.update_one(
        {"id": bill_id, "company_id": cid},
        {"$set": {
            "status": "paid",
            "paid_at": paid_at,
            "paid_amount": float(paid_amount),
            "cash_account_id": payload.cash_account_id,
            "payment_method_id": payload.payment_method_id or bill.get("payment_method_id"),
            "updated_at": now_iso(),
        }},
    )
    mov.pop("_id", None)
    # Sprint 19 — emit event (pagamento recebido/efetuado)
    try:
        from services.event_emitters import emit_business
        await emit_business(
            kind="payment.received", actor=user,
            payload={"bill_id": bill_id,
                       "subscriber_id": bill.get("supplier_id"),
                       "amount": float(paid_amount)},
            severity="baixa", source="financeiro_ops.pay_bill")
    except Exception:
        pass
    return {"ok": True, "movement": mov}


# ===========================================================================
# CASH MOVEMENTS (Fluxo de Caixa) — CRUD
# ===========================================================================
@router.get("/movements")
async def list_movements(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    cash_account_id: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    user: dict = Depends(require_finance()),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if type:
        q["type"] = type
    if cash_account_id:
        q["cash_account_id"] = cash_account_id
    if from_date or to_date:
        q["date"] = {}
        if from_date:
            q["date"]["$gte"] = from_date
        if to_date:
            q["date"]["$lte"] = to_date
    cur = db.fin_cash_movements.find(q, {"_id": 0}).sort([("date", -1), ("created_at", -1)]).limit(limit)
    return [doc async for doc in cur]


@router.post("/movements")
async def create_movement(payload: MovementIn,
                          user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cash_acc = await db.fin_cash_accounts.find_one(
        {"id": payload.cash_account_id, "company_id": cid}, {"_id": 0},
    )
    if not cash_acc:
        raise HTTPException(400, "Conta caixa inválida")
    data = payload.model_dump()
    data.setdefault("reference_type", "manual")
    doc = {
        **data, "id": f"mov-{uuid.uuid4().hex[:10]}",
        "company_id": cid, "created_at": now_iso(),
    }
    await db.fin_cash_movements.insert_one(doc)
    # Atualiza saldo
    delta = float(payload.amount) if payload.type == "income" else -float(payload.amount)
    await _update_balance(cid, payload.cash_account_id, delta)
    doc.pop("_id", None)
    return doc


@router.delete("/movements/{mov_id}")
async def delete_movement(mov_id: str,
                          user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    mov = await db.fin_cash_movements.find_one(
        {"id": mov_id, "company_id": cid}, {"_id": 0},
    )
    if not mov:
        raise HTTPException(404, "Lançamento não encontrado")
    if mov.get("reference_type") == "bill":
        raise HTTPException(400, "Não excluir lançamento de pagamento. Estorne pela conta a pagar.")
    # Reverte saldo
    if mov.get("cash_account_id") and mov.get("amount"):
        delta = -float(mov["amount"]) if mov["type"] == "income" else float(mov["amount"])
        await _update_balance(cid, mov["cash_account_id"], delta)
    await db.fin_cash_movements.delete_one({"id": mov_id, "company_id": cid})
    return {"ok": True}


# ===========================================================================
# FLUXO DE CAIXA — Agregado para gráfico
# ===========================================================================
@router.get("/cashflow")
async def cashflow_summary(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    group_by: str = Query("day", pattern="^(day|month)$"),
    user: dict = Depends(require_finance()),
):
    """Agrega entradas/saídas por dia (ou mês). Default: últimos 30d."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if not to_date:
        to_date = _today_str()
    if not from_date:
        # 30 dias atrás
        from datetime import timedelta
        start = datetime.now(timezone.utc) - timedelta(days=30)
        from_date = start.strftime("%Y-%m-%d")

    q: Dict[str, Any] = {"company_id": cid, "date": {"$gte": from_date, "$lte": to_date}}
    cur = db.fin_cash_movements.find(q, {"_id": 0, "date": 1, "type": 1, "amount": 1})
    buckets: Dict[str, Dict[str, float]] = {}
    totals = {"income": 0.0, "expense": 0.0}
    async for m in cur:
        key = m["date"][:7] if group_by == "month" else m["date"]
        b = buckets.setdefault(key, {"income": 0.0, "expense": 0.0})
        amt = float(m.get("amount") or 0)
        b[m["type"]] = b.get(m["type"], 0.0) + amt
        totals[m["type"]] += amt
    # Lista ordenada
    series = []
    for k in sorted(buckets.keys()):
        b = buckets[k]
        series.append({
            "date": k,
            "income": round(b["income"], 2),
            "expense": round(b["expense"], 2),
            "net": round(b["income"] - b["expense"], 2),
        })
    # Saldo total atual (todas contas ativas)
    cash_accs = [doc async for doc in db.fin_cash_accounts.find(
        {"company_id": cid, "active": True}, {"_id": 0, "current_balance": 1},
    )]
    current_balance = sum(float(a.get("current_balance") or 0) for a in cash_accs)
    return {
        "series": series,
        "totals": {
            "income": round(totals["income"], 2),
            "expense": round(totals["expense"], 2),
            "net": round(totals["income"] - totals["expense"], 2),
        },
        "current_balance": round(current_balance, 2),
        "group_by": group_by,
        "from_date": from_date,
        "to_date": to_date,
    }


# ===========================================================================
# Job interno (chamado pelo scheduler central) — marca contas vencidas
# ===========================================================================
async def auto_mark_overdue() -> Dict[str, Any]:
    today = _today_str()
    r = await db.fin_bills_payable.update_many(
        {"status": "pending", "due_date": {"$lt": today}},
        {"$set": {"status": "overdue", "updated_at": now_iso()}},
    )
    return {"updated": r.modified_count}
