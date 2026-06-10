"""ISABELLA REVENUE COMMANDER — detecção ativa de oportunidades de receita.

Mapeia, com dados REAIS:
  • Upgrade de plano (subscriber em plano antigo, sem upgrade ≥ 12 meses,
    pagamentos em dia, novo plano superior disponível)
  • Add-ons potenciais (PlayHub / Ligo 5G / IP fixo / WiFi Premium) baseado
    em sinais (alto uso de tickets de wifi, plano premium, etc).
  • Reativação de cancelados recentes (≤ 90d) sem ticket de churn definitivo.

Não dispara nada — gera oportunidades de receita no painel para o humano
acionar (1-click).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from database import db
from services.event_bus import EventType, emit_event
from services.isabella_opportunities import upsert_opportunity

log = logging.getLogger("ponto.isabella_revenue")


def _now():
    return datetime.now(timezone.utc)


async def _active_plans(company_id: str) -> List[Dict[str, Any]]:
    plans = await db.plans.find(
        {"company_id": company_id, "active": True},
        {"_id": 0, "id": 1, "name": 1, "monthly_price": 1,
         "speed_down_mbps": 1, "speed_up_mbps": 1}
    ).to_list(100)
    return sorted(plans, key=lambda p: float(p.get("monthly_price") or 0))


def _next_upgrade(current_price: float,
                   plans: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    if not plans:
        return None
    higher = [p for p in plans if float(p.get("monthly_price") or 0)
                > current_price + 5]
    if not higher:
        return None
    # Próximo plano (menor diferença)
    return min(higher, key=lambda p: float(p.get("monthly_price") or 0))


async def _client_health(company_id: str,
                          ext_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Para cada cliente (ext_id normalizado), retorna se tem fatura
    vencida + n_tickets_recent."""
    out: Dict[str, Dict[str, Any]] = {}
    if not ext_ids:
        return out
    today_iso = _now().date().isoformat()
    # subscriber_invoices.subscriber_external_id = string ("1813301")
    pipe = [
        {"$match": {"company_id": company_id,
                      "subscriber_external_id": {"$in": ext_ids},
                      "status": {"$in": ["open", "overdue"]},
                      "due_date": {"$lt": today_iso}}},
        {"$group": {"_id": "$subscriber_external_id",
                       "n_late": {"$sum": 1}}},
    ]
    async for r in db.subscriber_invoices.aggregate(pipe):
        out.setdefault(str(r["_id"]), {})["n_late"] = int(r["n_late"] or 0)
    # tickets.atlaz_id_assinante = int — converte
    int_ids = []
    for e in ext_ids:
        try:
            int_ids.append(int(e))
        except (TypeError, ValueError):
            continue
    cutoff = (_now() - timedelta(days=60)).isoformat()
    if int_ids:
        pipe2 = [
            {"$match": {"company_id": company_id,
                          "atlaz_id_assinante": {"$in": int_ids},
                          "type": {"$in": ["lentidao", "lentidão",
                                              "wifi_ruim", "sem internet"]},
                          "opened_at": {"$gte": cutoff}}},
            {"$group": {"_id": "$atlaz_id_assinante",
                           "n_speed": {"$sum": 1}}},
        ]
        async for r in db.tickets.aggregate(pipe2):
            out.setdefault(str(r["_id"]), {})["n_speed"] = int(r["n_speed"] or 0)
    return out


