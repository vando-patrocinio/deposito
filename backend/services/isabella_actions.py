"""ISABELLA ACTIONS — executor de ações na Lousa via marcadores.

Como Isabella não tem function-calling nativo no fluxo conversacional,
ela emite MARCADORES no fim da resposta. O sistema:
  1. Detecta o marcador
  2. Executa a ação REAL (insert em `tickets`)
  3. Substitui o marcador pela confirmação ao cliente

Marcadores suportados:
  [AGENDAR_VISITA data=YYYY-MM-DD janela=manha|tarde motivo="texto"]
  [ABRIR_CHAMADO tipo=tecnico|comercial motivo="texto"]
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["ticket.opened"],
    "company_id_required": True,
    "notes": "Cria tickets via marcadores [AGENDAR_VISITA] / [ABRIR_CHAMADO].",
}


import logging
import re
import uuid
from datetime import datetime, time, timezone
from typing import Any, Dict, List, Optional, Tuple

from database import db

log = logging.getLogger("ponto.isabella_actions")


# ─── Marcadores ───────────────────────────────────────────────
_AGENDAR_RX = re.compile(
    r"\[AGENDAR_VISITA\s+"
    r"data=(\d{4}-\d{2}-\d{2})\s+"
    r"janela=(manha|tarde)"
    r"(?:\s+motivo=\"([^\"]+)\")?\s*\]",
    re.IGNORECASE)

_CHAMADO_RX = re.compile(
    r"\[ABRIR_CHAMADO\s+"
    r"tipo=(tecnico|t[ée]cnico|comercial|suporte)"
    r"(?:\s+motivo=\"([^\"]+)\")?\s*\]",
    re.IGNORECASE)


# Slots horários DENTRO de cada janela (1h por bolha).
WINDOW_SLOTS = {
    "manha": [9, 10, 11],     # 09h, 10h, 11h
    "tarde": [13, 14, 15, 16, 17],
}

WINDOWS = {
    "manha": (time(9, 0), "09h–12h"),
    "tarde": (time(13, 0), "13h–18h"),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


SALA_COLLABORATOR_ID = "col-sala"


async def _ensure_sala(company_id: str) -> str:
    """Garante que existe a Lousa virtual SALA para o tenant.
    Idempotente. Retorna o collaborator_id da SALA."""
    sid = SALA_COLLABORATOR_ID
    existing = await db.collaborators.find_one(
        {"id": sid, "company_id": company_id}, {"_id": 0, "id": 1})
    if existing:
        return sid
    # Outro tenant tem? Cria uma SALA com id distinto.
    other = await db.collaborators.find_one({"id": sid}, {"_id": 0, "company_id": 1})
    if other:
        sid = f"col-sala-{company_id}"
        existing = await db.collaborators.find_one(
            {"id": sid}, {"_id": 0})
        if existing:
            return sid
    await db.collaborators.insert_one({
        "id": sid,
        "name": "SALA",
        "cpf": f"SALA-VIRTUAL-{company_id}",
        "email": "", "phone": "",
        "role": "sala",
        "company_id": company_id,
        "company": "",
        "schedule": {}, "overtime_policy": {},
        "city": "", "state": "", "praca_id": None,
        "is_test_mode": False,
        "is_virtual": True,
        "virtual_kind": "sala_atendimento",
        "description": ("Lousa virtual SALA. Recebe agendamentos da "
                          "Isabella. Atendimento especializado distribui "
                          "para técnicos."),
        "atlaz_synced": False,
        "created_at": _now_iso(), "updated_at": _now_iso(),
        "clock_in_enabled": False,
        "active": True,
    })
    log.info("[isabella_actions] SALA criada para %s (id=%s)",
              company_id, sid)
    return sid


async def _pick_vacant_slot(*, company_id: str, sala_id: str,
                                 date_iso: str, window: str
                                 ) -> Optional[int]:
    """Retorna a próxima HORA cheia LIVRE dentro da janela.

    Slot = 1 hora cravada (ex.: manha → 09h, 10h, 11h).
    Considera apenas bolhas ATIVAS da SALA naquele dia.
    Retorna None se TODOS os slots da janela estiverem ocupados.
    """
    slots = WINDOW_SLOTS.get(window) or []
    if not slots:
        return None
    # Bolhas atuais da SALA naquele dia (active)
    cursor = db.tickets.find({
        "company_id": company_id,
        "assigned_collaborator_id": sala_id,
        "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]},
        "scheduled_time": {"$regex": f"^{date_iso}"},
    }, {"_id": 0, "scheduled_time": 1})
    occupied: set = set()
    async for t in cursor:
        st = t.get("scheduled_time") or ""
        # extrai HH do "YYYY-MM-DDTHH:MM:SS..."
        try:
            hh = int(st.split("T", 1)[1][:2])
            occupied.add(hh)
        except Exception:
            continue
    for h in slots:
        if h not in occupied:
            return h
    return None


async def _pick_default_collaborator(company_id: str) -> Optional[str]:
    """Mantido por compatibilidade. Isabella SEMPRE roteia para SALA
    agora — esta função retorna SALA."""
    return await _ensure_sala(company_id)


async def _create_visit_ticket(*, company_id: str, phone: str,
                                  subscriber_id: Optional[str],
                                  subscriber_name: Optional[str],
                                  date_iso: str,
                                  window: str,
                                  motivo: str) -> Dict[str, Any]:
    _, win_label = WINDOWS.get(window, WINDOWS["manha"])
    # SALA: roteia toda bolha da Isabella aqui.
    sala_id = await _ensure_sala(company_id)
    # Slot vago DENTRO da janela
    hour = await _pick_vacant_slot(
        company_id=company_id, sala_id=sala_id,
        date_iso=date_iso, window=window)
    if hour is None:
        # Janela cheia — sinaliza ao chamador (humanizer responde ao cliente).
        log.warning("[isabella_actions] janela cheia %s %s %s",
                      date_iso, window, company_id)
        return {"window_full": True,
                  "window": window, "window_label": win_label,
                  "scheduled_date": date_iso,
                  "br_date": _format_br_date(date_iso)}

    scheduled = f"{date_iso}T{hour:02d}:00:00+00:00"
    slot_label = f"{hour:02d}h"
    ticket_id = f"tkt-{uuid.uuid4().hex[:10]}"
    short = f"TK-{uuid.uuid4().hex[:7].upper()}"

    # próxima posição na fila da SALA
    last = await db.tickets.find(
        {"assigned_collaborator_id": sala_id,
         "status": {"$in": ["pendente", "aberta",
                              "aguardando_atendimento"]}},
        {"_id": 0, "position": 1}).sort("position", -1).to_list(1)
    next_pos = ((last[0].get("position") or 0) + 1) if last else 0

    ticket = {
        "id": ticket_id,
        "short_id": short,
        "company_id": company_id,
        "client_id": subscriber_id or str(uuid.uuid4()),
        "client_snapshot": {
            "name": subscriber_name or "Cliente WhatsApp",
            "address": "",
            "neighborhood": "",
            "phone": phone,
            "latitude": None, "longitude": None,
            "relato": motivo or "",
            "pppoe_user": "",
            "test_history": [],
        },
        "type": "reparo",
        "subject": (f"Visita técnica — {motivo[:80]}"
                     if motivo else "Visita técnica solicitada via WhatsApp"),
        "description": motivo or "",
        "priority": "horario",
        "scheduled_time": scheduled,
        "scheduled_window": window,
        "scheduled_window_label": win_label,
        "scheduled_slot_label": slot_label,
        "scheduled_date": date_iso,
        "position": next_pos,
        "status": "pendente",
        "assigned_collaborator_id": sala_id,
        "phone": phone,
        "subscriber_id": subscriber_id,
        "subscriber_name": subscriber_name,
        "source": "isabella_whatsapp",
        "auto_created_by_isabella": True,
        "needs_assignment_review": True,  # SALA exige distribuição
        "opened_at": None, "closed_at": None, "closed_by": None,
        "close_location": None, "outcome": None,
        "whatsapp_status": "nao_enviado",
        "whatsapp_last_message": None,
        "completion_data": None, "admin_action": None, "admin_notes": None,
        "ai_triage_pending": True,
        "signal_at_open": None, "signal_at_open_at": None,
        "signal_at_close": None, "signal_at_close_at": None,
        "created_at": _now_iso(),
        "created_by": "isabella",
    }
    await db.tickets.insert_one(ticket)
    try:
        from services.event_bus import emit_event
        await emit_event(
            "ticket.opened",
            company_id=company_id,
            source="isabella_actions",
            payload={"ticket_id": ticket_id, "short_id": short,
                       "type": "visita_tecnica",
                       "scheduled_date": date_iso,
                       "scheduled_hour": hour,
                       "queue": "SALA"},
        )
    except Exception:
        pass
    log.info("[isabella_actions] visita SALA ticket=%s short=%s phone=%s "
              "date=%s slot=%s window=%s", ticket_id, short, phone,
              date_iso, slot_label, window)
    return {"ticket_id": ticket_id, "short_id": short,
            "scheduled_date": date_iso, "window": window,
            "window_label": win_label,
            "slot_label": slot_label,
            "hour": hour,
            "assigned_collaborator_id": sala_id,
            "queue": "SALA",
            "br_date": _format_br_date(date_iso)}


async def _create_chamado(*, company_id: str, phone: str,
                            subscriber_id: Optional[str],
                            subscriber_name: Optional[str],
                            tipo: str,
                            motivo: str) -> Dict[str, Any]:
    tipo_norm = "tecnico" if "tec" in tipo.lower() else tipo.lower()
    ticket_id = f"tkt-{uuid.uuid4().hex[:10]}"
    short = f"TK-{uuid.uuid4().hex[:7].upper()}"
    assigned = await _pick_default_collaborator(company_id)
    next_pos = 0
    if assigned:
        last = await db.tickets.find(
            {"assigned_collaborator_id": assigned,
             "status": {"$in": ["pendente", "aberta",
                                  "aguardando_atendimento"]}},
            {"_id": 0, "position": 1}).sort("position", -1).to_list(1)
        next_pos = ((last[0].get("position") or 0) + 1) if last else 0
    ticket = {
        "id": ticket_id,
        "short_id": short,
        "company_id": company_id,
        "client_id": subscriber_id or str(uuid.uuid4()),
        "client_snapshot": {
            "name": subscriber_name or "Cliente WhatsApp",
            "address": "",
            "neighborhood": "",
            "phone": phone,
            "latitude": None, "longitude": None,
            "relato": motivo or "",
            "pppoe_user": "",
            "test_history": [],
        },
        "type": "reparo" if tipo_norm == "tecnico" else "instalacao",
        "subject": (f"Chamado {tipo_norm} — {motivo[:80]}"
                     if motivo else f"Chamado {tipo_norm} via WhatsApp"),
        "description": motivo or "",
        "priority": "normal",
        "status": "pendente",
        "position": next_pos,
        "assigned_collaborator_id": assigned,
        "phone": phone,
        "subscriber_id": subscriber_id,
        "subscriber_name": subscriber_name,
        "source": "isabella_whatsapp",
        "auto_created_by_isabella": True,
        "needs_assignment_review": assigned is None,
        "opened_at": None, "closed_at": None, "closed_by": None,
        "close_location": None, "outcome": None,
        "whatsapp_status": "nao_enviado",
        "whatsapp_last_message": None,
        "completion_data": None, "admin_action": None, "admin_notes": None,
        "ai_triage_pending": True,
        "signal_at_open": None, "signal_at_open_at": None,
        "signal_at_close": None, "signal_at_close_at": None,
        "created_at": _now_iso(),
        "created_by": "isabella",
    }
    await db.tickets.insert_one(ticket)
    try:
        from services.event_bus import emit_event
        await emit_event(
            "ticket.opened",
            company_id=company_id,
            source="isabella_actions",
            payload={"ticket_id": ticket_id, "short_id": short,
                       "tipo": tipo_norm,
                       "assigned_collaborator_id": assigned},
        )
    except Exception:
        pass
    log.info("[isabella_actions] chamado criado ticket=%s short=%s "
              "phone=%s tipo=%s assigned=%s",
              ticket_id, short, phone, tipo_norm, assigned)
    return {"ticket_id": ticket_id, "short_id": short, "tipo": tipo_norm,
            "assigned_collaborator_id": assigned}


def _format_br_date(date_iso: str) -> str:
    try:
        d = datetime.strptime(date_iso, "%Y-%m-%d").date()
        return d.strftime("%d/%m")
    except Exception:
        return date_iso


async def execute_action_markers(*, reply_text: str,
                                      company_id: str,
                                      phone: str,
                                      subscriber_id: Optional[str] = None,
                                      subscriber_name: Optional[str] = None
                                      ) -> Tuple[str, List[Dict[str, Any]]]:
    """Detecta marcadores em reply_text, executa as ações e substitui
    pelo texto de confirmação para o cliente.

    Retorna (reply_text_sem_marcadores, lista_ações_executadas).
    """
    actions_done: List[Dict[str, Any]] = []
    if not reply_text or "[" not in reply_text:
        return reply_text, actions_done

    # AGENDAR_VISITA
    async def _replace_agendar(match: re.Match) -> str:
        date_iso = match.group(1)
        window = match.group(2).lower()
        motivo = (match.group(3) or "").strip()
        try:
            result = await _create_visit_ticket(
                company_id=company_id, phone=phone,
                subscriber_id=subscriber_id,
                subscriber_name=subscriber_name,
                date_iso=date_iso, window=window, motivo=motivo)
            if result.get("window_full"):
                actions_done.append({"type": "schedule_visit_failed",
                                        "reason": "window_full",
                                        **result})
                return (f"A janela {result['window_label']} de "
                         f"{result['br_date']} está cheia. "
                         f"Posso te encaixar em outra janela?")
            actions_done.append({"type": "schedule_visit", **result})
            return (f"Marquei pra {result['br_date']} às "
                     f"{result['slot_label']} (janela "
                     f"{result['window_label']}) — protocolo "
                     f"{result['short_id']}.")
        except Exception as e:
            log.error("[isabella_actions] AGENDAR_VISITA falhou: %s", e)
            return ("Tive um problema ao registrar agora. "
                     "Vou repassar pro time e te confirmo.")

    # ABRIR_CHAMADO
    async def _replace_chamado(match: re.Match) -> str:
        tipo = match.group(1).lower()
        motivo = (match.group(2) or "").strip()
        try:
            result = await _create_chamado(
                company_id=company_id, phone=phone,
                subscriber_id=subscriber_id,
                subscriber_name=subscriber_name,
                tipo=tipo, motivo=motivo)
            actions_done.append({"type": "open_ticket", **result})
            return (f"Abri o chamado — protocolo {result['short_id']}. "
                     f"A equipe entra em contato.")
        except Exception as e:
            log.error("[isabella_actions] ABRIR_CHAMADO falhou: %s", e)
            return "Vou repassar pro time."

    # re.sub não suporta async replace; fazemos manualmente
    out = reply_text
    # AGENDAR
    while True:
        m = _AGENDAR_RX.search(out)
        if not m:
            break
        replacement = await _replace_agendar(m)
        out = out[:m.start()] + replacement + out[m.end():]
    # CHAMADO
    while True:
        m = _CHAMADO_RX.search(out)
        if not m:
            break
        replacement = await _replace_chamado(m)
        out = out[:m.start()] + replacement + out[m.end():]
    return out.strip(), actions_done


def actions_prompt_block() -> str:
    """Bloco a injetar no system_prompt da Isabella ensinando os marcadores."""
    return """
