"""
services/destructive_audit.py — CTO 16/02/2026 — ONDA 1 (Destrutivos).

Contrato canônico para operações destrutivas do patrimônio.

REGRA MESTRA (ordem CEO):
  Nenhuma operação que apague, resete, descarte ou reverta patrimônio pode
  executar SEM antes chamar `record_destructive_action(...)`. Este helper
  valida `reason` obrigatório, gera `audit_hash` determinístico (SHA-256),
  e grava em collection separada que SOBREVIVE a qualquer reset.

DECISÕES (CEO 16/02/2026):
  1c = Híbrido — motivos hardcoded por enquanto, migra pra collection
       (`destructive_reason_catalog`) na Onda 2.
  2a = Snapshot completo SEMPRE (sem amostragem, sem checksum). Patrimônio
       não economiza evidência.
  3a = Sequencial 1.1 → 1.2 → 1.3 → 1.4. Este arquivo é o 1.1.

REGRAS DE NEGÓCIO:
  - `reason.code` deve estar em `DESTRUCTIVE_REASONS` (9 valores).
  - Se `reason.code == "Outro"`, `reason.details` é OBRIGATÓRIO e ≥ 20 chars.
  - `before_snapshot.docs` deve conter dump COMPLETO dos documentos antes do
    delete (NÃO apenas contagens).
  - `after_snapshot.counts` deve ser preenchido APÓS a execução (chamada
    de duas etapas: `record_destructive_action(...)` retorna o doc gravado,
    o caller depois chama `attach_after_snapshot(audit_id, after_counts)`).
  - Collection física: `destructive_actions_audit` — não é apagada por
    nenhum reset (mesmo padrão de `stok_admin_log`, que sobreviveu).

NADA AQUI MUDA COMPORTAMENTO DE CÓDIGO QUE LÊ `stok_admin_log` OU
`purchases_deletion_audit`. Este é um sistema NOVO de auditoria.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db


# ═══════════ Constantes canônicas ════════════════════════════════════════════

PHYSICAL_COLLECTION = "destructive_actions_audit"

# Whitelist absoluta de tipos de ação destrutiva.
ACTION_TYPES = {
    "stok_reset_full",          # POST /api/stok/admin/reset
    "stok_reset_granular",      # POST /api/stok/admin/reset-granular
    "scrap_ont",                # POST /api/stok-transfers/defective-onts/{mac}/scrap
    "revert_defective_ont",     # POST /api/stok-transfers/defective-onts/{mac}/revert
    "delete_purchase",          # DELETE /api/purchases/{id}
    "batch_delete_purchases",   # POST /api/purchases/batch-delete
    "wipe_tickets",             # POST /api/lousa/tickets/wipe-all
    "revert_purchase_stock",    # _revert_purchase_stock_impact helper
}

# Tabela de motivos pré-definidos (CEO 16/02/2026 — decisão 1c, hardcoded).
DESTRUCTIVE_REASONS = (
    "Inventário incorreto",
    "Equipamento defeituoso",
    "Equipamento condenado",
    "Devolução fornecedor",
    "Erro operacional",
    "Duplicidade de cadastro",
    "Correção de auditoria",
    "Determinação diretoria",
    "Outro",
)

# Quando reason.code == "Outro", details deve ter este mínimo.
MIN_REASON_DETAILS_LENGTH = 20


class DestructiveAuditError(ValueError):
    """Erro de validação da auditoria destrutiva."""


# ═══════════ Helpers internos ════════════════════════════════════════════════

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit_hash(record: Dict[str, Any]) -> str:
    """SHA-256 determinístico sobre os campos críticos.

    Campos incluídos: action_type, company_id, executed_by.id, executed_at,
    scope (canonicalizado), reason.code, before_snapshot.doc_ids.

    NÃO inclui o snapshot completo (poderia ser MB) — apenas os IDs dos
    docs afetados são suficientes para hash forense.
    """
    bs = record.get("before_snapshot") or {}
    docs = bs.get("docs") or []
    # IDs dos docs (ou MAC/SN como fallback)
    doc_ids = []
    for d in docs:
        if isinstance(d, dict):
            ident = (d.get("id") or d.get("mac") or d.get("scan_sn")
                     or d.get("sn") or "")
            doc_ids.append(str(ident))
    doc_ids.sort()

    canon = json.dumps({
        "action_type": record.get("action_type"),
        "company_id": record.get("company_id"),
        "executed_by_id": (record.get("executed_by") or {}).get("id"),
        "executed_at": record.get("executed_at"),
        "scope": record.get("scope"),
        "reason_code": (record.get("reason") or {}).get("code"),
        "before_doc_ids": doc_ids,
    }, sort_keys=True, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


# ═══════════ Validação ═══════════════════════════════════════════════════════

def _validate_reason(reason: Optional[Dict[str, Any]]) -> None:
    if not reason or not isinstance(reason, dict):
        raise DestructiveAuditError("reason é obrigatório (dict)")
    code = (reason.get("code") or "").strip()
    if not code:
        raise DestructiveAuditError(
            f"reason.code é obrigatório. Use um de: {list(DESTRUCTIVE_REASONS)}"
        )
    if code not in DESTRUCTIVE_REASONS:
        raise DestructiveAuditError(
            f"reason.code inválido: {code!r}. "
            f"Permitidos: {list(DESTRUCTIVE_REASONS)}"
        )
    if code == "Outro":
        details = (reason.get("details") or "").strip()
        if len(details) < MIN_REASON_DETAILS_LENGTH:
            raise DestructiveAuditError(
                f"Quando reason.code='Outro', reason.details é obrigatório "
                f"com mínimo {MIN_REASON_DETAILS_LENGTH} caracteres. "
                f"Recebido: {len(details)} chars."
            )


def _validate_executed_by(executed_by: Optional[Dict[str, Any]]) -> None:
    if executed_by is None or not isinstance(executed_by, dict):
        raise DestructiveAuditError("executed_by é obrigatório (dict)")
    eid = executed_by.get("id")
    email = executed_by.get("email")
    if not eid and not email:
        raise DestructiveAuditError(
            "executed_by precisa ter ao menos `id` OU `email`"
        )


def _validate_snapshot(snapshot: Optional[Dict[str, Any]], *,
                        require_docs: bool) -> None:
    if not snapshot or not isinstance(snapshot, dict):
        raise DestructiveAuditError("before_snapshot é obrigatório (dict)")
    if require_docs:
        docs = snapshot.get("docs")
        counts = snapshot.get("counts")
        if not docs and not counts:
            raise DestructiveAuditError(
                "before_snapshot precisa ter `docs` (dump completo) "
                "OU `counts` (operação sem entidades específicas)"
            )


def validate_record(record: Dict[str, Any]) -> None:
    """Valida um registro destrutivo ANTES da gravação.

    Regras:
      - action_type ∈ ACTION_TYPES
      - company_id obrigatório
      - executed_by com id ou email
      - reason válido (código + details se "Outro")
      - before_snapshot presente (docs OU counts)
      - executed_at preenchido (ISO)
    """
    at = record.get("action_type")
    if at not in ACTION_TYPES:
        raise DestructiveAuditError(
            f"action_type inválido: {at!r}. "
            f"Permitidos: {sorted(ACTION_TYPES)}"
        )
    if not record.get("company_id"):
        raise DestructiveAuditError("company_id é obrigatório")
    if not record.get("executed_at"):
        raise DestructiveAuditError("executed_at é obrigatório")
    _validate_executed_by(record.get("executed_by"))
    _validate_reason(record.get("reason"))
    _validate_snapshot(record.get("before_snapshot"), require_docs=True)


# ═══════════ API pública ═════════════════════════════════════════════════════

async def record_destructive_action(
    *,
    company_id: str,
    action_type: str,
    reason: Dict[str, Any],          # {"code": "...", "details": "..."}
    executed_by: Dict[str, Any],     # {"id", "email", "name", "role"}
    before_snapshot: Dict[str, Any], # {"docs": [...], "counts": {...}}
    scope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Grava o registro destrutivo ANTES da execução.

    Args:
      company_id: tenant alvo.
      action_type: um de ACTION_TYPES.
      reason: {"code": <um de DESTRUCTIVE_REASONS>, "details": <livre>}.
              Se code=="Outro", details é obrigatório com >= 20 chars.
      executed_by: ator. Precisa de id ou email.
      before_snapshot: estado ANTES do delete. `docs` deve conter dump completo
                       dos documentos a serem afetados. `counts` é metadado.
      scope: filtros/parâmetros usados (ex.: {"target_id":..., "scope":"praca"}).

    Returns:
      Doc gravado com `audit_id`, `audit_hash`, `created_at`.

    Raises:
      DestructiveAuditError em qualquer violação de schema/regra.
    """
    record = {
        "id": f"dest-{uuid.uuid4().hex[:14]}",
        "action_type": action_type,
        "company_id": company_id,
        "executed_at": _now_iso(),
        "executed_by": dict(executed_by),
        "reason": dict(reason),
        "scope": dict(scope or {}),
        "before_snapshot": dict(before_snapshot),
        "after_snapshot": None,   # preenchido depois via attach_after_snapshot
        "after_attached_at": None,
        "created_at": _now_iso(),
    }
    validate_record(record)
    record["audit_hash"] = _audit_hash(record)
    record["audit_id"] = record["id"]
    await db[PHYSICAL_COLLECTION].insert_one(dict(record))
    return record


