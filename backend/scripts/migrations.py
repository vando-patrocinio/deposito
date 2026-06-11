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


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "low",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

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
# 2026-05-20 — Vando = super_admin no banco (não mais env-only)
# =============================================================================
async def m_20260520_vando_super_admin(db) -> None:
    """Set vando@example.com.is_super_admin = true. Idempotente."""
    await db.users.update_one(
        {"email": "vando@example.com"},
        {"$set": {"is_super_admin": True}},
    )


# =============================================================================
# 2026-05-29 — iter180: Conta corporativa Vando @ligotelecom.com como super_admin
# =============================================================================
async def m_20260529_vando_ligotelecom_super_admin(db) -> None:
    """Set vando@ligotelecom.com.is_super_admin = true. Idempotente.

    A criação do usuário em si é feita pelo `seed_default_users()` em
    `auth.py`. Aqui só elevamos a flag de super-admin (mesmo padrão da
    migration anterior). Mantém vando@example.com ativo também.
    """
    await db.users.update_one(
        {"email": "vando@ligotelecom.com"},
        {"$set": {"is_super_admin": True}},
    )


# =============================================================================
# 2026-05-29 — iter180: índices da Sentinela IA da foto da CTO
# =============================================================================
async def m_20260529_cto_photo_validator_indexes(db) -> None:
    await db.cto_photo_validations.create_index(
        [("company_id", 1), ("created_at", -1)])
    await db.cto_photo_validations.create_index(
        [("company_id", 1), ("sha1", 1)])
    await db.cto_photo_validations.create_index(
        [("company_id", 1), ("phash", 1)])
    await db.cto_photo_validations.create_index([("id", 1)], unique=True)
    await db.network_tickets.create_index(
        [("company_id", 1), ("status", 1), ("created_at", -1)])
    await db.network_tickets.create_index([("id", 1)], unique=True)


# =============================================================================
# 2026-05-29 — iter180: índices do SmartOLT VLAN sync worker
# =============================================================================
async def m_20260529_smartolt_vlan_sync_indexes(db) -> None:
    await db.subscriber_vlan_history.create_index(
        [("company_id", 1), ("subscriber_id", 1), ("changed_at", -1)])
    await db.subscriber_vlan_history.create_index(
        [("company_id", 1), ("changed_at", -1)])
    await db.network_tickets.create_index(
        [("company_id", 1), ("type", 1), ("status", 1), ("created_at", -1)],
        sparse=True)
    await db.subscribers.create_index(
        [("company_id", 1), ("current_vlan", 1)], sparse=True)


# =============================================================================
# 2026-05-29 — iter180: nova nomenclatura sem bairro
# CTO  "CTO 004_301_BRA"  → "CTO_301_004"
# CABO "CABO 004_301_BRA" → "CABO_301_004"
# CE   "CE00001_BRA"      → "CE_00001"
# =============================================================================
async def m_20260529_rename_ctos_no_sigla(db) -> None:
    """Renomeia todos os elementos de rede para a nova nomenclatura
    sem bairro. Mantém VLAN inalterada. RENUMERA quando a migração
    de remoção de sigla causaria colisão por (company, vlan, tipo).

    IDEMPOTENTE: docs cujo nome já está no novo formato são pulados.
    """
    from collections import defaultdict

    # Carrega todos os elementos relevantes
    items = []
    cursor = db.ctos.find(
        {},
        {"_id": 0, "id": 1, "name": 1, "number": 1, "vlan": 1,
         "element_type": 1, "created_at": 1, "company_id": 1},
    )
    async for c in cursor:
        if isinstance(c.get("number"), int):
            items.append(c)
    # Ordena por (created_at, number) para preservar a ordem original
    # quando renumerarmos colisões.
    items.sort(key=lambda x: (x.get("created_at") or "", x.get("number") or 0))

    # Aloca número sequencial por (company, vlan, type)  — exceto CE
    # que ignora VLAN.
    used: dict = defaultdict(set)  # key → set de números já usados
    renamed = 0
    renumbered = 0
    skipped = 0
    for c in items:
        elem_t = (c.get("element_type") or "cto").lower()
        cid = (c.get("company_id") or None)
        if cid is None:
            cid = await _fetch_company_id_for_cto(db, c["id"])
        vlan = c.get("vlan")
        if elem_t == "ce":
            key = (cid, "ce")
        else:
            key = (cid, elem_t, vlan)
        # número original tem prioridade se ainda livre
        orig = c["number"]
        new_n = orig if orig not in used[key] else max(used[key]) + 1
        used[key].add(new_n)
        if elem_t == "ce":
            new_name = f"CE_{new_n:05d}"
        elif elem_t == "cabo":
            new_name = f"CABO_{vlan}_{new_n:03d}" if vlan else f"CABO_{new_n:03d}"
        else:
            new_name = f"CTO_{vlan}_{new_n:03d}" if vlan else f"CTO_{new_n:03d}"
        sets = {"name": new_name}
        if new_n != orig:
            sets["number"] = new_n
            renumbered += 1
        if c.get("name") == new_name and new_n == orig:
            skipped += 1
            continue
        sets["name_legacy"] = c.get("name")
        sets["name_migrated_at"] = datetime.now(timezone.utc).isoformat()
        await db.ctos.update_one({"id": c["id"]}, {"$set": sets})
        renamed += 1
    logger.info("[migration rename CTOs] renamed=%s (renumbered=%s) skipped=%s",
                  renamed, renumbered, skipped)


