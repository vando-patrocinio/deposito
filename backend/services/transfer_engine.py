"""
services/transfer_engine.py — CTO 16/02/2026 — ONDA 2.1 (Transferências).

Contrato canônico para QUALQUER transferência de owner de ONT/equipamento.

REGRA MESTRA (decisão CEO 16/02/2026):
  Nenhuma rota pode mais escrever direto em `stok_onts` para mudar
  `location_type` / `location_id` / `status`. Todas devem passar por
  `execute_transfer(...)`. O helper:
    1. Valida `reason` OBRIGATÓRIO (decisão C).
    2. Valida transição permitida pelo grafo (§2 TRANSFER_FLOW_MATRIX.md).
    3. Bloqueia AUTOSN_* (D3=a) automaticamente via inventory_movements.
    4. Grava trilha em `inventory_os_movements_audit` com audit_hash SHA-256.
    5. Atualiza `stok_onts` em transação lógica (write_movement + update_one).
    6. Retorna {movement_id, audit_hash, before, after}.

DECISÕES CEO:
  A = Plano §5 aprovado.
  B = Backfill sintético em collection SEPARADA `inventory_movements_synthetic_backfill`.
      (Implementado por função separada `record_synthetic_backfill`, NUNCA polui a
      trilha real.)
  C = `reason` obrigatório. Sem reason → DestructiveAuditError → HTTP 400.
  D = Cleanup `stok_history.action=null` é backlog separado (NÃO toca aqui).

REUTILIZA:
  - `services.inventory_movements.write_movement` (motor canônico).
  - `services.destructive_audit.DESTRUCTIVE_REASONS` (filosofia compatível).

NÃO REUTILIZA:
  - `DESTRUCTIVE_REASONS` — transferências têm motivos próprios (operacionais).
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import HTTPException

from database import db

logger = logging.getLogger("transfer_engine")


# ═══════════ ContextVar — rastreia chamadas de execute_transfer ════════════
# Garantia arquitetural: o decorator @requires_transfer_audit valida que a
# rota chamou execute_transfer() ao menos 1x durante o request. Caso
# contrário, retorna HTTP 400. Isolado por request via ContextVar.
_transfer_audit_calls: ContextVar[Optional[List[Dict[str, Any]]]] = ContextVar(
    "_transfer_audit_calls", default=None,
)


# ═══════════ Constantes canônicas ════════════════════════════════════════════

# Whitelist absoluta de tipos de transferência. Sincronizada com
# `services/inventory_movements.MOVEMENT_TYPES` (não duplica — apenas
# documenta os tipos que ESTE engine usa).
TRANSFER_MOVEMENT_TYPES = {
    "auto_pull_empresa_tecnico",
    "manual_transfer_empresa_tecnico",
    "manual_transfer_tecnico_empresa",
    "instalacao_tecnico_cliente",
    "retirada_cliente_tecnico",
    "defect_returned_to_empresa",
    "reconciliation_smartolt_sync",
    "disposal",
}

# Motivos operacionais de transferência (decisão CEO 16/02 — OBRIGATÓRIO).
# Diferente de DESTRUCTIVE_REASONS porque o universo operacional é distinto:
# aqui não há "Equipamento condenado"; lá não há "Instalação".
TRANSFER_REASONS = (
    "Instalação OS",                # via guardrail (lousa)
    "Retirada OS",                  # via guardrail (lousa)
    "Troca de equipamento",         # via guardrail (lousa)
    "Saída pra campo",              # gestor → técnico
    "Devolução estoque",            # técnico → empresa
    "Reconciliação SmartOLT",       # sync com OLT
    "Reposição em campo",           # técnico recebe ONT em rota
    "Marca como defeito",           # técnico → defeito
    "Confirmação defeito",          # técnico → empresa (devolveu defeituosa)
    "Regularização manual",         # gestor faz fora de OS — exige details
    "Outro",                        # exige details ≥ 20 chars
)

# Quando reason.code == "Outro" OU "Regularização manual", details obrigatório
MIN_REASON_DETAILS_LENGTH = 20
REASON_CODES_REQUIRING_DETAILS = {"Outro", "Regularização manual"}

# Grafo de transições permitidas → mapeia (origin, destination) para o
# movement_type CANÔNICO já existente em `inventory_movements.MOVEMENT_TYPES`.
# Reutiliza os nomes legados pra zero mudança no whitelist canônico.
ALLOWED_TRANSITIONS: Dict[Tuple[str, str], str] = {
    ("empresa", "tecnico"):  "auto_pull_empresa_tecnico",
    ("tecnico", "empresa"):  "defect_returned_to_empresa",  # operacional via retorno
    ("tecnico", "cliente"):  "instalacao_tecnico_cliente",
    ("cliente", "tecnico"):  "retirada_cliente_tecnico",
    ("tecnico", "defeito"):  "defect_returned_to_empresa",  # fluxo defeito
    ("defeito", "empresa"):  "defect_returned_to_empresa",
}

# Manual override: gestor sem OS → usa os tipos `manual_*`.
MANUAL_TRANSITIONS: Dict[Tuple[str, str], str] = {
    ("empresa", "tecnico"):  "manual_transfer_empresa_tecnico",
    ("tecnico", "empresa"):  "manual_transfer_tecnico_empresa",
}

# Reconciliação SmartOLT (Onda 2.8 — decisão CEO 16/02/2026).
# Exceção controlada: o equipamento está fisicamente no cliente conforme OLT,
# mas o banco mostra estoque (empresa/tecnico). NÃO é instalação real — é
# correção de verdade cadastral. Não conta produtividade. Source obrigatório
# = "smartolt_reconcile". Snapshot SmartOLT obrigatório.
RECONCILIATION_TRANSITIONS: Dict[Tuple[str, str], str] = {
    ("empresa", "cliente"):  "reconciliation_smartolt_sync",
    ("tecnico", "cliente"):  "reconciliation_smartolt_sync",
}
RECONCILIATION_REASON_CODE = "Reconciliação SmartOLT"
RECONCILIATION_SOURCE = "smartolt_reconcile"

# Collection separada para backfill sintético (decisão B do CEO).
# JAMAIS escrever na collection real `inventory_os_movements_audit` por engano.
SYNTHETIC_BACKFILL_COLLECTION = "inventory_movements_synthetic_backfill"


class TransferEngineError(ValueError):
    """Erro de validação de transferência."""


# ═══════════ Validação ═══════════════════════════════════════════════════════

def _validate_reason(reason: Optional[Dict[str, Any]]) -> None:
    """`reason` é OBRIGATÓRIO (decisão CEO C)."""
    if not reason or not isinstance(reason, dict):
        raise TransferEngineError(
            "reason é obrigatório (decisão CEO Onda 2). "
            f"Use um de: {list(TRANSFER_REASONS)}"
        )
    code = (reason.get("code") or "").strip()
    if not code:
        raise TransferEngineError(
            f"reason.code é obrigatório. Permitidos: {list(TRANSFER_REASONS)}"
        )
    if code not in TRANSFER_REASONS:
        raise TransferEngineError(
            f"reason.code inválido: {code!r}. "
            f"Permitidos: {list(TRANSFER_REASONS)}"
        )
    if code in REASON_CODES_REQUIRING_DETAILS:
        details = (reason.get("details") or "").strip()
        if len(details) < MIN_REASON_DETAILS_LENGTH:
            raise TransferEngineError(
                f"reason.code={code!r} exige reason.details com "
                f"≥{MIN_REASON_DETAILS_LENGTH} chars. Got {len(details)}."
            )


def _validate_actor(actor: Optional[Dict[str, Any]]) -> None:
    if actor is None or not isinstance(actor, dict):
        raise TransferEngineError("actor é obrigatório (dict)")
    if not actor.get("id") and not actor.get("email"):
        raise TransferEngineError("actor precisa de `id` OU `email`")


def _resolve_movement_type(
    origin_type: str, destination_type: str,
    manual: bool = False, is_reconciliation: bool = False,
) -> str:
    """Retorna movement_type canônico. Bloqueia transições proibidas."""
    key = (origin_type, destination_type)
    if is_reconciliation:
        if key not in RECONCILIATION_TRANSITIONS:
            raise TransferEngineError(
                f"Transição de reconciliação não permitida: "
                f"{origin_type} → {destination_type}. "
                f"Reconciliação permite apenas: "
                f"{sorted(RECONCILIATION_TRANSITIONS.keys())}"
            )
        return RECONCILIATION_TRANSITIONS[key]
    if key not in ALLOWED_TRANSITIONS:
        raise TransferEngineError(
            f"Transição não permitida: {origin_type} → {destination_type}. "
            f"Grafo permite: {sorted(ALLOWED_TRANSITIONS.keys())}"
        )
    if manual and key in MANUAL_TRANSITIONS:
        return MANUAL_TRANSITIONS[key]
    return ALLOWED_TRANSITIONS[key]


# ═══════════ Helpers ═════════════════════════════════════════════════════════

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_audit_hash(record: Dict[str, Any]) -> str:
    canon = json.dumps({
        "movement_type": record.get("movement_type"),
        "company_id": record.get("company_id"),
        "sn": record.get("sn"),
        "mac": record.get("mac"),
        "origin_type": record.get("origin_type"),
        "origin_id": record.get("origin_id"),
        "destination_type": record.get("destination_type"),
        "destination_id": record.get("destination_id"),
        "actor_id": (record.get("actor") or {}).get("id"),
        "reason_code": (record.get("reason") or {}).get("code"),
        "ticket_id": record.get("ticket_id"),
        "performed_at": record.get("performed_at"),
    }, sort_keys=True, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


async def _resolve_ont(
    *, company_id: str, mac: Optional[str], sn: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Localiza ONT por MAC (preferencial) ou SN."""
    if mac:
        ont = await db.stok_onts.find_one(
            {"company_id": company_id, "mac": mac}, {"_id": 0})
        if ont:
            return ont
    if sn:
        ont = await db.stok_onts.find_one(
            {"company_id": company_id, "scan_sn": sn}, {"_id": 0})
        if ont:
            return ont
    return None


