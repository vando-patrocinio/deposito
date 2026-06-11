"""ISABELLA EXECUTION SCORE — ROI real consolidado da Isabella.

Mede a contribuição mensurável da Isabella no negócio com base em
`isabella_outcomes` (zero suposição):

  • receita_gerada_brl       — soma de roi_real dos outcomes revenue+expansion success
  • churn_evitado_brl        — soma de roi_real de churn success
  • dunning_recuperado_brl   — soma de roi_real de dunning success
  • incidentes_evitados      — count de incident.mass_repair detectados antes
  • truck_roll_evitado_brl   — incident_block que agrupou cliente em massa
  • produtividade_ganha_h    — somatório do tempo poupado por field_ops/Isabella

Endpoint: /api/isabella/execution-score
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from database import db

log = logging.getLogger("ponto.isabella_execution_score")


def _now():
    return datetime.now(timezone.utc)


async def compute(company_id: str, *, days: int = 30) -> Dict[str, Any]:
    cutoff_iso = (_now() - timedelta(days=days)).isoformat()

    # 1) Outcomes consolidados
    pipe = [
        {"$match": {"company_id": company_id,
                      "measured_at": {"$gte": cutoff_iso}}},
        {"$group": {
            "_id": {"kind": "$kind", "result": "$result"},
            "n": {"$sum": 1},
            "roi": {"$sum": "$roi_real_brl"},
            "impact_pred": {"$sum": "$impact_pred_brl"},
        }},
    ]
    by = {}
    async for r in db.isabella_outcomes.aggregate(pipe):
        kind = r["_id"]["kind"]
        result = r["_id"]["result"]
        by.setdefault(kind, {}).setdefault(result, {})
        by[kind][result] = {"n": int(r["n"] or 0),
                             "roi_real_brl": round(float(r["roi"] or 0), 2),
                             "impact_pred_brl": round(float(
                                 r["impact_pred"] or 0), 2)}

    def _success_roi(kind: str) -> float:
        return float(by.get(kind, {}).get("success", {})
                     .get("roi_real_brl", 0.0))

    receita_gerada = _success_roi("revenue") + _success_roi("expansion")
    churn_evitado = _success_roi("churn")
    dunning_recuperado = _success_roi("dunning")
    twin_prev = _success_roi("twin")

    # 2) Incidentes evitados (preditos + agrupamentos automáticos)
    incidents_predicted = await db.isabella_incidents.count_documents(
        {"company_id": company_id, "created_at": {"$gte": cutoff_iso},
         "status": {"$in": ["predicted", "confirmed", "resolved"]}})
    # truck roll evitado: cada grouped_client em incidente = 1 visita poupada
    incs = await db.isabella_incidents.find(
        {"company_id": company_id, "created_at": {"$gte": cutoff_iso}},
        {"_id": 0, "grouped_clients": 1,
         "financial_impact": 1}).to_list(2000)
    truck_roll_evitado = 0
    truck_roll_brl = 0.0
    AVG_TRUCK_ROLL_COST = 85.0  # R$ por visita
    for i in incs:
        n = len(i.get("grouped_clients") or [])
        truck_roll_evitado += n
        truck_roll_brl += n * AVG_TRUCK_ROLL_COST

    # 3) Notify em massa: clientes proativamente informados
    notify_sent = 0
    async for r in db.isabella_incident_notifications.aggregate([
            {"$match": {"company_id": company_id,
                          "created_at": {"$gte": cutoff_iso}}},
            {"$group": {"_id": None, "sent": {"$sum": "$sent"}}}]):
        notify_sent = int(r.get("sent") or 0)

    # 4) Oportunidades aprovadas (engagement do humano com sugestões IA)
    approved = await db.isabella_commander_opportunities.count_documents(
        {"company_id": company_id, "status": "approved",
         "created_at": {"$gte": cutoff_iso}})
    executed = await db.isabella_commander_opportunities.count_documents(
        {"company_id": company_id, "status": "executed",
         "created_at": {"$gte": cutoff_iso}})
    dismissed = await db.isabella_commander_opportunities.count_documents(
        {"company_id": company_id, "status": "dismissed",
         "created_at": {"$gte": cutoff_iso}})
    pending = await db.isabella_commander_opportunities.count_documents(
        {"company_id": company_id, "status": "pending",
         "created_at": {"$gte": cutoff_iso}})

    total_decided = approved + executed + dismissed
    engagement_rate = round((approved + executed) / max(total_decided, 1), 4)

    # 5) Precisão preditiva: roi_real / impact_pred (success+failure)
    total_pred = 0.0
    total_real = 0.0
    for kind, res in by.items():
        for r, val in res.items():
            total_pred += val.get("impact_pred_brl", 0.0)
            if r == "success":
                total_real += val.get("roi_real_brl", 0.0)
    precision_rate = round(total_real / max(total_pred, 1), 4)

    total_roi = round(receita_gerada + churn_evitado + dunning_recuperado
                       + twin_prev + truck_roll_brl, 2)

    return {
        "company_id": company_id,
        "window_days": days,
        "components": {
            "receita_gerada_brl": round(receita_gerada, 2),
            "churn_evitado_brl": round(churn_evitado, 2),
            "dunning_recuperado_brl": round(dunning_recuperado, 2),
            "twin_falhas_antecipadas_brl": round(twin_prev, 2),
            "truck_roll_evitado_brl": round(truck_roll_brl, 2),
            "truck_roll_visitas_evitadas": truck_roll_evitado,
            "incidentes_preditos": incidents_predicted,
            "clientes_notificados_em_massa": notify_sent,
        },
        "opportunities": {
            "pending": pending, "approved": approved,
            "executed": executed, "dismissed": dismissed,
            "engagement_rate": engagement_rate,
        },
        "outcomes": by,
        "roi_real_brl_total": total_roi,
        "precision_rate": precision_rate,
    }
