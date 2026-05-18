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


@router.get("/tickets-summary")
async def tickets_created_by_isabella(
    days: int = Query(7, ge=1, le=90),
    user: dict = Depends(require_role("gestor")),
):
    """Resumo de bolhas criadas automaticamente pela Isabella IA na Lousa.

    Conta tickets com `created_by = "isabella_ai"` agregando por dia e por
    status. Inclui breakdown hoje (UTC) + janela `days` (default 7d) +
    quebra por status atual (pendente/aceito/em_andamento/finalizado).

    Retorna também os 10 tickets mais recentes pra exibir num "feed" no card.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    since_iso = since.isoformat()
    today_iso = now.strftime("%Y-%m-%d")

    base = {"company_id": cid, "created_by": "isabella_ai"}

    total_window = await db.tickets.count_documents(
        {**base, "created_at": {"$gte": since_iso}}
    )
    total_today = await db.tickets.count_documents(
        {**base, "created_at": {"$gte": today_iso}}
    )

    # Breakdown por status atual (na janela)
    pipeline_status = [
        {"$match": {**base, "created_at": {"$gte": since_iso}}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]
    by_status_raw = await db.tickets.aggregate(pipeline_status).to_list(20)
    by_status = {s["_id"] or "—": int(s["count"]) for s in by_status_raw}

    # Breakdown por priority + diagnóstico LOS / Power fail
    pipeline_priority = [
        {"$match": {**base, "created_at": {"$gte": since_iso}}},
        {"$group": {"_id": "$priority", "count": {"$sum": 1}}},
    ]
    by_priority_raw = await db.tickets.aggregate(pipeline_priority).to_list(20)
    by_priority = {p["_id"] or "—": int(p["count"]) for p in by_priority_raw}

    # Top 10 tickets recentes
    recent_docs = await db.tickets.find(
        {**base, "created_at": {"$gte": since_iso}},
        {
            "_id": 0,
            "id": 1,
            "status": 1,
            "priority": 1,
            "type": 1,
            "created_at": 1,
            "client_snapshot.name": 1,
            "client_snapshot.phone": 1,
            "ai_diagnosis.status": 1,
            "ai_diagnosis.olt_name": 1,
        },
    ).sort([("created_at", -1)]).limit(10).to_list(10)
    recent = []
    for d in recent_docs:
        cs = d.get("client_snapshot") or {}
        ad = d.get("ai_diagnosis") or {}
        recent.append({
            "id": d.get("id"),
            "status": d.get("status"),
            "priority": d.get("priority"),
            "type": d.get("type"),
            "created_at": d.get("created_at"),
            "client_name": cs.get("name"),
            "phone": cs.get("phone"),
            "smartolt_status": ad.get("status"),
            "olt_name": ad.get("olt_name"),
        })

    # Série diária pra mini-gráfico (sparkline)
    pipeline_series = [
        {"$match": {**base, "created_at": {"$gte": since_iso}}},
        {"$addFields": {"day": {"$substr": ["$created_at", 0, 10]}}},
        {"$group": {"_id": "$day", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    series_raw = await db.tickets.aggregate(pipeline_series).to_list(200)
    series_map = {s["_id"]: int(s["count"]) for s in series_raw if s.get("_id")}
    series = []
    for i in range(days):
        day = (since + timedelta(days=i)).strftime("%Y-%m-%d")
        series.append({"day": day, "count": series_map.get(day, 0)})

    return {
        "days": days,
        "since": since_iso,
        "total_window": total_window,
        "total_today": total_today,
        "by_status": by_status,
        "by_priority": by_priority,
        "recent": recent,
        "series": series,
    }



@router.get("/clients-classification")
async def clients_classification(
    classification: Optional[str] = Query(
        None,
        description=(
            "Filtrar por classificação específica "
            "(persistente|recorrente|esporádico|eventual)."
        ),
    ),
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(require_role("gestor")),
):
    """Classificação histórica de clientes com tickets de reparo nos
    últimos 90 dias + qual técnico foi/está designado.

    Útil pra gestor identificar:
      - Quais clientes estão com problema PERSISTENTE (3+ tickets em 30d)
      - Quem é o técnico mais frequente em cada cliente
      - Telefone, plano, filial pra contato proativo

    Ordenado por número de tickets DESC, depois por last_at DESC.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    now = datetime.now(timezone.utc)
    since_30 = (now - timedelta(days=30)).isoformat()
    since_60 = (now - timedelta(days=60)).isoformat()
    since_90 = (now - timedelta(days=90)).isoformat()

    pipeline = [
        {"$match": {
            "company_id": cid,
            "type": "reparo",
            "created_at": {"$gte": since_90},
            "client_id": {"$ne": None},
        }},
        {"$sort": {"created_at": -1}},
        {"$group": {
            "_id": "$client_id",
            "tickets_total_90d": {"$sum": 1},
            "tickets_30d": {"$sum": {"$cond": [
                {"$gte": ["$created_at", since_30]}, 1, 0]}},
            "tickets_60d": {"$sum": {"$cond": [
                {"$gte": ["$created_at", since_60]}, 1, 0]}},
            "last_ticket": {"$first": "$$ROOT"},
            "diagnoses": {"$addToSet": "$ai_diagnosis.status"},
            "technicians": {"$addToSet": "$assigned_collaborator_id"},
        }},
        {"$sort": {"tickets_total_90d": -1, "last_ticket.created_at": -1}},
        {"$limit": limit},
    ]
    rows = await db.tickets.aggregate(pipeline).to_list(limit)

    sub_ids = [r["_id"] for r in rows if r.get("_id")]
    tech_ids = list({
        t for r in rows for t in (r.get("technicians") or []) if t
    })
    last_tech_ids = list({
        (r.get("last_ticket") or {}).get("assigned_collaborator_id")
        for r in rows
    })
    last_tech_ids = [t for t in last_tech_ids if t]
    all_tech_ids = list(set(tech_ids + last_tech_ids))

    subs_map: dict = {}
    if sub_ids:
        async for sub in db.subscribers.find(
            {"id": {"$in": sub_ids}, "company_id": cid},
            {"_id": 0, "id": 1, "name": 1, "nickname": 1, "plan_name": 1,
             "branch": 1, "external_code": 1, "status": 1, "document": 1},
        ):
            subs_map[sub["id"]] = sub

    techs_map: dict = {}
    if all_tech_ids:
        async for tech in db.collaborators.find(
            {"id": {"$in": all_tech_ids}, "company_id": cid},
            {"_id": 0, "id": 1, "name": 1, "role": 1, "avatar_url": 1},
        ):
            techs_map[tech["id"]] = tech

    phones_map: dict = {}
    if sub_ids:
        async for ph in db.subscriber_phones.find(
            {"subscriber_id": {"$in": sub_ids}, "company_id": cid,
             "is_primary": True},
            {"_id": 0, "subscriber_id": 1, "normalized_number": 1},
        ):
            phones_map[ph["subscriber_id"]] = ph.get("normalized_number")

    def classify(t30: int, t60: int, t90: int) -> str:
        if t30 >= 3:
            return "persistente"
        if t60 >= 2:
            return "recorrente"
        if t90 >= 1:
            return "esporádico"
        return "eventual"

    items = []
    for r in rows:
        sub = subs_map.get(r["_id"]) or {}
        last_t = r.get("last_ticket") or {}
        last_diag = (last_t.get("ai_diagnosis") or {}).get("status")
        cls = classify(
            int(r.get("tickets_30d", 0)),
            int(r.get("tickets_60d", 0)),
            int(r.get("tickets_total_90d", 0)),
        )
        if classification and cls != classification.lower():
            continue
        last_tech_id = last_t.get("assigned_collaborator_id")
        last_tech = techs_map.get(last_tech_id) if last_tech_id else None
        all_techs = [
            techs_map.get(t) for t in (r.get("technicians") or []) if t
        ]
        all_techs = [t for t in all_techs if t]
        items.append({
            "client_id": r["_id"],
            "client_name": sub.get("name") or "—",
            "client_nickname": sub.get("nickname"),
            "phone": phones_map.get(r["_id"]),
            "plan_name": sub.get("plan_name"),
            "branch": sub.get("branch"),
            "external_code": sub.get("external_code"),
            "subscriber_status": sub.get("status"),
            "classification": cls,
            "tickets_30d": int(r.get("tickets_30d", 0)),
            "tickets_60d": int(r.get("tickets_60d", 0)),
            "tickets_90d": int(r.get("tickets_total_90d", 0)),
            "last_ticket_id": last_t.get("id"),
            "last_ticket_at": last_t.get("created_at"),
            "last_ticket_status": last_t.get("status"),
            "last_ticket_priority": last_t.get("priority"),
            "last_diagnosis": last_diag,
            "diagnoses": [d for d in (r.get("diagnoses") or []) if d],
            "last_technician": ({
                "id": last_tech["id"],
                "name": last_tech.get("name"),
                "role": last_tech.get("role"),
                "avatar_url": last_tech.get("avatar_url"),
            } if last_tech else None),
            "all_technicians": [{
                "id": t["id"],
                "name": t.get("name"),
                "role": t.get("role"),
            } for t in all_techs],
        })

    summary = {
        "total": len(items),
        "by_classification": {
            "persistente": sum(1 for i in items if i["classification"] == "persistente"),
            "recorrente": sum(1 for i in items if i["classification"] == "recorrente"),
            "esporádico": sum(1 for i in items if i["classification"] == "esporádico"),
            "eventual": sum(1 for i in items if i["classification"] == "eventual"),
        },
    }

    return {
        "since_90d": since_90,
        "summary": summary,
        "items": items,
    }