# ═══════════ API PÚBLICA ═════════════════════════════════════════════════════

async def execute_transfer(
    *,
    company_id: str,
    origin_type: str,
    origin_id: Optional[str],
    destination_type: str,
    destination_id: Optional[str],
    actor: Dict[str, Any],
    reason: Dict[str, Any],
    mac: Optional[str] = None,
    sn: Optional[str] = None,
    ticket_id: Optional[str] = None,
    manual: bool = False,
    is_reconciliation: bool = False,
    smartolt_snapshot: Optional[Dict[str, Any]] = None,
    extra_set_fields: Optional[Dict[str, Any]] = None,
    extra_unset_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Executa uma transferência canônica.

    Sequência:
      1. Valida reason + actor + transição.
      2. Localiza ONT por mac/sn.
      3. Grava em `inventory_os_movements_audit` (via write_movement).
      4. Update_one em `stok_onts` (location_type/id/status).
      5. Retorna {movement_id, audit_hash, before, after}.

    Modo `is_reconciliation=True` (Onda 2.8 — exceção SmartOLT):
      - reason.code DEVE ser "Reconciliação SmartOLT".
      - smartolt_snapshot OBRIGATÓRIO (dict com pelo menos `pppoe_user` ou `olt_name`).
      - Marca o movimento com `is_reconciliation=True`, `source="smartolt_reconcile"`.
      - NÃO conta como instalação/produtividade do técnico (flag explícita).

    Idempotente: re-chamadas com mesmo (sn, mac, movement_type, actor_id,
    ticket_id) produzem mesmo audit_hash → write_movement rejeita duplicata.

    Raises:
      TransferEngineError em qualquer violação.
    """
    # 1. Validações
    _validate_reason(reason)
    _validate_actor(actor)
    if is_reconciliation:
        rcode = (reason.get("code") or "").strip()
        if rcode != RECONCILIATION_REASON_CODE:
            raise TransferEngineError(
                f"is_reconciliation=True exige reason.code="
                f"{RECONCILIATION_REASON_CODE!r}. Got {rcode!r}.")
        if not smartolt_snapshot or not isinstance(smartolt_snapshot, dict):
            raise TransferEngineError(
                "is_reconciliation=True exige smartolt_snapshot (dict) "
                "com pelo menos pppoe_user OU olt_name.")
        if not (smartolt_snapshot.get("pppoe_user")
                or smartolt_snapshot.get("olt_name")):
            raise TransferEngineError(
                "smartolt_snapshot deve conter pppoe_user OU olt_name "
                "(prova de que a ONT está ativa na OLT).")
    movement_type = _resolve_movement_type(
        origin_type, destination_type,
        manual=manual, is_reconciliation=is_reconciliation,
    )

    if not mac and not sn:
        raise TransferEngineError("Informe `mac` ou `sn` para identificar a ONT")

    # 2. Localiza ONT
    ont = await _resolve_ont(company_id=company_id, mac=mac, sn=sn)
    if not ont:
        raise TransferEngineError(
            f"ONT não encontrada (company={company_id}, mac={mac}, sn={sn})")
    mac_final = ont.get("mac") or mac
    sn_final = ont.get("scan_sn") or sn

    # 3. Snapshot pré-mudança (before)
    before = {
        "location_type": ont.get("location_type"),
        "location_id": ont.get("location_id"),
        "status": ont.get("status"),
        "client_name": ont.get("client_name"),
    }

    # 4. Monta registro canônico para inventory_movements.
    # Schema canônico exige `os_id` em movimentos físicos. Para
    # transferências SEM OS (gestor faz movimento operacional direto),
    # gera um id virtual `mantr-<uuid>` que indica "manual transfer".
    performed_at = _now_iso()
    movement_id = f"mov-{uuid.uuid4().hex[:14]}"
    os_id_for_movement = ticket_id or f"mantr-{uuid.uuid4().hex[:12]}"
    record = {
        "id": movement_id,
        "movement_id": movement_id,
        "os_id": os_id_for_movement,
        "ticket_id": ticket_id,
        "company_id": company_id,
        "movement_type": movement_type,
        "origin_type": origin_type,
        "destination_type": destination_type,
        "origin_owner": origin_type,
        "destination_owner": destination_type,
        "origin_id": origin_id,
        "destination_id": destination_id,
        "client_id": (destination_id if destination_type == "cliente"
                       else origin_id if origin_type == "cliente" else None),
        "technician_id": (destination_id if destination_type == "tecnico"
                           else origin_id if origin_type == "tecnico" else None),
        "equipment_id": ont.get("id"),
        "sn": sn_final,
        "mac": mac_final,
        "actor_id": actor.get("id"),
        "actor_name": actor.get("name") or actor.get("email"),
        "actor_email": actor.get("email"),
        "actor_role": actor.get("role"),
        "actor_origin": actor.get("origin") or "transfer_engine",
        "reason": dict(reason),
        "performed_at": performed_at,
        "physical_attendance": bool(actor.get("physical_attendance", False)),
    }
    if is_reconciliation:
        record["is_reconciliation"] = True
        record["source"] = RECONCILIATION_SOURCE
        record["counts_as_install"] = False
        record["counts_for_tech_productivity"] = False
        record["smartolt_snapshot"] = dict(smartolt_snapshot or {})
    record["audit_hash"] = _compute_audit_hash(record)

    # 5. Persistir trilha (write_movement faz validação extra: D3=a AUTOSN_*)
    from services.inventory_movements import write_movement, InventoryMovementError
    try:
        await write_movement(record)
    except InventoryMovementError as e:
        raise TransferEngineError(f"inventory_movements rejeitou: {e}")

    # 6. Atualizar stok_onts
    # Status pós-transferência segue regra simples baseada em destination_type.
    status_by_destination = {
        "empresa":  "retornada_empresa",
        "tecnico":  "com_tecnico",
        "cliente":  "instalada",
        "defeito":  "defeito_em_analise",
        "descarte": "sucateada",
    }
    new_status = status_by_destination.get(destination_type, ont.get("status"))
    set_fields = {
        "location_type": destination_type,
        "location_id": destination_id,
        "status": new_status,
        "last_transfer_id": movement_id,
        "last_transfer_hash": record["audit_hash"],
        "last_transfer_at": performed_at,
    }
    # Para destino=cliente, propaga client_name; pra outros, limpa.
    if destination_type == "cliente":
        set_fields["client_name"] = (actor.get("client_name")
                                       or ont.get("client_name"))
    else:
        set_fields["client_name"] = None
    if extra_set_fields:
        set_fields.update(extra_set_fields)

    update_doc: Dict[str, Any] = {"$set": set_fields}
    if extra_unset_fields:
        update_doc["$unset"] = {k: "" for k in extra_unset_fields}

    # Preferencialmente por id (canônico). Fallback por MAC (legado).
    if ont.get("id"):
        filt = {"id": ont["id"], "company_id": company_id}
    else:
        filt = {"mac": mac_final, "company_id": company_id}
    await db.stok_onts.update_one(filt, update_doc)

    after = {**before, **set_fields}
    result = {
        "movement_id": movement_id,
        "audit_hash": record["audit_hash"],
        "movement_type": movement_type,
        "before": before,
        "after": {k: after.get(k) for k in
                   ("location_type", "location_id", "status", "client_name")},
        "performed_at": performed_at,
    }
    # Registra na ContextVar (consumida pelo decorator @requires_transfer_audit)
    _slot = _transfer_audit_calls.get()
    if _slot is not None:
        _slot.append({
            "movement_id": movement_id,
            "audit_hash": record["audit_hash"],
            "movement_type": movement_type,
        })
    return result


# ═══════════ Backfill sintético (decisão B = B1) ═════════════════════════════

async def record_synthetic_backfill(
    *,
    company_id: str,
    ont: Dict[str, Any],
    inferred_movement_type: str,
    reason_note: str,
    operator_email: str,
) -> Dict[str, Any]:
    """Grava 1 trilha SINTÉTICA para uma ONT órfã.

    Collection: `inventory_movements_synthetic_backfill` (separada — NUNCA
    polui `inventory_os_movements_audit`).

    Marca `is_synthetic=True` no doc. A Watchtower deve filtrar por padrão.

    Não chama `write_movement` (que validaria contra a real). Grava direto
    na collection sintética com schema próprio.
    """
    if not reason_note or len(reason_note.strip()) < MIN_REASON_DETAILS_LENGTH:
        raise TransferEngineError(
            f"reason_note do backfill exige ≥{MIN_REASON_DETAILS_LENGTH} chars")

    rec = {
        "id": f"synth-{uuid.uuid4().hex[:12]}",
        "is_synthetic": True,
        "company_id": company_id,
        "movement_type": inferred_movement_type,
        "destination_type": ont.get("location_type"),
        "destination_id": ont.get("location_id"),
        "destination_owner": ont.get("location_type"),
        "sn": ont.get("scan_sn"),
        "mac": ont.get("mac"),
        "equipment_id": ont.get("id"),
        "client_name": ont.get("client_name"),
        "actor_email": operator_email,
        "actor_origin": "synthetic_backfill_onda2",
        "reason": {"code": "Regularização manual",
                    "details": reason_note.strip()},
        "performed_at": _now_iso(),
        "created_at": _now_iso(),
    }
    rec["audit_hash"] = _compute_audit_hash(rec)
    await db[SYNTHETIC_BACKFILL_COLLECTION].insert_one(dict(rec))
    return rec


async def count_synthetic_backfill(company_id: str) -> int:
    return await db[SYNTHETIC_BACKFILL_COLLECTION].count_documents(
        {"company_id": company_id})


# ═══════════ Decorator @requires_transfer_audit (Onda 2 — fechamento) ═══════

def requires_transfer_audit(func):
    """Decorator arquitetural — Onda 2 lockdown.

    Garante que a rota chame `execute_transfer(...)` ao menos 1x. Caso a
    rota retorne sem registrar nenhuma trilha no `transfer_engine`, levanta
    HTTP 400 com `error="transfer_audit_missing"`.

    Uso:
        @router.post("/onts/transfer-to-tech")
        @requires_transfer_audit
        async def transfer_to_tech(...):
            ...
            await execute_transfer(...)
            return {...}

    Observações:
      - Não interfere em rotas que SKIPam tudo (ex: no-op idempotente).
        Para esses casos, marque o response com `transfer_audit_skipped=True`
        explicitamente — o decorator respeita.
      - Implementação via ContextVar (thread-safe + async-safe).
      - Preserva signature com tipos JÁ RESOLVIDOS pra FastAPI poder
        parsear `payload: PydanticModel` como body (sem isso, ForwardRef
        falha resolução no __globals__ do wrapper e cai pra query).
    """
    import inspect as _inspect
    import typing as _typing

    @wraps(func)
    async def wrapper(*args, **kwargs):
        token = _transfer_audit_calls.set([])
        try:
            result = await func(*args, **kwargs)
        finally:
            calls = _transfer_audit_calls.get() or []
            _transfer_audit_calls.reset(token)
        # Permite skip explícito no response
        skipped = False
        if isinstance(result, dict):
            skipped = bool(result.get("transfer_audit_skipped"))
        if not calls and not skipped:
            raise HTTPException(
                400,
                {
                    "error": "transfer_audit_missing",
                    "message": (
                        f"Rota {func.__name__} retornou sem chamar "
                        f"transfer_engine.execute_transfer(). Toda "
                        f"mutação de ownership de ONT exige trilha "
                        f"canônica (Onda 2 — decisão CEO 16/02/2026)."
                    ),
                },
            )
        # Enriquece response com os audits coletados (best-effort)
        if isinstance(result, dict) and calls:
            result.setdefault("_transfer_audits", calls)
        return result

    # Reconstrói signature com tipos RESOLVIDOS (não ForwardRef) pra que
    # FastAPI consiga ver Pydantic models como body parameters.
    try:
        original_sig = _inspect.signature(func)
        resolved_hints = _typing.get_type_hints(func)
        new_params = []
        for name, param in original_sig.parameters.items():
            ann = resolved_hints.get(name, param.annotation)
            new_params.append(param.replace(annotation=ann))
        wrapper.__signature__ = original_sig.replace(parameters=new_params)
        wrapper.__annotations__ = resolved_hints
    except (ValueError, TypeError, NameError) as e:  # pragma: no cover
        logger.warning("[requires_transfer_audit] sig copy fail %s: %s",
                       func.__name__, e)
    return wrapper
