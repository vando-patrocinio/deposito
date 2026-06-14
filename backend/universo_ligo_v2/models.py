"""
Modelo de dados V2 — Pydantic-friendly dicts (sem ORM heavy).

Nenhum destes modelos sobrescreve estrutura existente. Todos coexistem.
"""
from __future__ import annotations
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone


# ──────────────────────────────────────────────────────────────────────────
# Collection: universo_ligo_levels (config — 6 docs)
# ──────────────────────────────────────────────────────────────────────────
# Estrutura final (NÃO toca legacy):
#   {
#     "key": "viajante",                       # unique
#     "level_id": 2,
#     "name": "Viajante",
#     "icon": "🚶",
#     "description": "...",
#     "min_score": 100,
#     "max_score": 249,
#     "entry_rule": "6 meses + 0 inadimplência + ...",
#     "tempo_medio_meses_min": 6,
#     "tempo_medio_meses_max": 18,
#     "frase_do_cliente": "Tô gostando.",
#     "benefits": [...],
#     "non_benefits": [...],                   # só Embaixador tem
#     "requires_invite": False,                # só Embaixador = True
#     "active": True,
#     "_seed_version": 1,
#     "_seeded_at": "<iso>"
#   }


# ──────────────────────────────────────────────────────────────────────────
# Collection: universo_ligo_scores (já existe — vamos ESTENDER, não substituir)
# Campos NOVOS que serão adicionados (todos opcionais, default None/0):
# ──────────────────────────────────────────────────────────────────────────
NEW_FIELDS_IN_SCORES = {
    # Identidade V2
    "level_key_v2": None,          # str — após migração
    "level_name_v2": None,         # str
    "level_key_legacy": None,      # str — preserva o antigo (rollback)
    "level_name_legacy": None,     # str

    # Comunidade (Família Ligo)
    "family_tree_l1_count": 0,     # int — apresentações diretas convertidas
    "family_tree_l2_count": 0,     # int — apresentações indiretas
    "family_economy_brl": 0.0,     # float — economia acumulada via desconto

    # Convite Embaixador
    "embaixador_invited_at": None, # iso str — quando Pâmela+gerente convidaram
    "embaixador_accepted_at": None,
    "embaixador_card_number": None,  # ex: "Petrópolis #007"

    # Observabilidade
    "v2_migrated_at": None,        # iso str — primeira vez que rodou a migração
    "v2_last_recalc_at": None,
    "v2_schema_version": 2,
}


# ──────────────────────────────────────────────────────────────────────────
# Collection: subscribers (já tem 26.851 docs — vamos ADICIONAR campos opcionais)
# ──────────────────────────────────────────────────────────────────────────
NEW_FIELDS_IN_SUBSCRIBERS = {
    # Denormalização para queries rápidas
    "universo_score": None,           # float — sincronizado com universo_ligo_scores.score
    "universo_level_key": None,       # str — sincronizado com universo_ligo_scores.level_key_v2

    # Comunidade
    "referral_code": None,            # str — único globalmente (já existe em 8 docs)
    "referred_by_subscriber_id": None,  # FK

    # Marcos
    "first_anniversary_at": None,     # iso — calculado de installation_date

    # Observabilidade
    "universo_v2_backfilled_at": None,  # iso
}


# ──────────────────────────────────────────────────────────────────────────
# Collection: universo_ligo_milestones (NOVA)
# ──────────────────────────────────────────────────────────────────────────
# Marcos do cliente — Pâmela usa para celebrar.
# Documento:
#   {
#     "id": "uml-<random>",
#     "subscriber_id": "sub-xxx",
#     "company_id": "co-demo",
#     "milestone_type": "anniversary_1y" | "level_up" | "first_apresentation" |
#                       "6m_paid_on_time" | "90d_no_ticket" | "birthday",
#     "reached_at": "<iso>",
#     "celebrated_at": null,           # null = ainda não comunicado
#     "celebrated_by": null,           # "pamela" quando enviar
#     "context": {...},
#     "created_at": "<iso>"
#   }


# ──────────────────────────────────────────────────────────────────────────
# Collection: universo_ligo_tree_index (NOVA)
# ──────────────────────────────────────────────────────────────────────────
# Cache da árvore da família. Atualizada por scheduler.
# Documento:
#   {
#     "subscriber_id": "sub-xxx",
#     "company_id": "co-demo",
#     "l1_subscribers": ["sub-aaa","sub-bbb"],   # apresentações diretas
#     "l2_subscribers": ["sub-ccc","sub-ddd"],   # indiretas (vieram via l1)
#     "l1_count": 2,
#     "l2_count": 2,
#     "total_count": 4,
#     "last_calculated_at": "<iso>",
#     "ttl_expires_at": "<iso>",       # 7 dias
#   }


# ──────────────────────────────────────────────────────────────────────────
# Collection: universo_ligo_benefit_grants (NOVA)
# ──────────────────────────────────────────────────────────────────────────
# Concessão real de benefício ao cliente. Auditável.
# Documento:
#   {
#     "id": "ulbg-<random>",
#     "subscriber_id": "sub-xxx",
#     "company_id": "co-demo",
#     "level_key": "constelacao",
#     "benefit_key": "ligo_plus_filmes",
#     "granted_at": "<iso>",
#     "granted_by": "system_levelup" | "pamela_manual" | "gerente_regional",
#     "expires_at": null,                # null = vitalício enquanto ativo
#     "status": "active" | "used" | "expired" | "revoked",
#     "usage_count": 0,
#     "last_used_at": null,
#     "audit_log": [...],
#   }


# ──────────────────────────────────────────────────────────────────────────
# Collection: universo_ligo_migration_log (NOVA — auditoria obrigatória)
# ──────────────────────────────────────────────────────────────────────────
# Toda operação da migração escreve aqui. Sem isso, rollback é cego.
# Documento:
#   {
#     "id": "ulml-<random>",
#     "phase": "A" | "B" | "C",
#     "operation": "seed_levels" | "rename_legacy_keys" | "backfill_subscribers" | ...,
#     "subscriber_id": null,             # null se for operação global
#     "before": {...},
#     "after": {...},
#     "executed_by": "migration_script" | "manual_admin",
#     "executed_at": "<iso>",
#     "reversible_by_operation": "<id_op_inverso>",
#     "status": "applied" | "rolled_back",
#     "dry_run": False
#   }


def utcnow_iso() -> str:
    """Retorna ISO 8601 UTC string."""
    return datetime.now(timezone.utc).isoformat()
