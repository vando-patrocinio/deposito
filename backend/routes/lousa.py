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

import json
import logging
import re
import uuid

import httpx
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core import (
    DEMO_COMPANY_ID,
    effective_company_id,
    geocode_address,
    get_current_user,
    llm_chat,
    now_iso,
    require_role,
    tenant_filter,
    today_str,
)
from database import db
from routes.lousa_score import compute_duration_minutes, heuristic_score_for_ticket

logger = logging.getLogger("ponto")
router = APIRouter(prefix="/api", tags=["lousa"])


# -------------------------------------------------------------------------
# Models
# -------------------------------------------------------------------------
Priority = Literal["normal", "horario", "prioridade", "urgente"]
TicketType = Literal["reparo", "instalacao", "retirada", "prioridade", "preventiva", "venda"]
TicketStatus = Literal[
    "pendente", "aberta", "aguardando_atendimento",
    "finalizada", "encerrada", "reagendada", "cancelada"
]
Outcome = Literal["sucesso", "informada"]

POINTS_BY_TYPE: Dict[str, float] = {
    "instalacao": 3.0, "retirada": 1.5, "reparo": 1.0,
    "prioridade": 2.5, "preventiva": 1.5, "venda": 2.0,
}
PRIORITY_RANK = {"urgente": -1, "prioridade": 0, "horario": 1, "normal": 2}
ADMIN_RESOLVED = ("encerrada", "reagendada", "cancelada")
TECH_RESOLVED = ("finalizada",)

