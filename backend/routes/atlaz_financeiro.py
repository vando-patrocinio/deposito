"""Integração financeira com a API Atlaz V2 (Fase 4).

ESCOPO: puxa COBRANÇAS / FATURAS / RECEBIMENTOS dos assinantes (clientes).
NÃO confunde com `fin_bills_payable` que são DESPESAS da empresa.

ENDPOINTS DA API ATLAZ V2 (a confirmar com o painel docs):
  • GET /listacobrancas   — faturas geradas
  • GET /listaboletos     — boletos emitidos
  • GET /listapagamentos  — pagamentos recebidos
  • GET /listaclientes    — clientes/assinantes

Como a documentação oficial não está disponível publicamente, a estratégia é:
  1. Endpoint GET /api/atlaz-financeiro/probe — testa quais endpoints respondem
  2. Endpoint POST /api/atlaz-financeiro/sync-now — pull com fallback gracioso
  3. Coleção local `subscriber_invoices` armazena resultados normalizados

Quando o token Atlaz tiver acesso aos endpoints financeiros, a sincronização
acontece automaticamente. Caso contrário, o endpoint /probe relata 404/403.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db
from routes.atlaz import ATLAZ_BASE_URL, _get_config

logger = logging.getLogger("ponto.atlaz_financeiro")
router = APIRouter(prefix="/api/atlaz-financeiro", tags=["atlaz-financeiro"])


# Endpoints candidatos a testar — em ordem de prioridade
PROBE_ENDPOINTS = [
    "listacobrancas",
    "listaboletos",
    "listapagamentos",
    "listaclientes",
    "listaservicos",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _http_get(endpoint: str, params: Dict[str, Any], timeout: int = 20) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.get(f"{ATLAZ_BASE_URL}/{endpoint}", params=params)


def _norm_invoice(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza um documento Atlaz para schema interno subscriber_invoices.

    Como o shape exato dos endpoints é desconhecido até receber resposta real,
    fazemos uma normalização tolerante: tentamos vários nomes de campos
    comuns e usamos None como fallback.
    """
    pick = lambda *keys: next((raw.get(k) for k in keys if raw.get(k) is not None), None)  # noqa: E731
    return {
        "external_id": str(pick("id", "id_cobranca", "id_fatura", "id_boleto") or ""),
        "subscriber_external_id": str(pick("id_cliente", "id_assinante", "cliente_id") or ""),
        "subscriber_name": pick("cliente_nome", "nome_cliente", "nome"),
        "subscriber_document": pick("cpf", "cnpj", "documento"),
        "amount": float(pick("valor", "valor_cobranca", "valor_fatura") or 0),
        "amount_paid": float(pick("valor_pago", "valor_recebido") or 0),
        "due_date": pick("data_vencimento", "vencimento", "data_venc"),
        "issue_date": pick("data_emissao", "data_geracao", "emissao"),
        "paid_date": pick("data_pagamento", "data_baixa", "data_recebimento"),
        "status": pick("status", "situacao", "estado") or "unknown",
        "barcode": pick("codigo_barras", "linha_digitavel"),
        "raw": {k: raw.get(k) for k in raw.keys() if not k.startswith("_")},
    }


