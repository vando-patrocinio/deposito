"""Lousa - Manager Callbacks (pedidos de contato pendentes).

Extraido de `routes/lousa.py` para reduzir o monolito (era ~8763 LOC).

Endpoints:
- GET    /api/lousa/manager-callbacks
- POST   /api/lousa/manager-callbacks/{req_id}/resolve
- POST   /api/lousa/manager-callbacks/{req_id}/release-back
- POST   /api/lousa/manager-callbacks/{req_id}/create-new-ticket
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "operacoes",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["ticket.updated"],
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import (
    DEMO_COMPANY_ID,
    geocode_address,
    get_current_user,
    now_iso,
    require_role,
)
from database import db

logger = logging.getLogger("ponto")
router = APIRouter(prefix="/api", tags=["lousa-manager-callbacks"])


# Tipos espelhados de routes/lousa.py (evita circular import).
Priority = Literal["normal", "horario", "prioridade", "urgente"]
TicketType = Literal[
    "reparo", "instalacao", "retirada", "prioridade",
    "preventiva", "venda", "rompimento",
]


@router.get("/lousa/manager-callbacks")
async def list_manager_callbacks(
    status: str = "pending",
    limit: int = 50,
    user: dict = Depends(get_current_user),
):
    """Lista pedidos de contato pendentes/contactados/resolvidos."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q = {"company_id": cid}
    if status != "all":
        q["status"] = status
    items = await db.lousa_manager_callback_requests.find(
        q, {"_id": 0}).sort("requested_at", -1).limit(min(limit, 200))\
        .to_list(200)
    return {"items": items, "count": len(items)}


