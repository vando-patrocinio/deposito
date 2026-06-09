"""
revenue_attribution.py — FASE 1 da Constituição V3.0 (RevenueOps IA)

Toda ação da IA que produz outcome financeiro é registrada em
`motor_ia_revenue_attribution` com R$ atribuído, kind e source.

Kinds suportados:
  - recovered:       receita recuperada via cobrança automática
  - generated:       receita nova (upsell, cross-sell, indicação convertida)
  - churn_prevented: cliente que ia cancelar e foi retido
  - cost_saved:      visita técnica evitada, hora-homem poupada (R$ equiv.)

Source:
  - action_id (FK motor_ia_actions)
  - template (qual template/playbook converteu)
  - channel (whatsapp_baileys / email / sms / call)
  - campaign_id (opcional)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db


VALID_KINDS = {
    "recovered",
    "generated",
    "churn_prevented",
    "cost_saved",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


async def attribute(
    *,
    company_id: str,
    kind: str,
    amount_BRL: float,
    action_id: Optional[str] = None,
    decision_id: Optional[str] = None,
    subscriber_id: Optional[str] = None,
    template: Optional[str] = None,
    channel: Optional[str] = None,
    campaign_id: Optional[str] = None,
    recognized_at: Optional[datetime] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Insere 1 atribuição financeira. Idempotente por (action_id, kind).

    Retorna o documento criado (ou existente se duplicado).
    """
    if kind not in VALID_KINDS:
        raise ValueError(f"kind inválido: {kind} (use {VALID_KINDS})")
    if amount_BRL <= 0:
        raise ValueError("amount_BRL deve ser > 0")

    # Idempotência: 1 ação só atribui 1x por kind
    if action_id:
        existing = await db.motor_ia_revenue_attribution.find_one(
            {"action_id": action_id, "kind": kind, "company_id": company_id}
        )
        if existing:
            return existing

    doc = {
        "id": f"rev-{uuid.uuid4().hex[:14]}",
        "company_id": company_id,
        "kind": kind,
        "amount_BRL": round(float(amount_BRL), 2),
        "action_id": action_id,
        "decision_id": decision_id,
        "subscriber_id": subscriber_id,
        "template": template,
        "channel": channel,
        "campaign_id": campaign_id,
        "recognized_at": _iso(recognized_at or _now()),
        "created_at": _iso(_now()),
        "metadata": metadata or {},
    }
    await db.motor_ia_revenue_attribution.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