=== AÇÕES EXECUTÁVEIS NA LOUSA (PRIORIDADE MÁXIMA) ===

Você AGORA pode AGENDAR visitas e ABRIR chamados DIRETAMENTE no sistema.
NÃO peça permissão pro cliente confirmar "vou abrir, ok?". DECIDA com base
no que ele já disse e EXECUTE.

PARA AGENDAR UMA VISITA TÉCNICA:
Emita o marcador no FIM da sua resposta:
  [AGENDAR_VISITA data=YYYY-MM-DD janela=manha motivo="descrição curta"]

Janelas válidas (PERÍODOS, NÃO HORÁRIOS FIXOS):
  manha → o sistema vai colocar a bolha em um slot LIVRE entre 09h, 10h ou 11h
  tarde → o sistema vai colocar a bolha em um slot LIVRE entre 13h e 17h

REGRA CRÍTICA: você NUNCA escolhe a hora exata. Você OFERECE a janela
(manhã/tarde). O sistema valida a SALA e devolve a hora cravada DENTRO
da janela. Se a janela inteira estiver lotada, o sistema avisa e você
oferece outra janela.

A bolha é roteada para a Lousa SALA (atendimento especializado distribui
para o técnico depois). Você NÃO precisa escolher técnico.

Exemplo:
  Cliente: "Pode marcar pra amanhã manhã"
  Sua resposta: "Beleza, amanhã pela manhã. [AGENDAR_VISITA data=2026-02-11 janela=manha motivo=\"sinal não vinculado\"]"

O sistema vai SUBSTITUIR o marcador por algo como
"Marquei pra 11/02 às 09h (janela 09h-12h) — protocolo TK-ABC1234."
quando enviar pro cliente. O marcador NUNCA aparece pro cliente —
é executado no servidor.

PARA ABRIR UM CHAMADO (sem data marcada):
  [ABRIR_CHAMADO tipo=tecnico motivo="descrição"]

Tipos válidos: tecnico, comercial, suporte

REGRAS:
1. NÃO ofereça hora cravada ao cliente. Ofereça janela (manhã/tarde).
2. NÃO emita marcador se o cliente AINDA NÃO confirmou — só após ele
   dizer "sim" / "pode marcar" / "amanhã manhã".
3. UM marcador por resposta. Se precisar agendar + chamado, faça em 2 turns.
4. NUNCA escreva o marcador como "exemplo" ao cliente — ele só serve
   pro sistema executar.
5. Se o sistema responder "janela cheia", ofereça a outra janela ou
   uma data diferente.
""".strip()
