"""
decision_engine.py — Sprint 8 + pós-CTO audit (expansão de regras)
Motor de Decisão do Presidente IA Autônomo.

Fluxo: Evento → Contexto → Correlação → Predição → Decisão → Ação.

Pós-CTO audit:
  - Streaming cursor (sem .limit(500) em memória) — escala melhor.
  - 15 regras (era 4). Cobre >50% dos EventTypes da taxonomia.
  - Propagação de `correlation_id` (evento gatilho → decisão).
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db


# ─────────────────── Helpers ───────────────────
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mk_decision(
    company_id: Optional[str],
    title: str,
    reasoning: str,
    action_type: str,
    action_payload: Dict[str, Any],
    confidence: float = 0.8,
    trigger_event_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "id": f"dec-{uuid.uuid4().hex[:14]}",
        "created_at": _now(),
        "company_id": company_id,
        "title": title,
        "reasoning": reasoning,
        "confidence": confidence,
        "action_type": action_type,
        "action_payload": action_payload,
        "trigger_event_id": trigger_event_id,
        "correlation_id": correlation_id,
        "executed": False,
    }


def _ev_payload(ev: Dict[str, Any]) -> Dict[str, Any]:
    return ev.get("payload") or {}


# ─────────────────── Rules ───────────────────
async def _rule_collective_outage(events):
    """5+ CLIENT_OFFLINE/ONU_OFFLINE no mesmo CTO em 10min."""
    from services.rule_thresholds import get as get_th
    min_count = await get_th("collective_outage", "min_offline_count",
                                 5)
    decisions = []
    by_cto = defaultdict(list)
    for ev in events:
        if ev.get("event_type") not in ("CLIENT_OFFLINE", "ONU_OFFLINE"):
            continue
        cto = _ev_payload(ev).get("cto_id")
        if cto:
            by_cto[cto].append(ev)
    for cto_id, evs in by_cto.items():
        if len(evs) >= int(min_count):
            decisions.append(_mk_decision(
                company_id=evs[0].get("company_id"),
                title=f"Incidente coletivo na CTO {cto_id}",
                reasoning=(
                    f"{len(evs)} clientes ficaram offline na mesma "
                    f"CTO {cto_id} nos últimos 10 minutos "
                    f"(threshold dinâmico={min_count})."),
                action_type="open_incident",
                action_payload={
                    "cto_id": cto_id,
                    "affected_count": len(evs),
                    "client_ids": [_ev_payload(e).get("subscriber_id")
                                       for e in evs[:20]],
                },
                confidence=0.92,
                trigger_event_id=evs[0]["id"],
                correlation_id=evs[0].get("correlation_id"),
            ))
    return decisions


async def _rule_churn_risk(events):
    """CLIENT_CHURN_RISK → oportunidade Isabella."""
    decisions = []
    for ev in events:
        if ev.get("event_type") != "CLIENT_CHURN_RISK":
            continue
        sub = _ev_payload(ev).get("subscriber_id")
        if not sub:
            continue
        decisions.append(_mk_decision(
            company_id=ev.get("company_id"),
            title=f"Risco de churn — cliente {sub}",
            reasoning=(
                f"Cliente com sinais de churn: "
                f"{_ev_payload(ev).get('reason', '?')}."),
            action_type="create_retention_opportunity",
            action_payload={"subscriber_id": sub,
                            "channel": "whatsapp", "agent": "isabella"},
            confidence=0.78,
            trigger_event_id=ev["id"],
            correlation_id=ev.get("correlation_id"),
        ))
    return decisions


async def _rule_rbac_abuse(events):
    """≥3 RBAC_DENIED do mesmo user → alerta gestor."""
    from services.rule_thresholds import get as get_th
    min_denied = int(await get_th("rbac_abuse", "min_denied_count", 3))
    decisions = []
    by_user = defaultdict(list)
    for ev in events:
        if ev.get("event_type") != "RBAC_DENIED":
            continue
        uid = ev.get("user_id")
        if uid:
            by_user[uid].append(ev)
    for uid, evs in by_user.items():
        if len(evs) >= min_denied:
            decisions.append(_mk_decision(
                company_id=evs[0].get("company_id"),
                title=(f"Possível escalação de privilégio — "
                         f"user {uid}"),
                reasoning=(
                    f"{len(evs)} tentativas de acesso negadas em "
                    f"sequência."),
                action_type="notify_manager",
                action_payload={
                    "user_id": uid,
                    "denied_count": len(evs),
                    "message": (
                        f"Usuário {uid} foi bloqueado {len(evs)}× "
                        f"pelo RBAC."),
                },
                confidence=0.85,
                trigger_event_id=evs[0]["id"],
                correlation_id=evs[0].get("correlation_id"),
            ))
    return decisions


async def _rule_payment_overdue(events):
    """PAYMENT_OVERDUE → escalonar régua de cobrança."""
    decisions = []
    for ev in events:
        if ev.get("event_type") != "PAYMENT_OVERDUE":
            continue
        sub = _ev_payload(ev).get("subscriber_id")
        if not sub:
            continue
        decisions.append(_mk_decision(
            company_id=ev.get("company_id"),
            title=f"Inadimplência detectada — {sub}",
            reasoning=("Pagamento em atraso. Acionar régua de cobrança."),
            action_type="escalate_dunning",
            action_payload={"subscriber_id": sub},
            confidence=0.95,
            trigger_event_id=ev["id"],
            correlation_id=ev.get("correlation_id"),
        ))
    return decisions


async def _rule_onu_low_signal(events):
    """ONU_LOW_SIGNAL → cria ticket técnico."""
    decisions = []
    for ev in events:
        if ev.get("event_type") != "ONU_LOW_SIGNAL":
            continue
        p = _ev_payload(ev)
        sub = p.get("subscriber_id") or p.get("onu_id")
        if not sub:
            continue
        decisions.append(_mk_decision(
            company_id=ev.get("company_id"),
            title=f"Sinal baixo na ONU — {sub}",
            reasoning=(f"Sinal RX abaixo do limite "
                         f"(rx={p.get('rx_dbm', '?')}dBm)."),
            action_type="open_technical_ticket",
            action_payload={"subscriber_id": sub,
                            "issue": "low_signal",
                            "rx_dbm": p.get("rx_dbm")},
            confidence=0.82,
            trigger_event_id=ev["id"],
            correlation_id=ev.get("correlation_id"),
        ))
    return decisions


async def _rule_cto_critical(events):
    """CTO_CRITICAL/DEGRADED → notifica equipe NOC + abre incidente."""
    decisions = []
    for ev in events:
        if ev.get("event_type") not in ("CTO_CRITICAL", "CTO_DEGRADED"):
            continue
        p = _ev_payload(ev)
        cto = p.get("cto_id")
        if not cto:
            continue
        decisions.append(_mk_decision(
            company_id=ev.get("company_id"),
            title=f"CTO {cto} em estado crítico",
            reasoning=(f"Estado={ev.get('event_type')}, "
                         f"métrica={p.get('metric', 'n/a')}."),
            action_type="open_incident",
            action_payload={"cto_id": cto,
                            "affected_count": p.get("subscribers", 0),
                            "client_ids": []},
            confidence=0.90 if ev["event_type"] == "CTO_CRITICAL"
                       else 0.75,
            trigger_event_id=ev["id"],
            correlation_id=ev.get("correlation_id"),
        ))
    return decisions


async def _rule_vlan_saturated(events):
    """VLAN_SATURATED → notifica gestor de rede."""
    decisions = []
    for ev in events:
        if ev.get("event_type") != "VLAN_SATURATED":
            continue
        p = _ev_payload(ev)
        decisions.append(_mk_decision(
            company_id=ev.get("company_id"),
            title=f"VLAN saturada — {p.get('vlan', '?')}",
            reasoning=(f"Utilização {p.get('usage_pct', '?')}% "
                         f"acima do SLA."),
            action_type="notify_manager",
            action_payload={"message":
                              f"VLAN {p.get('vlan')} saturada"},
            confidence=0.80,
            trigger_event_id=ev["id"],
            correlation_id=ev.get("correlation_id"),
        ))
    return decisions


async def _rule_ticket_recurring(events):
    """TICKET_RECURRING (>3 tickets do mesmo cliente) → retenção."""
    decisions = []
    for ev in events:
        if ev.get("event_type") != "TICKET_RECURRING":
            continue
        p = _ev_payload(ev)
        sub = p.get("subscriber_id")
        if not sub:
            continue
        decisions.append(_mk_decision(
            company_id=ev.get("company_id"),
            title=f"Cliente recorrente em suporte — {sub}",
            reasoning=(f"{p.get('count', '?')} tickets abertos. "
                         f"Risco alto de churn."),
            action_type="create_retention_opportunity",
            action_payload={"subscriber_id": sub,
                            "channel": "whatsapp",
                            "agent": "isabella",
                            "kind": "ticket_recurrence"},
            confidence=0.82,
            trigger_event_id=ev["id"],
            correlation_id=ev.get("correlation_id"),
        ))
    return decisions


async def _rule_opportunity_detected(events):
    """OPPORTUNITY_DETECTED → cria lead para o time comercial."""
    decisions = []
    for ev in events:
        if ev.get("event_type") != "OPPORTUNITY_DETECTED":
            continue
        p = _ev_payload(ev)
        decisions.append(_mk_decision(
            company_id=ev.get("company_id"),
            title=f"Oportunidade detectada — {p.get('source', 'N/A')}",
            reasoning=p.get("reason", "Padrão identificado."),
            action_type="create_sales_lead",
            action_payload=p,
            confidence=0.70,
            trigger_event_id=ev["id"],
            correlation_id=ev.get("correlation_id"),
        ))
    return decisions


async def _rule_sale_lost(events):
    """SALE_LOST → registra motivo e tenta win-back se >R$X."""
    decisions = []
    for ev in events:
        if ev.get("event_type") != "SALE_LOST":
            continue
        p = _ev_payload(ev)
        if (p.get("value") or 0) >= 200:
            decisions.append(_mk_decision(
                company_id=ev.get("company_id"),
                title=f"Win-back — venda perdida ({p.get('lead_id')})",
                reasoning=(f"Venda de R${p.get('value')} perdida. "
                             f"Motivo={p.get('reason', '?')}. "
                             f"Tentativa de recuperação automática."),
                action_type="create_retention_opportunity",
                action_payload={"subscriber_id": p.get("lead_id"),
                                "channel": "whatsapp",
                                "agent": "isabella",
                                "kind": "win_back"},
                confidence=0.65,
                trigger_event_id=ev["id"],
                correlation_id=ev.get("correlation_id"),
            ))
    return decisions


async def _rule_gps_deviation(events):
    """GPS_ROUTE_DEVIATION → notifica gestor de frota."""
    decisions = []
    for ev in events:
        if ev.get("event_type") != "GPS_ROUTE_DEVIATION":
            continue
        p = _ev_payload(ev)
        decisions.append(_mk_decision(
            company_id=ev.get("company_id"),
            title=f"Desvio de rota — técnico {p.get('tech_id', '?')}",
            reasoning=(f"Desvio de {p.get('distance_km', '?')}km da "
                         f"rota prevista."),
            action_type="notify_manager",
            action_payload={"message":
                              (f"Técnico {p.get('tech_id')} desviou "
                               f"{p.get('distance_km')}km da rota.")},
            confidence=0.72,
            trigger_event_id=ev["id"],
            correlation_id=ev.get("correlation_id"),
        ))
    return decisions


async def _rule_tech_productivity(events):
    """TECH_PRODUCTIVITY_DROP → notifica gestor."""
    decisions = []
    for ev in events:
        if ev.get("event_type") != "TECH_PRODUCTIVITY_DROP":
            continue
        p = _ev_payload(ev)
        decisions.append(_mk_decision(
            company_id=ev.get("company_id"),
            title=(f"Queda de produtividade — técnico "
                     f"{p.get('tech_id', '?')}"),
            reasoning=(f"Produtividade {p.get('current', '?')} vs "
                         f"baseline {p.get('baseline', '?')}."),
            action_type="notify_manager",
            action_payload={"message":
                              f"Queda de produtividade {p.get('tech_id')}"},
            confidence=0.68,
            trigger_event_id=ev["id"],
            correlation_id=ev.get("correlation_id"),
        ))
    return decisions


async def _rule_data_quality_drop(events):
    """DATA_QUALITY_DROP → notifica admin para limpeza."""
    decisions = []
    for ev in events:
        if ev.get("event_type") != "DATA_QUALITY_DROP":
            continue
        p = _ev_payload(ev)
        decisions.append(_mk_decision(
            company_id=ev.get("company_id"),
            title=f"Data Quality em risco — score {p.get('score', '?')}",
            reasoning=("Score do banco caiu. Issues prioritários "
                         "detectados pelo scanner."),
            action_type="notify_manager",
            action_payload={"message":
                              (f"Score de qualidade do banco caiu para "
                               f"{p.get('score')}.")},
            confidence=0.85,
            trigger_event_id=ev["id"],
            correlation_id=ev.get("correlation_id"),
        ))
    return decisions


async def _rule_dunning_escalated(events):
    """DUNNING_ESCALATED (fim da régua sem pagamento) → suspensão."""
    decisions = []
    for ev in events:
        if ev.get("event_type") != "DUNNING_ESCALATED":
            continue
        p = _ev_payload(ev)
        sub = p.get("subscriber_id")
        if not sub:
            continue
        decisions.append(_mk_decision(
            company_id=ev.get("company_id"),
            title=f"Suspensão recomendada — {sub}",
            reasoning=("Régua de cobrança esgotada sem pagamento. "
                         "Acionar suspensão técnica."),
            action_type="notify_manager",
            action_payload={"message":
                              (f"Cliente {sub} pendente após régua "
                               f"completa — sugerir suspensão.")},
            confidence=0.88,
            trigger_event_id=ev["id"],
            correlation_id=ev.get("correlation_id"),
        ))
    return decisions


async def _rule_collective_outage_extended(events):
    """COLLECTIVE_OUTAGE explícito → abre incidente já preformado."""
    decisions = []
    for ev in events:
        if ev.get("event_type") != "COLLECTIVE_OUTAGE":
            continue
        p = _ev_payload(ev)
        decisions.append(_mk_decision(
            company_id=ev.get("company_id"),
            title=f"Outage coletivo — {p.get('region', '?')}",
            reasoning=(f"Outage afetando {p.get('affected_count', '?')}"
                         f" clientes."),
            action_type="open_incident",
            action_payload={"cto_id": p.get("cto_id") or "n/a",
                            "affected_count": p.get("affected_count", 0),
                            "client_ids": p.get("client_ids") or []},
            confidence=0.95,
            trigger_event_id=ev["id"],
            correlation_id=ev.get("correlation_id"),
        ))
    return decisions


RULES = [
    _rule_collective_outage,
    _rule_collective_outage_extended,
    _rule_churn_risk,
    _rule_rbac_abuse,
    _rule_payment_overdue,
    _rule_onu_low_signal,
    _rule_cto_critical,
    _rule_vlan_saturated,
    _rule_ticket_recurring,
    _rule_opportunity_detected,
    _rule_sale_lost,
    _rule_gps_deviation,
    _rule_tech_productivity,
    _rule_data_quality_drop,
    _rule_dunning_escalated,
]


# ─────────────────── Consumer ───────────────────
async def run_decision_cycle(limit_events: Optional[int] = None
                                  ) -> Dict[str, Any]:
    """Lê eventos não consumidos via STREAMING CURSOR (sem carregar
    tudo em RAM), aplica regras, grava decisões.

    Pós-CTO audit:
      - `limit_events=None` (default): processa todo o backlog em lotes
        de 200. Mantém parâmetro para compatibilidade nos testes.
      - Streaming via async cursor (não há `.find(...).to_list()`).

    Sprint 10:
      - Ajusta `confidence` de cada decisão pelo feedback_loop antes
        de persistir (data-driven adjustment).
    """
    batch_size = 200
    events: List[Dict[str, Any]] = []
    cur = db.motor_ia_events.find({"consumed": False}).sort("timestamp", 1)
    if limit_events is not None:
        cur = cur.limit(limit_events)
    async for e in cur:
        events.append(e)
        if limit_events is None and len(events) >= batch_size:
            break  # processa em ondas

    decisions: List[Dict[str, Any]] = []
    for rule in RULES:
        try:
            decisions += await rule(events)
        except Exception:
            continue

    # Sprint 10: feedback loop — ajusta confidence pelas success_rates
    if decisions:
        try:
            from services.feedback_loop import adjust_confidence
            for d in decisions:
                base = d.get("confidence", 0.8)
                adj = await adjust_confidence(d["action_type"], base)
                d["confidence_base"] = base
                d["confidence"] = adj
        except Exception:
            pass

    if decisions:
        try:
            await db.motor_ia_decisions.insert_many(decisions)
        except Exception:
            pass

    if events:
        try:
            await db.motor_ia_events.update_many(
                {"id": {"$in": [e["id"] for e in events]}},
                {"$set": {"consumed": True, "consumed_at": _now()}})
        except Exception:
            pass

    return {
        "events_processed": len(events),
        "decisions_created": len(decisions),
        "decisions_by_type": {
            t: sum(1 for d in decisions if d["action_type"] == t)
            for t in {d["action_type"] for d in decisions}
        },
        "rules_active": len(RULES),
        "generated_at": _now(),
    }