async def summary(
    company_id: str,
    *,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Retorna agregado por kind: total, count, ticket_médio."""
    q: Dict[str, Any] = {"company_id": company_id}
    if since or until:
        rng: Dict[str, Any] = {}
        if since:
            rng["$gte"] = _iso(since)
        if until:
            rng["$lte"] = _iso(until)
        q["recognized_at"] = rng

    out = {k: {"total_BRL": 0.0, "count": 0, "avg_BRL": 0.0} for k in VALID_KINDS}
    pipeline = [
        {"$match": q},
        {"$group": {
            "_id": "$kind",
            "total": {"$sum": "$amount_BRL"},
            "count": {"$sum": 1},
        }},
    ]
    async for row in db.motor_ia_revenue_attribution.aggregate(pipeline):
        k = row["_id"]
        if k not in out:
            continue
        out[k]["total_BRL"] = round(row["total"], 2)
        out[k]["count"] = row["count"]
        out[k]["avg_BRL"] = round(row["total"] / row["count"], 2) if row["count"] else 0.0

    # ROI marginal — custo ~0 com Baileys, custo real só LLM
    total_brl = sum(v["total_BRL"] for v in out.values())
    total_count = sum(v["count"] for v in out.values())
    out["_total_BRL"] = round(total_brl, 2)
    out["_total_count"] = total_count
    return out


async def by_template(
    company_id: str, *, since: Optional[datetime] = None,
    until: Optional[datetime] = None, limit: int = 20,
) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"company_id": company_id,
                          "template": {"$ne": None}}
    if since or until:
        rng: Dict[str, Any] = {}
        if since:
            rng["$gte"] = _iso(since)
        if until:
            rng["$lte"] = _iso(until)
        q["recognized_at"] = rng
    pipeline = [
        {"$match": q},
        {"$group": {
            "_id": "$template",
            "total_BRL": {"$sum": "$amount_BRL"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"total_BRL": -1}},
        {"$limit": limit},
    ]
    res = []
    async for r in db.motor_ia_revenue_attribution.aggregate(pipeline):
        res.append({
            "template": r["_id"],
            "total_BRL": round(r["total_BRL"], 2),
            "count": r["count"],
            "avg_BRL": round(r["total_BRL"]/r["count"], 2) if r["count"] else 0.0,
        })
    return res


async def by_channel(
    company_id: str, *, since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"company_id": company_id,
                          "channel": {"$ne": None}}
    if since or until:
        rng: Dict[str, Any] = {}
        if since:
            rng["$gte"] = _iso(since)
        if until:
            rng["$lte"] = _iso(until)
        q["recognized_at"] = rng
    pipeline = [
        {"$match": q},
        {"$group": {
            "_id": "$channel",
            "total_BRL": {"$sum": "$amount_BRL"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"total_BRL": -1}},
    ]
    res = []
    async for r in db.motor_ia_revenue_attribution.aggregate(pipeline):
        res.append({
            "channel": r["_id"],
            "total_BRL": round(r["total_BRL"], 2),
            "count": r["count"],
        })
    return res


async def by_action_type(
    company_id: str, *, since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Junta com motor_ia_actions para agrupar por action_type."""
    q: Dict[str, Any] = {"company_id": company_id,
                          "action_id": {"$ne": None}}
    if since or until:
        rng: Dict[str, Any] = {}
        if since:
            rng["$gte"] = _iso(since)
        if until:
            rng["$lte"] = _iso(until)
        q["recognized_at"] = rng
    pipeline = [
        {"$match": q},
        {"$lookup": {
            "from": "motor_ia_actions",
            "localField": "action_id",
            "foreignField": "id",
            "as": "act",
        }},
        {"$unwind": {"path": "$act", "preserveNullAndEmptyArrays": True}},
        {"$group": {
            "_id": "$act.action_type",
            "total_BRL": {"$sum": "$amount_BRL"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"total_BRL": -1}},
    ]
    res = []
    async for r in db.motor_ia_revenue_attribution.aggregate(pipeline):
        res.append({
            "action_type": r["_id"] or "unknown",
            "total_BRL": round(r["total_BRL"], 2),
            "count": r["count"],
        })
    return res


async def timeline(
    company_id: str, *, since: Optional[datetime] = None,
    until: Optional[datetime] = None, granularity: str = "day",
) -> List[Dict[str, Any]]:
    """Series diárias por kind."""
    q: Dict[str, Any] = {"company_id": company_id}
    if since or until:
        rng: Dict[str, Any] = {}
        if since:
            rng["$gte"] = _iso(since)
        if until:
            rng["$lte"] = _iso(until)
        q["recognized_at"] = rng

    fmt = {"day": "%Y-%m-%d", "month": "%Y-%m"}.get(granularity, "%Y-%m-%d")
    pipeline = [
        {"$match": q},
        {"$addFields": {
            "_ts": {"$dateFromString": {"dateString": "$recognized_at"}},
        }},
        {"$group": {
            "_id": {
                "bucket": {"$dateToString": {"format": fmt, "date": "$_ts"}},
                "kind": "$kind",
            },
            "total_BRL": {"$sum": "$amount_BRL"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id.bucket": 1}},
    ]
    buckets: Dict[str, Dict[str, Any]] = {}
    async for r in db.motor_ia_revenue_attribution.aggregate(pipeline):
        b = r["_id"]["bucket"]
        if b not in buckets:
            buckets[b] = {"bucket": b, "total_BRL": 0.0, "by_kind": {}}
        buckets[b]["by_kind"][r["_id"]["kind"]] = round(r["total_BRL"], 2)
        buckets[b]["total_BRL"] = round(
            buckets[b]["total_BRL"] + r["total_BRL"], 2
        )
    return list(buckets.values())


async def top_actions(
    company_id: str, *, limit: int = 10,
    since: Optional[datetime] = None, until: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Top ações individuais por R$ atribuído."""
    q: Dict[str, Any] = {"company_id": company_id}
    if since or until:
        rng: Dict[str, Any] = {}
        if since:
            rng["$gte"] = _iso(since)
        if until:
            rng["$lte"] = _iso(until)
        q["recognized_at"] = rng
    res = []
    cur = db.motor_ia_revenue_attribution.find(q).sort(
        "amount_BRL", -1).limit(limit)
    async for d in cur:
        d.pop("_id", None)
        res.append(d)
    return res