# -------------------------------------------------------------------------
# REGRA: Bolha da Lousa só aparece no dia que corresponde à sua data.
# Cada ticket tem um "dia do calendário" (BR, UTC-3) calculado a partir de
# `scheduled_time` (prioridade), `opened_at` ou `created_at`. Quando o
# técnico reagenda, atualizamos `scheduled_time` para o novo dia — assim
# o ticket some da Lousa de hoje e aparece na Lousa do novo dia.
# -------------------------------------------------------------------------
def _today_br_iso() -> str:
    """Hoje em UTC-3 (horário de Brasília), formato YYYY-MM-DD."""
    return (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%d")


def _ticket_day_iso(ticket: dict) -> str:
    """Dia do calendário (BR) do ticket, no formato YYYY-MM-DD.

    Prioridade dos campos:
      1. scheduled_time (data de serviço efetiva — usada no reagendamento)
      2. opened_at (quando começou)
      3. created_at (quando foi criada)
    Retorna string vazia se nenhum disponível ou inválido.
    """
    raw = (ticket.get("scheduled_time") or ticket.get("opened_at")
           or ticket.get("created_at"))
    if not raw:
        return ""
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return (d - timedelta(hours=3)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return ""


async def _send_boss_mode_whatsapp(ticket: dict, collaborator: dict) -> None:
    """Modo Boss: ao criar nota URGENTE, dispara mensagem proativa pro cliente.

    Best-effort: se Baileys não estiver disponível ou cliente não tiver telefone
    válido, apenas loga e segue (não falha o create do ticket).
    """
    snapshot = ticket.get("client_snapshot") or {}
    phone_raw = (snapshot.get("phone") or "").strip()
    if not phone_raw:
        logger.info("[lousa.boss] sem telefone do cliente — skip")
        return
    # Normaliza telefone BR: só dígitos, prefixo 55 se faltar
    digits = "".join(c for c in phone_raw if c.isdigit())
    if not digits:
        return
    if not digits.startswith("55"):
        digits = "55" + digits
    jid = f"{digits}@s.whatsapp.net"
    nome = (snapshot.get("name") or "").split(" ")[0] or "Cliente"
    tech = collaborator.get("name") or "nosso técnico"
    msg = (
        f"Olá *{nome}*! 🚨\n"
        f"Sua solicitação foi marcada como *URGENTE* e já está em andamento.\n\n"
        f"O técnico *{tech}* foi alocado e está priorizando seu atendimento. "
        "Em breve entraremos em contato com mais detalhes."
    )
    try:
        # Chama endpoint interno Baileys
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.post(
                "http://localhost:3002/send",
                json={"to": jid, "text": msg},
            )
            ok = r.status_code in (200, 201)
            logger.info("[lousa.boss] WhatsApp boss-mode sent=%s status=%s",
                          ok, r.status_code)
            # Persiste em aihub_wa_messages pra aparecer no chat
            await db.aihub_wa_messages.insert_one({
                "id": str(uuid.uuid4()),
                "company_id": ticket.get("company_id") or DEMO_COMPANY_ID,
                "phone": digits, "direction": "outbound",
                "text": msg, "channel": "baileys",
                "context": "boss_mode_urgent_ticket",
                "ticket_id": ticket["id"],
                "delivery_status": "sent" if ok else "failed",
                "created_at": now_iso(),
            })
    except Exception as e:
        logger.exception("[lousa.boss] erro enviando whatsapp: %s", e)




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
    pppoe_user: Optional[str] = None
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
    # Vínculo cliente ↔ CTO/porta (instalação)
    cto_id: Optional[str] = None
    cto_name: Optional[str] = None
    cto_port_number: Optional[int] = None
    # Fibra adicional (já existia mas faltava no model)
    fibra_06fo: float = 0
    fibra_12fo: float = 0
    fibra_24fo: float = 0


class TicketIn(BaseModel):
    """Cadastro de uma nova bolha (nota de serviço) — apenas gestor/admin."""
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


class PublicReorderIn(BaseModel):
    collaborator_id: str
    items: List[ReorderItem]


class AdminCloseIn(BaseModel):
    action: Literal["encerrar", "reagendar", "cancelar"]
    notes: Optional[str] = None
    new_scheduled_time: Optional[str] = None
    new_date: Optional[str] = None        # YYYY-MM-DD (alternativa a new_scheduled_time)
    new_time: Optional[str] = None        # HH:MM (combinada com new_date)
    # Modo "fechamento técnico" — gestor preenche dados como se fosse o técnico.
    # Quando preenchido em action=encerrar, gravamos em completion_data e
    # disparamos os hooks (signal snapshot, auto-resched, etc).
    completion_data: Optional[Dict[str, Any]] = None


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
    # Push real-time via SSE para gestores conectados (best-effort)
    try:
        from routes.events import publish_event
        await publish_event(company_id, "notification", n)
    except Exception as e:
        logger.warning("[lousa] SSE publish falhou: %s", e)
    return n


async def _log_ticket_action(
    *, ticket_id: str, action: str, actor_id: str, actor_name: str,
    actor_role: str, details: Optional[str] = None, company_id: str,
) -> None:
    """Registra ação no log de auditoria da bolha."""
    log = {
        "id": f"tlg-{uuid.uuid4().hex[:10]}",
        "ticket_id": ticket_id,
        "action": action,           # criada | aberta | finalizada | encerrada | reagendada | cancelada | transferida | aguardando_gestor
        "actor_id": actor_id,
        "actor_name": actor_name,
        "actor_role": actor_role,   # colaborador | gestor | administrador | sistema
        "details": details,
        "company_id": company_id,
        "at": now_iso(),
    }
    await db.ticket_logs.insert_one(log)


async def _sla_minutes_for_type(ttype: str, company_id: str) -> int:
    """Pega o tempo de referência (SLA) para um tipo de serviço."""
    s = await db.settings.find_one({"id": company_id}, {"_id": 0})
    if not s:
        s = {}
    defaults = {
        "reparo": 60, "instalacao": 120, "retirada": 30,
        "prioridade": 45, "preventiva": 90, "venda": 60,
    }
    key = f"sla_{ttype}_minutes"
    return int(s.get(key, defaults.get(ttype, 60)))


def _compute_sla(ticket: dict, sla_minutes: int, yellow_minutes: int = 15,
                 red_after_minutes: int = 0, pending_grace_minutes: int = 60) -> dict:
    """Retorna info SLA usando minutos absolutos:
    - 🟢 ok: dentro do tempo, sem alerta
    - 🟡 warning: faltam <= yellow_minutes para estourar
    - 🔴 overdue: passou (sla_minutes + red_after_minutes)

    Reference time chosen by ticket state:
    - status == "aberta" + opened_at  → relógio de execução (tempo desde o técnico iniciar)
    - pendente/aguardando + scheduled_time → atraso de agenda (deadline = scheduled_time + sla_minutes)
    - sem scheduled_time + created_at → fila parada (deadline = created_at + pending_grace_minutes + sla_minutes)
    Status finalizado/cancelado/encerrado/reagendado retorna n/a.
    """
    status_raw = ticket.get("status")
    if status_raw in ("finalizada", "cancelada", "encerrada", "reagendada"):
        return {"sla_minutes": sla_minutes, "elapsed_minutes": None, "remaining_minutes": None,
                "pct": None, "status": "n/a"}

    # Pick reference timestamp + effective deadline
    ref_iso = None
    deadline_minutes = sla_minutes
    mode = None
    if status_raw == "aberta" and ticket.get("opened_at"):
        ref_iso = ticket["opened_at"]
        mode = "execution"
    elif ticket.get("scheduled_time"):
        ref_iso = ticket["scheduled_time"]
        mode = "schedule"
    elif ticket.get("created_at"):
        ref_iso = ticket["created_at"]
        deadline_minutes = sla_minutes + pending_grace_minutes
        mode = "queue"
    if not ref_iso:
        return {"sla_minutes": sla_minutes, "elapsed_minutes": None, "remaining_minutes": None,
                "pct": None, "status": "n/a"}

    try:
        ref = datetime.fromisoformat(str(ref_iso).replace("Z", "+00:00"))
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        elapsed_min = round((datetime.now(timezone.utc) - ref).total_seconds() / 60, 1)
        # `scheduled_time` no futuro → ainda não começou a correr
        if elapsed_min < 0:
            return {"sla_minutes": sla_minutes, "elapsed_minutes": elapsed_min,
                    "remaining_minutes": round(deadline_minutes - elapsed_min, 1),
                    "pct": 0.0, "status": "ok", "mode": mode}
        remaining = round(deadline_minutes - elapsed_min, 1)
        pct = (elapsed_min / deadline_minutes) * 100 if deadline_minutes > 0 else 0
        red_threshold = deadline_minutes + red_after_minutes
        if elapsed_min >= red_threshold:
            status = "overdue"
        elif remaining <= yellow_minutes:
            status = "warning"
        else:
            status = "ok"
        return {"sla_minutes": sla_minutes, "elapsed_minutes": elapsed_min,
                "remaining_minutes": remaining, "pct": round(pct, 1),
                "status": status, "mode": mode}
    except Exception:
        return {"sla_minutes": sla_minutes, "elapsed_minutes": None, "remaining_minutes": None,
                "pct": None, "status": "n/a"}


def _time_slot_for(ticket: dict) -> str:
    """Retorna slot de horário da bolha (Manhã/Tarde/Noite/Sem horário)."""
    sched = ticket.get("scheduled_time")
    if sched:
        try:
            hour = int(sched[11:13])
            if hour < 12:
                return f"manha_{hour:02d}"   # ordenável: manha_08, manha_09...
            if hour < 18:
                return f"tarde_{hour:02d}"
            return f"noite_{hour:02d}"
        except Exception:
            pass
    return "sem_horario"


# -------------------------------------------------------------------------
# READ - Lousa do colaborador / Lista para gestor
# -------------------------------------------------------------------------
class TransferIn(BaseModel):
    new_collaborator_id: Optional[str] = None
    new_position: Optional[int] = None
    new_grid_slot: Optional[str] = None  # "08:00", "09:00" ou "sem_horario"


@router.post("/lousa/tickets/{ticket_id}/transfer")
async def transfer_ticket(ticket_id: str, payload: TransferIn,
                          user: dict = Depends(require_role("gestor"))):
    """Gestor transfere bolha de um técnico para outro OU muda slot dentro da mesma coluna."""
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    if t["status"] in ("finalizada", "encerrada", "cancelada"):
        raise HTTPException(400, "Nota já encerrada — não pode ser transferida")
    if t["status"] == "aberta":
        raise HTTPException(409, "Serviço em execução pelo técnico — não pode ser movido. Aguarde a finalização ou encerre antes.")

    update = {}
    target_cid = payload.new_collaborator_id or t["assigned_collaborator_id"]

    # Mudou de técnico: transfer entre colunas
    if payload.new_collaborator_id and payload.new_collaborator_id != t["assigned_collaborator_id"]:
        new_coll = await db.collaborators.find_one(
            {"id": payload.new_collaborator_id}, {"_id": 0, "id": 1, "name": 1},
        )
        if not new_coll:
            raise HTTPException(404, "Técnico destino não encontrado")
        if payload.new_position is None:
            last = await db.tickets.find(
                {"assigned_collaborator_id": payload.new_collaborator_id,
                 "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]}},
                {"_id": 0, "position": 1},
            ).sort("position", -1).to_list(1)
            update["position"] = (last[0]["position"] + 1) if last else 0
        else:
            update["position"] = payload.new_position
        update["assigned_collaborator_id"] = payload.new_collaborator_id
        if t["status"] == "aberta":
            update["status"] = "pendente"
            update["opened_at"] = None

    # Mudança de slot (mesmo técnico ou novo)
    if payload.new_grid_slot is not None:
        # Valida capacidade (max_per_slot)
        company_id = user.get("company_id") or DEMO_COMPANY_ID
        settings = await db.settings.find_one({"id": company_id}, {"_id": 0}) or {}
        max_per_slot = int(settings.get("lousa_grid_max_per_slot", 2))
        if payload.new_grid_slot != "sem_horario":
            occupied = await db.tickets.count_documents({
                "assigned_collaborator_id": target_cid,
                "grid_slot": payload.new_grid_slot,
                "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]},
                "id": {"$ne": ticket_id},
            })
            if occupied >= max_per_slot:
                raise HTTPException(
                    409,
                    f"Slot {payload.new_grid_slot} cheio ({occupied}/{max_per_slot}). "
                    f"Aumente o limite em Configurações ou escolha outro horário.",
                )
        update["grid_slot"] = payload.new_grid_slot

    if not update:
        return t

    await db.tickets.update_one({"id": ticket_id}, {"$set": update})
    await _log_ticket_action(
        ticket_id=ticket_id, action="transferida",
        actor_id=user["id"], actor_name=user.get("name", "Gestor"),
        actor_role=user.get("role", "gestor"),
        details=(
            (f"De: {t.get('assigned_collaborator_id')} → Para: {update.get('assigned_collaborator_id', target_cid)}"
             if "assigned_collaborator_id" in update else "Mesmo técnico") +
            (f" · Slot: {payload.new_grid_slot}" if payload.new_grid_slot else "")
        ),
        company_id=t.get("company_id") or DEMO_COMPANY_ID,
    )
    return await db.tickets.find_one({"id": ticket_id}, {"_id": 0})


# -------------------------------------------------------------------------
# LOGS de auditoria (todas as ações nas bolhas)
# -------------------------------------------------------------------------
@router.get("/lousa/logs")
async def list_ticket_logs(
    user: dict = Depends(require_role("gestor")),
    ticket_id: Optional[str] = None,
    limit: int = 100,
):
    """Lista logs de ações nas bolhas (todas ou de uma bolha específica)."""
    q = tenant_filter(user)
    if ticket_id:
        q["ticket_id"] = ticket_id
    items = await db.ticket_logs.find(q, {"_id": 0}).sort("at", -1).to_list(limit)
    return {"items": items}


@router.get("/lousa/grid")
async def lousa_grid(
    user: dict = Depends(require_role("gestor")),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Retorna lousa em formato GRADE.
    Sem parâmetros: bolhas ATIVAS agora (default).
    Com date_from/date_to (YYYY-MM-DD): histórico — bolhas que estavam abertas/criadas/encerradas
    em qualquer momento dentro do intervalo. View read-only para o frontend.
    """
    q = tenant_filter(user)
    # Cargo filter: apenas funções de campo aparecem na Lousa.
    # Colaboradores legados sem `cargo` (None/"") continuam visíveis pra
    # compatibilidade — o admin pode rodar a migration depois.
    from cargo import LOUSA_CARGOS
    q["$or"] = [
        {"cargo": {"$in": list(LOUSA_CARGOS)}},
        {"cargo": {"$exists": False}},
        {"cargo": None},
        {"cargo": ""},
    ]
    collabs = await db.collaborators.find(q, {"_id": 0}).to_list(500)
    collabs.sort(key=lambda c: c.get("name", ""))

    cids = [c["id"] for c in collabs]
    is_historical = bool(date_from or date_to)

    # Regra de negócio: a grade de uma data só pode conter bolhas cuja data
    # de calendário (scheduled_time > opened_at > created_at) bata com a data
    # selecionada. Helper `_ticket_day_iso` é o mesmo usado pela Lousa Mobile.
    selected_date = (date_from or _today_br_iso())

    def _matches_selected_date(t: dict) -> bool:
        return _ticket_day_iso(t) == selected_date

    if is_historical:
        # Período: usa today se não fornecido
        df = date_from or today_str()
        dt = date_to or df
        from_iso = f"{df}T00:00:00"
        from datetime import timedelta as _td
        next_d = (datetime.fromisoformat(dt) + _td(days=1)).strftime("%Y-%m-%d")
        to_iso = f"{next_d}T00:00:00"

        # Tickets que TOCARAM o período: criado dentro OU encerrado dentro OU
        # aberto antes E (ainda aberto OU encerrado depois). Em seguida aplicamos
        # o filtro de scheduled_time para honrar a regra "bolha = data agendada".
        all_active = []
        raw_resolved = await db.tickets.find(
            {"assigned_collaborator_id": {"$in": cids},
             "$or": [
                 {"created_at": {"$gte": from_iso, "$lt": to_iso}},
                 {"closed_at": {"$gte": from_iso, "$lt": to_iso}},
                 # ainda aberta E criada antes do fim do período
                 {"closed_at": None, "created_at": {"$lt": to_iso}},
             ]},
            {"_id": 0},
        ).to_list(5000)
        all_resolved = [t for t in raw_resolved if _matches_selected_date(t)]
    else:
        active_states = ["pendente", "aberta", "aguardando_atendimento"]
        raw_active = await db.tickets.find(
            {"assigned_collaborator_id": {"$in": cids}, "status": {"$in": active_states}},
            {"_id": 0},
        ).to_list(2000)
        all_active = [t for t in raw_active if _matches_selected_date(t)]
        # Inclui também os últimos 24h finalizados/encerrados — para gap entre serviços e duração
        cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        raw_resolved = await db.tickets.find(
            {"assigned_collaborator_id": {"$in": cids},
             "status": {"$in": ["finalizada", "encerrada", "cancelada", "reagendada"]},
             "closed_at": {"$gte": cutoff_24h}},
            {"_id": 0},
        ).to_list(1000)
        all_resolved = [t for t in raw_resolved if _matches_selected_date(t)]

    # Settings da empresa para SLA + grade fixa
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    settings = await db.settings.find_one({"id": company_id}, {"_id": 0}) or {}
    sla_map = {
        "reparo": int(settings.get("sla_reparo_minutes", 60)),
        "instalacao": int(settings.get("sla_instalacao_minutes", 120)),
        "retirada": int(settings.get("sla_retirada_minutes", 30)),
        "prioridade": int(settings.get("sla_prioridade_minutes", 45)),
        "preventiva": int(settings.get("sla_preventiva_minutes", 90)),
        "venda": int(settings.get("sla_venda_minutes", 60)),
    }
    warning_pct = int(settings.get("sla_warning_pct", 80))
    yellow_min = int(settings.get("sla_yellow_minutes", 15))
    red_after_min = int(settings.get("sla_red_after_minutes", 0))
    pending_grace_min = int(settings.get("sla_pending_grace_minutes", 60))
    blink = bool(settings.get("sla_blink_when_overdue", True))
    grid_start = int(settings.get("lousa_grid_start_hour", 8))
    grid_end = int(settings.get("lousa_grid_end_hour", 18))
    slot_minutes = int(settings.get("lousa_grid_slot_minutes", 60))
    max_per_slot = int(settings.get("lousa_grid_max_per_slot", 2))
    fixed_slots = _build_fixed_slots(grid_start, grid_end, slot_minutes)

    # Estado do dia de cada colaborador
    today = today_str()
    records = await db.clock_records.find(
        {"collaborator_id": {"$in": cids}, "date": today,
         "status": {"$in": ["Válido", "Offline sincronizado"]}},
        {"_id": 0, "collaborator_id": 1, "type": 1, "time": 1, "created_at": 1},
    ).to_list(5000)
    state_by_cid: dict = {}
    for r in records:
        s = state_by_cid.setdefault(r["collaborator_id"], {"types": set(), "records": [], "last_record_at": None})
        s["types"].add(r["type"])
        s["records"].append({"type": r["type"], "time": r["time"]})
        ca = r.get("created_at")
        if ca and (s["last_record_at"] is None or ca > s["last_record_at"]):
            s["last_record_at"] = ca

    online_threshold_min = int(settings.get("online_threshold_minutes", 5))
    online_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=online_threshold_min)).isoformat()

    columns = []
    for c in collabs:
        cid = c["id"]
        if is_historical:
            # No modo histórico, todos os tickets do período viram o tickets principal (read-only)
            tickets = sorted(
                [t for t in all_resolved if t["assigned_collaborator_id"] == cid],
                key=lambda t: (PRIORITY_RANK.get(t.get("priority"), 99), t.get("position", 0)),
            )
            recent_resolved = []
        else:
            tickets = sorted(
                [t for t in all_active if t["assigned_collaborator_id"] == cid],
                key=lambda t: (PRIORITY_RANK[t["priority"]], t["position"]),
            )
            recent_resolved = sorted(
                [t for t in all_resolved if t["assigned_collaborator_id"] == cid],
                key=lambda t: t.get("closed_at", ""),
            )
        locked_idx = compute_locked_positions(tickets)
        s = state_by_cid.get(cid, {"types": set(), "records": [], "last_record_at": None})
        in_intervalo = ("Início intervalo" in s["types"]) and ("Fim intervalo" not in s["types"])
        has_entrada = "Entrada" in s["types"]
        ended_day = "Saída" in s["types"]
        # Indicador online: técnico bateu Entrada e tem record recente (≤ threshold) e não bateu Saída
        last_record_at = s.get("last_record_at")
        is_online = bool(has_entrada and not ended_day and last_record_at and last_record_at >= online_cutoff)
        # Adiciona SLA + slot + duração + gap + ai_score por bolha
        # Inicializa gap_minutes_to_prev=None em todos para conformidade com a spec
        for t in tickets:
            t["gap_minutes_to_prev"] = None
        # Gaps: ordem cronológica dos resolvidos depois pelas ativas (por opened_at)
        chrono_for_gaps = list(recent_resolved) + sorted(
            [t for t in tickets if t.get("opened_at")],
            key=lambda t: t.get("opened_at") or "",
        )
        prev_close_iso: Optional[str] = None
        for t in chrono_for_gaps:
            opened_iso = t.get("opened_at")
            if prev_close_iso and opened_iso:
                try:
                    pc = datetime.fromisoformat(prev_close_iso.replace("Z", "+00:00"))
                    op = datetime.fromisoformat(opened_iso.replace("Z", "+00:00"))
                    if pc.tzinfo is None:
                        pc = pc.replace(tzinfo=timezone.utc)
                    if op.tzinfo is None:
                        op = op.replace(tzinfo=timezone.utc)
                    t["gap_minutes_to_prev"] = max(0, round((op - pc).total_seconds() / 60.0, 1))
                except Exception:
                    t["gap_minutes_to_prev"] = None
            else:
                t["gap_minutes_to_prev"] = None
            if t.get("closed_at"):
                prev_close_iso = t["closed_at"]

        for i, t in enumerate(tickets):
            if is_historical:
                t["locked"] = True
                t["historical"] = True
            else:
                t["locked"] = (i in locked_idx) or in_intervalo or (not has_entrada) or ended_day
            t["in_execution"] = t.get("status") == "aberta"
            sla_min = sla_map.get(t.get("type", "reparo"), 60)
            t["sla"] = _compute_sla(t, sla_min, yellow_min, red_after_min, pending_grace_min)
            t["grid_slot"] = _slot_for_ticket(t, fixed_slots, slot_minutes)
            t["duration_minutes"] = compute_duration_minutes(t)
            t["ai_score"] = await heuristic_score_for_ticket(t, sla_minutes=sla_min)
        for t in recent_resolved:
            t["duration_minutes"] = compute_duration_minutes(t)
        # Monta slots fixos com bolhas de cada slot (sempre exibe TODOS slots)
        slots_data = []
        for slot_label in fixed_slots:
            in_slot = [t for t in tickets if t["grid_slot"] == slot_label]
            slots_data.append({"slot": slot_label, "tickets": in_slot, "full": len(in_slot) >= max_per_slot})
        unscheduled = [t for t in tickets if t["grid_slot"] == "sem_horario"]
        columns.append({
            "collaborator": {
                "id": cid, "name": c.get("name", ""),
                "avatar": c.get("avatar_data_url"),
                "is_test_mode": c.get("is_test_mode", False),
                "praca_id": c.get("praca_id"),
                "praca": c.get("praca_name") or c.get("city") or "",
            },
            "clock_state": {
                "has_entrada": has_entrada, "in_intervalo": in_intervalo,
                "ended_day": ended_day,
                "is_online": is_online,
                "last_record_at": last_record_at,
                "online_threshold_minutes": online_threshold_min,
                "records": sorted(s["records"], key=lambda r: r["time"]),
            },
            "tickets": tickets,
            "recent_resolved": recent_resolved,
            "slots": slots_data,
            "unscheduled": unscheduled,
        })
    # Enriquece TODAS as bolhas com sinal SmartOLT (cache local, 1 query batch)
    try:
        from routes.smartolt import enrich_tickets_with_live_signal
        all_t: list[dict] = []
        for col in columns:
            all_t.extend(col.get("unscheduled") or [])
            for s in col.get("slots") or []:
                all_t.extend(s.get("tickets") or [])
        company_id = (user.get("company_id") or DEMO_COMPANY_ID)
        await enrich_tickets_with_live_signal(all_t, company_id)
    except Exception as _e:
        logger.warning("[lousa] enrich live_signal falhou: %s", _e)

    # Ordena colunas: técnicos com MAIS bolhas (ativas) à esquerda → menos à direita.
    # Tiebreaker: nome alfabético para resultado estável.
    def _bubble_count(col: dict) -> int:
        n = len(col.get("unscheduled") or [])
        for s in col.get("slots") or []:
            n += len(s.get("tickets") or [])
        return n
    columns.sort(key=lambda c: (-_bubble_count(c), (c.get("collaborator") or {}).get("name", "")))
    return {
        "columns": columns,
        "historical": is_historical,
        "date_from": date_from if is_historical else None,
        "date_to": date_to if is_historical else None,
        "sla_blink_when_overdue": blink,
        "sla_warning_pct": warning_pct,
        "sla_yellow_minutes": yellow_min,
        "sla_red_after_minutes": red_after_min,
        "sla_map": sla_map,
        "grid": {
            "start_hour": grid_start, "end_hour": grid_end,
            "slot_minutes": slot_minutes, "max_per_slot": max_per_slot,
            "slots": fixed_slots,
        },
    }


def _build_fixed_slots(start_hour: int, end_hour: int, slot_minutes: int) -> list[str]:
    """Retorna lista de labels de slots fixos: ['08:00', '09:00', ...]"""
    slots = []
    total_min = (end_hour - start_hour) * 60
    n = max(1, total_min // max(1, slot_minutes))
    for i in range(n):
        m = start_hour * 60 + i * slot_minutes
        slots.append(f"{m // 60:02d}:{m % 60:02d}")
    return slots


def _slot_for_ticket(t: dict, slots: list[str], slot_minutes: int) -> str:
    """Determina em qual slot fixo a bolha cai. Prioridade:
    1. grid_slot já atribuído manualmente
    2. scheduled_time arredondado p/ baixo no slot mais próximo
    3. 'sem_horario' (cai num slot virtual)
    """
    if t.get("grid_slot") and t["grid_slot"] in slots:
        return t["grid_slot"]
    sched = t.get("scheduled_time")
    if sched:
        try:
            hour = int(sched[11:13])
            minute = int(sched[14:16])
            total = hour * 60 + minute
            # Encontra slot que contém esse horário
            for s in slots:
                sh, sm = int(s[:2]), int(s[3:5])
                slot_start = sh * 60 + sm
                if slot_start <= total < slot_start + slot_minutes:
                    return s
        except Exception:
            pass
    return "sem_horario"


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
async def get_lousa_by_collaborator(cid: str, admin_test: int = 0,
                                       request: Request = None):
    """Lousa pública por collaborator_id (mobile PWA não tem auth).

    Quando `admin_test=1` é passado E o requisitante for administrador/auditor
    autenticado, retorna bolhas de TODOS os colaboradores da empresa do
    `cid` (modo "teste admin" — gestor/auditor pode abrir qualquer bolha de
    qualquer técnico em qualquer horário). Sem essa flag, mantém o
    comportamento histórico (só bolhas atribuídas ao próprio cid).
    """
    coll = await db.collaborators.find_one(
        {"id": cid}, {"_id": 0, "id": 1, "company_id": 1},
    )
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    cross_collab_company = None
    if admin_test:
        # Valida JWT manualmente — se for admin/auditor, libera o modo
        # cross-colaborador
        try:
            auth_header = (request.headers.get("authorization") or "") if request else ""
            if auth_header.lower().startswith("bearer "):
                token = auth_header.split(" ", 1)[1].strip()
                from auth import decode_token
                payload = decode_token(token)
                if payload and payload.get("role") in ("administrador", "auditor"):
                    cross_collab_company = coll.get("company_id")
        except Exception:
            cross_collab_company = None
    return await _lousa_for_collaborator(
        cid, admin_test_company_id=cross_collab_company,
    )


async def _lousa_for_collaborator(
    cid: str,
    admin_test_company_id: Optional[str] = None,
) -> dict:
    state = await _today_clock_state(cid)
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0, "clock_in_enabled": 1})
    clock_in_enabled = bool((coll or {}).get("clock_in_enabled", True))
    # No modo admin_test, NUNCA bloqueia por ponto (gestor não bate ponto).
    if (not admin_test_company_id) and clock_in_enabled and not state["has_entrada"]:
        return {
            "tickets": [],
            "recent_resolved": [],
            "active_ticket_id": None,
            "clock_state": state,
            "lousa_unlocked": False,
            "needs_clock_in": True,
            "clock_in_enabled": True,
        }
    active_states = ["pendente", "aberta", "aguardando_atendimento"]
    # Query: admin_test busca por company_id; modo normal por collaborator_id
    if admin_test_company_id:
        active_query = {
            "company_id": admin_test_company_id,
            "status": {"$in": active_states},
        }
    else:
        active_query = {
            "assigned_collaborator_id": cid,
            "status": {"$in": active_states},
        }
    active_raw = await db.tickets.find(active_query, {"_id": 0}).to_list(500)
    # REGRA DE DATA: filtra apenas bolhas cuja data de serviço/abertura
    # corresponde a HOJE (BR). Bolhas reagendadas pra outros dias somem
    # da Lousa de hoje (e aparecem na Lousa do dia agendado).
    today = _today_br_iso()
    active_raw = [t for t in active_raw if _ticket_day_iso(t) == today]
    active_raw.sort(key=lambda t: (PRIORITY_RANK.get(t.get("priority"), 99),
                                       t.get("position") or 999))
    locked_idx = compute_locked_positions(active_raw)
    for i, t in enumerate(active_raw):
        # Para clock_in_enabled=false, in_intervalo e ended_day não aplicam
        is_blocked_by_clock = clock_in_enabled and (state["in_intervalo"] or state["ended_day"])
        # t["locked"] = NÃO PODE abrir/iniciar a bolha (somente clock state real).
        # t["reorder_locked"] = NÃO PODE reordenar (posicional — bolhas horario/prioridade
        # ou a anterior a uma horario). Esse era o motivo do bug do VANDO: bolha solo
        # com priority="horario" virava locked=True só pela regra de reorder, e o
        # frontend desabilitava o clique mesmo a lousa estando liberada.
        t["locked"] = is_blocked_by_clock
        t["reorder_locked"] = i in locked_idx
        t["admin_resolved"] = False

    # Tickets resolvidos PELO TÉCNICO ficam visíveis 24h (histórico do dia).
    # Tickets resolvidos PELA GESTÃO (cancelada/reagendada) saem da Lousa do app —
    # gestão já cuidou e o técnico não precisa mais agir/ver.
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    if admin_test_company_id:
        resolved_query = {
            "company_id": admin_test_company_id,
            "status": {"$in": list(TECH_RESOLVED)},
            "closed_at": {"$gte": cutoff},
        }
    else:
        resolved_query = {
            "assigned_collaborator_id": cid,
            "status": {"$in": list(TECH_RESOLVED)},
            "closed_at": {"$gte": cutoff},
        }
    resolved_raw = await db.tickets.find(resolved_query, {"_id": 0}).to_list(200)
    resolved_raw.sort(key=lambda t: t.get("closed_at", ""), reverse=True)
    for t in resolved_raw:
        t["locked"] = True
        t["admin_resolved"] = t["status"] in ADMIN_RESOLVED
        t["duration_minutes"] = compute_duration_minutes(t)

    # Calcula gap em ordem cronológica (mais antigo → mais novo) ----
    chrono = sorted(
        [t for t in resolved_raw if t.get("opened_at")] +
        [t for t in active_raw if t.get("opened_at")],
        key=lambda t: t.get("opened_at") or "",
    )
    prev_close_iso: Optional[str] = None
    for t in chrono:
        if prev_close_iso and t.get("opened_at"):
            try:
                pc = datetime.fromisoformat(prev_close_iso.replace("Z", "+00:00"))
                op = datetime.fromisoformat(t["opened_at"].replace("Z", "+00:00"))
                if pc.tzinfo is None:
                    pc = pc.replace(tzinfo=timezone.utc)
                if op.tzinfo is None:
                    op = op.replace(tzinfo=timezone.utc)
                t["gap_minutes_to_prev"] = max(0, round((op - pc).total_seconds() / 60.0, 1))
            except Exception:
                t["gap_minutes_to_prev"] = None
        else:
            t["gap_minutes_to_prev"] = None
        if t.get("closed_at"):
            prev_close_iso = t["closed_at"]
    for t in active_raw:
        t["duration_minutes"] = compute_duration_minutes(t)

    # Tempo entre Saída-do-último-serviço e AGORA — útil pro app mostrar gap até clock-out
    last_closed_at: Optional[str] = None
    if resolved_raw:
        last_closed_at = resolved_raw[0].get("closed_at")  # já ordenado desc
    minutes_since_last_close: Optional[float] = None
    if last_closed_at:
        try:
            lc = datetime.fromisoformat(last_closed_at.replace("Z", "+00:00"))
            if lc.tzinfo is None:
                lc = lc.replace(tzinfo=timezone.utc)
            minutes_since_last_close = round((datetime.now(timezone.utc) - lc).total_seconds() / 60.0, 1)
        except Exception:
            pass

    active = next((t for t in active_raw if t["status"] in ("aberta", "aguardando_atendimento")), None)

    # Enriquece bolhas com o nome do colaborador atribuído (útil no modo
    # admin_test onde técnicos diferentes aparecem na mesma tela).
    cids_in_tickets = {t.get("assigned_collaborator_id")
                         for t in (active_raw + resolved_raw)
                         if t.get("assigned_collaborator_id")}
    if cids_in_tickets:
        async for c in db.collaborators.find(
            {"id": {"$in": list(cids_in_tickets)}},
            {"_id": 0, "id": 1, "name": 1},
        ):
            for t in active_raw + resolved_raw:
                if t.get("assigned_collaborator_id") == c["id"]:
                    t["assigned_collaborator_name"] = c.get("name") or "—"
    # Enriquece com sinal SmartOLT (best-effort — útil pro técnico ver dBm antes de chegar)
    try:
        from routes.smartolt import enrich_tickets_with_live_signal
        coll_doc = await db.collaborators.find_one({"id": cid}, {"_id": 0, "company_id": 1})
        cid_company = (coll_doc or {}).get("company_id") or DEMO_COMPANY_ID
        await enrich_tickets_with_live_signal(active_raw + resolved_raw, cid_company)
    except Exception as _e:
        logger.warning("[lousa] enrich live_signal (mobile) falhou: %s", _e)
    # MIRROR: Lousa do colaborador = APENAS bolhas ativas (mesmas que aparecem na lousa do gestor)
    # Resolvidos vão como metadata separada para o card "Último serviço encerrado", não na lista de bolhas
    return {
        "tickets": active_raw,  # apenas ativas — espelha exatamente lousa do gestor
        "recent_resolved": resolved_raw,  # metadata para histórico do dia
        "active_ticket_id": active["id"] if active else None,
        "last_closed_at": last_closed_at,
        "minutes_since_last_close": minutes_since_last_close,
        "clock_state": state,
        # Para colaboradores sem ponto a Lousa nunca tranca por intervalo/saída
        "lousa_unlocked": (not clock_in_enabled) or (not state["in_intervalo"] and not state["ended_day"]),
        "needs_clock_in": False,
        "clock_in_enabled": clock_in_enabled,
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


@router.get("/lousa/returned-notes")
async def list_returned_notes(
    user: dict = Depends(require_role("gestor")),
    days_back: int = 30,
):
    """Notas que **retornaram**: bolhas que ficaram em aberto/pendente em
    dias anteriores ao de hoje. Não voltam pra fila — entram só nesta lista
    para o gestor decidir manualmente (reagendar, cancelar, ou liberar
    pra outro técnico).

    Critério (exclusivo desta listagem):
    - status em `pendente`/`aberta`/`aguardando_atendimento`
    - `_ticket_day_iso(t)` < hoje (calculado pelo helper já usado pela lousa)
    - dentro da janela `days_back` (default 30 dias)

    Bolhas reagendadas (`status=reagendada`) NÃO entram aqui — quem
    reagenda já indicou que vai trabalhar de novo. Só "esquecidas".
    """
    q = tenant_filter(user)
    collabs = await db.collaborators.find(q, {"_id": 0, "id": 1, "name": 1}).to_list(500)
    cids = [c["id"] for c in collabs]
    name_by_cid = {c["id"]: c.get("name", "—") for c in collabs}

    today_iso = _today_br_iso()
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()

    raw = await db.tickets.find(
        {"assigned_collaborator_id": {"$in": cids},
         "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]},
         "created_at": {"$gte": cutoff_iso}},
        {"_id": 0},
    ).to_list(5000)

    returned = []
    for t in raw:
        day = _ticket_day_iso(t)
        if not day or day >= today_iso:
            continue
        t["returned_from_date"] = day
        t["technician_name"] = name_by_cid.get(t.get("assigned_collaborator_id"), "—")
        try:
            tdate = datetime.fromisoformat(day)
            now_br = datetime.now(timezone.utc)
            days_old = max(1, (now_br.date() - tdate.date()).days)
        except Exception:
            days_old = None
        t["days_overdue"] = days_old
        returned.append(t)

    returned.sort(key=lambda x: (x.get("returned_from_date") or "", x.get("position", 0)))

    # Resumo por técnico (cards)
    by_tech: dict = {}
    for t in returned:
        tid = t.get("assigned_collaborator_id") or "—"
        if tid not in by_tech:
            by_tech[tid] = {
                "collaborator_id": tid,
                "name": name_by_cid.get(tid, "—"),
                "count": 0,
                "oldest_date": None,
            }
        by_tech[tid]["count"] += 1
        d = t.get("returned_from_date")
        cur_old = by_tech[tid]["oldest_date"]
        if d and (cur_old is None or d < cur_old):
            by_tech[tid]["oldest_date"] = d

    return {
        "ok": True,
        "total": len(returned),
        "items": returned,
        "by_technician": list(by_tech.values()),
        "today": today_iso,
        "days_back": days_back,
    }


@router.get("/lousa/ping-quality-report")
async def lousa_ping_quality_report(
    user: dict = Depends(require_role("gestor")),
    days_back: int = 7,
):
    """KPI: % de bolhas FINALIZADAS que tiveram teste de ping realizado,
    agrupado por técnico nos últimos N dias.

    Critério "tem ping":
      - completion_data.ping_summary contém "✓" ou "respondeu" (positivo) OR
      - "realizado" (qualquer resultado, mesmo falha) — desde que NÃO seja
        "NÃO FOI REALIZADO"

    Resposta:
      {
        "days_back": 7,
        "totals": { "finalized": 120, "with_ping": 78, "without_ping": 42,
                     "rate_pct": 65.0 },
        "by_technician": [ { collaborator_id, name, finalized, with_ping,
                              without_ping, rate_pct }, ... ]
      }
    """
    q = tenant_filter(user)
    collabs = await db.collaborators.find(
        q, {"_id": 0, "id": 1, "name": 1},
    ).to_list(500)
    cids = [c["id"] for c in collabs]
    name_by_cid = {c["id"]: c.get("name", "—") for c in collabs}

    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
    tickets = await db.tickets.find(
        {"assigned_collaborator_id": {"$in": cids},
         "status": "finalizada",
         "closed_at": {"$gte": since}},
        {"_id": 0, "id": 1, "assigned_collaborator_id": 1,
         "closed_at": 1, "completion_data.ping_summary": 1},
    ).to_list(20000)

    by_tech: dict = {}
    total_fin = total_with = 0
    for t in tickets:
        tid = t.get("assigned_collaborator_id") or "—"
        if tid not in by_tech:
            by_tech[tid] = {
                "collaborator_id": tid,
                "name": name_by_cid.get(tid, "—"),
                "finalized": 0, "with_ping": 0, "without_ping": 0,
            }
        by_tech[tid]["finalized"] += 1
        total_fin += 1
        cd = (t.get("completion_data") or {})
        summary = (cd.get("ping_summary") or "").strip()
        has_ping = bool(summary) and "NÃO FOI REALIZADO" not in summary.upper()
        if has_ping:
            by_tech[tid]["with_ping"] += 1
            total_with += 1
        else:
            by_tech[tid]["without_ping"] += 1

    rows = []
    for r in by_tech.values():
        n = r["finalized"]
        r["rate_pct"] = round(100.0 * r["with_ping"] / n, 1) if n else 0.0
        rows.append(r)
    rows.sort(key=lambda x: (-x["finalized"], -x["rate_pct"]))

    return {
        "days_back": days_back,
        "totals": {
            "finalized": total_fin,
            "with_ping": total_with,
            "without_ping": total_fin - total_with,
            "rate_pct": round(100.0 * total_with / total_fin, 1) if total_fin else 0.0,
        },
        "by_technician": rows,
    }


# ===========================================================================
# Coaching automático — config + histórico de alertas
# ===========================================================================
class CoachingCfgIn(BaseModel):
    enabled: bool = False
    manager_phone: str = Field("", max_length=32)
    threshold: int = Field(3, ge=2, le=10)


@router.get("/lousa/coaching-config")
async def get_coaching_cfg(user: dict = Depends(require_role("gestor"))):
    from services.lousa_coaching import get_coaching_config
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await get_coaching_config(cid)


@router.put("/lousa/coaching-config")
async def save_coaching_cfg(payload: CoachingCfgIn,
                              user: dict = Depends(require_role("gestor"))):
    from services.lousa_coaching import save_coaching_config
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await save_coaching_config(
        cid, payload.enabled, payload.manager_phone, payload.threshold,
    )


@router.get("/lousa/coaching-alerts")
async def list_coaching_alerts(days_back: int = 30,
                                  user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
    docs = await db.lousa_coaching_alerts.find(
        {"company_id": cid, "created_at": {"$gte": since}},
        {"_id": 0},
    ).sort("created_at", -1).limit(200).to_list(200)
    return {"items": docs, "count": len(docs), "days_back": days_back}


# ===========================================================================
# Closure Quality — IA correlaciona reclamação x solução e dá nota
# ===========================================================================
class ClosureQualityAnalyzeIn(BaseModel):
    days_back: int = Field(7, ge=1, le=60)
    limit: int = Field(20, ge=1, le=100)


async def _analyze_ticket_quality_with_ai(ticket: dict) -> dict:
    """Usa LLM pra correlacionar reclamação do cliente x solução do técnico.

    Retorna { score: 0-100, verdict: str, reasoning: str }.
    Score alto → solução provavelmente resolve o problema.
    Score baixo → solução incoerente ou paliativo.
    """
    cd = ticket.get("completion_data") or {}
    client = (ticket.get("client_snapshot") or {}).get("name") or "—"
    complaint = (ticket.get("title")
                 or ticket.get("description")
                 or ticket.get("category")
                 or "")
    outcome = ticket.get("outcome") or "—"
    observations = (cd.get("observations") or cd.get("laudo") or "")
    ping_summary = cd.get("ping_summary") or ""
    sinal = cd.get("sinal")

    prompt = (
        "Você é um auditor técnico de provedores de internet. "
        "Compare a RECLAMAÇÃO do cliente com a SOLUÇÃO que o técnico aplicou e "
        "responda em JSON estrito.\n\n"
        f"CLIENTE: {client}\n"
        f"RECLAMAÇÃO/CATEGORIA: {complaint}\n"
        f"DESFECHO: {outcome}\n"
        f"SINAL ÓTICO (dBm): {sinal}\n"
        f"PING NA ONU: {ping_summary[:300]}\n"
        f"OBSERVAÇÕES DO TÉCNICO: {observations[:600]}\n\n"
        "Regras:\n"
        "- score: inteiro 0-100. 80+ se a solução resolve a reclamação. "
        "30- se é paliativa, incoerente ou se faltou diagnóstico (ex.: "
        "fechou sem ping numa reclamação de internet lenta).\n"
        "- verdict: uma de [\"resolve\",\"paliativo\",\"incoerente\","
        "\"sem_diagnostico\"].\n"
        "- reasoning: no máximo 220 caracteres em Português, direto ao ponto.\n\n"
        "Responda APENAS o JSON, sem markdown."
    )
    try:
        from emergentintegrations.llm.chat import UserMessage
        chat = await llm_chat(
            session_id=f"lousa-quality-{ticket.get('id')}",
            system="Auditor técnico. Responda apenas JSON.",
        )
        resp = await chat.send_message(UserMessage(text=prompt))
        raw = str(resp).strip()
        # Remove fences caso o modelo tenha forçado ```json
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.DOTALL)
        data = json.loads(raw)
        score = int(data.get("score", 0))
        score = max(0, min(score, 100))
        return {
            "score": score,
            "verdict": str(data.get("verdict", "incoerente"))[:32],
            "reasoning": str(data.get("reasoning", ""))[:240],
        }
    except Exception as e:
        logger.warning("[closure-quality] ia falhou ticket=%s: %s",
                       ticket.get("id"), e)
        return {"score": 0, "verdict": "ia_falhou", "reasoning": str(e)[:200]}


@router.get("/lousa/reports/closure-quality")
async def closure_quality_report(days_back: int = 7,
                                    user: dict = Depends(require_role("gestor"))):
    """Card "Qualidade dos Fechamentos": top motivos + estatística da
    análise IA cacheada.

    Lê de `lousa_closure_analysis` (preenchida via POST /analyze).
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
    q = {"company_id": cid, "status": "finalizada",
         "closed_at": {"$gte": since}}
    tickets = await db.tickets.find(
        q,
        {"_id": 0, "id": 1, "title": 1, "category": 1, "outcome": 1,
         "closed_at": 1, "assigned_collaborator_id": 1,
         "client_snapshot": 1, "completion_data.observations": 1,
         "completion_data.ping_summary": 1, "completion_data.sinal": 1},
    ).sort("closed_at", -1).limit(2000).to_list(2000)
    total = len(tickets)

    # Top motivos: agrupa por category||outcome||title (primeiros 40 chars)
    reasons: dict = {}
    for t in tickets:
        key = (t.get("category") or t.get("outcome")
               or (t.get("title") or "—"))
        key = str(key).strip()[:60] or "—"
        reasons[key] = reasons.get(key, 0) + 1
    top_reasons = sorted(
        [{"reason": k, "count": v,
          "pct": round(100.0 * v / total, 1) if total else 0.0}
         for k, v in reasons.items()],
        key=lambda x: -x["count"],
    )[:10]

    # Carrega análises já feitas (cache)
    tids = [t["id"] for t in tickets]
    analyses = await db.lousa_closure_analysis.find(
        {"ticket_id": {"$in": tids}},
        {"_id": 0},
    ).to_list(len(tids) or 1)

    analyzed = [a for a in analyses if isinstance(a.get("score"), int)]
    if analyzed:
        avg_score = round(sum(a["score"] for a in analyzed) / len(analyzed), 1)
    else:
        avg_score = None
    low_score = sorted(
        [a for a in analyzed if a["score"] < 50],
        key=lambda a: a["score"],
    )[:8]

    # Anexa client + title nas low_score para UI
    for a in low_score:
        t = next((x for x in tickets if x["id"] == a["ticket_id"]), None)
        if t:
            a["client_name"] = (t.get("client_snapshot") or {}).get("name") or "—"
            a["title"] = t.get("title") or t.get("category") or "—"
            a["closed_at"] = t.get("closed_at")

    return {
        "days_back": days_back,
        "totals": {
            "finalized": total,
            "analyzed": len(analyzed),
            "pending": total - len(analyzed),
            "avg_score": avg_score,
            "low_score_count": len([a for a in analyzed if a["score"] < 50]),
        },
        "top_reasons": top_reasons,
        "low_score_tickets": low_score,
    }


@router.post("/lousa/reports/closure-quality/analyze")
async def closure_quality_analyze(payload: ClosureQualityAnalyzeIn,
                                     user: dict = Depends(require_role("gestor"))):
    """Roda IA nos tickets fechados ainda não analisados (limit configurável).

    Persiste em `lousa_closure_analysis` (ticket_id é chave única).
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    since = (datetime.now(timezone.utc)
              - timedelta(days=payload.days_back)).isoformat()
    tickets = await db.tickets.find(
        {"company_id": cid, "status": "finalizada",
         "closed_at": {"$gte": since}},
        {"_id": 0},
    ).sort("closed_at", -1).limit(2000).to_list(2000)
    tids = [t["id"] for t in tickets]
    already = await db.lousa_closure_analysis.find(
        {"ticket_id": {"$in": tids}},
        {"_id": 0, "ticket_id": 1},
    ).to_list(len(tids) or 1)
    done = {a["ticket_id"] for a in already}
    pending = [t for t in tickets if t["id"] not in done][:payload.limit]

    processed = 0
    for t in pending:
        result = await _analyze_ticket_quality_with_ai(t)
        doc = {
            "ticket_id": t["id"],
            "company_id": cid,
            "collaborator_id": t.get("assigned_collaborator_id"),
            "score": result["score"],
            "verdict": result["verdict"],
            "reasoning": result["reasoning"],
            "analyzed_at": now_iso(),
        }
        try:
            await db.lousa_closure_analysis.update_one(
                {"ticket_id": t["id"]},
                {"$set": doc},
                upsert=True,
            )
            processed += 1
        except Exception as e:
            logger.warning("[closure-quality] persist falhou ticket=%s: %s",
                           t["id"], e)

    return {"processed": processed, "remaining_pending":
                max(0, len([t for t in tickets if t["id"] not in done]) - processed)}



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
            "pppoe_user": payload.pppoe_user,
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
        "ai_triage_pending": True,
        # Quality notes — snapshot do sinal SmartOLT na abertura.
        # Preenchido best-effort (cliente pode não ter SmartOLT mapeado).
        "signal_at_open": None,
        "signal_at_open_at": None,
        "signal_at_close": None,
        "signal_at_close_at": None,
        "created_at": now_iso(),
    }
    await db.tickets.insert_one(doc)
    # Captura snapshot do sinal NO MOMENTO DA ABERTURA (best-effort, async)
    try:
        snap = await _capture_signal_snapshot(doc["id"], doc["company_id"], "open")
        if snap:
            doc["signal_at_open"] = snap
            doc["signal_at_open_at"] = now_iso()
    except Exception as e:
        logger.info("[lousa.quality] snapshot abertura falhou: %s", e)
    # Modo Boss: se urgente, envia notificação automática ao cliente via Baileys
    if payload.priority == "urgente":
        try:
            await _send_boss_mode_whatsapp(doc, coll)
        except Exception as e:
            logger.exception("[lousa] boss_mode whatsapp falhou: %s", e)
    await _log_ticket_action(
        ticket_id=doc["id"], action="criada",
        actor_id=user["id"], actor_name=user.get("name", "Gestor"),
        actor_role=user.get("role", "gestor"),
        details=f"Atribuída a {coll.get('name', 'colaborador')} · {payload.client_name}",
        company_id=doc["company_id"],
    )
    doc.pop("_id", None)
    return doc


async def _quality_capture_enabled(company_id: str) -> bool:
    """Retorna True se a captura automática de sinal está ligada para a empresa.
    Default = True (compatibilidade retroativa)."""
    try:
        doc = await db.lousa_quality_config.find_one(
            {"company_id": company_id}, {"_id": 0, "enabled": 1},
        )
        if doc is None:
            return True
        return doc.get("enabled") is not False
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Auto-Reschedule on Degraded Signal (controlado pelo auditor)
# ---------------------------------------------------------------------------
async def _auto_resched_config(company_id: str) -> dict:
    """Configuração persistida em `lousa_auto_resched_config`.

    Padrões (compatibilidade retro):
        enabled=False, delay_hours=24, target_role='tecnico_rede',
        target_collaborator_id=None
    """
    doc = await db.lousa_auto_resched_config.find_one(
        {"company_id": company_id}, {"_id": 0},
    ) or {}
    return {
        "enabled": bool(doc.get("enabled", False)),
        "delay_hours": int(doc.get("delay_hours", 24)),
        "target_role": doc.get("target_role") or "tecnico_rede",
        "target_collaborator_id": doc.get("target_collaborator_id"),
        "updated_by": doc.get("updated_by"),
        "updated_at": doc.get("updated_at"),
    }


async def _pick_tecnico_rede(company_id: str,
                              prefer_id: Optional[str] = None) -> Optional[dict]:
    """Encontra um colaborador de rede para receber o reagendamento."""
    if prefer_id:
        c = await db.collaborators.find_one(
            {"id": prefer_id, "company_id": company_id, "active": {"$ne": False}},
            {"_id": 0, "id": 1, "name": 1},
        )
        if c:
            return c
    # Busca por role/cargo "tecnico_rede" no campo `role` ou `cargo`
    c = await db.collaborators.find_one(
        {"company_id": company_id, "active": {"$ne": False},
         "$or": [
            {"role": {"$regex": "rede", "$options": "i"}},
            {"cargo": {"$regex": "rede", "$options": "i"}},
            {"function": {"$regex": "rede", "$options": "i"}},
         ]},
        {"_id": 0, "id": 1, "name": 1},
    )
    return c


async def _maybe_auto_resched_degraded(ticket_id: str, company_id: str) -> None:
    """Se sinal degradou (|close| > |open|) E auditor ligou o toggle,
    cria automaticamente um chamado de reinspeção para Técnico de Rede.

    Não falha se algum requisito estiver ausente (skip silencioso).
    """
    cfg = await _auto_resched_config(company_id)
    if not cfg["enabled"]:
        return
    t = await db.tickets.find_one(
        {"id": ticket_id},
        {"_id": 0, "id": 1, "client_snapshot": 1, "type": 1, "priority": 1,
         "signal_at_open": 1, "signal_at_close": 1, "completion_data": 1,
         "company_id": 1},
    )
    if not t:
        return
    sig_open = (t.get("signal_at_open") or {}).get("rx_dbm")
    sig_close_obj = t.get("signal_at_close") or {}
    sig_close = sig_close_obj.get("rx_dbm")
    if sig_close is None:
        sig_close = (t.get("completion_data") or {}).get("sinal")
    if sig_open is None or sig_close is None:
        return
    if abs(float(sig_close)) <= abs(float(sig_open)):
        # Não degradou — pode ter melhorado ou ficado estável. Skip.
        return

    target = await _pick_tecnico_rede(
        company_id, cfg.get("target_collaborator_id"))
    if not target:
        logger.warning(
            "[lousa.auto-resched] ticket=%s sinal degradou %.1f→%.1f mas "
            "não há técnico de rede disponível.",
            ticket_id, float(sig_open), float(sig_close))
        return

    # Calcula scheduled_time = agora + delay_hours
    from datetime import datetime as dt_, timedelta, timezone as tz_
    sched_dt = dt_.now(tz_.utc) + timedelta(hours=cfg["delay_hours"])
    sched_iso = sched_dt.isoformat()

    # Próxima posição no quadro do técnico de rede
    last = await db.tickets.find_one(
        {"assigned_collaborator_id": target["id"],
         "company_id": company_id, "status": "pendente"},
        sort=[("position", -1)], projection={"position": 1, "_id": 0},
    )
    next_pos = ((last or {}).get("position") or 0) + 1

    new_id = f"tkt-{uuid.uuid4().hex[:10]}"
    new_doc = {
        "id": new_id,
        "client_id": (t.get("client_snapshot") or {}).get("id"),
        "client_snapshot": t.get("client_snapshot") or {},
        "type": "manutencao_rede",
        "priority": "alta",
        "scheduled_time": sched_iso,
        "position": next_pos,
        "status": "pendente",
        "assigned_collaborator_id": target["id"],
        "company_id": company_id,
        "opened_at": None, "closed_at": None, "closed_by": None,
        "close_location": None, "outcome": None,
        "whatsapp_status": "nao_enviado", "whatsapp_last_message": None,
        "completion_data": None,
        "admin_action": "auto_resched_degraded",
        "admin_notes": (
            f"Reinspeção automática — Sinal degradou de "
            f"{float(sig_open):.1f} dBm para {float(sig_close):.1f} dBm "
            f"na OS [{ticket_id}]."
        ),
        "auto_resched_from": ticket_id,
        "ai_triage_pending": False,
        "signal_at_open": None, "signal_at_open_at": None,
        "signal_at_close": None, "signal_at_close_at": None,
        "created_at": now_iso(),
    }
    await db.tickets.insert_one(dict(new_doc))
    await _log_ticket_action(
        ticket_id=new_id, action="auto_resched_degraded",
        actor_id="system", actor_name="Sistema (auto)",
        actor_role="system",
        details=(f"Reagendada automaticamente a partir de {ticket_id} · "
                  f"sinal {float(sig_open):.1f} → {float(sig_close):.1f} dBm"),
        company_id=company_id,
    )
    logger.info(
        "[lousa.auto-resched] %s → %s (téc rede %s) sinal %.1f→%.1f",
        ticket_id, new_id, target["name"],
        float(sig_open), float(sig_close))


class AutoReschedConfigIn(BaseModel):
    enabled: bool
    delay_hours: Optional[int] = 24
    target_collaborator_id: Optional[str] = None


@router.get("/lousa/auto-resched-config")
async def get_auto_resched_config(
        user: dict = Depends(require_role("auditor", "administrador"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _auto_resched_config(company_id)
    # Anexa lista de técnicos de rede pra UI
    rede_candidates = await db.collaborators.find(
        {"company_id": company_id, "active": {"$ne": False},
         "$or": [
            {"role": {"$regex": "rede", "$options": "i"}},
            {"cargo": {"$regex": "rede", "$options": "i"}},
            {"function": {"$regex": "rede", "$options": "i"}},
         ]},
        {"_id": 0, "id": 1, "name": 1},
    ).limit(20).to_list(20)
    cfg["rede_candidates"] = rede_candidates
    return cfg


@router.put("/lousa/auto-resched-config")
async def set_auto_resched_config(payload: AutoReschedConfigIn,
        user: dict = Depends(require_role("auditor", "administrador"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    delay = max(0, min(int(payload.delay_hours or 24), 168))  # 0..168h (1 sem)
    doc = {
        "company_id": company_id,
        "enabled": bool(payload.enabled),
        "delay_hours": delay,
        "target_role": "tecnico_rede",
        "target_collaborator_id": payload.target_collaborator_id,
        "updated_by": user.get("name") or user.get("email"),
        "updated_at": now_iso(),
    }
    await db.lousa_auto_resched_config.update_one(
        {"company_id": company_id},
        {"$set": doc}, upsert=True,
    )
    await _log_ticket_action(
        ticket_id="-", action="auto_resched_config",
        actor_id=user.get("id", "auditor"),
        actor_name=user.get("name", "auditor"),
        actor_role=user.get("role", "auditor"),
        details=(f"Auto-resched ON sinal degradado · "
                  f"enabled={payload.enabled} delay={delay}h "
                  f"target={payload.target_collaborator_id or 'auto'}"),
        company_id=company_id,
    )
    cfg = await _auto_resched_config(company_id)
    return cfg


async def _capture_signal_snapshot(ticket_id: str, company_id: str,
                                       moment: str) -> Optional[dict]:
    """Captura snapshot do sinal SmartOLT no chamado e grava em
    `signal_at_open` ou `signal_at_close`. Honra o toggle global.

    Retorna o snapshot gravado ou None se não foi possível.
    moment: 'open' | 'close'
    """
    if moment not in ("open", "close"):
        return None
    try:
        if not await _quality_capture_enabled(company_id):
            return None
        t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
        if not t:
            return None
        from routes.smartolt import resolve_signal_for_ticket, get_onu_signal_live
        onu = await resolve_signal_for_ticket(t)
        if not onu or not onu.get("sn"):
            return None
        live = await get_onu_signal_live(onu.get("sn"), company_id)
        if not live or live.get("rx_dbm") is None:
            return None
        snap = {
            "rx_dbm": float(live["rx_dbm"]),
            "status": live.get("status"),
            "sn": onu.get("sn"),
        }
        key = f"signal_at_{moment}"
        key_at = f"signal_at_{moment}_at"
        await db.tickets.update_one(
            {"id": ticket_id},
            {"$set": {key: snap, key_at: now_iso()}},
        )
        return snap
    except Exception as e:
        logger.info("[lousa.quality] snapshot %s falhou: %s", moment, e)
        return None


@router.get("/lousa/quality-notes/config")
async def quality_notes_get_config(user: dict = Depends(require_role("gestor"))):
    """Lê config da feature 'Notas de Qualidade' (toggle on/off + threshold)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.lousa_quality_config.find_one({"company_id": cid}, {"_id": 0})
    if not doc:
        doc = {
            "company_id": cid,
            "enabled": True,
            "degradation_threshold_db": 3.0,
            "los_threshold_dbm": -28.0,
        }
    return doc


class QualityConfigIn(BaseModel):
    enabled: Optional[bool] = None
    degradation_threshold_db: Optional[float] = Field(default=None, ge=0.5, le=20)
    los_threshold_dbm: Optional[float] = Field(default=None, ge=-40, le=-15)


@router.put("/lousa/quality-notes/config")
async def quality_notes_set_config(body: QualityConfigIn,
                                       user: dict = Depends(require_role("administrador"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    if not upd:
        raise HTTPException(400, "Nada para atualizar")
    upd["updated_at"] = now_iso()
    upd["updated_by"] = user.get("email")
    await db.lousa_quality_config.update_one(
        {"company_id": cid}, {"$set": upd, "$setOnInsert": {"company_id": cid}},
        upsert=True,
    )
    return await quality_notes_get_config(user)


@router.get("/lousa/quality-notes")
async def quality_notes_list(
    days: int = 30, limit: int = 100,
    user: dict = Depends(require_role("gestor")),
):
    """Lista tickets finalizados com snapshot de sinal antes/depois +
    classificação automática:

    - **bom**: sinal melhorou (Δ ≥ 0)
    - **regular**: piorou pouco (Δ < 3 dB)
    - **ruim**: piorou >= 3 dB ou foi pra LOS pós-reparo
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await quality_notes_get_config(user)
    deg_thr = float(cfg.get("degradation_threshold_db") or 3.0)
    los_thr = float(cfg.get("los_threshold_dbm") or -28.0)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    rows = await db.tickets.find(
        {
            "company_id": cid,
            "status": {"$in": ["finalizada", "encerrada"]},
            "closed_at": {"$gte": cutoff},
            "signal_at_open": {"$ne": None},
            "signal_at_close": {"$ne": None},
        },
        {"_id": 0, "id": 1, "client_snapshot": 1, "type": 1,
         "assigned_collaborator_id": 1, "closed_at": 1, "closed_by": 1,
         "signal_at_open": 1, "signal_at_close": 1,
         "signal_at_open_at": 1, "signal_at_close_at": 1, "outcome": 1,
         "admin_action": 1, "completion_data.internal_close": 1},
    ).sort("closed_at", -1).limit(min(limit, 500)).to_list(500)

    # Enriquece com nome do técnico
    coll_ids = list({r["closed_by"] for r in rows if r.get("closed_by")})
    coll_map = {}
    if coll_ids:
        for c in await db.collaborators.find(
                {"id": {"$in": coll_ids}}, {"_id": 0, "id": 1, "name": 1},
        ).to_list(len(coll_ids)):
            coll_map[c["id"]] = c.get("name")

    summary = {"bom": 0, "regular": 0, "ruim": 0, "internal_close": 0}
    for r in rows:
        before = float(r["signal_at_open"]["rx_dbm"])
        after = float(r["signal_at_close"]["rx_dbm"])
        delta = round(after - before, 2)
        # Em dBm, valores mais próximos de 0 são melhores. -23 > -27.
        # "delta positivo" = melhorou (saiu de -27 pra -23 = +4dB)
        is_los_after = after <= los_thr
        if is_los_after:
            grade = "ruim"
            reason = f"Pós-reparo em LOS ({after} ≤ {los_thr} dBm)"
        elif delta < -deg_thr:
            grade = "ruim"
            reason = f"Piorou {abs(delta):.1f} dB (≥ {deg_thr})"
        elif delta < 0:
            grade = "regular"
            reason = f"Piorou {abs(delta):.1f} dB (tolerável)"
        else:
            grade = "bom"
            reason = f"Estável ou melhorou ({'+' if delta >= 0 else ''}{delta:.1f} dB)"
        r["quality_delta_db"] = delta
        r["quality_grade"] = grade
        r["quality_reason"] = reason
        r["closed_by_name"] = coll_map.get(r.get("closed_by"))
        # Fechamento interno (gestor sem técnico no local): bandeira de auditoria
        cd = r.get("completion_data") or {}
        r["internal_close"] = bool(cd.get("internal_close")) or r.get("admin_action") == "encerrar"
        summary[grade] += 1
        if r["internal_close"]:
            summary["internal_close"] += 1

    return {
        "items": rows,
        "total": len(rows),
        "summary": summary,
        "config": cfg,
    }


@router.delete("/lousa/tickets/{ticket_id}")
async def delete_ticket(ticket_id: str, user: dict = Depends(require_role("gestor"))):
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0, "status": 1})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    if t.get("status") == "aberta":
        raise HTTPException(409, "Serviço em execução pelo técnico — não pode ser removido. Encerre antes via gestão.")
    res = await db.tickets.delete_one({"id": ticket_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Nota não encontrada")
    return {"ok": True}


@router.get("/lousa/quality-notes/technicians-ranking")
async def quality_technicians_ranking(
    days: int = Query(7, ge=1, le=365),
    user: dict = Depends(require_role("gestor")),
):
    """Ranking de técnicos por % de reparos com sinal melhorado.

    Agrega tickets finalizados com `signal_at_open` E `signal_at_close` por
    técnico nos últimos `days` dias e classifica cada um em:
      - **bom**: sinal estável/melhorou (Δ ≥ 0)
      - **regular**: piorou < `degradation_threshold_db`
      - **ruim**: piorou ≥ threshold OU ficou em LOS no fechamento
    Retorna lista ordenada por `quality_score` (% de bons + ponderação).
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await quality_notes_get_config(user)
    deg_thr = float(cfg.get("degradation_threshold_db") or 3.0)
    los_thr = float(cfg.get("los_threshold_dbm") or -28.0)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    rows = await db.tickets.find(
        {
            "company_id": cid,
            "status": "finalizada",
            "closed_at": {"$gte": cutoff},
            "signal_at_open": {"$ne": None},
            "signal_at_close": {"$ne": None},
            "closed_by": {"$ne": None},
        },
        {"_id": 0, "closed_by": 1, "assigned_collaborator_id": 1,
         "signal_at_open": 1, "signal_at_close": 1},
    ).to_list(5000)

    # Resolve user_id -> collaborator_id quando necessário (closed_by pode ser user.id)
    user_ids = list({r["closed_by"] for r in rows if r.get("closed_by")})
    user_to_coll: Dict[str, str] = {}
    if user_ids:
        async for u in db.users.find(
            {"id": {"$in": user_ids}}, {"_id": 0, "id": 1, "collaborator_id": 1},
        ):
            if u.get("collaborator_id"):
                user_to_coll[u["id"]] = u["collaborator_id"]

    # Agrega por colaborador
    agg: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        # Usa assigned_collaborator_id primeiro (mais confiável), depois mapeia closed_by
        cid_t = (r.get("assigned_collaborator_id")
                 or user_to_coll.get(r.get("closed_by"))
                 or r.get("closed_by"))
        if not cid_t:
            continue
        before = float(r["signal_at_open"]["rx_dbm"])
        after = float(r["signal_at_close"]["rx_dbm"])
        delta = after - before
        is_los = after <= los_thr
        if is_los:
            grade = "ruim"
        elif delta < -deg_thr:
            grade = "ruim"
        elif delta < 0:
            grade = "regular"
        else:
            grade = "bom"
        bucket = agg.setdefault(cid_t, {
            "collaborator_id": cid_t,
            "name": None,
            "total": 0, "bom": 0, "regular": 0, "ruim": 0,
            "sum_delta": 0.0, "deltas": [],
        })
        bucket["total"] += 1
        bucket[grade] += 1
        bucket["sum_delta"] += delta
        bucket["deltas"].append(delta)

    # Enriquece com nome do técnico
    coll_ids = list(agg.keys())
    if coll_ids:
        async for c in db.collaborators.find(
            {"id": {"$in": coll_ids}}, {"_id": 0, "id": 1, "name": 1},
        ):
            if c["id"] in agg:
                agg[c["id"]]["name"] = c.get("name")

    # Score: % bom (peso 70) + % melhoria média (peso 30 — normalizado por delta médio até +3dB)
    items = []
    for cid_t, b in agg.items():
        total = b["total"]
        pct_bom = (b["bom"] / total * 100.0) if total else 0.0
        pct_ruim = (b["ruim"] / total * 100.0) if total else 0.0
        avg_delta = (b["sum_delta"] / total) if total else 0.0
        # delta_component: 0..30 conforme média de delta (cap em +3dB de melhoria)
        delta_comp = max(0.0, min(30.0, ((avg_delta + 3.0) / 6.0) * 30.0))
        score = round(pct_bom * 0.7 + delta_comp, 1)
        items.append({
            "collaborator_id": cid_t,
            "name": b["name"] or "Sem nome",
            "total_reparos": total,
            "bom": b["bom"],
            "regular": b["regular"],
            "ruim": b["ruim"],
            "pct_bom": round(pct_bom, 1),
            "pct_ruim": round(pct_ruim, 1),
            "avg_delta_db": round(avg_delta, 2),
            "quality_score": score,
        })

    items.sort(key=lambda x: (-x["quality_score"], -x["total_reparos"]))
    return {
        "days": days,
        "total_reparos": sum(i["total_reparos"] for i in items),
        "technicians_count": len(items),
        "items": items,
        "config": {
            "degradation_threshold_db": deg_thr,
            "los_threshold_dbm": los_thr,
        },
    }


# -------------------------------------------------------------------------
# DESTRUTIVO — apaga TODAS as bolhas da empresa.
# Restrito a auditor (papel responsável por compliance/limpeza geral).
# Apaga inclusive notas em execução — é lei.
# -------------------------------------------------------------------------
@router.post("/lousa/tickets/wipe-all")
async def wipe_all_tickets(payload: dict = None,
                           user: dict = Depends(get_current_user)):
    if user.get("role") != "auditor":
        raise HTTPException(403, "Apenas auditor pode apagar todas as bolhas.")
    confirm = (payload or {}).get("confirm")
    if confirm != "APAGAR TUDO":
        raise HTTPException(400, "Para confirmar, envie {confirm: 'APAGAR TUDO'}.")
    cid = user.get("company_id") or "co-demo"
    res = await db.tickets.delete_many({"company_id": cid})
    await db.lousa_logs.insert_one({
        "id": f"wipe-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "action": "wipe_all_tickets",
        "user_email": user.get("email"),
        "user_name": user.get("name"),
        "deleted_count": res.deleted_count,
        "created_at": now_iso(),
    })
    logger.warning("[lousa] WIPE-ALL by auditor=%s deleted=%d", user.get("email"), res.deleted_count)
    return {"ok": True, "deleted_count": res.deleted_count}


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


    for item in payload.items:
        t = by_id[item.id]
        if t["priority"] == "normal" and item.id not in locked_ids:
            await db.tickets.update_one({"id": item.id}, {"$set": {"position": item.position}})
    return {"ok": True}


# -------------------------------------------------------------------------
# SmartOLT signal lookup por ticket (lazy — só quando user abre o modal)
# -------------------------------------------------------------------------
@router.get("/lousa/tickets/{ticket_id}/signal")
async def get_ticket_signal(ticket_id: str,
                              refresh: bool = False,
                              user: dict = Depends(require_role("gestor"))):
    """Retorna sinal SmartOLT da ONU correspondente ao cliente da bolha.

    - `refresh=true` força chamada live na SmartOLT (respeitando cache TTL).
    - Resposta sempre tem `match_strategy` (pppoe/name/none) para a UI.
    """
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    snap = t.get("client_snapshot") or {}
    pppoe = (snap.get("pppoe_user") or "").strip()
    name = (snap.get("name") or "").strip()
    if not pppoe and not name:
        return {"found": False, "reason": "missing_pppoe_and_name", "snap": snap}
    try:
        from routes.smartolt import resolve_signal_for_ticket, get_onu_signal_live
    except ImportError:
        return {"found": False, "reason": "smartolt_module_missing"}
    onu = await resolve_signal_for_ticket(t)
    if not onu:
        return {"found": False, "reason": "no_match", "pppoe": pppoe, "name": name}
    strategy = "pppoe" if pppoe else "name"
    if refresh:
        try:
            live = await get_onu_signal_live(onu["unique_external_id"], user=user)
            return {"found": True, "match_strategy": strategy, **live}
        except HTTPException:
            pass
        except Exception as e:
            return {"found": True, "match_strategy": strategy, "cached": True,
                    "onu": onu, "warning": f"refresh_failed: {e}"}
    return {"found": True, "match_strategy": strategy, "cached": True, "onu": onu}


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
    # Token de autorização emitido pelo gestor quando block_bad_signal está ON
    # e o técnico precisa fechar com sinal abaixo do threshold.
    bad_signal_auth_id: Optional[str] = None


@router.post("/lousa/public/tickets/{ticket_id}/open")
async def public_open_ticket(ticket_id: str, payload: PublicOpenIn,
                                request: Request = None):
    cid = payload.collaborator_id
    # Modo "teste admin": admin/auditor logado pode abrir bolha de qualquer
    # colaborador (impersonifica). Detecta via JWT no header.
    is_admin_test = False
    try:
        auth_header = (request.headers.get("authorization") or "") if request else ""
        if auth_header.lower().startswith("bearer "):
            from auth import decode_token
            payload_jwt = decode_token(auth_header.split(" ", 1)[1].strip())
            if payload_jwt and payload_jwt.get("role") in ("administrador", "auditor"):
                is_admin_test = True
    except Exception:
        is_admin_test = False

    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0, "clock_in_enabled": 1})
    clock_in_enabled = bool((coll or {}).get("clock_in_enabled", True))
    if clock_in_enabled and not is_admin_test:
        state = await _today_clock_state(cid)
        if not state["has_entrada"]:
            raise HTTPException(412, "Bata o ponto de Entrada antes de abrir uma nota")
        if state["in_intervalo"]:
            raise HTTPException(412, "Você está em intervalo — bata Fim intervalo antes")
        if state["ended_day"]:
            raise HTTPException(412, "Você já bateu a Saída do dia")

    if not is_admin_test:
        other = await _has_active_ticket(cid)
        if other and other["id"] != ticket_id:
            raise HTTPException(409, f"Finalize a nota atual antes: {other['client_snapshot']['name']}")

    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    # No modo normal, valida que a nota pertence ao colaborador
    if (not is_admin_test) and t.get("assigned_collaborator_id") != cid:
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
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0, "name": 1, "company_id": 1})
    await _log_ticket_action(
        ticket_id=ticket_id, action="aberta",
        actor_id=cid, actor_name=(coll or {}).get("name", "Técnico"),
        actor_role="colaborador",
        details=f"Iniciou atendimento de {t['client_snapshot']['name']}",
        company_id=t.get("company_id") or DEMO_COMPANY_ID,
    )
    # Bridge Estoque ↔ Lousa: cria OS de estoque automaticamente (parte b)
    try:
        from routes.stok import auto_open_service_for_ticket
        full_t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
        await auto_open_service_for_ticket(full_t)
    except Exception as e:
        # Sync best-effort — não derruba abertura da bolha se estoque falhar
        logger.warning("[lousa] auto_open_service_for_ticket falhou: %s", e)
    return await db.tickets.find_one({"id": ticket_id}, {"_id": 0})


@router.post("/lousa/public/tickets/{ticket_id}/finalize")
async def public_finalize_ticket(ticket_id: str, payload: PublicFinalizeIn,
                                    request: Request = None):
    cid = payload.collaborator_id
    # Modo "teste admin": admin/auditor pode finalizar nota de qualquer cid
    is_admin_test = False
    try:
        auth_header = (request.headers.get("authorization") or "") if request else ""
        if auth_header.lower().startswith("bearer "):
            from auth import decode_token
            payload_jwt = decode_token(auth_header.split(" ", 1)[1].strip())
            if payload_jwt and payload_jwt.get("role") in ("administrador", "auditor"):
                is_admin_test = True
    except Exception:
        is_admin_test = False
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    if (not is_admin_test) and t.get("assigned_collaborator_id") != cid:
        raise HTTPException(404, "Nota não encontrada")
    if t["status"] != "aberta":
        raise HTTPException(400, "Somente notas abertas podem ser finalizadas")
    cd = payload.completion_data
    # Wizard 2-passos (iter89+) coleta foto do equipamento (obrigatória) + opcional foto
    # da etiqueta (OCR SN/MAC). Mínimo passa a ser 1 foto — front já bloqueia avanço sem
    # ela via photo-required-modal.
    if t["type"] == "instalacao" and len(cd.fotos) < 1:
        raise HTTPException(400, "Instalação exige pelo menos 1 foto do equipamento")
    if t["type"] == "instalacao" and not cd.ont:
        raise HTTPException(400, "ONT é obrigatório para instalação")

    company_id = t.get("company_id") or DEMO_COMPANY_ID

    # === CENTRAL_ONT: validação de sinal ruim + autorização ===
    cfg = await db.central_ont_settings.find_one(
        {"company_id": company_id}, {"_id": 0},
    ) or {}
    threshold = float(cfg.get("bad_signal_threshold", -27.0))
    block_enabled = bool(cfg.get("block_bad_signal_close", False))
    is_bad_signal = cd.sinal is not None and cd.sinal < threshold

    auth_used = None
    if is_bad_signal and block_enabled:
        if not payload.bad_signal_auth_id:
            # Cria uma request pending automaticamente
            req_id = f"bsa-{uuid.uuid4().hex[:10]}"
            await db.bad_signal_auth_requests.insert_one({
                "id": req_id,
                "company_id": company_id,
                "ticket_id": ticket_id,
                "collaborator_id": cid,
                "sinal": cd.sinal,
                "threshold": threshold,
                "status": "pending",
                "requested_at": now_iso(),
                "decided_at": None, "decided_by": None,
                "expires_at": (datetime.now(timezone.utc)
                                 + timedelta(minutes=30)).isoformat(),
            })
            coll = await db.collaborators.find_one(
                {"id": cid}, {"_id": 0, "name": 1})
            await _create_notification(
                type_="bad_signal_auth_request",
                title="🟡 Pedido de autorização — sinal ruim",
                message=(
                    f"{(coll or {}).get('name','Técnico')} pediu autorização "
                    f"para fechar {t['client_snapshot'].get('name','—')} "
                    f"com sinal {cd.sinal:.1f} dBm (limite {threshold})."
                ),
                collaborator_id=cid, ticket_id=ticket_id,
                company_id=company_id, severity="warning",
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "needs_bad_signal_auth",
                    "message": (
                        f"Sinal de {cd.sinal:.1f} dBm abaixo do limite "
                        f"({threshold} dBm). Autorização do gestor foi solicitada."
                    ),
                    "request_id": req_id,
                    "threshold": threshold,
                    "sinal": cd.sinal,
                },
            )
        # Valida o token de autorização
        auth = await db.bad_signal_auth_requests.find_one(
            {"id": payload.bad_signal_auth_id, "company_id": company_id,
             "ticket_id": ticket_id, "collaborator_id": cid}, {"_id": 0},
        )
        if not auth:
            raise HTTPException(400,
                                  "Autorização inválida — peça uma nova ao gestor.")
        if auth.get("status") != "approved":
            raise HTTPException(
                400,
                f"Autorização ainda não aprovada (status={auth.get('status')}).",
            )
        try:
            exp = datetime.fromisoformat(
                (auth.get("expires_at") or "").replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp:
                await db.bad_signal_auth_requests.update_one(
                    {"id": auth["id"]}, {"$set": {"status": "expired"}})
                raise HTTPException(400, "Autorização expirada — peça uma nova.")
        except HTTPException:
            raise
        except Exception:
            pass
        auth_used = auth["id"]
        # marca como consumido
        await db.bad_signal_auth_requests.update_one(
            {"id": auth["id"]},
            {"$set": {"status": "used", "used_at": now_iso()}},
        )

    # === SN mismatch (somente warning, não bloqueia) ===
    sn_mismatch = None
    if cd.ont and t.get("live_signal", {}).get("sn"):
        # live_signal pode não ter sido enriquecido — re-enriquece on-demand
        pass
    # Buscar SN da SmartOLT pelo PPPoE
    try:
        from routes.smartolt import enrich_tickets_with_live_signal
        t_for_sn = dict(t)
        await enrich_tickets_with_live_signal([t_for_sn], company_id)
        smartolt_sn = (t_for_sn.get("live_signal") or {}).get("sn")
        if (cd.ont and smartolt_sn
                and cd.ont.upper().replace(":", "")
                != smartolt_sn.upper().replace(":", "")):
            sn_mismatch = {"smartolt_sn": smartolt_sn, "typed_sn": cd.ont}
    except Exception:
        pass

    # === Anexa resumo dos pings feitos para essa bolha ===
    # Se houve ping → resumo (RTT, loss, alive); se não houve → marca como
    # "NÃO FOI REALIZADO". Vai pro completion_data.ping_summary (texto).
    try:
        from routes.network_diag import build_close_ping_summary
        ping_summary = await build_close_ping_summary(
            ticket_id, opened_at=t.get("opened_at"),
        )
    except Exception as e:
        logger.info("[lousa] build_close_ping_summary skip: %s", e)
        ping_summary = "🛰 Teste de ping: NÃO FOI REALIZADO durante o atendimento."

    cd_dump = cd.model_dump()
    cd_dump["ping_summary"] = ping_summary
    # Também anexa no observations/laudo se já existir, agregando ao texto
    obs_field = cd_dump.get("observations") or cd_dump.get("laudo") or ""
    cd_dump["observations"] = (
        (obs_field.rstrip() + "\n\n" + ping_summary)
        if obs_field else ping_summary
    )

    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {
            "status": "finalizada", "outcome": payload.outcome,
            "closed_at": now_iso(), "closed_by": cid,
            "close_location": {"latitude": payload.latitude, "longitude": payload.longitude},
            "completion_data": cd_dump,
            "central_ont": {
                "sinal": cd.sinal,
                "is_bad_signal": is_bad_signal,
                "threshold": threshold,
                "auth_used": auth_used,
                "sn_mismatch": sn_mismatch,
            },
        }},
    )
    # Vincula cliente à porta da CTO (instalação)
    if cd.cto_id and cd.cto_port_number:
        try:
            cs = t.get("client_snapshot") or {}
            await db.ctos.update_one(
                {
                    "id": cd.cto_id,
                    "company_id": company_id,
                    "ports.number": cd.cto_port_number,
                },
                {"$set": {
                    "ports.$.status": "used",
                    "ports.$.client_subscriber_id": cs.get("id"),
                    "ports.$.client_name": cs.get("name"),
                    "ports.$.client_pppoe": cs.get("pppoe_user") or t.get("pppoe_user"),
                    "ports.$.connected_at": now_iso(),
                    "ports.$.connected_via_ticket": ticket_id,
                }},
            )
        except Exception as e:
            logger.warning("[lousa] vínculo CTO porta falhou: %s", e)
    # Quality notes — snapshot do sinal NO FECHAMENTO (SmartOLT live, honra toggle)
    await _capture_signal_snapshot(ticket_id, company_id, "close")
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0, "name": 1})
    coll_name = (coll or {}).get("name", "Técnico")
    await _log_ticket_action(
        ticket_id=ticket_id, action="finalizada",
        actor_id=cid, actor_name=coll_name,
        actor_role="colaborador",
        details=f"ONT={cd.ont or '-'} · sinal={cd.sinal} dBm · fotos={len(cd.fotos)}",
        company_id=company_id,
    )
    # Notification de sinal ruim (sempre que o sinal for abaixo do threshold,
    # mesmo quando o block está desligado — pra o gestor monitorar)
    if is_bad_signal:
        await _create_notification(
            type_="bad_signal_close",
            title="📡 Bolha fechada com sinal alto/ruim",
            message=(
                f"{coll_name} fechou {t['client_snapshot'].get('name','—')} "
                f"com {cd.sinal:.1f} dBm (limite {threshold}). "
                + ("Autorização do gestor foi usada." if auth_used
                    else "Block desligado — fechamento permitido.")
            ),
            collaborator_id=cid, ticket_id=ticket_id,
            company_id=company_id, severity="warning",
        )
    # Bridge Estoque ↔ Lousa: AUTO-BAIXA do estoque a partir do completion_data
    try:
        from routes.stok import auto_close_service_from_ticket
        await auto_close_service_from_ticket(
            ticket_id=ticket_id,
            company_id=company_id,
            completion_data=cd.model_dump(),
            technician_id=cid,
            technician_name=coll_name,
        )
    except Exception as e:
        logger.warning("[lousa] auto_close_service_from_ticket falhou: %s", e)

    # Coaching automático — alerta quando técnico fecha N bolhas seguidas sem ping
    try:
        from services.lousa_coaching import check_ping_skip_streak
        await check_ping_skip_streak(company_id, cid, ticket_id)
    except Exception as e:
        logger.warning("[lousa] coaching check falhou: %s", e)

    # Auto-reschedule p/ Técnico de Rede se sinal degradou (honra toggle)
    try:
        await _maybe_auto_resched_degraded(ticket_id, company_id)
    except Exception as e:
        logger.warning("[lousa] auto-resched degraded falhou: %s", e)

    result = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    # Anexa warnings pra exibir no app
    result["_warnings"] = {
        "sn_mismatch": sn_mismatch,
        "bad_signal": {
            "active": is_bad_signal, "threshold": threshold,
            "sinal": cd.sinal,
        } if is_bad_signal else None,
    }
    return result


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


