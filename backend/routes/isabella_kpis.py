"""Isabella KPIs — sub-aba do Central IA.

Métricas de uso do canal WhatsApp + assistente Isabella (auto-reply IA) e
do botão "Enviar com IA" (polish-text). Também controla um toggle global
por empresa para ligar/desligar o botão azul no composer.

Endpoints:
- GET  /api/central-ia/isabella?days=N    → KPIs agregados + série temporal
- GET  /api/central-ia/isabella/config    → { polish_button_enabled: bool }
- PUT  /api/central-ia/isabella/config    → atualiza o toggle
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.isabella_kpis")
router = APIRouter(prefix="/api/central-ia/isabella", tags=["central-ia-isabella"])


def _iso_floor(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat()


@router.get("")
async def isabella_dashboard(days: int = Query(7, ge=1, le=90),
                                user: dict = Depends(require_role("gestor"))):
    """Agrega métricas de uso da Isabella (IA) vs atendimento humano,
    inclui ranking de atendentes e série temporal de mensagens.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    since_iso = since.isoformat()

    base = {"company_id": cid, "created_at": {"$gte": since_iso}}

    # ---- Totais por fonte (IA / humano / inbound) ----
    out_total = await db.aihub_wa_messages.count_documents(
        {**base, "direction": "outbound"}
    )
    out_ai = await db.aihub_wa_messages.count_documents(
        {**base, "direction": "outbound", "auto_reply": True}
    )
    out_human = await db.aihub_wa_messages.count_documents(
        {**base, "direction": "outbound",
         "$or": [{"auto_reply": False}, {"auto_reply": {"$exists": False}}]}
    )
    in_total = await db.aihub_wa_messages.count_documents(
        {**base, "direction": "inbound"}
    )

    # ---- Botão polish (com IA) vs sem IA — só conta outbound humano ----
    out_polished = await db.aihub_wa_messages.count_documents(
        {**base, "direction": "outbound", "polished_by_ai": True}
    )
    out_human_unpolished = max(0, out_human - out_polished)

    polish_pct = round(100.0 * out_polished / out_human, 1) if out_human else 0.0
    ai_share_pct = round(100.0 * out_ai / out_total, 1) if out_total else 0.0
    human_share_pct = round(100.0 - ai_share_pct, 1) if out_total else 0.0

    # ---- Ranking atendentes humanos ----
    pipeline_rank = [
        {"$match": {**base, "direction": "outbound",
                    "$or": [{"auto_reply": False},
                             {"auto_reply": {"$exists": False}}]}},
        {"$group": {
            "_id": "$sent_by_user_id",
            "messages": {"$sum": 1},
            "polished": {"$sum": {"$cond": [
                {"$eq": ["$polished_by_ai", True]}, 1, 0
            ]}},
            "actor": {"$first": "$actor_user"},
        }},
        {"$sort": {"messages": -1}},
        {"$limit": 20},
    ]
    rank_raw = await db.aihub_wa_messages.aggregate(pipeline_rank).to_list(50)
    user_ids = [r["_id"] for r in rank_raw if r.get("_id")]
    users_lookup = {}
    if user_ids:
        async for u in db.users.find(
            {"id": {"$in": user_ids}},
            {"_id": 0, "id": 1, "name": 1, "email": 1},
        ):
            users_lookup[u["id"]] = u
    ranking = []
    for r in rank_raw:
        uid = r.get("_id")
        u = users_lookup.get(uid) or {}
        msgs = r.get("messages", 0)
        polished = r.get("polished", 0)
        ranking.append({
            "user_id": uid,
            "name": u.get("name") or u.get("email") or r.get("actor") or "—",
            "messages": msgs,
            "polished": polished,
            "polish_pct": round(100.0 * polished / msgs, 1) if msgs else 0.0,
        })

    # ---- Tempo médio de atendimento humano por conversa ----
    # Usamos a duração entre primeira mensagem inbound e última outbound humana
    pipeline_sla = [
        {"$match": base},
        {"$group": {
            "_id": "$phone",
            "first": {"$min": "$created_at"},
            "last": {"$max": "$created_at"},
            "human_msgs": {"$sum": {"$cond": [
                {"$and": [
                    {"$eq": ["$direction", "outbound"]},
                    {"$ne": ["$auto_reply", True]},
                ]}, 1, 0]
            }},
        }},
        {"$match": {"human_msgs": {"$gt": 0}}},
        {"$limit": 500},
    ]
    sla_docs = await db.aihub_wa_messages.aggregate(pipeline_sla).to_list(500)
    durations_min: list[float] = []
    for d in sla_docs:
        try:
            f = datetime.fromisoformat(d["first"].replace("Z", "+00:00"))
            last_dt = datetime.fromisoformat(d["last"].replace("Z", "+00:00"))
            dur = (last_dt - f).total_seconds() / 60.0
            if 0 <= dur <= 60 * 24:  # filtro: <= 24h evita outliers
                durations_min.append(dur)
        except Exception:
            continue
    avg_handling_min = round(sum(durations_min) / len(durations_min), 1) \
        if durations_min else 0.0

    # ---- Série temporal de mensagens (gráfico linear) ----
    # Bucketiza por dia (UTC) os 3 fluxos.
    series_pipeline = [
        {"$match": base},
        {"$addFields": {
            "day": {"$substr": ["$created_at", 0, 10]},
            "is_inbound": {"$cond": [{"$eq": ["$direction", "inbound"]}, 1, 0]},
            "is_ai": {"$cond": [{"$and": [
                {"$eq": ["$direction", "outbound"]},
                {"$eq": ["$auto_reply", True]},
            ]}, 1, 0]},
            "is_human": {"$cond": [{"$and": [
                {"$eq": ["$direction", "outbound"]},
                {"$ne": ["$auto_reply", True]},
            ]}, 1, 0]},
        }},
        {"$group": {
            "_id": "$day",
            "inbound": {"$sum": "$is_inbound"},
            "ai": {"$sum": "$is_ai"},
            "human": {"$sum": "$is_human"},
        }},
        {"$sort": {"_id": 1}},
    ]
    series_raw = await db.aihub_wa_messages.aggregate(series_pipeline).to_list(200)
    series_map = {s["_id"]: s for s in series_raw if s.get("_id")}
    # Preenche todos os dias do range para gráfico fluído
    series = []
    for i in range(days):
        day = (since + timedelta(days=i)).strftime("%Y-%m-%d")
        s = series_map.get(day, {})
        series.append({
            "day": day,
            "inbound": int(s.get("inbound", 0)),
            "ai": int(s.get("ai", 0)),
            "human": int(s.get("human", 0)),
            "total": int(s.get("inbound", 0)) + int(s.get("ai", 0))
                       + int(s.get("human", 0)),
        })

    # Estado do toggle do botão polish
    cfg_doc = await db.isabella_config.find_one(
        {"company_id": cid}, {"_id": 0, "polish_button_enabled": 1}
    )
    polish_enabled = True if not cfg_doc else bool(
        cfg_doc.get("polish_button_enabled", True)
    )

    return {
        "days": days,
        "since": since_iso,
        "until": now.isoformat(),
        "polish_button_enabled": polish_enabled,
        "totals": {
            "outbound": out_total,
            "outbound_ai": out_ai,
            "outbound_human": out_human,
            "outbound_human_polished": out_polished,
            "outbound_human_raw": out_human_unpolished,
            "inbound": in_total,
            "all_messages": out_total + in_total,
        },
        "ratios": {
            "ai_share_pct": ai_share_pct,
            "human_share_pct": human_share_pct,
            "polish_use_pct": polish_pct,
        },
        "avg_handling_minutes": avg_handling_min,
        "ranking": ranking,
        "series": series,
    }


class IsabellaConfigIn(BaseModel):
    polish_button_enabled: bool


@router.get("/config")
async def get_config(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.isabella_config.find_one(
        {"company_id": cid}, {"_id": 0, "polish_button_enabled": 1}
    )
    return {
        "polish_button_enabled": True if not doc else bool(
            doc.get("polish_button_enabled", True)
        ),
    }


@router.put("/config")
async def put_config(payload: IsabellaConfigIn,
                       user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    await db.isabella_config.update_one(
        {"company_id": cid},
        {"$set": {
            "company_id": cid,
            "polish_button_enabled": bool(payload.polish_button_enabled),
            "updated_at": now_iso(),
            "updated_by": user.get("email") or user.get("id"),
        }},
        upsert=True,
    )
    return {"polish_button_enabled": bool(payload.polish_button_enabled)}
