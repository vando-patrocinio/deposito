"""OPERAÇÃO ISABELLA AGENDA NA LOUSA.

Pipeline completo Isabella → diagnóstico → decisão → janela → confirmação
→ criação de OS (bolha) na Lousa → notificação → acompanhamento.

ZERO nova IA · ZERO nova Lousa · ZERO nova coleção.
Reusa: db.tickets (Lousa) · db.collaborators · db.subscribers ·
       services.truck_roll_guard · services.smartolt_client.

API pública:
  - classify_intent(user_text) -> str  (reparo|instalacao|retirada|...)
  - decide_action(company_id, subscriber_id, user_text) -> dict
        retorna {action, decision, rationale, signals}
  - find_available_slot(company_id, *, preferred_cargo, today_only=True)
        retorna {collaborator_id, name, scheduled_time, slot_label}
  - propose_window(company_id, subscriber_id, user_text) -> dict
        Junta decide_action + find_available_slot. NÃO cria OS.
  - confirm_and_create_os(company_id, subscriber_id, proposal,
                           confirmation_text="sim") -> dict
        Persiste em db.tickets. Replica para Lousa Mobile (mesmo doc).
  - followup_open_tickets_by_isabella(company_id, phone) -> list
        Tickets criados pela Isabella ainda em aberto.
"""
from __future__ import annotations
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db


# ---------------------------------------------------------------------------
# 1) Classificação de intenção
# ---------------------------------------------------------------------------
INTENT_PATTERNS: List[tuple] = [
    ("incidente_coletivo", re.compile(
        r"\b(rua\s+toda|prédio|condom[íi]nio|todos\s+os\s+vizinhos|"
        r"todo\s+(bairro|mundo))\b", re.IGNORECASE)),
    ("instalacao", re.compile(
        r"\b(quero\s+contratar|nova\s+instala|primeira\s+vez|"
        r"sou\s+novo|querer\s+(instalar|assinar))\b", re.IGNORECASE)),
    ("retirada", re.compile(
        r"\b(cancelar|encerrar|tirar\s+o\s+(plano|servi[çc]o)|"
        r"devolver\s+(o\s+)?equipamento)\b", re.IGNORECASE)),
    ("troca_equipamento", re.compile(
        r"\b(trocar\s+(o\s+)?(modem|onu|roteador|equipamento))\b",
        re.IGNORECASE)),
    ("financeiro", re.compile(
        r"\b(2[ªa]?\s*via|segunda\s+via|boleto|pagar|fatura|"
        r"negocia|atrasad|atraso\b|cobran[çc]a)\b", re.IGNORECASE)),
    ("venda", re.compile(
        r"\b(upgrade|plano\s+mais|playhub|ligo\s+(security|m[óo]vel)|"
        r"ip\s+fixo|combo|aumentar\s+velocidade)\b", re.IGNORECASE)),
    ("retencao", re.compile(
        r"\b(quero\s+cancelar|estou\s+pensando\s+em\s+sair|caro\s+demais)\b",
        re.IGNORECASE)),
    ("reparo", re.compile(
        r"\b(sem\s+internet|caiu|offline|lento|lerdo|wifi|"
        r"sinal|fibra|modem|roteador|onu|n[ãa]o\s+funciona)\b",
        re.IGNORECASE)),
]


def classify_intent(user_text: str) -> str:
    """Devolve 1 intenção do conjunto fixo."""
    if not user_text:
        return "duvida_simples"
    for tag, pat in INTENT_PATTERNS:
        if pat.search(user_text):
            return tag
    return "duvida_simples"