@router.post("/lousa/public/reorder")
async def public_reorder_tickets(payload: PublicReorderIn):
    """Mobile reorder — sem JWT, valida que o colaborador existe e os tickets pertencem a ele.
    Mesmas regras do /lousa/reorder: bolhas com priority != 'normal' ou 'travadas pela posição' não podem mudar de posição.
    """
    cid = payload.collaborator_id
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0, "id": 1})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
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
            raise HTTPException(400, f"Ticket {item.id} não pertence a este colaborador")
        is_locked = t["priority"] != "normal" or t["id"] in locked_ids
        if is_locked and item.position != raw.index(t):
            raise HTTPException(400, f"Bolha travada não pode ser movida ({t['client_snapshot']['name']})")

    for item in payload.items:
        t = by_id[item.id]
        if t["priority"] == "normal" and item.id not in locked_ids:
            await db.tickets.update_one({"id": item.id}, {"$set": {"position": item.position}})
    return {"ok": True}


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
    # Mínimo de 1 foto (wizard 2-passos enforça equip photo client-side).
    if t["type"] == "instalacao" and len(cd.fotos) < 1:
        raise HTTPException(400, "Instalação exige pelo menos 1 foto do equipamento")
    if t["type"] == "instalacao" and not cd.ont:
        raise HTTPException(400, "ONT é obrigatório para instalação")

    # Anexa resumo dos pings ao fechamento (igual ao endpoint público)
    try:
        from routes.network_diag import build_close_ping_summary
        ping_summary = await build_close_ping_summary(
            ticket_id, opened_at=t.get("opened_at"),
        )
    except Exception:
        ping_summary = "🛰 Teste de ping: NÃO FOI REALIZADO durante o atendimento."

    cd_dump = cd.model_dump()
    cd_dump["ping_summary"] = ping_summary
    obs_field = cd_dump.get("observations") or cd_dump.get("laudo") or ""
    cd_dump["observations"] = (
        (obs_field.rstrip() + "\n\n" + ping_summary)
        if obs_field else ping_summary
    )

    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {
            "status": "finalizada",
            "outcome": payload.outcome,
            "closed_at": now_iso(),
            "closed_by": user["id"],
            "close_location": {"latitude": payload.latitude, "longitude": payload.longitude},
            "completion_data": cd_dump,
        }},
    )
    # Quality notes — snapshot do sinal NO FECHAMENTO (SmartOLT live, honra toggle)
    company_id = t.get("company_id") or DEMO_COMPANY_ID
    await _capture_signal_snapshot(ticket_id, company_id, "close")
    # Auto-reschedule p/ Técnico de Rede se sinal degradou (honra toggle)
    try:
        await _maybe_auto_resched_degraded(ticket_id, company_id)
    except Exception as e:
        logger.warning("[lousa] auto-resched degraded falhou: %s", e)
    # Coaching automático — mesmo gatilho do endpoint público
    try:
        from services.lousa_coaching import check_ping_skip_streak
        await check_ping_skip_streak(company_id, cid, ticket_id)
    except Exception as e:
        logger.warning("[lousa] coaching check (auth) falhou: %s", e)
    return await db.tickets.find_one({"id": ticket_id}, {"_id": 0})


