"""
smartolt_predictive.py — V6.0 Bloco 8
Preditor de falhas de rede ANTES do cliente reclamar.
Antecipa CTO crítica, PON crítica, VLAN crítica, churn por sinal.
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "infra-team",
    "domain": "rede",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from database import db


def _now(): return datetime.now(timezone.utc)


async def predict_cto_failures(company_id: str,
                                 limit: int = 50) -> List[Dict[str, Any]]:
    """Identifica CTOs em risco. Score baseado em:
       - % de ONUs offline/LOS na CTO
       - histórico de tickets na zona
       - taxa de churn por zone"""
    pipe = [
        {"$match": {"company_id": company_id,
                     "smartolt_onu_zone": {"$nin": [None, ""]}}},
        {"$group": {
            "_id": "$smartolt_onu_zone",
            "total":   {"$sum": 1},
            "online":  {"$sum": {"$cond": [
                {"$eq": ["$smartolt_onu_status", "Online"]}, 1, 0]}},
            "offline": {"$sum": {"$cond": [
                {"$in": ["$smartolt_onu_status",
                          ["Offline", "LOS", "Power fail"]]}, 1, 0]}},
            "mrr":     {"$sum": "$plan_price"},
        }},
        {"$match": {"total": {"$gte": 3}}},
    ]
    rows = await db.subscribers.aggregate(pipe).to_list(500)

    # Tickets últimos 30d por zona
    cutoff = (_now() - timedelta(days=30)).isoformat()
    tk_pipe = [
        {"$match": {"company_id": company_id,
                     "created_at": {"$gte": cutoff}}},
        {"$lookup": {"from": "subscribers",
                       "localField": "client_id",
                       "foreignField": "id", "as": "s"}},
        {"$unwind": "$s"},
        {"$group": {"_id": "$s.smartolt_onu_zone",
                     "tickets": {"$sum": 1}}},
    ]
    tk_map = {}
    async for t in db.tickets.aggregate(tk_pipe):
        if t["_id"]: tk_map[t["_id"]] = t["tickets"]

    out: List[Dict[str, Any]] = []
    for r in rows:
        zone = r["_id"]
        total = r["total"]
        offline_pct = r["offline"] / max(total, 1) * 100
        tickets = tk_map.get(zone, 0)
        ticket_rate = tickets / max(total, 1)
        mrr = float(r.get("mrr") or 0)

        # Score 0-100: maior = mais crítico
        score = min(
            offline_pct * 0.6              # peso degradação
            + min(ticket_rate * 30, 30)     # peso tickets recentes
            + (10 if total > 20 else 5),     # peso tamanho da zona
            100)
        if score < 25:
            severity = "OK"
        elif score < 50:
            severity = "ATENCAO"
        elif score < 75:
            severity = "ALTO"
        else:
            severity = "CRITICO"

        if severity == "OK":
            continue

        # Causa / efeito / impacto (XAI obrigatório)
        cause_parts = []
        if offline_pct > 10: cause_parts.append(
            f"{offline_pct:.1f}% das ONUs offline")
        if ticket_rate > 0.2: cause_parts.append(
            f"{tickets} tickets nos últimos 30d")
        if total > 30: cause_parts.append(
            f"zona grande ({total} clientes)")
        cause = " · ".join(cause_parts) or "Padrão de degradação detectado"

        impact_BRL_mensal = round(mrr * (offline_pct / 100) * 0.6, 2)

        out.append({
            "kind": "cto_at_risk",
            "zone": zone,
            "severity": severity,
            "score": round(score, 1),
            "subscribers_total": total,
            "subscribers_offline": r["offline"],
            "offline_pct": round(offline_pct, 1),
            "tickets_last_30d": tickets,
            "ticket_rate": round(ticket_rate, 3),
            "monthly_mrr_BRL": round(mrr, 2),
            "impact_BRL_monthly": impact_BRL_mensal,
            "cause": cause,
            "effect": "Risco de churn em massa e tickets reativos",
            "impact": (f"R$ {impact_BRL_mensal:.2f}/mês de receita em risco "
                        f"+ degradação NPS"),
            "recommended_action": (
                "Visita preventiva à CTO" if severity == "ALTO"
                else "URGENTE: manutenção emergencial na CTO"),
            "confidence": min(round(score / 100, 2), 0.95),
            "evidence": [
                {"type": "offline_pct", "value": round(offline_pct, 1)},
                {"type": "tickets_30d", "value": tickets},
                {"type": "subs_total", "value": total},
            ],
        })

    out.sort(key=lambda x: -x["score"])
    return out[:limit]


async def predict_recurrent_onu_failures(
        company_id: str, limit: int = 30) -> List[Dict[str, Any]]:
    """ONUs com histórico recorrente de queda → vão cair de novo."""
    cutoff = (_now() - timedelta(days=14)).isoformat()
    pipe = [
        {"$match": {"company_id": company_id,
                     "created_at": {"$gte": cutoff},
                     "title": {"$regex": "ONU|sinal|conex", "$options": "i"}}},
        {"$group": {"_id": "$client_id", "incidents": {"$sum": 1}}},
        {"$match": {"incidents": {"$gte": 2}}},
        {"$sort": {"incidents": -1}},
        {"$limit": limit},
    ]
    rows = await db.tickets.aggregate(pipe).to_list(limit)
    out = []
    for r in rows:
        sub = await db.subscribers.find_one(
            {"id": r["_id"], "company_id": company_id},
            {"plan_price": 1, "smartolt_onu_status": 1,
             "smartolt_onu_zone": 1, "name": 1})
        if not sub: continue
        price = float(sub.get("plan_price") or 0)
        incidents = r["incidents"]
        out.append({
            "kind": "onu_recurrent",
            "subscriber_id": r["_id"],
            "incidents_14d": incidents,
            "zone": sub.get("smartolt_onu_zone"),
            "current_onu_status": sub.get("smartolt_onu_status"),
            "monthly_plan_BRL": price,
            "impact_BRL_yearly": round(price * 12 * 0.5, 2),
            "cause": f"{incidents} incidentes em 14 dias",
            "effect": "Cliente próximo de cancelar",
            "impact": (f"Risco churn → perda R$ {price * 12 * 0.5:.2f}/ano"),
            "recommended_action": "Troca preventiva de equipamento + visita",
            "confidence": min(0.5 + incidents * 0.1, 0.95),
            "evidence": [
                {"type": "tickets_count_14d", "value": incidents},
                {"type": "onu_status",
                  "value": sub.get("smartolt_onu_status")},
            ],
        })
    return out


async def predict_signal_churn(company_id: str,
                                 limit: int = 30) -> List[Dict[str, Any]]:
    """Clientes com sinal degradado prolongado → churn alto."""
    cur = db.subscribers.find(
        {"company_id": company_id,
          "status": "ATIVO",
          "smartolt_onu_status": {"$in": ["LOS", "Power fail"]}},
        {"id": 1, "plan_price": 1, "smartolt_onu_zone": 1,
         "smartolt_onu_status": 1}).limit(limit)
    out = []
    async for s in cur:
        price = float(s.get("plan_price") or 0)
        out.append({
            "kind": "signal_churn",
            "subscriber_id": s["id"],
            "zone": s.get("smartolt_onu_zone"),
            "onu_status": s.get("smartolt_onu_status"),
            "monthly_plan_BRL": price,
            "impact_BRL_monthly": price,
            "cause": (f"ONU em estado {s.get('smartolt_onu_status')} "
                        "prolongado"),
            "effect": "Cliente sem serviço — provável cancelamento",
            "impact": f"Risco mensal R$ {price:.2f}",
            "recommended_action": "Contato proativo + visita técnica",
            "confidence": 0.85,
            "evidence": [
                {"type": "onu_status",
                  "value": s.get("smartolt_onu_status")},
                {"type": "subscriber_status", "value": "ATIVO"},
            ],
        })
    return out


async def predictive_summary(company_id: str) -> Dict[str, Any]:
    cto = await predict_cto_failures(company_id, limit=20)
    onu = await predict_recurrent_onu_failures(company_id, limit=20)
    sig = await predict_signal_churn(company_id, limit=20)
    total_BRL = (
        sum(x["impact_BRL_monthly"] for x in cto) +
        sum(x["impact_BRL_monthly"] for x in sig)
    )
    critical_ctos = sum(1 for x in cto if x["severity"] == "CRITICO")
    return {
        "generated_at": _now().isoformat(),
        "headline": (
            f"{critical_ctos} CTO(s) crítica(s) · "
            f"{len(cto)} CTO(s) em risco · "
            f"{len(onu)} ONU(s) recorrentes · "
            f"{len(sig)} sinais críticos · "
            f"R$ {total_BRL:,.2f}/mês em risco técnico"
        ),
        "ctos_at_risk":         cto,
        "recurrent_onus":       onu,
        "signal_churn_risks":   sig,
        "total_monthly_risk_BRL": round(total_BRL, 2),
        "summary": {
            "ctos_at_risk":       len(cto),
            "ctos_critical":      critical_ctos,
            "recurrent_onus":     len(onu),
            "signal_churn_risks": len(sig),
        },
    }


async def auto_create_preventive_tickets(
        company_id: str, max_tickets: int = 10) -> Dict[str, Any]:
    """Cria tickets preventivos para os top N riscos."""
    import uuid
    preds = await predictive_summary(company_id)
    created = []

    # Critical CTOs primeiro
    for c in preds["ctos_at_risk"][:max_tickets]:
        if c["severity"] not in ("ALTO", "CRITICO"):
            continue
        tk_id = f"tk-pred-{uuid.uuid4().hex[:10]}"
        await db.tickets.insert_one({
            "id": tk_id, "company_id": company_id,
            "status": "aberta",
            "priority": "ALTA" if c["severity"] == "CRITICO" else "MEDIA",
            "title": f"Preditivo · CTO {c['zone']} em estado "
                      f"{c['severity']}",
            "description": (f"Causa: {c['cause']}. "
                              f"Ação: {c['recommended_action']}. "
                              f"Impacto: {c['impact']}"),
            "origin": "smartolt_predictive",
            "created_at": _now().isoformat(),
            "_predictive_kind": c["kind"],
            "_predictive_zone": c["zone"],
            "_predictive_confidence": c["confidence"],
        })
        created.append({"ticket_id": tk_id, "zone": c["zone"],
                          "severity": c["severity"]})

    return {"created": len(created), "tickets": created,
             "generated_at": _now().isoformat()}
