"""
event_emitters.py — Sprint 13
Helpers idiomáticos para PLUGAR módulos no Event Bus sem ficar
repetindo `emit_event(...)` com 8 parâmetros em cada call site.

Padrão de uso:
    from services.event_emitters import emit_business

    await emit_business(
        kind="ticket.opened",       # tipo do negócio → EventType formal
        company_id=user["company_id"],
        actor=user,
        payload={"ticket_id": t.id, "subscriber_id": t.subscriber_id},
    )

Vantagens:
    - Resolve EventType a partir de uma string "kind" simples.
    - Pega `company_id` automaticamente do dict `actor` (user) se
      não vier explícito.
    - Resolve correlation_id de Request.state (FastAPI middleware
      injetou) se disponível.
    - Falha silenciosamente — nunca quebra o fluxo principal.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from services.event_bus import emit_event, EventType

log = logging.getLogger("event_emitters")


# kind (string fácil de lembrar) → EventType formal
KIND_MAP: Dict[str, str] = {
    # Tickets
    "ticket.opened": EventType.TICKET_OPENED,
    "ticket.closed": EventType.TICKET_CLOSED,
    "ticket.recurring": EventType.TICKET_RECURRING,
    # Clientes
    "client.created": EventType.CLIENT_CREATED,
    "client.online": EventType.CLIENT_ONLINE,
    "client.offline": EventType.CLIENT_OFFLINE,
    "client.churn_risk": EventType.CLIENT_CHURN_RISK,
    # Financeiro
    "payment.overdue": EventType.PAYMENT_OVERDUE,
    "payment.received": EventType.PAYMENT_RECEIVED,
    "dunning.escalated": EventType.DUNNING_ESCALATED,
    # Vendas
    "sale.created": EventType.SALE_CREATED,
    "sale.lost": EventType.SALE_LOST,
    "opportunity.detected": EventType.OPPORTUNITY_DETECTED,
    # WhatsApp
    "wa.inbound": EventType.WA_INBOUND_RECEIVED,
    "wa.campaign_sent": EventType.WA_CAMPAIGN_SENT,
    # Rede
    "onu.low_signal": EventType.ONU_LOW_SIGNAL,
    "onu.offline": EventType.ONU_OFFLINE,
    "cto.degraded": EventType.CTO_DEGRADED,
    "cto.critical": EventType.CTO_CRITICAL,
    "vlan.saturated": EventType.VLAN_SATURATED,
    "collective_outage": EventType.COLLECTIVE_OUTAGE,
    # GPS/Frota
    "gps.route_deviation": EventType.GPS_ROUTE_DEVIATION,
    "tech.productivity_drop": EventType.TECH_PRODUCTIVITY_DROP,
    # Parceiros / Indicações
    "partner.qr_redeemed": EventType.PARTNER_QR_REDEEMED,
    "referral.converted": EventType.REFERRAL_CONVERTED,
    # Audit
    "audit.export": EventType.AUDIT_EXPORT,
    "audit.delete": EventType.AUDIT_DELETE,
    "rbac.denied": EventType.RBAC_DENIED,
    "impersonate": EventType.IMPERSONATE,
    # FASE 3 Constituição — emit_business completos
    # Comercial
    "sale.converted": EventType.SALE_CONVERTED,
    # Instalações
    "install.scheduled": EventType.INSTALL_SCHEDULED,
    "install.completed": EventType.INSTALL_COMPLETED,
    "install.failed": EventType.INSTALL_FAILED,
    # Financeiro
    "invoice.created": EventType.INVOICE_CREATED,
    "invoice.paid": EventType.INVOICE_PAID,
    "invoice.overdue": EventType.INVOICE_OVERDUE,
    # Atendimento
    "ticket.reopened": EventType.TICKET_REOPENED,
    # WhatsApp
    "wa.outbound": EventType.WA_OUTBOUND_SENT,
    # Indicações
    "referral.created": EventType.REFERRAL_CREATED,
    # Parceiros
    "partner.redeemed": EventType.PARTNER_QR_REDEEMED,  # alias
    # Estoque
    "equipment.assigned": EventType.EQUIPMENT_ASSIGNED,
    "equipment.returned": EventType.EQUIPMENT_RETURNED,
    # Rede
    "onu.online": EventType.ONU_ONLINE,
    "signal.degraded": EventType.SIGNAL_DEGRADED,
    # Operações
    "technician.started": EventType.TECHNICIAN_STARTED,
    "technician.finished": EventType.TECHNICIAN_FINISHED,
    "technician.late": EventType.TECHNICIAN_LATE,
    # Data Quality (já emitido em data_quality_v2)
    "data_quality.recovery": EventType.DATA_QUALITY_RECOVERY,
    "data_quality.drop": EventType.DATA_QUALITY_DROP,
}


def _resolve_company_id(actor: Optional[Dict[str, Any]],
                          explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    if actor and isinstance(actor, dict):
        return (actor.get("company_id")
                or actor.get("companyId"))
    return None


def _resolve_user_id(actor: Optional[Dict[str, Any]]) -> Optional[str]:
    if not actor:
        return None
    return (actor.get("id")
            or actor.get("sub")
            or actor.get("user_id"))


async def emit_business(
    *,
    kind: str,
    company_id: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
    severity: str = "media",
    correlation_id: Optional[str] = None,
    source: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Emite evento de negócio resolvendo EventType pela string `kind`."""
    event_type = KIND_MAP.get(kind)
    if not event_type:
        log.warning("[event_emitters] kind desconhecido: %s", kind)
        return None
    co = _resolve_company_id(actor, company_id)
    uid = _resolve_user_id(actor)
    try:
        return await emit_event(
            event_type,
            company_id=co,
            user_id=uid,
            source=source or "business",
            severity=severity,
            payload=payload or {},
            correlation_id=correlation_id,
        )
    except Exception as e:  # noqa: BLE001
        log.debug("[event_emitters] emit falhou (%s): %s", kind, e)
        return None
