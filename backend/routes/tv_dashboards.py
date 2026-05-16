"""TV Dashboards — endpoints públicos para telas de operação no escritório.

Sem autenticação — usado em TVs em modo kiosk. Inclui:
- GET /api/tv/{cid}/board    → Kanban de tickets ativos (lousa)
- GET /api/tv/{cid}/isabella → KPIs IA × humanos do dia
- GET /api/tv/{cid}/finance  → boletos pagos hoje, meta do mês
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException

from core import DEMO_COMPANY_ID
from database import db

logger = logging.getLogger("ponto.tv")
router = APIRouter(prefix="/api/tv", tags=["tv-public"])


def _today_window():
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return now, start.isoformat(), end.isoformat()


def _minutes_since(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
    except Exception:
        return None


# ===========================================================================
# 1) KANBAN — quadro de tickets ativos
# ===========================================================================
@router.get("/{cid}/board")
async def board_kanban(cid: str):
    """Retorna tickets ativos agrupados em colunas Kanban.

    Colunas:
    - aguardando: tickets pendentes (sem técnico ou na fila)
    - em_rota: técnico saiu mas ainda não chegou
    - atendendo: técnico no local executando
    - urgente: tickets boss-mode (destaque)
    """
    cid = cid or DEMO_COMPANY_ID

    # Tickets ativos (não finalizados nem cancelados)
    cursor = db.tickets.find({
        "company_id": cid,
        "status": {"$in": [
            "pendente", "aberta", "aguardando_atendimento",
            "aguardando_cliente", "em_pausa",
        ]},
    }, {
        "_id": 0, "id": 1, "status": 1, "type": 1,
        "subscriber_name": 1, "subscriber_phone": 1, "subscriber_address": 1,
        "subscriber_external_code": 1,
        "assigned_collaborator_id": 1, "assigned_collaborator_name": 1,
        "boss_mode": 1, "is_urgent": 1, "priority": 1,
        "scheduled_at": 1, "opened_at": 1, "created_at": 1,
        "tech_started_at": 1, "tech_arrived_at": 1,
        "title": 1, "description": 1,
    }).limit(150)

    cols = {"urgente": [], "aguardando": [], "em_rota": [], "atendendo": []}

    # Pré-fetch avatars dos colaboradores envolvidos
    tickets = await cursor.to_list(length=150)
    coll_ids = list({t.get("assigned_collaborator_id") for t in tickets
                     if t.get("assigned_collaborator_id")})
    coll_map = {}
    if coll_ids:
        async for c in db.collaborators.find(
            {"id": {"$in": coll_ids}},
            {"_id": 0, "id": 1, "name": 1, "avatar_data_url": 1,
              "google_picture": 1},
        ):
            coll_map[c["id"]] = c

    for t in tickets:
        ticket_card = {
            "id": t["id"],
            "type": t.get("type") or "atendimento",
            "title": t.get("title") or t.get("description") or "—",
            "subscriber_name": t.get("subscriber_name") or "Cliente",
            "subscriber_address": t.get("subscriber_address") or "",
            "subscriber_external_code": t.get("subscriber_external_code"),
            "priority": t.get("priority") or "normal",
            "boss_mode": bool(t.get("boss_mode") or t.get("is_urgent")),
            "tech_id": t.get("assigned_collaborator_id"),
            "tech_name": t.get("assigned_collaborator_name"),
            "tech_avatar": (coll_map.get(t.get("assigned_collaborator_id"))
                              or {}).get("avatar_data_url")
                              or (coll_map.get(t.get("assigned_collaborator_id"))
                                    or {}).get("google_picture"),
            "scheduled_at": t.get("scheduled_at"),
            "opened_at": t.get("opened_at"),
            "minutes_open": _minutes_since(
                t.get("opened_at") or t.get("created_at")
            ),
        }

        # Classifica em colunas
        if ticket_card["boss_mode"]:
            cols["urgente"].append(ticket_card)
        elif t.get("tech_arrived_at") or t.get("status") == "aberta":
            cols["atendendo"].append(ticket_card)
        elif t.get("tech_started_at") and not t.get("tech_arrived_at"):
            cols["em_rota"].append(ticket_card)
        else:
            cols["aguardando"].append(ticket_card)

    # Ordena cada coluna: urgentes primeiro, depois por tempo aberto desc
    for col in cols.values():
        col.sort(key=lambda c: (
            -1 if c["boss_mode"] else 0,
            -(c["minutes_open"] or 0),
        ))

    counts = {k: len(v) for k, v in cols.items()}

    # Notas finalizadas hoje (rodapé inspirador)
    _, day_start, day_end = _today_window()
    closed_today = await db.tickets.count_documents({
        "company_id": cid,
        "status": "finalizada",
        "closed_at": {"$gte": day_start, "$lt": day_end},
    })

    return {
        "company_id": cid,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "columns": cols,
        "counts": counts,
        "closed_today": closed_today,
        "active_total": sum(counts.values()),
    }


# ===========================================================================
# 2) ISABELLA LIVE — KPIs simplificados pra TV
# ===========================================================================
@router.get("/{cid}/isabella")
async def isabella_live(cid: str):
    cid = cid or DEMO_COMPANY_ID
    _, day_start, day_end = _today_window()
    base = {"company_id": cid, "created_at": {"$gte": day_start, "$lt": day_end}}

    in_total = await db.aihub_wa_messages.count_documents(
        {**base, "direction": "inbound"}
    )
    out_total = await db.aihub_wa_messages.count_documents(
        {**base, "direction": "outbound"}
    )
    out_ai = await db.aihub_wa_messages.count_documents(
        {**base, "direction": "outbound", "auto_reply": True}
    )
    out_human = max(0, out_total - out_ai)
    ai_share = round(100.0 * out_ai / out_total, 1) if out_total else 0.0

    # Buckets atuais (tempo real)
    waiting = await db.wa_conversations.count_documents({
        "company_id": cid, "status": {"$ne": "closed"},
        "$or": [{"assignee_role": None}, {"assignee_role": {"$exists": False}}],
    })
    in_human = await db.wa_conversations.count_documents({
        "company_id": cid, "assignee_role": "human",
        "status": {"$ne": "closed"},
    })
    in_ai = await db.wa_conversations.count_documents({
        "company_id": cid, "assignee_role": "ai",
        "status": {"$ne": "closed"},
    })

    # Vendas concluídas hoje pela Isabella (transferência → aguardando)
    sales_completed = await db.wa_conversations.count_documents({
        "company_id": cid,
        "sales_completed_at": {"$gte": day_start, "$lt": day_end},
    })

    return {
        "company_id": cid,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "today": {
            "inbound": in_total,
            "ai_replies": out_ai,
            "human_replies": out_human,
            "total": in_total + out_total,
            "ai_share_pct": ai_share,
            "sales_completed": sales_completed,
        },
        "live_buckets": {
            "waiting": waiting,
            "with_human": in_human,
            "with_ai": in_ai,
        },
    }


# ===========================================================================
# 3) FINANCE LIVE — vendas e cobrança do dia
# ===========================================================================
@router.get("/{cid}/finance")
async def finance_live(cid: str):
    cid = cid or DEMO_COMPANY_ID
    _, day_start, day_end = _today_window()
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0,
                                microsecond=0).isoformat()

    # Faturas pagas hoje
    paid_today_cur = db.subscriber_invoices.find({
        "company_id": cid,
        "status": {"$in": ["pago", "paid", "PAGO", "Pago"]},
        "paid_at": {"$gte": day_start, "$lt": day_end},
    }, {"_id": 0, "amount": 1, "value": 1, "paid_at": 1})
    paid_today = await paid_today_cur.to_list(length=2000)
    paid_today_total = sum(float(d.get("amount") or d.get("value") or 0)
                            for d in paid_today)

    # Pagas no mês
    paid_month_cur = db.subscriber_invoices.find({
        "company_id": cid,
        "status": {"$in": ["pago", "paid", "PAGO", "Pago"]},
        "paid_at": {"$gte": month_start, "$lt": day_end},
    }, {"_id": 0, "amount": 1, "value": 1})
    paid_month = await paid_month_cur.to_list(length=20000)
    paid_month_total = sum(float(d.get("amount") or d.get("value") or 0)
                            for d in paid_month)

    # A vencer (3 dias)
    in_3_days = (now + timedelta(days=3)).isoformat()
    upcoming_cur = db.subscriber_invoices.find({
        "company_id": cid,
        "status": {"$in": ["pendente", "aberta", "open"]},
        "due_at": {"$gte": now.isoformat(), "$lt": in_3_days},
    }, {"_id": 0, "amount": 1, "value": 1})
    upcoming = await upcoming_cur.to_list(length=5000)
    upcoming_total = sum(float(d.get("amount") or d.get("value") or 0)
                          for d in upcoming)

    # Vencidas
    overdue_cur = db.subscriber_invoices.find({
        "company_id": cid,
        "status": {"$in": ["pendente", "aberta", "open", "atrasado"]},
        "due_at": {"$lt": now.isoformat()},
    }, {"_id": 0, "amount": 1, "value": 1})
    overdue = await overdue_cur.to_list(length=10000)
    overdue_total = sum(float(d.get("amount") or d.get("value") or 0)
                         for d in overdue)

    # Novos contratos hoje (subscribers ativados)
    new_subs = await db.subscribers.count_documents({
        "company_id": cid,
        "activation_date": {"$gte": day_start, "$lt": day_end},
    })

    return {
        "company_id": cid,
        "generated_at": now.isoformat(),
        "today": {
            "paid_count": len(paid_today),
            "paid_total": round(paid_today_total, 2),
            "new_subscribers": new_subs,
        },
        "month": {
            "paid_count": len(paid_month),
            "paid_total": round(paid_month_total, 2),
        },
        "upcoming_3d": {
            "count": len(upcoming),
            "total": round(upcoming_total, 2),
        },
        "overdue": {
            "count": len(overdue),
            "total": round(overdue_total, 2),
        },
    }


# ===========================================================================
# 4) META — info da empresa pra header das telas
# ===========================================================================
@router.get("/{cid}/meta")
async def tv_meta(cid: str):
    cid = cid or DEMO_COMPANY_ID
    company = await db.companies.find_one(
        {"id": cid}, {"_id": 0, "id": 1, "name": 1, "logo_url": 1}
    ) or {"id": cid, "name": "SmartProv"}
    if not company.get("logo_url"):
        company["logo_url"] = None
    return company
