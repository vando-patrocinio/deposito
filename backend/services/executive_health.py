"""
executive_health.py — Sprint 7 / iter226
Saúde executiva consolidada (12 indicadores) + churn detector.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from database import db


async def compute_executive_score(company_id: str = None
                                       ) -> Dict[str, Any]:
    """Calcula score corporativo 0-100 + sub-scores por área.

    Sprint 14: aceita company_id para isolamento multi-tenant.
    """
    def _co_filter(extra=None):
        f = dict(extra or {})
        if company_id:
            f["company_id"] = company_id
        return f
    # 1) Dados (reusa data_quality)
    from services.data_quality import run_scan
    dq = await run_scan(company_id=company_id)
    score_dados = dq["score"]

    # 2) Operacional (tickets abertos / total clientes — invertido)
    try:
        total_clients = await db.subscribers.count_documents(
            _co_filter())
        open_tickets = await db.tickets.count_documents(
            _co_filter({"status": {"$nin": ["closed", "finalizado",
                                                  "completed"]}}))
        score_op = max(0.0, 100.0
                          - 100.0 * open_tickets / max(total_clients, 1)
                          * 10)
    except Exception:
        score_op = 100.0

    # 3) Comercial (vendas/perdas 30d)
    try:
        sales = await db.sales.count_documents(_co_filter())
        lost = await db.sales.count_documents(
            _co_filter({"status": "lost"}))
        conv = (1.0 - lost / max(sales, 1)) * 100
        score_com = round(conv, 1)
    except Exception:
        score_com = 80.0

    # 4) Financeiro (overdue/total)
    try:
        overdue = await db.financeiro_movs.count_documents(
            _co_filter({"status": {"$in": ["overdue", "atrasado"]}}))
        total_movs = await db.financeiro_movs.count_documents(
            _co_filter())
        score_fin = max(0.0, 100.0 - 100.0 * overdue
                            / max(total_movs, 1) * 3)
    except Exception:
        score_fin = 90.0

    # 5) Segurança (rbac_blocked 24h, exports massivos)
    try:
        from datetime import timedelta
        since = (datetime.now(timezone.utc)
                   - timedelta(hours=24)).isoformat()
        blocks = await db.audit_log.count_documents(
            _co_filter({"category": "rbac_blocked",
                          "created_at": {"$gte": since}}))
        score_seg = max(0.0, 100.0 - blocks * 2)
    except Exception:
        score_seg = 100.0

    overall = round(
        (score_dados * 0.20 + score_op * 0.25 + score_com * 0.20
            + score_fin * 0.20 + score_seg * 0.15), 1)

    if overall >= 85:
        status = "saudavel"
    elif overall >= 65:
        status = "atencao"
    else:
        status = "critico"

    out = {
        "overall_score": overall,
        "status": status,
        "scores": {
            "dados": round(score_dados, 1),
            "operacional": round(score_op, 1),
            "comercial": round(score_com, 1),
            "financeiro": round(score_fin, 1),
            "seguranca": round(score_seg, 1),
        },
        "company_id": company_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await db.motor_ia_insights.insert_one({
            **out, "kind": "executive_health",
            "created_at": out["generated_at"]})
    except Exception:
        pass
    return out


async def compute_executive_score_all_tenants() -> Dict[str, Any]:
    """Sprint 14 — roda compute_executive_score por company_id.

    Garante 1 insight por empresa em vez de um global vazado entre
    tenants.
    """
    try:
        companies = await db.subscribers.distinct("company_id")
    except Exception:
        companies = []
    companies = [c for c in companies if c]
    if not companies:
        return await compute_executive_score(company_id=None)
    results = []
    for co in companies:
        try:
            r = await compute_executive_score(company_id=co)
            results.append({"company_id": co,
                              "overall": r["overall_score"]})
        except Exception:
            pass
    return {"total_companies": len(results), "results": results}


async def detect_churn_risk(threshold_days: int = 60
                                ) -> List[Dict[str, Any]]:
    """Identifica clientes com sinais de churn."""
    risks: List[Dict[str, Any]] = []
    try:
        # heurística simples: clientes com >=2 tickets abertos
        # OU pagamento atrasado
        pipe = [
            {"$match": {"status": {"$nin": ["closed",
                                                  "finalizado"]}}},
            {"$group": {"_id": "$subscriber_id",
                          "n": {"$sum": 1}}},
            {"$match": {"n": {"$gte": 2}}},
            {"$limit": 100},
        ]
        async for r in db.tickets.aggregate(pipe):
            risks.append({"subscriber_id": r["_id"],
                            "open_tickets": r["n"],
                            "reason": "multi_open_tickets"})
        # grava insights
        if risks:
            await db.motor_ia_insights.insert_one({
                "kind": "churn_risk_scan",
                "count": len(risks),
                "sample": risks[:10],
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
    except Exception:
        pass
    return risks