@router.post("/lousa/manager-callbacks/{req_id}/resolve")
async def resolve_manager_callback(
    req_id: str,
    payload: Dict[str, Any],
    user: dict = Depends(require_role("gestor")),
):
    """Gestor marca um pedido como contatado / resolvido.

    Body:
      action: "contacted" | "resolved_close" | "resolved_reschedule" | "resolved_reassign"
      observacao: texto livre (obrigatório, mínimo 5 chars)
      new_scheduled_time: opcional, se action="resolved_reschedule"
      new_collaborator_id: opcional, se action="resolved_reassign"
      close_outcome: opcional, default "informada" (se action="resolved_close")
    """
    action = (payload.get("action") or "").strip()
    if action not in ("contacted", "resolved_close",
                       "resolved_reschedule", "resolved_reassign"):
        raise HTTPException(400, "action inválido")
    obs = (payload.get("observacao") or "").strip()
    if len(obs) < 5:
        raise HTTPException(400, "observacao mínima 5 caracteres")

    cid = user.get("company_id") or DEMO_COMPANY_ID
    req = await db.lousa_manager_callback_requests.find_one(
        {"id": req_id, "company_id": cid}, {"_id": 0})
    if not req:
        raise HTTPException(404, "Pedido de contato não encontrado")
    if req.get("status") == "resolved":
        raise HTTPException(409, "Pedido já resolvido")

    now = datetime.now(timezone.utc).isoformat()
    new_status = "contacted" if action == "contacted" else "resolved"
    update = {
        "status": new_status,
        "manager_action": action,
        "manager_observacao": obs,
        "manager_id": user.get("id"),
        "manager_name": user.get("name") or user.get("email"),
        f"{new_status}_at": now,
    }
    if action == "contacted":
        # Só marca que o gestor ligou — não muda OS ainda
        await db.lousa_manager_callback_requests.update_one(
            {"id": req_id}, {"$set": update})
        # Adiciona ao histórico do ticket
        await db.tickets.update_one(
            {"id": req["ticket_id"]},
            {"$push": {"manager_callback_log": {
                "ts": now, "action": "contacted",
                "manager": user.get("name") or "",
                "observacao": obs,
            }}},
        )
        try:
            from services.event_bus import emit_event
            await emit_event(
                "ticket.updated",
                company_id=cid,
                source="lousa",
                payload={},
            )
        except Exception:
            pass
        return {"ok": True, "status": "contacted",
                "next_action_required": True,
                "message": "Contato registrado. Defina o próximo passo "
                           "(fechar improdutiva, reagendar ou realocar)."}

    # Resolved — modifica a OS de fato
    ticket_id = req["ticket_id"]
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "OS associada não existe mais")

    collab = None
    if action == "resolved_close":
        outcome = payload.get("close_outcome") or "informada"
        if outcome not in ("informada", "sucesso", "cancelada"):
            outcome = "informada"
        # ════════════════════════════════════════════════════════════
        # CTO 19/06/2026 — Onda 3 hook (P0 bypass manager_callback)
        # Gestor finaliza remotamente. Exige motivo ≥20 chars.
        # outcome="sucesso" → enforcement completa (ONT/CTO/Porta ou
        # override). outcome=informada|cancelada → audit non-operational.
        # ════════════════════════════════════════════════════════════
        from services.os_finalization_validator import (
            validate_finalization, record_validation,
        )
        sub_id = (
            t.get("subscriber_id")
            or (t.get("client_snapshot") or {}).get("id")
        )
        collab_for_ticket = (
            t.get("assigned_collaborator_id")
            or user.get("id") or "manager"
        )
        # Para outcome="sucesso", precisa ONT/CTO/Porta OU override pelo gestor
        cd_validate = {
            "outcome": outcome,
            "manager_close_reason": (obs or "").strip(),
            "onda3_override_reason": (obs or "").strip()
                if outcome == "sucesso" and len((obs or "").strip()) >= 20
                else None,
        }
        # Para sucesso, copia ONT/CTO/Porta de completion_data ou client_snapshot
        if outcome == "sucesso":
            existing_cd = t.get("completion_data") or {}
            cd_validate["ont"] = existing_cd.get("ont")
            cd_validate["ont_sn"] = existing_cd.get("ont_sn")
            cd_validate["ont_mac"] = existing_cd.get("ont_mac")
            cd_validate["cto_id"] = existing_cd.get("cto_id") or (
                t.get("client_snapshot") or {}).get("cto_id")
            cd_validate["port_number"] = existing_cd.get("port_number") or (
                t.get("client_snapshot") or {}).get("cto_port_number")

        ok_o3, diag_o3 = await validate_finalization(
            db,
            company_id=cid,
            service_type=(t.get("type") or "reparo"),
            ticket_id=ticket_id,
            service_id=None,
            subscriber_id=sub_id,
            collaborator_id=collab_for_ticket,
            completion_data=cd_validate,
        )
        await record_validation(
            db, company_id=cid, ok=ok_o3, diag=diag_o3,
            ticket_id=ticket_id, service_id=None,
            actor_user_id=user.get("id"),
            actor_email=user.get("email"),
        )
        if not ok_o3:
            raise HTTPException(403, {
                "error": "onda3_manager_close_bloqueada",
                "missing": diag_o3.get("missing"),
                "human_reason": diag_o3.get("reason"),
                "outcome": outcome,
                "diag": diag_o3,
            })

        await db.tickets.update_one(
            {"id": ticket_id},
            {"$set": {
                "status": "finalizada",
                "outcome": outcome,
                "closed_at": now,
                "closed_by": user.get("id") or "manager",
                "manager_close_reason": obs,
                "manager_callback_resolved": True,
                "needs_manager_action": False,
                "onda3_validation_diag": diag_o3,
            }},
        )
        try:
            from services.event_bus import emit_event
            await emit_event(
                "ticket.updated",
                company_id=(t or {}).get("company_id"),
                source="lousa",
                payload={},
            )
        except Exception:
            pass
    elif action == "resolved_reschedule":
        new_time = payload.get("new_scheduled_time")
        if not new_time:
            raise HTTPException(400, "new_scheduled_time obrigatório")
        await db.tickets.update_one(
            {"id": ticket_id},
            {"$set": {
                "scheduled_time": new_time,
                "manager_callback_resolved": True,
                "needs_manager_action": False,
                "rescheduled_at": now,
                "rescheduled_by": user.get("id") or "manager",
                "rescheduled_reason": obs,
            }},
        )
        try:
            from services.event_bus import emit_event
            await emit_event(
                "ticket.updated",
                company_id=(t or {}).get("company_id"),
                source="lousa",
                payload={},
            )
        except Exception:
            pass
    elif action == "resolved_reassign":
        new_collab = payload.get("new_collaborator_id")
        if not new_collab:
            raise HTTPException(400, "new_collaborator_id obrigatório")
        collab = await db.collaborators.find_one(
            {"id": new_collab, "company_id": cid},
            {"_id": 0, "id": 1, "name": 1})
        if not collab:
            raise HTTPException(404, "Colaborador não encontrado")
        await db.tickets.update_one(
            {"id": ticket_id},
            {"$set": {
                "assigned_collaborator_id": new_collab,
                "assigned_collaborator_name": collab.get("name"),
                "manager_callback_resolved": True,
                "needs_manager_action": False,
                "reassigned_at": now,
                "reassigned_by": user.get("id") or "manager",
                "reassign_reason": obs,
            }},
        )
        try:
            from services.event_bus import emit_event
            await emit_event(
                "ticket.updated",
                company_id=(collab or {}).get("company_id"),
                source="lousa",
                payload={},
            )
        except Exception:
            pass

    await db.lousa_manager_callback_requests.update_one(
        {"id": req_id}, {"$set": update})
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$push": {"manager_callback_log": {
            "ts": now, "action": action,
            "manager": user.get("name") or "",
            "observacao": obs,
        }}},
    )
    try:
        from services.event_bus import emit_event
        await emit_event(
            "ticket.updated",
            company_id=(collab or {}).get("company_id") if collab else (t or {}).get("company_id"),
            source="lousa",
            payload={},
        )
    except Exception:
        pass
    return {"ok": True, "status": "resolved", "action": action,
            "ticket_id": ticket_id}