# ===========================================================================
# Endpoints
# ===========================================================================
@router.get("/probe")
async def probe(user: dict = Depends(require_role("administrador"))):
    """Testa quais endpoints financeiros do Atlaz V2 respondem com o token atual.

    Retorna lista com status HTTP, payload sample e se é utilizável.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(cid)
    if not cfg.api_key:
        raise HTTPException(400, "Token Atlaz não configurado")

    results: List[Dict[str, Any]] = []
    base_params = {"token": cfg.api_key}
    for ep in PROBE_ENDPOINTS:
        try:
            r = await _http_get(ep, base_params, timeout=cfg.timeout_seconds)
            sample: Any = None
            ok = False
            try:
                data = r.json()
                ok = (r.status_code == 200) and (
                    data.get("success") == "true" or isinstance(data, list)
                )
                # Pega 1 item como sample
                if isinstance(data, dict):
                    for k in ("cobrancas", "boletos", "pagamentos",
                              "clientes", "data", "results"):
                        v = data.get(k)
                        if isinstance(v, list) and v:
                            sample = v[0]
                            break
                elif isinstance(data, list) and data:
                    sample = data[0]
            except Exception:
                pass
            results.append({
                "endpoint": ep,
                "http_status": r.status_code,
                "available": ok,
                "sample_keys": (list(sample.keys()) if isinstance(sample, dict)
                                else None),
                "error": (r.text[:200] if r.status_code >= 400 else None),
            })
        except Exception as e:
            results.append({
                "endpoint": ep, "http_status": 0,
                "available": False, "error": str(e)[:200],
            })
    return {"probed_at": now_iso(), "endpoints": results}


@router.post("/sync-now")
async def sync_now(user: dict = Depends(require_role("administrador"))):
    """Pull manual de cobranças/faturas/pagamentos do Atlaz para `subscriber_invoices`.

    Estratégia tolerante: tenta cada endpoint, salva o que conseguiu.
    Quando nenhum endpoint estiver disponível, retorna 200 com counter zero.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(cid)
    if not cfg.api_key:
        raise HTTPException(400, "Token Atlaz não configurado")

    base_params = {"token": cfg.api_key}
    inserted = 0
    updated = 0
    errors: List[str] = []
    endpoints_ok: List[str] = []

    for ep in ("listacobrancas", "listaboletos", "listapagamentos"):
        try:
            r = await _http_get(ep, base_params, timeout=cfg.timeout_seconds)
            if r.status_code >= 400:
                errors.append(f"{ep}: HTTP {r.status_code}")
                continue
            data = r.json()
            items: List[Dict[str, Any]] = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                for k in ("cobrancas", "boletos", "pagamentos", "data", "results"):
                    v = data.get(k)
                    if isinstance(v, list):
                        items = v
                        break
            if not items:
                continue
            endpoints_ok.append(ep)
            for raw in items:
                norm = _norm_invoice(raw)
                if not norm["external_id"]:
                    continue
                norm["company_id"] = cid
                norm["source"] = ep
                norm["synced_at"] = now_iso()
                existing = await db.subscriber_invoices.find_one(
                    {"company_id": cid, "external_id": norm["external_id"]},
                    {"_id": 0, "id": 1},
                )
                if existing:
                    await db.subscriber_invoices.update_one(
                        {"id": existing["id"]}, {"$set": norm},
                    )
                    updated += 1
                else:
                    norm["id"] = f"sinv-{uuid.uuid4().hex[:10]}"
                    norm["created_at"] = now_iso()
                    await db.subscriber_invoices.insert_one(norm)
                    inserted += 1
        except Exception as e:
            errors.append(f"{ep}: {type(e).__name__} {e}")

    await db.atlaz_sync_logs.insert_one({
        "id": f"asf-{uuid.uuid4().hex[:10]}",
        "company_id": cid, "event": "atlaz_financeiro_sync",
        "status": "ok" if endpoints_ok else "skipped",
        "details": f"endpoints={endpoints_ok}; inserted={inserted}; updated={updated}",
        "errors": errors[:5],
        "at": now_iso(),
    })
    return {
        "endpoints_ok": endpoints_ok,
        "inserted": inserted, "updated": updated,
        "errors": errors,
    }


@router.get("/invoices")
async def list_invoices(
    status: Optional[str] = None,
    subscriber_document: Optional[str] = None,
    limit: int = 200,
    user: dict = Depends(require_role("administrador", "financeiro")),
):
    """Lista faturas/cobranças sincronizadas dos assinantes."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if status:
        q["status"] = status
    if subscriber_document:
        q["subscriber_document"] = subscriber_document
    cur = db.subscriber_invoices.find(q, {"_id": 0}).sort(
        [("due_date", -1)],
    ).limit(min(limit, 1000))
    items = [doc async for doc in cur]
    total = await db.subscriber_invoices.count_documents(q)
    return {"items": items, "total": total}


@router.get("/stats")
async def stats(user: dict = Depends(require_role("administrador", "financeiro"))):
    """Resumo: total recebido, em aberto, vencido."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    pipeline = [
        {"$match": {"company_id": cid}},
        {"$group": {
            "_id": "$status",
            "count": {"$sum": 1},
            "amount": {"$sum": "$amount"},
        }},
    ]
    by_status: Dict[str, Dict[str, float]] = {}
    async for row in db.subscriber_invoices.aggregate(pipeline):
        by_status[str(row["_id"])] = {
            "count": row["count"], "amount": round(row["amount"], 2),
        }
    total = await db.subscriber_invoices.count_documents({"company_id": cid})
    last_sync = await db.atlaz_sync_logs.find_one(
        {"company_id": cid, "event": "atlaz_financeiro_sync"},
        {"_id": 0}, sort=[("at", -1)],
    )
    return {
        "total_invoices": total,
        "by_status": by_status,
        "last_sync": last_sync.get("at") if last_sync else None,
        "last_sync_status": last_sync.get("status") if last_sync else None,
    }
