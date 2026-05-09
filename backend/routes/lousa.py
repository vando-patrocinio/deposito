"""Lousa (Smart Service Board) - Bolhas de notas de serviço dos técnicos.

Originalmente do projeto SmartProv (smart1), agora integrado com:
- Sistema de ponto (clock_records) - máquina de estados (entrada → almoço → saída)
- Cerca virtual da nota (auto-criada do endereço da bolha aberta)
- Notificações in-app para gestor/admin quando técnico encerra com bolha aberta

Integração com clock.py:
- Técnico só pode abrir bolha após bater "Entrada" do dia
- Não pode bater "Início intervalo" / "Saída" com bolha aberta (deve fechar antes)
- Lousa fica visualmente travada entre "Início intervalo" e "Fim intervalo"
- Ao bater "Saída" com bolha aberta → frontend pergunta + endpoint força-encerra + cria notification
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import (
    DEMO_COMPANY_ID,
    effective_company_id,
    geocode_address,
    get_current_user,
    now_iso,
    require_role,
    tenant_filter,
    today_str,
)
from database import db

logger = logging.getLogger("ponto")
router = APIRouter(prefix="/api", tags=["lousa"])


# -------------------------------------------------------------------------
# Models
# -------------------------------------------------------------------------
Priority = Literal["normal", "horario", "prioridade"]
TicketType = Literal["reparo", "instalacao", "retirada"]
TicketStatus = Literal[
    "pendente", "aberta", "aguardando_atendimento",
    "finalizada", "encerrada", "reagendada", "cancelada"
]
Outcome = Literal["sucesso", "informada"]

POINTS_BY_TYPE: Dict[str, float] = {"instalacao": 3.0, "retirada": 1.5, "reparo": 1.0}
PRIORITY_RANK = {"prioridade": 0, "horario": 1, "normal": 2}
ADMIN_RESOLVED = ("encerrada", "reagendada", "cancelada")
TECH_RESOLVED = ("finalizada",)


class NetworkTest(BaseModel):
    date: str
    signal_dbm: float
    ping_ms: float
    notes: Optional[str] = None


class ClientSnapshot(BaseModel):
    name: str
    address: str
    neighborhood: str
    phone: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    relato: str
    test_history: List[NetworkTest] = Field(default_factory=list)


class CompletionData(BaseModel):
    sinal: float
    qtd_drop: int
    esticadores: int
    conectores_fast: int
    cabo_rede: float
    conectores_rede: int
    ont: Optional[str] = None
    fotos: List[str] = Field(default_factory=list)
    observacoes: Optional[str] = None


class TicketIn(BaseModel):
    """Cadastro de uma nova bolha (nota de serviço) — apenas gestor/admin."""
    client_name: str
    address: str
    neighborhood: str = ""
    phone: str = ""
    relato: str = ""
    type: TicketType = "reparo"
    priority: Priority = "normal"
    scheduled_time: Optional[str] = None
    assigned_collaborator_id: str
    test_history: List[NetworkTest] = Field(default_factory=list)


class ReorderItem(BaseModel):
    id: str
    position: int


class ReorderIn(BaseModel):
    items: List[ReorderItem]


class FinalizeIn(BaseModel):
    completion_data: CompletionData
    latitude: float
    longitude: float
    outcome: Outcome = "sucesso"


class AdminCloseIn(BaseModel):
    action: Literal["encerrar", "reagendar", "cancelar"]
    notes: Optional[str] = None
    new_scheduled_time: Optional[str] = None


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------
def compute_locked_positions(tickets_sorted: List[Dict[str, Any]]) -> set:
    """Posições travadas: 'horario'/'prioridade' + a anterior a 'horario'."""
    locked = set()
    for i, t in enumerate(tickets_sorted):
        if t["priority"] in ("horario", "prioridade"):
            locked.add(i)
            if t["priority"] == "horario" and i - 1 >= 0:
                locked.add(i - 1)
    return locked


async def _user_collaborator_id(user: dict) -> Optional[str]:
    """Retorna o collaborator_id ligado ao usuário (se for colaborador)."""
    return user.get("collaborator_id")


async def _today_clock_state(collaborator_id: str) -> dict:
    """Retorna estado do dia: quais pontos já foram batidos com sucesso."""
    today = today_str()
    records = await db.clock_records.find(
        {"collaborator_id": collaborator_id, "date": today,
         "status": {"$in": ["Válido", "Offline sincronizado"]}},
        {"_id": 0, "type": 1, "time": 1},
    ).to_list(50)
    types = {r["type"] for r in records}
    return {
        "has_entrada": "Entrada" in types,
        "has_inicio_intervalo": "Início intervalo" in types,
        "has_fim_intervalo": "Fim intervalo" in types,
        "has_saida": "Saída" in types,
        "in_intervalo": ("Início intervalo" in types) and ("Fim intervalo" not in types),
        "ended_day": "Saída" in types,
        "records": sorted(records, key=lambda r: r["time"]),
    }


async def _has_active_ticket(collaborator_id: str) -> Optional[dict]:
    """Retorna a bolha em estado 'aberta'/'aguardando_atendimento' do colaborador (se houver)."""
    return await db.tickets.find_one(
        {"assigned_collaborator_id": collaborator_id,
         "status": {"$in": ["aberta", "aguardando_atendimento"]}},
        {"_id": 0},
    )


async def _create_notification(
    *, type_: str, title: str, message: str,
    collaborator_id: Optional[str], ticket_id: Optional[str],
    company_id: str, severity: str = "warning",
) -> dict:
    """Cria notificação in-app destinada a gestor/administrador."""
    n = {
        "id": f"ntf-{uuid.uuid4().hex[:10]}",
        "type": type_,                  # ex: 'ticket_unfinished_on_exit', 'ai_dwell_alert'
        "title": title,
        "message": message,
        "collaborator_id": collaborator_id,
        "ticket_id": ticket_id,
        "company_id": company_id,
        "severity": severity,           # info | warning | critical
        "read_by": [],                  # ids de usuários que leram
        "created_at": now_iso(),
    }
    await db.notifications.insert_one(n)
    n.pop("_id", None)
    return n


# -------------------------------------------------------------------------
# READ - Lousa do colaborador / Lista para gestor
# -------------------------------------------------------------------------
@router.get("/lousa/me")
async def get_my_lousa(user: dict = Depends(get_current_user)):
    """Lousa do colaborador logado: bolhas ativas + estado do ponto + última info."""
    if user["role"] != "colaborador":
        raise HTTPException(403, "Endpoint exclusivo para colaboradores")
    cid = await _user_collaborator_id(user)
    if not cid:
        raise HTTPException(400, "Usuário não está vinculado a um colaborador")
    return await _lousa_for_collaborator(cid)


@router.get("/lousa/by-collaborator/{cid}")
async def get_lousa_by_collaborator(cid: str):
    """Lousa pública por collaborator_id (mobile PWA não tem auth)."""
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0, "id": 1})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    return await _lousa_for_collaborator(cid)


async def _lousa_for_collaborator(cid: str) -> dict:
    state = await _today_clock_state(cid)
    active_states = ["pendente", "aberta", "aguardando_atendimento"]
    active_raw = await db.tickets.find(
        {"assigned_collaborator_id": cid, "status": {"$in": active_states}},
        {"_id": 0},
    ).to_list(500)
    active_raw.sort(key=lambda t: (PRIORITY_RANK[t["priority"]], t["position"]))
    locked_idx = compute_locked_positions(active_raw)
    for i, t in enumerate(active_raw):
        t["locked"] = (i in locked_idx) or state["in_intervalo"] or (not state["has_entrada"]) or state["ended_day"]
        t["admin_resolved"] = False

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    resolved_raw = await db.tickets.find(
        {"assigned_collaborator_id": cid,
         "status": {"$in": list(ADMIN_RESOLVED) + list(TECH_RESOLVED)},
         "closed_at": {"$gte": cutoff}},
        {"_id": 0},
    ).to_list(200)
    resolved_raw.sort(key=lambda t: t.get("closed_at", ""), reverse=True)
    for t in resolved_raw:
        t["locked"] = True
        t["admin_resolved"] = t["status"] in ADMIN_RESOLVED

    active = next((t for t in active_raw if t["status"] in ("aberta", "aguardando_atendimento")), None)
    return {
        "tickets": active_raw + resolved_raw,
        "active_ticket_id": active["id"] if active else None,
        "clock_state": state,
        "lousa_unlocked": state["has_entrada"] and not state["in_intervalo"] and not state["ended_day"],
    }


@router.get("/lousa/all")
async def list_all_tickets(user: dict = Depends(require_role("gestor"))):
    """Painel gestor/admin: todas as bolhas do tenant."""
    q = tenant_filter(user)
    raw = await db.tickets.find(q, {"_id": 0}).to_list(2000)
    raw.sort(key=lambda t: (
        0 if t["status"] == "aguardando_atendimento" else 1,
        PRIORITY_RANK.get(t.get("priority", "normal"), 2),
        t.get("position", 0),
    ))
    return {"tickets": raw}


@router.get("/lousa/tickets/{ticket_id}")
async def get_ticket(ticket_id: str, user: dict = Depends(get_current_user)):
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    if user["role"] == "colaborador":
        cid = await _user_collaborator_id(user)
        if t["assigned_collaborator_id"] != cid:
            raise HTTPException(403, "Esta nota não é sua")
    return t


# -------------------------------------------------------------------------
# WRITE - Cadastro de bolhas (gestor)
# -------------------------------------------------------------------------
@router.post("/lousa/tickets")
async def create_ticket(payload: TicketIn, user: dict = Depends(require_role("gestor"))):
    coll = await db.collaborators.find_one(
        {"id": payload.assigned_collaborator_id}, {"_id": 0, "company_id": 1, "name": 1},
    )
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")

    # Geocode do endereço (best-effort) para futuras cercas dinâmicas
    lat, lng = None, None
    try:
        geo = await geocode_address(payload.address)
        lat, lng = geo.lat, geo.lng
    except Exception as e:
        logger.warning("[lousa] geocode falhou para '%s': %s", payload.address, e)

    # Próxima posição (no final da fila daquele técnico)
    last = await db.tickets.find(
        {"assigned_collaborator_id": payload.assigned_collaborator_id,
         "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]}},
        {"_id": 0, "position": 1},
    ).sort("position", -1).to_list(1)
    next_pos = (last[0]["position"] + 1) if last else 0

    doc = {
        "id": f"tkt-{uuid.uuid4().hex[:10]}",
        "client_id": str(uuid.uuid4()),
        "client_snapshot": {
            "name": payload.client_name,
            "address": payload.address,
            "neighborhood": payload.neighborhood,
            "phone": payload.phone,
            "latitude": lat, "longitude": lng,
            "relato": payload.relato,
            "test_history": [t.model_dump() for t in payload.test_history],
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
        "created_at": now_iso(),
    }
    await db.tickets.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/lousa/tickets/{ticket_id}")
async def delete_ticket(ticket_id: str, user: dict = Depends(require_role("gestor"))):
    res = await db.tickets.delete_one({"id": ticket_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Nota não encontrada")
    return {"ok": True}


# -------------------------------------------------------------------------
# Reorder (técnico)
# -------------------------------------------------------------------------
@router.post("/lousa/reorder")
async def reorder_tickets(payload: ReorderIn, user: dict = Depends(get_current_user)):
    if user["role"] != "colaborador":
        raise HTTPException(403, "Apenas colaboradores reordenam a própria lousa")
    cid = await _user_collaborator_id(user)
    raw = await db.tickets.find(
        {"assigned_collaborator_id": cid,
         "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]}},
        {"_id": 0},
    ).to_list(500)
    raw.sort(key=lambda t: (PRIORITY_RANK[t["priority"]], t["position"]))
    by_id = {t["id"]: t for t in raw}
    locked_ids = {raw[i]["id"] for i in compute_locked_positions(raw)}

    for item in payload.items:
        t = by_id.get(item.id)
        if not t:
            raise HTTPException(400, f"Ticket {item.id} inexistente")
        is_locked = t["priority"] != "normal" or t["id"] in locked_ids
        if is_locked and item.position != raw.index(t):
            raise HTTPException(400, f"Bolha travada não pode ser movida ({t['client_snapshot']['name']})")

    for item in payload.items:
        t = by_id[item.id]
        if t["priority"] == "normal" and item.id not in locked_ids:
            await db.tickets.update_one({"id": item.id}, {"$set": {"position": item.position}})
    return {"ok": True}


# -------------------------------------------------------------------------
# Public mobile endpoints (sem auth — usa collaborator_id no body, igual /clock-records)
# -------------------------------------------------------------------------
class PublicOpenIn(BaseModel):
    collaborator_id: str


class PublicFinalizeIn(BaseModel):
    collaborator_id: str
    completion_data: CompletionData
    latitude: float
    longitude: float
    outcome: Outcome = "sucesso"


@router.post("/lousa/public/tickets/{ticket_id}/open")
async def public_open_ticket(ticket_id: str, payload: PublicOpenIn):
    cid = payload.collaborator_id
    state = await _today_clock_state(cid)
    if not state["has_entrada"]:
        raise HTTPException(412, "Bata o ponto de Entrada antes de abrir uma nota")
    if state["in_intervalo"]:
        raise HTTPException(412, "Você está em intervalo — bata Fim intervalo antes")
    if state["ended_day"]:
        raise HTTPException(412, "Você já bateu a Saída do dia")

    other = await _has_active_ticket(cid)
    if other and other["id"] != ticket_id:
        raise HTTPException(409, f"Finalize a nota atual antes: {other['client_snapshot']['name']}")

    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t or t["assigned_collaborator_id"] != cid:
        raise HTTPException(404, "Nota não encontrada")
    if t["status"] not in ("pendente", "aberta"):
        raise HTTPException(400, "Nota não está disponível")

    msg = (
        f"Olá {t['client_snapshot']['name']}! Aqui é da equipe técnica. "
        f"Nosso técnico está a caminho do seu endereço. "
        f"Você está disponível agora? Responda SIM ou NÃO."
    )
    await db.whatsapp_log.insert_one({
        "id": str(uuid.uuid4()), "ticket_id": ticket_id,
        "phone": t["client_snapshot"].get("phone", ""),
        "message": msg, "sent_at": now_iso(), "mock": True,
    })
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {
            "status": "aberta", "opened_at": now_iso(),
            "whatsapp_status": "enviado", "whatsapp_last_message": msg,
        }},
    )
    return await db.tickets.find_one({"id": ticket_id}, {"_id": 0})


@router.post("/lousa/public/tickets/{ticket_id}/finalize")
async def public_finalize_ticket(ticket_id: str, payload: PublicFinalizeIn):
    cid = payload.collaborator_id
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t or t["assigned_collaborator_id"] != cid:
        raise HTTPException(404, "Nota não encontrada")
    if t["status"] != "aberta":
        raise HTTPException(400, "Somente notas abertas podem ser finalizadas")
    cd = payload.completion_data
    if t["type"] == "instalacao" and len(cd.fotos) < 3:
        raise HTTPException(400, "Instalação exige no mínimo 3 fotos")
    if t["type"] == "instalacao" and not cd.ont:
        raise HTTPException(400, "ONT é obrigatório para instalação")
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {
            "status": "finalizada", "outcome": payload.outcome,
            "closed_at": now_iso(), "closed_by": cid,
            "close_location": {"latitude": payload.latitude, "longitude": payload.longitude},
            "completion_data": cd.model_dump(),
        }},
    )
    return await db.tickets.find_one({"id": ticket_id}, {"_id": 0})


@router.post("/lousa/public/exit-resolve")
async def public_exit_resolve(payload: PublicOpenIn):
    """Versão pública: técnico confirma encerrar bolhas em aberto ao bater Saída."""
    cid = payload.collaborator_id
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0, "name": 1, "company_id": 1})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    open_tickets = await db.tickets.find(
        {"assigned_collaborator_id": cid,
         "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]}},
        {"_id": 0, "id": 1},
    ).to_list(500)
    if not open_tickets:
        return {"ok": True, "moved": 0}
    ids = [t["id"] for t in open_tickets]
    await db.tickets.update_many(
        {"id": {"$in": ids}},
        {"$set": {"status": "aguardando_atendimento", "closed_at": now_iso(),
                  "admin_action": "saida_com_pendencia",
                  "admin_notes": "Encerradas pelo colaborador ao bater Saída"}},
    )
    await _create_notification(
        type_="ticket_unfinished_on_exit",
        title=f"⚠️ Saída com {len(ids)} nota(s) em aberto",
        message=f"{coll.get('name', 'Técnico')} bateu Saída deixando {len(ids)} nota(s) sem finalizar.",
        collaborator_id=cid, ticket_id=None,
        company_id=coll.get("company_id") or DEMO_COMPANY_ID,
        severity="critical",
    )
    return {"ok": True, "moved": len(ids), "ticket_ids": ids}


# -------------------------------------------------------------------------
# OPEN ticket (técnico) — REGRAS
# -------------------------------------------------------------------------
@router.post("/lousa/tickets/{ticket_id}/open")
async def open_ticket(ticket_id: str, user: dict = Depends(get_current_user)):
    if user["role"] != "colaborador":
        raise HTTPException(403, "Apenas colaboradores abrem bolhas")
    cid = await _user_collaborator_id(user)

    # 1. Estado do ponto
    state = await _today_clock_state(cid)
    if not state["has_entrada"]:
        raise HTTPException(412, "Bata o ponto de Entrada antes de abrir uma nota")
    if state["in_intervalo"]:
        raise HTTPException(412, "Você está em intervalo de almoço — bata Fim intervalo antes")
    if state["ended_day"]:
        raise HTTPException(412, "Você já bateu a Saída do dia — não é possível abrir nova nota")

    # 2. Já tem outra aberta?
    other = await _has_active_ticket(cid)
    if other and other["id"] != ticket_id:
        raise HTTPException(409, f"Finalize a nota atual antes de abrir outra: {other['client_snapshot']['name']}")

    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    if t["assigned_collaborator_id"] != cid:
        raise HTTPException(403, "Nota não é sua")
    if t["status"] not in ("pendente", "aberta"):
        raise HTTPException(400, "Nota não está disponível")

    # 3. WhatsApp mock (mantido do smart1)
    msg = (
        f"Olá {t['client_snapshot']['name']}! Aqui é da equipe técnica. "
        f"Nosso técnico está a caminho do seu endereço. "
        f"Você está disponível agora? Responda SIM ou NÃO."
    )
    await db.whatsapp_log.insert_one({
        "id": str(uuid.uuid4()), "ticket_id": ticket_id,
        "phone": t["client_snapshot"].get("phone", ""),
        "message": msg, "sent_at": now_iso(), "mock": True,
    })

    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {
            "status": "aberta",
            "opened_at": now_iso(),
            "whatsapp_status": "enviado",
            "whatsapp_last_message": msg,
        }},
    )
    return await db.tickets.find_one({"id": ticket_id}, {"_id": 0})


@router.post("/lousa/tickets/{ticket_id}/finalize")
async def finalize_ticket(ticket_id: str, payload: FinalizeIn, user: dict = Depends(get_current_user)):
    if user["role"] != "colaborador":
        raise HTTPException(403, "Apenas colaboradores finalizam suas notas")
    cid = await _user_collaborator_id(user)
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t or t["assigned_collaborator_id"] != cid:
        raise HTTPException(404, "Nota não encontrada")
    if t["status"] != "aberta":
        raise HTTPException(400, "Somente notas abertas podem ser finalizadas")

    cd = payload.completion_data
    if t["type"] == "instalacao" and len(cd.fotos) < 3:
        raise HTTPException(400, "Instalação exige no mínimo 3 fotos")
    if t["type"] == "instalacao" and not cd.ont:
        raise HTTPException(400, "ONT é obrigatório para instalação")

    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {
            "status": "finalizada",
            "outcome": payload.outcome,
            "closed_at": now_iso(),
            "closed_by": user["id"],
            "close_location": {"latitude": payload.latitude, "longitude": payload.longitude},
            "completion_data": cd.model_dump(),
        }},
    )
    return await db.tickets.find_one({"id": ticket_id}, {"_id": 0})


@router.post("/lousa/tickets/{ticket_id}/notify-backoffice")
async def notify_backoffice(ticket_id: str, user: dict = Depends(get_current_user)):
    """Técnico solicita ajuda do gestor (cliente não confirma WhatsApp)."""
    if user["role"] != "colaborador":
        raise HTTPException(403, "Apenas colaboradores acionam o gestor")
    cid = await _user_collaborator_id(user)
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t or t["assigned_collaborator_id"] != cid:
        raise HTTPException(404, "Nota não encontrada")
    if t["status"] != "aberta":
        raise HTTPException(400, "Nota precisa estar aberta")
    await db.tickets.update_one({"id": ticket_id}, {"$set": {"status": "aguardando_atendimento"}})
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0, "name": 1, "company_id": 1})
    await _create_notification(
        type_="ticket_needs_backoffice",
        title="Cliente não confirmou — aguardando gestor",
        message=f"{coll.get('name', 'Técnico')} solicitou ajuda na nota '{t['client_snapshot']['name']}'.",
        collaborator_id=cid, ticket_id=ticket_id,
        company_id=(coll or {}).get("company_id") or DEMO_COMPANY_ID,
        severity="warning",
    )
    return {"ok": True}


# -------------------------------------------------------------------------
# Backoffice / Gestor — encerrar / reagendar / cancelar
# -------------------------------------------------------------------------
@router.post("/lousa/tickets/{ticket_id}/admin-close")
async def admin_close_ticket(ticket_id: str, payload: AdminCloseIn,
                             user: dict = Depends(require_role("gestor"))):
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    if t["status"] in ("finalizada", "encerrada", "cancelada"):
        raise HTTPException(400, "Nota já encerrada")
    status_map = {"encerrar": "encerrada", "reagendar": "reagendada", "cancelar": "cancelada"}
    update = {
        "status": status_map[payload.action],
        "outcome": "informada",
        "closed_at": now_iso(),
        "closed_by": user["id"],
        "admin_action": payload.action,
        "admin_notes": payload.notes,
    }
    if payload.action == "reagendar" and payload.new_scheduled_time:
        update["scheduled_time"] = payload.new_scheduled_time
    await db.tickets.update_one({"id": ticket_id}, {"$set": update})
    return await db.tickets.find_one({"id": ticket_id}, {"_id": 0})


# -------------------------------------------------------------------------
# Force-close ALL open tickets at exit (chamado pelo fluxo de Saída)
# -------------------------------------------------------------------------
@router.post("/lousa/exit-resolve")
async def exit_resolve_open_tickets(user: dict = Depends(get_current_user)):
    """Chamado quando técnico confirma 'Sim, encerrar bolhas em aberto' ao bater Saída.
    - Marca todas as bolhas ativas (pendente/aberta/aguardando_atendimento) como 'aguardando_atendimento'
    - Cria notificação para gestor
    """
    if user["role"] != "colaborador":
        raise HTTPException(403, "Apenas colaboradores")
    cid = await _user_collaborator_id(user)
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0, "name": 1, "company_id": 1})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")

    open_tickets = await db.tickets.find(
        {"assigned_collaborator_id": cid,
         "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]}},
        {"_id": 0},
    ).to_list(500)
    if not open_tickets:
        return {"ok": True, "moved": 0}

    ids = [t["id"] for t in open_tickets]
    await db.tickets.update_many(
        {"id": {"$in": ids}},
        {"$set": {"status": "aguardando_atendimento", "closed_at": now_iso(),
                  "admin_action": "saida_com_pendencia", "admin_notes": "Encerradas pelo colaborador ao bater Saída"}},
    )
    await _create_notification(
        type_="ticket_unfinished_on_exit",
        title=f"⚠️ Saída com {len(ids)} nota(s) em aberto",
        message=f"{coll.get('name', 'Técnico')} bateu o ponto de Saída deixando {len(ids)} nota(s) sem finalizar. Verifique o painel.",
        collaborator_id=cid, ticket_id=None,
        company_id=coll.get("company_id") or DEMO_COMPANY_ID,
        severity="critical",
    )
    return {"ok": True, "moved": len(ids), "ticket_ids": ids}


# -------------------------------------------------------------------------
# Notifications
# -------------------------------------------------------------------------
@router.get("/notifications")
async def list_notifications(user: dict = Depends(require_role("gestor")),
                             unread_only: bool = False):
    q = tenant_filter(user)
    if unread_only:
        q["read_by"] = {"$nin": [user["id"]]}
    items = await db.notifications.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    unread = sum(1 for n in items if user["id"] not in (n.get("read_by") or []))
    return {"items": items, "unread_count": unread}


@router.post("/notifications/{nid}/read")
async def mark_notification_read(nid: str, user: dict = Depends(require_role("gestor"))):
    await db.notifications.update_one({"id": nid}, {"$addToSet": {"read_by": user["id"]}})
    return {"ok": True}


@router.post("/notifications/read-all")
async def mark_all_read(user: dict = Depends(require_role("gestor"))):
    q = tenant_filter(user)
    await db.notifications.update_many(q, {"$addToSet": {"read_by": user["id"]}})
    return {"ok": True}