# ---------------------------------------------------------------------------
# Manager Callback: liberar OS de volta para o técnico (sem fechar)
# ---------------------------------------------------------------------------
@router.post("/lousa/manager-callbacks/{req_id}/release-back")
async def release_back_manager_callback(
    req_id: str,
    payload: Dict[str, Any],
    user: dict = Depends(require_role("gestor")),
):
    """Gestor libera a OS pausada de volta para o técnico (mesmo ou outro).

    Body:
      observacao: obrigatório (>=5 chars) — o que o cliente disse
      new_collaborator_id: opcional — se quiser realocar pra outro técnico
      new_scheduled_time: opcional — se quiser reagendar pra outra hora
    """
    obs = (payload.get("observacao") or "").strip()
    if len(obs) < 5:
        raise HTTPException(400, "observacao mínima 5 caracteres")

    cid = user.get("company_id") or DEMO_COMPANY_ID
    req = await db.lousa_manager_callback_requests.find_one(
        {"id": req_id, "company_id": cid}, {"_id": 0})
    if not req:
        raise HTTPException(404, "Pedido de contato não encontrado")
    if req.get("status") == "resolved":
        raise HTTPException(409, "Pedido já resolvido")

    ticket_id = req["ticket_id"]
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "OS associada não existe mais")

    now = datetime.now(timezone.utc).isoformat()
    set_fields = {
        "needs_manager_action": False,
        "manager_callback_resolved": True,
        "released_back_at": now,
        "released_back_by": user.get("id") or "manager",
        "released_back_reason": obs,
    }

    collab = None
    new_collab = (payload.get("new_collaborator_id") or "").strip()
    if new_collab and new_collab != t.get("assigned_collaborator_id"):
        collab = await db.collaborators.find_one(
            {"id": new_collab, "company_id": cid},
            {"_id": 0, "id": 1, "name": 1})
        if not collab:
            raise HTTPException(404, "Colaborador novo não encontrado")
        set_fields["assigned_collaborator_id"] = new_collab
        set_fields["assigned_collaborator_name"] = collab.get("name")
        set_fields["reassigned_at"] = now
        set_fields["reassigned_by"] = user.get("id") or "manager"
        set_fields["reassign_reason"] = obs

    new_time = (payload.get("new_scheduled_time") or "").strip()
    if new_time:
        set_fields["scheduled_time"] = new_time
        set_fields["rescheduled_at"] = now
        set_fields["rescheduled_by"] = user.get("id") or "manager"
        set_fields["rescheduled_reason"] = obs

    await db.tickets.update_one({"id": ticket_id}, {"$set": set_fields})
    try:
        from services.event_bus import emit_event
        await emit_event(
            "ticket.updated",
            company_id=(collab or {}).get("company_id") if collab else (t or {}).get("company_id"),
            source="lousa",
            payload={},
        )
    except Exception:
        pass
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$push": {"manager_callback_log": {
            "ts": now, "action": "released_back",
            "manager": user.get("name") or "",
            "observacao": obs,
            "new_collaborator_id": new_collab or None,
            "new_scheduled_time": new_time or None,
        }}},
    )
    try:
        from services.event_bus import emit_event
        await emit_event(
            "ticket.updated",
            company_id=(collab or {}).get("company_id") if collab else (t or {}).get("company_id"),
            source="lousa",
            payload={},
        )
    except Exception:
        pass
    await db.lousa_manager_callback_requests.update_one(
        {"id": req_id},
        {"$set": {
            "status": "resolved",
            "manager_action": "released_back",
            "manager_observacao": obs,
            "manager_id": user.get("id"),
            "manager_name": user.get("name") or user.get("email"),
            "resolved_at": now,
        }},
    )
    return {"ok": True, "ticket_id": ticket_id, "released_back": True}


# ---------------------------------------------------------------------------
# Manager Callback: cria nova OS pra continuar o serviço
# (a OS original PERMANECE pausada até o gestor decidir o que fazer com ela)
# ---------------------------------------------------------------------------
class CreateNewOsFromCallbackIn(BaseModel):
    observacao: str = Field(..., min_length=5)
    # Dados da nova OS (gestor edita tudo)
    client_name: str
    address: str
    neighborhood: str = ""
    phone: str = ""
    relato: str = ""
    pppoe_user: str = ""
    type: TicketType = "reparo"
    priority: Priority = "normal"
    scheduled_time: Optional[str] = None
    assigned_collaborator_id: str


