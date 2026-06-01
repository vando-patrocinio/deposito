"""Integração financeira com a API Atlaz V2 (Fase 4).

ESCOPO: puxa FATURAS dos assinantes (clientes).
NÃO confunde com `fin_bills_payable` que são DESPESAS da empresa.

ENDPOINTS DA API ATLAZ V2 (descobertos via /probe):
  • GET /faturas         — exige data_vencimento_inicial OU data_vencimento_final
                            OU id_assinante. Retorna {success, cnt_faturas, faturas:[...]}
                            Schema da fatura: {id, id_assinante, valor, data_vencimento,
                                                data_pagamento, linha_digitavel, link, descricao,
                                                desconto_pontualidade, multa, juros, ...}
  • GET /listaclientes   — retorna {success, total_de_paginas, assinantes: [...]}

Estratégia: pull /faturas com janela móvel + bulk_write (1k+ docs eficiente).
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from pymongo import UpdateOne

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db
from routes.atlaz import ATLAZ_BASE_URL, _get_config

logger = logging.getLogger("ponto.atlaz_financeiro")
router = APIRouter(prefix="/api/atlaz-financeiro", tags=["atlaz-financeiro"])


# Endpoints candidatos a testar — em ordem de prioridade
PROBE_ENDPOINTS = [
    # Variações de FATURAS / COBRANÇAS
    "listacobrancas", "listafaturas", "listaboletos", "listapagamentos",
    "listarecebimentos", "listafinanceiro", "listafinanceiros",
    "listamensalidades", "listacobrancasabertas", "listapagamentosrecebidos",
    "cobrancas", "faturas", "boletos", "pagamentos", "financeiro",
    "consultafaturas", "buscacobrancas", "getfaturas",
    # Clientes (referência)
    "listaclientes", "listaservicos",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _http_get(endpoint: str, params: Dict[str, Any], timeout: int = 20) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.get(f"{ATLAZ_BASE_URL}/{endpoint}", params=params)


def _norm_invoice(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza um documento de fatura Atlaz V2 para o schema interno.

    Schema real da Atlaz: id, id_assinante, valor, data_vencimento,
      data_pagamento, linha_digitavel, link, descricao, valor_pago, ...
    """
    pick = lambda *keys: next((raw.get(k) for k in keys if raw.get(k) is not None), None)  # noqa: E731

    def _flt(v):
        try:
            return float(str(v).replace(",", ".")) if v else 0.0
        except (TypeError, ValueError):
            return 0.0

    paid_date = pick("data_pagamento", "data_baixa", "data_recebimento")
    status_raw = pick("status", "situacao", "estado")
    if not status_raw:
        # Status derivado se a API não trouxe explicitamente
        status_raw = "paid" if paid_date else "open"

    return {
        "external_id": str(pick("id", "id_fatura", "id_cobranca") or ""),
        "subscriber_external_id": str(pick("id_assinante", "id_cliente") or ""),
        "subscriber_name": pick("nome_assinante", "cliente_nome",
                                  "nome_cliente", "nome", "razao_social"),
        "subscriber_document": pick("cpf_cnpj", "cpf", "cnpj", "documento"),
        "amount": _flt(pick("valor", "valor_fatura", "valor_cobranca")),
        "amount_paid": _flt(pick("valor_pago", "valor_recebido")),
        "due_date": pick("data_vencimento", "vencimento", "data_venc"),
        "issue_date": pick("data_emissao", "data_geracao", "emissao",
                            "data_cadastro"),
        "paid_date": paid_date,
        "status": status_raw,
        "barcode": pick("linha_digitavel", "codigo_barras"),
        "boleto_url": pick("link", "url_boleto", "boleto_url"),
        "description": pick("descricao", "description"),
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


async def _load_clients_cache(cid: str, token: str,
                                timeout: float) -> Dict[str, Dict[str, Any]]:
    """Carrega mapa id_assinante → {name, document, phone} via /listaclientes.

    Schema real da Atlaz:
      {success, total_de_paginas, assinantes: {"1": {assinante: {...},
                                                       pontos_de_acesso: [...]},
                                                "2": {...}, ...}}

    Cada assinante.id_assinante é a chave de junção com /faturas.id_assinante.
    Salva no cache local `atlaz_clients_cache` (1 doc por subscriber).
    """
    out: Dict[str, Dict[str, Any]] = {}
    page = 1
    max_pages_safety = 100
    while page <= max_pages_safety:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(
                f"{ATLAZ_BASE_URL}/listaclientes",
                params={"token": token, "pagina": str(page)},
            )
        if r.status_code >= 400:
            logger.warning("[atlaz-fin] clientes HTTP %s pg=%s", r.status_code, page)
            break
        data = r.json() if r.content else {}
        if not isinstance(data, dict) or data.get("success") in ("false", False):
            break
        assinantes = data.get("assinantes")
        if not assinantes:
            break
        # Iterar — pode vir como dict numerado OU como lista
        records: List[Dict[str, Any]] = []
        if isinstance(assinantes, dict):
            records = list(assinantes.values())
        elif isinstance(assinantes, list):
            records = assinantes
        if not records:
            break
        ops = []
        for rec in records:
            # Schema: {"assinante": {...}, "pontos_de_acesso": [...]}
            a = rec.get("assinante") if isinstance(rec, dict) and "assinante" in rec else rec
            if not isinstance(a, dict):
                continue
            sid = str(a.get("id_assinante") or a.get("id") or "")
            if not sid:
                continue
            info = {
                "name": a.get("nome") or a.get("razao_social") or a.get("nome_completo"),
                "document": (a.get("cpf_cnpj") or a.get("cpf")
                              or a.get("cnpj") or a.get("documento")),
                "phone": (a.get("telefone") or a.get("celular")
                          or a.get("whatsapp") or a.get("celular1")),
                "email": a.get("email"),
            }
            out[sid] = info
            ops.append(UpdateOne(
                {"company_id": cid, "external_id": sid},
                {"$set": {"company_id": cid, "external_id": sid,
                           **info, "synced_at": now_iso()}},
                upsert=True,
            ))
        if ops:
            await db.atlaz_clients_cache.bulk_write(ops, ordered=False)
        # Paginação — Atlaz retorna total_de_paginas
        total_pages = data.get("total_de_paginas")
        try:
            total_pages = int(total_pages) if total_pages else None
        except (TypeError, ValueError):
            total_pages = None
        if total_pages is None or page >= total_pages:
            break
        page += 1
    return out


@router.post("/sync-now")
async def sync_now(
    days_back: int = Query(15, ge=1, le=365),
    days_forward: int = Query(15, ge=0, le=365),
    enrich_clients: bool = Query(True),
    user: dict = Depends(require_role("administrador", "gestor", "auditor", "financeiro")),
):
    """Pull manual de faturas do Atlaz V2 → `subscriber_invoices`.

    Estratégia:
      • Default 15d back + 15d forward (rápido)
      • Se enrich_clients=true, faz JOIN com /listaclientes pra trazer
        nome + CPF do assinante (a /faturas só traz id_assinante).
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(cid)
    if not cfg.api_key:
        raise HTTPException(400, "Token Atlaz não configurado")

    # Timeout interno < ingress (60s); deixa folga pra DB + retorno
    fat_timeout = 45.0

    today = datetime.now(timezone.utc).date()
    date_ini = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    date_fim = (today + timedelta(days=days_forward)).strftime("%Y-%m-%d")

    # 1) Cache local de clientes (id_assinante -> {nome, cpf}) — opcional
    # Se cache existe local, usa ele direto (não busca da API agora)
    clients_map: Dict[str, Dict[str, Any]] = {}
    if enrich_clients:
        cur = db.atlaz_clients_cache.find(
            {"company_id": cid},
            {"_id": 0, "external_id": 1, "name": 1, "document": 1, "phone": 1},
        )
        async for c in cur:
            clients_map[c["external_id"]] = c
        logger.info("[atlaz-fin] cache local clientes: %d", len(clients_map))

    inserted = 0
    updated = 0
    errors: List[str] = []
    pages_fetched = 0

    page = 1
    max_pages = 50  # safety cap
    while page <= max_pages:
        params = {
            "token": cfg.api_key,
            "data_vencimento_inicial": date_ini,
            "data_vencimento_final": date_fim,
            "pagina": str(page),
        }
        try:
            async with httpx.AsyncClient(timeout=fat_timeout) as client:
                r = await client.get(f"{ATLAZ_BASE_URL}/faturas", params=params)
            if r.status_code >= 400:
                errors.append(f"HTTP {r.status_code} pg={page}")
                break
            data = r.json()
            if isinstance(data, dict) and data.get("success") in ("false", False):
                errors.append(f"pg={page}: {data.get('msg')}")
                break
            items: List[Dict[str, Any]] = []
            if isinstance(data, dict):
                for k in ("faturas", "data", "results", "items"):
                    v = data.get(k)
                    if isinstance(v, list):
                        items = v
                        break
            elif isinstance(data, list):
                items = data
            if not items:
                break
            pages_fetched += 1
            # Bulk write: muito mais rápido que update_one em loop
            ops = []
            now_str = now_iso()
            for raw in items:
                norm = _norm_invoice(raw)
                if not norm["external_id"]:
                    continue
                # Enriquecer com nome+cpf do cliente (cache)
                sub_id = norm.get("subscriber_external_id")
                if sub_id and sub_id in clients_map:
                    c = clients_map[sub_id]
                    norm["subscriber_name"] = c.get("name")
                    norm["subscriber_document"] = c.get("document")
                    norm["subscriber_phone"] = c.get("phone")
                norm["company_id"] = cid
                norm["source"] = "atlaz_faturas"
                norm["synced_at"] = now_str
                ops.append(UpdateOne(
                    {"company_id": cid, "external_id": norm["external_id"]},
                    {"$set": norm,
                     "$setOnInsert": {
                         "id": f"sinv-{uuid.uuid4().hex[:10]}",
                         "created_at": now_str,
                     }},
                    upsert=True,
                ))
            if ops:
                result = await db.subscriber_invoices.bulk_write(ops, ordered=False)
                inserted += result.upserted_count
                updated += (result.modified_count + result.matched_count
                             - result.upserted_count)
            # Paginação
            total_pages = None
            if isinstance(data, dict):
                total_pages = data.get("total_de_paginas")
                try:
                    total_pages = int(total_pages) if total_pages else None
                except (TypeError, ValueError):
                    total_pages = None
            if total_pages is None:
                # Atlaz /faturas retorna tudo em uma "página" se total_de_paginas=None
                break
            if page >= total_pages:
                break
            page += 1
        except Exception as e:
            errors.append(f"pg={page}: {type(e).__name__} {e}")
            break

    await db.atlaz_sync_logs.insert_one({
        "id": f"asf-{uuid.uuid4().hex[:10]}",
        "company_id": cid, "event": "atlaz_financeiro_sync",
        "status": "ok" if pages_fetched > 0 else "skipped",
        "details": f"date_range={date_ini}..{date_fim}; pages={pages_fetched}; ins={inserted}; upd={updated}",
        "errors": errors[:5],
        "at": now_iso(),
    })
    return {
        "date_range": [date_ini, date_fim],
        "pages_fetched": pages_fetched,
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


# ===========================================================================
# Marcar fatura como PAGA — local + best-effort push pra Atlaz V2
# ===========================================================================
# Endpoints candidatos da Atlaz V2 para registrar pagamento (a API V2 não
# documenta isso publicamente; testamos vários nomes possíveis).
ATLAZ_PAY_ENDPOINTS = [
    "baixafatura", "baixarfatura", "baixar_fatura",
    "quitarfatura", "quitar_fatura",
    "registrarpagamento", "registrar_pagamento",
    "pagarfatura", "pagar_fatura",
    "recebimento", "registrarrecebimento",
    "atualizafatura", "atualizar_fatura",
]


class MarkPaidPayload(BaseModel):
    paid_amount: Optional[float] = None
    paid_date: Optional[str] = None  # YYYY-MM-DD
    paid_method: Optional[str] = "manual"
    paid_note: Optional[str] = None
    push_to_atlaz: bool = True


async def _try_push_atlaz_payment(
    token: str,
    external_id: str,
    paid_amount: float,
    paid_date: str,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """Tenta marcar fatura como paga na API Atlaz V2 testando múltiplos endpoints.

    Retorna {ok, endpoint, http_status, response, error}.
    Se todos falharem, retorna {ok: False, error: "no_endpoint_responded"}.
    """
    attempts: List[Dict[str, Any]] = []
    params_base = {
        "token": token,
        "id_fatura": external_id,
        "id": external_id,
        "valor_pago": str(paid_amount),
        "valor": str(paid_amount),
        "data_pagamento": paid_date,
        "data_baixa": paid_date,
    }
    for ep in ATLAZ_PAY_ENDPOINTS:
        for method in ("POST", "GET"):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    if method == "POST":
                        r = await client.post(
                            f"{ATLAZ_BASE_URL}/{ep}", params=params_base,
                        )
                    else:
                        r = await client.get(
                            f"{ATLAZ_BASE_URL}/{ep}", params=params_base,
                        )
                body_short = (r.text or "")[:200]
                # Sucesso: 200 com success=true OU sem erro óbvio
                ok = False
                if r.status_code == 200:
                    try:
                        data = r.json()
                        success_flag = data.get("success") if isinstance(data, dict) else None
                        ok = (success_flag == "true" or success_flag is True
                              or (success_flag is None and "erro" not in body_short.lower()
                                  and "not found" not in body_short.lower()))
                    except Exception:
                        ok = "erro" not in body_short.lower()
                attempts.append({
                    "endpoint": ep, "method": method,
                    "http_status": r.status_code,
                    "response": body_short, "ok": ok,
                })
                if ok:
                    return {
                        "ok": True, "endpoint": ep, "method": method,
                        "http_status": r.status_code, "response": body_short,
                        "attempts": len(attempts),
                    }
            except Exception as e:
                attempts.append({
                    "endpoint": ep, "method": method,
                    "http_status": 0, "error": str(e)[:120], "ok": False,
                })
                continue
    return {
        "ok": False,
        "error": "no_endpoint_responded",
        "attempts": attempts[:6],  # primeiros 6 pra debug, evita payload gigante
        "total_attempts": len(attempts),
    }


@router.post("/invoices/{invoice_id}/mark-paid")
async def mark_invoice_paid(
    invoice_id: str,
    payload: MarkPaidPayload,
    user: dict = Depends(require_role("administrador", "financeiro")),
):
    """Marca fatura como paga LOCALMENTE + tenta push pra Atlaz V2 (best-effort).

    Sempre atualiza local (status=paid, paid_*). Se push_to_atlaz=True e o
    Atlaz tiver token configurado, tenta empurrar a baixa via /baixafatura
    e similares. Retorna `atlaz_push` com resultado do push.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    inv = await db.subscriber_invoices.find_one(
        {"company_id": cid, "id": invoice_id}, {"_id": 0},
    )
    if not inv:
        raise HTTPException(404, "Fatura não encontrada")

    paid_amount = payload.paid_amount if payload.paid_amount is not None else inv.get("amount", 0.0)
    paid_date = payload.paid_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    paid_at = now_iso()

    # --- 1) Atualização LOCAL (sempre roda)
    update_doc = {
        "status": "paid",
        "paid_date": paid_date,
        "amount_paid": paid_amount,
        "paid_method": payload.paid_method or "manual",
        "paid_note": payload.paid_note,
        "paid_by_user_id": user.get("id"),
        "paid_by_user_name": user.get("name") or user.get("email"),
        "paid_at": paid_at,
        "paid_source": "smartprov",
    }
    await db.subscriber_invoices.update_one(
        {"company_id": cid, "id": invoice_id},
        {"$set": update_doc},
    )

    # --- 2) Push pra Atlaz (best-effort)
    atlaz_push: Dict[str, Any] = {"attempted": False}
    if payload.push_to_atlaz and inv.get("external_id"):
        cfg = await _get_config(cid)
        if cfg.api_key:
            atlaz_push = {"attempted": True}
            try:
                push = await _try_push_atlaz_payment(
                    token=cfg.api_key,
                    external_id=str(inv["external_id"]),
                    paid_amount=float(paid_amount),
                    paid_date=paid_date,
                    timeout=cfg.timeout_seconds,
                )
                atlaz_push.update(push)
                if push.get("ok"):
                    await db.subscriber_invoices.update_one(
                        {"company_id": cid, "id": invoice_id},
                        {"$set": {
                            "paid_pushed_to_atlaz": True,
                            "paid_atlaz_endpoint": push.get("endpoint"),
                            "paid_atlaz_at": paid_at,
                        }},
                    )
                else:
                    await db.subscriber_invoices.update_one(
                        {"company_id": cid, "id": invoice_id},
                        {"$set": {
                            "paid_pushed_to_atlaz": False,
                            "paid_atlaz_last_error": push.get("error"),
                        }},
                    )
            except Exception as e:
                logger.exception("[atlaz-fin] push falhou inv=%s", invoice_id)
                atlaz_push = {
                    "attempted": True, "ok": False,
                    "error": f"{type(e).__name__}: {e}",
                }

    # --- 3) Log de auditoria
    await db.atlaz_sync_logs.insert_one({
        "id": f"pay-{uuid.uuid4().hex[:10]}",
        "company_id": cid, "event": "invoice_mark_paid",
        "status": "ok",
        "details": (
            f"inv={invoice_id} subscriber={inv.get('subscriber_name') or inv.get('subscriber_external_id')}"
            f" amount={paid_amount} atlaz_push_ok={atlaz_push.get('ok', False)}"
        ),
        "at": paid_at,
    })

    updated = await db.subscriber_invoices.find_one(
        {"company_id": cid, "id": invoice_id}, {"_id": 0},
    )
    return {"ok": True, "invoice": updated, "atlaz_push": atlaz_push}


@router.post("/invoices/{invoice_id}/unmark-paid")
async def unmark_invoice_paid(
    invoice_id: str,
    user: dict = Depends(require_role("administrador", "financeiro")),
):
    """Reverte a marcação local de paga (volta status=open). Não desfaz no Atlaz."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    inv = await db.subscriber_invoices.find_one(
        {"company_id": cid, "id": invoice_id}, {"_id": 0},
    )
    if not inv:
        raise HTTPException(404, "Fatura não encontrada")
    await db.subscriber_invoices.update_one(
        {"company_id": cid, "id": invoice_id},
        {
            "$set": {
                "status": "open",
                "amount_paid": 0,
                "paid_unmarked_by": user.get("id"),
                "paid_unmarked_at": now_iso(),
            },
            "$unset": {
                "paid_date": "", "paid_method": "", "paid_note": "",
                "paid_by_user_id": "", "paid_by_user_name": "", "paid_at": "",
                "paid_source": "", "paid_pushed_to_atlaz": "",
                "paid_atlaz_endpoint": "", "paid_atlaz_at": "",
                "paid_atlaz_last_error": "",
            },
        },
    )
    return {"ok": True}


@router.get("/probe-write")
async def probe_write(
    user: dict = Depends(require_role("administrador")),
):
    """Descobre quais endpoints de ESCRITA (baixa de fatura) existem na Atlaz V2.

    NÃO efetua nenhuma escrita real — apenas faz um GET/HEAD nos endpoints
    com token sozinho (sem id_fatura) e analisa a resposta de erro pra
    inferir se o endpoint existe (ex.: "id_fatura obrigatório" indica que o
    endpoint EXISTE; HTTP 404 indica que não).
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(cid)
    if not cfg.api_key:
        raise HTTPException(400, "Token Atlaz não configurado")
    results: List[Dict[str, Any]] = []
    for ep in ATLAZ_PAY_ENDPOINTS:
        try:
            async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
                r = await client.get(
                    f"{ATLAZ_BASE_URL}/{ep}",
                    params={"token": cfg.api_key},
                )
            body = (r.text or "")[:200]
            exists = r.status_code != 404 and "not found" not in body.lower()
            results.append({
                "endpoint": ep, "http_status": r.status_code,
                "likely_exists": exists, "body_sample": body,
            })
        except Exception as e:
            results.append({
                "endpoint": ep, "http_status": 0,
                "likely_exists": False, "error": str(e)[:120],
            })
    return {"probed_at": now_iso(), "endpoints": results}


@router.post("/sync-clients")
async def sync_clients(user: dict = Depends(require_role("administrador"))):
    """Sincroniza clientes Atlaz para o cache local (rodando em background).

    Pode demorar (55+ páginas para Ligo Fibra). Roda fire-and-forget e
    retorna imediatamente. Consulte /api/atlaz-financeiro/clients-cache
    pra ver progresso.
    """
    import asyncio
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(cid)
    if not cfg.api_key:
        raise HTTPException(400, "Token Atlaz não configurado")

    async def _bg():
        try:
            n = await _load_clients_cache(cid, cfg.api_key, 45.0)
            logger.info("[atlaz-fin] sync-clients background: %d clientes carregados", len(n))
            await db.atlaz_sync_logs.insert_one({
                "id": f"asc-{uuid.uuid4().hex[:10]}",
                "company_id": cid, "event": "atlaz_clients_sync",
                "status": "ok",
                "details": f"clients_synced={len(n)}",
                "at": now_iso(),
            })
        except Exception as e:
            logger.exception("[atlaz-fin] sync-clients background falhou: %s", e)
            await db.atlaz_sync_logs.insert_one({
                "id": f"asc-{uuid.uuid4().hex[:10]}",
                "company_id": cid, "event": "atlaz_clients_sync",
                "status": "error",
                "details": f"{type(e).__name__}: {e}",
                "at": now_iso(),
            })

    asyncio.create_task(_bg())
    return {"ok": True, "message": "Sync em background iniciado. Acompanhe via /clients-cache."}


@router.get("/clients-cache")
async def clients_cache_stats(user: dict = Depends(require_role("administrador", "financeiro"))):
    """Estatísticas do cache de clientes (progresso da sync)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    n = await db.atlaz_clients_cache.count_documents({"company_id": cid})
    last = await db.atlaz_sync_logs.find_one(
        {"company_id": cid, "event": "atlaz_clients_sync"},
        {"_id": 0}, sort=[("at", -1)],
    )
    return {
        "total_cached": n,
        "last_run": last.get("at") if last else None,
        "last_status": last.get("status") if last else None,
        "last_details": last.get("details") if last else None,
    }


@router.post("/enrich-invoices")
async def enrich_existing_invoices(user: dict = Depends(require_role("administrador"))):
    """Aplica nome/CPF/telefone do cache de clientes às faturas já sincronizadas."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # Carrega mapa do cache local
    cur = db.atlaz_clients_cache.find(
        {"company_id": cid},
        {"_id": 0, "external_id": 1, "name": 1, "document": 1, "phone": 1},
    )
    cmap: Dict[str, Dict[str, Any]] = {}
    async for c in cur:
        cmap[c["external_id"]] = c
    if not cmap:
        return {"ok": False, "message": "Cache vazio. Execute /sync-clients primeiro."}
    ops = []
    cur2 = db.subscriber_invoices.find(
        {"company_id": cid,
         "$or": [{"subscriber_name": None}, {"subscriber_document": None}]},
        {"_id": 0, "id": 1, "subscriber_external_id": 1},
    )
    async for inv in cur2:
        c = cmap.get(inv.get("subscriber_external_id"))
        if not c:
            continue
        ops.append(UpdateOne(
            {"id": inv["id"]},
            {"$set": {
                "subscriber_name": c.get("name"),
                "subscriber_document": c.get("document"),
                "subscriber_phone": c.get("phone"),
                "enriched_at": now_iso(),
            }},
        ))
    if ops:
        result = await db.subscriber_invoices.bulk_write(ops, ordered=False)
        return {"ok": True, "enriched": result.modified_count}
    return {"ok": True, "enriched": 0}


@router.post("/cleanup-orphans")
async def cleanup_orphans(user: dict = Depends(require_role("administrador"))):
    """Remove registros antigos sem subscriber_external_id (lixo de testes/iter72)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    r = await db.subscriber_invoices.delete_many({
        "company_id": cid,
        "$or": [
            {"subscriber_external_id": ""},
            {"subscriber_external_id": None},
            {"status": "unknown"},
            {"source": {"$nin": ["atlaz_faturas"]}},
        ],
    })
    return {"deleted": r.deleted_count}


# ===========================================================================
# Job scheduled — chamado pelo scheduler central a cada 2h
# ===========================================================================
async def auto_sync_atlaz_financeiro() -> Dict[str, Any]:
    """Sync automática (todas as empresas com token configurado)."""
    out: Dict[str, Any] = {"companies": 0, "errors": []}
    async for cfg in db.atlaz_config.find({"api_key": {"$ne": None, "$ne": ""}},
                                            {"_id": 0, "company_id": 1,
                                             "api_key": 1}):
        cid = cfg["company_id"]
        try:
            # Sync faturas com janela de 7d back + 30d forward
            from routes.atlaz import _get_config
            atc = await _get_config(cid)
            if not atc.api_key:
                continue
            today = datetime.now(timezone.utc).date()
            date_ini = (today - timedelta(days=7)).strftime("%Y-%m-%d")
            date_fim = (today + timedelta(days=30)).strftime("%Y-%m-%d")
            clients_map: Dict[str, Dict[str, Any]] = {}
            cur = db.atlaz_clients_cache.find(
                {"company_id": cid},
                {"_id": 0, "external_id": 1, "name": 1,
                 "document": 1, "phone": 1},
            )
            async for c in cur:
                clients_map[c["external_id"]] = c
            page = 1
            while page <= 50:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    r = await client.get(
                        f"{ATLAZ_BASE_URL}/faturas",
                        params={"token": atc.api_key,
                                "data_vencimento_inicial": date_ini,
                                "data_vencimento_final": date_fim,
                                "pagina": str(page)},
                    )
                if r.status_code >= 400:
                    break
                data = r.json()
                if isinstance(data, dict) and data.get("success") in ("false", False):
                    break
                items = (data.get("faturas") if isinstance(data, dict) else
                          data if isinstance(data, list) else []) or []
                if not items:
                    break
                ops = []
                now_str = now_iso()
                for raw in items:
                    norm = _norm_invoice(raw)
                    if not norm["external_id"]:
                        continue
                    sub_id = norm.get("subscriber_external_id")
                    if sub_id and sub_id in clients_map:
                        c = clients_map[sub_id]
                        norm["subscriber_name"] = c.get("name")
                        norm["subscriber_document"] = c.get("document")
                        norm["subscriber_phone"] = c.get("phone")
                    norm["company_id"] = cid
                    norm["source"] = "atlaz_faturas"
                    norm["synced_at"] = now_str
                    ops.append(UpdateOne(
                        {"company_id": cid, "external_id": norm["external_id"]},
                        {"$set": norm,
                         "$setOnInsert": {
                             "id": f"sinv-{uuid.uuid4().hex[:10]}",
                             "created_at": now_str,
                         }},
                        upsert=True,
                    ))
                if ops:
                    await db.subscriber_invoices.bulk_write(ops, ordered=False)
                total_pages = None
                if isinstance(data, dict):
                    total_pages = data.get("total_de_paginas")
                    try:
                        total_pages = int(total_pages) if total_pages else None
                    except (TypeError, ValueError):
                        total_pages = None
                if total_pages is None or page >= total_pages:
                    break
                page += 1
            out["companies"] += 1
        except Exception as e:
            logger.exception("[atlaz-fin] auto_sync %s falhou", cid)
            out["errors"].append(f"{cid}: {type(e).__name__}: {e}")
    return out


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
