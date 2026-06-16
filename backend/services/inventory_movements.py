"""
services/inventory_movements.py — CTO 16/02/2026 — Fase 2 (Movimento Único).

Contrato canônico de movimentação operacional do estoque.

DECISÕES (CEO/CTO):
  D1=b  Mantém collection física `inventory_os_movements_audit`.
         Este módulo expõe alias lógico `inventory_movements` como contrato
         canônico. Nenhuma migração de dados.
  D3=a  Bloqueia movimentação de ONT com SN auto-gerado (AUTOSN_*),
         "REAL-LABEL-*-FIXED" ou SN ausente. Mensagem clara, sem auto-fix.

REGRA MESTRA:
  Nenhuma movimentação pode ser gravada FORA deste helper. Toda escrita
  passa por `write_movement(...)` que valida schema, blocklist e duplica
  campos canonical↔legacy.

Nada aqui muda comportamento do código que LÊ `inventory_os_movements_audit`.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db


# ═══════════ Constantes canônicas ════════════════════════════════════════════

# Nome físico (D1=b — não mudar). Use `LOGICAL_NAME` quando referir
# arquiteturalmente ao contrato.
PHYSICAL_COLLECTION = "inventory_os_movements_audit"
LOGICAL_NAME = "inventory_movements"

# Tipos de movimento permitidos (whitelist absoluta).
MOVEMENT_TYPES = {
    # ───── Movimentos físicos por OS ─────
    "auto_pull_empresa_tecnico",
    "instalacao_tecnico_cliente",
    "troca_entrega_tecnico_cliente",
    "retirada_cliente_tecnico",
    "troca_devolucao_cliente_tecnico",
    # ───── Movimentos administrativos ─────
    "admin_close_no_movement",
    "blocked_attempt",
    # ───── Reconciliação (worker) ─────
    "reconciliation_smartolt_sync",
    # ───── Manuais (gestor com motivo) ─────
    "manual_transfer_empresa_tecnico",
    "manual_transfer_tecnico_empresa",
    "defect_returned_to_empresa",
    "disposal",
    # ───── Reabertura de OS (Onda 0d) — reverte fechamento anterior ─────
    "ticket_reopen_revert",
}

# Tipos de owner permitidos.
OWNER_TYPES = {"empresa", "tecnico", "cliente", "defeito", "descarte"}

# Padrão de SN não-confiável (D3=a). Bloqueio absoluto até re-scan.
# Re-scan substitui scan_sn no doc do estoque e remove sn_auto_generated.
_BLOCKED_SN_PATTERNS = [
    re.compile(r"^AUTOSN_", re.IGNORECASE),
    re.compile(r"^REAL-LABEL-.*-FIXED$", re.IGNORECASE),
]


class InventoryMovementError(ValueError):
    """Erro de validação do contrato lógico inventory_movements."""


# ═══════════ Helpers internos ════════════════════════════════════════════════

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_sn_blocked(sn: Optional[str]) -> bool:
    """D3=a — SN auto-gerado ou padrão temporário. Bloqueio até re-scan."""
    if not sn:
        return False  # sem SN = outro código de validação trata
    s = str(sn).strip()
    if not s:
        return False
    return any(p.match(s) for p in _BLOCKED_SN_PATTERNS)


def explain_sn_blocked(sn: Optional[str]) -> str:
    return (
        f"Equipamento sem SN confiável (sn={sn!r}). "
        "Re-scan obrigatório antes da movimentação."
    )


# ═══════════ Validação de schema ═════════════════════════════════════════════

REQUIRED_FIELDS_BY_TYPE = {
    # admin_close não exige sn/mac (não há movimento físico)
    "admin_close_no_movement": {
        "os_id", "ticket_id", "movement_type", "audit_hash",
        "actor_id", "company_id",
    },
    # blocked_attempt registra a tentativa (não exige owner — falhou)
    "blocked_attempt": {
        "os_id", "ticket_id", "movement_type", "audit_hash",
        "blocked_reasons", "company_id",
    },
}

# Movimentos físicos (todos os outros) — exigem owner + SN/MAC.
_PHYSICAL_REQUIRED = {
    "os_id", "movement_type", "audit_hash",
    "origin_type", "destination_type",
    "company_id",
}


def validate_movement(record: Dict[str, Any]) -> None:
    """Valida o schema lógico ANTES de gravar. Levanta InventoryMovementError.

    Regras:
      - movement_type ∈ MOVEMENT_TYPES
      - origin_type/destination_type ∈ OWNER_TYPES (quando físico)
      - SN ou MAC obrigatório quando movimento físico (não admin/blocked)
      - SN não pode estar na blocklist (AUTOSN_*) — D3=a
      - audit_hash obrigatório (64 chars hex de SHA-256)
      - confidence opcional MAS se presente deve ser 0..1
    """
    mtype = record.get("movement_type")
    if mtype not in MOVEMENT_TYPES:
        raise InventoryMovementError(
            f"movement_type inválido: {mtype!r}. "
            f"Permitidos: {sorted(MOVEMENT_TYPES)}"
        )

    required = REQUIRED_FIELDS_BY_TYPE.get(mtype, _PHYSICAL_REQUIRED)
    missing = [k for k in required if not record.get(k)]
    if missing:
        raise InventoryMovementError(
            f"Campos obrigatórios ausentes em {mtype}: {missing}"
        )

    # audit_hash deve ser SHA-256 hex (64 chars)
    h = record.get("audit_hash") or ""
    if not isinstance(h, str) or len(h) != 64 or not re.fullmatch(
            r"[0-9a-f]{64}", h):
        raise InventoryMovementError(
            f"audit_hash inválido: precisa ser SHA-256 hex (64 chars). "
            f"Recebido: {h!r}"
        )

    # owner types (físicos)
    if mtype not in ("admin_close_no_movement", "blocked_attempt"):
        ot = record.get("origin_type")
        dt = record.get("destination_type")
        if ot not in OWNER_TYPES:
            raise InventoryMovementError(
                f"origin_type inválido: {ot!r}. "
                f"Permitidos: {sorted(OWNER_TYPES)}"
            )
        if dt not in OWNER_TYPES:
            raise InventoryMovementError(
                f"destination_type inválido: {dt!r}. "
                f"Permitidos: {sorted(OWNER_TYPES)}"
            )
        # SN OU MAC obrigatório
        if not record.get("sn") and not record.get("mac"):
            raise InventoryMovementError(
                "SN OU MAC obrigatório em movimento físico."
            )
        # D3=a — bloquear SN não-confiável
        sn = record.get("sn")
        if is_sn_blocked(sn):
            raise InventoryMovementError(explain_sn_blocked(sn))

    # confidence opcional, range 0..1
    if "confidence" in record and record["confidence"] is not None:
        c = record["confidence"]
        if not isinstance(c, (int, float)) or not (0.0 <= float(c) <= 1.0):
            raise InventoryMovementError(
                f"confidence inválido: {c!r} (precisa 0..1)"
            )


# ═══════════ Canonical → Physical mapping ════════════════════════════════════

def _to_physical(record: Dict[str, Any]) -> Dict[str, Any]:
    """Converte um movimento canônico em doc físico.

    Mantém os nomes legacy (origin_owner/destination_owner/hash_auditoria/id)
    PARA NÃO QUEBRAR LEITURAS já existentes, e adiciona os nomes canônicos
    (origin_type/destination_type/audit_hash/movement_id) lado a lado.
    """
    doc = dict(record)
    # IDs
    if "movement_id" in doc and "id" not in doc:
        doc["id"] = doc["movement_id"]
    elif "id" in doc and "movement_id" not in doc:
        doc["movement_id"] = doc["id"]
    # Hash
    if "audit_hash" in doc and "hash_auditoria" not in doc:
        doc["hash_auditoria"] = doc["audit_hash"]
    elif "hash_auditoria" in doc and "audit_hash" not in doc:
        doc["audit_hash"] = doc["hash_auditoria"]
    # Owner naming compat (legacy ↔ canonical)
    if "origin_type" in doc and "origin_owner" not in doc:
        doc["origin_owner"] = doc["origin_type"]
    elif "origin_owner" in doc and "origin_type" not in doc:
        doc["origin_type"] = doc["origin_owner"]
    if "destination_type" in doc and "destination_owner" not in doc:
        doc["destination_owner"] = doc["destination_type"]
    elif "destination_owner" in doc and "destination_type" not in doc:
        doc["destination_type"] = doc["destination_owner"]
    return doc


# ═══════════ API pública (contrato canônico) ═════════════════════════════════

async def write_movement(record: Dict[str, Any]) -> Dict[str, Any]:
    """Grava UM movimento operacional na collection física, validando o
    contrato canônico. Esta é a ÚNICA porta de escrita autorizada.

    Args:
      record: dict com pelo menos:
        os_id, movement_type, audit_hash, company_id, [origin_type,
        destination_type, sn|mac, ...]

    Returns:
      O doc físico gravado (já com `id`, `movement_id`, `created_at`).

    Raises:
      InventoryMovementError em qualquer violação de schema/blocklist.
    """
    record = dict(record)
    record.setdefault("movement_id", f"invmov-{uuid.uuid4().hex[:14]}")
    record.setdefault("created_at", _now_iso())

    validate_movement(record)

    doc = _to_physical(record)
    await db[PHYSICAL_COLLECTION].insert_one(dict(doc))
    return doc


async def write_movements_bulk(records: List[Dict[str, Any]]) -> List[str]:
    """Grava várias movimentações em sequência (uma OS pode gerar 2+
    movimentos: ex.: troca = devolução + entrega). Retorna a lista de
    `audit_hash` gravados na ordem.

    Falha atômica: se UMA falhar, NENHUMA é gravada (validação prévia).
    """
    # Pré-valida TODAS antes de gravar (atomicidade lógica)
    normalized = []
    for r in records:
        r = dict(r)
        r.setdefault("movement_id", f"invmov-{uuid.uuid4().hex[:14]}")
        r.setdefault("created_at", _now_iso())
        validate_movement(r)
        normalized.append(_to_physical(r))

    if not normalized:
        return []
    await db[PHYSICAL_COLLECTION].insert_many([dict(d) for d in normalized])
    return [d["audit_hash"] for d in normalized]


async def find_movements(filter: Dict[str, Any], *, limit: int = 100,
                          sort_field: str = "created_at",
                          sort_direction: int = -1) -> List[Dict[str, Any]]:
    """Lê movimentações da collection física (alias lógico de leitura)."""
    cur = db[PHYSICAL_COLLECTION].find(filter, {"_id": 0}).sort(
        sort_field, sort_direction).limit(limit)
    return [d async for d in cur]


async def count_movements(filter: Dict[str, Any]) -> int:
    return await db[PHYSICAL_COLLECTION].count_documents(filter)
