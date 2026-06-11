"""AI TRIBUNAL — rastreabilidade completa de decisões da Isabella.

Toda decisão tem:
  • o que VIU (evidence_at_open)
  • o que CONCLUIU (score + probability + reason_codes)
  • o que RECOMENDOU (recommended_action)
  • o que EXECUTOU (campaign/opp executed → send_result)
  • ROI esperado vs realizado
  • confidence (learning_engine)
  • acertou? errou? (result do outcome)

Endpoint consultivo: agrega tudo num único explainability report.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "shield",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db

log = logging.getLogger("ponto.ai_tribunal")


def _now():
    return datetime.now(timezone.utc).isoformat()


async def explain_opportunity(opp_id: str) -> Optional[Dict[str, Any]]:
    """Retorna o dossiê completo de uma oportunidade Isabella."""
    opp = await db.isabella_commander_opportunities.find_one(
        {"id": opp_id}, {"_id": 0})
    if not opp:
        return None
    outc = await db.isabella_outcomes.find_one(
        {"opp_id": opp_id}, {"_id": 0})
    weight = None
    if outc:
        k = outc.get("kind") or ""
        sub = outc.get("subkind") or "_"
        pb = outc.get("playbook") or "_"
        w = await db.isabella_playbook_weights.find_one(
            {"company_id": opp["company_id"], "kind": k,
             "subkind": sub, "playbook": pb},
            {"_id": 0})
        if w:
            weight = {"weight": w.get("weight"),
                      "confidence": w.get("confidence"),
                      "attempts": w.get("attempts"),
                      "successes": w.get("successes"),
                      "failures": w.get("failures")}
    return {
        "opportunity_id": opp_id,
        "company_id": opp["company_id"],
        "kind": opp["kind"], "subkind": opp.get("subkind"),
        "what_isabella_saw": opp.get("evidence") or {},
        "what_isabella_concluded": {
            "score": opp.get("score"),
            "probability": opp.get("probability"),
            "reason_codes": opp.get("reason_codes") or [],
        },
        "what_isabella_recommended": opp.get("recommended_action") or {},
        "human_decision": {
            "status": opp.get("status"),
            "approved_by": opp.get("approved_by"),
            "approved_at": opp.get("approved_at"),
            "dismissed_by": opp.get("dismissed_by"),
            "dismiss_notes": opp.get("dismiss_notes"),
        },
        "execution": {
            "executed_at": opp.get("executed_at"),
            "execution_result": opp.get("execution_result"),
        },
        "outcome": outc,
        "roi": {
            "expected_brl": opp.get("impact_brl"),
            "real_brl": (outc or {}).get("roi_real_brl"),
        },
        "isabella_correctness": ((outc or {}).get("result")
                                  if outc else "no_outcome_yet"),
        "learning_state": weight,
        "explained_at": _now(),
    }


async def explain_campaign(campaign_id: str) -> Optional[Dict[str, Any]]:
    camp = await db.experience_campaigns.find_one(
        {"id": campaign_id}, {"_id": 0})
    if not camp:
        return None
    audit = await db.experience_campaigns_audit.find(
        {"campaign_id": campaign_id}, {"_id": 0}) \
        .sort("at", 1).to_list(200)
    return {
        "campaign_id": campaign_id,
        "company_id": camp["company_id"],
        "what_isabella_detected": {
            "event_key": camp["event_key"],
            "template_id": camp["template_id"],
        },
        "what_isabella_proposed": {
            "message": camp["message"],
            "channel": camp.get("channel"),
            "warnings": camp.get("message_warnings") or [],
        },
        "human_authorization": {
            "approval_level": camp["approval_level"],
            "auto_execute": camp.get("auto_execute"),
            "status": camp["status"],
            "approvals": camp.get("approvals") or [],
        },
        "council_review": camp.get("council_review"),
        "execution": {
            "executed_at": camp.get("executed_at"),
            "executed_by": camp.get("executed_by"),
            "send_result": camp.get("send_result"),
        },
        "roi": {
            "expected_brl": camp.get("expected_roi_brl"),
            "real_cost_brl": camp.get("real_cost_brl"),
        },
        "audit_trail": audit,
        "explained_at": _now(),
    }


async def list_recent_decisions(company_id: str, *,
                                    limit: int = 50) -> List[Dict[str, Any]]:
    opps = await db.isabella_commander_opportunities.find(
        {"company_id": company_id,
         "status": {"$in": ["approved", "executed", "dismissed"]}},
        {"_id": 0, "id": 1, "kind": 1, "subkind": 1, "score": 1,
         "status": 1, "target_label": 1, "approved_at": 1,
         "approved_by": 1, "impact_brl": 1}
    ).sort("approved_at", -1).limit(min(limit, 200)) \
        .to_list(min(limit, 200))
    return opps
