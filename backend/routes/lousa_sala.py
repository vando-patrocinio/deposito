"""Rotas da Lousa SALA — fila virtual para atendimento especializado.

Recebe TODOS os agendamentos da Isabella. O atendimento especializado
visualiza, decide o técnico real e transfere via `POST /lousa/tickets/{id}/transfer`.

Endpoints:
  GET  /api/lousa/sala                Bolhas em SALA do dia (default hoje)
  GET  /api/lousa/sala/dias           Datas com bolhas pendentes na SALA
  POST /api/lousa/sala/{ticket_id}/distribuir  Atalho: transfer + clear flag
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "lousa",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
    "notes": "View dedicada da Lousa SALA.",
}

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from core import DEMO_COMPANY_ID, require_role
from database import db

log = logging.getLogger("ponto.lousa_sala")
router = APIRouter(prefix="/api/lousa/sala", tags=["lousa-sala"])


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


def _today_br_iso() -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%d")


async def _sala_collaborator_id(company_id: str) -> str:
    """Resolve o id da SALA virtual deste tenant."""
    for candidate in ("col-sala", f"col-sala-{company_id}"):
        doc = await db.collaborators.find_one(
            {"id": candidate, "company_id": company_id},
            {"_id": 0, "id": 1})
        if doc:
            return doc["id"]
    return "col-sala"  # fallback


@router.get("")
async def listar_sala(
    date: Optional[str] = Query(None, description="YYYY-MM-DD (default: hoje)"),
    window: Optional[str] = Query(None, description="manha|tarde"),
    user: dict = Depends(require_role("gestor")),
):
    """Lista bolhas atualmente em SALA, agrupadas por janela.

    Bolhas em SALA = `assigned_collaborator_id == col-sala`
                     AND status ∈ {pendente, aberta, aguardando_atendimento}
                     AND needs_assignment_review = True.

    Atendimento especializado usa este endpoint para distribuir.
    """
    cid = _cid(user)
    sala_id = await _sala_collaborator_id(cid)
    date_iso = (date or _today_br_iso()).strip()

    query: Dict[str, Any] = {
        "company_id": cid,
        "assigned_collaborator_id": sala_id,
        "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]},
        "scheduled_time": {"$regex": f"^{date_iso}"},
    }
    if window in ("manha", "tarde"):
        query["scheduled_window"] = window

    rows = await db.tickets.find(query, {"_id": 0}).to_list(500)
    # ordena por hora cravada
    rows.sort(key=lambda t: t.get("scheduled_time", ""))

    # Agrupa por janela para a UI
    by_window: Dict[str, List[Dict[str, Any]]] = {"manha": [], "tarde": []}
    for t in rows:
        w = t.get("scheduled_window") or "manha"
        by_window.setdefault(w, []).append(t)

    return {
        "company_id": cid,
        "sala_id": sala_id,
        "date": date_iso,
        "total": len(rows),
        "by_window": by_window,
        "tickets": rows,
    }


@router.get("/dias")
async def listar_dias(
    user: dict = Depends(require_role("gestor")),
):
    """Datas (próximos 30 dias) com bolhas pendentes em SALA."""
    cid = _cid(user)
    sala_id = await _sala_collaborator_id(cid)

    pipe = [
        {"$match": {
            "company_id": cid,
            "assigned_collaborator_id": sala_id,
            "status": {"$in": ["pendente", "aberta",
                                  "aguardando_atendimento"]},
        }},
        {"$group": {
            "_id": {"$substr": ["$scheduled_time", 0, 10]},
            "count": {"$sum": 1},
            "manha": {
                "$sum": {"$cond": [
                    {"$eq": ["$scheduled_window", "manha"]}, 1, 0]}},
            "tarde": {
                "$sum": {"$cond": [
                    {"$eq": ["$scheduled_window", "tarde"]}, 1, 0]}},
        }},
        {"$sort": {"_id": 1}},
    ]
    days = [
        {"date": r["_id"], "count": r["count"],
         "manha": r.get("manha", 0), "tarde": r.get("tarde", 0)}
        async for r in db.tickets.aggregate(pipe)
        if r.get("_id")
    ]
    return {"sala_id": sala_id, "days": days}


@router.get("/count")
async def contagem_sala(
    user: dict = Depends(require_role("gestor")),
):
    """Contador rapido de triagem em SALA, com nivel de pressao.

    Retorno:
      {
        "total":   total ATIVO em SALA (qualquer data),
        "today":   bolhas com scheduled_time = hoje (BRT),
        "overdue": bolhas com scheduled_time em data passada (BRT),
        "future":  bolhas com scheduled_time em data futura,
        "level":   "calm" (<5) | "warn" (5-15) | "hot" (>15)
      }
    """
    cid = _cid(user)
    sala_id = await _sala_collaborator_id(cid)
    today_iso = _today_br_iso()

    base = {
        "company_id": cid,
        "assigned_collaborator_id": sala_id,
        "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]},
    }
    total = await db.tickets.count_documents(base)
    today = await db.tickets.count_documents({
        **base, "scheduled_time": {"$regex": f"^{today_iso}"}})
    overdue = await db.tickets.count_documents({
        **base, "scheduled_time": {"$lt": today_iso, "$ne": ""}})
    future = total - today - overdue
    if future < 0:
        future = 0

    if total < 5:
        level = "calm"
    elif total <= 15:
        level = "warn"
    else:
        level = "hot"

    return {
        "sala_id": sala_id,
        "total": total,
        "today": today,
        "overdue": overdue,
        "future": future,
        "level": level,
    }



@router.post("/{ticket_id}/distribuir")
async def distribuir(
    ticket_id: str,
    body: Dict[str, Any] = Body(...),
    user: dict = Depends(require_role("gestor")),
):
    """Distribui uma bolha da SALA para um técnico real.

    Body: {"collaborator_id": "col-xxx"}.
    Limpa `needs_assignment_review` e ajusta `assigned_collaborator_id`.
    Reusa a regra de posição já existente (próxima posição na fila do
    técnico). Não permite distribuir para outra Lousa virtual.
    """
    target_id = (body or {}).get("collaborator_id")
    if not target_id:
        raise HTTPException(400, "collaborator_id obrigatório")

    target = await db.collaborators.find_one(
        {"id": target_id}, {"_id": 0, "id": 1, "name": 1,
                              "company_id": 1, "is_virtual": 1})
    if not target:
        raise HTTPException(404, "Colaborador não encontrado")
    if target.get("is_virtual"):
        raise HTTPException(400, "Não pode distribuir para outra "
                                    "Lousa virtual")

    t = await db.tickets.find_one(
        {"id": ticket_id}, {"_id": 0, "id": 1, "company_id": 1,
                              "assigned_collaborator_id": 1,
                              "scheduled_window": 1})
    if not t:
        raise HTTPException(404, "Bolha não encontrada")
    if t["company_id"] != target.get("company_id"):
        raise HTTPException(400, "Bolha e técnico de tenants diferentes")

    # Próxima posição na fila do técnico destino
    last = await db.tickets.find(
        {"assigned_collaborator_id": target_id,
         "status": {"$in": ["pendente", "aberta",
                              "aguardando_atendimento"]}},
        {"_id": 0, "position": 1}).sort("position", -1).to_list(1)
    next_pos = ((last[0].get("position") or 0) + 1) if last else 0

    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {
            "assigned_collaborator_id": target_id,
            "needs_assignment_review": False,
            "position": next_pos,
            "distributed_from_sala_at": datetime.now(
                timezone.utc).isoformat(),
            "distributed_by": user.get("email") or user.get("id"),
        }})
    log.info("[lousa_sala] ticket=%s SALA → %s (%s)",
              ticket_id, target_id, target.get("name"))
    updated = await db.tickets.find_one(
        {"id": ticket_id}, {"_id": 0})
    return {"ok": True, "ticket": updated,
              "to": {"id": target_id, "name": target.get("name")}}
