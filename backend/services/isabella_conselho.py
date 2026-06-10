"""ISABELLA CONSELHO EXECUTIVO IA — reunião diária consolidada.

Convergência dos Commanders + Presidente IA + Álvaro IA + Rede IA + Router IA.

Gera, para cada empresa, uma **ata** com:
  • Receita prevista (oportunidades Revenue + Expansion impact_brl)
  • Risco financeiro (Churn impact + Dunning total_due)
  • Incidentes ativos (isabella_incidents abertos)
  • Frota / estoque / técnicos (Twin)
  • Decisões priorizadas (top 10 oportunidades pendentes)
  • Riscos críticos (score ≥ 80)

Persistida em `isabella_council_minutes`.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from database import db
from services.event_bus import EventType, emit_event
from services.isabella_opportunities import kpis as opp_kpis

log = logging.getLogger("ponto.isabella_conselho")


def _now():
    return datetime.now(timezone.utc)


async def _top_opps(company_id: str, *, limit: int = 10) -> List[Dict[str, Any]]:
    return await db.isabella_commander_opportunities.find(
        {"company_id": company_id, "status": "pending"},
        {"_id": 0, "id": 1, "kind": 1, "subkind": 1, "target_label": 1,
         "score": 1, "impact_brl": 1, "reason_codes": 1}
    ).sort([("score", -1), ("impact_brl", -1)]).limit(limit).to_list(limit)


async def _open_incidents(company_id: str) -> Dict[str, Any]:
    n = await db.isabella_incidents.count_documents(
        {"company_id": company_id, "status": {"$in": ["predicted", "confirmed"]}})
    critical = await db.isabella_incidents.count_documents(
        {"company_id": company_id,
         "status": {"$in": ["predicted", "confirmed"]},
         "score": {"$gte": 80}})
    return {"total_open": n, "critical": critical}


async def _churn_risk_total(company_id: str) -> Dict[str, Any]:
    pipe = [
        {"$match": {"company_id": company_id, "kind": "churn",
                      "status": "pending"}},
        {"$group": {"_id": None,
                       "n": {"$sum": 1},
                       "impact": {"$sum": "$impact_brl"},
                       "critical": {"$sum": {"$cond": [
                           {"$gte": ["$score", 75]}, 1, 0]}}}},
    ]
    rows = await db.isabella_commander_opportunities.aggregate(pipe).to_list(1)
    if not rows:
        return {"n": 0, "impact_12m_brl": 0.0, "critical": 0}
    r = rows[0]
    return {"n": int(r.get("n") or 0),
            "impact_12m_brl": round(float(r.get("impact") or 0), 2),
            "critical": int(r.get("critical") or 0)}


async def _revenue_expansion_total(company_id: str) -> Dict[str, Any]:
    pipe = [
        {"$match": {"company_id": company_id,
                      "kind": {"$in": ["revenue", "expansion"]},
                      "status": "pending"}},
        {"$group": {"_id": "$kind",
                       "n": {"$sum": 1},
                       "impact": {"$sum": "$impact_brl"}}},
    ]
    out = {"revenue_n": 0, "revenue_impact_brl": 0.0,
            "expansion_n": 0, "expansion_impact_brl": 0.0}
    async for r in db.isabella_commander_opportunities.aggregate(pipe):
        k = r["_id"]
        out[f"{k}_n"] = int(r.get("n") or 0)
        out[f"{k}_impact_brl"] = round(float(r.get("impact") or 0), 2)
    return out


async def _dunning_total(company_id: str) -> Dict[str, Any]:
    pipe = [
        {"$match": {"company_id": company_id, "kind": "dunning",
                      "status": "pending"}},
        {"$group": {"_id": None,
                       "n": {"$sum": 1},
                       "total_due": {"$sum": "$impact_brl"}}},
    ]
    rows = await db.isabella_commander_opportunities.aggregate(pipe).to_list(1)
    if not rows:
        return {"n": 0, "total_due_brl": 0.0}
    return {"n": int(rows[0]["n"] or 0),
            "total_due_brl": round(float(rows[0].get("total_due") or 0), 2)}


def _decisions(top: List[Dict[str, Any]],
                churn: Dict[str, Any],
                dun: Dict[str, Any],
                rev: Dict[str, Any],
                inc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Decisões executivas geradas pelo Conselho — não executa, apenas pauta."""
    out: List[Dict[str, Any]] = []
    if inc["critical"] >= 1:
        out.append({"priority": "P0",
                      "title": f"Tratar {inc['critical']} incidentes críticos abertos",
                      "owner": "Field President",
                      "rationale": "Risco massivo de churn coletivo"})
    if churn["critical"] >= 1:
        out.append({"priority": "P0",
                      "title": f"Acionar retenção em {churn['critical']} clientes alto risco",
                      "owner": "Churn Commander",
                      "rationale": f"R$ {churn['impact_12m_brl']:.0f} de LTV em risco"})
    if dun["total_due_brl"] >= 500:
        out.append({"priority": "P1",
                      "title": f"Recuperar R$ {dun['total_due_brl']:.0f} em inadimplência",
                      "owner": "Dunning Commander",
                      "rationale": f"{dun['n']} contas em régua autônoma"})
    if (rev.get("revenue_impact_brl", 0) + rev.get("expansion_impact_brl", 0)) >= 100:
        out.append({"priority": "P1",
                      "title": f"Capturar R$ {rev.get('revenue_impact_brl', 0):.0f} em upsell "
                               f"+ R$ {rev.get('expansion_impact_brl', 0):.0f} em expansão",
                      "owner": "Revenue + Expansion Commanders",
                      "rationale": "Oportunidades pendentes com aprovação humana"})
    if not out:
        out.append({"priority": "P2",
                      "title": "Operação saudável — manter cadência de varredura",
                      "owner": "Conselho IA",
                      "rationale": "Nenhum alerta acima do threshold"})
    return out


