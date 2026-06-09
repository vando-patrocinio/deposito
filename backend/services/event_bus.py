"""
event_bus.py — Sprint 7 / iter226
Barramento único de eventos corporativos. Toda emissão passa por aqui
para alimentar o Sistema Nervoso (motor_ia_events).

Uso:
    from services.event_bus import emit_event, EventType
    await emit_event(EventType.CLIENT_OFFLINE, company_id="...",
                       user_id="...", source="smartolt",
                       severity="alta", payload={...})
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from database import db

log = logging.getLogger("event_bus")


class EventType:
    # Clientes
    CLIENT_OFFLINE = "CLIENT_OFFLINE"
    CLIENT_ONLINE = "CLIENT_ONLINE"
    CLIENT_CHURN_RISK = "CLIENT_CHURN_RISK"
    CLIENT_CREATED = "CLIENT_CREATED"
    # Rede
    ONU_LOW_SIGNAL = "ONU_LOW_SIGNAL"
    ONU_OFFLINE = "ONU_OFFLINE"
    CTO_DEGRADED = "CTO_DEGRADED"
    CTO_CRITICAL = "CTO_CRITICAL"
    VLAN_SATURATED = "VLAN_SATURATED"
    COLLECTIVE_OUTAGE = "COLLECTIVE_OUTAGE"
    # Atendimento
    TICKET_OPENED = "TICKET_OPENED"
    TICKET_CLOSED = "TICKET_CLOSED"
    TICKET_RECURRING = "TICKET_RECURRING"
    # Vendas
    SALE_CREATED = "SALE_CREATED"
    SALE_LOST = "SALE_LOST"
    OPPORTUNITY_DETECTED = "OPPORTUNITY_DETECTED"
    # Financeiro
    PAYMENT_OVERDUE = "PAYMENT_OVERDUE"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
    DUNNING_ESCALATED = "DUNNING_ESCALATED"
    # GPS / Frota
    GPS_ROUTE_DEVIATION = "GPS_ROUTE_DEVIATION"
    TECH_PRODUCTIVITY_DROP = "TECH_PRODUCTIVITY_DROP"
    # Parceiros
    PARTNER_QR_REDEEMED = "PARTNER_QR_REDEEMED"
    REFERRAL_CONVERTED = "REFERRAL_CONVERTED"
    # WhatsApp
    WA_INBOUND_RECEIVED = "WA_INBOUND_RECEIVED"
    WA_CAMPAIGN_SENT = "WA_CAMPAIGN_SENT"
    # Segurança / Governança
    RBAC_DENIED = "RBAC_DENIED"
    AUDIT_EXPORT = "AUDIT_EXPORT"
    AUDIT_DELETE = "AUDIT_DELETE"
    IMPERSONATE = "IMPERSONATE"
    DATA_QUALITY_DROP = "DATA_QUALITY_DROP"
    # Motor IA
    AI_DECISION = "AI_DECISION"
    AI_ACTION = "AI_ACTION"
    AI_OUTCOME = "AI_OUTCOME"
    # FASE 3 Constituição V3.0 — Sistema Nervoso 90%
    # Comercial
    SALE_CONVERTED = "SALE_CONVERTED"
    # Instalações
    INSTALL_SCHEDULED = "INSTALL_SCHEDULED"
    INSTALL_COMPLETED = "INSTALL_COMPLETED"
    INSTALL_FAILED = "INSTALL_FAILED"
    # Financeiro
    INVOICE_CREATED = "INVOICE_CREATED"
    INVOICE_PAID = "INVOICE_PAID"
    INVOICE_OVERDUE = "INVOICE_OVERDUE"
    # Atendimento
    TICKET_REOPENED = "TICKET_REOPENED"
    # WhatsApp
    WA_OUTBOUND_SENT = "WA_OUTBOUND_SENT"
    # Indicações
    REFERRAL_CREATED = "REFERRAL_CREATED"
    # Estoque
    EQUIPMENT_ASSIGNED = "EQUIPMENT_ASSIGNED"
    EQUIPMENT_RETURNED = "EQUIPMENT_RETURNED"
    # Rede
    ONU_ONLINE = "ONU_ONLINE"
    SIGNAL_DEGRADED = "SIGNAL_DEGRADED"
    # Operações
    TECHNICIAN_STARTED = "TECHNICIAN_STARTED"
    TECHNICIAN_FINISHED = "TECHNICIAN_FINISHED"
    TECHNICIAN_LATE = "TECHNICIAN_LATE"
    # Data Quality
    DATA_QUALITY_RECOVERY = "DATA_QUALITY_RECOVERY"


SEVERITY = ("baixa", "media", "alta", "critica")


async def emit_event(
    event_type: str,
    *,
    company_id: Optional[str] = None,
    user_id: Optional[str] = None,
    source: str = "system",
    severity: str = "media",
    payload: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Emite um evento no barramento corporativo. Best-effort: falha
    silenciosa para não impactar fluxo principal.

    Pós-CTO audit:
      - `correlation_id` é gerado automaticamente se None (rastreabilidade
        ponta-a-ponta).
      - `company_id` ausente é LOGADO como warning (tenant leakage).
    """
    if not company_id:
        log.warning(
            "[event_bus] event_type=%s sem company_id (source=%s) — "
            "potencial tenant leak",
            event_type, source)
    if not correlation_id:
        correlation_id = f"corr-{uuid.uuid4().hex[:14]}"
    doc = {
        "id": f"evt-{uuid.uuid4().hex[:14]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "company_id": company_id,
        "user_id": user_id,
        "source": source,
        "event_type": event_type,
        "severity": severity if severity in SEVERITY else "media",
        "payload": payload or {},
        "correlation_id": correlation_id,
        "consumed": False,
    }
    try:
        await db.motor_ia_events.insert_one(doc)
    except Exception:
        pass
    return doc


async def ensure_indexes() -> None:
    """Índices das 7 collections de memória corporativa."""
    # motor_ia_events
    try:
        await db.motor_ia_events.create_index([("timestamp", -1)])
        await db.motor_ia_events.create_index(
            [("event_type", 1), ("timestamp", -1)])
        await db.motor_ia_events.create_index(
            [("company_id", 1), ("timestamp", -1)])
        await db.motor_ia_events.create_index([("consumed", 1)])
    except Exception:
        pass
    # demais collections
    for col in ("motor_ia_memory", "motor_ia_insights",
                  "motor_ia_predictions", "motor_ia_decisions",
                  "motor_ia_actions", "motor_ia_outcomes",
                  "motor_ia_learnings"):
        try:
            await db[col].create_index([("created_at", -1)])
            await db[col].create_index([("company_id", 1),
                                          ("created_at", -1)])
        except Exception:
            pass
