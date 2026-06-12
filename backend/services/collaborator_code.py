"""Serviço de código único do colaborador (LIGO-NNNN).

Pedido CTO 12/06/2026: cada colaborador deve ter um código humanamente
memorável (formato `LIGO-NNNN`, sequencial, idempotente) que sirva como
identificação no sistema SmartProv (diferente do UUID interno `col-xxxxxxxx`).

Regras:
  • Idempotente: NUNCA regenera um código que já foi atribuído.
  • Sequencial: próximo código = max(NNNN existentes) + 1.
  • Por tenant (`company_id`): cada empresa tem sua própria sequência.
  • Formato: `LIGO-NNNN` (4 dígitos zero-padded; expande pra 5+ se ultrapassar 9999).
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from database import db

logger = logging.getLogger(__name__)

CODE_PATTERN = re.compile(r"^LIGO-(\d{4,})$", re.IGNORECASE)


def _format_code(n: int) -> str:
    return f"LIGO-{n:04d}"


async def _next_seq(company_id: str) -> int:
    """Calcula o próximo número da sequência, varrendo códigos existentes."""
    max_n = 0
    cursor = db.collaborators.find(
        {"company_id": company_id, "code": {"$exists": True, "$ne": None}},
        {"_id": 0, "code": 1},
    )
    async for doc in cursor:
        m = CODE_PATTERN.match(str(doc.get("code") or ""))
        if m:
            try:
                max_n = max(max_n, int(m.group(1)))
            except ValueError:
                continue
    return max_n + 1


async def get_or_assign_code(collaborator_id: str, company_id: str) -> Optional[str]:
    """Retorna o code do colaborador. Se não tiver, atribui um novo (idempotente)."""
    doc = await db.collaborators.find_one(
        {"id": collaborator_id, "company_id": company_id},
        {"_id": 0, "code": 1},
    )
    if not doc:
        return None
    if doc.get("code"):
        return doc["code"]
    next_n = await _next_seq(company_id)
    code = _format_code(next_n)
    # Race condition guard: try insert, retry once if duplicate.
    for attempt in range(3):
        try:
            r = await db.collaborators.update_one(
                {"id": collaborator_id, "company_id": company_id,
                 "$or": [{"code": {"$exists": False}}, {"code": None}]},
                {"$set": {"code": code}},
            )
            if r.matched_count > 0:
                logger.info("[collab_code] %s = %s", collaborator_id, code)
                return code
            # Alguém atribuiu primeiro — releia
            fresh = await db.collaborators.find_one(
                {"id": collaborator_id, "company_id": company_id},
                {"_id": 0, "code": 1},
            )
            if fresh and fresh.get("code"):
                return fresh["code"]
            next_n += 1
            code = _format_code(next_n)
        except Exception as e:  # noqa: BLE001
            logger.warning("[collab_code] retry %d falhou: %s", attempt, e)
    return None


async def backfill_all(company_id: Optional[str] = None) -> dict:
    """Migração idempotente: atribui code para TODOS os colaboradores que
    ainda não têm. Pode ser chamada na inicialização ou via endpoint.

    Retorna `{checked, assigned, skipped, errors}`.
    """
    q = {"$or": [{"code": {"$exists": False}}, {"code": None}]}
    if company_id:
        q["company_id"] = company_id

    # Agrupa por tenant pra manter sequência separada
    summary = {"checked": 0, "assigned": 0, "skipped": 0, "errors": 0,
                "by_company": {}}

    tenants = await db.collaborators.distinct("company_id", q)
    for cid in tenants:
        if not cid:
            continue
        next_n = await _next_seq(cid)
        cursor = db.collaborators.find(
            {**q, "company_id": cid},
            {"_id": 0, "id": 1},
        )
        async for doc in cursor:
            summary["checked"] += 1
            code = _format_code(next_n)
            try:
                r = await db.collaborators.update_one(
                    {"id": doc["id"], "company_id": cid,
                     "$or": [{"code": {"$exists": False}}, {"code": None}]},
                    {"$set": {"code": code}},
                )
                if r.matched_count > 0:
                    summary["assigned"] += 1
                    next_n += 1
                else:
                    summary["skipped"] += 1
            except Exception as e:  # noqa: BLE001
                summary["errors"] += 1
                logger.warning("[collab_code backfill] %s falhou: %s",
                                doc.get("id"), e)
        summary["by_company"][cid] = next_n - 1

    logger.info("[collab_code backfill] %s", summary)
    return summary