async def _fetch_company_id_for_cto(db, cto_id: str):
    doc = await db.ctos.find_one({"id": cto_id}, {"_id": 0, "company_id": 1})
    return (doc or {}).get("company_id")


# =============================================================================
# 2026-05-29 — iter180: índice único impede 2 elementos do mesmo tipo
# com o mesmo nome dentro de uma empresa
# =============================================================================
async def m_20260529_unique_element_name(db) -> None:
    try:
        await db.ctos.create_index(
            [("company_id", 1), ("element_type", 1), ("name", 1)],
            unique=True, sparse=True,
            name="uniq_company_type_name_v2",
        )
    except Exception as e:
        logger.warning("[migration unique_element_name] %s", e)


# =============================================================================
# 2026-05-20 — Central de Compras: índices e adição de campos opcionais
# =============================================================================
async def m_20260520_purchases_setup(db) -> None:
    await db.purchases.create_index(
        [("company_id", 1), ("created_at", -1)])
    await db.purchases.create_index(
        [("company_id", 1), ("praca_id", 1), ("status", 1)])
    await db.purchases.create_index([("id", 1)], unique=True)
    # Estende stok_onts com campos opcionais (compat com fluxo existente)
    await db.stok_onts.create_index(
        [("company_id", 1), ("praca_id", 1)], sparse=True)
    await db.stok_stock.create_index(
        [("company_id", 1), ("praca_id", 1), ("insumo_key", 1)],
        sparse=True)


# =============================================================================
# 2026-05-21 — Sales Funnel: garante que a aba aparece pras roles que tinham
#              acesso default; cria índices nas novas coleções
# =============================================================================
async def m_20260521_sales_funnel_setup(db) -> None:
    # 1. Adiciona "sales-funnel" ao tab_permissions de roles que TINHAM o
    #    "mass-messaging" (mesmo grupo Inteligência) — preserva desmarcações.
    async for doc in db.company_branding.find({}):
        tp = doc.get("tab_permissions") or {}
        changed = False
        for role in ("administrador", "auditor", "gestor"):
            arr = tp.get(role)
            if isinstance(arr, list) and "mass-messaging" in arr and "sales-funnel" not in arr:
                arr.append("sales-funnel")
                changed = True
        if changed:
            await db.company_branding.update_one(
                {"_id": doc["_id"]}, {"$set": {"tab_permissions": tp}})
    # 2. Índices
    await db.pre_subscribers.create_index([("company_id", 1), ("phone", 1)])
    await db.pre_subscribers.create_index([("company_id", 1), ("status", 1),
                                              ("created_at", -1)])
    await db.sales_funnel_log.create_index([("company_id", 1), ("at", -1)])
    await db.mass_messages_jobs.create_index(
        [("company_id", 1), ("status", 1)], sparse=True)


# =============================================================================
# Lista ordenada de migrations a executar
# =============================================================================
MIGRATIONS: List[Tuple[str, Callable[..., Awaitable[None]]]] = [
    ("20260520_bank_import_memory_indexes", m_20260520_bank_import_memory_indexes),
    ("20260520_branding_schema_version", m_20260520_branding_schema_version),
    ("20260520_vando_super_admin", m_20260520_vando_super_admin),
    ("20260520_purchases_setup", m_20260520_purchases_setup),
    ("20260521_sales_funnel_setup", m_20260521_sales_funnel_setup),
    ("20260529_vando_ligotelecom_super_admin", m_20260529_vando_ligotelecom_super_admin),
    ("20260529_cto_photo_validator_indexes", m_20260529_cto_photo_validator_indexes),
    ("20260529_smartolt_vlan_sync_indexes", m_20260529_smartolt_vlan_sync_indexes),
    ("20260529_rename_ctos_no_sigla", m_20260529_rename_ctos_no_sigla),
    ("20260529_unique_element_name", m_20260529_unique_element_name),
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