class CaptureSignalIn(BaseModel):
    moment: Literal["open", "close"] = "close"


@router.post("/lousa/tickets/{ticket_id}/capture-signal")
async def manual_capture_signal(ticket_id: str, payload: CaptureSignalIn,
                                     user: dict = Depends(get_current_user)):
    """Recaptura o sinal SmartOLT sob demanda (técnico ou gestor).

    Útil quando o técnico quer ver o sinal atual antes de fechar o chamado, ou
    quando a captura automática falhou no momento da abertura/fechamento.
    """
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    # Permissões: técnico só captura seu próprio chamado; gestor/admin sempre
    role = user.get("role")
    if role == "colaborador":
        cid = await _user_collaborator_id(user)
        if t.get("assigned_collaborator_id") != cid:
            raise HTTPException(403, "Chamado não é seu")
    company_id = t.get("company_id") or DEMO_COMPANY_ID
    if not await _quality_capture_enabled(company_id):
        raise HTTPException(
            400,
            "Captura de sinal está desligada. Peça ao administrador para ligar.",
        )
    snap = await _capture_signal_snapshot(ticket_id, company_id, payload.moment)
    if not snap:
        raise HTTPException(
            422,
            "Não foi possível ler o sinal no SmartOLT agora. "
            "Verifique se a ONU está cadastrada e online.",
        )
    return {
        "ok": True,
        "moment": payload.moment,
        "snapshot": snap,
        "captured_at": now_iso(),
    }


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
    # Persiste completion_data (fechamento interno): sinal + observações.
    # Marcado com internal_close=True para diferenciar de fechamento físico.
    if payload.action == "encerrar" and payload.completion_data:
        cd = dict(payload.completion_data)
        cd.setdefault("internal_close", True)
        update["completion_data"] = cd
    if payload.action == "reagendar":
        # aceita new_scheduled_time OU (new_date + new_time)
        sched = payload.new_scheduled_time
        if not sched and payload.new_date and payload.new_time:
            sched = f"{payload.new_date}T{payload.new_time}:00"
        if sched:
            update["scheduled_time"] = sched
            update["grid_slot"] = None
            # REGRA DE DATA: ao reagendar, a bolha PERMANECE viva (não marca
            # como resolvida). Ela some da Lousa de HOJE (filtro por dia) e
            # aparece na Lousa do dia agendado automaticamente.
            update["status"] = "pendente"
            update["closed_at"] = None  # mantém aberta no novo dia
            update["rescheduled_at"] = now_iso()
            update["rescheduled_by"] = user["id"]
            # Histórico: quantas vezes foi reagendada
            update["reschedule_count"] = int(t.get("reschedule_count") or 0) + 1
    await db.tickets.update_one({"id": ticket_id}, {"$set": update})
    await _log_ticket_action(
        ticket_id=ticket_id, action=payload.action,
        actor_id=user["id"], actor_name=user.get("name", "Gestor"),
        actor_role=user.get("role", "gestor"),
        details=payload.notes or "",
        company_id=t.get("company_id") or DEMO_COMPANY_ID,
    )
    # Notifica colaborador se ação for cancelar/reagendar — para o app do técnico atualizar
    if payload.action in ("cancelar", "reagendar"):
        client_name = (t.get("client_snapshot") or {}).get("name") or "Cliente"
        verb = "cancelada" if payload.action == "cancelar" else "reagendada"
        await _create_notification(
            type_=f"ticket_{payload.action}_by_admin",
            title=f"Nota {verb} pela gestão",
            message=f"Nota de {client_name} foi {verb} por {user.get('name', 'gestão')}. " + (payload.notes or ""),
            collaborator_id=t.get("assigned_collaborator_id"),
            ticket_id=ticket_id,
            company_id=t.get("company_id") or DEMO_COMPANY_ID,
            severity="info" if payload.action == "reagendar" else "warning",
        )
    # Push baixa para o Atlaz se a bolha veio de lá
    if t.get("atlaz_external_id"):
        try:
            from routes import atlaz as routes_atlaz
            await routes_atlaz.push_close(
                t, payload.action, payload.notes,
                update.get("scheduled_time") if payload.action == "reagendar" else None,
            )
        except Exception as e:
            logger.warning("[atlaz] push falhou para %s: %s", ticket_id, e)
    # Bridge Estoque ↔ Lousa: cancela OS associada (sem baixa de estoque) em cancel/reagendar
    if payload.action in ("cancelar", "reagendar"):
        try:
            from routes.stok import cancel_service_for_ticket
            await cancel_service_for_ticket(
                ticket_id, t.get("company_id") or DEMO_COMPANY_ID,
                reason=f"Lousa: {payload.action} — {payload.notes or ''}".strip(),
            )
        except Exception as e:
            logger.warning("[lousa] cancel_service_for_ticket falhou: %s", e)
    # Hooks de fechamento (quando gestor fecha como se fosse técnico)
    if payload.action == "encerrar" and payload.completion_data:
        try:
            company_id = t.get("company_id") or DEMO_COMPANY_ID
            await _capture_signal_snapshot(ticket_id, company_id, "close")
            await _maybe_auto_resched_degraded(ticket_id, company_id)
        except Exception as e:
            logger.warning("[lousa] admin-close hooks falharam: %s", e)
    return await db.tickets.find_one({"id": ticket_id}, {"_id": 0})


