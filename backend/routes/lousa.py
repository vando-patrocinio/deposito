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

from fastapi import APIRouter, Depends, HTTPException, Query
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
Priority = Literal["normal", "horario", "prioridade"]
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
PRIORITY_RANK = {"prioridade": 0, "horario": 1, "normal": 2}
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
async def get_lousa_by_collaborator(cid: str):
    """Lousa pública por collaborator_id (mobile PWA não tem auth)."""
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0, "id": 1})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado")
    return await _lousa_for_collaborator(cid)


async def _lousa_for_collaborator(cid: str) -> dict:
    state = await _today_clock_state(cid)
    # Colaboradores não-CLT (clock_in_enabled=false) não batem ponto — Lousa sempre liberada
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0, "clock_in_enabled": 1})
    clock_in_enabled = bool((coll or {}).get("clock_in_enabled", True))
    # Bolhas só aparecem após bater Entrada (identificação do técnico)
    # Para colaboradores sem ponto (freelancer/MEI/etc) liberamos direto.
    if clock_in_enabled and not state["has_entrada"]:
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
    active_raw = await db.tickets.find(
        {"assigned_collaborator_id": cid, "status": {"$in": active_states}},
        {"_id": 0},
    ).to_list(500)
    # REGRA DE DATA: filtra apenas bolhas cuja data de serviço/abertura
    # corresponde a HOJE (BR). Bolhas reagendadas pra outros dias somem
    # da Lousa de hoje (e aparecem na Lousa do dia agendado).
    today = _today_br_iso()
    active_raw = [t for t in active_raw if _ticket_day_iso(t) == today]
    active_raw.sort(key=lambda t: (PRIORITY_RANK[t["priority"]], t["position"]))
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
    resolved_raw = await db.tickets.find(
        {"assigned_collaborator_id": cid,
         "status": {"$in": list(TECH_RESOLVED)},  # apenas finalizada/encerrada pelo técnico
         "closed_at": {"$gte": cutoff}},
        {"_id": 0},
    ).to_list(200)
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
        "created_at": now_iso(),
    }
    await db.tickets.insert_one(doc)
    await _log_ticket_action(
        ticket_id=doc["id"], action="criada",
        actor_id=user["id"], actor_name=user.get("name", "Gestor"),
        actor_role=user.get("role", "gestor"),
        details=f"Atribuída a {coll.get('name', 'colaborador')} · {payload.client_name}",
        company_id=doc["company_id"],
    )
    doc.pop("_id", None)
    return doc


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


@router.post("/lousa/public/tickets/{ticket_id}/open")
async def public_open_ticket(ticket_id: str, payload: PublicOpenIn):
    cid = payload.collaborator_id
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0, "clock_in_enabled": 1})
    clock_in_enabled = bool((coll or {}).get("clock_in_enabled", True))
    if clock_in_enabled:
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
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0, "name": 1})
    await _log_ticket_action(
        ticket_id=ticket_id, action="finalizada",
        actor_id=cid, actor_name=(coll or {}).get("name", "Técnico"),
        actor_role="colaborador",
        details=f"ONT={cd.ont or '-'} · sinal={cd.sinal} dBm · fotos={len(cd.fotos)}",
        company_id=t.get("company_id") or DEMO_COMPANY_ID,
    )
    # Bridge Estoque ↔ Lousa: AUTO-BAIXA do estoque a partir do completion_data
    try:
        from routes.stok import auto_close_service_from_ticket
        coll_doc = await db.collaborators.find_one({"id": cid}, {"_id": 0, "name": 1, "company_id": 1})
        await auto_close_service_from_ticket(
            ticket_id=ticket_id,
            company_id=t.get("company_id") or DEMO_COMPANY_ID,
            completion_data=cd.model_dump(),
            technician_id=cid,
            technician_name=(coll_doc or {}).get("name", "Técnico"),
        )
    except Exception as e:
        logger.warning("[lousa] auto_close_service_from_ticket falhou: %s", e)
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