# ---------------------------------------------------------------------------
# 2) Decisão antes da OS (reusa truck_roll_guard)
# ---------------------------------------------------------------------------
async def decide_action(company_id: str, subscriber_id: Optional[str],
                          user_text: str) -> Dict[str, Any]:
    """Decisão central. Action ∈ {NO_OS, DISPATCH, ESCALATE_COLLECTIVE, ASK_MORE_INFO}."""
    intent = classify_intent(user_text)
    if intent in ("financeiro", "venda", "duvida_simples", "retencao"):
        return {"action": "NO_OS", "intent": intent,
                "rationale": "intenção não exige visita técnica"}

    if not subscriber_id:
        return {"action": "ASK_MORE_INFO", "intent": intent,
                "rationale": "subscriber_id não resolvido — pedir endereço/CPF"}

    # Reusa truck_roll_guard.evaluate
    try:
        from services.truck_roll_guard import evaluate as trg_evaluate
        trg = await trg_evaluate(company_id, subscriber_id)
    except Exception as e:
        trg = {"decision": "DISPATCH", "confidence": 0.5,
                "rationale": f"truck_roll_guard offline: {e}",
                "signals": {}}

    decision = trg.get("decision", "DISPATCH")
    if decision == "DO_NOT_DISPATCH":
        action = "NO_OS"
    elif decision == "INCIDENTE_COLETIVO":
        action = "ESCALATE_COLLECTIVE"
    elif decision == "PREVENTIVA":
        action = "DISPATCH"
    else:
        action = "DISPATCH"

    return {
        "action": action, "intent": intent,
        "decision": decision,
        "confidence": trg.get("confidence"),
        "rationale": trg.get("rationale"),
        "signals": trg.get("signals"),
    }


# ---------------------------------------------------------------------------
# 3) Janela disponível — consulta Lousa real
# ---------------------------------------------------------------------------
# Grade Lousa: 09:00-18:00 (regra do TicketIn._validate_scheduled_time)
# Slots de 1h. Período da tarde = 13-18h.
LOUSA_OPEN_HOUR = 9
LOUSA_CLOSE_HOUR = 18
DEFAULT_CARGO = "tecnico_rede"


async def find_available_slot(company_id: str, *,
                                 preferred_cargo: str = DEFAULT_CARGO,
                                 today_only: bool = True
                                 ) -> Optional[Dict[str, Any]]:
    """Encontra o primeiro técnico+horário livre. Estratégia:
       1. Pega todos os colaboradores com cargo desejado.
       2. Para cada um, conta tickets em status pendente/aberta hoje.
       3. Escolhe o de MENOR carga.
       4. Sugere a próxima hora livre (após `now` se for hoje).
    """
    cur = db.collaborators.find(
        {"company_id": company_id,
         "$or": [{"cargo": preferred_cargo},
                  {"cargo": {"$in": ["tecnico_rede", "tecnico_instalacao",
                                       "tecnico_externo", "tecnico"]}}]},
        {"_id": 0, "id": 1, "name": 1, "cargo": 1})
    techs = await cur.to_list(50)
    if not techs:
        # fallback: qualquer colaborador
        cur = db.collaborators.find(
            {"company_id": company_id},
            {"_id": 0, "id": 1, "name": 1, "cargo": 1})
        techs = await cur.to_list(50)
    if not techs:
        return None

    now = datetime.now(timezone.utc)
    # Conta carga
    loads: List[tuple] = []
    for t in techs:
        n = await db.tickets.count_documents({
            "assigned_collaborator_id": t["id"],
            "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]},
            "company_id": company_id,
        })
        loads.append((n, t))
    loads.sort(key=lambda x: x[0])

    # Para cada técnico em ordem de menor carga, encontra um slot livre
    target_date = now.date() if today_only else now.date()
    for load, tech in loads:
        # Horários já ocupados deste técnico no dia
        busy: set = set()
        async for tk in db.tickets.find(
                {"assigned_collaborator_id": tech["id"],
                 "company_id": company_id,
                 "scheduled_time": {"$regex": f"^{target_date.isoformat()}"}},
                {"_id": 0, "scheduled_time": 1}):
            try:
                dt = datetime.fromisoformat(tk["scheduled_time"])
                busy.add(dt.hour)
            except Exception:
                pass

        # Hora mínima — se hoje, no mínimo 1h após now
        if target_date == now.date():
            min_hour = max(LOUSA_OPEN_HOUR, now.hour + 1)
        else:
            min_hour = LOUSA_OPEN_HOUR

        for hour in range(min_hour, LOUSA_CLOSE_HOUR):
            if hour in busy:
                continue
            scheduled = datetime(target_date.year, target_date.month,
                                   target_date.day, hour, 0,
                                   tzinfo=timezone.utc)
            # Janela = 1h
            window_label = f"{hour:02d}h às {hour+1:02d}h"
            return {
                "collaborator_id": tech["id"],
                "collaborator_name": tech["name"],
                "cargo": tech.get("cargo"),
                "scheduled_time": scheduled.strftime("%Y-%m-%dT%H:%M"),
                "scheduled_date": target_date.isoformat(),
                "window_label": window_label,
                "current_load": load,
            }
    # Nada hoje → tenta amanhã
    if today_only:
        return await find_available_slot(company_id,
                                            preferred_cargo=preferred_cargo,
                                            today_only=False)
    return None


