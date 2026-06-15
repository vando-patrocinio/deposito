"""Backfill `subscribers.atlaz_subscriber_code` usando GET /consultacliente.

Auditoria 2026-02 (CTO Mode):
A API Atlaz v2 expõe `/consultacliente?cpf_cnpj=...` e `?telefone=...` que
permitem lookup reverso por documento/telefone. Isso destrava o Issue #2
(Sprint 1.1) sem precisar pedir nada novo ao Atlaz.

Estratégia:
  1. Para cada subscriber sem `atlaz_subscriber_code` (ou `atlaz_id_assinante`):
     a. Se tem `document` (CPF/CNPJ): consulta por `cpf_cnpj`.
     b. Senão se tem `phone`: consulta por `telefone` com
        `testar_com_e_sem_nono_digito=true`.
  2. Quando a API retorna `success=true`, popula:
     - `atlaz_subscriber_code` (= id_assinante, string)
     - `atlaz_id_assinante` (int, compat com código legado)
     - `atlaz_id_ponto` (primeiro ponto de acesso ativo)
     - `atlaz_pppoe_user` (username do primeiro ponto)
     - `atlaz_id_plano`
     - `atlaz_backfill_at` (timestamp)

Uso:
  python /app/backend/scripts/atlaz_backfill_subscriber_code.py
      [--company-id=<cid>]
      [--limit=200]
      [--dry-run]
      [--only-missing]   (default True)

Idempotente. Pode ser executado várias vezes.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

# Permite rodar como script (`python scripts/...`) sem PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db  # noqa: E402

ATLAZ_BASE_URL = "https://app.atlaz.com.br/api/v2"
logger = logging.getLogger("atlaz_backfill")


async def _get_atlaz_token(company_id: str) -> Optional[str]:
    cfg = await db.atlaz_config.find_one(
        {"company_id": company_id}, {"_id": 0, "api_key": 1},
    )
    return cfg.get("api_key") if cfg else None


def _digits(s: Any) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())


async def _consulta_cliente(token: str, *,
                              cpf_cnpj: Optional[str] = None,
                              telefone: Optional[str] = None,
                              timeout: float = 20.0) -> Optional[Dict[str, Any]]:
    params: Dict[str, str] = {"token": token,
                                "ocultar_contratos_desativados": "0",
                                "ocultar_assinantes_sem_contrato_ativo": "0"}
    if cpf_cnpj:
        params["cpf_cnpj"] = cpf_cnpj
    elif telefone:
        params["telefone"] = telefone
        params["testar_com_e_sem_nono_digito"] = "true"
    else:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{ATLAZ_BASE_URL}/consultacliente",
                                  params=params)
    except Exception as e:
        logger.warning("[atlaz-backfill] HTTP fail %s", e)
        return None
    if r.status_code >= 400:
        return None
    try:
        data = r.json()
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("success") != "true":
        return None
    return data


def _extract_atlaz_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """Extrai campos relevantes do payload /consultacliente."""
    assinante = data.get("assinante") or {}
    pontos = data.get("pontos_de_acesso") or []
    # Preferir ponto Ativo
    ponto = next((p for p in pontos
                   if str(p.get("status") or "").lower() == "ativo"),
                  pontos[0] if pontos else {})
    id_assinante = assinante.get("id_assinante")
    return {
        "atlaz_subscriber_code": str(id_assinante) if id_assinante else None,
        "atlaz_id_assinante": id_assinante,
        "atlaz_id_ponto": ponto.get("id_ponto"),
        "atlaz_pppoe_user": ponto.get("username"),
        "atlaz_id_plano": ponto.get("id_plano"),
        "atlaz_plano_label": ponto.get("plano"),
        "atlaz_status_ponto": ponto.get("status"),
        "atlaz_backfill_at": datetime.now(timezone.utc).isoformat(),
        "atlaz_backfill_method": data.get("_lookup_method"),
    }


async def backfill_company(company_id: str,
                              limit: int = 200,
                              dry_run: bool = False,
                              only_missing: bool = True) -> Dict[str, Any]:
    token = await _get_atlaz_token(company_id)
    if not token:
        return {"company_id": company_id, "error": "no_atlaz_token"}

    query: Dict[str, Any] = {"company_id": company_id}
    if only_missing:
        query["$and"] = [
            {"$or": [{"atlaz_subscriber_code": {"$exists": False}},
                      {"atlaz_subscriber_code": None},
                      {"atlaz_subscriber_code": ""}]},
            {"$or": [{"atlaz_id_assinante": {"$exists": False}},
                      {"atlaz_id_assinante": None}]},
        ]

    total_processed = 0
    matched_by_doc = 0
    matched_by_phone = 0
    not_found = 0
    skipped = 0
    errors = 0

    cur = db.subscribers.find(
        query,
        {"_id": 0, "id": 1, "document": 1, "phone": 1, "name": 1,
         "atlaz_subscriber_code": 1, "atlaz_id_assinante": 1},
    ).limit(limit)

    async for sub in cur:
        total_processed += 1
        doc = _digits(sub.get("document"))
        phone = _digits(sub.get("phone"))

        if len(doc) not in (11, 14):
            doc = ""
        if len(phone) not in (10, 11):
            phone = ""

        if not doc and not phone:
            skipped += 1
            continue

        lookup_method = None
        result = None

        if doc:
            result = await _consulta_cliente(token, cpf_cnpj=doc)
            if result:
                lookup_method = "cpf_cnpj"
                matched_by_doc += 1

        if not result and phone:
            result = await _consulta_cliente(token, telefone=phone)
            if result:
                lookup_method = "telefone"
                matched_by_phone += 1

        if not result:
            not_found += 1
            continue

        result["_lookup_method"] = lookup_method
        fields = _extract_atlaz_fields(result)
        if not fields.get("atlaz_subscriber_code"):
            errors += 1
            continue

        if dry_run:
            logger.info("[dry-run] %s → %s (via %s)",
                         sub.get("id"), fields["atlaz_subscriber_code"],
                         lookup_method)
            continue

        try:
            await db.subscribers.update_one(
                {"company_id": company_id, "id": sub.get("id")},
                {"$set": {k: v for k, v in fields.items() if v is not None}},
            )
        except Exception as e:
            logger.warning("[atlaz-backfill] update fail %s: %s",
                            sub.get("id"), e)
            errors += 1

    # Log de auditoria
    log_doc = {
        "company_id": company_id,
        "event": "atlaz_backfill_subscriber_code",
        "total_processed": total_processed,
        "matched_by_doc": matched_by_doc,
        "matched_by_phone": matched_by_phone,
        "not_found": not_found,
        "skipped": skipped,
        "errors": errors,
        "dry_run": dry_run,
        "limit": limit,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    if not dry_run:
        await db.atlaz_sync_logs.insert_one(log_doc)

    return log_doc


async def main():
    parser = argparse.ArgumentParser(description="Backfill atlaz_subscriber_code")
    parser.add_argument("--company-id", default=None,
                          help="Se omitido, processa todas as empresas com config Atlaz")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--all", action="store_true",
                          help="Reprocessa todos (não apenas faltantes)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                          format="%(asctime)s %(levelname)s %(message)s")

    companies: list[str] = []
    if args.company_id:
        companies = [args.company_id]
    else:
        async for c in db.atlaz_config.find(
                {"api_key": {"$nin": [None, ""]}},
                {"_id": 0, "company_id": 1}):
            companies.append(c["company_id"])

    if not companies:
        print("Nenhuma empresa com token Atlaz configurado.")
        return

    print(f"Processando {len(companies)} empresa(s): {companies}")
    for cid in companies:
        res = await backfill_company(
            cid, limit=args.limit, dry_run=args.dry_run,
            only_missing=not args.all,
        )
        print(f"  {cid}: {res}")


if __name__ == "__main__":
    asyncio.run(main())