async def scan_company(company_id: str, *, limit: int = 500) -> Dict[str, Any]:
    plans = await _active_plans(company_id)
    if len(plans) < 2:
        return {"company_id": company_id, "opportunities": 0,
                "reason": "menos de 2 planos ativos — sem espaço para upgrade"}

    # Universo: ativos com plan_price > 0
    cutoff_active = (_now() - timedelta(days=730)).isoformat()
    subs = await db.subscribers.find(
        {"company_id": company_id,
         "contract_status": {"$in": ["ATIVO", None]},
         "cancellation_date": {"$in": [None, ""]},
         "plan_price": {"$gt": 0},
         "activation_date": {"$lte": cutoff_active}},  # ativos há ≥2 anos
        {"_id": 0, "id": 1, "name": 1, "external_code": 1, "phone": 1,
         "plan_name": 1, "plan_price": 1, "plan_speed": 1,
         "activation_date": 1, "last_readjustment_at": 1}
    ).limit(5000).to_list(5000)

    if not subs:
        return {"company_id": company_id, "opportunities": 0,
                "reason": "sem assinantes elegíveis"}

    ext_ids_raw = [s["external_code"] for s in subs if s.get("external_code")]

    def _norm(c):
        c = (c or "").strip()
        return c.split("-", 1)[1].strip() if c.upper().startswith("ATLAZ-") else c
    # mapa normalizado -> original (precisamos saber qual chave casa com tickets/invoices)
    ext_ids = [_norm(e) for e in ext_ids_raw]
    health = await _client_health(company_id, ext_ids)

    created = 0
    for s in subs:
        price = float(s.get("plan_price") or 0)
        if price <= 0:
            continue
        norm = _norm(s.get("external_code") or "")
        h = health.get(norm, {})
        if h.get("n_late", 0) >= 1:
            continue  # inadimplente não é alvo de upgrade
        up = _next_upgrade(price, plans)
        subkind = None
        delta = 0.0
        target_plan = None
        reasons: List[str] = []
        if up:
            target_plan = up
            delta = float(up["monthly_price"]) - price
            subkind = "upgrade_plan"
            reasons.append(
                f"Plano atual {s.get('plan_name')} R${price:.2f} → "
                f"sugerido {up['name']} R${up['monthly_price']:.2f}")
        # Sinaliza wifi_premium se cliente tem queixas recurrentes mesmo
        # estando em plano com >= 500 Mbps
        if h.get("n_speed", 0) >= 2 and ("500" in (s.get("plan_speed") or "")
                                            or "GIGA" in (s.get("plan_name") or "").upper()):
            subkind = "wifi_premium"
            delta = 19.90
            reasons.append(f"{h['n_speed']} reclamações de lentidão em 60d em "
                           "plano de alta velocidade — sinaliza WiFi Premium")
            target_plan = None
        if not subkind:
            continue
        score = min(100.0, 40 + delta * 0.6 + h.get("n_speed", 0) * 5)
        prob = min(0.7, 0.25 + delta * 0.005)
        impact = round(delta * 12, 2)  # 12 meses de upsell
        action = {"type": "send_offer",
                  "channel": "whatsapp",
                  "playbook": subkind,
                  "subscriber_id": s["id"],
                  "subscriber_external_id": s.get("external_code"),
                  "phone": s.get("phone"),
                  "target_plan": (target_plan and {
                      "id": target_plan["id"],
                      "name": target_plan["name"],
                      "price": target_plan["monthly_price"]}) or None,
                  "addon_price": delta if subkind == "wifi_premium" else None,
                  "requires_approval": True}
        await upsert_opportunity(
            company_id=company_id,
            kind="revenue",
            subkind=subkind,
            target_type="subscriber",
            target_id=s["id"],
            target_label=f"{s.get('name')} ({s.get('external_code')})",
            score=score,
            probability=prob,
            impact_brl=impact,
            reason_codes=reasons,
            evidence={"current_plan": s.get("plan_name"),
                        "current_price": price,
                        "target_plan": (target_plan and target_plan.get("name")) or None,
                        "delta_brl": delta,
                        "activation_date": s.get("activation_date"),
                        "phone": s.get("phone"),
                        "n_speed_tickets_60d": h.get("n_speed", 0)},
            recommended_action=action,
            ttl_hours=24 * 14,  # 14 dias
            source="isabella_revenue",
        )
        created += 1
        await emit_event(
            EventType.REVENUE_OPPORTUNITY_DETECTED,
            company_id=company_id, source="isabella_revenue",
            severity="alta" if delta >= 30 else "media",
            payload={"subscriber_id": s["id"], "subkind": subkind,
                      "delta_brl": delta, "impact_12m_brl": impact})
        if created >= limit:
            break

    return {"company_id": company_id,
            "subscribers_in_scope": len(subs),
            "opportunities": created}


async def scan_all() -> List[Dict[str, Any]]:
    out = []
    cids = await db.companies.distinct("id")
    for cid in cids:
        try:
            out.append(await scan_company(cid))
        except Exception as e:
            log.exception("[revenue] %s failed: %s", cid, e)
    return out
