"""
Migrations idempotentes — SmartProv

Sistema simples e ADITIVO:
- Cada migration tem um `id` único e roda APENAS se ainda não rodou
- Estado de migrações fica em `db.schema_migrations` (id + applied_at)
- Migrations SÓ adicionam campos/coleções/índices — NUNCA apagam ou
  renomeiam (essas operações precisam ser feitas manualmente em ops)

Como criar uma nova migration:
    1. Adicionar entrada em MIGRATIONS abaixo com id único (data + slug)
    2. Função async (db) -> None que faz as alterações
    3. Restart do backend → roda automaticamente

Como verificar quais migrations rodaram:
    > db.schema_migrations.find({}, {_id:0}).sort({applied_at:1})
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable, List, Tuple

logger = logging.getLogger("ponto.migrations")


# =============================================================================
# 2026-05-20 — Garante que bank_import_memory tem índices
# =============================================================================
async def m_20260520_bank_import_memory_indexes(db) -> None:
    await db.bank_import_memory.create_index(
        [("company_id", 1), ("doc", 1)], sparse=True)
    await db.bank_import_memory.create_index(
        [("company_id", 1), ("key", 1)])
    await db.bank_import_staging.create_index(
        [("company_id", 1), ("created_at", -1)])


# =============================================================================
# 2026-05-20 — Garante schema_version em company_branding (default = "1")
# =============================================================================
async def m_20260520_branding_schema_version(db) -> None:
    """Adiciona schema_version a docs sem ela. NÃO sobrescreve quem já tem."""
    await db.company_branding.update_many(
        {"schema_version": {"$exists": False}},
        {"$set": {"schema_version": "1"}},
    )


# =============================================================================
# Lista ordenada de migrations a executar
# =============================================================================
MIGRATIONS: List[Tuple[str, Callable[..., Awaitable[None]]]] = [
    ("20260520_bank_import_memory_indexes", m_20260520_bank_import_memory_indexes),
    ("20260520_branding_schema_version", m_20260520_branding_schema_version),
]


async def run_pending_migrations(db) -> dict:
    """Executa todas as migrations não aplicadas. Idempotente.

    Retorna dict com {applied: [...], skipped: [...]}.
    """
    applied: List[str] = []
    skipped: List[str] = []
    failed: List[Tuple[str, str]] = []

    for mig_id, mig_fn in MIGRATIONS:
        existing = await db.schema_migrations.find_one({"id": mig_id})
        if existing:
            skipped.append(mig_id)
            continue
        try:
            logger.info("[migrations] aplicando %s …", mig_id)
            await mig_fn(db)
            await db.schema_migrations.insert_one({
                "id": mig_id,
                "applied_at": datetime.now(timezone.utc).isoformat(),
            })
            applied.append(mig_id)
            logger.info("[migrations] %s OK", mig_id)
        except Exception as e:
            logger.exception("[migrations] %s falhou: %s", mig_id, e)
            failed.append((mig_id, str(e)))
            # NÃO aborta as outras — cada migration é independente

    return {"applied": applied, "skipped": skipped, "failed": failed}