async def hold_meeting(company_id: str) -> Dict[str, Any]:
    """Executa uma reunião do conselho — registra ata e emite evento."""
    top = await _top_opps(company_id)
    inc = await _open_incidents(company_id)
    churn = await _churn_risk_total(company_id)
    rev = await _revenue_expansion_total(company_id)
    dun = await _dunning_total(company_id)
    kpis_all = await opp_kpis(company_id)

    minutes = {
        "id": f"council-{uuid.uuid4().hex[:14]}",
        "company_id": company_id,
        "held_at": _now().isoformat(),
        "agenda": {
            "incidents": inc,
            "churn": churn,
            "dunning": dun,
            "revenue_expansion": rev,
            "opportunities_kpi": kpis_all,
        },
        "top_opportunities": top,
        "decisions": _decisions(top, churn, dun, rev, inc),
        "financial_summary": {
            "revenue_potential_brl": round(
                rev.get("revenue_impact_brl", 0)
                + rev.get("expansion_impact_brl", 0), 2),
            "loss_at_risk_brl": round(
                churn.get("impact_12m_brl", 0)
                + dun.get("total_due_brl", 0), 2),
            "net_outlook_brl": round(
                (rev.get("revenue_impact_brl", 0)
                  + rev.get("expansion_impact_brl", 0))
                - (churn.get("impact_12m_brl", 0)
                    + dun.get("total_due_brl", 0)), 2),
        },
    }
    await db.isabella_council_minutes.insert_one(dict(minutes))
    await emit_event(
        EventType.COUNCIL_MEETING_HELD,
        company_id=company_id, source="isabella_conselho",
        severity="alta",
        payload={"id": minutes["id"],
                  "decisions": [d["title"] for d in minutes["decisions"]],
                  "net_outlook_brl": minutes["financial_summary"]["net_outlook_brl"]})
    minutes.pop("_id", None)
    return minutes


async def hold_all() -> List[Dict[str, Any]]:
    out = []
    cids = await db.companies.distinct("id")
    for cid in cids:
        try:
            out.append(await hold_meeting(cid))
        except Exception as e:
            log.exception("[conselho] %s failed: %s", cid, e)
    return out
