"""Módulo Financeiro — Cadastros base (Fase 2).

CRUDs:
  • categorias       → fin_categories
  • fornecedores     → fin_suppliers
  • métodos cobrança → fin_payment_methods
  • caixas/contas    → fin_cash_accounts

Acesso restrito a: super_admin (administrador) e financeiro.
Próximas fases adicionam: contas a pagar, lançamentos, fluxo de caixa, DRE.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "billing-team",
    "domain": "financeiro",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.financeiro")
router = APIRouter(prefix="/api/financeiro", tags=["financeiro"])


# ---------------------------------------------------------------------------
# RBAC helper — financeiro OU administrador OU auditor
# ---------------------------------------------------------------------------
def require_finance():
    """Permite super_admin e role 'financeiro'."""
    return require_role("administrador", "financeiro", "auditor")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class CategoryIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    kind: str = Field("expense", pattern="^(expense|income|both)$")
    color: Optional[str] = None
    parent_id: Optional[str] = None
    active: bool = True


class SupplierIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    document: Optional[str] = None  # CPF/CNPJ
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    active: bool = True
    # CTO 2026-02: filiação por filial. CEO regra — "gastos são feitos
    # dentro das filiais". Aceita 1 default + lista de filiais permitidas.
    default_filial_id: Optional[str] = None
    allowed_filiais: Optional[List[str]] = None
    # Campos opcionais do modal CONTAS A PAGAR
    category: Optional[str] = None
    pix_type: Optional[str] = Field(
        None, pattern="^(CPF|CNPJ|EMAIL|TELEFONE|ALEATORIA|CHAVE)?$")
    pix_key: Optional[str] = None
    whatsapp_phone: Optional[str] = None
    send_receipt_via_wa: bool = False
    address_cep: Optional[str] = None
    address_state: Optional[str] = None
    address_street: Optional[str] = None
    address_number: Optional[str] = None
    address_complement: Optional[str] = None
    address_neighborhood: Optional[str] = None
    address_city: Optional[str] = None
    default_cash_account_id: Optional[str] = None


class PaymentMethodIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    kind: str = Field("pix", pattern="^(pix|boleto|card|cash|transfer|other)$")
    fee_percent: float = Field(0.0, ge=0, le=100)
    settle_days: int = Field(0, ge=0, le=90)
    active: bool = True


class CashAccountIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    kind: str = Field("bank", pattern="^(bank|cash|wallet|other)$")
    bank_name: Optional[str] = None
    agency: Optional[str] = None
    account_number: Optional[str] = None
    opening_balance: float = 0.0
    current_balance: float = 0.0
    active: bool = True


class FilialIn(BaseModel):
    """Filial (unidade/branch). Conceito global do sistema — colaboradores,
    clientes, contas e tickets podem ser vinculados a uma filial. Phase 1
    cobre o cadastro mínimo (apenas nome + ativo) e linkagem com contas
    do Financeiro. Phase 2 estende para colaboradores/clientes/lousa.

    `default_collaborator_id`: técnico padrão da filial. Quando o gestor
    seleciona a filial em qualquer fluxo (Nova conta, Lousa, etc), o sistema
    pré-preenche o técnico responsável usando este mapeamento. Pura
    associação — sem inferência IA.
    """
    name: str = Field(..., min_length=1, max_length=120)
    active: bool = True
    default_collaborator_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Generic CRUD helpers
# ---------------------------------------------------------------------------
def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


async def _list(collection: str, company_id: str,
                only_active: bool = False) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"company_id": company_id}
    if only_active:
        q["active"] = True
    cur = db[collection].find(q, {"_id": 0}).sort("name", 1)
    return [doc async for doc in cur]


async def _create(collection: str, company_id: str, prefix: str,
                  payload: Dict[str, Any]) -> Dict[str, Any]:
    doc = {**payload, "id": _new_id(prefix), "company_id": company_id,
           "created_at": now_iso(), "updated_at": now_iso()}
    await db[collection].insert_one(doc)
    # remover _id (mongo o adicionou após insert)
    doc.pop("_id", None)
    return doc


async def _update(collection: str, company_id: str, doc_id: str,
                  payload: Dict[str, Any]) -> Dict[str, Any]:
    update = {k: v for k, v in payload.items() if v is not None}
    update["updated_at"] = now_iso()
    r = await db[collection].update_one(
        {"id": doc_id, "company_id": company_id}, {"$set": update},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Registro não encontrado")
    doc = await db[collection].find_one({"id": doc_id, "company_id": company_id},
                                         {"_id": 0})
    return doc or {}


async def _delete(collection: str, company_id: str, doc_id: str) -> Dict[str, Any]:
    r = await db[collection].delete_one({"id": doc_id, "company_id": company_id})
    if r.deleted_count == 0:
        raise HTTPException(404, "Registro não encontrado")
    return {"ok": True}


# ===========================================================================
# CATEGORIA FINANCEIRA
# ===========================================================================
@router.get("/categories")
async def list_categories(only_active: bool = False,
                          user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _list("fin_categories", cid, only_active)


@router.post("/categories")
async def create_category(payload: CategoryIn,
                          user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _create("fin_categories", cid, "fcat", payload.model_dump())


@router.put("/categories/{doc_id}")
async def update_category(doc_id: str, payload: CategoryIn,
                          user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _update("fin_categories", cid, doc_id, payload.model_dump())


@router.delete("/categories/{doc_id}")
async def delete_category(doc_id: str,
                          user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _delete("fin_categories", cid, doc_id)


# ===========================================================================
# FORNECEDOR
# ===========================================================================
@router.get("/suppliers")
async def list_suppliers(only_active: bool = False,
                         user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _list("fin_suppliers", cid, only_active)


@router.post("/suppliers")
async def create_supplier(payload: SupplierIn,
                          user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _create("fin_suppliers", cid, "fsup", payload.model_dump())


@router.put("/suppliers/{doc_id}")
async def update_supplier(doc_id: str, payload: SupplierIn,
                          user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _update("fin_suppliers", cid, doc_id, payload.model_dump())


@router.delete("/suppliers/{doc_id}")
async def delete_supplier(doc_id: str,
                          user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _delete("fin_suppliers", cid, doc_id)


# ===========================================================================
# MÉTODO DE COBRANÇA
# ===========================================================================
@router.get("/payment-methods")
async def list_payment_methods(only_active: bool = False,
                               user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _list("fin_payment_methods", cid, only_active)


@router.post("/payment-methods")
async def create_payment_method(payload: PaymentMethodIn,
                                user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _create("fin_payment_methods", cid, "fpm", payload.model_dump())


@router.put("/payment-methods/{doc_id}")
async def update_payment_method(doc_id: str, payload: PaymentMethodIn,
                                user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _update("fin_payment_methods", cid, doc_id, payload.model_dump())


@router.delete("/payment-methods/{doc_id}")
async def delete_payment_method(doc_id: str,
                                user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _delete("fin_payment_methods", cid, doc_id)


# ===========================================================================
# CAIXA / CONTA BANCÁRIA
# ===========================================================================
@router.get("/cash-accounts")
async def list_cash_accounts(only_active: bool = False,
                             user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _list("fin_cash_accounts", cid, only_active)


@router.post("/cash-accounts")
async def create_cash_account(payload: CashAccountIn,
                              user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    data = payload.model_dump()
    # current_balance inicia igual ao opening_balance se vier 0
    if data.get("current_balance") == 0 and data.get("opening_balance"):
        data["current_balance"] = data["opening_balance"]
    return await _create("fin_cash_accounts", cid, "fca", data)


@router.put("/cash-accounts/{doc_id}")
async def update_cash_account(doc_id: str, payload: CashAccountIn,
                              user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _update("fin_cash_accounts", cid, doc_id, payload.model_dump())


@router.delete("/cash-accounts/{doc_id}")
async def delete_cash_account(doc_id: str,
                              user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _delete("fin_cash_accounts", cid, doc_id)


# ===========================================================================
# FILIAL (unidade/branch)
# ===========================================================================
@router.get("/filiais")
async def list_filiais(only_active: bool = False,
                       user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _list("fin_filiais", cid, only_active)


@router.post("/filiais")
async def create_filial(payload: FilialIn,
                        user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await _create("fin_filiais", cid, "fil", payload.model_dump())
    await _push_to_atlaz_config(cid, doc)
    return doc


@router.put("/filiais/{doc_id}")
async def update_filial(doc_id: str, payload: FilialIn,
                        user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await _update("fin_filiais", cid, doc_id, payload.model_dump())
    await _push_to_atlaz_config(cid, doc)
    return doc


@router.delete("/filiais/{doc_id}")
async def delete_filial(doc_id: str,
                        user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # Limpa filial_id das contas vinculadas pra não deixar referência órfã
    await db.fin_bills_payable.update_many(
        {"company_id": cid, "filial_id": doc_id},
        {"$unset": {"filial_id": ""}},
    )
    return await _delete("fin_filiais", cid, doc_id)


async def _push_to_atlaz_config(company_id: str, filial_doc: Dict[str, Any]) -> None:
    """Sincroniza Filial → Atlaz config (bidirecional).

    Quando o gestor cria/edita uma filial aqui no Financeiro com técnico padrão,
    grava de volta no `db.atlaz_config.{filiais, filial_to_collaborator}` para
    manter as 2 telas (Configurações → Atlaz e Financeiro → Filial) coerentes.

    Não falha o request se o atlaz_config não existir — apenas faz log.
    """
    if not filial_doc or not filial_doc.get("name"):
        return
    name = filial_doc["name"]
    default_col = filial_doc.get("default_collaborator_id")
    try:
        cfg = await db.atlaz_config.find_one(
            {"company_id": company_id},
            {"_id": 0, "filiais": 1, "filial_to_collaborator": 1},
        )
        if not cfg:
            # Não existe config Atlaz pra esse tenant ainda — não cria sozinho
            logger.info("atlaz_config not found for company %s, skipping push",
                        company_id)
            return
        filiais: List[str] = list(cfg.get("filiais") or [])
        mapping: Dict[str, str] = dict(cfg.get("filial_to_collaborator") or {})
        # Lookup case-insensitive para não duplicar
        existing_keys = {f.lower(): f for f in filiais}
        canonical_name = existing_keys.get(name.lower(), name)
        if canonical_name not in filiais:
            filiais.append(canonical_name)
        # Atualiza mapping. Remove chaves duplicadas case-insensitive.
        clean_mapping = {k: v for k, v in mapping.items()
                          if k.lower() != name.lower()}
        if default_col:
            clean_mapping[canonical_name] = default_col
        await db.atlaz_config.update_one(
            {"company_id": company_id},
            {"$set": {"filiais": filiais,
                       "filial_to_collaborator": clean_mapping}},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("push_to_atlaz_config failed for %s/%s: %s",
                        company_id, name, e)


@router.post("/filiais/sync-from-atlaz")
async def sync_filiais_from_atlaz(user: dict = Depends(require_finance())):
    """Sincroniza Filiais do mapeamento Atlaz (Configurações → Atlaz →
    Mapeamento Filial → Técnico padrão) para a coleção `fin_filiais`.

    - Idempotente: filiais com mesmo `name` (case-insensitive) NÃO são duplicadas
    - Cria as ausentes e atualiza o `default_collaborator_id` com base no
      `filial_to_collaborator` salvo no Atlaz
    - Não remove filiais locais que não existem mais no Atlaz (proteção)
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # Lê config Atlaz (mesma coleção usada por /api/atlaz/settings)
    atlaz_cfg = await db.atlaz_config.find_one(
        {"company_id": cid}, {"_id": 0, "filiais": 1, "filial_to_collaborator": 1},
    )
    if not atlaz_cfg:
        return {"created": 0, "updated": 0, "skipped": 0,
                "message": "Configuração Atlaz não encontrada. "
                            "Configure em Sistema → Configurações → Atlaz."}
    atlaz_filiais: List[str] = [f.strip() for f in (atlaz_cfg.get("filiais") or [])
                                  if f and f.strip()]
    mapping: Dict[str, str] = atlaz_cfg.get("filial_to_collaborator") or {}

    # Lê filiais financeiras existentes (case-insensitive lookup)
    existing: Dict[str, Dict[str, Any]] = {}
    async for row in db.fin_filiais.find({"company_id": cid}, {"_id": 0}):
        existing[(row.get("name") or "").strip().lower()] = row

    now = datetime.now(timezone.utc)
    created = updated = skipped = 0
    for name in atlaz_filiais:
        key = name.lower()
        # Resolução case-insensitive do colaborador padrão.
        # No Atlaz, mapping pode estar em qualquer caixa.
        default_col = None
        for k, v in mapping.items():
            if (k or "").strip().lower() == key:
                default_col = v
                break
        cur = existing.get(key)
        if cur:
            # Atualiza apenas se houver mudança no default
            if (cur.get("default_collaborator_id") or None) != (default_col or None):
                await db.fin_filiais.update_one(
                    {"company_id": cid, "id": cur["id"]},
                    {"$set": {"default_collaborator_id": default_col,
                              "updated_at": now}},
                )
                updated += 1
            else:
                skipped += 1
        else:
            doc = {
                "id": f"fil-{uuid.uuid4().hex[:10]}",
                "company_id": cid,
                "name": name,
                "active": True,
                "default_collaborator_id": default_col,
                "created_at": now,
                "updated_at": now,
            }
            await db.fin_filiais.insert_one(doc)
            created += 1

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "total_atlaz_filiais": len(atlaz_filiais),
        "mapping_entries": len(mapping),
    }





# ===========================================================================
# RESUMO (dashboard rápido para a aba inicial do Financeiro)
# ===========================================================================
@router.get("/summary")
async def summary(user: dict = Depends(require_finance())):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cats = await db.fin_categories.count_documents({"company_id": cid})
    sups = await db.fin_suppliers.count_documents({"company_id": cid})
    pms = await db.fin_payment_methods.count_documents({"company_id": cid})
    cas_docs = [doc async for doc in db.fin_cash_accounts.find(
        {"company_id": cid, "active": True}, {"_id": 0, "current_balance": 1},
    )]
    total_balance = sum(float(d.get("current_balance") or 0) for d in cas_docs)
    return {
        "categories": cats,
        "suppliers": sups,
        "payment_methods": pms,
        "cash_accounts": len(cas_docs),
        "total_balance": round(total_balance, 2),
    }
