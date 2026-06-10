"""ISABELLA AUDIT — relatórios de governança operacional.

Três produtos do Sistema Nervoso:
  1. learning_report   — evidência matemática de aprendizado por playbook
  2. precision_audit   — comparação previsto × real (rotina diária)
  3. auto_execute_ready — playbooks elegíveis a autoexecução (apenas marca)

Critérios de elegibilidade (sem habilitar):
  attempts ≥ 100 ∧ confidence ≥ 0.85 ∧ success_rate ≥ 0.80
  ∧ roi_real_brl > 0 ∧ taxa de aprovação histórica ≥ 0.60
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db

log = logging.getLogger("ponto.isabella_audit")

# Guardrails de elegibilidade
THRESHOLDS = {
    "attempts": 100,
    "confidence": 0.85,
    "success_rate": 0.80,
    "approval_rate": 0.60,
}


def _now():
    return datetime.now(timezone.utc)


def _iso(d):
    return d.isoformat()


async def learning_report(company_id: str, *,
                            days: int = 90) -> Dict[str, Any]:
    """Relatório de aprendizado — por (kind, subkind, playbook).

    Combina pesos do learning engine + estatísticas do outcome engine
    + taxa de aprovação histórica (executed+approved / total).
    """
    cutoff_iso = _iso(_now() - timedelta(days=days))

    # 1) Weights atuais
    weights = await db.isabella_playbook_weights.find(
        {"company_id": company_id}, {"_id": 0}).to_list(2000)
    # 2) Outcomes consolidados
    pipe = [
        {"$match": {"company_id": company_id,
                      "created_at": {"$gte": cutoff_iso}}},
        {"$group": {
            "_id": {"kind": "$kind", "subkind": "$subkind",
                       "playbook": "$playbook"},
            "n_total": {"$sum": 1},
            "n_success": {"$sum": {"$cond": [
                {"$eq": ["$result", "success"]}, 1, 0]}},
            "n_failure": {"$sum": {"$cond": [
                {"$eq": ["$result", "failure"]}, 1, 0]}},
            "n_pending": {"$sum": {"$cond": [
                {"$eq": ["$result", "pending"]}, 1, 0]}},
            "roi_real": {"$sum": "$roi_real_brl"},
            "impact_pred": {"$sum": "$impact_pred_brl"},
        }},
    ]
    outc_rows = await db.isabella_outcomes.aggregate(pipe).to_list(2000)
    outc_map = {(r["_id"]["kind"], r["_id"]["subkind"],
                  r["_id"]["playbook"]): r for r in outc_rows}

    # 3) Aprovação histórica nas oportunidades
    pipe2 = [
        {"$match": {"company_id": company_id,
                      "created_at": {"$gte": cutoff_iso}}},
        {"$group": {
            "_id": {"kind": "$kind", "subkind": "$subkind",
                       "playbook": {"$ifNull": [
                           "$recommended_action.playbook",
                           "$recommended_action.type"]}},
            "n_total": {"$sum": 1},
            "n_approved": {"$sum": {"$cond": [
                {"$in": ["$status", ["approved", "executed"]]}, 1, 0]}},
            "n_dismissed": {"$sum": {"$cond": [
                {"$eq": ["$status", "dismissed"]}, 1, 0]}},
        }},
    ]
    appr_rows = await db.isabella_commander_opportunities.aggregate(pipe2) \
        .to_list(2000)
    appr_map = {(r["_id"]["kind"], r["_id"]["subkind"],
                  r["_id"]["playbook"]): r for r in appr_rows}

    items: List[Dict[str, Any]] = []
    for w in weights:
        k = (w.get("kind"), w.get("subkind"), w.get("playbook"))
        outc = outc_map.get(k, {})
        appr = appr_map.get(k, {})
        n_eval = int(w.get("successes") or 0) + int(w.get("failures") or 0)
        success_rate = round(int(w.get("successes") or 0)
                              / max(n_eval, 1), 4)
        appr_total = int(appr.get("n_approved", 0)) \
            + int(appr.get("n_dismissed", 0))
        approval_rate = round(int(appr.get("n_approved", 0))
                                / max(appr_total, 1), 4) if appr_total else 0.0
        items.append({
            "kind": w.get("kind"), "subkind": w.get("subkind"),
            "playbook": w.get("playbook"),
            "attempts": int(w.get("attempts") or 0),
            "successes": int(w.get("successes") or 0),
            "failures": int(w.get("failures") or 0),
            "success_rate": success_rate,
            "weight": float(w.get("weight") or 1.0),
            "confidence": float(w.get("confidence") or 0.0),
            "roi_real_brl": round(float(w.get("roi_real_brl") or 0), 2),
            "impact_pred_brl": round(float(outc.get("impact_pred") or 0), 2),
            "outcomes_pending": int(outc.get("n_pending") or 0),
            "approval_rate": approval_rate,
            "n_approved": int(appr.get("n_approved") or 0),
            "n_dismissed": int(appr.get("n_dismissed") or 0),
        })
    items.sort(key=lambda x: (x["attempts"], x["weight"]), reverse=True)
    return {"company_id": company_id, "window_days": days,
            "playbooks": len(items),
            "items": items,
            "thresholds": THRESHOLDS}


async def auto_execute_ready(company_id: str, *,
                                 days: int = 90) -> Dict[str, Any]:
    """Marca playbooks elegíveis a auto-execução (não habilita nada)."""
    report = await learning_report(company_id, days=days)
    eligible: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    for it in report["items"]:
        reasons: List[str] = []
        if it["attempts"] < THRESHOLDS["attempts"]:
            reasons.append(f"attempts {it['attempts']} < {THRESHOLDS['attempts']}")
        if it["confidence"] < THRESHOLDS["confidence"]:
            reasons.append(f"confidence {it['confidence']} < {THRESHOLDS['confidence']}")
        if it["success_rate"] < THRESHOLDS["success_rate"]:
            reasons.append(f"success_rate {it['success_rate']} < {THRESHOLDS['success_rate']}")
        if it["roi_real_brl"] <= 0:
            reasons.append("ROI não positivo")
        if it["approval_rate"] < THRESHOLDS["approval_rate"]:
            reasons.append(f"approval_rate {it['approval_rate']} < {THRESHOLDS['approval_rate']}")
        if not reasons:
            eligible.append({**it, "policy_action": "auto_execute_candidate"})
        else:
            blocked.append({**it, "blockers": reasons})
    return {"company_id": company_id, "window_days": days,
            "thresholds": THRESHOLDS,
            "eligible": eligible,
            "blocked": blocked,
            "n_eligible": len(eligible),
            "n_blocked": len(blocked)}


async def precision_audit_run(company_id: str, *,
                                  days: int = 30) -> Dict[str, Any]:
    """Executa a auditoria de precisão e persiste em `isabella_precision_audits`."""
    cutoff_iso = _iso(_now() - timedelta(days=days))
    # Agrega outcomes resolved no período
    pipe = [
        {"$match": {"company_id": company_id,
                      "result": {"$in": ["success", "failure"]},
                      "measured_at": {"$gte": cutoff_iso}}},
        {"$group": {
            "_id": "$kind",
            "n_resolved": {"$sum": 1},
            "n_success": {"$sum": {"$cond": [
                {"$eq": ["$result", "success"]}, 1, 0]}},
            "n_failure": {"$sum": {"$cond": [
                {"$eq": ["$result", "failure"]}, 1, 0]}},
            "roi_real_sum": {"$sum": "$roi_real_brl"},
            "impact_pred_sum": {"$sum": "$impact_pred_brl"},
        }},
    ]
    by_kind: Dict[str, Dict[str, Any]] = {}
    async for r in db.isabella_outcomes.aggregate(pipe):
        k = r["_id"] or "unknown"
        n_total = int(r["n_resolved"] or 0)
        n_succ = int(r["n_success"] or 0)
        pred = float(r.get("impact_pred_sum") or 0)
        real = float(r.get("roi_real_sum") or 0)
        by_kind[k] = {
            "n_resolved": n_total,
            "n_success": n_succ,
            "n_failure": int(r["n_failure"] or 0),
            "success_rate": round(n_succ / max(n_total, 1), 4),
            "impact_pred_brl": round(pred, 2),
            "roi_real_brl": round(real, 2),
            "precision_rate": round(real / max(pred, 1), 4),
        }
    # Total
    n_resolved_total = sum(v["n_resolved"] for v in by_kind.values())
    n_success_total = sum(v["n_success"] for v in by_kind.values())
    pred_total = sum(v["impact_pred_brl"] for v in by_kind.values())
    real_total = sum(v["roi_real_brl"] for v in by_kind.values())

    audit = {
        "id": f"audit-{uuid.uuid4().hex[:12]}",
        "company_id": company_id,
        "window_days": days,
        "created_at": _iso(_now()),
        "by_kind": by_kind,
        "totals": {
            "n_resolved": n_resolved_total,
            "n_success": n_success_total,
            "n_failure": n_resolved_total - n_success_total,
            "success_rate": round(n_success_total
                                    / max(n_resolved_total, 1), 4),
            "impact_pred_brl": round(pred_total, 2),
            "roi_real_brl": round(real_total, 2),
            "precision_rate": round(real_total / max(pred_total, 1), 4),
        },
    }
    try:
        await db.isabella_precision_audits.insert_one(dict(audit))
    except Exception as e:
        log.warning("[audit] insert: %s", e)
    audit.pop("_id", None)
    return audit


async def precision_audit_history(company_id: str, *,
                                      limit: int = 30) -> List[Dict[str, Any]]:
    return await db.isabella_precision_audits.find(
        {"company_id": company_id}, {"_id": 0}
    ).sort("created_at", -1).limit(min(limit, 200)) \
        .to_list(min(limit, 200))
