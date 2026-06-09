"""
nervous_coverage.py — Mede cobertura do Sistema Nervoso (FASE 3 V3.0).

Cobertura = % das categorias da Constituição V3.0 que tiveram pelo menos
1 evento emitido nos últimos N dias.

Também:
  - Top eventos do dia
  - Eventos por domínio
  - Eventos por empresa
  - Timeline corporativa enriquecida (eventos + decisions + actions)
  - Resposta autônoma "O que aconteceu na empresa hoje?"
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db


# Mapeamento Constituição V3.0: domínio → lista de event_types esperados
EXPECTED_BY_DOMAIN: Dict[str, List[str]] = {
    "comercial": ["SALE_CREATED", "SALE_CONVERTED", "SALE_LOST"],
    "instalacoes": ["INSTALL_SCHEDULED", "INSTALL_COMPLETED",
                     "INSTALL_FAILED"],
    "financeiro": ["INVOICE_CREATED", "INVOICE_PAID", "INVOICE_OVERDUE",
                    "PAYMENT_RECEIVED", "PAYMENT_OVERDUE",
                    "DUNNING_ESCALATED"],
    "atendimento": ["TICKET_OPENED", "TICKET_CLOSED",
                     "TICKET_REOPENED", "TICKET_RECURRING"],
    "whatsapp": ["WA_INBOUND_RECEIVED", "WA_OUTBOUND_SENT",
                  "WA_CAMPAIGN_SENT"],
    "indicacoes": ["REFERRAL_CREATED", "REFERRAL_CONVERTED"],
    "parceiros": ["PARTNER_QR_REDEEMED"],
    "estoque": ["EQUIPMENT_ASSIGNED", "EQUIPMENT_RETURNED"],
    "rede": ["ONU_OFFLINE", "ONU_ONLINE", "SIGNAL_DEGRADED",
              "VLAN_SATURATED", "CTO_DEGRADED", "CTO_CRITICAL",
              "COLLECTIVE_OUTAGE", "CLIENT_OFFLINE", "CLIENT_ONLINE"],
    "operacoes": ["TECHNICIAN_STARTED", "TECHNICIAN_FINISHED",
                   "TECHNICIAN_LATE", "GPS_ROUTE_DEVIATION",
                   "TECH_PRODUCTIVITY_DROP"],
}

FRIENDLY_NAMES = {
    "SALE_CREATED": "Venda criada",
    "SALE_CONVERTED": "Venda convertida",
    "SALE_LOST": "Venda perdida",
    "INSTALL_SCHEDULED": "Instalação agendada",
    "INSTALL_COMPLETED": "Instalação concluída",
    "INSTALL_FAILED": "Instalação falhou",
    "INVOICE_CREATED": "Fatura criada",
    "INVOICE_PAID": "Fatura paga",
    "INVOICE_OVERDUE": "Fatura vencida",
    "PAYMENT_RECEIVED": "Pagamento recebido",
    "PAYMENT_OVERDUE": "Pagamento atrasado",
    "DUNNING_ESCALATED": "Cobrança escalada",
    "TICKET_OPENED": "Ticket aberto",
    "TICKET_CLOSED": "Ticket fechado",
    "TICKET_REOPENED": "Ticket reaberto",
    "TICKET_RECURRING": "Ticket recorrente",
    "WA_INBOUND_RECEIVED": "WhatsApp recebido",
    "WA_OUTBOUND_SENT": "WhatsApp enviado",
    "WA_CAMPAIGN_SENT": "Campanha WhatsApp",
    "REFERRAL_CREATED": "Indicação criada",
    "REFERRAL_CONVERTED": "Indicação convertida",
    "PARTNER_QR_REDEEMED": "Parceiro resgatado",
    "EQUIPMENT_ASSIGNED": "Equipamento atribuído",
    "EQUIPMENT_RETURNED": "Equipamento devolvido",
    "ONU_OFFLINE": "ONU offline",
    "ONU_ONLINE": "ONU online",
    "SIGNAL_DEGRADED": "Sinal degradado",
    "ONU_LOW_SIGNAL": "ONU sinal baixo",
    "VLAN_SATURATED": "VLAN saturada",
    "CTO_DEGRADED": "CTO degradada",
    "CTO_CRITICAL": "CTO crítica",
    "COLLECTIVE_OUTAGE": "Queda coletiva",
    "CLIENT_OFFLINE": "Cliente offline",
    "CLIENT_ONLINE": "Cliente online",
    "TECHNICIAN_STARTED": "Técnico iniciou",
    "TECHNICIAN_FINISHED": "Técnico finalizou",
    "TECHNICIAN_LATE": "Técnico atrasado",
    "GPS_ROUTE_DEVIATION": "Desvio de rota",
    "TECH_PRODUCTIVITY_DROP": "Queda de produtividade",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


async def coverage_report(
    company_id: str, window_days: int = 7
) -> Dict[str, Any]:
    """Cobertura por domínio: % de event_types com ao menos 1 evento."""
    since = _iso(_now() - timedelta(days=window_days))
    pipe = [
        {"$match": {"company_id": company_id, "timestamp": {"$gte": since}}},
        {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
    ]
    seen: Dict[str, int] = {}
    async for r in db.motor_ia_events.aggregate(pipe):
        seen[r["_id"]] = r["count"]

    domains_report = {}
    total_expected = 0
    total_covered = 0
    for dom, types in EXPECTED_BY_DOMAIN.items():
        covered = [t for t in types if t in seen]
        domains_report[dom] = {
            "expected": types,
            "covered": covered,
            "missing": [t for t in types if t not in seen],
            "coverage_pct": round(len(covered) / len(types) * 100, 1),
            "event_count": sum(seen.get(t, 0) for t in types),
        }
        total_expected += len(types)
        total_covered += len(covered)
    overall = round(total_covered / max(total_expected, 1) * 100, 2)
    return {
        "company_id": company_id,
        "window_days": window_days,
        "overall_coverage_pct": overall,
        "total_expected_types": total_expected,
        "total_covered_types": total_covered,
        "domains": domains_report,
        "level": ("VERDE" if overall >= 90 else
                  "AMARELO" if overall >= 60 else "VERMELHO"),
    }


async def top_events(
    company_id: str, *, hours: int = 24, limit: int = 20
) -> List[Dict[str, Any]]:
    """Top eventos por contagem nas últimas N horas."""
    since = _iso(_now() - timedelta(hours=hours))
    pipe = [
        {"$match": {"company_id": company_id, "timestamp": {"$gte": since}}},
        {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": limit},
    ]
    res = []
    async for r in db.motor_ia_events.aggregate(pipe):
        res.append({
            "event_type": r["_id"],
            "label": FRIENDLY_NAMES.get(r["_id"], r["_id"]),
            "count": r["count"],
        })
    return res


async def events_by_domain(
    company_id: str, *, hours: int = 24
) -> Dict[str, int]:
    """Soma por domínio nas últimas N horas."""
    since = _iso(_now() - timedelta(hours=hours))
    pipe = [
        {"$match": {"company_id": company_id, "timestamp": {"$gte": since}}},
        {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
    ]
    by_type: Dict[str, int] = {}
    async for r in db.motor_ia_events.aggregate(pipe):
        by_type[r["_id"]] = r["count"]
    out: Dict[str, int] = {dom: 0 for dom in EXPECTED_BY_DOMAIN}
    out["outros"] = 0
    for et, n in by_type.items():
        bucketed = False
        for dom, types in EXPECTED_BY_DOMAIN.items():
            if et in types:
                out[dom] += n
                bucketed = True
                break
        if not bucketed:
            out["outros"] += n
    return out


async def events_per_company(*, hours: int = 24) -> List[Dict[str, Any]]:
    """Eventos por tenant (super admin)."""
    since = _iso(_now() - timedelta(hours=hours))
    pipe = [
        {"$match": {"timestamp": {"$gte": since}}},
        {"$group": {"_id": "$company_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    res = []
    async for r in db.motor_ia_events.aggregate(pipe):
        res.append({"company_id": r["_id"] or "_unknown", "count": r["count"]})
    return res


async def timeline_today(
    company_id: str, *, limit: int = 80
) -> List[Dict[str, Any]]:
    """Timeline corporativa: últimos eventos + decisões + actions."""
    today = _now().date().isoformat()
    cur_e = db.motor_ia_events.find(
        {"company_id": company_id,
         "timestamp": {"$gte": today + "T00:00:00"}}
    ).sort("timestamp", -1).limit(limit)
    items: List[Dict[str, Any]] = []
    async for d in cur_e:
        items.append({
            "kind": "event",
            "ts": d.get("timestamp"),
            "event_type": d.get("event_type"),
            "label": FRIENDLY_NAMES.get(d.get("event_type"),
                                          d.get("event_type")),
            "severity": d.get("severity"),
            "payload": d.get("payload"),
            "source": d.get("source"),
        })
    cur_d = db.motor_ia_decisions.find(
        {"company_id": company_id}
    ).sort("created_at", -1).limit(20)
    async for d in cur_d:
        items.append({
            "kind": "decision",
            "ts": d.get("created_at"),
            "label": d.get("kind") or "AI decision",
            "rationale": d.get("rationale"),
        })
    cur_a = db.motor_ia_actions.find(
        {"company_id": company_id}
    ).sort("created_at", -1).limit(20)
    async for d in cur_a:
        items.append({
            "kind": "action",
            "ts": d.get("created_at"),
            "label": d.get("action_type"),
            "status": d.get("status"),
        })
    items.sort(key=lambda x: x.get("ts") or "", reverse=True)
    return items[:limit]


async def what_happened_today(company_id: str) -> Dict[str, Any]:
    """Resposta autônoma do Presidente IA:
       "O que aconteceu na empresa hoje?"
    """
    by_dom = await events_by_domain(company_id, hours=24)
    top = await top_events(company_id, hours=24, limit=5)
    cov = await coverage_report(company_id, window_days=1)
    today_total = sum(by_dom.values())
    headline = f"{today_total} eventos nas últimas 24h."
    bullets = []
    sorted_doms = sorted(by_dom.items(), key=lambda x: -x[1])
    for dom, cnt in sorted_doms:
        if cnt <= 0 or dom == "outros":
            continue
        bullets.append(f"{dom.capitalize()}: {cnt} eventos")
    return {
        "headline": headline,
        "bullets": bullets,
        "top": top[:5],
        "domain_counts": by_dom,
        "coverage_today_pct": cov["overall_coverage_pct"],
        "coverage_level": cov["level"],
        "generated_at": _iso(_now()),
    }