# ---------------------------------------------------------------------------
# 4) Propor janela (DECIDIR + ACHAR SLOT) — sem criar OS
# ---------------------------------------------------------------------------
async def propose_window(company_id: str, subscriber_id: Optional[str],
                            user_text: str) -> Dict[str, Any]:
    decision = await decide_action(company_id, subscriber_id, user_text)
    if decision["action"] != "DISPATCH":
        return {"decision": decision, "slot": None,
                "proposal_text": None}

    # Cargo por intenção
    cargo_map = {
        "instalacao": "tecnico_instalacao",
        "retirada": "tecnico_instalacao",
        "troca_equipamento": "tecnico_instalacao",
        "reparo": "tecnico_rede",
    }
    pref = cargo_map.get(decision["intent"], DEFAULT_CARGO)
    slot = await find_available_slot(company_id, preferred_cargo=pref)
    if not slot:
        return {"decision": decision, "slot": None,
                "proposal_text": (
                    "Não tenho horário disponível para hoje. "
                    "Posso reservar para amanhã pela manhã?"
                )}
    return {
        "decision": decision, "slot": slot,
        "proposal_text": (
            f"Consigo agendar uma visita para hoje, das {slot['window_label']}. "
            "Pode ter alguém no local nesse período?"
        ),
    }