class TicketEditIn(BaseModel):
    """Edição de bolha pelo gestor/admin (qualquer campo opcional)."""
    client_name: Optional[str] = None
    address: Optional[str] = None
    neighborhood: Optional[str] = None
    phone: Optional[str] = None
    relato: Optional[str] = None
    pppoe_user: Optional[str] = None
    type: Optional[TicketType] = None
    priority: Optional[Priority] = None
    scheduled_time: Optional[str] = None


@router.patch("/lousa/tickets/{ticket_id}")
async def edit_ticket(ticket_id: str, payload: TicketEditIn,
                      user: dict = Depends(require_role("gestor"))):
    """Gestor/admin edita campos da bolha. Não permite editar nota já encerrada."""
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    if t["status"] in ("finalizada", "encerrada", "cancelada"):
        raise HTTPException(400, "Nota encerrada não pode ser editada")

    update: dict = {}
    snap = dict(t.get("client_snapshot") or {})
    snap_changed = False
    snap_fields = {"client_name": "name", "address": "address",
                   "neighborhood": "neighborhood", "phone": "phone", "relato": "relato",
                   "pppoe_user": "pppoe_user"}
    for f_in, f_snap in snap_fields.items():
        v = getattr(payload, f_in, None)
        if v is not None:
            snap[f_snap] = v
            snap_changed = True
    if snap_changed:
        update["client_snapshot"] = snap

    for f in ("type", "priority", "scheduled_time"):
        v = getattr(payload, f, None)
        if v is not None:
            update[f] = v

    # Se scheduled_time mudou, limpa grid_slot persistido para que o cálculo
    # automático no /api/lousa/grid recompute corretamente (evita slot obsoleto).
    if "scheduled_time" in update:
        update["grid_slot"] = None

    if not update:
        return t

    await db.tickets.update_one({"id": ticket_id}, {"$set": update})
    await _log_ticket_action(
        ticket_id=ticket_id, action="editada",
        actor_id=user["id"], actor_name=user.get("name", "Gestor"),
        actor_role=user.get("role", "gestor"),
        details=f"Campos: {', '.join(update.keys())}",
        company_id=t.get("company_id") or DEMO_COMPANY_ID,
    )
    return await db.tickets.find_one({"id": ticket_id}, {"_id": 0})


@router.post("/lousa/tickets/{ticket_id}/admin-open")
async def admin_open_ticket(ticket_id: str, user: dict = Depends(require_role("gestor"))):
    """Gestor/admin abre uma bolha em nome do colaborador (para casos especiais)."""
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    if t["status"] not in ("pendente",):
        raise HTTPException(400, f"Nota já está com status '{t['status']}'")
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {"status": "aberta", "opened_at": now_iso()}},
    )
    await _log_ticket_action(
        ticket_id=ticket_id, action="aberta_admin",
        actor_id=user["id"], actor_name=user.get("name", "Gestor"),
        actor_role=user.get("role", "gestor"),
        details=f"Aberta pelo gestor (não pelo técnico) — {t['client_snapshot']['name']}",
        company_id=t.get("company_id") or DEMO_COMPANY_ID,
    )
    # Bridge Estoque ↔ Lousa: cria OS de estoque automaticamente
    try:
        from routes.stok import auto_open_service_for_ticket
        full_t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
        await auto_open_service_for_ticket(full_t)
    except Exception as e:
        logger.warning("[lousa] auto_open_service_for_ticket (admin) falhou: %s", e)
    return await db.tickets.find_one({"id": ticket_id}, {"_id": 0})


# -------------------------------------------------------------------------
# ADMIN — Liberar bolha presa (botão vermelho de emergência no painel)
# -------------------------------------------------------------------------
class ReleaseStuckIn(BaseModel):
    collaborator_id: str
    reason: Optional[str] = None


