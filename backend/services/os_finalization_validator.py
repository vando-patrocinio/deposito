"""os_finalization_validator — Sprint 5 Onda 3 (CEO mandate 19/02/2026)

Bloqueia finalização de OS que não respondem instantaneamente:

  Cliente → CTO → Porta → ONU → Técnico → OS → Ticket

REGRA DE OURO: NÃO CORRIGIR DEPOIS. BLOQUEAR ANTES.

Aplicação:
  - instalação, reparo, troca, retirada, rompimento → enforcement ON
  - preventiva, vistoria, auditoria → exceção (skip enforcement)

Override gestor: completion_data["onda3_override_reason"] (texto ≥20 chars)
permite finalizar SEM CTO/porta APENAS com motivo registrado + audit.
"""
from __future__ import annotations

import logging
import os as _os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ENFORCED_SERVICE_TYPES = {
    "instalacao", "install",
    "reparo", "swap",
    "troca", "replacement",
    "retirada", "removal",
}

EXEMPT_SERVICE_TYPES = {
    "preventiva", "vistoria", "auditoria",
}

# CTO 19/06/2026 — Rompimento é fechamento a nível de REDE (não cliente).
# Não exige ONT/CTO/Porta/subscriber. Exige ticket + colaborador + praça
# + report_text (auditável).
ROMPIMENTO_TYPES = {"rompimento"}

# Outcomes que NÃO representam trabalho operacional executado
# (gestor finaliza remotamente após contato). Auditados mas não bloqueiam.
NON_OPERATIONAL_OUTCOMES = {"informada", "cancelada", "improdutiva"}


def is_enforcement_active() -> bool:
    """Lê env var. Default TRUE em produção (CEO ordem)."""
    v = (_os.environ.get("SPRINT5_ONDA3_ENFORCE") or "true").strip().lower()
    return v in ("1", "true", "yes", "on", "y")