# ---------------------------------------------------------------------------
# 5) Criar OS na Lousa (bolha) após confirmação
# ---------------------------------------------------------------------------
async def confirm_and_create_os(*, company_id: str,
                                   subscriber_id: Optional[str],
                                   phone: str,
                                   user_text: str,
                                   proposal: Dict[str, Any],
                                   confirmation_text: str = "sim"
                                   ) -> Dict[str, Any]:
    """Cria 1 OS (bolha) em db.tickets, após confirmação do cliente.

    Idempotência: se já existe ticket criado por isabella nas últimas 4h
    para o mesmo subscriber/phone com status aberto, retorna o existente.
    """
    if not proposal or not proposal.get("slot"):
        return {"error": "sem slot proposto"}
    decision = proposal["decision"]
    slot = proposal["slot"]

    # Idempotência
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
    existing = await db.tickets.find_one({
        "company_id": company_id,
        "origin": "isabella",
        "$or": [
            {"client_snapshot.subscriber_id": subscriber_id} if subscriber_id else {"_x": 1},
            {"client_snapshot.phone": phone},
        ],
        "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]},
        "created_at": {"$gte": cutoff},
    }, {"_id": 0})
    if existing:
        return {"ticket": existing, "duplicate": True}

    # Carrega subscriber para snapshot
    sub: Dict[str, Any] = {}
    if subscriber_id:
        sub = await db.subscribers.find_one(
            {"id": subscriber_id, "company_id": company_id},
            {"_id": 0, "name": 1, "address": 1, "neighborhood": 1,
             "phones": 1, "pppoe": 1, "pppoe_user": 1, "login": 1,
             "id": 1, "cto_id": 1, "olt_name": 1}) or {}

    intent = decision.get("intent") or "reparo"
    intent_to_type = {
        "instalacao": "instalacao",
        "retirada": "retirada",
        "troca_equipamento": "reparo",
        "reparo": "reparo",
    }
    ticket_type = intent_to_type.get(intent, "reparo")

    # Prioridade
    priority = "normal"
    if decision.get("decision") == "PREVENTIVA":
        priority = "horario"
    if (decision.get("signals") or {}).get("tickets_30d", 0) >= 3:
        priority = "prioridade"

    tid = f"tkt-{uuid.uuid4().hex[:10]}"
    pppoe = sub.get("pppoe") or sub.get("pppoe_user") or sub.get("login") or ""
    address = sub.get("address") or "—"
    relato = (user_text or "")[:280]
    obs_tecnico = (
        f"Diagnóstico Isabella: {decision.get('rationale', '—')}. "
        f"Truck Roll: {decision.get('decision')} ({decision.get('confidence')}). "
        f"Intenção: {intent}."
    )

    doc = {
        "id": tid,
        "client_id": subscriber_id or str(uuid.uuid4()),
        "client_snapshot": {
            "name": sub.get("name") or "Cliente",
            "address": address,
            "neighborhood": sub.get("neighborhood") or "",
            "phone": phone,
            "latitude": None, "longitude": None,
            "relato": relato,
            "pppoe_user": pppoe,
            "subscriber_id": subscriber_id,
            "test_history": [],
        },
        "type": ticket_type,
        "priority": priority,
        "scheduled_time": slot["scheduled_time"],
        "scheduled_window": slot["window_label"],
        "position": 0,
        "status": "aberta",  # agendada e visível
        "assigned_collaborator_id": slot["collaborator_id"],
        "company_id": company_id,
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "closed_at": None, "closed_by": None,
        "outcome": None,
        "whatsapp_status": "nao_enviado",
        "completion_data": None,
        "ai_triage_pending": False,
        "signal_at_open": (decision.get("signals") or {}).get("onu"),
        "signal_at_open_at": datetime.now(timezone.utc).isoformat(),
        # Campos Isabella
        "origin": "isabella",
        "isabella_decision": decision,
        "isabella_obs_tecnico": obs_tecnico,
        "isabella_confirmation": confirmation_text,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.tickets.insert_one(doc)

    # Log
    try:
        await db.ticket_logs.insert_one({
            "id": f"tlog-{uuid.uuid4().hex[:10]}",
            "ticket_id": tid, "company_id": company_id,
            "action": "criada_por_isabella",
            "actor_id": "isabella", "actor_name": "Isabella",
            "actor_role": "ai",
            "details": obs_tecnico,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass

    # Mensagem para o cliente
    short_id = tid.replace("tkt-", "#")[:8]
    customer_message = (
        f"PLANO_DE_ACAO: sua visita ficou agendada para hoje, das "
        f"{slot['window_label']}. OS {short_id}. "
        "Vou acompanhar por aqui até a conclusão.\n"
        "Outcome: PLANO_DE_ACAO"
    )
    doc.pop("_id", None)
    return {
        "ticket": doc, "duplicate": False,
        "customer_message": customer_message,
        "short_id": short_id,
    }


# ---------------------------------------------------------------------------
# 6) Follow-up — Isabella acompanha tickets abertos criados por ela
# ---------------------------------------------------------------------------
async def followup_open_tickets_by_isabella(company_id: str,
                                              phone: Optional[str] = None
                                              ) -> List[Dict[str, Any]]:
    q = {"company_id": company_id, "origin": "isabella",
         "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]}}
    if phone:
        q["client_snapshot.phone"] = phone
    out: List[Dict[str, Any]] = []
    async for t in db.tickets.find(q, {"_id": 0}).sort("created_at", -1).limit(50):
        out.append(t)
    return out
