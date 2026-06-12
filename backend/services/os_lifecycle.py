"""SmartProv FSM Lifecycle — Service Order canonical state machine (12/06/2026).

Implementa o modelo padrão FSM 2026 (ServiceNow/Salesforce/Microsoft) em
camada ADITIVA sobre `tickets.status` legado.

Estados canônicos (9):
  draft → ready_for_dispatch → assigned → accepted → en_route → in_progress
        → pending → completed → closed_incomplete / canceled

Work types (independentes do status):
  install · repair · pickup · swap · preventive · inspection · outage_auto

Reason codes (motivos granulares quando aplicável):
  pending: pending_parts · pending_customer · pending_access · pending_approval
  closed_incomplete: customer_no_show · access_denied · safety_issue · failed_test
  canceled: duplicate · client_canceled · system_error · sla_expired

Backfill mapping do status legado:
  pendente            → assigned (se assigned_collaborator_id) senão ready_for_dispatch
  aberta              → in_progress
  finalizada          → completed
  encerrada           → completed (alias)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("os_lifecycle")

# =====================================================================
# Catalog
# =====================================================================
LIFECYCLE_STATES: List[Dict[str, Any]] = [
    {"key": "draft",              "label": "Rascunho",           "color": "#94a3b8", "is_terminal": False, "is_active": False},
    {"key": "ready_for_dispatch", "label": "Pronta p/ despacho", "color": "#0ea5e9", "is_terminal": False, "is_active": True},
    {"key": "assigned",           "label": "Atribuída",          "color": "#6366f1", "is_terminal": False, "is_active": True},
    {"key": "accepted",           "label": "Aceita pelo técnico","color": "#8b5cf6", "is_terminal": False, "is_active": True},
    {"key": "en_route",           "label": "A caminho",          "color": "#a855f7", "is_terminal": False, "is_active": True},
    {"key": "in_progress",        "label": "Em execução",        "color": "#0d9488", "is_terminal": False, "is_active": True},
    {"key": "pending",            "label": "Em espera",          "color": "#f59e0b", "is_terminal": False, "is_active": True},
    {"key": "completed",          "label": "Concluída",          "color": "#16a34a", "is_terminal": True,  "is_active": False},
    {"key": "closed_incomplete",  "label": "Encerrada s/ êxito", "color": "#dc2626", "is_terminal": True,  "is_active": False},
    {"key": "canceled",           "label": "Cancelada",          "color": "#64748b", "is_terminal": True,  "is_active": False},
]
LIFECYCLE_STATE_KEYS = {s["key"] for s in LIFECYCLE_STATES}

WORK_TYPES: List[Dict[str, str]] = [
    {"key": "install",     "label": "Instalação"},
    {"key": "repair",      "label": "Reparo"},
    {"key": "pickup",      "label": "Retirada"},
    {"key": "swap",        "label": "Troca de equipamento"},
    {"key": "preventive",  "label": "Preventiva"},
    {"key": "inspection",  "label": "Vistoria"},
    {"key": "outage_auto", "label": "Outage automático"},
]
WORK_TYPE_KEYS = {w["key"] for w in WORK_TYPES}

# Mapping legado → canônico
LEGACY_TYPE_MAP: Dict[str, str] = {
    "instalacao": "install",
    "reparo": "repair",
    "retirada": "pickup",
    "troca": "swap",
    "troca_endereco": "swap",
    "preventiva": "preventive",
    "rompimento": "repair",       # rompimento de cabo = reparo de rede
    "lentidão": "repair",
    "lentidao": "repair",
    "OUTAGE_AUTO": "outage_auto",
}

REASON_CODES: Dict[str, List[Dict[str, str]]] = {
    "pending": [
        {"key": "pending_parts",     "label": "Aguardando peça/ONT"},
        {"key": "pending_customer",  "label": "Aguardando cliente"},
        {"key": "pending_access",    "label": "Sem acesso ao local"},
        {"key": "pending_approval",  "label": "Aguardando aprovação"},
        {"key": "pending_network",   "label": "Aguardando rede/OLT"},
    ],
    "closed_incomplete": [
        {"key": "customer_no_show",  "label": "Cliente ausente"},
        {"key": "access_denied",     "label": "Acesso negado"},
        {"key": "safety_issue",      "label": "Risco operacional"},
        {"key": "failed_test",       "label": "Falha no teste final"},
        {"key": "wrong_address",     "label": "Endereço incorreto"},
    ],
    "canceled": [
        {"key": "duplicate",         "label": "OS duplicada"},
        {"key": "client_canceled",   "label": "Cliente cancelou"},
        {"key": "system_error",      "label": "Erro do sistema"},
        {"key": "sla_expired",       "label": "SLA expirado (TTL)"},
        {"key": "reassigned",        "label": "Reagendada/Realocada"},
    ],
}

# Transições permitidas (FROM → set(TO))
ALLOWED_TRANSITIONS: Dict[str, set] = {
    "draft":              {"ready_for_dispatch", "canceled"},
    "ready_for_dispatch": {"assigned", "canceled"},
    "assigned":           {"accepted", "ready_for_dispatch", "canceled"},
    "accepted":           {"en_route", "in_progress", "assigned", "canceled"},
    "en_route":           {"in_progress", "pending", "canceled"},
    "in_progress":        {"pending", "completed", "closed_incomplete", "canceled"},
    "pending":            {"in_progress", "closed_incomplete", "canceled"},
    "completed":          {"in_progress"},  # apenas para reabertura (auditoria)
    "closed_incomplete":  {"in_progress"},
    "canceled":           {"ready_for_dispatch"},  # ressuscitar com auditoria
}


def is_valid_state(state: str) -> bool:
    return state in LIFECYCLE_STATE_KEYS


def can_transition(from_state: str, to_state: str) -> bool:
    if from_state == to_state:
        return False
    return to_state in (ALLOWED_TRANSITIONS.get(from_state) or set())


# =====================================================================
# Backfill: legacy_status → lifecycle_state
# =====================================================================
def derive_lifecycle_state(ticket: Dict[str, Any]) -> str:
    """Mapeia o ticket legado pro lifecycle_state canônico.

    Regras:
      - status='pendente' + tem técnico atribuído → 'assigned'
      - status='pendente' + sem técnico         → 'ready_for_dispatch'
      - status='aberta'                          → 'in_progress'
      - status='finalizada'                      → 'completed'
      - status='encerrada'                       → 'completed' (alias)
      - desconhecido                             → 'draft'
    """
    s = (ticket.get("status") or "").lower().strip()
    if s == "pendente":
        if ticket.get("assigned_collaborator_id"):
            return "assigned"
        return "ready_for_dispatch"
    if s == "aberta":
        return "in_progress"
    if s in ("finalizada", "encerrada"):
        return "completed"
    return "draft"


def derive_work_type(ticket: Dict[str, Any]) -> str:
    raw = (ticket.get("type") or "").strip()
    if not raw:
        return "repair"  # default conservador
    return LEGACY_TYPE_MAP.get(raw, LEGACY_TYPE_MAP.get(raw.lower(), "repair"))


async def backfill_company(db, company_id: str) -> Dict[str, Any]:
    """Backfill idempotente: popula lifecycle_state + work_type em todos os
    tickets do tenant sem sobrescrever quem já tem.

    Retorna `{checked, set_lifecycle, set_worktype, skipped}`.
    """
    summary = {"checked": 0, "set_lifecycle": 0, "set_worktype": 0,
                "skipped": 0, "by_lifecycle": {}}
    cursor = db.tickets.find(
        {"company_id": company_id},
        {"_id": 0, "id": 1, "status": 1, "type": 1,
         "assigned_collaborator_id": 1,
         "lifecycle_state": 1, "work_type": 1},
    )
    async for t in cursor:
        summary["checked"] += 1
        sets: Dict[str, Any] = {}
        if not t.get("lifecycle_state"):
            sets["lifecycle_state"] = derive_lifecycle_state(t)
        if not t.get("work_type"):
            sets["work_type"] = derive_work_type(t)
        if not sets:
            summary["skipped"] += 1
            continue
        r = await db.tickets.update_one({"id": t["id"]}, {"$set": sets})
        if r.matched_count > 0:
            if "lifecycle_state" in sets:
                summary["set_lifecycle"] += 1
                k = sets["lifecycle_state"]
                summary["by_lifecycle"][k] = summary["by_lifecycle"].get(k, 0) + 1
            if "work_type" in sets:
                summary["set_worktype"] += 1
    return summary


# =====================================================================
# State machine transitions
# =====================================================================
async def transition(
    db,
    ticket_id: str,
    *,
    to_state: str,
    reason_code: Optional[str] = None,
    notes: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Executa uma transição de estado validada com auditoria.

    Levanta ValueError se transição é inválida (a menos que force=True).
    Retorna o ticket atualizado.
    """
    if not is_valid_state(to_state):
        raise ValueError(f"Estado inválido: {to_state}")

    t = await db.tickets.find_one({"id": ticket_id})
    if not t:
        raise ValueError(f"Ticket não encontrado: {ticket_id}")

    from_state = t.get("lifecycle_state") or derive_lifecycle_state(t)
    if not force and not can_transition(from_state, to_state):
        raise ValueError(
            f"Transição não permitida: {from_state} → {to_state}. "
            f"Permitidas: {sorted(ALLOWED_TRANSITIONS.get(from_state, set()))}"
        )

    # Validações de reason_code
    if to_state in REASON_CODES and not reason_code:
        valid_codes = [r["key"] for r in REASON_CODES[to_state]]
        raise ValueError(
            f"O estado '{to_state}' exige reason_code. "
            f"Válidos: {valid_codes}"
        )
    if reason_code and to_state in REASON_CODES:
        valid_codes = {r["key"] for r in REASON_CODES[to_state]}
        if reason_code not in valid_codes:
            raise ValueError(
                f"reason_code '{reason_code}' inválido para '{to_state}'. "
                f"Válidos: {sorted(valid_codes)}"
            )

    now = datetime.now(timezone.utc).isoformat()
    event = {
        "from_state": from_state,
        "to_state": to_state,
        "reason_code": reason_code,
        "notes": notes,
        "at": now,
        "actor_id": (actor or {}).get("id"),
        "actor_name": (actor or {}).get("name"),
        "actor_email": (actor or {}).get("email"),
        "forced": force,
    }

    update: Dict[str, Any] = {
        "lifecycle_state": to_state,
        "lifecycle_updated_at": now,
    }
    if reason_code:
        update["lifecycle_reason_code"] = reason_code
    else:
        # limpa reason se transitou pra estado sem reason
        update["lifecycle_reason_code"] = None

    # Backwards-compat: também atualiza `status` legado
    if to_state == "completed":
        update["status"] = "encerrada"
    elif to_state in ("closed_incomplete", "canceled"):
        update["status"] = "encerrada"
    elif to_state == "in_progress":
        update["status"] = "aberta"
    elif to_state in ("draft", "ready_for_dispatch", "assigned",
                       "accepted", "en_route", "pending"):
        update["status"] = "pendente"

    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": update, "$push": {"lifecycle_history": event}},
    )
    return {"ok": True, "from_state": from_state, "to_state": to_state,
             "ticket_id": ticket_id, "event": event}


# =====================================================================
# TTL: auto-cancel preventivas paradas há X dias
# =====================================================================
async def auto_cancel_stale_preventive(
    db, company_id: str, days: int = 7,
) -> Dict[str, Any]:
    """Cancela preventivas em ready_for_dispatch/assigned há mais de `days` dias."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    targets = await db.tickets.find(
        {"company_id": company_id,
         "work_type": "preventive",
         "lifecycle_state": {"$in": ["ready_for_dispatch", "assigned"]},
         "created_at": {"$lt": cutoff}},
        {"_id": 0, "id": 1, "lifecycle_state": 1},
    ).to_list(5000)
    canceled = 0
    for t in targets:
        try:
            await transition(
                db, t["id"],
                to_state="canceled",
                reason_code="sla_expired",
                notes=f"Auto-cancel: preventiva sem ação há mais de {days} dias",
                actor={"id": "system", "name": "TTL auto-cancel", "email": "system@smartprov"},
            )
            canceled += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("[auto_cancel] %s falhou: %s", t["id"], e)
    return {"canceled": canceled, "scanned": len(targets), "days": days,
             "cutoff": cutoff}
