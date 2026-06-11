"""ai_center_v80.py — V8.0 endpoints."""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from fastapi import APIRouter, Depends, HTTPException, Body
from typing import Optional

from rbac import require_roles
from services import smartprov_score, golive_master
from database import db


router = APIRouter(prefix="/api/ai-center/v80",
                    tags=["ai-center-v80"])


def _co(user):
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid: raise HTTPException(400, "company_id ausente")
    return cid


@router.get("/score")
async def get_smartprov_score(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return await smartprov_score.compute(_co(user))


@router.get("/golive-master")
async def get_golive_master(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    return await golive_master.status(_co(user))


@router.get("/money-stream")
async def get_money_stream(days: int = 30,
                            user=Depends(require_roles(
                                "administrador", "auditor", "gestor"))):
    """Money Stream — onde o dinheiro está morrendo?
    Calcula dropoff R$ por estágio."""
    from services import cash_operation as cash
    a2c = await cash.action_to_cash(_co(user), days)
    # Dropoff em R$: cada estágio perdido custa expected_BRL médio
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc)
               - timedelta(days=days)).isoformat()
    pipe = [
        {"$match": {"company_id": _co(user),
                     "created_at": {"$gte": cutoff},
                     "action_kind": {"$nin": [None, "noop"]}}},
        {"$group": {"_id": None,
                     "avg": {"$avg": "$expected_BRL"}}},
    ]
    r = await db.motor_ia_decisions.aggregate(pipe).to_list(1)
    avg = float(r[0]["avg"]) if r else 0

    stages = ["created", "sent", "delivered", "read",
               "replied", "negotiated", "paid", "received"]
    drops = []
    for i in range(1, len(stages)):
        prev = a2c["funnel"][stages[i - 1]]
        cur = a2c["funnel"][stages[i]]
        lost_count = max(prev - cur, 0)
        lost_BRL = round(lost_count * avg, 2)
        drops.append({
            "stage_from": stages[i - 1],
            "stage_to":   stages[i],
            "lost_count": lost_count,
            "lost_BRL":   lost_BRL,
        })
    biggest = max(drops, key=lambda x: x["lost_BRL"]) if drops else None
    return {
        "funnel":             a2c["funnel"],
        "conversion_rates":   a2c["conversion_rates_pct"],
        "avg_expected_BRL_per_action": round(avg, 2),
        "dropoffs":           drops,
        "biggest_leak":       biggest,
        "headline": (
            f"Maior vazamento: {biggest['stage_from']} → "
            f"{biggest['stage_to']} · R$ {biggest['lost_BRL']:,.2f} perdidos"
            if biggest and biggest["lost_BRL"] > 0
            else "Sem vazamentos significativos"),
    }


@router.post("/experiments/create")
async def create_experiment(payload: dict = Body(...),
                              user=Depends(require_roles(
                                  "administrador", "auditor"))):
    """V8.0 PRIORIDADE 5 — Cria experimento A/B."""
    import uuid
    from datetime import datetime, timezone
    exp = {
        "experiment_id": f"exp-{uuid.uuid4().hex[:10]}",
        "company_id":   _co(user),
        "name":         payload.get("name", "exp"),
        "kind":         payload.get("kind", "template"),
        "variants":     payload.get("variants", []),
        "status":       "running",
        "created_at":   datetime.now(timezone.utc).isoformat(),
    }
    await db.motor_ia_experiments.insert_one(dict(exp))
    return exp


@router.get("/experiments")
async def list_experiments(user=Depends(
    require_roles("administrador", "auditor", "gestor"))):
    rows = await db.motor_ia_experiments.find(
        {"company_id": _co(user)}
    ).sort("created_at", -1).limit(50).to_list(50)
    for r in rows: r.pop("_id", None)
    return {"items": rows}


@router.post("/experiments/{exp_id}/promote")
async def promote_winner(exp_id: str, winner: str,
                          user=Depends(require_roles(
                              "administrador", "auditor"))):
    """Promove variante vencedora; rebaixa as outras."""
    from datetime import datetime, timezone
    r = await db.motor_ia_experiments.update_one(
        {"experiment_id": exp_id, "company_id": _co(user)},
        {"$set": {"status": "promoted",
                   "winner_variant": winner,
                   "promoted_at": datetime.now(
                       timezone.utc).isoformat()}})
    if r.modified_count == 0:
        raise HTTPException(404, "experiment not found")
    return {"experiment_id": exp_id, "winner": winner,
             "status": "promoted"}