async def validate_finalization(
    db,
    *,
    company_id: str,
    service_type: str,
    ticket_id: Optional[str],
    service_id: Optional[str],
    subscriber_id: Optional[str],
    collaborator_id: Optional[str],
    completion_data: Optional[dict] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """Valida finalização. Retorna (ok, diagnostic_dict).

    diagnostic_dict contém:
      missing: lista de campos faltantes
      reason: descrição human-readable
      override_used: bool
      enforcement_active: bool
      service_type_status: enforced | exempt | unknown
    """
    cd = completion_data or {}
    diag: Dict[str, Any] = {
        "missing": [],
        "reason": None,
        "override_used": False,
        "enforcement_active": is_enforcement_active(),
        "service_type": service_type,
        "service_type_status": "unknown",
    }

    st_norm = (service_type or "").lower().strip()

    # CTO 19/06/2026 — Rompimento: regra própria (rede, sem cliente/ONT)
    if st_norm in ROMPIMENTO_TYPES:
        return await _validate_rompimento(
            db, company_id=company_id, ticket_id=ticket_id,
            collaborator_id=collaborator_id, completion_data=cd, diag=diag,
        )

    # CTO 19/06/2026 — Outcome não-operacional (gestor "informada"/"cancelada"):
    # ainda exige ticket + collaborator (quem fechou) + reason ≥20 chars,
    # mas NÃO exige ONT/CTO/Porta. Audita.
    outcome = (cd.get("outcome") or "").lower().strip()
    if outcome in NON_OPERATIONAL_OUTCOMES:
        return _validate_non_operational(
            outcome=outcome, ticket_id=ticket_id,
            collaborator_id=collaborator_id, completion_data=cd, diag=diag,
        )

    # Exempt types: sempre passam
    if st_norm in EXEMPT_SERVICE_TYPES:
        diag["service_type_status"] = "exempt"
        return True, diag

    if st_norm not in ENFORCED_SERVICE_TYPES:
        # Tipo desconhecido — não bloqueia (mas registra)
        diag["service_type_status"] = "unknown"
        return True, diag

    diag["service_type_status"] = "enforced"

    # Se enforcement desligado, passa mas registra
    if not diag["enforcement_active"]:
        diag["reason"] = "enforcement disabled by env"
        return True, diag

    # Override gestor
    override_reason = (cd.get("onda3_override_reason") or "").strip()
    if override_reason and len(override_reason) >= 20:
        diag["override_used"] = True
        diag["override_reason"] = override_reason
        return True, diag

    # === Validações obrigatórias ===
    missing: List[str] = []

    if not ticket_id:
        missing.append("ticket_id")
    if not service_id:
        missing.append("service_id")
    if not subscriber_id:
        missing.append("subscriber_id")
    if not collaborator_id:
        missing.append("collaborator_id")

    cto_id = cd.get("cto_id")
    port_number = cd.get("port_number")
    ont_identifier = (cd.get("ont") or cd.get("ont_sn")
                       or cd.get("ont_mac"))

    # Para rompimento e retirada: ONU obrigatória; porta/CTO podem
    # ser herdadas da Onda 2 Owner/Location no subscriber.
    if not ont_identifier:
        missing.append("ont_identifier")

    if not cto_id:
        # tenta herdar do subscriber (Onda 2 Owner/Location)
        if subscriber_id:
            sub = await db.subscribers.find_one(
                {"id": subscriber_id, "company_id": company_id},
                {"_id": 0, "cto_id": 1, "cto_port_number": 1},
            )
            if sub:
                cto_id = cto_id or sub.get("cto_id")
                port_number = port_number or sub.get("cto_port_number")
        if not cto_id:
            missing.append("cto_id")

    if port_number is None or port_number == "":
        missing.append("port_number")

    if missing:
        diag["missing"] = missing
        diag["reason"] = (
            f"OS {service_type} bloqueada — faltam: "
            f"{', '.join(missing)}")
        return False, diag

    # === Validação de porta (existe + pertence à CTO + status válido) ===
    port_doc = await db.cto_ports.find_one(
        {"company_id": company_id, "cto_id": cto_id,
         "port_number": int(port_number)},
        {"_id": 0, "id": 1, "status": 1, "subscriber_id": 1},
    )
    if not port_doc:
        diag["missing"].append("cto_port_valid")
        diag["reason"] = (
            f"Porta {port_number} não existe na CTO {cto_id}")
        return False, diag

    port_status = port_doc.get("status")
    port_sub = port_doc.get("subscriber_id")
    if port_status == "occupied" and port_sub and port_sub != subscriber_id:
        # ocupada por outro cliente
        diag["missing"].append("cto_port_available_or_own")
        diag["reason"] = (
            f"Porta {port_number} ocupada por outro subscriber "
            f"({port_sub}) — não pode ser usada por {subscriber_id}")
        return False, diag

    # === Validação de ONU (estoque ou SmartOLT) ===
    if st_norm not in ("retirada", "removal", "rompimento"):
        # Para install/swap/replacement: ONU nova precisa estar válida
        ont_estoque = await db.stok_onts.find_one(
            {"company_id": company_id,
             "$or": [{"mac": ont_identifier},
                        {"sn": ont_identifier},
                        {"serial": ont_identifier}]},
            {"_id": 0, "mac": 1, "sn": 1},
        )
        ont_smartolt = await db.smartolt_onus.find_one(
            {"company_id": company_id,
             "$or": [{"unique_external_id": ont_identifier},
                        {"sn": ont_identifier}]},
            {"_id": 0, "unique_external_id": 1, "sn": 1},
        )
        if not ont_estoque and not ont_smartolt:
            diag["missing"].append("ont_valid")
            diag["reason"] = (
                f"ONU {ont_identifier} não consta no estoque "
                f"nem no SmartOLT")
            return False, diag
        diag["ont_source"] = ("estoque" if ont_estoque else "smartolt")

    diag["cto_id"] = cto_id
    diag["port_number"] = int(port_number)
    diag["reason"] = "validated"
    return True, diag


async def record_validation(
    db, *, company_id: str, ok: bool, diag: Dict[str, Any],
    ticket_id: Optional[str], service_id: Optional[str],
    actor_user_id: Optional[str] = None,
    actor_email: Optional[str] = None,
) -> None:
    """Persiste resultado da validação para métricas + audit."""
    try:
        await db.sprint5_onda3_validations.insert_one({
            "id": f"o3v-{datetime.now(timezone.utc).timestamp()*1000:.0f}",
            "company_id": company_id,
            "ok": ok,
            "diag": diag,
            "ticket_id": ticket_id,
            "service_id": service_id,
            "actor_user_id": actor_user_id,
            "actor_email": actor_email,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.warning("[onda3.record_validation] %s", e)


async def _validate_rompimento(
    db, *, company_id: str, ticket_id: Optional[str],
    collaborator_id: Optional[str], completion_data: dict,
    diag: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
    """Rompimento de rede: exige ticket + colaborador + praça + report.

    Não exige ONT/CTO/Porta/subscriber (rompimento é a nível de rede).
    Override gestor (≥20 chars) permite fechamento sem report.
    """
    diag["service_type_status"] = "rompimento_specific"
    cd = completion_data or {}

    # Override gestor já tratado upstream — mas se chegou aqui ainda válido
    override_reason = (cd.get("onda3_override_reason") or "").strip()
    if override_reason and len(override_reason) >= 20:
        diag["override_used"] = True
        diag["override_reason"] = override_reason
        diag["reason"] = "rompimento_override"
        return True, diag

    missing: List[str] = []
    if not ticket_id:
        missing.append("ticket_id")
    if not collaborator_id:
        missing.append("collaborator_id")
    if not cd.get("praca_id"):
        missing.append("praca_id")
    report = (cd.get("report_text") or "").strip()
    if len(report) < 5:
        missing.append("report_text")

    if missing:
        diag["missing"] = missing
        diag["reason"] = (
            "Rompimento bloqueado — faltam: " + ", ".join(missing)
        )
        return False, diag

    diag["reason"] = "rompimento_validated"
    diag["report_len"] = len(report)
    return True, diag


def _validate_non_operational(
    *, outcome: str, ticket_id: Optional[str],
    collaborator_id: Optional[str], completion_data: dict,
    diag: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
    """Outcome não-operacional (informada/cancelada/improdutiva).

    Gestor finaliza remotamente. Não há trabalho de campo.
    Exige: ticket_id, collaborator_id (quem fechou), motivo ≥20 chars.
    """
    diag["service_type_status"] = "non_operational"
    diag["outcome"] = outcome
    cd = completion_data or {}

    missing: List[str] = []
    if not ticket_id:
        missing.append("ticket_id")
    if not collaborator_id:
        missing.append("collaborator_id")
    reason = (cd.get("manager_close_reason")
              or cd.get("onda3_override_reason") or "").strip()
    if len(reason) < 20:
        missing.append("manager_close_reason_min20")

    if missing:
        diag["missing"] = missing
        diag["reason"] = (
            f"OS {outcome} bloqueada — faltam: " + ", ".join(missing)
        )
        return False, diag

    diag["reason"] = f"{outcome}_validated_non_operational"
    diag["close_reason_len"] = len(reason)
    return True, diag