@router.get("/lousa/admin/stuck-tickets")
async def list_stuck_tickets(
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Lista colaboradores que TÊM bolha em status 'aberta' AGORA — a UI
    usa pra alimentar o select do modal 'Liberar bolha'.

    Retorna 1 entrada por colaborador (com a bolha mais antiga aberta).
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cur = db.tickets.find(
        {"company_id": cid, "status": "aberta"},
        {"_id": 0, "id": 1, "assigned_collaborator_id": 1,
         "client_snapshot": 1, "opened_at": 1, "scheduled_time": 1,
         "type": 1, "priority": 1},
    ).sort("opened_at", 1)
    items_by_collab: Dict[str, Dict[str, Any]] = {}
    async for t in cur:
        col_id = t.get("assigned_collaborator_id")
        if not col_id:
            continue
        # mantém só a mais antiga (1ª iteração devido ao sort)
        items_by_collab.setdefault(col_id, t)

    if not items_by_collab:
        return {"items": []}

    coll_docs = await db.collaborators.find(
        {"id": {"$in": list(items_by_collab.keys())}},
        {"_id": 0, "id": 1, "name": 1, "phone": 1},
    ).to_list(500)
    coll_by_id = {c["id"]: c for c in coll_docs}

    items: List[Dict[str, Any]] = []
    for col_id, t in items_by_collab.items():
        c = coll_by_id.get(col_id) or {}
        opened_at = t.get("opened_at")
        minutes_stuck = None
        if opened_at:
            try:
                ot = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
                minutes_stuck = round(
                    (datetime.now(timezone.utc) - ot).total_seconds() / 60.0, 1
                )
            except Exception:
                pass
        items.append({
            "collaborator_id": col_id,
            "collaborator_name": c.get("name") or col_id,
            "ticket_id": t["id"],
            "client_name": (t.get("client_snapshot") or {}).get("name") or "—",
            "client_address": (t.get("client_snapshot") or {}).get("address") or "",
            "opened_at": opened_at,
            "minutes_stuck": minutes_stuck,
            "type": t.get("type"),
            "priority": t.get("priority"),
        })
    # Ordena: mais tempo presa primeiro
    items.sort(key=lambda x: (x.get("minutes_stuck") or 0), reverse=True)
    return {"items": items}


@router.post("/lousa/admin/release-stuck")
async def release_stuck_ticket(
    payload: ReleaseStuckIn,
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Botão vermelho — libera UMA bolha presa do colaborador.

    Mecânica:
      • Acha a bolha mais antiga em status 'aberta' do colaborador escolhido
      • Reseta status → 'pendente', limpa opened_at + whatsapp_status
      • Loga ação 'liberada_admin' com quem clicou (auditoria)
      • Cria notification 'bolha_liberada_admin' (severidade critical) pros
        outros admins/gestores verem a ação
      • Retorna a bolha liberada
      • Se houver outras presas, é necessário CLICAR DE NOVO (1 por vez)
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    col_id = payload.collaborator_id

    # 1) Acha a bolha mais antiga 'aberta' do colaborador
    t = await db.tickets.find_one(
        {"company_id": cid, "assigned_collaborator_id": col_id,
         "status": "aberta"},
        {"_id": 0},
        sort=[("opened_at", 1)],
    )
    if not t:
        raise HTTPException(
            404, "Nenhuma bolha presa encontrada para este colaborador.",
        )

    # 2) Reset status pra pendente + limpa marcas de execução
    await db.tickets.update_one(
        {"id": t["id"]},
        {
            "$set": {"status": "pendente"},
            "$unset": {
                "opened_at": "", "whatsapp_status": "",
                "whatsapp_last_message": "",
            },
        },
    )

    # 3) Auditoria — quem clicou
    coll_doc = await db.collaborators.find_one(
        {"id": col_id}, {"_id": 0, "name": 1},
    )
    col_name = (coll_doc or {}).get("name") or col_id
    actor_name = user.get("name") or user.get("email") or user["id"]
    client_name = (t.get("client_snapshot") or {}).get("name") or "—"

    await _log_ticket_action(
        ticket_id=t["id"], action="liberada_admin",
        actor_id=user["id"], actor_name=actor_name,
        actor_role=user.get("role", "administrador"),
        details=(
            f"Bolha liberada (presa) — técnico: {col_name} · "
            f"cliente: {client_name}"
            + (f" · motivo: {payload.reason}" if payload.reason else "")
        ),
        company_id=cid,
    )

    # 4) Notification crítica pros admins
    await _create_notification(
        type_="bolha_liberada_admin",
        title="🚨 Bolha liberada manualmente",
        message=(
            f"{actor_name} liberou a bolha de {client_name} do técnico "
            f"{col_name}. A bolha voltou para 'pendente'."
            + (f" Motivo: {payload.reason}." if payload.reason else "")
        ),
        collaborator_id=col_id,
        ticket_id=t["id"],
        company_id=cid,
        severity="critical",
    )

    freed = await db.tickets.find_one({"id": t["id"]}, {"_id": 0})
    return {
        "ok": True,
        "freed_ticket": freed,
        "collaborator_id": col_id,
        "collaborator_name": col_name,
    }


# -------------------------------------------------------------------------
# CENTRAL_ONT — controle de fechamento com sinal ruim + relatórios
# -------------------------------------------------------------------------
class CentralOntSettingsIn(BaseModel):
    block_bad_signal_close: bool = False
    bad_signal_threshold: float = -27.0


@router.get("/lousa/central-ont/settings")
async def get_central_ont_settings(
    user: dict = Depends(require_role("administrador", "gestor")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.central_ont_settings.find_one(
        {"company_id": cid}, {"_id": 0},
    ) or {}
    return {
        "block_bad_signal_close": bool(doc.get("block_bad_signal_close", False)),
        "bad_signal_threshold": float(doc.get("bad_signal_threshold", -27.0)),
        "updated_at": doc.get("updated_at"),
        "updated_by": doc.get("updated_by"),
    }


@router.put("/lousa/central-ont/settings")
async def put_central_ont_settings(
    payload: CentralOntSettingsIn,
    user: dict = Depends(require_role("administrador", "gestor")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    await db.central_ont_settings.update_one(
        {"company_id": cid},
        {"$set": {
            "company_id": cid,
            "block_bad_signal_close": payload.block_bad_signal_close,
            "bad_signal_threshold": payload.bad_signal_threshold,
            "updated_by": user.get("email") or user.get("id"),
            "updated_at": now_iso(),
        }},
        upsert=True,
    )
    return {"ok": True}


@router.get("/lousa/central-ont/report")
async def central_ont_report(
    days: int = Query(default=30, ge=1, le=365),
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Relatório de notas finalizadas com sinal ruim nos últimos N dias.

    Retorna:
      - total_closes              → total geral de finalizações no período
      - bad_signal_closes         → total com sinal abaixo do threshold
      - per_collaborator          → lista (técnico → total, bad, ratio)
      - items                     → lista de notas com sinal ruim (até 200)
      - settings                  → settings atuais (threshold + block)
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    cfg_doc = await db.central_ont_settings.find_one(
        {"company_id": cid}, {"_id": 0},
    ) or {}
    threshold = float(cfg_doc.get("bad_signal_threshold", -27.0))
    block_enabled = bool(cfg_doc.get("block_bad_signal_close", False))

    # Buscar todas as finalizações
    cur = db.tickets.find(
        {"company_id": cid, "status": "finalizada",
         "closed_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1, "closed_at": 1, "closed_by": 1,
         "assigned_collaborator_id": 1, "client_snapshot": 1,
         "completion_data": 1, "central_ont": 1, "type": 1,
         "outcome": 1},
    )
    total = 0
    bad_items: List[Dict[str, Any]] = []
    per_col: Dict[str, Dict[str, Any]] = {}
    async for t in cur:
        total += 1
        col_id = t.get("closed_by") or t.get("assigned_collaborator_id") or "?"
        per_col.setdefault(col_id, {"total": 0, "bad": 0})
        per_col[col_id]["total"] += 1
        sinal = ((t.get("central_ont") or {}).get("sinal")
                  or (t.get("completion_data") or {}).get("sinal"))
        if sinal is not None:
            try:
                sf = float(sinal)
                if sf < threshold:
                    per_col[col_id]["bad"] += 1
                    bad_items.append({
                        "ticket_id": t["id"],
                        "client_name": (t.get("client_snapshot") or {}).get("name"),
                        "address": (t.get("client_snapshot") or {}).get("address"),
                        "closed_at": t.get("closed_at"),
                        "collaborator_id": col_id,
                        "sinal": sf,
                        "outcome": t.get("outcome"),
                        "type": t.get("type"),
                        "ont": (t.get("completion_data") or {}).get("ont"),
                        "auth_used": (t.get("central_ont")
                                       or {}).get("auth_used"),
                    })
            except (TypeError, ValueError):
                pass

    # Resolve nomes dos colabs
    if per_col or bad_items:
        ids = list({*per_col.keys(),
                    *(b["collaborator_id"] for b in bad_items)})
        coll_docs = await db.collaborators.find(
            {"id": {"$in": ids}}, {"_id": 0, "id": 1, "name": 1},
        ).to_list(500)
        name_by_id = {c["id"]: c.get("name", c["id"]) for c in coll_docs}
    else:
        name_by_id = {}

    per_col_list = []
    for col_id, agg in per_col.items():
        total_c = agg["total"]
        bad_c = agg["bad"]
        per_col_list.append({
            "collaborator_id": col_id,
            "collaborator_name": name_by_id.get(col_id, col_id),
            "total_closes": total_c,
            "bad_signal_closes": bad_c,
            "ratio": round(bad_c / total_c, 4) if total_c else 0.0,
            "ratio_pct": round((bad_c / total_c) * 100, 1) if total_c else 0.0,
        })
    per_col_list.sort(key=lambda x: x["bad_signal_closes"], reverse=True)

    # Decora bad_items com nome
    for b in bad_items:
        b["collaborator_name"] = name_by_id.get(b["collaborator_id"],
                                                 b["collaborator_id"])
    bad_items.sort(key=lambda b: (b.get("closed_at") or ""), reverse=True)

    total_bad = sum(c["bad_signal_closes"] for c in per_col_list)

    return {
        "period_days": days,
        "threshold": threshold,
        "block_enabled": block_enabled,
        "total_closes": total,
        "bad_signal_closes": total_bad,
        "overall_ratio_pct": round((total_bad / total) * 100, 1) if total else 0.0,
        "per_collaborator": per_col_list,
        "items": bad_items[:200],
    }


# Autorizações pendentes (gestor decide)
@router.get("/lousa/central-ont/auth-requests")
async def list_auth_requests(
    status: Optional[str] = Query(default=None),
    user: dict = Depends(require_role("administrador", "gestor")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if status:
        q["status"] = status
    cur = db.bad_signal_auth_requests.find(q, {"_id": 0}) \
        .sort("requested_at", -1).limit(100)
    items = [d async for d in cur]
    if items:
        coll_ids = list({i["collaborator_id"] for i in items
                          if i.get("collaborator_id")})
        coll_docs = await db.collaborators.find(
            {"id": {"$in": coll_ids}}, {"_id": 0, "id": 1, "name": 1},
        ).to_list(500)
        name_by_id = {c["id"]: c.get("name", c["id"]) for c in coll_docs}
        for i in items:
            i["collaborator_name"] = name_by_id.get(
                i.get("collaborator_id"), i.get("collaborator_id") or "—")
            # adiciona client name
            t = await db.tickets.find_one(
                {"id": i.get("ticket_id")},
                {"_id": 0, "client_snapshot": 1},
            )
            i["client_name"] = ((t or {}).get("client_snapshot") or
                                  {}).get("name") or "—"
    return {"items": items}


@router.post("/lousa/central-ont/auth-requests/{req_id}/approve")
async def approve_auth_request(
    req_id: str,
    user: dict = Depends(require_role("administrador", "gestor")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    req = await db.bad_signal_auth_requests.find_one(
        {"id": req_id, "company_id": cid}, {"_id": 0},
    )
    if not req:
        raise HTTPException(404, "Solicitação não encontrada")
    if req["status"] != "pending":
        raise HTTPException(400, f"Status atual: {req['status']}")
    await db.bad_signal_auth_requests.update_one(
        {"id": req_id},
        {"$set": {
            "status": "approved",
            "decided_at": now_iso(),
            "decided_by": user.get("email") or user.get("id"),
        }},
    )
    return {"ok": True, "status": "approved"}


@router.post("/lousa/central-ont/auth-requests/{req_id}/reject")
async def reject_auth_request(
    req_id: str,
    user: dict = Depends(require_role("administrador", "gestor")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    res = await db.bad_signal_auth_requests.update_one(
        {"id": req_id, "company_id": cid, "status": "pending"},
        {"$set": {
            "status": "rejected",
            "decided_at": now_iso(),
            "decided_by": user.get("email") or user.get("id"),
        }},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Solicitação não encontrada ou já decidida")
    return {"ok": True, "status": "rejected"}


# Polling endpoint público (técnico checa o status sem JWT)
@router.get("/lousa/public/bad-signal-auth/{req_id}")
async def public_check_auth_status(req_id: str):
    req = await db.bad_signal_auth_requests.find_one(
        {"id": req_id}, {"_id": 0, "id": 1, "status": 1,
                          "decided_at": 1, "expires_at": 1, "sinal": 1,
                          "threshold": 1},
    )
    if not req:
        raise HTTPException(404, "Solicitação não encontrada")
    return req


# -------------------------------------------------------------------------
# OCR — lê SN/MAC de uma foto via Gemini Vision (Emergent LLM Key)
# -------------------------------------------------------------------------
class OcrSnIn(BaseModel):
    image_base64: str  # data URL ou raw base64
    hint: Optional[str] = None  # "SN", "MAC", "ONT" — guia a IA


@router.post("/lousa/public/ocr-sn")
async def public_ocr_sn(payload: OcrSnIn):
    """Extrai número de série/MAC de uma foto da etiqueta do equipamento.

    Best-effort: usa Gemini 2.5 Flash (Nano Banana) com prompt focado em ler
    etiquetas de ONT/ONU. Retorna {sn, mac, raw, confidence}. Endpoint público
    porque o app do colaborador é stateless (token via ?cid=).
    """
    import base64
    import os
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        raise HTTPException(503,
                              "EMERGENT_LLM_KEY não configurada — OCR indisponível.")
    raw = payload.image_base64 or ""
    if raw.startswith("data:"):
        try:
            raw = raw.split(",", 1)[1]
        except Exception:
            pass
    if not raw or len(raw) < 100:
        raise HTTPException(400, "Imagem inválida ou muito pequena.")
    # Cap em ~4MB pra não estourar
    try:
        decoded = base64.b64decode(raw)
        if len(decoded) > 4 * 1024 * 1024:
            raise HTTPException(400, "Imagem maior que 4MB.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "Falha decodificando base64.") from None

    try:
        from emergentintegrations.llm.chat import (
            ImageContent, LlmChat, UserMessage,
        )
    except Exception as e:
        raise HTTPException(503,
                              f"emergentintegrations indisponível: {e}") from e

    system = (
        "Você é um leitor de etiquetas de ONT/ONU (fibra óptica). "
        "Receba uma foto de etiqueta de equipamento e extraia o "
        "SERIAL NUMBER (SN) e o MAC ADDRESS quando aparecerem. "
        "Padrões comuns: SN começa com letras do fabricante (FHTT, HWTC, "
        "TPLG, etc.) seguidos de hex. MAC tem 12 hex separados ou não por ':'. "
        "Responda APENAS em JSON: {\"sn\":\"...\", \"mac\":\"...\", "
        "\"confidence\":\"alta|media|baixa\", \"raw_text\":\"...\"}. "
        "Use null quando não detectar."
    )
    chat = LlmChat(
        api_key=key, session_id=f"ocr-sn-{uuid.uuid4().hex[:8]}",
        system_message=system,
    ).with_model("gemini", "gemini-2.5-flash")
    user_msg = UserMessage(
        text=("Leia a etiqueta. Hint do usuário: "
              + (payload.hint or "SN/MAC de ONT")),
        file_contents=[ImageContent(image_base64=raw)],
    )
    try:
        resp = await chat.send_message(user_msg)
    except Exception as e:
        logger.exception("[lousa] ocr-sn LLM falhou: %s", e)
        raise HTTPException(502, f"OCR falhou: {e}") from e

    txt = (resp or "").strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```(?:json)?\s*", "", txt)
        txt = re.sub(r"\s*```\s*$", "", txt)
    try:
        m = re.search(r"\{.*\}", txt, flags=re.S)
        parsed = json.loads(m.group(0)) if m else {}
    except Exception:
        parsed = {}
    # Limpa SN/MAC (sem espaços, uppercase)
    sn = (parsed.get("sn") or "").strip().upper().replace(" ", "")
    mac_raw = (parsed.get("mac") or "").strip().upper().replace(" ", "")
    # Normaliza MAC removendo separadores extras
    mac = "".join(c for c in mac_raw if c in "0123456789ABCDEF")
    if len(mac) == 12:
        mac = ":".join(mac[i:i+2] for i in range(0, 12, 2))
    else:
        mac = mac_raw  # devolve cru se não bateu 12 hex

    return {
        "sn": sn or None,
        "mac": mac or None,
        "confidence": parsed.get("confidence") or "baixa",
        "raw_text": parsed.get("raw_text") or "",
        "best": sn or mac or None,
    }


# -------------------------------------------------------------------------
# Sugestão de insumos IA — mediana histórica por tipo+bairro
# -------------------------------------------------------------------------
class SuggestSuppliesIn(BaseModel):
    ticket_id: Optional[str] = None
    type: Optional[str] = None  # instalacao | retirada | suporte | troca_endereco
    neighborhood: Optional[str] = None
    company_id: Optional[str] = None


def _median(values: list[float]) -> float:
    vals = sorted([float(v) for v in values if v is not None])
    if not vals:
        return 0.0
    mid = len(vals) // 2
    if len(vals) % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2.0


@router.post("/lousa/public/suggest-supplies")
async def suggest_supplies(payload: SuggestSuppliesIn):
    """Sugere quantidades de insumos baseado em chamados finalizados similares.

    Estratégia: agrega últimas N notas finalizadas do MESMO tipo, prioriza
    mesmo bairro quando disponível, computa MEDIANA por insumo. Fallback para
    defaults sãos se histórico < 3.
    """
    ttype = payload.type
    if not ttype and payload.ticket_id:
        t = await db.tickets.find_one(
            {"id": payload.ticket_id}, {"_id": 0, "type": 1, "client_snapshot": 1,
                                          "company_id": 1},
        )
        if t:
            ttype = t.get("type")
            if not payload.neighborhood:
                payload.neighborhood = (t.get("client_snapshot") or {}).get("neighborhood")
            if not payload.company_id:
                payload.company_id = t.get("company_id")

    company_id = payload.company_id or DEMO_COMPANY_ID
    ttype = ttype or "instalacao"
    bairro = (payload.neighborhood or "").strip()

    # Defaults conservadores por tipo
    DEFAULTS = {
        "instalacao": {
            "qtd_drop": 80, "esticadores": 2, "conectores_fast": 2,
            "cabo_rede": 8, "conectores_rede": 2,
        },
        "troca_endereco": {
            "qtd_drop": 80, "esticadores": 2, "conectores_fast": 2,
            "cabo_rede": 8, "conectores_rede": 2,
        },
        "retirada": {
            "qtd_drop": 0, "esticadores": 0, "conectores_fast": 0,
            "cabo_rede": 0, "conectores_rede": 0,
        },
        "suporte": {
            "qtd_drop": 20, "esticadores": 1, "conectores_fast": 1,
            "cabo_rede": 3, "conectores_rede": 1,
        },
    }
    base = DEFAULTS.get(ttype, DEFAULTS["suporte"])

    # Busca histórico — mesmo bairro primeiro, senão empresa-wide
    base_query = {
        "company_id": company_id,
        "type": ttype,
        "status": "finalizada",
        "completion_data": {"$exists": True},
    }
    historical = []
    source = "defaults"
    if bairro:
        cursor = db.tickets.find(
            {**base_query, "client_snapshot.neighborhood": bairro},
            {"_id": 0, "completion_data": 1, "closed_at": 1},
        ).sort("closed_at", -1).limit(30)
        historical = [doc async for doc in cursor]
        if len(historical) >= 3:
            source = f"bairro:{bairro}"

    if len(historical) < 3:
        cursor = db.tickets.find(
            base_query, {"_id": 0, "completion_data": 1, "closed_at": 1},
        ).sort("closed_at", -1).limit(30)
        historical = [doc async for doc in cursor]
        if len(historical) >= 3:
            source = "empresa"

    if len(historical) < 3:
        return {
            "qtd_drop": base["qtd_drop"],
            "esticadores": base["esticadores"],
            "conectores_fast": base["conectores_fast"],
            "cabo_rede": base["cabo_rede"],
            "conectores_rede": base["conectores_rede"],
            "sample_size": len(historical),
            "source": "defaults",
            "rationale": (
                f"Sem histórico suficiente para {ttype}"
                + (f" em {bairro}" if bairro else "")
                + " — usando padrão conservador."
            ),
        }

    # Computa medianas
    cd_list = [h.get("completion_data") or {} for h in historical]
    suggested = {
        "qtd_drop": round(_median([c.get("qtd_drop", 0) for c in cd_list])),
        "esticadores": round(_median([c.get("esticadores", 0) for c in cd_list])),
        "conectores_fast": round(_median([c.get("conectores_fast", 0) for c in cd_list])),
        "cabo_rede": round(_median([c.get("cabo_rede", 0) for c in cd_list]) * 2) / 2,
        "conectores_rede": round(_median([c.get("conectores_rede", 0) for c in cd_list])),
    }
    label = "bairro" if source.startswith("bairro:") else "empresa"
    return {
        **suggested,
        "sample_size": len(historical),
        "source": source,
        "rationale": (
            f"Baseado na mediana de {len(historical)} {ttype}s "
            f"finalizadas recentes ({label}"
            + (f" — {bairro}" if source.startswith("bairro:") else "") + ")."
        ),
    }


# -------------------------------------------------------------------------
# Performance do técnico — card de gamificação suave no app do colaborador
# -------------------------------------------------------------------------
@router.get("/lousa/public/tech-performance/{cid}")
async def get_tech_performance(cid: str):
    """KPIs do dia + ranking entre técnicos da mesma empresa.

    Retorna closed_today, success_rate, avg_minutes, rank, total_techs, badge,
    streak (dias consecutivos com >=1 fechada). Endpoint público — usa cid como
    chave (mesmo padrão do resto do app do colaborador).
    """
    col = await db.collaborators.find_one({"id": cid}, {"_id": 0, "company_id": 1})
    if not col:
        raise HTTPException(404, "Colaborador não encontrado")
    company_id = col.get("company_id") or DEMO_COMPANY_ID

    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_iso = day_start.isoformat()
    next_day_iso = (day_start + timedelta(days=1)).isoformat()

    # Notas do técnico no dia
    my_closed = await db.tickets.find(
        {
            "assigned_collaborator_id": cid,
            "status": "finalizada",
            "closed_at": {"$gte": day_start_iso, "$lt": next_day_iso},
        },
        {"_id": 0, "opened_at": 1, "closed_at": 1, "outcome": 1, "type": 1},
    ).to_list(length=200)
    closed_today = len(my_closed)

    # Gamificação por pontos:
    #   reparo/suporte = 1pt, retirada = 1.5pt, instalacao = 3pt,
    #   troca_endereco = 3pt (mesmo esforço que instalação)
    POINTS = {
        "instalacao": 3.0, "troca_endereco": 3.0,
        "retirada": 1.5,
        "reparo": 1.0, "suporte": 1.0,
    }
    points_today = sum(POINTS.get(t.get("type") or "reparo", 1.0)
                         for t in my_closed)
    points_today = round(points_today, 1)

    # Tempo médio por nota (min)
    durations = []
    for t in my_closed:
        try:
            o = datetime.fromisoformat(t.get("opened_at") or "")
            c = datetime.fromisoformat(t.get("closed_at") or "")
            mins = max(1, int((c - o).total_seconds() / 60))
            if mins < 60 * 24:  # ignora outliers >24h
                durations.append(mins)
        except Exception:
            continue
    avg_minutes = round(sum(durations) / len(durations)) if durations else 0

    # % sucesso
    successes = sum(1 for t in my_closed if t.get("outcome") == "sucesso")
    success_rate = round((successes / closed_today) * 100) if closed_today else 0

    # Ranking — conta por colaborador
    pipeline = [
        {"$match": {
            "company_id": company_id,
            "status": "finalizada",
            "closed_at": {"$gte": day_start_iso, "$lt": next_day_iso},
        }},
        {"$group": {"_id": "$assigned_collaborator_id", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
    ]
    leaderboard = await db.tickets.aggregate(pipeline).to_list(length=100)
    total_techs = len(leaderboard)
    rank = next(
        (i + 1 for i, r in enumerate(leaderboard) if r["_id"] == cid),
        None,
    )

    # Streak — quantos dias consecutivos com >=1 nota fechada (até 30)
    streak = 0
    for back in range(0, 30):
        d_start = (day_start - timedelta(days=back)).isoformat()
        d_end = (day_start - timedelta(days=back - 1)).isoformat()
        has = await db.tickets.find_one(
            {
                "assigned_collaborator_id": cid,
                "status": "finalizada",
                "closed_at": {"$gte": d_start, "$lt": d_end},
            },
            {"_id": 0, "id": 1},
        )
        if has:
            streak += 1
        else:
            if back == 0:
                # se hoje sem nota, streak começa zerado
                break
            break

    # Badge motivacional
    if closed_today == 0:
        badge = "Bora começar o dia!"
    elif rank == 1 and total_techs > 1:
        badge = "🏆 Líder do dia"
    elif success_rate == 100 and closed_today >= 3:
        badge = "💯 100% sucesso"
    elif streak >= 5:
        badge = f"🔥 {streak} dias seguidos"
    elif closed_today >= 5:
        badge = "⚡ Em ritmo forte"
    else:
        badge = "Bom trabalho!"

    return {
        "closed_today": closed_today,
        "points_today": points_today,
        "success_rate": success_rate,
        "avg_minutes": avg_minutes,
        "rank": rank,
        "total_techs": total_techs,
        "streak": streak,
        "badge": badge,
    }



# -------------------------------------------------------------------------
# Conquistas/medalhas do técnico — persistente, calculadas on-the-fly
# -------------------------------------------------------------------------

# Catálogo de medalhas. Cada uma é avaliada via uma function async (db, cid).
async def _ach_first_note(db, cid: str) -> bool:
    return bool(await db.tickets.find_one(
        {"assigned_collaborator_id": cid, "status": "finalizada"},
        {"_id": 0, "id": 1},
    ))


async def _ach_count_total(db, cid: str, threshold: int) -> int:
    """Retorna quantas finalizadas — para badges com tiers."""
    return await db.tickets.count_documents(
        {"assigned_collaborator_id": cid, "status": "finalizada"},
    )


async def _ach_count_type(db, cid: str, ttype: str) -> int:
    return await db.tickets.count_documents(
        {"assigned_collaborator_id": cid, "status": "finalizada",
          "type": ttype},
    )


async def _ach_max_streak(db, cid: str) -> int:
    """Maior streak histórico (até 365 dias atrás)."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    days_set = set()
    cursor = db.tickets.find(
        {"assigned_collaborator_id": cid, "status": "finalizada"},
        {"_id": 0, "closed_at": 1},
    )
    async for t in cursor:
        try:
            d = datetime.fromisoformat(t["closed_at"]).date()
            days_set.add(d)
        except Exception:
            continue
    if not days_set:
        return 0
    sorted_days = sorted(days_set)
    best, cur = 1, 1
    for i in range(1, len(sorted_days)):
        if (sorted_days[i] - sorted_days[i - 1]).days == 1:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


# Catálogo: (id, icon, label, description, tier)
ACHIEVEMENTS_CATALOG = [
    {"id": "primeira_nota", "icon": "🌱", "label": "Primeira nota",
      "desc": "Fechou seu primeiro chamado"},
    {"id": "dezena", "icon": "🔟", "label": "Dezena", "desc": "10 notas fechadas"},
    {"id": "centena", "icon": "💯", "label": "Centena",
      "desc": "100 notas fechadas"},
    {"id": "mil_mestres", "icon": "🏅", "label": "Mil mestre",
      "desc": "1000 notas fechadas"},
    {"id": "instalador_10", "icon": "🔧", "label": "Instalador",
      "desc": "10 instalações concluídas"},
    {"id": "instalador_100", "icon": "⚙️", "label": "Instalador Master",
      "desc": "100 instalações concluídas"},
    {"id": "retirador", "icon": "📦", "label": "Retirador",
      "desc": "10 retiradas de equipamento concluídas"},
    {"id": "streak_7", "icon": "🔥", "label": "Streak 7",
      "desc": "7 dias consecutivos com fechamento"},
    {"id": "streak_30", "icon": "🌋", "label": "Streak 30",
      "desc": "30 dias consecutivos com fechamento"},
    {"id": "sinal_ouro", "icon": "📡", "label": "Sinal de Ouro",
      "desc": "Média RX melhor que -22 dBm em 50+ instalações"},
    {"id": "veloz", "icon": "⚡", "label": "Veloz",
      "desc": "Tempo médio < 30min em 50+ notas"},
]


@router.get("/lousa/public/achievements/{cid}")
async def get_achievements(cid: str):
    """Lista todas as medalhas + flag earned para o técnico."""
    col = await db.collaborators.find_one(
        {"id": cid}, {"_id": 0, "id": 1, "name": 1},
    )
    if not col:
        raise HTTPException(404, "Colaborador não encontrado")

    earned = []
    # Contadores
    total = await db.tickets.count_documents(
        {"assigned_collaborator_id": cid, "status": "finalizada"},
    )
    instals = await _ach_count_type(db, cid, "instalacao")
    retiradas = await _ach_count_type(db, cid, "retirada")
    streak_max = await _ach_max_streak(db, cid)
    # Métricas avançadas
    rx_avg = None
    avg_min = None
    fast_count = 0
    good_sig_count = 0
    cursor = db.tickets.find(
        {"assigned_collaborator_id": cid, "status": "finalizada"},
        {"_id": 0, "completion_data": 1, "opened_at": 1, "closed_at": 1,
          "type": 1},
    )
    rxs, mins = [], []
    async for t in cursor:
        cd = t.get("completion_data") or {}
        sn = cd.get("sinal")
        if isinstance(sn, (int, float)):
            rxs.append(float(sn))
            if t.get("type") == "instalacao" and sn > -22:
                good_sig_count += 1
        try:
            from datetime import datetime
            o = datetime.fromisoformat(t["opened_at"])
            c = datetime.fromisoformat(t["closed_at"])
            m = max(1, int((c - o).total_seconds() / 60))
            if m < 60 * 24:
                mins.append(m)
                if m < 30:
                    fast_count += 1
        except Exception:
            continue
    if rxs:
        rx_avg = round(sum(rxs) / len(rxs), 1)
    if mins:
        avg_min = round(sum(mins) / len(mins))

    rules = {
        "primeira_nota": total >= 1,
        "dezena": total >= 10,
        "centena": total >= 100,
        "mil_mestres": total >= 1000,
        "instalador_10": instals >= 10,
        "instalador_100": instals >= 100,
        "retirador": retiradas >= 10,
        "streak_7": streak_max >= 7,
        "streak_30": streak_max >= 30,
        "sinal_ouro": good_sig_count >= 50,
        "veloz": fast_count >= 50,
    }
    medals = []
    for entry in ACHIEVEMENTS_CATALOG:
        medals.append({**entry, "earned": rules.get(entry["id"], False)})
        if rules.get(entry["id"]):
            earned.append(entry["id"])
    return {
        "collaborator_id": cid,
        "name": col["name"],
        "medals": medals,
        "earned_count": len(earned),
        "total_count": len(ACHIEVEMENTS_CATALOG),
        "stats": {
            "total_closed": total,
            "instalacoes": instals,
            "retiradas": retiradas,
            "max_streak": streak_max,
            "rx_avg": rx_avg,
            "avg_minutes": avg_min,
        },
    }



# -------------------------------------------------------------------------
# Geofence Alert — detecta técnico fora da área da bolha aberta
# -------------------------------------------------------------------------
class GeofencePingIn(BaseModel):
    collaborator_id: str
    lat: float
    lng: float


@router.post("/lousa/public/geofence-ping")
async def geofence_ping(payload: GeofencePingIn):
    """Recebe ping de posição do técnico. Se ele estiver em chamado aberto
    e fora do raio de 500m do endereço do cliente por > 5min, cria uma
    bolha de alerta tipo `alerta_geofence` piscando vermelha na grade da Lousa.
    Endpoint público (técnico não tem JWT)."""
    cid = payload.collaborator_id
    col = await db.collaborators.find_one({"id": cid},
                                              {"_id": 0, "name": 1,
                                                "company_id": 1})
    if not col:
        raise HTTPException(404, "Colaborador não encontrado")
    company_id = col.get("company_id") or DEMO_COMPANY_ID

    # Persiste a última posição do técnico (para Smart Route admin)
    await db.collaborators.update_one(
        {"id": cid},
        {"$set": {"last_position": {
            "lat": payload.lat, "lng": payload.lng,
            "updated_at": now_iso(),
        }}},
    )

    # Chamados abertos do técnico hoje
    today = _today_br_iso()
    open_ticket = await db.tickets.find_one(
        {
            "assigned_collaborator_id": cid,
            "status": {"$in": ["em_andamento", "aceito"]},
        },
        {"_id": 0, "id": 1, "client_snapshot": 1, "status": 1,
          "geofence_state": 1, "type": 1},
    )

    if not open_ticket:
        # Limpa qualquer estado pendente
        return {"ok": True, "alert": False, "reason": "sem chamado aberto"}

    snap = open_ticket.get("client_snapshot") or {}
    tlat = snap.get("latitude")
    tlng = snap.get("longitude")
    if not (isinstance(tlat, (int, float))
            and isinstance(tlng, (int, float))):
        return {"ok": True, "alert": False, "reason": "endereço sem coords"}

    distance_m = _haversine_km(payload.lat, payload.lng,
                                   float(tlat), float(tlng)) * 1000
    state = open_ticket.get("geofence_state") or {}
    now = datetime.now(timezone.utc)
    INSIDE_RADIUS_M = 500
    THRESHOLD_MIN = 5

    if distance_m <= INSIDE_RADIUS_M:
        # Volta a estar perto: reseta state
        if state.get("outside_since"):
            await db.tickets.update_one(
                {"id": open_ticket["id"]},
                {"$set": {"geofence_state.outside_since": None,
                            "geofence_state.last_distance_m": int(distance_m)}},
            )
        return {"ok": True, "alert": False, "distance_m": int(distance_m)}

    # FORA do raio
    outside_since = state.get("outside_since")
    if not outside_since:
        await db.tickets.update_one(
            {"id": open_ticket["id"]},
            {"$set": {"geofence_state.outside_since": now.isoformat(),
                        "geofence_state.last_distance_m": int(distance_m),
                        "geofence_state.alert_fired": False}},
        )
        return {"ok": True, "alert": False, "distance_m": int(distance_m),
                "outside_since": now.isoformat()}

    # Já estava fora — checa há quanto tempo
    try:
        since_dt = datetime.fromisoformat(outside_since)
        elapsed_min = (now - since_dt).total_seconds() / 60
    except Exception:
        elapsed_min = 0

    already_fired = bool(state.get("alert_fired"))
    if elapsed_min >= THRESHOLD_MIN and not already_fired:
        # Cria bolha de alerta na lousa
        alert_id = f"alerta-{uuid.uuid4().hex[:10]}"
        alert_doc = {
            "id": alert_id,
            "company_id": company_id,
            "type": "alerta_geofence",  # tipo especial
            "priority": "urgente",
            "status": "pendente",
            "assigned_collaborator_id": cid,  # mesmo técnico (visível na coluna dele)
            "created_at": now.isoformat(),
            "opened_at": now.isoformat(),
            "client_snapshot": {
                "name": f"⚠️ {col['name']}",
                "address": snap.get("address") or "—",
                "neighborhood": snap.get("neighborhood") or "—",
                "phone": "",
            },
            "relato": (
                f"Técnico {col['name']} está há {int(elapsed_min)} min "
                f"a {int(distance_m)}m do endereço do chamado "
                f"{open_ticket['id']} ({snap.get('address') or '—'}). "
                "Sem fechamento ainda — verificar."
            ),
            "position": int(now.timestamp() * -1000),  # topo da lista
            "source_ticket_id": open_ticket["id"],
            "source_collaborator_id": cid,
            "geofence_distance_m": int(distance_m),
            "geofence_elapsed_min": int(elapsed_min),
        }
        await db.tickets.insert_one(alert_doc)
        await db.tickets.update_one(
            {"id": open_ticket["id"]},
            {"$set": {"geofence_state.alert_fired": True,
                        "geofence_state.alert_id": alert_id}},
        )
        logger.warning("[lousa.geofence] ALERTA: tech=%s d=%dm t=%dmin "
                          "→ ticket %s", cid, int(distance_m),
                          int(elapsed_min), alert_id)
        return {
            "ok": True, "alert": True, "alert_id": alert_id,
            "distance_m": int(distance_m), "elapsed_min": int(elapsed_min),
        }

    return {"ok": True, "alert": False, "distance_m": int(distance_m),
            "elapsed_min": int(elapsed_min)}




# -------------------------------------------------------------------------
# Smart Route — otimiza ordem das bolhas pelo trajeto via nearest neighbor
# -------------------------------------------------------------------------
class RouteOptimizeIn(BaseModel):
    collaborator_id: str
    current_lat: float
    current_lng: float
    apply: bool = False  # se True, persiste a nova ordem via reorder


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    import math
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@router.post("/lousa/public/optimize-route")
async def optimize_route(payload: RouteOptimizeIn):
    """Calcula ordem ótima das bolhas do dia via Nearest-Neighbor TSP greedy.

    Considera apenas tickets pendentes/aguardando do dia com lat/lng válidos
    E priority="normal" (urgentes/horario têm slot fixo e não podem ser
    reordenados). Retorna a sequência otimizada + distância total estimada.
    """
    today = _today_br_iso()
    cursor = db.tickets.find(
        {
            "assigned_collaborator_id": payload.collaborator_id,
            "status": {"$in": ["pendente", "aguardando_atendimento"]},
            "priority": "normal",
        },
        {"_id": 0, "id": 1, "client_snapshot": 1, "priority": 1,
          "scheduled_time": 1, "opened_at": 1, "created_at": 1, "position": 1},
    )
    candidates = []
    async for t in cursor:
        if _ticket_day_iso(t) != today:
            continue
        snap = t.get("client_snapshot") or {}
        lat = snap.get("latitude")
        lng = snap.get("longitude")
        if not (isinstance(lat, (int, float)) and isinstance(lng, (int, float))):
            continue
        candidates.append({
            "id": t["id"], "lat": float(lat), "lng": float(lng),
            "name": snap.get("name", ""),
            "address": snap.get("address", ""),
            "neighborhood": snap.get("neighborhood", ""),
            "original_position": t.get("position", 0),
        })

    if len(candidates) < 2:
        return {
            "ok": False,
            "reason": ("Nenhum chamado reordenável (precisa de pelo menos 2 "
                        "bolhas normais com endereço válido)."),
            "optimized": [], "total_km": 0.0,
            "candidates_count": len(candidates),
        }

    # Nearest neighbor
    cur_lat, cur_lng = payload.current_lat, payload.current_lng
    remaining = candidates[:]
    ordered = []
    total = 0.0
    while remaining:
        nearest = min(
            remaining,
            key=lambda c: _haversine_km(cur_lat, cur_lng, c["lat"], c["lng"]),
        )
        d = _haversine_km(cur_lat, cur_lng, nearest["lat"], nearest["lng"])
        total += d
        nearest["distance_km"] = round(d, 2)
        ordered.append(nearest)
        cur_lat, cur_lng = nearest["lat"], nearest["lng"]
        remaining.remove(nearest)

    # Aplica se solicitado — usa _apply_reorder helper se existir, ou
    # update_many de position
    applied = False
    if payload.apply:
        # Posições começam após bolhas com prioridade fixa (urgente/horário).
        # Encontra menor `position` entre as candidatas e usa como base.
        base = min((c["original_position"] for c in candidates), default=0)
        for i, c in enumerate(ordered):
            await db.tickets.update_one(
                {"id": c["id"]},
                {"$set": {"position": base + i}},
            )
        applied = True

    return {
        "ok": True,
        "optimized": [
            {
                "id": c["id"], "name": c["name"],
                "address": c["address"],
                "neighborhood": c["neighborhood"],
                "distance_km": c["distance_km"],
            } for c in ordered
        ],
        "total_km": round(total, 2),
        "stops": len(ordered),
        "applied": applied,
        "estimated_minutes": round(total / 30 * 60 + len(ordered) * 25),
    }




# -------------------------------------------------------------------------


# Endpoint admin: otimiza rota usando última posição conhecida do técnico
class AdminRouteOptimizeIn(BaseModel):
    collaborator_id: str
    apply: bool = True


@router.post("/lousa/admin/optimize-route")
async def admin_optimize_route(payload: AdminRouteOptimizeIn,
                                  user: dict = Depends(require_role("gestor"))):
    """Gestor otimiza a rota de um técnico usando a última posição GPS dele."""
    col = await db.collaborators.find_one(
        {"id": payload.collaborator_id},
        {"_id": 0, "id": 1, "name": 1, "last_position": 1},
    )
    if not col:
        raise HTTPException(404, "Técnico não encontrado")
    last = col.get("last_position") or {}
    lat = last.get("lat")
    lng = last.get("lng")
    if not (isinstance(lat, (int, float)) and isinstance(lng, (int, float))):
        raise HTTPException(
            400,
            "Sem posição GPS do técnico — peça para ele abrir o app primeiro.",
        )
    # Reusa a lógica do public endpoint
    return await optimize_route(RouteOptimizeIn(
        collaborator_id=payload.collaborator_id,
        current_lat=float(lat), current_lng=float(lng),
        apply=payload.apply,
    ))




# Toggles globais dos cards (ativar/desativar exibição no app do técnico)
DASHBOARD_CONFIG_DEFAULTS = {
    "show_performance": True,
    "show_achievements": True,
    "show_smart_route": True,
    "show_points": True,
    "enable_geofence_alerts": True,
}


@router.get("/lousa/admin/dashboard-config")
async def get_dashboard_config(user: dict = Depends(get_current_user)):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await db.lousa_dashboard_config.find_one(
        {"company_id": company_id}, {"_id": 0},
    )
    return {**DASHBOARD_CONFIG_DEFAULTS, **(cfg or {}),
              "company_id": company_id}


@router.post("/lousa/admin/dashboard-config")
async def set_dashboard_config(payload: Dict[str, Any],
                                  user: dict = Depends(require_role("gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    updates = {k: bool(v) for k, v in payload.items()
                if k in DASHBOARD_CONFIG_DEFAULTS}
    if not updates:
        raise HTTPException(400, "Nenhum campo válido enviado")
    await db.lousa_dashboard_config.update_one(
        {"company_id": company_id},
        {"$set": {**updates, "company_id": company_id,
                    "updated_at": now_iso()}},
        upsert=True,
    )
    cfg = await db.lousa_dashboard_config.find_one(
        {"company_id": company_id}, {"_id": 0},
    )
    return {**DASHBOARD_CONFIG_DEFAULTS, **(cfg or {}),
              "company_id": company_id}


# Endpoint público pro app do técnico ler os toggles
@router.get("/lousa/public/dashboard-config/{cid}")
async def get_dashboard_config_public(cid: str):
    col = await db.collaborators.find_one({"id": cid},
                                              {"_id": 0, "company_id": 1})
    if not col:
        raise HTTPException(404, "Colaborador não encontrado")
    company_id = col.get("company_id") or DEMO_COMPANY_ID
    cfg = await db.lousa_dashboard_config.find_one(
        {"company_id": company_id}, {"_id": 0},
    )
    return {**DASHBOARD_CONFIG_DEFAULTS, **(cfg or {}),
              "company_id": company_id}


# Mural público — ranking dos técnicos do dia (TV no escritório)
# -------------------------------------------------------------------------
@router.get("/lousa/public/leaderboard")
async def get_leaderboard(company_id: Optional[str] = None,
                            limit: int = 10):
    """Top N técnicos do dia para mural público no escritório.

    Sem autenticação — display em TV. Filtra colaboradores ativos e que
    bateram ponto OU finalizaram pelo menos 1 nota hoje.
    """
    from datetime import datetime, timezone, timedelta
    cid_filter = company_id or DEMO_COMPANY_ID
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_iso = day_start.isoformat()
    next_day_iso = (day_start + timedelta(days=1)).isoformat()

    # Agrega notas finalizadas hoje
    pipeline = [
        {"$match": {
            "company_id": cid_filter,
            "status": "finalizada",
            "closed_at": {"$gte": day_start_iso, "$lt": next_day_iso},
        }},
        {"$group": {
            "_id": "$assigned_collaborator_id",
            "closed": {"$sum": 1},
            "successes": {"$sum": {
                "$cond": [{"$eq": ["$outcome", "sucesso"]}, 1, 0],
            }},
            "total_minutes": {"$sum": {"$ifNull": [
                {"$divide": [
                    {"$subtract": [
                        {"$dateFromString": {"dateString": "$closed_at"}},
                        {"$dateFromString": {"dateString": "$opened_at"}},
                    ]},
                    60000,
                ]},
                0,
            ]}},
        }},
        {"$sort": {"closed": -1, "successes": -1}},
        {"$limit": max(1, min(limit, 20))},
    ]
    rows = await db.tickets.aggregate(pipeline).to_list(length=20)

    # Hidrata com nome + avatar
    cids = [r["_id"] for r in rows if r["_id"]]
    cmap = {}
    if cids:
        async for c in db.collaborators.find(
            {"id": {"$in": cids}},
            {"_id": 0, "id": 1, "name": 1, "avatar_data_url": 1,
              "google_picture": 1, "role": 1},
        ):
            cmap[c["id"]] = c

    leaderboard = []
    for idx, r in enumerate(rows):
        cid = r["_id"]
        col = cmap.get(cid, {})
        closed = r.get("closed", 0)
        successes = r.get("successes", 0)
        total_minutes = r.get("total_minutes", 0) or 0
        avg_minutes = round(total_minutes / closed) if closed else 0
        success_rate = round((successes / closed) * 100) if closed else 0
        # badge inline
        if idx == 0 and len(rows) > 1:
            badge = "🏆 Líder"
        elif success_rate == 100 and closed >= 3:
            badge = "💯 Perfeito"
        elif closed >= 5:
            badge = "⚡ Forte"
        else:
            badge = ""

        leaderboard.append({
            "rank": idx + 1,
            "collaborator_id": cid,
            "name": col.get("name") or "—",
            "photo_url": col.get("avatar_data_url") or col.get("google_picture"),
            "role": col.get("role") or "técnico",
            "closed_today": closed,
            "success_rate": success_rate,
            "avg_minutes": avg_minutes,
            "badge": badge,
        })

    return {
        "company_id": cid_filter,
        "generated_at": now.isoformat(),
        "total_techs": len(leaderboard),
        "leaderboard": leaderboard,
    }



# -------------------------------------------------------------------------
# SERVER TIME (sincronização)
# -------------------------------------------------------------------------
@router.get("/server-time")
async def get_server_time():
    """Retorna o horário atual do servidor para sincronização com dispositivos."""
    from datetime import datetime, timezone
    import time as _time
    now = datetime.now(timezone.utc)
    settings = await db.settings.find_one({"id": DEMO_COMPANY_ID}, {"_id": 0}) or {}
    return {
        "iso": now.isoformat(),
        "epoch_ms": int(now.timestamp() * 1000),
        "epoch_s": int(now.timestamp()),
        "tz": settings.get("time_sync_timezone", "America/Sao_Paulo"),
        "sync_enabled": bool(settings.get("time_sync_enabled", False)),
        "max_drift_seconds": int(settings.get("time_sync_max_drift_seconds", 60)),
    }


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



# -------------------------------------------------------------------------
# STATS — Painel de estatísticas dos serviços
# -------------------------------------------------------------------------
@router.get("/lousa/stats")
async def lousa_stats(user: dict = Depends(require_role("gestor")),
                      days: int = 30):
    """Estatísticas agregadas das bolhas/serviços do tenant nos últimos N dias.

    Retorna: total, by_status (executada/finalizada/encerrada/cancelada/etc),
    avg_duration_minutes, by_type (ranking) e tendência diária.
    """
    q = tenant_filter(user)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
    q_recent = dict(q)
    q_recent["$or"] = [
        {"created_at": {"$gte": cutoff}},
        {"closed_at": {"$gte": cutoff}},
    ]
    docs = await db.tickets.find(q_recent, {"_id": 0}).to_list(5000)

    by_status: dict = {}
    by_type: dict = {}
    by_type_durations: dict = {}
    durations: list[float] = []
    by_day: dict = {}  # {YYYY-MM-DD: {created, finalized}}

    for t in docs:
        st = t.get("status", "pendente")
        by_status[st] = by_status.get(st, 0) + 1
        ttype = t.get("type", "reparo")
        by_type[ttype] = by_type.get(ttype, 0) + 1

        dur = compute_duration_minutes(t)
        if dur is not None and t.get("status") in ("finalizada", "encerrada"):
            durations.append(dur)
            by_type_durations.setdefault(ttype, []).append(dur)

        for ts_field, key in (("created_at", "created"), ("closed_at", "finalized")):
            ts = t.get(ts_field)
            if not ts:
                continue
            day = ts[:10]
            d = by_day.setdefault(day, {"created": 0, "finalized": 0})
            if key == "finalized" and t.get("status") not in ("finalizada", "encerrada"):
                continue
            d[key] += 1

    # Ranking de tipos com média de duração
    ranking = []
    for ttype, count in sorted(by_type.items(), key=lambda x: -x[1]):
        durs = by_type_durations.get(ttype, [])
        avg = round(sum(durs) / len(durs), 1) if durs else None
        ranking.append({
            "type": ttype,
            "count": count,
            "avg_duration_minutes": avg,
        })

    timeline = [
        {"day": d, "created": v["created"], "finalized": v["finalized"]}
        for d, v in sorted(by_day.items())
    ]

    return {
        "period_days": days,
        "total": len(docs),
        "by_status": {
            "pendente": by_status.get("pendente", 0),
            "aberta": by_status.get("aberta", 0),
            "aguardando_atendimento": by_status.get("aguardando_atendimento", 0),
            "finalizada": by_status.get("finalizada", 0),
            "encerrada": by_status.get("encerrada", 0),
            "reagendada": by_status.get("reagendada", 0),
            "cancelada": by_status.get("cancelada", 0),
        },
        "executed_count": by_status.get("aberta", 0)
                        + by_status.get("finalizada", 0)
                        + by_status.get("encerrada", 0),
        "finalized_count": by_status.get("finalizada", 0),
        "avg_duration_minutes": round(sum(durations) / len(durations), 1) if durations else None,
        "ranking_by_type": ranking,
        "timeline": timeline,
    }


# -------------------------------------------------------------------------
# AI EVALUATION — Avaliação profunda via LLM (Claude/GPT/Gemini)
# -------------------------------------------------------------------------
# Cache em memória (TTL 5min) para evitar chamadas LLM repetidas no mesmo ticket
_AI_EVAL_CACHE: Dict[str, Dict[str, Any]] = {}
_AI_EVAL_TTL_SECONDS = 300


def _ai_cache_get(ticket_id: str) -> Optional[Dict[str, Any]]:
    entry = _AI_EVAL_CACHE.get(ticket_id)
    if not entry:
        return None
    age = (datetime.now(timezone.utc) - entry["at"]).total_seconds()
    if age > _AI_EVAL_TTL_SECONDS:
        _AI_EVAL_CACHE.pop(ticket_id, None)
        return None
    return entry["result"]


def _ai_cache_set(ticket_id: str, result: Dict[str, Any]) -> None:
    _AI_EVAL_CACHE[ticket_id] = {"at": datetime.now(timezone.utc), "result": result}


@router.post("/lousa/tickets/{ticket_id}/ai-evaluate")
async def ai_evaluate_ticket(ticket_id: str,
                             user: dict = Depends(require_role("gestor"))):
    """Roda LLM para gerar análise textual da execução do serviço com sugestões.
    Usa o score heurístico como contexto e devolve um parecer + nota IA.
    Cache em memória de 5 minutos por ticket_id para reduzir custo/latência.
    """
    cached = _ai_cache_get(ticket_id)
    if cached:
        return {**cached, "cached": True}
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Serviço não encontrado")
    cid = t.get("assigned_collaborator_id")
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0, "name": 1, "praca_name": 1})
    company_id = t.get("company_id") or DEMO_COMPANY_ID
    settings = await db.settings.find_one({"id": company_id}, {"_id": 0}) or {}
    sla_min = int(settings.get(f"sla_{t.get('type', 'reparo')}_minutes", 60))

    heur = await heuristic_score_for_ticket(t, sla_minutes=sla_min)
    duration = compute_duration_minutes(t)

    prompt_user = (
        f"Avalie a execução deste serviço de campo. Devolva um JSON com chaves "
        f"`ai_score` (0-10, número), `verdict` ('Excelente'|'Bom'|'Atenção'|'Crítico'), "
        f"`summary` (string curta em PT-BR, max 200 chars) e `recommendations` (lista de strings PT-BR, max 4 itens, max 120 chars cada).\n\n"
        f"DADOS:\n"
        f"- Técnico: {coll.get('name') if coll else cid}\n"
        f"- Tipo de serviço: {t.get('type')}\n"
        f"- Status: {t.get('status')}\n"
        f"- SLA configurado: {sla_min} minutos\n"
        f"- Duração real: {f'{duration:.0f}' if duration is not None else 'em andamento'} minutos\n"
        f"- Cliente: {(t.get('client_snapshot') or {}).get('name')}\n"
        f"- Endereço: {(t.get('client_snapshot') or {}).get('address')}\n"
        f"- Bairro: {(t.get('client_snapshot') or {}).get('neighborhood')}\n"
        f"- Relato: {(t.get('client_snapshot') or {}).get('relato')[:300]}\n"
        f"- Score heurístico atual: {heur['score']} ({heur['label']})\n"
        f"- Sinais detectados:\n"
        + "\n".join(f"  · [{s.get('level','')}] {s.get('msg','')}" for s in heur.get('signals') or [])
    )

    system_msg = (
        "Você é um auditor sênior de operações de campo (field service). "
        "Avalie tecnicamente a execução do serviço com base nos dados fornecidos. "
        "Seja imparcial, factual e sucinto. Sempre devolva APENAS o JSON solicitado, sem cercas markdown."
    )

    try:
        from emergentintegrations.llm.chat import UserMessage
        chat = await llm_chat(session_id=f"ai-eval-{ticket_id}", system=system_msg)
        resp = await chat.send_message(UserMessage(text=prompt_user))
        text = (resp or "").strip()
        # Tenta extrair JSON
        import json as _json
        import re as _re
        m = _re.search(r"\{.*\}", text, _re.DOTALL)
        parsed = _json.loads(m.group(0)) if m else {}
        ai_score = float(parsed.get("ai_score") or heur["score"])
        verdict = parsed.get("verdict") or heur["label"]
        summary = parsed.get("summary") or "Análise indisponível."
        recs = parsed.get("recommendations") or []
        if not isinstance(recs, list):
            recs = [str(recs)]
        result = {
            "ticket_id": ticket_id,
            "ai_score": round(max(0.0, min(10.0, ai_score)), 1),
            "verdict": verdict,
            "summary": summary[:240],
            "recommendations": [str(r)[:160] for r in recs[:4]],
            "heuristic": heur,
            "method": "llm",
            "computed_at": now_iso(),
        }
    except Exception as e:
        logger.warning("[ai-evaluate] LLM falhou, usando heurística: %s", e)
        result = {
            "ticket_id": ticket_id,
            "ai_score": heur["score"],
            "verdict": heur["label"],
            "summary": "Avaliação automática (heurística) — IA indisponível no momento.",
            "recommendations": [s.get("msg", "") for s in heur.get("signals", []) if s.get("level") in ("warning", "critical")][:4],
            "heuristic": heur,
            "method": "heuristic_fallback",
            "computed_at": now_iso(),
            "error": str(e)[:160],
        }

    # Persiste em ticket_logs para auditoria
    await _log_ticket_action(
        ticket_id=ticket_id, action="avaliacao_ia",
        actor_id=user["id"], actor_name=user.get("name", "Gestor"),
        actor_role=user.get("role", "gestor"),
        details=f"IA: {result['verdict']} ({result['ai_score']}) — {result['summary'][:120]}",
        company_id=company_id,
    )
    # Cache somente se LLM funcionou; se for fallback heurístico, deixa cair
    # para a próxima call e dar chance do LLM voltar.
    if result.get("method") != "heuristic_fallback":
        _ai_cache_set(ticket_id, result)
    return result


@router.get("/lousa/ai-rankings")
async def lousa_ai_rankings(user: dict = Depends(require_role("gestor")),
                             days: int = 30):
    """Rankings de IA por colaborador nos últimos N dias.

    Computa score heurístico de cada ticket (mesma fórmula do grid) e agrega
    por técnico: média, total avaliado, pior/melhor score, distribuição por
    nível (Excelente / Bom / Atenção / Crítico).
    """
    q = tenant_filter(user)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
    q_recent = dict(q)
    q_recent["$or"] = [
        {"created_at": {"$gte": cutoff}},
        {"closed_at": {"$gte": cutoff}},
    ]
    docs = await db.tickets.find(q_recent, {"_id": 0}).to_list(5000)

    company_id = user.get("company_id") or DEMO_COMPANY_ID
    settings = await db.settings.find_one({"id": company_id}, {"_id": 0}) or {}

    # Agregação por colaborador
    by_coll: Dict[str, Dict[str, Any]] = {}
    for t in docs:
        cid = t.get("assigned_collaborator_id")
        if not cid:
            continue
        sla_min = int(settings.get(f"sla_{t.get('type', 'reparo')}_minutes", 60))
        try:
            heur = await heuristic_score_for_ticket(t, sla_minutes=sla_min)
        except Exception:
            continue
        score = float(heur.get("score") or 0.0)
        verdict = heur.get("label") or "—"
        b = by_coll.setdefault(cid, {
            "collaborator_id": cid,
            "scores": [], "verdicts": {"Excelente": 0, "Bom": 0, "Atenção": 0, "Crítico": 0},
            "min": 10.0, "max": 0.0,
            "worst_ticket": None, "best_ticket": None,
        })
        b["scores"].append(score)
        if verdict in b["verdicts"]:
            b["verdicts"][verdict] += 1
        if score < b["min"]:
            b["min"] = score
            b["worst_ticket"] = {"id": t.get("id"), "client": (t.get("client_snapshot") or {}).get("name"), "score": score}
        if score > b["max"]:
            b["max"] = score
            b["best_ticket"] = {"id": t.get("id"), "client": (t.get("client_snapshot") or {}).get("name"), "score": score}

    # Resolve nomes dos colaboradores
    coll_ids = list(by_coll.keys())
    if coll_ids:
        colls = await db.collaborators.find(
            {"id": {"$in": coll_ids}}, {"_id": 0, "id": 1, "name": 1, "avatar": 1, "praca_name": 1},
        ).to_list(len(coll_ids))
        coll_map = {c["id"]: c for c in colls}
    else:
        coll_map = {}

    items = []
    for cid, b in by_coll.items():
        scores = b["scores"]
        avg = round(sum(scores) / len(scores), 2) if scores else 0.0
        coll = coll_map.get(cid, {})
        items.append({
            "collaborator_id": cid,
            "collaborator_name": coll.get("name") or cid,
            "avatar": coll.get("avatar"),
            "praca": coll.get("praca_name"),
            "total_evaluated": len(scores),
            "avg_score": avg,
            "min_score": round(b["min"], 2) if scores else None,
            "max_score": round(b["max"], 2) if scores else None,
            "verdicts": b["verdicts"],
            "best_ticket": b["best_ticket"],
            "worst_ticket": b["worst_ticket"],
        })
    items.sort(key=lambda x: x["avg_score"], reverse=True)

    overall_avg = (
        round(sum(x["avg_score"] * x["total_evaluated"] for x in items)
              / max(sum(x["total_evaluated"] for x in items), 1), 2)
        if items else 0.0
    )
    return {
        "days": days,
        "total_evaluated": sum(x["total_evaluated"] for x in items),
        "overall_avg": overall_avg,
        "items": items,
    }


# -------------------------------------------------------------------------
# BULK ACTIONS — ações coletivas em várias bolhas selecionadas
# -------------------------------------------------------------------------
class BulkActionIn(BaseModel):
    ticket_ids: List[str] = Field(..., min_length=1, max_length=200)
    action: Literal["encerrar", "reagendar", "cancelar"]
    notes: Optional[str] = None
    new_scheduled_time: Optional[str] = None
    new_date: Optional[str] = None
    new_time: Optional[str] = None


class BulkAiEvaluateIn(BaseModel):
    ticket_ids: List[str] = Field(..., min_length=1, max_length=50)


@router.post("/lousa/tickets/bulk-action")
async def lousa_bulk_action(payload: BulkActionIn,
                            user: dict = Depends(require_role("gestor"))):
    """Aplica encerrar/reagendar/cancelar em várias bolhas de uma só vez.

    Ignora silenciosamente bolhas já encerradas (registradas em `errors`).
    Retorna lista de sucesso e erros por ID para o frontend mostrar feedback.
    """
    status_map = {"encerrar": "encerrada", "reagendar": "reagendada", "cancelar": "cancelada"}
    new_status = status_map[payload.action]

    sched = payload.new_scheduled_time
    if payload.action == "reagendar" and not sched and payload.new_date and payload.new_time:
        sched = f"{payload.new_date}T{payload.new_time}:00"

    success: List[str] = []
    errors: List[Dict[str, str]] = []

    for tid in payload.ticket_ids:
        t = await db.tickets.find_one({"id": tid}, {"_id": 0})
        if not t:
            errors.append({"id": tid, "error": "Nota não encontrada"})
            continue
        if t["status"] in ("finalizada", "encerrada", "cancelada"):
            errors.append({"id": tid, "error": f"Já {t['status']}"})
            continue
        update = {
            "status": new_status,
            "outcome": "informada",
            "closed_at": now_iso(),
            "closed_by": user["id"],
            "admin_action": payload.action,
            "admin_notes": payload.notes,
        }
        if payload.action == "reagendar" and sched:
            update["scheduled_time"] = sched
            update["grid_slot"] = None
        await db.tickets.update_one({"id": tid}, {"$set": update})
        await _log_ticket_action(
            ticket_id=tid, action=payload.action,
            actor_id=user["id"], actor_name=user.get("name", "Gestor"),
            actor_role=user.get("role", "gestor"),
            details=(payload.notes or "") + " [bulk]",
            company_id=t.get("company_id") or DEMO_COMPANY_ID,
        )
        if payload.action in ("cancelar", "reagendar"):
            client_name = (t.get("client_snapshot") or {}).get("name") or "Cliente"
            verb = "cancelada" if payload.action == "cancelar" else "reagendada"
            await _create_notification(
                type_=f"ticket_{payload.action}_by_admin",
                title=f"Nota {verb} pela gestão",
                message=f"Nota de {client_name} foi {verb} por {user.get('name', 'gestão')}. " + (payload.notes or ""),
                collaborator_id=t.get("assigned_collaborator_id"),
                ticket_id=tid,
                company_id=t.get("company_id") or DEMO_COMPANY_ID,
                severity="info" if payload.action == "reagendar" else "warning",
            )
        # Push para Atlaz se aplicável (best-effort, não trava o lote)
        if t.get("atlaz_external_id"):
            try:
                from routes import atlaz as routes_atlaz
                await routes_atlaz.push_close(
                    t, payload.action, payload.notes,
                    sched if payload.action == "reagendar" else None,
                )
            except Exception as e:
                logger.warning("[atlaz] bulk push falhou %s: %s", tid, e)
        success.append(tid)

    return {
        "action": payload.action,
        "processed": len(success),
        "failed": len(errors),
        "success": success,
        "errors": errors,
    }


@router.post("/lousa/tickets/bulk-ai-evaluate")
async def lousa_bulk_ai_evaluate(payload: BulkAiEvaluateIn,
                                 user: dict = Depends(require_role("gestor"))):
    """Roda avaliação heurística (rápida) em várias bolhas de uma só vez.

    Para evitar custo/latência alto de LLM em lote, usa apenas o score
    heurístico aqui. O gestor pode abrir a IA profunda em uma bolha
    individual depois se quiser.
    """
    results: List[Dict[str, Any]] = []
    for tid in payload.ticket_ids:
        t = await db.tickets.find_one({"id": tid}, {"_id": 0})
        if not t:
            results.append({"ticket_id": tid, "error": "não encontrada"})
            continue
        company_id = t.get("company_id") or DEMO_COMPANY_ID
        settings = await db.settings.find_one({"id": company_id}, {"_id": 0}) or {}
        sla_min = int(settings.get(f"sla_{t.get('type', 'reparo')}_minutes", 60))
        heur = await heuristic_score_for_ticket(t, sla_minutes=sla_min)
        duration = compute_duration_minutes(t)
        results.append({
            "ticket_id": tid,
            "client_name": (t.get("client_snapshot") or {}).get("name") or "—",
            "type": t.get("type"),
            "status": t.get("status"),
            "ai_score": heur["score"],
            "verdict": heur["label"],
            "duration_minutes": duration,
            "signals": heur.get("signals", []),
            "method": "heuristic",
        })
    return {"count": len(results), "items": results}


# -------------------------------------------------------------------------
# BRIEFING DIÁRIO — relatório resumido para o gestor
# -------------------------------------------------------------------------
@router.get("/lousa/briefing")
async def lousa_briefing(user: dict = Depends(require_role("gestor")),
                         use_ai: bool = True):
    """Gera resumo do dia para o gestor: top 3 serviços, técnico do dia,
    pior score IA, atrasos pendentes. Opcionalmente usa LLM para texto natural.
    """
    q = tenant_filter(user)
    today = today_str()
    company_id = user.get("company_id") or DEMO_COMPANY_ID

    # Tickets do dia (criados hoje OU fechados hoje)
    todays = await db.tickets.find(
        {**q, "$or": [
            {"created_at": {"$regex": f"^{today}"}},
            {"closed_at": {"$regex": f"^{today}"}},
        ]},
        {"_id": 0},
    ).to_list(2000)

    finalized = [t for t in todays if t.get("status") == "finalizada"]
    open_late = [t for t in todays if t.get("status") in ("aberta", "aguardando_atendimento")]
    canceled = [t for t in todays if t.get("status") == "cancelada"]

    # Top técnicos por #finalizados
    by_tech: dict = {}
    for t in finalized:
        cid = t["assigned_collaborator_id"]
        by_tech.setdefault(cid, []).append(t)
    tech_ranking = sorted(by_tech.items(), key=lambda x: -len(x[1]))

    top_collab_id, top_collab_count = (tech_ranking[0][0], len(tech_ranking[0][1])) if tech_ranking else (None, 0)
    top_collab_name = None
    if top_collab_id:
        c = await db.collaborators.find_one({"id": top_collab_id}, {"_id": 0, "name": 1})
        top_collab_name = c.get("name") if c else None

    # Score IA por bolha aberta — pega o pior score
    settings = await db.settings.find_one({"id": company_id}, {"_id": 0}) or {}
    sla_map = {
        "reparo": int(settings.get("sla_reparo_minutes", 60)),
        "instalacao": int(settings.get("sla_instalacao_minutes", 120)),
        "retirada": int(settings.get("sla_retirada_minutes", 30)),
        "prioridade": int(settings.get("sla_prioridade_minutes", 45)),
        "preventiva": int(settings.get("sla_preventiva_minutes", 90)),
        "venda": int(settings.get("sla_venda_minutes", 60)),
    }
    worst_score = None
    worst_ticket = None
    for t in open_late:
        sla = sla_map.get(t.get("type", "reparo"), 60)
        s = await heuristic_score_for_ticket(t, sla_minutes=sla)
        if worst_score is None or s["score"] < worst_score["score"]:
            worst_score = s
            worst_ticket = t

    # Top 3 serviços por duração (finalizados hoje)
    top3 = sorted(
        [t for t in finalized if compute_duration_minutes(t) is not None],
        key=lambda t: compute_duration_minutes(t) or 0,
        reverse=True,
    )[:3]
    top3_payload = [{
        "client": (t.get("client_snapshot") or {}).get("name"),
        "type": t.get("type"),
        "duration_minutes": compute_duration_minutes(t),
        "tech_id": t.get("assigned_collaborator_id"),
    } for t in top3]

    avg_dur = (sum(compute_duration_minutes(t) or 0 for t in finalized) / len(finalized)) if finalized else None

    summary_data = {
        "date": today,
        "total_today": len(todays),
        "finalized_count": len(finalized),
        "still_open_count": len(open_late),
        "canceled_count": len(canceled),
        "avg_duration_minutes": round(avg_dur, 1) if avg_dur else None,
        "top_collaborator": {
            "id": top_collab_id, "name": top_collab_name, "count": top_collab_count,
        } if top_collab_id else None,
        "worst_score_ticket": ({
            "ticket_id": worst_ticket.get("id"),
            "client": (worst_ticket.get("client_snapshot") or {}).get("name"),
            "type": worst_ticket.get("type"),
            "score": worst_score["score"],
            "label": worst_score["label"],
            "signals": worst_score.get("signals", [])[:3],
        }) if worst_ticket else None,
        "top3_services": top3_payload,
    }

    # Texto narrativo via LLM (se solicitado)
    narrative = None
    if use_ai:
        try:
            from emergentintegrations.llm.chat import UserMessage
            chat = await llm_chat(
                session_id=f"briefing-{today}-{company_id}",
                system=(
                    "Você é um analista sênior de operações de campo. "
                    "Crie um briefing executivo curto (max 4 parágrafos curtos, em PT-BR) com tom profissional. "
                    "Destaque número de serviços, top performer, atrasos, alertas. Use bullets ou frases curtas. "
                    "NÃO repita os números brutos do JSON; INTERPRETE-OS."
                ),
            )
            prompt = (
                f"Dados do dia ({today}):\n"
                f"- Total de serviços hoje: {summary_data['total_today']}\n"
                f"- Finalizados: {summary_data['finalized_count']}\n"
                f"- Em aberto/aguardando: {summary_data['still_open_count']}\n"
                f"- Cancelados: {summary_data['canceled_count']}\n"
                f"- Tempo médio: {summary_data['avg_duration_minutes']}min\n"
                f"- Top técnico: {top_collab_name} com {top_collab_count} finalizadas\n"
                f"- Pior score IA: {worst_score['score'] if worst_score else 'N/A'} "
                f"({(worst_ticket.get('client_snapshot') or {}).get('name') if worst_ticket else 'N/A'})\n"
                f"- Top serviços por duração: {[(s['client'], int(s['duration_minutes'])) for s in top3_payload]}"
            )
            narrative = (await chat.send_message(UserMessage(text=prompt))).strip()
        except Exception as e:
            logger.warning("[briefing] LLM falhou: %s", e)
            narrative = None

    return {
        "summary_data": summary_data,
        "narrative": narrative,
        "method": "llm" if narrative else "data-only",
        "computed_at": now_iso(),
    }



# -------------------------------------------------------------------------
# MANAGEMENT KPIs — métricas das ações da gestão
# -------------------------------------------------------------------------
@router.get("/lousa/management-kpis")
async def lousa_management_kpis(user: dict = Depends(require_role("gestor")),
                                days: int = 30):
    """KPIs específicos das ações da gestão (admin-open, cancel, reschedule, edit, transfer).
    Lê ticket_logs e tickets para gerar contagens, ranking de motivos e tempo médio até decisão.
    """
    q = tenant_filter(user)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()

    logs = await db.ticket_logs.find(
        {**q, "at": {"$gte": cutoff}},
        {"_id": 0},
    ).to_list(10000)

    by_action: dict = {}
    by_actor: dict = {}        # actor_name → counts
    cancel_reasons: list = []
    reschedule_reasons: list = []
    decision_durations: list = []  # min entre criação do ticket e ação da gestão

    # Pré-cache de tickets para olhar created_at
    tids = list({log["ticket_id"] for log in logs if log.get("ticket_id")})
    tickets_by_id: dict = {}
    if tids:
        for t in await db.tickets.find({"id": {"$in": tids}}, {"_id": 0}).to_list(5000):
            tickets_by_id[t["id"]] = t

    mgmt_actions = {"cancelar", "reagendar", "encerrar", "aberta_admin", "editada", "transferida"}
    for log in logs:
        action = log.get("action", "")
        if action not in mgmt_actions:
            continue
        by_action[action] = by_action.get(action, 0) + 1
        actor = log.get("actor_name") or log.get("actor_id") or "?"
        a = by_actor.setdefault(actor, {"role": log.get("actor_role"), "total": 0})
        a["total"] += 1
        a[action] = a.get(action, 0) + 1

        if action == "cancelar" and log.get("details"):
            cancel_reasons.append(log["details"][:120])
        if action == "reagendar" and log.get("details"):
            reschedule_reasons.append(log["details"][:120])

        # Tempo entre criação e decisão
        t = tickets_by_id.get(log.get("ticket_id"))
        if t and t.get("created_at"):
            try:
                ca = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00"))
                la = datetime.fromisoformat(log["at"].replace("Z", "+00:00"))
                if ca.tzinfo is None:
                    ca = ca.replace(tzinfo=timezone.utc)
                if la.tzinfo is None:
                    la = la.replace(tzinfo=timezone.utc)
                delta = (la - ca).total_seconds() / 60.0
                if delta >= 0:
                    decision_durations.append(delta)
            except Exception:
                pass

    # Top motivos (frequência simples — palavras comuns)
    def top_reasons(reasons: list, k: int = 5):
        from collections import Counter
        clean = [r.strip() for r in reasons if r and len(r.strip()) > 3]
        ct = Counter(clean).most_common(k)
        return [{"reason": r, "count": c} for r, c in ct]

    # Notas que estão atualmente reagendadas/canceladas no período
    period_tickets = await db.tickets.find(
        {**q, "$or": [
            {"created_at": {"$gte": cutoff}},
            {"closed_at": {"$gte": cutoff}},
        ]},
        {"_id": 0, "status": 1, "type": 1},
    ).to_list(5000)
    by_status: dict = {}
    cancel_by_type: dict = {}
    reschedule_by_type: dict = {}
    for t in period_tickets:
        s = t.get("status", "")
        by_status[s] = by_status.get(s, 0) + 1
        if s == "cancelada":
            cancel_by_type[t.get("type", "?")] = cancel_by_type.get(t.get("type", "?"), 0) + 1
        if s == "reagendada":
            reschedule_by_type[t.get("type", "?")] = reschedule_by_type.get(t.get("type", "?"), 0) + 1

    return {
        "period_days": days,
        "by_action": {
            "trabalhadas_pela_gestao": by_action.get("aberta_admin", 0),  # admin-open
            "encerradas": by_action.get("encerrar", 0),
            "canceladas": by_action.get("cancelar", 0),
            "reagendadas": by_action.get("reagendar", 0),
            "editadas": by_action.get("editada", 0),
            "transferidas": by_action.get("transferida", 0),
        },
        "total_management_actions": sum(by_action.values()),
        "by_actor": [
            {"name": k, **v} for k, v in sorted(by_actor.items(), key=lambda x: -x[1]["total"])[:10]
        ],
        "top_cancel_reasons": top_reasons(cancel_reasons, 5),
        "top_reschedule_reasons": top_reasons(reschedule_reasons, 5),
        "cancel_by_type": [{"type": k, "count": v} for k, v in sorted(cancel_by_type.items(), key=lambda x: -x[1])],
        "reschedule_by_type": [{"type": k, "count": v} for k, v in sorted(reschedule_by_type.items(), key=lambda x: -x[1])],
        "current_status_counts": by_status,
        "avg_minutes_to_decision": round(sum(decision_durations) / len(decision_durations), 1) if decision_durations else None,
        "computed_at": now_iso(),
    }


# -------------------------------------------------------------------------
# MANAGEMENT INSIGHTS — IA analisa decisões da gestão e sugere melhorias
# -------------------------------------------------------------------------
@router.post("/lousa/management-insights")
async def lousa_management_insights(user: dict = Depends(require_role("gestor")),
                                    days: int = 30):
    """IA analisa as ações de gestão (cancel, reschedule, transfer) e sugere
    melhorias de processo. Roda LLM com os dados de management-kpis como contexto.
    """
    kpis = await lousa_management_kpis(user, days)

    system_msg = (
        "Você é um consultor sênior de operações de campo (field service management). "
        "Analise objetivamente os números das decisões da gestão e produza um JSON com:\n"
        "- `analysis_summary`: 2-3 frases resumindo o padrão observado (PT-BR).\n"
        "- `red_flags`: lista de 0-4 alertas (strings PT-BR, max 130 chars) — pontos de atenção.\n"
        "- `recommendations`: lista de 2-5 recomendações concretas (PT-BR, max 150 chars cada) para melhorar o processo.\n"
        "- `priority_action`: 1 ação prioritária a tomar essa semana (PT-BR, max 130 chars).\n"
        "Responda SOMENTE o JSON, sem cercas markdown."
    )

    prompt = (
        f"DADOS — últimos {kpis['period_days']} dias:\n"
        f"- Notas trabalhadas pela gestão (admin-open): {kpis['by_action']['trabalhadas_pela_gestao']}\n"
        f"- Canceladas pela gestão: {kpis['by_action']['canceladas']}\n"
        f"- Reagendadas: {kpis['by_action']['reagendadas']}\n"
        f"- Encerradas pela gestão: {kpis['by_action']['encerradas']}\n"
        f"- Editadas: {kpis['by_action']['editadas']}\n"
        f"- Transferidas: {kpis['by_action']['transferidas']}\n"
        f"- Tempo médio até decisão: {kpis['avg_minutes_to_decision']}min\n"
        f"- Top motivos de cancelamento: {[r['reason'] for r in kpis['top_cancel_reasons']]}\n"
        f"- Top motivos de reagendamento: {[r['reason'] for r in kpis['top_reschedule_reasons']]}\n"
        f"- Cancelamentos por tipo de serviço: {kpis['cancel_by_type']}\n"
        f"- Reagendamentos por tipo: {kpis['reschedule_by_type']}\n"
        f"- Status atual no período: {kpis['current_status_counts']}\n"
        f"- Top atores: {[{'name': a['name'], 'total': a['total']} for a in kpis['by_actor'][:5]]}"
    )

    insights = None
    try:
        from emergentintegrations.llm.chat import UserMessage
        chat = await llm_chat(session_id=f"mgmt-insights-{user.get('company_id', DEMO_COMPANY_ID)}-{days}", system=system_msg)
        raw = (await chat.send_message(UserMessage(text=prompt))).strip()
        import json as _json
        import re as _re
        m = _re.search(r"\{.*\}", raw, _re.DOTALL)
        if m:
            insights = _json.loads(m.group(0))
    except Exception as e:
        logger.warning("[mgmt-insights] LLM falhou: %s", e)

    return {
        "kpis": kpis,
        "insights": insights or {
            "analysis_summary": "Análise IA indisponível no momento — verifique abaixo os números brutos.",
            "red_flags": [],
            "recommendations": [],
            "priority_action": "Revisar manualmente os indicadores e definir um plano de ação.",
        },
        "method": "llm" if insights else "fallback",
        "computed_at": now_iso(),
    }



# -------------------------------------------------------------------------
# HISTÓRICO DA LOUSA — filtros por dia/mês/ano/período
# -------------------------------------------------------------------------
@router.get("/lousa/history")
async def lousa_history(
    user: dict = Depends(require_role("gestor")),
    granularity: Literal["day", "month", "year", "range"] = "day",
    date: Optional[str] = None,        # YYYY-MM-DD (granularity=day)
    month: Optional[str] = None,       # YYYY-MM (granularity=month)
    year: Optional[str] = None,        # YYYY (granularity=year)
    date_from: Optional[str] = None,   # YYYY-MM-DD (range)
    date_to: Optional[str] = None,     # YYYY-MM-DD (range, inclusive)
    collaborator_id: Optional[str] = None,
    status: Optional[str] = None,      # filter by status
    type_filter: Optional[str] = Query(default=None, alias="type"),
):
    """Histórico de notas da lousa com filtros temporais e por técnico/tipo/status.
    Considera tickets criados OU finalizados no período.
    """
    q = tenant_filter(user)

    # Determina from_iso e to_iso baseado em granularity
    today_dt = datetime.now(timezone.utc)
    if granularity == "day":
        d = date or today_dt.strftime("%Y-%m-%d")
        from_iso = f"{d}T00:00:00"
        # Próximo dia 00:00 (intervalo semi-aberto, igual month/year)
        from datetime import timedelta as _td
        next_d = (datetime.fromisoformat(d) + _td(days=1)).strftime("%Y-%m-%d")
        to_iso = f"{next_d}T00:00:00"
        label = d
    elif granularity == "month":
        m = month or today_dt.strftime("%Y-%m")
        from_iso = f"{m}-01T00:00:00"
        # last day of month — primeiro dia do mês seguinte minus 1ms
        y, mo = m.split("-")
        if int(mo) == 12:
            ny, nm = int(y) + 1, 1
        else:
            ny, nm = int(y), int(mo) + 1
        to_iso = f"{ny}-{nm:02d}-01T00:00:00"
        label = m
    elif granularity == "year":
        yr = year or today_dt.strftime("%Y")
        from_iso = f"{yr}-01-01T00:00:00"
        to_iso = f"{int(yr) + 1}-01-01T00:00:00"
        label = yr
    else:  # range
        if not date_from or not date_to:
            raise HTTPException(400, "date_from e date_to obrigatórios para granularity=range")
        from_iso = f"{date_from}T00:00:00"
        from datetime import timedelta as _td
        next_d = (datetime.fromisoformat(date_to) + _td(days=1)).strftime("%Y-%m-%d")
        to_iso = f"{next_d}T00:00:00"
        label = f"{date_from} → {date_to}"

    # Query: ticket criado OU encerrado dentro do período
    base_q = dict(q)
    base_q["$or"] = [
        {"created_at": {"$gte": from_iso, "$lt": to_iso}},
        {"closed_at": {"$gte": from_iso, "$lt": to_iso}},
    ]
    if collaborator_id:
        base_q["assigned_collaborator_id"] = collaborator_id
    if status:
        base_q["status"] = status
    if type_filter:
        base_q["type"] = type_filter

    docs = await db.tickets.find(base_q, {"_id": 0}).sort("created_at", -1).to_list(5000)

    # Enriquecer com nome do técnico e duration_minutes
    cids = list({d.get("assigned_collaborator_id") for d in docs if d.get("assigned_collaborator_id")})
    coll_map = {}
    if cids:
        for c in await db.collaborators.find({"id": {"$in": cids}}, {"_id": 0, "id": 1, "name": 1}).to_list(500):
            coll_map[c["id"]] = c.get("name", "")

    items = []
    summary = {
        "total": 0, "finalizada": 0, "encerrada": 0, "cancelada": 0,
        "reagendada": 0, "pendente": 0, "aberta": 0,
        "aguardando_atendimento": 0,
        "by_type": {}, "by_collaborator": {},
        "total_duration_minutes": 0.0, "durations_count": 0,
    }
    for d in docs:
        dur = compute_duration_minutes(d)
        cid = d.get("assigned_collaborator_id")
        items.append({
            "id": d.get("id"),
            "client_name": (d.get("client_snapshot") or {}).get("name"),
            "address": (d.get("client_snapshot") or {}).get("address"),
            "neighborhood": (d.get("client_snapshot") or {}).get("neighborhood"),
            "type": d.get("type"),
            "priority": d.get("priority"),
            "status": d.get("status"),
            "scheduled_time": d.get("scheduled_time"),
            "created_at": d.get("created_at"),
            "opened_at": d.get("opened_at"),
            "closed_at": d.get("closed_at"),
            "duration_minutes": round(dur, 1) if dur is not None else None,
            "admin_action": d.get("admin_action"),
            "admin_notes": d.get("admin_notes"),
            "collaborator_id": cid,
            "collaborator_name": coll_map.get(cid, "—"),
            # Snapshot de sinal SmartOLT na abertura e fechamento + sinal
            # informado pelo técnico no completion_data (badge no card).
            "signal_at_open": d.get("signal_at_open"),
            "signal_at_close": d.get("signal_at_close"),
            "completion_data": d.get("completion_data"),
        })
        st = d.get("status", "pendente")
        summary[st] = summary.get(st, 0) + 1
        summary["total"] += 1
        ttype = d.get("type", "?")
        summary["by_type"][ttype] = summary["by_type"].get(ttype, 0) + 1
        if cid:
            summary["by_collaborator"][cid] = summary["by_collaborator"].get(cid, 0) + 1
        if dur is not None and d.get("status") in ("finalizada", "encerrada"):
            summary["total_duration_minutes"] += dur
            summary["durations_count"] += 1

    # Avg duration
    summary["avg_duration_minutes"] = (
        round(summary["total_duration_minutes"] / summary["durations_count"], 1)
        if summary["durations_count"] > 0 else None
    )

    # Top collaborator (named)
    top_collab = None
    if summary["by_collaborator"]:
        top_id = max(summary["by_collaborator"].items(), key=lambda x: x[1])[0]
        top_collab = {
            "id": top_id, "name": coll_map.get(top_id, "—"),
            "count": summary["by_collaborator"][top_id],
        }
    summary["top_collaborator"] = top_collab

    return {
        "granularity": granularity,
        "label": label,
        "from_iso": from_iso,
        "to_iso": to_iso,
        "items": items,
        "summary": summary,
    }