@router.post("/lousa/manager-callbacks/{req_id}/create-new-ticket")
async def create_new_ticket_from_callback(
    req_id: str,
    payload: CreateNewOsFromCallbackIn,
    user: dict = Depends(require_role("gestor")),
):
    """Cria uma NOVA OS pra continuar o atendimento do cliente.

    A OS ORIGINAL permanece pausada (needs_manager_action=true) até o
    gestor explicitamente fechar improdutiva OU liberar de volta.
    A nova OS recebe `parent_ticket_id` e `from_manager_callback_id`
    pra rastreabilidade.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    req = await db.lousa_manager_callback_requests.find_one(
        {"id": req_id, "company_id": cid}, {"_id": 0})
    if not req:
        raise HTTPException(404, "Pedido de contato não encontrado")

    coll = await db.collaborators.find_one(
        {"id": payload.assigned_collaborator_id},
        {"_id": 0, "company_id": 1, "name": 1, "id": 1},
    )
    if not coll:
        raise HTTPException(404, "Colaborador novo não encontrado")

    # Geocode (best-effort)
    lat, lng = None, None
    try:
        geo = await geocode_address(payload.address)
        lat, lng = geo.lat, geo.lng
    except Exception as e:
        logger.warning("[lousa.callback.new-os] geocode falhou '%s': %s",
                       payload.address, e)

    last = await db.tickets.find(
        {"assigned_collaborator_id": payload.assigned_collaborator_id,
         "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]}},
        {"_id": 0, "position": 1},
    ).sort("position", -1).to_list(1)
    # bug-fix 19/06/2026 — tickets legados sem `position` cairiam em KeyError.
    next_pos = (last[0].get("position", -1) + 1) if last else 0

    parent_ticket_id = req["ticket_id"]
    now = now_iso()
    new_id = f"tkt-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": new_id,
        "client_id": str(uuid.uuid4()),
        "client_snapshot": {
            "name": payload.client_name,
            "address": payload.address,
            "neighborhood": payload.neighborhood,
            "phone": payload.phone,
            "latitude": lat, "longitude": lng,
            "relato": payload.relato,
            "pppoe_user": payload.pppoe_user,
            "test_history": [],
        },
        "type": payload.type,
        "priority": payload.priority,
        "scheduled_time": payload.scheduled_time,
        "position": next_pos,
        "status": "pendente",
        "assigned_collaborator_id": payload.assigned_collaborator_id,
        "company_id": coll.get("company_id") or DEMO_COMPANY_ID,
        "opened_at": None, "closed_at": None, "closed_by": None,
        "close_location": None, "outcome": None,
        "whatsapp_status": "nao_enviado", "whatsapp_last_message": None,
        "completion_data": None, "admin_action": None, "admin_notes": None,
        "ai_triage_pending": True,
        "signal_at_open": None, "signal_at_open_at": None,
        "signal_at_close": None, "signal_at_close_at": None,
        "created_at": now,
        # Rastreabilidade — OS criada a partir de callback do gestor
        "parent_ticket_id": parent_ticket_id,
        "from_manager_callback_id": req_id,
        "creation_reason": "manager_callback_continuation",
    }
    await db.tickets.insert_one(doc)

    # Marca callback como tendo gerado nova OS (mas NÃO resolve — gestor
    # ainda precisa decidir o destino da OS original)
    await db.lousa_manager_callback_requests.update_one(
        {"id": req_id},
        {"$set": {
            "new_ticket_id": new_id,
            "new_ticket_created_at": now,
            "new_ticket_created_by": user.get("id") or "manager",
            "manager_observacao": payload.observacao,
            "manager_id": user.get("id"),
            "manager_name": user.get("name") or user.get("email"),
        }},
    )
    # Loga no ticket original
    await db.tickets.update_one(
        {"id": parent_ticket_id},
        {"$push": {"manager_callback_log": {
            "ts": now, "action": "new_ticket_created",
            "manager": user.get("name") or "",
            "observacao": payload.observacao,
            "new_ticket_id": new_id,
        }}},
    )
    # Lazy import pra evitar circular com routes.lousa
    from routes.lousa import _log_ticket_action
    await _log_ticket_action(
        ticket_id=new_id, action="criada_via_callback",
        actor_id=user["id"], actor_name=user.get("name", "Gestor"),
        actor_role=user.get("role", "gestor"),
        details=(f"Continuação do callback {req_id} "
                 f"(OS original: {parent_ticket_id})"),
        company_id=doc["company_id"],
    )
    return {
        "ok": True,
        "new_ticket_id": new_id,
        "parent_ticket_id": parent_ticket_id,
        "callback_request_id": req_id,
        "message": ("Nova OS criada. A OS original continua pausada "
                    "até você decidir o que fazer com ela "
                    "(fechar improdutiva ou liberar de volta)."),
    }
