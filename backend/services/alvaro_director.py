"""
alvaro_director.py — FASE 7 da Constituição V4.0
Álvaro IA: Diretor de Operações Digital.

Responde:
  1. Quem está produzindo? (ranking técnicos)
  2. Quem está atrasado?
  3. Onde tem gargalo?
  4. Onde tem desperdício?
  5. Qual decisão hoje?
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

import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from database import db


def _now(): return datetime.now(timezone.utc)
def _iso(d=None): return (d or _now()).astimezone(timezone.utc).isoformat()


async def technician_ranking(company_id: str) -> List[Dict[str, Any]]:
    """Score 0-100 por técnico (assigned_to do tickets)."""
    pipe = [
        {"$match": {"company_id": company_id,
                     "assigned_to": {"$nin": [None, ""]}}},
        {"$group": {
            "_id": "$assigned_to",
            "total": {"$sum": 1},
            "closed": {"$sum": {"$cond": [
                {"$in": ["$status", ["encerrada", "finalizada",
                                       "closed", "completed"]]},
                1, 0]}},
        }},
        {"$sort": {"total": -1}},
        {"$limit": 50},
    ]
    out: List[Dict[str, Any]] = []
    async for r in db.tickets.aggregate(pipe):
        total = r["total"]
        closed = r["closed"]
        rate = (closed / max(total, 1)) * 100
        volume_bonus = min(total / 50 * 30, 30)  # +30 por volume
        score = round(rate * 0.7 + volume_bonus, 1)
        out.append({
            "collaborator_id": r["_id"],
            "total_tickets": total,
            "closed": closed,
            "closure_rate": round(rate, 1),
            "score": min(score, 100),
            "level": ("DESTAQUE" if score >= 80
                       else "ATENCAO" if score < 50 else "REGULAR"),
        })
    out.sort(key=lambda x: -x["score"])
    return out


async def region_ranking(company_id: str) -> List[Dict[str, Any]]:
    """Score por zona (smartolt_onu_zone)."""
    pipe = [
        {"$match": {"company_id": company_id,
                     "smartolt_onu_zone": {"$nin": [None, ""]}}},
        {"$group": {
            "_id": "$smartolt_onu_zone",
            "subs": {"$sum": 1},
            "bad_onus": {"$sum": {"$cond": [
                {"$in": ["$smartolt_onu_status",
                          ["Offline", "LOS", "Power fail"]]}, 1, 0]}},
        }},
        {"$sort": {"subs": -1}},
        {"$limit": 30},
    ]
    out = []
    async for r in db.subscribers.aggregate(pipe):
        subs = r["subs"]; bad = r["bad_onus"]
        # tickets nessa zona
        sub_ids = await db.subscribers.distinct(
            "id", {"company_id": company_id,
                    "smartolt_onu_zone": r["_id"]})
        tickets_n = await db.tickets.count_documents(
            {"company_id": company_id,
             "client_id": {"$in": sub_ids}})
        # score: 100 - penalidade
        bad_pct = bad / max(subs, 1) * 100
        tk_per_sub = tickets_n / max(subs, 1)
        score = max(100 - bad_pct - tk_per_sub * 20, 0)
        out.append({
            "region": r["_id"],
            "subscribers": subs,
            "bad_onus": bad,
            "tickets": tickets_n,
            "score": round(score, 1),
            "level": ("CRITICA" if score < 60
                       else "ATENCAO" if score < 80 else "SAUDAVEL"),
        })
    out.sort(key=lambda x: x["score"])  # piores primeiro
    return out


async def bottlenecks(company_id: str) -> List[Dict[str, Any]]:
    """Detecta gargalos operacionais."""
    items = []
    # 1. SLA em risco: tickets abertos > 48h
    cutoff = (_now() - timedelta(hours=48)).isoformat()
    sla_risk = await db.tickets.count_documents({
        "company_id": company_id,
        "status": {"$nin": ["encerrada", "finalizada",
                              "closed", "completed"]},
        "opened_at": {"$lte": cutoff},
    })
    if sla_risk > 0:
        items.append({
            "type": "SLA_BREACH_RISK", "count": sla_risk,
            "severity": "alta",
            "description": f"{sla_risk} tickets abertos há mais de 48h",
        })
    # 2. Técnicos sobrecarregados (>15 tickets abertos)
    pipe = [
        {"$match": {"company_id": company_id,
                     "assigned_to": {"$nin": [None, ""]},
                     "status": {"$nin": ["encerrada", "finalizada",
                                          "closed", "completed"]}}},
        {"$group": {"_id": "$assigned_to", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gte": 15}}},
    ]
    overloaded = []
    async for r in db.tickets.aggregate(pipe):
        overloaded.append({"collaborator_id": r["_id"], "open": r["n"]})
    if overloaded:
        items.append({
            "type": "TECHNICIAN_OVERLOAD",
            "count": len(overloaded),
            "severity": "media",
            "description": f"{len(overloaded)} técnicos com 15+ tickets abertos",
            "detail": overloaded,
        })
    # 3. Regiões críticas
    regions = await region_ranking(company_id)
    critical = [r for r in regions if r["level"] == "CRITICA"]
    if critical:
        items.append({
            "type": "REGION_CRITICAL", "count": len(critical),
            "severity": "alta",
            "description": (f"{len(critical)} regiões críticas: "
                              f"{', '.join(r['region'] for r in critical[:3])}"),
        })
    return items


async def waste_detection(company_id: str) -> Dict[str, Any]:
    """Onde estamos perdendo dinheiro/produtividade?"""
    # Tickets de retrabalho (mesmo client_id 3+ tickets em 30d)
    cutoff = (_now() - timedelta(days=30)).isoformat()
    pipe = [
        {"$match": {"company_id": company_id,
                     "created_at": {"$gte": cutoff}}},
        {"$group": {"_id": "$client_id", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gte": 3}}},
    ]
    rework = []
    async for r in db.tickets.aggregate(pipe):
        rework.append({"client_id": r["_id"], "tickets": r["n"]})
    # Visitas técnicas em ONU saudável (desperdício)
    healthy_onu_tickets = 0
    if rework:
        for r in rework[:50]:
            sub = await db.subscribers.find_one(
                {"id": r["client_id"], "company_id": company_id})
            if sub and sub.get("smartolt_onu_status") == "Online":
                healthy_onu_tickets += r["tickets"]
    # Faturas inadimplentes sem ação (receita perdida)
    overdue_no_action = await db.subscriber_invoices.count_documents(
        {"company_id": company_id, "status": "overdue"})
    return {
        "clients_with_rework": len(rework),
        "rework_in_healthy_onu": healthy_onu_tickets,
        "overdue_without_dunning": overdue_no_action,
        "waste_summary": (
            f"{len(rework)} clientes com retrabalho (3+ tickets/30d) · "
            f"{healthy_onu_tickets} visitas em ONU saudável (desperdício) · "
            f"{overdue_no_action} faturas overdue sem cobrança automática"
        ),
    }


async def recommendations(company_id: str) -> List[Dict[str, Any]]:
    """Recomendações operacionais com problema/impacto/urgência/ação."""
    recs = []
    bk = await bottlenecks(company_id)
    wt = await waste_detection(company_id)

    for b in bk:
        rec = {
            "id": f"rec-{uuid.uuid4().hex[:10]}",
            "problem": b["description"],
            "impact": ("Risco de churn + reclamação"
                       if b["type"] == "SLA_BREACH_RISK"
                       else "Equipe sobrecarregada"
                       if b["type"] == "TECHNICIAN_OVERLOAD"
                       else "Receita em risco regional"),
            "urgency": b["severity"].upper(),
            "action": ("Realocar tickets antigos + visita prioritária"
                       if b["type"] == "SLA_BREACH_RISK"
                       else "Redistribuir fila entre técnicos"
                       if b["type"] == "TECHNICIAN_OVERLOAD"
                       else "Visita técnica preventiva nas CTOs críticas"),
            "expected_result": ("Reduzir SLA breach"
                                  if b["type"] == "SLA_BREACH_RISK"
                                  else "Equilibrar workload"
                                  if b["type"] == "TECHNICIAN_OVERLOAD"
                                  else "Reduzir churn regional"),
            "confidence": 0.75,
        }
        recs.append(rec)
    if wt["rework_in_healthy_onu"] > 0:
        recs.append({
            "id": f"rec-{uuid.uuid4().hex[:10]}",
            "problem": (f"{wt['rework_in_healthy_onu']} visitas em ONU "
                          f"saudável (desperdício)"),
            "impact": "Custo operacional sem retorno",
            "urgency": "MEDIA",
            "action": "Triagem remota antes de despachar técnico",
            "expected_result": "Reduzir ~40% das visitas evitáveis",
            "confidence": 0.70,
        })
    if wt["overdue_without_dunning"] > 0:
        recs.append({
            "id": f"rec-{uuid.uuid4().hex[:10]}",
            "problem": (f"{wt['overdue_without_dunning']} faturas overdue "
                          f"sem cobrança automática"),
            "impact": "Receita represada",
            "urgency": "ALTA",
            "action": ("Rodar Operação Tese sobre Tier C do Gate SmartOLT "
                        "(blindados)"),
            "expected_result": "R$ recuperado em até 72h (~18% conversão)",
            "confidence": 0.85,
        })
    return recs


async def daily_briefing(company_id: str,
                            kind: str = "07h") -> Dict[str, Any]:
    """Gera relatório executivo. kind ∈ {07h, 12h, 18h}."""
    yesterday = (_now() - timedelta(days=1)).date().isoformat()
    yest_start = yesterday + "T00:00:00"
    yest_end = yesterday + "T23:59:59"

    # Sales / pagamentos / tickets / instalações ontem
    sales = await db.sales_leads.count_documents(
        {"company_id": company_id, "ts": {"$gte": yest_start, "$lt": yest_end}})
    paid = await db.subscriber_invoices.count_documents(
        {"company_id": company_id, "status": "paid",
         "paid_date": {"$gte": yesterday}})
    tickets = await db.tickets.count_documents(
        {"company_id": company_id,
         "opened_at": {"$gte": yest_start, "$lt": yest_end}})
    installs = await db.appointments.count_documents(
        {"company_id": company_id,
         "created_at": {"$gte": yest_start, "$lt": yest_end}})

    # Receita IA (MTD)
    from services.revenue_attribution import summary
    s = await summary(company_id)
    receita_ia = s["_total_BRL"]

    from services.smartolt_twin import revenue_at_risk, cto_health
    rr = await revenue_at_risk(company_id)
    ctos = await cto_health(company_id)
    critical_ctos = len([c for c in ctos if c["score"] < 70])

    # Top técnicos
    techs = await technician_ranking(company_id)
    top_tech = [t for t in techs if t["level"] == "DESTAQUE"][:3]
    atencao_tech = [t for t in techs if t["level"] == "ATENCAO"][:3]

    # Pergunta-resposta por kind
    if kind == "07h":
        question = "O que preciso saber antes de começar o dia?"
        body = (
            f"Ontem: {sales} vendas · {paid} pagamentos · {tickets} tickets · "
            f"{installs} instalações.\n"
            f"Receita IA (MTD): R$ {receita_ia:,.2f}.\n"
            f"Receita em risco: R$ {rr['monthly_BRL_at_risk']:,.2f}/mês.\n"
            f"CTOs críticas: {critical_ctos}.\n"
            f"Destaques: {[t['collaborator_id'] for t in top_tech]}.\n"
            f"Atenção: {[t['collaborator_id'] for t in atencao_tech]}."
        )
    elif kind == "12h":
        bottle = await bottlenecks(company_id)
        question = "O que precisa de atenção agora?"
        body = "\n".join(b["description"] for b in bottle) or "Sem gargalos."
    else:  # 18h
        question = "Como terminou o dia?"
        body = (
            f"Hoje fechou com {tickets} tickets abertos, {paid} pagamentos. "
            f"Receita IA acumulada: R$ {receita_ia:,.2f}."
        )

    doc = {
        "id": f"brf-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "kind": kind,
        "question": question,
        "body": body,
        "metrics": {
            "sales": sales, "paid": paid, "tickets": tickets,
            "installs": installs,
            "receita_ia_MTD": receita_ia,
            "receita_em_risco": rr["monthly_BRL_at_risk"],
            "ctos_criticas": critical_ctos,
            "top_techs": [t["collaborator_id"] for t in top_tech],
            "atencao_techs": [t["collaborator_id"] for t in atencao_tech],
        },
        "generated_at": _iso(),
    }
    await db.motor_ia_daily_briefings.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


async def director_summary(company_id: str) -> Dict[str, Any]:
    """Painel principal do Álvaro: tudo em 1 chamada."""
    techs = await technician_ranking(company_id)
    regions = await region_ranking(company_id)
    bk = await bottlenecks(company_id)
    wt = await waste_detection(company_id)
    recs = await recommendations(company_id)
    return {
        "company_id": company_id,
        "generated_at": _iso(),
        "headline": (
            f"{len(bk)} gargalo(s) detectado(s) · "
            f"{len(recs)} recomendação(ões) ativa(s)"
        ),
        "top_technicians": techs[:5],
        "attention_technicians": [t for t in techs
                                      if t["level"] == "ATENCAO"][:5],
        "region_ranking": regions[:10],
        "bottlenecks": bk,
        "waste": wt,
        "recommendations": recs,
    }
