"""routes/clients_segments.py — Segmentações de clientes inspiradas no Atlaz.

Endpoints que retornam listas de assinantes/contratos por categoria:
  recent          — criados nos últimos 30 dias
  overdue         — fatura(s) em aberto (vencidas)
  blocked         — radius_state em REDUZIDO|WALLED_GARDEN|SUSPENSO
  no_charges      — sem fatura futura cadastrada (status ativo)
  connected       — com sessão radius ativa AGORA
  disconnected    — sem sessão radius ativa (mas contrato ativo)
  no_contract     — assinante sem contrato vigente

Todas as queries são leves (limit padrão 200) e enriquecem com:
  - radius_state (do contrato ativo)
  - active_session (sessão atual se houver)
  - max_overdue_days (maior atraso de fatura)
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

from core import DEMO_COMPANY_ID, get_current_user, is_super_admin
from database import db

logger = logging.getLogger("ponto.clients_segments")
router = APIRouter(prefix="/api/clients-segments", tags=["clients-segments"])


def _cid(user: dict) -> str:
    if is_super_admin(user):
        return (user.get("_active_company") or user.get("company_id")
                or DEMO_COMPANY_ID)
    return user.get("company_id") or DEMO_COMPANY_ID


async def _enrich(cid: str, subs: List[dict]) -> List[dict]:
    """Anexa radius_state + active_session + max_overdue_days nos subscribers."""
    sub_ids = [s["id"] for s in subs if s.get("id")]
    if not sub_ids:
        return subs
    # Contratos
    contracts_map = {}
    async for c in db.contracts.find(
        {"company_id": cid, "subscriber_id": {"$in": sub_ids},
         "status": {"$ne": "cancelado"}},
        {"_id": 0, "subscriber_id": 1, "radius_state": 1, "plan_name": 1,
         "monthly_value": 1, "due_day": 1},
    ):
        contracts_map[c["subscriber_id"]] = c
    # Sessões ativas (por pppoe_user)
    pppoe_users = [s.get("pppoe_user") for s in subs if s.get("pppoe_user")]
    sessions_map = {}
    if pppoe_users:
        async for sess in db.radius_sessions.find(
            {"company_id": cid, "status": "active",
             "username": {"$in": pppoe_users}},
            {"_id": 0, "username": 1, "framed_ip": 1, "nas_ip": 1,
             "started_at": 1, "session_time": 1, "bytes_in": 1,
             "bytes_out": 1},
        ):
            sessions_map[sess["username"]] = sess
    today = datetime.now(timezone.utc).date()
    # Overdue map (best-effort)
    overdue_map: Dict[str, int] = {}
    for coll in ("invoices", "billing_invoices", "faturas"):
        try:
            async for inv in db[coll].find(
                {"company_id": cid, "subscriber_id": {"$in": sub_ids},
                 "status": {"$in": ["open", "pending", "vencida",
                                     "em_aberto", "atrasada", "OVERDUE"]}},
                {"_id": 0, "subscriber_id": 1, "due_date": 1},
            ):
                sid = inv.get("subscriber_id")
                due = inv.get("due_date")
                if not sid or not due:
                    continue
                try:
                    ddate = (datetime.fromisoformat(
                        due.replace("Z", "+00:00")).date()
                              if isinstance(due, str) else due.date())
                    if ddate >= today:
                        continue
                    days = (today - ddate).days
                    if days > overdue_map.get(sid, 0):
                        overdue_map[sid] = days
                except (ValueError, TypeError, AttributeError):
                    continue
        except Exception:
            continue
    for s in subs:
        sid = s.get("id")
        c = contracts_map.get(sid)
        s["radius_state"] = (c or {}).get("radius_state") or "—"
        s["contract_plan_name"] = (c or {}).get("plan_name")
        s["contract_monthly_value"] = (c or {}).get("monthly_value")
        s["contract_due_day"] = (c or {}).get("due_day")
        s["has_contract"] = bool(c)
        s["max_overdue_days"] = overdue_map.get(sid, 0)
        s["active_session"] = sessions_map.get(s.get("pppoe_user"))
        s["is_connected"] = bool(sessions_map.get(s.get("pppoe_user")))
    return subs


@router.get("/{segment}")
async def list_segment(
    segment: str,
    search: str = "",
    limit: int = Query(default=200, ge=1, le=1000),
    user: dict = Depends(get_current_user),
):
    """Retorna assinantes filtrados pelo segmento.

    segmentos: recent | overdue | blocked | no_charges | connected |
               disconnected | no_contract | contracts | contracts_disabled
    """
    cid = _cid(user)
    base_q: Dict[str, Any] = {"company_id": cid}
    if search:
        base_q["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"pppoe_user": {"$regex": search, "$options": "i"}},
            {"phone": {"$regex": search, "$options": "i"}},
            {"document": {"$regex": search, "$options": "i"}},
        ]

    if segment == "recent":
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        base_q["created_at"] = {"$gte": cutoff}
        subs = await db.subscribers.find(base_q, {"_id": 0})\
            .sort("created_at", -1).limit(limit).to_list(limit)
        items = await _enrich(cid, subs)
        return {"items": items, "count": len(items), "segment": segment}

    if segment == "overdue":
        subs = await db.subscribers.find(base_q, {"_id": 0})\
            .limit(2000).to_list(2000)
        items = await _enrich(cid, subs)
        items = [s for s in items if (s.get("max_overdue_days") or 0) > 0]
        items.sort(key=lambda s: -s.get("max_overdue_days", 0))
        return {"items": items[:limit], "count": len(items),
                "segment": segment}

    if segment == "blocked":
        # Cruza contratos com radius_state bloqueante
        blocked_states = ("REDUZIDO", "WALLED_GARDEN", "SUSPENSO")
        contracts = await db.contracts.find(
            {"company_id": cid, "radius_state": {"$in": list(blocked_states)},
             "status": {"$ne": "cancelado"}},
            {"_id": 0, "subscriber_id": 1, "radius_state": 1},
        ).to_list(5000)
        sub_ids = [c["subscriber_id"] for c in contracts
                   if c.get("subscriber_id")]
        if not sub_ids:
            return {"items": [], "count": 0, "segment": segment}
        base_q["id"] = {"$in": sub_ids}
        subs = await db.subscribers.find(base_q, {"_id": 0})\
            .limit(limit).to_list(limit)
        items = await _enrich(cid, subs)
        return {"items": items, "count": len(items), "segment": segment}

    if segment == "connected":
        sessions = await db.radius_sessions.find(
            {"company_id": cid, "status": "active"},
            {"_id": 0, "username": 1}).to_list(5000)
        usernames = [s["username"] for s in sessions if s.get("username")]
        if not usernames:
            return {"items": [], "count": 0, "segment": segment}
        base_q["pppoe_user"] = {"$in": usernames}
        subs = await db.subscribers.find(base_q, {"_id": 0})\
            .limit(limit).to_list(limit)
        items = await _enrich(cid, subs)
        return {"items": items, "count": len(items), "segment": segment}

    if segment == "disconnected":
        sessions = await db.radius_sessions.find(
            {"company_id": cid, "status": "active"},
            {"_id": 0, "username": 1}).to_list(5000)
        connected_users = {s["username"] for s in sessions if s.get("username")}
        # Apenas com contrato ativo
        contracts = await db.contracts.find(
            {"company_id": cid, "status": {"$ne": "cancelado"},
             "radius_state": {"$nin": ["SUSPENSO", "CANCELADO"]}},
            {"_id": 0, "subscriber_id": 1, "pppoe_user": 1}).to_list(10000)
        target_sub_ids = [c["subscriber_id"] for c in contracts
                          if c.get("subscriber_id")
                          and c.get("pppoe_user") not in connected_users]
        if not target_sub_ids:
            return {"items": [], "count": 0, "segment": segment}
        base_q["id"] = {"$in": target_sub_ids}
        subs = await db.subscribers.find(base_q, {"_id": 0})\
            .limit(limit).to_list(limit)
        items = await _enrich(cid, subs)
        return {"items": items, "count": len(items), "segment": segment}

    if segment == "no_contract":
        contracts = await db.contracts.find(
            {"company_id": cid, "status": {"$ne": "cancelado"}},
            {"_id": 0, "subscriber_id": 1}).to_list(20000)
        with_contract = {c["subscriber_id"] for c in contracts
                          if c.get("subscriber_id")}
        subs_all = await db.subscribers.find(base_q, {"_id": 0})\
            .limit(2000).to_list(2000)
        subs_filtered = [s for s in subs_all
                          if s.get("id") not in with_contract]
        items = await _enrich(cid, subs_filtered[:limit])
        return {"items": items, "count": len(subs_filtered),
                "segment": segment}

    if segment == "no_charges":
        # Assinantes ativos sem futura cobrança (best-effort: nenhuma invoice
        # com due_date > hoje)
        today = datetime.now(timezone.utc).date().isoformat()
        future_subs = set()
        for coll in ("invoices", "billing_invoices", "faturas"):
            try:
                async for inv in db[coll].find(
                    {"company_id": cid, "due_date": {"$gte": today},
                     "status": {"$in": ["open", "pending", "scheduled",
                                          "future", "agendada"]}},
                    {"_id": 0, "subscriber_id": 1},
                ):
                    if inv.get("subscriber_id"):
                        future_subs.add(inv["subscriber_id"])
            except Exception:
                continue
        subs_all = await db.subscribers.find(base_q, {"_id": 0})\
            .limit(5000).to_list(5000)
        subs_filtered = [s for s in subs_all
                          if s.get("id") not in future_subs]
        items = await _enrich(cid, subs_filtered[:limit])
        return {"items": items, "count": len(subs_filtered),
                "segment": segment}

    if segment in ("contracts", "contracts_disabled"):
        q = {"company_id": cid}
        if segment == "contracts":
            q["status"] = "ativo"
            q["radius_state"] = {"$ne": "CANCELADO"}
        else:
            q["$or"] = [
                {"status": {"$in": ["cancelado", "encerrado"]}},
                {"radius_state": "CANCELADO"},
            ]
        items = await db.contracts.find(q, {"_id": 0})\
            .sort("created_at", -1).limit(limit).to_list(limit)
        return {"items": items, "count": len(items), "segment": segment}

    # Default fallback: tudo
    subs = await db.subscribers.find(base_q, {"_id": 0})\
        .limit(limit).to_list(limit)
    items = await _enrich(cid, subs)
    return {"items": items, "count": len(items), "segment": "all"}


@router.get("/_counts/dashboard")
async def counts_dashboard(user: dict = Depends(get_current_user)):
    """Retorna contagens de cada segmento — usado pelo badge no menu."""
    cid = _cid(user)
    out: Dict[str, int] = {}
    out["total"] = await db.subscribers.count_documents({"company_id": cid})

    # Connected/Disconnected via sessions
    out["connected"] = await db.radius_sessions.count_documents(
        {"company_id": cid, "status": "active"})

    # Blocked via contracts
    out["blocked"] = await db.contracts.count_documents(
        {"company_id": cid, "status": {"$ne": "cancelado"},
         "radius_state": {"$in": ["REDUZIDO", "WALLED_GARDEN", "SUSPENSO"]}})

    out["contracts_active"] = await db.contracts.count_documents(
        {"company_id": cid, "status": "ativo"})
    out["contracts_disabled"] = await db.contracts.count_documents(
        {"company_id": cid,
         "$or": [{"status": {"$in": ["cancelado", "encerrado"]}},
                  {"radius_state": "CANCELADO"}]})

    # Recent
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    out["recent"] = await db.subscribers.count_documents(
        {"company_id": cid, "created_at": {"$gte": cutoff}})
    return out
