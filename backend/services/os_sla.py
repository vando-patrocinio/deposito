"""SLA matrix por (work_type, lifecycle_state).

CTO P1 — 12/06/2026. Tempos esperados em MINUTOS para cada combinação.
Fonte: padrões de SLA ISP/telecom (ServiceNow benchmark + boas práticas Brasil).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

# SLA matrix em MINUTOS, por (work_type, lifecycle_state)
# State final terminal não tem SLA (já fechou).
SLA_MATRIX_MIN: Dict[str, Dict[str, int]] = {
    "install": {
        "ready_for_dispatch": 240,    # 4h pra alguém aceitar
        "assigned": 1440,             # 24h até começar
        "accepted": 60,               # 1h pra deslocar
        "en_route": 90,               # 90min máx no trajeto
        "in_progress": 240,           # 4h de execução
        "pending": 2880,              # 2 dias bloqueado é o limite
        "qa_review": 480,             # 8h pra supervisor revisar
    },
    "repair": {
        "ready_for_dispatch": 60,     # 1h — reparo é urgente
        "assigned": 240,              # 4h
        "accepted": 30,
        "en_route": 60,
        "in_progress": 120,           # 2h
        "pending": 720,               # 12h
        "qa_review": 240,
    },
    "pickup": {
        "ready_for_dispatch": 240,
        "assigned": 1440,
        "accepted": 60,
        "en_route": 90,
        "in_progress": 60,            # retirada é rápida
        "pending": 2880,
        "qa_review": 240,
    },
    "swap": {
        "ready_for_dispatch": 120,
        "assigned": 480,
        "accepted": 45,
        "en_route": 60,
        "in_progress": 180,
        "pending": 1440,
        "qa_review": 480,
    },
    "preventive": {
        "ready_for_dispatch": 10080,  # 7 dias
        "assigned": 10080,
        "accepted": 240,
        "en_route": 120,
        "in_progress": 120,
        "pending": 4320,              # 3 dias
        "qa_review": 1440,
    },
    "inspection": {
        "ready_for_dispatch": 4320,
        "assigned": 4320,
        "accepted": 120,
        "en_route": 90,
        "in_progress": 60,
        "pending": 2880,
        "qa_review": 1440,
    },
    "outage_auto": {
        "ready_for_dispatch": 15,     # crítico
        "assigned": 30,
        "accepted": 10,
        "en_route": 30,
        "in_progress": 60,
        "pending": 60,
        "qa_review": 120,
    },
}

# Multiplicadores quando há reason_code de espera externa
PENDING_REASON_MULTIPLIER: Dict[str, float] = {
    "pending_parts":    3.0,   # peça atrasa, esticamos o SLA
    "pending_customer": 5.0,
    "pending_access":   2.0,
    "pending_approval": 2.0,
    "pending_network":  1.5,
}


def get_sla_minutes(
    work_type: str, lifecycle_state: str,
    reason_code: Optional[str] = None,
) -> Optional[int]:
    """Retorna o SLA esperado em minutos, ou None se estado terminal."""
    matrix = SLA_MATRIX_MIN.get(work_type) or SLA_MATRIX_MIN.get("repair") or {}
    base = matrix.get(lifecycle_state)
    if base is None:
        return None
    if lifecycle_state == "pending" and reason_code:
        mult = PENDING_REASON_MULTIPLIER.get(reason_code, 1.0)
        return int(base * mult)
    return base


def compute_sla_breach(ticket: Dict[str, Any]) -> Dict[str, Any]:
    """Calcula breach status: minutos consumidos vs SLA, % de uso, breach=True/False."""
    wt = ticket.get("work_type") or "repair"
    ls = ticket.get("lifecycle_state") or "assigned"
    rc = ticket.get("lifecycle_reason_code")
    sla = get_sla_minutes(wt, ls, rc)
    if sla is None:
        return {"sla_minutes": None, "consumed_minutes": None,
                "breach": False, "percent_used": None}

    # Tempo no estado atual: usa lifecycle_updated_at, senão created_at
    ref = ticket.get("lifecycle_updated_at") or ticket.get("created_at")
    if not ref:
        return {"sla_minutes": sla, "consumed_minutes": None,
                "breach": False, "percent_used": None}
    try:
        dt = datetime.fromisoformat(str(ref).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        elapsed = (now - dt).total_seconds() / 60.0
        percent = elapsed / sla * 100.0
        return {
            "sla_minutes": sla,
            "consumed_minutes": int(elapsed),
            "percent_used": round(percent, 1),
            "breach": elapsed > sla,
            "warning": (not (elapsed > sla)) and percent >= 80.0,
        }
    except (ValueError, TypeError):
        return {"sla_minutes": sla, "consumed_minutes": None,
                "breach": False, "percent_used": None}