async def attach_after_snapshot(
    audit_id: str,
    after_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """Anexa o `after_snapshot` ao registro destrutivo após a execução.

    Chamado IMEDIATAMENTE depois da operação. Recebe contagens reais
    pós-execução (não dump — após delete os docs sumiram).

    Args:
      audit_id: o `audit_id` retornado por `record_destructive_action`.
      after_snapshot: {"counts": {...}, "delta": {...}, "verified_at": iso}.

    Returns:
      Doc atualizado.
    """
    if not isinstance(after_snapshot, dict):
        raise DestructiveAuditError("after_snapshot deve ser dict")
    after_snapshot = dict(after_snapshot)
    after_snapshot.setdefault("verified_at", _now_iso())
    res = await db[PHYSICAL_COLLECTION].update_one(
        {"id": audit_id},
        {"$set": {
            "after_snapshot": after_snapshot,
            "after_attached_at": _now_iso(),
        }},
    )
    if res.matched_count == 0:
        raise DestructiveAuditError(
            f"audit_id não encontrado: {audit_id!r}"
        )
    return await db[PHYSICAL_COLLECTION].find_one(
        {"id": audit_id}, {"_id": 0}
    )


async def find_destructive_actions(
    filter: Dict[str, Any],
    *,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Lê ações destrutivas (read-only, ordenadas por executed_at desc)."""
    cur = db[PHYSICAL_COLLECTION].find(filter, {"_id": 0}).sort(
        "executed_at", -1).limit(limit)
    return [d async for d in cur]


async def count_destructive_actions(filter: Dict[str, Any]) -> int:
    return await db[PHYSICAL_COLLECTION].count_documents(filter)
