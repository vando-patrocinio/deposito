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


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "operacoes",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["ticket.updated"],
    "company_id_required": True,
}

import json
import logging
import re
import uuid

import httpx
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

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
TicketType = Literal["reparo", "instalacao", "retirada", "prioridade", "preventiva", "venda", "rompimento"]
TicketStatus = Literal[
    "pendente", "aberta", "aguardando_atendimento",
    "finalizada", "encerrada", "reagendada", "cancelada"
]
Outcome = Literal["sucesso", "informada"]

POINTS_BY_TYPE: Dict[str, float] = {
    "instalacao": 3.0, "retirada": 1.5, "reparo": 1.0,
    "prioridade": 2.5, "preventiva": 1.5, "venda": 2.0,
    "rompimento": 2.5,
}
PRIORITY_RANK = {"urgente": -1, "prioridade": 0, "horario": 1, "normal": 2}
# Aliases PT-BR uppercase usados pelos serviços de IA (autonomous_engine,
# isabella_churn_to_sala, financial_foundation, smartolt_predictive).
# Mantém o lookup defensivo para nunca crashar a Lousa com KeyError.
PRIORITY_ALIASES = {
    "ALTA": -1, "MEDIA": 0, "MÉDIA": 0, "BAIXA": 2,
    "CRITICA": -2, "CRÍTICA": -2, "BLOCKER": -2,
    "alta": -1, "media": 0, "média": 0, "baixa": 2,
}


def _prio_rank(value):
    """Lookup defensivo de prioridade — nunca crasha, default 99."""
    if value in PRIORITY_RANK:
        return PRIORITY_RANK[value]
    if value in PRIORITY_ALIASES:
        return PRIORITY_ALIASES[value]
    return 99
ADMIN_RESOLVED = ("encerrada", "reagendada", "cancelada")
TECH_RESOLVED = ("finalizada",)



# =============================================================================
# Normalização de client_snapshot — protege contra crashes no frontend
# (helpers movidos para /app/backend/utils/normalize.py; mantido alias local)
# =============================================================================
from utils.normalize import (
    norm_string as _norm_string,
    normalize_fields as _normalize_client_snapshot,
)


# ---------------------------------------------------------------------------
# iter215aa — Helper centralizado pra vincular cliente à porta da CTO com
# regras de exclusividade:
#   1. Se a porta destino já tem OUTRO cliente → bloqueia (HTTP 409)
#   2. Se o cliente já está em OUTRA porta → libera a antiga (port_swap)
#   3. Idempotente: se já tá vinculado à mesma porta, no-op
# Substitui os `db.ctos.update_one` brutos que faziam o vínculo sem checar
# se a porta estava livre, permitindo sobrescrever cliente alheio.
# ---------------------------------------------------------------------------
async def _smart_link_client_to_port(
    *, company_id: str, cto_id: str, port_number: int,
    client_id: Optional[str], client_name: Optional[str],
    client_pppoe: Optional[str], actor_email: Optional[str],
    actor_id: Optional[str], actor_name: Optional[str],
    ticket_id: Optional[str] = None,
) -> dict:
    """Vincula cliente à porta da CTO seguindo as regras de exclusividade.

    Retorna {ok, action, message, prev_cto_id?, prev_port_number?}.
    Lança HTTPException(409) se a porta destino estiver ocupada por
    outro cliente.
    """
    from fastapi import HTTPException as _HE
    from routes.stok import (
        _find_client_cto_port, _free_cto_port, _occupy_cto_port,
    )
    port_number = int(port_number)
    # 1) Cliente já está em alguma porta? (XOR atribuição vs swap)
    current = None
    if client_id:
        current = await _find_client_cto_port(company_id, client_id)
    if (current and current["cto_id"] == cto_id
            and int(current["port_number"]) == port_number):
        return {"ok": True, "action": "noop",
                "message": "Cliente já vinculado a esta porta"}
    # 2) Verifica se a porta destino tem cliente diferente
    target_cto = await db.ctos.find_one(
        {"id": cto_id, "company_id": company_id},
        {"_id": 0, "id": 1, "name": 1, "ports": 1},
    )
    if not target_cto:
        raise _HE(404, f"CTO {cto_id} não encontrada")
    target_port = next(
        (p for p in (target_cto.get("ports") or [])
         if int(p.get("number") or 0) == port_number),
        None,
    )
    if not target_port:
        raise _HE(404,
                  f"Porta {port_number} não existe na CTO {target_cto.get('name')}")
    existing_client_id = target_port.get("client_subscriber_id")
    is_occupied_by_other = (
        target_port.get("status") == "used"
        and existing_client_id
        and existing_client_id != client_id
    )
    if is_occupied_by_other:
        raise _HE(409, {
            "code": "CTO_PORT_OCCUPIED_BY_OTHER",
            "message": (
                f"A porta {port_number} da CTO "
                f"{target_cto.get('name') or cto_id} já está OCUPADA "
                f"pelo cliente '{target_port.get('client_name') or '?'}'. "
                "Cada porta só pode ter UM cliente ativo. Para vincular "
                "este cliente aqui, primeiro retire o cliente atual "
                "(OS de retirada) ou escolha outra porta livre."
            ),
            "occupied_by": {
                "client_subscriber_id": existing_client_id,
                "client_name": target_port.get("client_name"),
            },
        })
    # 3) Ocupa a nova porta (idempotente se for o mesmo cliente)
    is_swap = current is not None
    ok = await _occupy_cto_port(
        company_id, cto_id, port_number, client_id, client_name,
        client_pppoe, actor_email,
        actor_name=actor_name, ticket_id=ticket_id,
        is_swap=is_swap,
        prev_cto_id=current["cto_id"] if current else None,
        prev_port_number=current["port_number"] if current else None,
    )
    if not ok:
        # Não deveria chegar aqui (já checamos acima), mas resguarda.
        raise _HE(409, "Não foi possível vincular cliente à porta")
    # 4) Libera porta antiga (port_swap)
    freed_msg = None
    if current and (current["cto_id"] != cto_id
                    or int(current["port_number"]) != port_number):
        await _free_cto_port(
            company_id, current["cto_id"], int(current["port_number"]),
            actor_email, "port_swap",
            client_id=None,  # já logado como port_swap em _occupy_cto_port
        )
        freed_msg = (f"Porta antiga {current['port_number']} "
                     f"({current.get('cto_name') or current['cto_id']}) liberada")
    # 5) Registra connected_via_ticket (rastreabilidade adicional)
    if ticket_id:
        await db.ctos.update_one(
            {"id": cto_id, "company_id": company_id,
             "ports.number": port_number},
            {"$set": {
                "ports.$.connected_at": now_iso(),
                "ports.$.connected_via_ticket": ticket_id,
            }},
        )
    action = "swap" if is_swap else "link"
    msg = (f"Cliente vinculado à porta {port_number}"
           + (f"; {freed_msg}" if freed_msg else ""))
    return {
        "ok": True, "action": action, "message": msg,
        "prev_cto_id": current["cto_id"] if current else None,
        "prev_port_number": (int(current["port_number"])
                             if current else None),
    }


def _normalize_ticket(t: dict) -> dict:
    """Aplica normalização defensiva a um ticket inteiro antes de retornar.

    Não muta o input — retorna shallow copy com client_snapshot saneado.
    """
    if not t:
        return t
    if t.get("client_snapshot"):
        t["client_snapshot"] = _normalize_client_snapshot(t["client_snapshot"])
    return t

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

    Prioridade dos campos (iter211z — Atlaz date preservation):
      1. scheduled_time (data de serviço efetiva — visit_date do Atlaz quando
         disponível, senão data de criação Atlaz preenchida por _resolve_schedule)
      2. opened_at (quando começou)
      3. atlaz_created_at (data ORIGINAL do chamado no Atlaz — evita que
         bolhas importadas hoje caiam em "hoje" quando o Atlaz não enviou
         visit_date)
      4. created_at (quando foi criada localmente — fallback final)
    Retorna string vazia se nenhum disponível ou inválido.
    """
    raw = (ticket.get("scheduled_time") or ticket.get("opened_at")
           or ticket.get("atlaz_created_at") or ticket.get("created_at"))
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
    # iter174 — SN da ONT como alternativa ao MAC para RETIRADA. Se o OCR
    # detectar SN mas não MAC, o backend usa SN para localizar a ONT.
    ont_sn: Optional[str] = None
    fotos: List[Any] = Field(default_factory=list)  # str (data url) ou dict {kind, dataUrl}
    observacoes: Optional[str] = None
    # Vínculo cliente ↔ CTO/porta (todos os tipos de OS)
    cto_id: Optional[str] = None
    cto_name: Optional[str] = None
    cto_port_number: Optional[int] = None
    cto_splitter: Optional[str] = None
    cto_vlan: Optional[int] = None
    cto_network_type: Optional[str] = None
    # Fibra adicional (já existia mas faltava no model)
    fibra_06fo: float = 0
    fibra_12fo: float = 0
    fibra_24fo: float = 0
    # === Troca de ONT/ONU (reparo) — opcional, o técnico pode informar
    # explicitamente os MACs antigo (retirado) e novo (instalado). Quando não
    # informado, o backend tenta auto-detectar via SmartOLT (cache).
    old_ont_mac: Optional[str] = None
    old_ont_sn: Optional[str] = None
    new_ont_mac: Optional[str] = None
    new_ont_sn: Optional[str] = None
    # Motivo do cancelamento (categoria) — preenchido SOMENTE em OS de retirada.
    # Usado pelo KPI de retenção e pelo dashboard de churn.
    # Valores aceitos: preco | atendimento | qualidade | mudanca | concorrente
    #                  | financeiro | nao_usa | outros
    cancel_reason_category: Optional[str] = None
    # Retirada: equipamento com defeito? Quando true, a ONT NÃO volta como
    # "retirada_com_tecnico" (reaproveitável). Em vez disso, é marcada como
    # "defeito_devolver_empresa" e fica bloqueada para reinstalar. Pedido
    # do user 28/05/2026.
    is_defective: Optional[bool] = False
    defective_reason: Optional[str] = None  # opcional, texto livre do técnico
    # === V9 P2 — Smart Field derived fields ============================
    # Backward-compatible: todos opcionais. Técnico preenche quando faz
    # sentido pelo tipo de OS; sistema usa em company_v6 para calcular
    # truck_roll_avoidance, asset_recovery, reopened_within_7d.
    resolution_kind: Optional[Literal["remote", "onsite"]] = None  # REPAIR
    asset_recovered: Optional[bool] = None                          # WITHDRAW
    signed_receipt: Optional[bool] = None                           # WITHDRAW


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
    # CTO 13/06/2026 — Contrato OS único: rastreabilidade da origem.
    origin: Optional[str] = None  # "isabella" | "atendimento" | "manual" | "api"
    created_by_agent: Optional[str] = None  # "isabella" | nome do gestor | ...
    isabella_context: Optional[dict] = None  # contexto livre da IA (opportunity_id, etc)

    @field_validator("scheduled_time")
    @classmethod
    def _validate_scheduled_time(cls, v):
        # Grade da Lousa: 09:00–18:00 (inclusivo). Aceita formatos
        # "YYYY-MM-DDTHH:MM" ou ISO completo. Rejeita horas fora da grade.
        if not v:
            return v
        try:
            # extrai HH:MM
            import re
            m = re.search(r"T(\d{2}):(\d{2})", v)
            if not m:
                return v  # formato inesperado — não bloqueia
            h = int(m.group(1))
            mn = int(m.group(2))
            if h < 9:
                raise ValueError(f"Horário {h:02d}:{mn:02d} antes da grade (09:00).")
            if h > 18 or (h == 18 and mn > 0):
                raise ValueError(f"Horário {h:02d}:{mn:02d} após a grade (18:00).")
        except ValueError:
            raise
        except Exception:
            pass
        return v


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
    # CTO 2026-02 — REGRA GLOBAL ESTOQUE OS (Q1=c híbrido).
    # Quando o gestor declarar physical_attendance=true, exigimos SN/MAC
    # e o guardrail movimenta estoque. Quando false, exige admin_reason
    # (motivo) e NÃO movimenta.
    physical_attendance: Optional[bool] = None
    admin_reason: Optional[str] = None
    smartolt_override_motivo: Optional[str] = None


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


# ---------------------------------------------------------------------------
# SmartOLT cross-check helpers (auto-detect ONT/ONU swap + relax rules
# for clients que não estão cadastrados na SmartOLT).
# ---------------------------------------------------------------------------
def _norm_hexid(s: Optional[str]) -> str:
    """Normaliza um MAC/SN para comparação (remove separadores e espaços,
    devolve UPPER). Aceita MAC (12 hex), SN da ONU (ex.: ALCLFC090E99)
    e qualquer formato livre."""
    if not s:
        return ""
    return "".join(c for c in str(s).upper() if c.isalnum())


async def _resolve_smartolt_for_ticket(ticket: dict) -> Optional[dict]:
    """Resolve o documento da ONU no cache `smartolt_onus` para um ticket.
    Retorna None quando o cliente NÃO está cadastrado no SmartOLT — neste caso
    todas as regras dependentes do SmartOLT (sinal bloqueante, sn_mismatch,
    snapshot, detecção de troca) devem ser puladas (pedido do usuário)."""
    try:
        from routes.smartolt import resolve_signal_for_ticket
        return await resolve_signal_for_ticket(ticket)
    except Exception as e:
        logger.warning("[lousa] resolve_smartolt_for_ticket falhou: %s", e)
        return None


def _detect_equipment_swap(ticket: dict, cd: "CompletionData",
                              smartolt_onu: Optional[dict]) -> Optional[dict]:
    """Detecta se a finalização representa uma troca de ONT/ONU.

    Regras:
      - Tipos elegíveis: `reparo` (a troca em reparo é o caso clássico).
        `troca_endereco` também é considerado, pois pode envolver swap.
      - Cliente PRECISA estar no SmartOLT (do contrário não há MAC/SN antigo
        confiável pra comparar). Se o técnico informar `old_ont_mac/sn`
        manualmente, aceitamos mesmo sem SmartOLT.
      - É considerado swap quando o MAC/SN novo informado (`cd.new_ont_sn`,
        `cd.new_ont_mac` ou fallback `cd.ont`) é DIFERENTE do registrado no
        SmartOLT (ou do `old_ont_mac/sn` informado manualmente).

    Retorna um dict com `{old_mac, old_sn, new_mac, new_sn, source}` ou None
    quando não há troca.
    """
    t_type = (ticket or {}).get("type") or ""
    if t_type not in ("reparo", "troca_endereco"):
        return None

    # Resolve novo MAC/SN — pode vir explícito ou via `cd.ont` (legado).
    new_sn = cd.new_ont_sn or cd.ont or ""
    new_mac = cd.new_ont_mac or ""
    if not (new_sn or new_mac):
        return None

    # Resolve antigo MAC/SN — preferência: manual (técnico informou) →
    # SmartOLT cache (auto-derivado).
    old_sn = (cd.old_ont_sn or "").strip()
    old_mac = (cd.old_ont_mac or "").strip()
    source = "manual"
    if (not old_sn) and (not old_mac) and smartolt_onu:
        old_sn = (smartolt_onu.get("sn") or "").strip()
        old_mac = (smartolt_onu.get("mac")
                    or smartolt_onu.get("ont_mac") or "").strip()
        source = "smartolt_cache"
    if not (old_sn or old_mac):
        return None  # sem referência → não é possível afirmar swap

    # Compara — qualquer dos hexids antigos batendo com o novo = NÃO é swap
    new_norm = {_norm_hexid(new_sn), _norm_hexid(new_mac)} - {""}
    old_norm = {_norm_hexid(old_sn), _norm_hexid(old_mac)} - {""}
    if not new_norm or not old_norm:
        return None
    if new_norm & old_norm:
        return None  # mesmo equipamento — não houve troca
    return {
        "old_mac": old_mac or None,
        "old_sn": old_sn or None,
        "new_mac": new_mac or None,
        "new_sn": new_sn or None,
        "source": source,        # "manual" | "smartolt_cache"
        "detected_at": now_iso(),
    }


async def _persist_equipment_swap(ticket_id: str, company_id: str,
                                       swap: dict, technician_id: str,
                                       technician_name: str) -> None:
    """Grava registro de auditoria de troca de ONT/ONU em
    `equipment_swaps`. Idempotente (chave: ticket_id)."""
    try:
        verif = swap.get("verification") or {}
        doc = {
            "id": f"swap-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "ticket_id": ticket_id,
            "technician_id": technician_id,
            "technician_name": technician_name,
            "old_mac": swap.get("old_mac"),
            "old_sn": swap.get("old_sn"),
            "new_mac": swap.get("new_mac"),
            "new_sn": swap.get("new_sn"),
            "source": swap.get("source"),
            # Verificação via uptime SmartOLT
            "verified": verif.get("verified"),       # True / False / None
            "verification_reason": verif.get("reason"),
            "uptime_seconds_at_close": verif.get("uptime_seconds"),
            "uptime_minutes_at_close": verif.get("uptime_minutes"),
            "last_status_change": verif.get("last_status_change"),
            "onu_status_at_close": verif.get("status"),
            "threshold_minutes": verif.get(
                "threshold_minutes", SWAP_UPTIME_THRESHOLD_MINUTES),
            "created_at": now_iso(),
        }
        # upsert por ticket_id pra não duplicar se finalize for chamado 2x
        await db.equipment_swaps.update_one(
            {"company_id": company_id, "ticket_id": ticket_id},
            {"$set": doc}, upsert=True,
        )
    except Exception as e:
        logger.warning("[lousa] persist_equipment_swap falhou: %s", e)


# Janela mínima (em minutos) que define uma troca de ONT/ONU LEGÍTIMA:
# se a ONU está online há mais que isso (sem reboot recente), a troca
# declarada pelo técnico é considerada SUSPEITA — equipamento provavelmente
# não foi realmente substituído (não passou pelo reboot que acompanha a troca).
SWAP_UPTIME_THRESHOLD_MINUTES = 10


def _parse_smartolt_ts(ts: Optional[str]) -> Optional[datetime]:
    """Converte timestamps comuns do SmartOLT ('YYYY-MM-DD HH:MM:SS' ou ISO)
    para `datetime` aware (UTC). Retorna None em qualquer falha."""
    if not ts:
        return None
    try:
        s = str(ts).strip().replace("Z", "+00:00")
        if " " in s and "T" not in s:
            s = s.replace(" ", "T", 1)
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


async def _verify_swap_via_uptime(smartolt_onu: Optional[dict],
                                          threshold_minutes: int = SWAP_UPTIME_THRESHOLD_MINUTES,
                                          ) -> dict:
    """Verifica se a troca declarada pelo técnico é coerente com o estado
    REAL da ONU no SmartOLT (uptime / último status change).

    Regra (pedido do usuário, 22/02/2026):
      Se a ONU NÃO foi desligada nas últimas N (=10) minutos, a troca não pôde
      ter ocorrido — toda substituição física implica reboot. Marcamos o
      registro como `verified=false` e o motivo `uptime_too_high` ou
      `no_recent_disconnect`. Vai pro card de auditoria mensal.

    Quando não há cache SmartOLT (cliente não mapeado), retorna
    `verified=null, reason="no_smartolt_mapping"` — ou seja, sem dado, sem
    julgamento (não é "suspeito", é apenas "não verificável").
    """
    out: Dict[str, Any] = {
        "verified": None, "reason": None,
        "uptime_seconds": None, "uptime_minutes": None,
        "last_status_change": None, "status": None,
        "threshold_minutes": threshold_minutes,
        "checked_at": now_iso(),
    }
    if not smartolt_onu:
        out["reason"] = "no_smartolt_mapping"
        return out

    last_change = smartolt_onu.get("last_status_change")
    status_str = (smartolt_onu.get("status") or "").lower()
    out["last_status_change"] = last_change
    out["status"] = status_str

    # Se a ONU está LOS/offline/power_off neste momento, ela acabou de cair —
    # podemos assumir que está num momento de transição (provavelmente
    # justamente sendo trocada). Não rejeita.
    if status_str and status_str != "online":
        out["verified"] = True
        out["reason"] = f"status_{status_str}"
        return out

    dt = _parse_smartolt_ts(last_change)
    if not dt:
        # Sem timestamp confiável — não rejeita nem confirma.
        out["reason"] = "no_last_status_change"
        return out

    delta = datetime.now(timezone.utc) - dt
    secs = max(int(delta.total_seconds()), 0)
    out["uptime_seconds"] = secs
    out["uptime_minutes"] = secs // 60

    if secs <= threshold_minutes * 60:
        out["verified"] = True
        out["reason"] = "recent_reboot"  # ONU rebootou recentemente → troca coerente
    else:
        out["verified"] = False
        out["reason"] = "uptime_too_high"  # ONU online há > N min sem reboot
    return out








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

    # company_id resolvido cedo — usado por emit_event + validacao de slot.
    company_id = (user.get("company_id")
                    or t.get("company_id")
                    or DEMO_COMPANY_ID)

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
    try:
        from services.event_bus import emit_event
        await emit_event(
            "ticket.updated",
            company_id=company_id,
            source="lousa",
            payload={},
        )
    except Exception:
        pass
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


# ╭───────────────────────────────────────────────────────────────────────╮
# │ OPERAÇÃO TICKET ARMADO (CTO 2026-02)                                   │
# │ P0-3 + P0-4 + P0-5 + P0-6 + P0-7 — endpoint único que entrega ao     │
# │ frontend tudo que o técnico precisa pra não ir cego pra campo:        │
# │   - live_signal já classificado (LOS / ATENUACAO / SAUDAVEL)          │
# │   - cache_label com timestamp ("CACHE · há Xmin")                     │
# │   - degradation_alert (queda detectada nas últimas 72h)               │
# │   - Profile alert (Generic_X)                                         │
# │   - Botão Live: passar ?force=true invalida cache e refaz SmartOLT    │
# ╰───────────────────────────────────────────────────────────────────────╯
@router.get("/tickets/{ticket_id}/armed-signal")
async def ticket_armed_signal(
    ticket_id: str,
    force: bool = False,
    max_age_seconds: int = 300,
    user: dict = Depends(require_role("gestor", "tecnico", "supervisor",
                                       "administrador", "auditor")),
):
    """Retorna o pacote completo de sinal para tornar o ticket ARMADO.

    Args:
        force: se True, invalida o cache do SmartOLT e refaz consulta live.
               Usado pelo botão "Live" no front (P0-7).
        max_age_seconds: P0-3 — quando cache > este valor e ticket está
                          aberto, auto-bypass cache (sem precisar force).

    Returns:
      live_signal, degradation_alert, classification, cache_label, ...
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    t = await db.tickets.find_one(
        {"id": ticket_id, "company_id": cid}, {"_id": 0},
    )
    if not t:
        # Tenant-bypass para admin
        if user.get("role") in ("administrador", "auditor"):
            t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
        if not t:
            raise HTTPException(404, "ticket não encontrado")

    company_id = t.get("company_id") or cid
    snap = t.get("client_snapshot") or {}
    relato = (snap.get("relato") or t.get("admin_notes")
               or t.get("description") or "")
    is_open = (t.get("status") or "").lower() in ("aberta", "pendente",
                                                     "em_andamento",
                                                     "em andamento")

    from routes.smartolt import (resolve_signal_for_ticket,
                                    get_onu_signal_live,
                                    _live_signal_summary)
    onu = await resolve_signal_for_ticket(t)
    refresh_attempted = False
    refresh_result = None
    refresh_error = None

    # P0-3: auto-bypass do cache se ticket aberto e cache velho
    needs_refresh = force
    if onu and is_open and not force:
        from datetime import datetime, timezone
        sync_ts = onu.get("signal_synced_at") or onu.get("synced_at")
        if sync_ts:
            try:
                ts = str(sync_ts).strip().replace("Z", "+00:00")
                if " " in ts and "T" not in ts:
                    ts = ts.replace(" ", "T", 1)
                dt = datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - dt).total_seconds()
                if age > max_age_seconds:
                    needs_refresh = True
            except (ValueError, TypeError):
                needs_refresh = True

    if needs_refresh and onu:
        ext_id = onu.get("unique_external_id")
        try:
            # Reusa o endpoint live (com force=True) — invalida + busca
            # Não passamos pelo Depends; chamamos diretamente o handler
            # com objeto user montado.
            refresh_attempted = True
            res = await get_onu_signal_live(ext_id, force=True, user=user)
            refresh_result = "ok" if (res and res.get("onu")) else "no_data"
            if isinstance(res, dict) and res.get("onu"):
                onu = res["onu"]
        except HTTPException as he:
            refresh_result = "error"
            refresh_error = f"{he.status_code}: {he.detail}"
        except Exception as e:
            refresh_result = "error"
            refresh_error = str(e)[:200]

    # P0-7: log da tentativa Live
    if refresh_attempted:
        try:
            from datetime import datetime, timezone
            await db.lousa_logs.insert_one({
                "id": f"ll-{uuid.uuid4().hex[:10]}",
                "company_id": company_id,
                "ticket_id": ticket_id,
                "action": "live_signal_refresh",
                "result": refresh_result,
                "error": refresh_error,
                "force": force,
                "actor_id": user.get("id") or user.get("sub"),
                "at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass

    live = _live_signal_summary(onu, ticket_relato=relato) if onu else None

    # P0-6: anexa degradation_alert se houver
    degradation = None
    if onu and onu.get("unique_external_id"):
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        a = await db.signal_degradation_alerts.find_one(
            {"company_id": company_id,
             "unique_external_id": onu["unique_external_id"],
             "detected_at": {"$gte": cutoff}},
            {"_id": 0},
            sort=[("detected_at", -1)],
        )
        if a:
            degradation = {
                "detected_at": a.get("detected_at"),
                "avg_24h_rx_dbm": a.get("avg_24h_rx_dbm"),
                "current_rx_dbm": a.get("current_rx_dbm"),
                "delta_dbm": a.get("delta_dbm"),
                "samples_count": a.get("samples_count"),
                "status": a.get("status"),
                "resolved_at": a.get("resolved_at"),
            }

    return {
        "ticket_id": ticket_id,
        "live_signal": live,
        "degradation_alert": degradation,
        "refresh": {
            "attempted": refresh_attempted,
            "result": refresh_result,
            "error": refresh_error,
            "forced_by_user": force,
            "auto_bypass_cache": needs_refresh and not force,
        },
        "match": {
            "found_onu": bool(onu),
            "via_pppoe": bool((snap.get("pppoe_user") or "").strip()),
            "pppoe_confidence": snap.get("pppoe_confidence"),
            "pppoe_source": snap.get("pppoe_source"),
        },
        "ticket_status": t.get("status"),
        "ticket_type": t.get("type"),
        "client_name": snap.get("name"),
    }


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
    # EXCLUI Lousa virtuais (SALA etc) — colocamos a SALA manualmente como
    # primeira coluna fixa, com query separada.
    q["is_virtual"] = {"$ne": True}
    collabs = await db.collaborators.find(q, {"_id": 0}).to_list(500)
    collabs.sort(key=lambda c: c.get("name", ""))

    # SALA — coluna FIXA no início do quadro. Recebe agendamentos da Isabella.
    company_id_for_sala = user.get("company_id") or DEMO_COMPANY_ID
    sala_q = {"company_id": company_id_for_sala, "is_virtual": True,
                "virtual_kind": "sala_atendimento"}
    sala_doc = await db.collaborators.find_one(sala_q, {"_id": 0})
    if sala_doc:
        collabs.insert(0, sala_doc)

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
        "rompimento": int(settings.get("sla_rompimento_minutes", 180)),
    }
    warning_pct = int(settings.get("sla_warning_pct", 80))
    yellow_min = int(settings.get("sla_yellow_minutes", 15))
    red_after_min = int(settings.get("sla_red_after_minutes", 30))
    pending_grace_min = int(settings.get("sla_pending_grace_minutes", 60))
    blink = bool(settings.get("sla_blink_when_overdue", True))
    grid_start = int(settings.get("lousa_grid_start_hour", 9))
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
                key=lambda t: (_prio_rank(t.get("priority")), t.get("position", 0)),
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

        # Marca pin manual ANTES de recomputar grid_slot, pra preservar
        # drag-and-drop do gestor durante a redistribuição (iter215).
        manual_pins: set[str] = {
            t["id"] for t in tickets
            if t.get("grid_slot") and t["grid_slot"] in fixed_slots
        }
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

        # ------------------------------------------------------------------
        # Redistribuição automática (iter215): se um slot tem >= 2 bolhas E
        # existe slot vazio na grade do mesmo técnico, move a bolha extra
        # para o slot vazio mais próximo. Preserva bolhas pinadas manualmente
        # pelo gestor (drag-and-drop).
        # ------------------------------------------------------------------
        slot_to_tickets: dict[str, list] = {sl: [] for sl in fixed_slots}
        for t in tickets:
            sl = t.get("grid_slot")
            if sl in slot_to_tickets:
                slot_to_tickets[sl].append(t)
        for _ in range(200):
            empty_slots = [sl for sl in fixed_slots if not slot_to_tickets[sl]]
            if not empty_slots:
                break
            overcrowded = sorted(
                [(sl, ts) for sl, ts in slot_to_tickets.items() if len(ts) > 1],
                key=lambda x: -len(x[1]),
            )
            moved_any = False
            for src_slot, src_tickets in overcrowded:
                movable = [t for t in src_tickets if t["id"] not in manual_pins]
                if not movable:
                    continue
                moved = movable[-1]
                src_tickets.remove(moved)
                src_idx = fixed_slots.index(src_slot)
                empty_slots.sort(key=lambda sl: abs(fixed_slots.index(sl) - src_idx))
                dst_slot = empty_slots[0]
                moved["grid_slot"] = dst_slot
                slot_to_tickets[dst_slot].append(moved)
                moved_any = True
                break
            if not moved_any:
                break

        # Monta slots fixos com bolhas de cada slot (sempre exibe TODOS slots)
        slots_data = []
        for slot_label in fixed_slots:
            in_slot = slot_to_tickets[slot_label]
            slots_data.append({"slot": slot_label, "tickets": in_slot, "full": len(in_slot) >= max_per_slot})
        unscheduled = [t for t in tickets if t["grid_slot"] == "sem_horario"]

        # Regra de exibição (pedido do usuário, iter215):
        # SÓ aparece coluna de colaborador que TEM bolha. Sem bolha →
        # não renderiza, independente de externo/interno ou histórico.
        # EXCEÇÃO: SALA virtual é fixa, aparece SEMPRE (pedido CTO Feb/26).
        has_any_bubble = bool(tickets) or bool(unscheduled) or (
            is_historical and bool(recent_resolved)
        )
        is_virtual_sala = bool(c.get("is_virtual"))
        if not has_any_bubble and not is_virtual_sala:
            continue

        columns.append({
            "collaborator": {
                "id": cid, "name": c.get("name", ""),
                "avatar": c.get("avatar_data_url"),
                "is_test_mode": c.get("is_test_mode", False),
                "is_virtual": is_virtual_sala,
                "virtual_kind": c.get("virtual_kind"),
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
            "tickets": [_normalize_ticket(t) for t in tickets],
            "recent_resolved": [_normalize_ticket(t) for t in recent_resolved],
            "slots": slots_data,
            "unscheduled": [_normalize_ticket(t) for t in unscheduled],
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

    # Ordena colunas: SALA virtual SEMPRE primeiro (fixa). Depois técnicos
    # com MAIS bolhas (ativas) à esquerda → menos à direita.
    # Tiebreaker: nome alfabético para resultado estável.
    def _bubble_count(col: dict) -> int:
        n = len(col.get("unscheduled") or [])
        for s in col.get("slots") or []:
            n += len(s.get("tickets") or [])
        return n
    def _is_sala(col: dict) -> bool:
        return bool((col.get("collaborator") or {}).get("is_virtual"))
    columns.sort(key=lambda c: (
        0 if _is_sala(c) else 1,
        -_bubble_count(c),
        (c.get("collaborator") or {}).get("name", "")))
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
    """Retorna lista de labels de slots fixos: ['09:00', '10:00', ..., '18:00'].
    `end_hour` é INCLUSIVO (iter215) — grade vai de 09:00 ATÉ 18:00 inclusive."""
    slots = []
    total_min = ((end_hour - start_hour) + 1) * 60
    n = max(1, total_min // max(1, slot_minutes))
    for i in range(n):
        m = start_hour * 60 + i * slot_minutes
        slots.append(f"{m // 60:02d}:{m % 60:02d}")
    return slots


def _slot_for_ticket(t: dict, slots: list[str], slot_minutes: int) -> str:
    """Determina em qual slot fixo a bolha cai. Toda bolha SEMPRE cai em algum
    slot da grade — não existe 'sem_horario' (regra de negócio iter215).

    Prioridade:
    1. grid_slot já atribuído manualmente (se válido).
    2. scheduled_time arredondado p/ baixo no slot que contém o horário.
    3. scheduled_time fora do range → clampa pro primeiro/último slot.
    4. Sem scheduled_time → tenta created_at; senão cai no primeiro slot.
    """
    if not slots:
        return ""
    first_slot, last_slot = slots[0], slots[-1]
    if t.get("grid_slot") and t["grid_slot"] in slots:
        return t["grid_slot"]
    sched = t.get("scheduled_time") or t.get("created_at")
    if sched:
        try:
            hour = int(sched[11:13])
            minute = int(sched[14:16])
            total = hour * 60 + minute
            first_h, first_m = int(first_slot[:2]), int(first_slot[3:5])
            last_h, last_m = int(last_slot[:2]), int(last_slot[3:5])
            first_total = first_h * 60 + first_m
            last_total = last_h * 60 + last_m
            # Antes do grid → primeiro slot
            if total < first_total:
                return first_slot
            # No range
            for s in slots:
                sh, sm = int(s[:2]), int(s[3:5])
                slot_start = sh * 60 + sm
                if slot_start <= total < slot_start + slot_minutes:
                    return s
            # Depois do último slot
            if total >= last_total:
                return last_slot
        except Exception:
            pass
    return first_slot


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
        # cross-colaborador. PORÉM, se o admin estiver olhando o PRÓPRIO
        # cadastro (seu collaborator_id == cid), mantém o modo normal —
        # só bolhas atribuídas a ele mesmo. (Pedido do usuário: app do
        # colaborador SEMPRE mostra apenas suas bolhas, mesmo se a pessoa
        # também for admin.)
        try:
            auth_header = (request.headers.get("authorization") or "") if request else ""
            if auth_header.lower().startswith("bearer "):
                token = auth_header.split(" ", 1)[1].strip()
                from auth import decode_token
                payload = decode_token(token)
                if payload and payload.get("role") in ("administrador", "auditor"):
                    own_collab_id = payload.get("collaborator_id")
                    if own_collab_id and own_collab_id == cid:
                        cross_collab_company = None  # app próprio → normal
                    else:
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
    # REGRA: bolhas pausadas aguardando ação do gestor (técnico chamou
    # gestor via "Não consegui executar") somem da lousa do técnico até
    # o gestor liberá-la de volta (ou fechá-la improdutiva / criar nova OS).
    active_raw = [t for t in active_raw if not t.get("needs_manager_action")]
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
        "tickets": [_normalize_ticket(t) for t in active_raw],  # apenas ativas — espelha exatamente lousa do gestor
        "recent_resolved": [_normalize_ticket(t) for t in resolved_raw],  # metadata para histórico do dia
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
    """Painel gestor/admin: todas as bolhas do tenant.

    CTO 11/06/2026: ticket sem `assigned_collaborator_id` é renderizado na SALA
    do tenant (col-sala-<cid>). Garante que nenhuma nota fique invisível.
    """
    q = tenant_filter(user)
    raw = await db.tickets.find(q, {"_id": 0}).to_list(5000)

    # Resolve sala_id do tenant (cacheia 1x)
    cid = user.get("company_id") or DEMO_COMPANY_ID
    sala_id = None
    try:
        from services.isabella_actions import _ensure_sala
        sala_id = await _ensure_sala(cid)
    except Exception:
        sala_id = "col-sala"

    # Fallback in-memory: órfãos viram virtuais da SALA (sem mutar DB aqui).
    orphans_made_visible = 0
    for t in raw:
        if not t.get("assigned_collaborator_id"):
            t["assigned_collaborator_id"] = sala_id
            t["system_generated"] = t.get("system_generated") or True
            t["sala_route_reason"] = t.get("sala_route_reason") or "auto_visible_fallback"
            orphans_made_visible += 1

    raw.sort(key=lambda t: (
        0 if t["status"] == "aguardando_atendimento" else 1,
        PRIORITY_RANK.get(t.get("priority", "normal"), 2),
        t.get("position", 0),
    ))
    return {
        "tickets": [_normalize_ticket(t) for t in raw],
        "_meta": {"orphans_made_visible": orphans_made_visible, "sala_id": sala_id},
    }


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
         # iter211bj — exclui OSs fechadas fora do raio do endereço
         "exclude_from_kpis": {"$ne": True},
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
         # iter211bj — exclui OSs fechadas fora da área do cliente
         "exclude_from_kpis": {"$ne": True},
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
         "exclude_from_kpis": {"$ne": True},  # iter211bj
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
    return _normalize_ticket(t)


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

    # ISABELLA INCIDENT COMMANDER — trava reparos individuais quando há
    # incidente coletivo ABERTO cobrindo a CTO/bairro do cliente. O cliente
    # é AGRUPADO no incidente (a OS coletiva resolve a causa na origem).
    if payload.type == "reparo":
        try:
            from services.isabella_incident import incident_block_for_new_repair
            _inc = await incident_block_for_new_repair(
                coll.get("company_id") or DEMO_COMPANY_ID,
                payload.client_name, payload.pppoe_user, payload.neighborhood)
        except Exception as _e:
            logger.warning("[lousa] incident guard fail: %s", _e)
            _inc = None
        if _inc:
            _sc = _inc.get("scope") or {}
            raise HTTPException(409, {
                "code": "COLLECTIVE_INCIDENT_OPEN",
                "incident_id": _inc["id"],
                "collective_ticket_id": _inc.get("collective_ticket_id"),
                "message": (
                    f"Isabella detectou incidente coletivo ABERTO em "
                    f"{_sc.get('cto_name') or _sc.get('cto_id') or _sc.get('neighborhood')}"
                    f" ({_inc.get('kind_label') or _inc['kind']}). O cliente foi "
                    f"AGRUPADO ao incidente — trate a causa na OS coletiva em vez "
                    f"de abrir reparo individual."),
            })

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
        # CTO 13/06/2026 — Contrato OS único: rastreabilidade da origem
        "origin": (payload.origin or "manual").lower(),
        "created_by_agent": payload.created_by_agent,
        "isabella_context": payload.isabella_context or {},
        # CTO 13/06/2026 — TODA OS é visível no mobile do colaborador
        # (não há OS oculto/orphan).
        "mobile_visible": True,
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
    # CTO 13/06/2026 — EventBus operacional: toda OS criada emite evento
    # canônico. Se vier da Isabella (origin=isabella), emite tipo dedicado.
    try:
        from services.event_bus import emit_event, EventType
        origin = (getattr(payload, "origin", None) or "manual").lower()
        is_isabella = origin in ("isabella", "ai_isabella", "ia_isabella")
        evt_type = "ISABELLA_OS_CREATED" if is_isabella else EventType.TICKET_OPENED
        await emit_event(
            evt_type,
            company_id=doc["company_id"],
            user_id=user.get("id"),
            source="lousa.create_ticket",
            severity="alta" if payload.priority == "urgente" else "media",
            payload={
                "ticket_id": doc["id"], "type": doc["type"],
                "priority": doc["priority"], "client_name": payload.client_name,
                "neighborhood": payload.neighborhood,
                "assigned_collaborator_id": coll.get("id"),
                "assigned_collaborator_name": coll.get("name"),
                "origin": origin,
                "created_by_agent": getattr(payload, "created_by_agent", None),
            },
        )
        # CTO 13/06/2026 — Evento canônico operacional (alimenta KPIs+watchdogs)
        await emit_event(
            "ticket.created",
            company_id=doc["company_id"],
            user_id=user.get("id"),
            source="lousa.create_ticket",
            severity="alta" if payload.priority == "urgente" else "media",
            payload={
                "ticket_id": doc["id"], "type": doc["type"],
                "priority": doc["priority"], "client_name": payload.client_name,
                "neighborhood": payload.neighborhood,
                "assigned_collaborator_id": coll.get("id"),
                "origin": origin,
                "created_by_agent": getattr(payload, "created_by_agent", None),
                "mobile_visible": True,
            },
        )
        # CTO 13/06/2026 — Espelha em `db.appointments` quando Isabella cria.
        # Garante: agendamento rastreável + fonte única pra Presidente IA.
        if is_isabella:
            try:
                from datetime import datetime, timezone
                await db.appointments.insert_one({
                    "id": f"apt-{doc['id'][4:]}",
                    "company_id": doc["company_id"],
                    "ticket_id": doc["id"],
                    "subscriber_id": doc.get("client_id"),
                    "customer_name": payload.client_name,
                    "customer_phone": payload.phone,
                    "address": payload.address,
                    "neighborhood": payload.neighborhood,
                    "type": doc["type"],
                    "priority": doc["priority"],
                    "scheduled_time": payload.scheduled_time,
                    "assigned_collaborator_id": coll.get("id"),
                    "assigned_collaborator_name": coll.get("name"),
                    "origin": "isabella",
                    "created_by_agent": getattr(payload, "created_by_agent", "isabella"),
                    "isabella_context": getattr(payload, "isabella_context", None) or {},
                    "status": "scheduled",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as _ae:
                logger.warning("[lousa] mirror appointments falhou: %s", _ae)
    except Exception as e:
        logger.warning("[lousa] emit OS_CREATED falhou: %s", e)
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
    try:
        from services.event_bus import emit_event
        await emit_event(
            "ticket.opened",
            company_id=(last or {}).get("company_id"),
            source="lousa",
            payload={},
        )
    except Exception:
        pass
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
    try:
        from services.event_bus import emit_event
        await emit_event(
            "ticket.closed",
            company_id=(t or {}).get("company_id"),
            source="lousa",
            payload={},
        )
    except Exception:
        pass
    if res.deleted_count == 0:
        raise HTTPException(404, "Nota não encontrada")
    return {"ok": True}


# =============================================================================
# iter211x — Cardápio de fotos obrigatórias por tipo de OS
# =============================================================================
# Catálogo configurável: cada item define UMA exigência de foto (CTO, ONT,
# etiqueta SN, comprovante, etc.) que se aplica a um ou mais tipos de OS.
# Substitui o hardcode antigo de 3 fotos. Gestor pode desligar, editar e
# ADICIONAR novas exigências de foto pelo painel de Configurações.
PHOTO_REQ_VALID_TICKET_TYPES = [
    "instalacao", "troca", "reparo", "retirada",
    "prioridade", "preventiva", "venda",
]
DEFAULT_PHOTO_REQUIREMENTS: List[Dict[str, Any]] = [
    {
        "id": "cto", "label": "Foto da CTO", "icon": "📦",
        "instruction": "Tire uma foto da caixa CTO onde o cliente foi conectado.",
        "ticket_types": ["instalacao", "troca", "reparo", "preventiva"],
        "required": True, "is_default": True, "sort_order": 1,
        "stamp_location": True,
    },
    {
        "id": "equipamento", "label": "Foto do Equipamento (ONT/ONU)", "icon": "📡",
        "instruction": "Tire uma foto do equipamento ligado no cliente.",
        "ticket_types": ["instalacao", "troca", "reparo"],
        "required": True, "is_default": True, "sort_order": 2,
        "stamp_location": False,
    },
    {
        "id": "sn", "label": "Foto do MAC/SN da etiqueta", "icon": "🏷️",
        "instruction": "Tire uma foto da etiqueta com MAC/SN (a IA lê automaticamente).",
        "ticket_types": ["instalacao", "troca", "reparo"],
        "required": True, "is_default": True, "sort_order": 3,
        "stamp_location": False,
    },
]


class PhotoRequirementIn(BaseModel):
    id: str = Field(..., min_length=2, max_length=40,
                    pattern=r"^[a-z0-9][a-z0-9_-]*$")
    label: str = Field(..., min_length=2, max_length=80)
    icon: str = Field(default="📷", max_length=4)
    instruction: str = Field(default="", max_length=300)
    ticket_types: List[str] = Field(default_factory=list)
    required: bool = True
    sort_order: int = 100
    stamp_location: bool = False  # iter211y — carimba data/hora/endereço/dispositivo


class PhotoRequirementsIn(BaseModel):
    items: List[PhotoRequirementIn]


def _norm_photo_req(item: Dict[str, Any]) -> Dict[str, Any]:
    types = [t for t in (item.get("ticket_types") or [])
             if t in PHOTO_REQ_VALID_TICKET_TYPES]
    return {
        "id": (item.get("id") or "").strip().lower(),
        "label": (item.get("label") or "").strip(),
        "icon": item.get("icon") or "📷",
        "instruction": (item.get("instruction") or "").strip(),
        "ticket_types": types,
        "required": bool(item.get("required", True)),
        "is_default": bool(item.get("is_default", False)),
        "sort_order": int(item.get("sort_order") or 100),
        "stamp_location": bool(item.get("stamp_location", False)),
    }


async def _get_or_seed_photo_reqs(company_id: str) -> List[Dict[str, Any]]:
    doc = await db.lousa_photo_requirements.find_one(
        {"company_id": company_id}, {"_id": 0})
    if not doc:
        items = [_norm_photo_req(it) for it in DEFAULT_PHOTO_REQUIREMENTS]
        await db.lousa_photo_requirements.update_one(
            {"company_id": company_id},
            {"$set": {"company_id": company_id, "items": items,
                       "updated_at": now_iso(), "seeded_at": now_iso()}},
            upsert=True,
        )
        return items
    items = [_norm_photo_req(it) for it in (doc.get("items") or [])]
    items.sort(key=lambda x: (x["sort_order"], x["id"]))
    return items


@router.get("/lousa/photo-requirements")
async def list_photo_requirements(user: dict = Depends(get_current_user)):
    """Lista as exigências de foto configuradas para esta empresa.
    Auto-seed com 3 defaults (cto/equipamento/sn) na primeira chamada.
    Aberto para qualquer usuário autenticado (lousa mobile consome)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    items = await _get_or_seed_photo_reqs(cid)
    return {
        "items": items,
        "valid_ticket_types": PHOTO_REQ_VALID_TICKET_TYPES,
    }


@router.put("/lousa/photo-requirements")
async def update_photo_requirements(
    payload: PhotoRequirementsIn,
    user: dict = Depends(require_role("gestor")),
):
    """Substitui a lista de exigências de foto. Ids devem ser únicos e
    em lowercase. Preserva flag `is_default` para os 3 originais (não
    podem ser excluídos, apenas desligados via `required=false`)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    items: List[Dict[str, Any]] = []
    seen_ids = set()
    default_ids = {it["id"] for it in DEFAULT_PHOTO_REQUIREMENTS}
    found_defaults = set()
    for raw in payload.items:
        norm = _norm_photo_req(raw.model_dump())
        if not norm["id"] or not norm["label"]:
            continue
        if norm["id"] in seen_ids:
            raise HTTPException(400, f"ID de foto duplicado: {norm['id']}")
        seen_ids.add(norm["id"])
        if norm["id"] in default_ids:
            norm["is_default"] = True
            found_defaults.add(norm["id"])
        items.append(norm)
    # Garante que os 3 defaults nunca somem (auto-reanexa desligados).
    for d in DEFAULT_PHOTO_REQUIREMENTS:
        if d["id"] not in found_defaults:
            items.append({**_norm_photo_req(d), "required": False})
    items.sort(key=lambda x: (x["sort_order"], x["id"]))
    await db.lousa_photo_requirements.update_one(
        {"company_id": cid},
        {"$set": {"company_id": cid, "items": items,
                   "updated_at": now_iso(),
                   "updated_by": user.get("email") or user.get("name")}},
        upsert=True,
    )
    return {"ok": True, "items": items}


# iter211w — Reabrir OS finalizada/encerrada
class ReopenIn(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)
    keep_technician: bool = True  # se True, mantém o mesmo técnico atribuído


async def _revert_ticket_side_effects(ticket: dict, actor: dict) -> Dict[str, Any]:
    """iter211w — Reverte TODOS os efeitos colaterais de um fechamento de OS:
      • ONT volta para o estoque do técnico (instalação) ou para o cliente (retirada)
      • Porta da CTO volta para `free`
      • Consumíveis (drop, esticadores, conectores) recreditados no técnico
      • stok_services volta para `ativo` (auto-reabertura junto da nota)
      • Vínculos `cto_ports_base` ressincronizados
      • Eventos `client_equipment_history` (port_release, install/withdraw reversa)
    Retorna um summary por componente para mostrar no log e na UI.
    Tudo é best-effort: cada componente é envolvido em try/except próprio
    para que falha parcial não impeça a reabertura da nota.
    """
    company_id = ticket.get("company_id") or DEMO_COMPANY_ID
    ticket_id = ticket["id"]
    ttype = ticket.get("type")
    cd = ticket.get("completion_data") or {}
    cs = ticket.get("client_snapshot") or {}
    summary: Dict[str, Any] = {
        "ont_reverted": None,
        "cto_port_freed": None,
        "consumables_recredited": None,
        "stok_service_reactivated": None,
        "errors": [],
    }

    # 1) Buscar service de estoque vinculado (se existir).
    service = None
    try:
        service = await db.stok_services.find_one(
            {"ticket_id": ticket_id, "company_id": company_id,
             "status": {"$in": ["fechado", "erro_estoque"]}},
            {"_id": 0},
        )
    except Exception as e:
        summary["errors"].append(f"stok_services lookup: {e}")

    # 2) Reverter ONT (instalação/retirada/troca).
    try:
        if ttype in ("instalacao", "troca"):
            # ONT que foi movida para o cliente via este ticket.
            ont = await db.stok_onts.find_one(
                {"company_id": company_id,
                 "installed_via_ticket": ticket_id},
                {"_id": 0},
            )
            if ont:
                tech_id = (ont.get("installed_by_id")
                           or (service or {}).get("technician_id")
                           or ticket.get("assigned_collaborator_id"))
                if tech_id:
                    await db.stok_onts.update_one(
                        {"company_id": company_id, "mac": ont["mac"]},
                        {"$set": {
                            "location_type": "tecnico",
                            "location_id": tech_id,
                            "client_name": None,
                            "status": "disponivel",
                        },
                         "$unset": {
                            "installed_at": "", "installed_by_id": "",
                            "installed_by_name": "", "installed_by_email": "",
                            "installed_via_ticket": "", "installed_via_service": "",
                            "pending_install_to_client": "",
                            "pending_install_service_id": "",
                            "pending_transfer_id": "",
                        }},
                    )
                    summary["ont_reverted"] = {
                        "action": "uninstall",
                        "mac": ont.get("mac"),
                        "sn": ont.get("scan_sn"),
                        "back_to_tech": tech_id,
                    }
                    if cs.get("id"):
                        try:
                            from services import client_equipment_history as _ceh
                            await _ceh.log_event(
                                company_id=company_id,
                                client_id=cs.get("id"),
                                client_name=cs.get("name"),
                                action="withdraw",  # operação reversa
                                ont_mac=ont.get("mac"),
                                ont_sn=ont.get("scan_sn"),
                                actor_id=actor.get("id"),
                                actor_name=actor.get("name") or actor.get("email"),
                                actor_email=actor.get("email"),
                                ticket_id=ticket_id,
                                notes="↻ Reabertura de OS — ONT devolvida ao estoque do técnico",
                            )
                        except Exception as _e:
                            summary["errors"].append(f"ceh uninstall: {_e}")
        elif ttype == "retirada":
            # ONT que foi retirada do cliente via este ticket → volta pro cliente.
            ont = await db.stok_onts.find_one(
                {"company_id": company_id,
                 "withdrawn_via_ticket": ticket_id},
                {"_id": 0},
            )
            if ont:
                cli_id = (ont.get("withdrawn_from_client_id")
                          or (service or {}).get("client_id")
                          or cs.get("id"))
                cli_name = (ont.get("withdrawn_from_client_name")
                            or (service or {}).get("client_name")
                            or cs.get("name"))
                if cli_id:
                    await db.stok_onts.update_one(
                        {"company_id": company_id, "mac": ont["mac"]},
                        {"$set": {
                            "location_type": "cliente",
                            "location_id": cli_id,
                            "client_name": cli_name,
                            "status": "instalada",
                        },
                         "$unset": {
                            "withdrawn_from_client_id": "",
                            "withdrawn_from_client_name": "",
                            "withdrawn_by_email": "",
                            "withdrawn_by_name": "",
                            "withdrawn_via_ticket": "",
                            "withdrawn_via_service": "",
                            "withdrawn_at": "",
                            "source": "",
                            "withdraw_inconsistency": "",
                            "withdraw_inconsistency_note": "",
                        }},
                    )
                    summary["ont_reverted"] = {
                        "action": "uninwithdraw",
                        "mac": ont.get("mac"),
                        "sn": ont.get("scan_sn"),
                        "back_to_client": cli_id,
                    }
                    try:
                        from services import client_equipment_history as _ceh
                        await _ceh.log_event(
                            company_id=company_id,
                            client_id=cli_id,
                            client_name=cli_name,
                            action="install",  # operação reversa
                            ont_mac=ont.get("mac"),
                            ont_sn=ont.get("scan_sn"),
                            actor_id=actor.get("id"),
                            actor_name=actor.get("name") or actor.get("email"),
                            actor_email=actor.get("email"),
                            ticket_id=ticket_id,
                            notes="↻ Reabertura de OS — ONT religada ao cliente (retirada desfeita)",
                        )
                    except Exception as _e:
                        summary["errors"].append(f"ceh reinstall: {_e}")
    except Exception as e:
        summary["errors"].append(f"ONT revert: {e}")

    # 3) Liberar porta da CTO (instalação).
    try:
        cto_id = cd.get("cto_id") or cd.get("cto") or None
        cto_port = cd.get("cto_port_number") or cd.get("cto_port") or None
        if not cto_id or not cto_port:
            # busca a porta diretamente pela referência ao ticket
            cto_doc = await db.ctos.find_one(
                {"company_id": company_id,
                 "ports.connected_via_ticket": ticket_id},
                {"_id": 0, "id": 1, "name": 1, "ports": 1},
            )
            if cto_doc:
                cto_id = cto_doc["id"]
                for p in (cto_doc.get("ports") or []):
                    if p.get("connected_via_ticket") == ticket_id:
                        cto_port = p.get("number")
                        break
        if cto_id and cto_port:
            await db.ctos.update_one(
                {"id": cto_id, "company_id": company_id,
                 "ports.number": int(cto_port)},
                {"$set": {"ports.$.status": "free"},
                 "$unset": {
                    "ports.$.client_subscriber_id": "",
                    "ports.$.client_name": "",
                    "ports.$.client_pppoe": "",
                    "ports.$.connected_at": "",
                    "ports.$.connected_via_ticket": "",
                }},
            )
            try:
                from services.event_bus import emit_event
                await emit_event(
                    "cto.updated",
                    company_id=(cto_doc or {}).get("company_id"),
                    source="lousa",
                    payload={},
                )
            except Exception:
                pass
            summary["cto_port_freed"] = {"cto_id": cto_id, "port": int(cto_port)}
            try:
                from routes.cto_ports_base import sync_port_from_cto
                await sync_port_from_cto(company_id, cto_id, int(cto_port))
            except Exception as _e:
                summary["errors"].append(f"sync_port_from_cto: {_e}")
            if cs.get("id"):
                try:
                    from services import client_equipment_history as _ceh
                    await _ceh.log_event(
                        company_id=company_id,
                        client_id=cs.get("id"),
                        client_name=cs.get("name"),
                        action="port_release",
                        cto_id=cto_id,
                        cto_port_number=int(cto_port),
                        actor_id=actor.get("id"),
                        actor_name=actor.get("name") or actor.get("email"),
                        actor_email=actor.get("email"),
                        ticket_id=ticket_id,
                        notes="↻ Reabertura de OS — porta liberada",
                    )
                except Exception as _e:
                    summary["errors"].append(f"ceh port_release: {_e}")
    except Exception as e:
        summary["errors"].append(f"CTO port revert: {e}")

    # 4) Re-creditar consumíveis (drop, esticadores, conectores) no estoque do técnico.
    try:
        used = (service or {}).get("auto_closed_used_items") or []
        if used and (service or {}).get("technician_id"):
            inc: Dict[str, int] = {}
            for ui in used:
                qty = int(ui.get("quantity") or 0)
                cid_ = ui.get("consumable_id")
                if cid_ and qty > 0:
                    inc[cid_] = inc.get(cid_, 0) + qty
            if inc:
                await db.stok_stock.update_one(
                    {"company_id": company_id,
                     "location": service["technician_id"]},
                    {"$inc": inc},
                    upsert=True,
                )
                summary["consumables_recredited"] = inc
    except Exception as e:
        summary["errors"].append(f"consumables revert: {e}")

    # 5) Reativar stok_service (volta para `ativo`).
    try:
        if service:
            await db.stok_services.update_one(
                {"id": service["id"], "company_id": company_id},
                {"$set": {"status": "ativo"},
                 "$unset": {
                    "closed_at": "", "ticket_finalized": "",
                    "ticket_finalized_at": "", "auto_closed": "",
                    "auto_closed_used_items": "", "auto_closed_ont_mac": "",
                    "smartolt_validation": "", "error_reason": "",
                    "auto_close_attempted_at": "",
                }},
            )
            summary["stok_service_reactivated"] = service["id"]
    except Exception as e:
        summary["errors"].append(f"stok_service revert: {e}")

    return summary


@router.post("/lousa/tickets/{ticket_id}/reopen")
async def reopen_ticket(ticket_id: str, payload: ReopenIn,
                        user: dict = Depends(require_role("gestor"))):
    """Reabre uma OS encerrada/finalizada — volta para 'pendente' e desfaz
    TODOS os efeitos colaterais do fechamento (iter211w++ 02/06/2026):

      • Lançamento de estoque (ONT no cliente → estoque do técnico)
      • Lançamento de caixa/consumíveis (drop, esticadores, conectores recreditados)
      • Lançamento de porta da CTO (porta volta para `free`)
      • Fotos do fechamento limpas (técnico precisa tirar tudo de novo)
      • completion_data inteiro arquivado em `previous_completions[]` para auditoria

    O fechamento anterior NÃO é apagado — é arquivado integralmente para
    permitir investigação posterior.

    Body:
      reason: str (mín 3 chars) — justificativa de auditoria.
      keep_technician: bool — se True (default), mantém o
                       assigned_collaborator_id; se False, deixa em aberto
                       para reatribuir.
    """
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if t.get("company_id") and t.get("company_id") != cid and user.get("role") != "auditor":
        raise HTTPException(403, "Nota de outra empresa")
    cur_status = t.get("status")
    if cur_status not in ("finalizada", "encerrada", "cancelada", "reagendada"):
        raise HTTPException(
            409,
            f"Nota não está fechada (status atual: {cur_status}). "
            "Apenas notas finalizadas/encerradas/canceladas/reagendadas podem ser reabertas.",
        )

    # 1) Reverte efeitos colaterais ANTES de mudar o status (precisamos do
    # completion_data ainda intacto para localizar CTO/ONT).
    revert_summary = await _revert_ticket_side_effects(t, user)

    # 2) Arquiva o fechamento atual em previous_completions[] para auditoria
    archived = {
        "archived_at": now_iso(),
        "archived_by": user.get("email") or user.get("name") or "?",
        "reason": payload.reason.strip(),
        "previous_status": cur_status,
        "previous_completion_data": t.get("completion_data"),
        "previous_closed_at": t.get("closed_at"),
        "previous_closed_by": t.get("closed_by"),
        "previous_finalized_at": t.get("finalized_at"),
        "previous_outcome": t.get("outcome"),
        "previous_admin_action": t.get("admin_action"),
        "revert_summary": revert_summary,
    }

    unset_fields: Dict[str, str] = {
        "closed_at": "", "closed_by": "", "finalized_at": "",
        "completion_data": "", "outcome": "", "admin_action": "",
        "signal_at_close": "", "duration_minutes": "",
        "ai_score": "", "ai_verdict": "", "ai_method": "",
        "ai_summary": "", "ai_recommendations": "", "ai_evaluated_at": "",
        "opened_at": "",  # técnico precisa abrir do zero
        "close_location": "",
        "smartolt_managed": "",
        "equipment_swap": "",
        "central_ont": "",
        "signal_at_open": "",
    }
    set_fields: Dict[str, Any] = {
        "status": "pendente",
        "reopened_at": now_iso(),
        "reopened_by": user.get("email") or user.get("name") or "?",
        "reopen_count": int(t.get("reopen_count") or 0) + 1,
        # V9 P2 — flag derivado de retrabalho (lido por company_v6
        # via _ensure_smart_record para penalizar quality score)
        "reopened": True,
    }
    # V9 P2 — calcula reopened_within_7d
    try:
        from datetime import datetime, timezone
        closed_at = t.get("closed_at")
        if closed_at:
            ca = closed_at
            if isinstance(ca, str):
                ca = datetime.fromisoformat(ca.replace("Z", "+00:00"))
            if ca.tzinfo is None:
                ca = ca.replace(tzinfo=timezone.utc)
            delta = (datetime.now(timezone.utc) - ca).days
            set_fields["reopened_within_7d"] = delta <= 7
            set_fields["reopened_within_days"] = delta
    except Exception as e:
        logger.warning("[reopen] reopened_within_7d calc fail: %s", e)
    if not payload.keep_technician:
        unset_fields["assigned_collaborator_id"] = ""

    await db.tickets.update_one(
        {"id": ticket_id},
        {
            "$set": set_fields,
            "$unset": unset_fields,
            "$push": {"previous_completions": archived},
        },
    )

    # Log estruturado (auditoria) — usa o mesmo formato dos outros action logs
    try:
        await _log_ticket_action(
            ticket_id=ticket_id,
            company_id=t.get("company_id") or cid,
            actor_id=user.get("id") or user.get("email") or "?",
            actor_name=user.get("name") or user.get("email") or "?",
            actor_role=user.get("role") or "?",
            action="reaberta",
            details=(
                f"De {cur_status} → pendente. Motivo: {payload.reason.strip()}"
                + (" (técnico mantido)" if payload.keep_technician else " (técnico desvinculado)")
                + f" · revert: {revert_summary}"
            ),
        )
    except Exception as e:
        logger.warning("[reopen] não foi possível gravar log: %s", e)

    fresh = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    out = _normalize_ticket(fresh) if fresh else {"ok": True}
    if isinstance(out, dict):
        out["revert_summary"] = revert_summary
    return out


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
    raw.sort(key=lambda t: (_prio_rank(t.get("priority")), t.get("position", 0)))
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
            live = await get_onu_signal_live(onu["unique_external_id"],
                                                  force=True, user=user)
            return {"found": True, "match_strategy": strategy, **live}
        except HTTPException:
            pass
        except Exception as e:
            return {"found": True, "match_strategy": strategy, "cached": True,
                    "onu": onu, "warning": f"refresh_failed: {e}"}
    return {"found": True, "match_strategy": strategy, "cached": True, "onu": onu}


@router.get("/lousa/public/tickets/{ticket_id}/signal")
async def get_ticket_signal_public(ticket_id: str,
                                       collaborator_id: str,
                                       refresh: bool = False):
    """Versão PÚBLICA (sem auth) do /signal — usada pelo app do colaborador
    no LousaMobile. Verifica que a OS pertence ao colaborador antes de
    devolver o sinal. Suporta `refresh=true` (Live) com force-bypass do
    rate-limit (iter215)."""
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    if t.get("assigned_collaborator_id") != collaborator_id:
        raise HTTPException(403, "Esta OS não pertence a este colaborador")
    snap = t.get("client_snapshot") or {}
    pppoe = (snap.get("pppoe_user") or "").strip()
    name = (snap.get("name") or "").strip()
    if not pppoe and not name:
        return {"found": False, "reason": "missing_pppoe_and_name"}
    try:
        from routes.smartolt import (resolve_signal_for_ticket,
                                              get_onu_signal_live)
    except ImportError:
        return {"found": False, "reason": "smartolt_module_missing"}
    onu = await resolve_signal_for_ticket(t)
    if not onu:
        return {"found": False, "reason": "no_match", "pppoe": pppoe, "name": name}
    strategy = "pppoe" if pppoe else "name"
    # Sintetiza um "user" compatível com o endpoint live
    fake_user = {"company_id": t.get("company_id") or DEMO_COMPANY_ID,
                 "role": "colaborador", "id": collaborator_id}
    if refresh:
        try:
            live = await get_onu_signal_live(onu["unique_external_id"],
                                                  force=True, user=fake_user)
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




# ---------------------------------------------------------------------------
# AGENTE IA — slots disponíveis + criação de ticket de reparo agendado
# ---------------------------------------------------------------------------
@router.get("/lousa/public/available-slots")
async def lousa_public_available_slots(company_id: str,
                                            days_ahead: int = 3,
                                            ticket_type: str = "reparo"):
    """Retorna próximos horários DISPONÍVEIS na Lousa para o agente IA
    sugerir ao cliente.

    Lógica simplificada (compatível com a grade fixa atual):
    - Considera apenas dias úteis (seg-sáb) a partir de amanhã.
    - Horários padrão: 08:00, 10:00, 13:00, 15:00, 17:00 (5 slots/dia).
    - Conta tickets já agendados no dia/slot e marca como "cheio" se >= 3.
    """
    cid = company_id or DEMO_COMPANY_ID
    from datetime import datetime, timedelta, timezone
    fixed_slots = ["08:00", "10:00", "13:00", "15:00", "17:00"]
    max_per_slot = 3
    now = datetime.now(timezone.utc)
    options = []
    for i in range(1, days_ahead * 2 + 5):  # tenta mais dias se algum for domingo
        d = (now + timedelta(days=i))
        if d.weekday() == 6:  # domingo
            continue
        date_str = d.date().isoformat()
        # Conta tickets no dia
        day_tickets = await db.tickets.find(
            {"company_id": cid, "scheduled_date": date_str,
              "status": {"$nin": ["finalizada", "encerrada", "cancelada"]}},
            {"_id": 0, "scheduled_time": 1},
        ).to_list(200)
        for sl in fixed_slots:
            count = sum(1 for t in day_tickets if t.get("scheduled_time") == sl)
            if count < max_per_slot:
                options.append({
                    "date": date_str,
                    "weekday": ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"][d.weekday()],
                    "time": sl,
                    "human": f"{['Seg','Ter','Qua','Qui','Sex','Sáb'][d.weekday()]} "
                                f"({d.day:02d}/{d.month:02d}) às {sl}",
                })
            if len(options) >= 6:
                break
        if len(options) >= 6:
            break
    return {"company_id": cid, "ticket_type": ticket_type,
              "options": options[:6]}


class PublicCreateRepairIn(BaseModel):
    """Cria ticket de reparo agendado a partir do diagnóstico do Álvaro."""
    phone: str
    subscriber_id: Optional[str] = None
    company_id: str
    scheduled_date: str  # YYYY-MM-DD
    scheduled_time: str  # HH:MM
    onu_status: str  # online/los/power_off/offline
    diagnosis_text: str
    client_name: Optional[str] = None
    address: Optional[str] = None
    neighborhood: Optional[str] = None
    reboot_attempted: bool = False


@router.post("/lousa/public/create-repair-from-ai")
async def lousa_public_create_repair_from_ai(payload: PublicCreateRepairIn):
    """Cria ticket de reparo aberto pela IA Álvaro.

    Diferenças do ticket comum:
    - origin_source = "alvaro_diagnose"
    - Inclui status SmartOLT no client_snapshot pra técnico ver no app
    - Prioridade automática:
       * los       → alta (interrompe rede de mais clientes provavelmente)
       * power_off → média (provavelmente interno do cliente)
       * online    → média (instável)
    """
    cid = payload.company_id or DEMO_COMPANY_ID
    sub = None
    if payload.subscriber_id:
        sub = await db.subscribers.find_one(
            {"id": payload.subscriber_id},
            {"_id": 0, "name": 1, "address": 1, "neighborhood": 1,
              "city": 1, "plan_name": 1, "pppoe": 1},
        )
    snap = {
        "name": (sub or {}).get("name") or payload.client_name or "Cliente WhatsApp",
        "phone": payload.phone,
        "address": payload.address or (sub or {}).get("address"),
        "neighborhood": payload.neighborhood or (sub or {}).get("neighborhood"),
        "city": (sub or {}).get("city"),
        "plan_name": (sub or {}).get("plan_name"),
        "pppoe": (sub or {}).get("pppoe"),
        "smartolt_status": payload.onu_status,
        "smartolt_diagnosis": payload.diagnosis_text,
        "reboot_attempted": payload.reboot_attempted,
    }
    priority_map = {"los": "alta", "online": "media", "power_off": "media"}
    ticket = {
        "id": f"tkt-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "type": "reparo",
        "status": "aberto",
        "priority": priority_map.get(payload.onu_status, "media"),
        "client_snapshot": snap,
        "subscriber_id": payload.subscriber_id,
        "origin_source": "alvaro_diagnose",
        "origin_phone": payload.phone,
        "scheduled_date": payload.scheduled_date,
        "scheduled_time": payload.scheduled_time,
        "notes": (f"Diagnóstico Álvaro IA: {payload.diagnosis_text}\n"
                    f"Status SmartOLT: {payload.onu_status}\n"
                    f"Reboot tentado: {'sim' if payload.reboot_attempted else 'não'}"),
        "created_at": now_iso(),
    }
    await db.tickets.insert_one(dict(ticket))
    try:
        from services.event_bus import emit_event
        await emit_event(
            "ticket.opened",
            company_id=(sub or {}).get("company_id"),
            source="lousa",
            payload={},
        )
    except Exception:
        pass
    # Marca conv com o ticket criado
    await db.wa_conversations.update_one(
        {"company_id": cid, "phone": payload.phone},
        {"$set": {"alvaro_ticket_id": ticket["id"],
                    "alvaro_ticket_at": now_iso()}},
    )
    return {"ok": True, "ticket_id": ticket["id"],
             "scheduled": f"{payload.scheduled_date} às {payload.scheduled_time}",
             "message": f"Tudo certo! Agendei sua visita técnica para "
                         f"{payload.scheduled_date} às {payload.scheduled_time}. "
                         f"O técnico vai te ligar antes de ir."}


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
                                    background_tasks: BackgroundTasks = None,
                                    request: Request = None):
    cid = payload.collaborator_id
    # Modo "teste admin": admin/auditor pode finalizar nota de qualquer cid
    # — EXCETO quando o admin também é o próprio colaborador da nota
    # (collaborator_id no JWT == cid recebido), pois nesse caso seria
    # "app próprio" e a action ainda é dele. Se for app de OUTRO técnico
    # (cross-mode), a finalização é BLOQUEADA — admin está em modo gestor
    # SOMENTE LEITURA.
    is_admin_test = False
    is_admin_cross_mode = False
    try:
        auth_header = (request.headers.get("authorization") or "") if request else ""
        if auth_header.lower().startswith("bearer "):
            from auth import decode_token
            payload_jwt = decode_token(auth_header.split(" ", 1)[1].strip())
            if payload_jwt and payload_jwt.get("role") in ("administrador", "auditor"):
                own_collab = payload_jwt.get("collaborator_id")
                if own_collab and own_collab == cid:
                    is_admin_test = False  # app próprio
                else:
                    is_admin_cross_mode = True
                    is_admin_test = True  # legado, mas será bloqueado abaixo
    except Exception:
        is_admin_test = False
    if is_admin_cross_mode:
        raise HTTPException(
            403,
            "Modo gestor é somente leitura — para finalizar esta nota, "
            "peça ao colaborador atribuído ou troque para o app dele.",
        )
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    if (not is_admin_test) and t.get("assigned_collaborator_id") != cid:
        raise HTTPException(404, "Nota não encontrada")
    if t["status"] != "aberta":
        raise HTTPException(400, "Somente notas abertas podem ser finalizadas")

    # ======================================================================
    # REGRA: técnico/instalador/reparador NÃO PODE finalizar OS "informada"
    # (sem execução). Apenas o gestor pode encerrar essa OS após contatar
    # o cliente. O técnico solicita o contato; cria pedido em
    # `lousa_manager_callback_requests` e bloqueia o fechamento.
    # `is_admin_test=True` significa que um administrador/auditor está
    # operando no próprio app — esses podem finalizar normalmente.
    # ======================================================================
    if payload.outcome == "informada" and not is_admin_test:
        cd = payload.completion_data
        motivo = (cd.observacoes or "").strip()
        if len(motivo) < 5:
            raise HTTPException(400, {
                "code": "INFORMADA_REQUIRES_REASON",
                "message": (
                    "Para registrar 'sem execução', escreva no campo de "
                    "observações o motivo (ex: cliente ausente, endereço "
                    "incorreto, recusou atendimento, sem acesso ao poste, "
                    "etc). Mínimo 5 caracteres."
                ),
            })
        snap = t.get("client_snapshot") or {}
        req_id = f"mcr-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        ticket_company_id = t.get("company_id") or DEMO_COMPANY_ID
        await db.lousa_manager_callback_requests.insert_one({
            "id": req_id,
            "company_id": ticket_company_id,
            "ticket_id": ticket_id,
            "ticket_type": t.get("type"),
            "ticket_atlaz_protocolo": t.get("atlaz_protocolo"),
            "collaborator_id": cid,
            "collaborator_name": t.get("assigned_collaborator_name")
                or "Técnico",
            "client_name": snap.get("name") or "",
            "client_phone": snap.get("phone") or "",
            "client_address": snap.get("address") or "",
            "client_neighborhood": snap.get("neighborhood") or "",
            "motivo": motivo,
            "fotos_count": len(cd.fotos or []),
            "fotos": cd.fotos[:6] if cd.fotos else [],
            "sinal": cd.sinal,
            "latitude": payload.latitude,
            "longitude": payload.longitude,
            "status": "pending",       # pending | contacted | resolved
            "created_at": now.isoformat(),
            "requested_at": now.isoformat(),
        })
        # Marca a OS como "aguardando_gestor" (NÃO é finalizada ainda).
        # O gestor decide se: a) reagenda; b) fecha como improdutiva
        # após contato; c) realoca pra outro técnico.
        await db.tickets.update_one(
            {"id": ticket_id},
            {"$set": {
                "manager_callback_required": True,
                "manager_callback_request_id": req_id,
                "manager_callback_motivo": motivo,
                "manager_callback_requested_by": cid,
                "manager_callback_requested_at": now.isoformat(),
                # status fica "aberta" — não fechamos. Adicionamos flag visual
                "needs_manager_action": True,
            }},
        )
        # Notifica gestores em tempo real
        try:
            await db.notifications.insert_one({
                "id": f"notif-{uuid.uuid4().hex[:10]}",
                "company_id": ticket_company_id,
                "type": "manager_callback_required",
                "severity": "warning",
                "title": "📞 Contato com cliente solicitado pelo técnico",
                "body": (
                    f"{t.get('assigned_collaborator_name', 'Técnico')} "
                    f"informou que a OS de "
                    f"{snap.get('name') or 'cliente'} "
                    f"não pode ser executada. Motivo: {motivo[:120]}"
                ),
                "ticket_id": ticket_id,
                "callback_request_id": req_id,
                "target_roles": ["gestor", "administrador"],
                "read_by": [],
                "created_at": now.isoformat(),
            })
        except Exception as e:
            logger.warning("[lousa] notif callback fail: %s", e)
        logger.info("[lousa] OS %s — técnico %s solicitou contato do gestor "
                    "(motivo=%s)", ticket_id, cid, motivo[:60])
        return {
            "ok": True,
            "blocked_close": True,
            "manager_callback_required": True,
            "callback_request_id": req_id,
            "message": (
                "OS marcada como aguardando contato do gestor. "
                "Você NÃO pode fechá-la sem execução — o gestor entrará "
                "em contato com o cliente e decidirá os próximos passos."
            ),
        }

    cd = payload.completion_data
    # Wizard 2-passos (iter89+) coleta foto do equipamento (obrigatória) + opcional foto
    # da etiqueta (OCR SN/MAC). Mínimo passa a ser 1 foto — front já bloqueia avanço sem
    # ela via photo-required-modal.
    # CTO 13/06/2026 — RESPEITA toggles globais. Em Modo Relaxado
    # (cto_photo_required=False E mac_validation_required=False), pula
    # essa trava de foto/ONT. Decisão do admin em Configurações vale aqui.
    company_id_for_toggles = t.get("company_id") or DEMO_COMPANY_ID
    try:
        _toggles_doc = await db.aihub_settings.find_one(
            {"company_id": company_id_for_toggles,
             "key": "os_validation_toggles"},
            {"_id": 0, "value": 1},
        ) or {}
        _toggles = (_toggles_doc.get("value") or {})
    except Exception:
        _toggles = {}
    _cto_photo_required_toggle = bool(_toggles.get("cto_photo_required", False))
    _mac_validation_required_toggle = bool(_toggles.get("mac_validation_required", False))
    _photo_enforcement_on = (_cto_photo_required_toggle
                             or _mac_validation_required_toggle)
    if (t["type"] == "instalacao" and len(cd.fotos) < 1
            and _photo_enforcement_on and not is_admin_test):
        raise HTTPException(400, "Instalação exige pelo menos 1 foto do equipamento")
    if t["type"] == "instalacao" and not cd.ont:
        raise HTTPException(400, "ONT é obrigatório para instalação")

    # iter215z — Porta da CTO OBRIGATÓRIA em instalação e reparo (regra
    # global pedida pelo user 2026-06). Bloqueia o fechamento se cto_id
    # ou cto_port_number ausentes. Admin/auditor (is_admin_test) e
    # super-unlock (full unlock) podem driblar — mas a OS recebe flag.
    cto_port_required = bool(_toggles.get("cto_port_required", True))
    if (cto_port_required
            and t["type"] in ("instalacao", "reparo", "troca_endereco")
            and not is_admin_test):
        if not cd.cto_id or not cd.cto_port_number:
            raise HTTPException(400, {
                "code": "CTO_PORT_REQUIRED",
                "message": (
                    f"OS de {t['type']} exige seleção da CTO e da porta "
                    "(regra global). Volte ao passo da CTO, escolha a "
                    "caixa, a porta livre e finalize. O cliente será "
                    "registrado automaticamente na porta e na Base de "
                    "Portas."
                ),
                "missing_cto_id": not cd.cto_id,
                "missing_cto_port_number": not cd.cto_port_number,
            })

    # iter215am — Em OS de retirada/troca: se o SN da ONT NÃO existe no
    # SmartOLT, técnico DEVE fotografar o equipamento (Claude Sonnet 4.6
    # analisa depois). Sempre registra movimentação no estoque do
    # colaborador (via stok.py — fluxo já existente).
    sn_required = bool((_toggles or {}).get("sn_smartolt_or_photo_required",
                                              True))
    # iter215ar — Regra global: se o CLIENTE não está cadastrado no
    # SmartOLT (sem match de PPPoE nem nome), pula TODAS as validações
    # relacionadas a SmartOLT. Faz sentido pra ISPs com clientes em
    # OLTs diferentes (FIBRA CITY etc.) ou ONTs em bridge.
    client_in_smartolt = False
    if sn_required and t["type"] in ("retirada", "troca") and not is_admin_test:
        try:
            from routes.smartolt import resolve_signal_for_ticket
            _match = await resolve_signal_for_ticket(t)
            client_in_smartolt = bool(_match)
        except Exception as _re:
            logger.warning(
                "[lousa] resolve_signal pra checagem SmartOLT falhou "
                "ticket=%s: %s", ticket_id, _re)
            client_in_smartolt = False
    if (sn_required
            and client_in_smartolt
            and t["type"] in ("retirada", "troca")
            and not is_admin_test):
        ont_sn = (cd.ont or "").strip().upper()
        sn_in_smartolt = False
        if ont_sn:
            onu = await db.smartolt_onus.find_one(
                {"company_id": company_id_for_toggles,
                 "sn": {"$regex": f"^{ont_sn}$", "$options": "i"}},
                {"_id": 0, "sn": 1},
            )
            sn_in_smartolt = bool(onu)
        if not sn_in_smartolt and len(cd.fotos or []) < 1:
            raise HTTPException(400, {
                "code": "SN_PHOTO_REQUIRED",
                "message": (
                    f"OS de {t['type']} sem SN cadastrado no SmartOLT "
                    "exige FOTO do equipamento (regra global). Volte e "
                    "anexe pelo menos 1 foto do equipamento retirado. "
                    "A IA vai analisar e o item será registrado no seu "
                    "estoque automaticamente."
                ),
                "sn_provided": ont_sn or None,
                "sn_in_smartolt": False,
            })
        # Marca para análise IA assíncrona (Claude Sonnet 4.6) se não tem
        # SN no SmartOLT mas tem foto. O worker pega depois e atualiza
        # o registro de estoque com SN/MAC/modelo extraídos da etiqueta.
        if not sn_in_smartolt and (cd.fotos or []):
            await db.tickets.update_one(
                {"id": ticket_id},
                {"$set": {
                    "ai_sn_photo_review_pending": True,
                    "ai_sn_photo_model": "claude-sonnet-4-6",
                    "ai_sn_photo_queued_at": now_iso(),
                }},
            )
            try:
                from services.event_bus import emit_event
                await emit_event(
                    "ticket.updated",
                    company_id=(onu or {}).get("company_id"),
                    source="lousa",
                    payload={},
                )
            except Exception:
                pass
            # Cria entrada pendente no estoque do técnico — fica como
            # `pending_ai_review` (ou `bloqueado_defeito` quando o técnico
            # marcou defeito). O worker assíncrono preenche SN/MAC depois.
            try:
                snap_ce = t.get("client_snapshot") or {}
                is_def = bool(cd.is_defective)
                pending_status = ("bloqueado_defeito" if is_def
                                   else "pending_ai_review")
                pending_id = f"ont-pending-{uuid.uuid4().hex[:10]}"
                # captura a 1ª foto pra rastreabilidade (data URL)
                first_photo = None
                for _f in (cd.fotos or []):
                    if isinstance(_f, str) and _f.startswith("data:image"):
                        first_photo = _f
                        break
                    if isinstance(_f, dict):
                        _u = _f.get("dataUrl") or _f.get("url") or _f.get("data")
                        if isinstance(_u, str) and _u.startswith("data:image"):
                            first_photo = _u
                            break
                await db.stok_onts.insert_one({
                    "id": pending_id,
                    "company_id": company_id_for_toggles,
                    "sn": None,
                    "mac": None,
                    "model": None,
                    "location_type": "tecnico",
                    "location_id": cid,
                    "location": cid,
                    "status": pending_status,
                    "is_defective": is_def,
                    "defective_reason": (cd.defective_reason or None)
                                           if is_def else None,
                    "source": "lousa_retirada_troca_photo",
                    "via_photo_ai": True,
                    "ai_review_pending": True,
                    "ticket_id": ticket_id,
                    "withdrawn_via_ticket": ticket_id,
                    "withdrawn_from_client_id": snap_ce.get("id"),
                    "withdrawn_from_client_name": snap_ce.get("name"),
                    "withdrawn_by_name": t.get("assigned_collaborator_name"),
                    "withdrawn_at": now_iso(),
                    "photo_sample": first_photo,
                    "created_at": now_iso(),
                })
                # Histórico (visível em /estoque/historico)
                try:
                    await db.stok_history.insert_one({
                        "id": str(uuid.uuid4()),
                        "company_id": company_id_for_toggles,
                        "date": now_iso(),
                        "type": "retirada" if t["type"] == "retirada"
                                  else "instalacao",
                        "description": (
                            f"Equipamento retirado SEM SN no SmartOLT "
                            f"(ticket {ticket_id}). Foto enviada — "
                            f"análise IA pendente. Status: {pending_status}."
                            + (" DEFEITUOSO — bloqueado." if is_def else "")
                        ),
                        "user": (t.get("assigned_collaborator_name")
                                  or "Técnico"),
                        "tag": "lousa_photo_ai_pending",
                        "ticket_id": ticket_id,
                        "pending_ont_id": pending_id,
                    })
                except Exception as _he:
                    logger.warning(
                        "[lousa] stok_history pending falhou: %s", _he)
                logger.info(
                    "[lousa] ticket=%s ONT pendente criada (id=%s, "
                    "tech=%s, defeito=%s) — aguarda IA.",
                    ticket_id, pending_id, cid, is_def,
                )
            except Exception as _pe:
                logger.warning(
                    "[lousa] criação ONT pendente falhou ticket=%s: %s",
                    ticket_id, _pe,
                )

    company_id = t.get("company_id") or DEMO_COMPANY_ID

    # ============================================================
    # iter211bj — GEOFENCE configurável (default 100m) do endereço do cliente
    # ------------------------------------------------------------
    # Regra: técnico SÓ pode finalizar a OS estando a até GEOFENCE_RADIUS_M
    # do endereço cadastrado do cliente. Admin/gestor pula essa regra
    # (mas a OS finalizada por gestor recebe flag `closed_outside_geofence`
    # e fica excluída dos KPIs do técnico).
    # iter223 — raio agora é configurável por empresa via
    # db.settings.geofence_radius_m (admin pode subir/descer).
    # ============================================================
    _settings_geo = await db.settings.find_one(
        {"id": company_id}, {"_id": 0, "geofence_radius_m": 1}) or {}
    try:
        GEOFENCE_RADIUS_M = int(_settings_geo.get("geofence_radius_m") or 100)
    except (TypeError, ValueError):
        GEOFENCE_RADIUS_M = 100
    GEOFENCE_RADIUS_M = max(20, min(GEOFENCE_RADIUS_M, 5000))
    snap_for_geo = t.get("client_snapshot") or {}
    client_lat = snap_for_geo.get("lat") or snap_for_geo.get("latitude")
    client_lng = snap_for_geo.get("lng") or snap_for_geo.get("longitude")
    tech_lat = payload.latitude
    tech_lng = payload.longitude
    closed_outside_geofence = False
    geofence_distance_m = None
    if (not is_admin_test and client_lat is not None and client_lng is not None
        and tech_lat is not None and tech_lng is not None):
        try:
            import math
            R = 6371000.0  # raio da Terra em metros
            la1, lo1 = math.radians(float(client_lat)), math.radians(float(client_lng))
            la2, lo2 = math.radians(float(tech_lat)), math.radians(float(tech_lng))
            dla = la2 - la1
            dlo = lo2 - lo1
            a = (math.sin(dla / 2) ** 2
                 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2)
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            geofence_distance_m = R * c
            if geofence_distance_m > GEOFENCE_RADIUS_M:
                tech_first_name = (t.get("assigned_collaborator_name") or "").split(" ")[0] or "Técnico"
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "OUTSIDE_GEOFENCE",
                        "message": (
                            f"❌ Você está a {int(geofence_distance_m)}m do endereço "
                            f"da OS (limite: {GEOFENCE_RADIUS_M}m).\n\n"
                            f"Vá até o endereço do cliente para finalizar.\n\n"
                            f"Se o serviço foi executado em outro local, peça ao "
                            f"gestor para finalizar a OS manualmente."
                        ),
                        "distance_m": int(geofence_distance_m),
                        "radius_m": GEOFENCE_RADIUS_M,
                        "technician_first_name": tech_first_name,
                    },
                )
        except HTTPException:
            raise
        except Exception as _ge:
            # Se haversine falhar por dados inválidos, NÃO bloqueia — apenas loga
            logger.warning("[lousa/geofence] cálculo falhou: %s", _ge)
            geofence_distance_m = None

    # Quando admin finaliza (is_admin_test=True) e o técnico estava FORA da área,
    # marca a OS pra exclusão dos KPIs (não conta como serviço realizado pelo técnico).
    if is_admin_test and client_lat is not None and client_lng is not None \
        and tech_lat is not None and tech_lng is not None:
        try:
            import math
            R = 6371000.0
            la1, lo1 = math.radians(float(client_lat)), math.radians(float(client_lng))
            la2, lo2 = math.radians(float(tech_lat)), math.radians(float(tech_lng))
            dla = la2 - la1
            dlo = lo2 - lo1
            a = (math.sin(dla / 2) ** 2
                 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2)
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            geofence_distance_m = R * c
            if geofence_distance_m > GEOFENCE_RADIUS_M:
                closed_outside_geofence = True
        except Exception:
            pass

    # === SmartOLT awareness ===
    # Cliente cadastrado na SmartOLT? Regras dependentes do SmartOLT
    # (bloqueio de sinal ruim, sn_mismatch, snapshot, detecção de swap)
    # SÓ valem quando há vínculo confirmado. Pedido do usuário:
    #   "para clientes que não estão cadastrados na smartolt, não peça
    #    regras de quem está."
    smartolt_onu = await _resolve_smartolt_for_ticket(t)
    is_smartolt_client = bool(smartolt_onu)

    # === CENTRAL_ONT: validação de sinal ruim + autorização ===
    cfg = await db.central_ont_settings.find_one(
        {"company_id": company_id}, {"_id": 0},
    ) or {}
    threshold = float(cfg.get("bad_signal_threshold", -27.0))
    block_enabled = bool(cfg.get("block_bad_signal_close", False))
    is_bad_signal = cd.sinal is not None and cd.sinal < threshold

    auth_used = None
    # SÓ aplicamos o bloqueio quando o cliente está mapeado no SmartOLT
    # (sem mapeamento, o valor de sinal é digitado pelo técnico sem
    # validação remota — não dá pra cobrar autorização nesse caso).
    if is_bad_signal and block_enabled and is_smartolt_client:
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
    # Só faz sentido quando o cliente está mapeado no SmartOLT.
    sn_mismatch = None
    if is_smartolt_client and cd.ont:
        try:
            smartolt_sn = (smartolt_onu.get("sn") or "").strip()
            if (smartolt_sn
                    and _norm_hexid(cd.ont) != _norm_hexid(smartolt_sn)):
                sn_mismatch = {"smartolt_sn": smartolt_sn, "typed_sn": cd.ont}
        except Exception:
            pass

    # === Detecta troca de ONT/ONU (reparo/troca_endereco) e persiste
    # MAC retirado + MAC novo no completion_data + auditoria global. ===
    equipment_swap = _detect_equipment_swap(t, cd, smartolt_onu)
    # Verifica via uptime do SmartOLT — se a ONU está online há > 10min sem
    # reboot, a troca é considerada SUSPEITA (provavelmente não houve
    # substituição física). Auditado no card mensal.
    if equipment_swap:
        # Pra obter um `last_status_change` fresco, preferimos uma leitura
        # live da SmartOLT (best-effort). Se falhar, caímos no cache.
        fresh_onu = smartolt_onu
        try:
            ext_id = (smartolt_onu or {}).get("unique_external_id")
            if ext_id:
                cfg = await db.smartolt_configs.find_one(
                    {"company_id": company_id}, {"_id": 0},
                ) or {}
                if cfg.get("enabled") and cfg.get("subdomain") and cfg.get("api_key"):
                    from routes.smartolt import _http_get  # type: ignore
                    class _CfgShim:
                        pass
                    shim = _CfgShim()
                    shim.subdomain = cfg["subdomain"]
                    shim.api_key = cfg["api_key"]
                    shim.timeout_seconds = cfg.get("timeout_seconds", 8)
                    st = await _http_get(shim, f"/onu/get_onu_status/{ext_id}")
                    st_resp = (st or {}).get("response") or {}
                    if st_resp:
                        fresh_onu = dict(smartolt_onu or {})
                        fresh_onu["status"] = (st_resp.get("status")
                                                  or fresh_onu.get("status"))
                        fresh_onu["last_status_change"] = (
                            st_resp.get("last_status_change")
                            or fresh_onu.get("last_status_change")
                        )
        except Exception as e:
            logger.info("[lousa] live status fetch (swap verify) falhou: %s", e)
        swap_verification = await _verify_swap_via_uptime(fresh_onu)
        equipment_swap["verification"] = swap_verification

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
    # Anexa swap detectado ao completion_data (espelhado no ticket)
    if equipment_swap:
        cd_dump["equipment_swap"] = equipment_swap
        cd_dump["old_ont_mac"] = equipment_swap.get("old_mac")
        cd_dump["old_ont_sn"]  = equipment_swap.get("old_sn")
        cd_dump["new_ont_mac"] = equipment_swap.get("new_mac")
        cd_dump["new_ont_sn"]  = equipment_swap.get("new_sn")

    # iter211bj — Quando admin/gestor finalizou OS com técnico fora do raio,
    # marca a OS pra exclusão dos KPIs do técnico e adiciona a observação
    # padronizada.
    tech_first = (t.get("assigned_collaborator_name") or "").split(" ")[0] or "Técnico"
    geofence_note = (f"O técnico {tech_first} não estava na região "
                       f"em que foi executado o serviço.")
    obs_atual = (cd_dump.get("observacoes") or "").strip()
    if closed_outside_geofence:
        cd_dump["observacoes"] = (geofence_note + (
            f"\n\n— Observação do técnico: {obs_atual}" if obs_atual else ""
        ))

    # ════════════════════════════════════════════════════════════════════
    # CTO 2026-02 — REGRA GLOBAL ESTOQUE OS (técnico via app).
    # Chokepoint idêntico ao admin-close. Bloqueia ANTES do write final.
    # Aplica-se apenas a outcome="executada" (informada já saiu acima).
    # is_admin_test (admin operando no app próprio) pula pra não bloquear
    # cenários de homologação interna.
    # ════════════════════════════════════════════════════════════════════
    guardrail_result = None
    if payload.outcome == "executada" and not is_admin_test:
        from services.os_inventory_guardrail import (
            enforce_os_inventory_movement, explain_block,
        )
        comp_g = dict(cd_dump)
        comp_g["physical_attendance"] = True
        # Pra troca, propaga old/new vindos do equipment_swap detectado
        if equipment_swap:
            comp_g.setdefault("old_ont_mac",
                              equipment_swap.get("old_mac"))
            comp_g.setdefault("old_ont_sn",
                              equipment_swap.get("old_sn"))
            comp_g.setdefault("new_ont_mac",
                              equipment_swap.get("new_mac"))
            comp_g.setdefault("new_ont_sn",
                              equipment_swap.get("new_sn"))
        actor_g = {
            "id": cid, "role": "colaborador", "email": None,
            "name": t.get("assigned_collaborator_name") or "Técnico",
            "origin": "tecnico_app",
            "is_super_admin": False,
        }
        guardrail_result = await enforce_os_inventory_movement(
            t, comp_g, actor_g)
        if not guardrail_result["allowed"]:
            raise HTTPException(403, {
                "error": "os_inventory_guardrail_bloqueou",
                "blocked_reasons": guardrail_result["blocked_reasons"],
                "human_reason": explain_block(
                    guardrail_result["blocked_reasons"]),
                "classification": guardrail_result["classification"],
                "audit_ids": guardrail_result["audit_ids"],
            })

    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {
            "status": "finalizada", "outcome": payload.outcome,
            "closed_at": now_iso(), "closed_by": cid,
            "close_location": {"latitude": payload.latitude, "longitude": payload.longitude},
            "completion_data": cd_dump,
            "smartolt_managed": is_smartolt_client,
            "equipment_swap": equipment_swap,  # null quando não houve troca
            # V9 P2 — propaga campos derivados para raiz do ticket
            "resolution_kind": cd_dump.get("resolution_kind"),
            "asset_recovered": cd_dump.get("asset_recovered"),
            "signed_receipt": cd_dump.get("signed_receipt"),
            # iter211bj — flags geofence
            "geofence_distance_m": (int(geofence_distance_m)
                                       if geofence_distance_m is not None else None),
            "closed_outside_geofence": closed_outside_geofence,
            "exclude_from_kpis": closed_outside_geofence,
            "geofence_note": (geofence_note if closed_outside_geofence else None),
            "central_ont": {
                "sinal": cd.sinal,
                "is_bad_signal": is_bad_signal,
                "threshold": threshold,
                "auth_used": auth_used,
                "sn_mismatch": sn_mismatch,
            },
            # CTO 2026-02 — Snapshot do guardrail + status pendente_conciliacao
            **({
                "os_inventory_guardrail": {
                    "classification": guardrail_result["classification"],
                    "movements": guardrail_result["movements"],
                    "smartolt": guardrail_result["smartolt"],
                    "smartolt_override_applied":
                        guardrail_result["smartolt_override_applied"],
                    "audit_ids": guardrail_result["audit_ids"],
                    "origin": "tecnico_app",
                },
            } if guardrail_result else {}),
            **({"status": "pendente_conciliacao",
                "pending_conciliation_reason":
                  "SmartOLT indisponível — fila de reconciliação.",
                "pending_conciliation_at": now_iso(),
                "pending_conciliation_retries": 0}
                if (guardrail_result
                    and guardrail_result.get("os_pending_conciliation"))
                else {}),
        }},
    )
    # Vincula cliente à porta da CTO (instalação/reparo).
    # iter215aa — Agora usa _smart_link_client_to_port que valida:
    #   • porta ocupada por OUTRO cliente → bloqueia (HTTP 409)
    #   • cliente em OUTRA porta → libera antiga (port_swap)
    #   • mesma porta/cliente → no-op
    if cd.cto_id and cd.cto_port_number:
        try:
            cs = t.get("client_snapshot") or {}
            coll_doc = await db.collaborators.find_one(
                {"id": cid}, {"_id": 0, "name": 1, "email": 1}) or {}
            await _smart_link_client_to_port(
                company_id=company_id,
                cto_id=cd.cto_id,
                port_number=cd.cto_port_number,
                client_id=cs.get("id"),
                client_name=cs.get("name"),
                client_pppoe=cs.get("pppoe_user") or t.get("pppoe_user"),
                actor_email=coll_doc.get("email"),
                actor_id=cid,
                actor_name=coll_doc.get("name"),
                ticket_id=ticket_id,
            )
        except HTTPException:
            # Porta ocupada por outro cliente — propaga pro técnico
            raise
        except Exception as e:
            logger.warning("[lousa] vínculo CTO porta falhou: %s", e)
    # Background: análise IA da foto da CTO (se houver foto tirada nesta OS)
    if cd.cto_id and background_tasks is not None:
        try:
            cto_photos = [f for f in (cd.fotos or [])
                            if isinstance(f, dict)
                            and (f.get("kind") or "").lower() == "cto"
                            and (f.get("dataUrl") or f.get("data_url"))]
            if cto_photos:
                # Pega a primeira foto da CTO desta OS
                first = cto_photos[0]
                data_url = first.get("dataUrl") or first.get("data_url")
                from services.cto_photo_inspector import analyze_and_persist_for_cto
                background_tasks.add_task(analyze_and_persist_for_cto,
                                           data_url, cd.cto_id, ticket_id)
        except Exception as e:
            logger.warning("[lousa] agendamento análise foto CTO falhou: %s", e)
    # Quality notes — snapshot do sinal NO FECHAMENTO (SmartOLT live, honra toggle)
    # Só faz sentido pra clientes mapeados no SmartOLT.
    if is_smartolt_client:
        await _capture_signal_snapshot(ticket_id, company_id, "close")
    # iter232 — Revoga tokens de bridge da ONT (técnico não acessa mais SmartOLT)
    await _revoke_onu_bridge_tokens_for_ticket(ticket_id, "OS finalizada")
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0, "name": 1})
    coll_name = (coll or {}).get("name", "Técnico")
    # Persiste auditoria global da troca de equipamento + notifica gestor.
    if equipment_swap:
        await _persist_equipment_swap(
            ticket_id=ticket_id, company_id=company_id,
            swap=equipment_swap, technician_id=cid, technician_name=coll_name,
        )
        verif = equipment_swap.get("verification") or {}
        verified = verif.get("verified")
        if verified is False:
            # Troca SUSPEITA — ONU online há mais que o threshold sem reboot.
            await _create_notification(
                type_="equipment_swap_suspect",
                title="🚨 Troca de ONT/ONU SUSPEITA",
                message=(
                    f"{coll_name} declarou troca em "
                    f"{t['client_snapshot'].get('name','—')}, mas a ONU está "
                    f"online há {verif.get('uptime_minutes','?')} min sem "
                    f"reboot (limite {verif.get('threshold_minutes')} min). "
                    f"Provavelmente o equipamento NÃO foi substituído."
                ),
                collaborator_id=cid, ticket_id=ticket_id,
                company_id=company_id, severity="warning",
            )
        else:
            await _create_notification(
                type_="equipment_swap",
                title="🔁 Troca de ONT/ONU registrada",
                message=(
                    f"{coll_name} trocou o equipamento em "
                    f"{t['client_snapshot'].get('name','—')}. "
                    f"MAC retirado: {equipment_swap.get('old_mac') or equipment_swap.get('old_sn') or '—'} · "
                    f"MAC novo: {equipment_swap.get('new_mac') or equipment_swap.get('new_sn') or '—'}"
                ),
                collaborator_id=cid, ticket_id=ticket_id,
                company_id=company_id, severity="info",
            )
    await _log_ticket_action(
        ticket_id=ticket_id, action="finalizada",
        actor_id=cid, actor_name=coll_name,
        actor_role="colaborador",
        details=(
            f"ONT={cd.ont or '-'} · sinal={cd.sinal} dBm · "
            f"fotos={len(cd.fotos)}"
            + (f" · TROCA: {equipment_swap.get('old_mac') or equipment_swap.get('old_sn') or '-'}"
               f" → {equipment_swap.get('new_mac') or equipment_swap.get('new_sn') or '-'}"
               if equipment_swap else "")
        ),
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

    # === Workflow específico de RETIRADA ===
    # 1) Envia "COMPROVANTE DE DEVOLUÇÃO DE EQUIPAMENTO" via WhatsApp
    # 2) Solicita remoção da ONU no SmartOLT (best-effort)
    if t.get("type") == "retirada" and background_tasks is not None:
        try:
            from services.retirada_workflow import (
                send_retirada_comprovante,
                request_smartolt_remove,
            )
            full_ticket = await db.tickets.find_one(
                {"id": ticket_id}, {"_id": 0})
            background_tasks.add_task(
                send_retirada_comprovante,
                company_id=company_id,
                ticket=full_ticket,
                technician_name=coll_name,
                ont_mac_sn=cd.ont,
            )
            if is_smartolt_client:
                background_tasks.add_task(
                    request_smartolt_remove,
                    company_id=company_id,
                    ticket=full_ticket,
                    smartolt_onu=smartolt_onu,
                )
        except Exception as e:
            logger.warning("[lousa] retirada workflow agendamento falhou: %s", e)

    result = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    # CTO 13/06/2026 — EventBus operacional: OS finalizada pelo mobile
    try:
        from services.event_bus import emit_event, EventType
        await emit_event(
            "FIELD_OS_COMPLETED",
            company_id=result.get("company_id") or DEMO_COMPANY_ID,
            user_id=payload.collaborator_id,
            source="lousa.public_finalize",
            severity="critica" if is_bad_signal else "media",
            payload={
                "ticket_id": ticket_id, "outcome": payload.outcome,
                "type": result.get("type"),
                "assigned_collaborator_id": payload.collaborator_id,
                "sinal": cd.sinal, "bad_signal": is_bad_signal,
                "duration_minutes": result.get("execution_minutes"),
            },
        )
        # Sinaliza TICKET_CLOSED canônico também (cobre dashboards legados)
        await emit_event(
            EventType.TICKET_CLOSED,
            company_id=result.get("company_id") or DEMO_COMPANY_ID,
            user_id=payload.collaborator_id,
            source="lousa.public_finalize",
            severity="media",
            payload={"ticket_id": ticket_id, "outcome": payload.outcome},
        )
        # CTO 13/06/2026 — Evento canônico operacional "ticket.finalized"
        await emit_event(
            "ticket.finalized",
            company_id=result.get("company_id") or DEMO_COMPANY_ID,
            user_id=payload.collaborator_id,
            source="lousa.public_finalize",
            severity="media",
            payload={
                "ticket_id": ticket_id, "outcome": payload.outcome,
                "type": result.get("type"),
                "assigned_collaborator_id": payload.collaborator_id,
                "sinal": cd.sinal, "bad_signal": is_bad_signal,
            },
        )
    except Exception as _e:
        logger.warning("[lousa] emit FIELD_OS_COMPLETED falhou: %s", _e)
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
    raw.sort(key=lambda t: (_prio_rank(t.get("priority")), t.get("position", 0)))
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

    company_id = t.get("company_id") or DEMO_COMPANY_ID
    # SmartOLT-aware: detecta troca de ONT/ONU e relaxa snapshot quando o
    # cliente não está mapeado.
    smartolt_onu = await _resolve_smartolt_for_ticket(t)
    is_smartolt_client = bool(smartolt_onu)
    equipment_swap = _detect_equipment_swap(t, cd, smartolt_onu)
    if equipment_swap:
        # Verificação por uptime (best-effort, sem live fetch nesta rota
        # autenticada — usamos o cache do SmartOLT, mais barato).
        equipment_swap["verification"] = await _verify_swap_via_uptime(
            smartolt_onu,
        )

    cd_dump = cd.model_dump()
    cd_dump["ping_summary"] = ping_summary
    obs_field = cd_dump.get("observations") or cd_dump.get("laudo") or ""
    cd_dump["observations"] = (
        (obs_field.rstrip() + "\n\n" + ping_summary)
        if obs_field else ping_summary
    )
    if equipment_swap:
        cd_dump["equipment_swap"] = equipment_swap
        cd_dump["old_ont_mac"] = equipment_swap.get("old_mac")
        cd_dump["old_ont_sn"]  = equipment_swap.get("old_sn")
        cd_dump["new_ont_mac"] = equipment_swap.get("new_mac")
        cd_dump["new_ont_sn"]  = equipment_swap.get("new_sn")

    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {
            "status": "finalizada",
            "outcome": payload.outcome,
            "closed_at": now_iso(),
            "closed_by": user["id"],
            "close_location": {"latitude": payload.latitude, "longitude": payload.longitude},
            "completion_data": cd_dump,
            "smartolt_managed": is_smartolt_client,
            "equipment_swap": equipment_swap,
            # V9 P2 — propaga campos derivados para raiz do ticket
            # (lidos por company_v6._ensure_smart_record)
            "resolution_kind": cd_dump.get("resolution_kind"),
            "asset_recovered": cd_dump.get("asset_recovered"),
            "signed_receipt": cd_dump.get("signed_receipt"),
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
    try:
        from services.event_bus import emit_event
        await emit_event(
            "ticket.updated",
            company_id=company_id,
            source="lousa",
            payload={},
        )
    except Exception:
        pass
    # Quality notes — snapshot do sinal NO FECHAMENTO (apenas SmartOLT-mapped)
    if is_smartolt_client:
        await _capture_signal_snapshot(ticket_id, company_id, "close")
    # iter232 — Revoga tokens de bridge da ONT (técnico não acessa mais SmartOLT)
    await _revoke_onu_bridge_tokens_for_ticket(ticket_id, "OS finalizada")
    # Auditoria de troca de equipamento
    if equipment_swap:
        await _persist_equipment_swap(
            ticket_id=ticket_id, company_id=company_id,
            swap=equipment_swap, technician_id=cid,
            technician_name=(user.get("name") or "Técnico"),
        )
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


# ---------------------------------------------------------------------------
# Equipment Swap audit — lista trocas de ONT/ONU registradas em finalizações
# ---------------------------------------------------------------------------
@router.get("/lousa/equipment-swaps")
async def list_equipment_swaps(limit: int = 100,
                                  user: dict = Depends(get_current_user)):
    """Lista as últimas trocas de ONT/ONU registradas.

    Cada item corresponde a uma OS finalizada onde o MAC/SN novo (instalado
    pelo técnico) era diferente do MAC/SN antigo (registrado no SmartOLT ou
    informado manualmente). Filtra por `company_id` do usuário."""
    if user.get("role") not in ("administrador", "gestor", "auditor"):
        raise HTTPException(403, "Apenas gestor/administrador/auditor")
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cur = db.equipment_swaps.find(
        {"company_id": cid}, {"_id": 0},
    ).sort("created_at", -1).limit(min(max(limit, 1), 500))
    items = await cur.to_list(500)
    return {"company_id": cid, "count": len(items), "items": items}


@router.get("/lousa/equipment-swaps/monthly-report")
async def equipment_swaps_monthly_report(
        months: int = 6,
        user: dict = Depends(get_current_user),
):
    """Relatório mensal de trocas de ONT/ONU — card de auditoria.

    Agrega `equipment_swaps` por mês (YYYY-MM) e por técnico, distinguindo
    trocas LEGÍTIMAS (`verified=true`/`null`) vs SUSPEITAS (`verified=false`,
    geralmente porque a ONU não passou por reboot — uptime > threshold).
    `months` = janela em meses (default 6, max 24).
    """
    if user.get("role") not in ("administrador", "gestor", "auditor"):
        raise HTTPException(403, "Apenas gestor/administrador/auditor")
    cid = user.get("company_id") or DEMO_COMPANY_ID
    months = min(max(months, 1), 24)
    cutoff = (datetime.now(timezone.utc)
                - timedelta(days=months * 31)).isoformat()
    cur = db.equipment_swaps.find(
        {"company_id": cid, "created_at": {"$gte": cutoff}},
        {"_id": 0},
    ).sort("created_at", -1).limit(5000)
    rows = await cur.to_list(5000)
    # Agrega por mês + técnico
    by_month: Dict[str, Dict[str, Any]] = {}
    by_tech: Dict[str, Dict[str, Any]] = {}
    total_legit = 0
    total_suspect = 0
    total_unknown = 0
    for r in rows:
        ym = (r.get("created_at") or "")[:7]  # "YYYY-MM"
        verified = r.get("verified")
        legit = bool(verified)
        suspect = verified is False
        unknown = verified is None
        if legit:
            total_legit += 1
        if suspect:
            total_suspect += 1
        if unknown:
            total_unknown += 1
        m = by_month.setdefault(ym, {
            "month": ym, "total": 0, "legit": 0, "suspect": 0, "unknown": 0,
        })
        m["total"] += 1
        m["legit"] += int(legit)
        m["suspect"] += int(suspect)
        m["unknown"] += int(unknown)
        tid = r.get("technician_id") or "—"
        tname = r.get("technician_name") or "—"
        tk = by_tech.setdefault(tid, {
            "technician_id": tid, "technician_name": tname,
            "total": 0, "legit": 0, "suspect": 0, "unknown": 0,
        })
        tk["total"] += 1
        tk["legit"] += int(legit)
        tk["suspect"] += int(suspect)
        tk["unknown"] += int(unknown)
    months_sorted = sorted(by_month.values(), key=lambda d: d["month"], reverse=True)
    techs_sorted = sorted(by_tech.values(),
                              key=lambda d: (d["suspect"], d["total"]),
                              reverse=True)
    return {
        "company_id": cid,
        "window_months": months,
        "totals": {
            "swaps": len(rows),
            "legit": total_legit,
            "suspect": total_suspect,
            "unknown": total_unknown,
            "suspect_rate": (
                round(total_suspect / len(rows), 3) if rows else 0
            ),
            "threshold_minutes": SWAP_UPTIME_THRESHOLD_MINUTES,
        },
        "by_month": months_sorted,
        "by_technician": techs_sorted,
        # Lista de suspeitas no período (pra UI "drill-down" do card)
        "suspects": [
            r for r in rows if r.get("verified") is False
        ][:200],
    }




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
@router.get("/lousa/tickets/{ticket_id}/client-current-ont")
async def get_client_current_ont(ticket_id: str,
                                 user: dict = Depends(require_role("gestor"))):
    """iter195 — Para o gestor visualizar a ONT atualmente instalada no cliente
    ao finalizar uma Retirada pelo painel admin. Retorna {mac, scan_sn, model}
    da ONT vinculada (location_type='cliente') ou 404 se nada encontrado.
    """
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    cid = t.get("company_id") or DEMO_COMPANY_ID
    # Tenta via service ativo (mais confiável — tem o client_id explícito)
    svc = await db.stok_services.find_one(
        {"ticket_id": ticket_id, "company_id": cid, "status": "ativo"},
        {"_id": 0, "client_id": 1},
    )
    client_id = (svc or {}).get("client_id")
    if not client_id:
        # Fallback: tenta pelo subscriber via pppoe do client_snapshot
        cs = t.get("client_snapshot") or {}
        pppoe = (cs.get("pppoe") or cs.get("login") or cs.get("pppoe_user")
                 or "").strip().lower()
        if pppoe:
            sub = await db.subscribers.find_one(
                {"company_id": cid,
                 "$or": [{"pppoe_user": pppoe}, {"username": pppoe}]},
                {"_id": 0, "id": 1},
            )
            client_id = (sub or {}).get("id")
    if not client_id:
        raise HTTPException(404, "Cliente não localizado para este ticket")
    ont = await db.stok_onts.find_one(
        {"company_id": cid, "location_type": "cliente", "location_id": client_id},
        {"_id": 0, "mac": 1, "scan_sn": 1, "model": 1, "status": 1},
    )
    if not ont:
        raise HTTPException(404, "Cliente sem ONT registrada no estoque")
    # iter197 — expõe `sn` (canonical) no nível raiz para o frontend
    ont["sn"] = ont.get("scan_sn") or None
    return ont


@router.get("/lousa/tickets/{ticket_id}/tech-stock")
async def get_ticket_tech_stock(ticket_id: str,
                                user: dict = Depends(require_role("gestor"))):
    """iter196 — Lista ONTs no estoque do técnico atribuído ao ticket, para o
    gestor escolher ao finalizar uma Instalação/Troca pelo painel admin.
    Exclui ONTs marcadas como defeituosas (devolver à empresa).
    """
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    tech_id = t.get("assigned_collaborator_id")
    if not tech_id:
        raise HTTPException(404, "Ticket sem técnico atribuído")
    cid = t.get("company_id") or DEMO_COMPANY_ID
    items = await db.stok_onts.find(
        {"company_id": cid, "location_type": "tecnico", "location_id": tech_id,
         "status": {"$ne": "defeito_devolver_empresa"}},
        {"_id": 0, "mac": 1, "model": 1, "scan_sn": 1, "status": 1,
         "source": 1, "withdrawn_from_client_name": 1, "created_at": 1},
    ).sort("created_at", -1).to_list(500)
    # iter197 — expõe `sn` (canonical) e ordena: ONTs com SN primeiro
    for o in items:
        o["sn"] = o.get("scan_sn") or None
    items.sort(key=lambda x: (0 if x.get("sn") else 1, x.get("created_at") or ""))
    return {
        "technician_id": tech_id,
        "technician_name": t.get("collaborator_name"),
        "items": items,
        "total": len(items),
    }


@router.post("/lousa/tickets/{ticket_id}/admin-close")
async def admin_close_ticket(ticket_id: str, payload: AdminCloseIn,
                             user: dict = Depends(require_role("gestor"))):
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    if t["status"] in ("finalizada", "encerrada", "cancelada"):
        raise HTTPException(400, "Nota já encerrada")
    # ════════════════════════════════════════════════════════════════════
    # CTO 2026-02 — REGRA GLOBAL ESTOQUE OS (Q1=c híbrido / Q2=b auto-pull /
    # Q3=a smartolt online / Q4=b commit parcial). Chokepoint OBRIGATÓRIO
    # antes de qualquer mutação no ticket.
    # ════════════════════════════════════════════════════════════════════
    guardrail_result = None
    if payload.action == "encerrar":
        from services.os_inventory_guardrail import (
            enforce_os_inventory_movement, explain_block,
        )
        comp = dict(payload.completion_data or {})
        # Default: se o gestor não declarou explicitamente, assume Q1=c "sim"
        # quando o tipo da OS é físico (instalação/retirada/troca/reparo) E
        # houver completion_data preenchido (sinal etc.). Caso contrário, vira
        # fechamento administrativo (sem movimentação).
        phys = payload.physical_attendance
        if phys is None:
            phys = bool(payload.completion_data) and \
                (t.get("type") or "").lower() in (
                    "instalacao", "retirada", "troca", "reparo")
        comp["physical_attendance"] = phys
        if payload.admin_reason:
            comp["admin_reason"] = payload.admin_reason
        if payload.smartolt_override_motivo:
            comp["smartolt_override_motivo"] = payload.smartolt_override_motivo
        actor = {
            "id": user.get("id"),
            "name": user.get("name") or user.get("email"),
            "email": user.get("email"),
            "role": user.get("role"),
            "is_super_admin": (user.get("role") in ("super_admin",
                                                     "administrador")
                                or user.get("is_super_admin")),
        }
        guardrail_result = await enforce_os_inventory_movement(t, comp, actor)
        if not guardrail_result["allowed"]:
            raise HTTPException(403, {
                "error": "os_inventory_guardrail_bloqueou",
                "blocked_reasons": guardrail_result["blocked_reasons"],
                "human_reason": explain_block(
                    guardrail_result["blocked_reasons"]),
                "classification": guardrail_result["classification"],
                "audit_ids": guardrail_result["audit_ids"],
            })
    status_map = {"encerrar": "encerrada", "reagendar": "reagendada", "cancelar": "cancelada"}
    update = {
        "status": status_map[payload.action],
        "outcome": "informada",
        "closed_at": now_iso(),
        "closed_by": user["id"],
        "closed_by_name": user.get("name") or user.get("email"),
        "closed_by_email": user.get("email"),
        "closed_by_role": user.get("role"),
        "admin_action": payload.action,
        "admin_notes": payload.notes,
    }
    # Persiste completion_data (fechamento interno): sinal + observações.
    # Marcado com internal_close=True para diferenciar de fechamento físico.
    if payload.action == "encerrar" and payload.completion_data:
        cd = dict(payload.completion_data)
        cd.setdefault("internal_close", True)
        update["completion_data"] = cd
    # CTO 2026-02 — Anexa resultado do guardrail à OS (auditoria + status)
    if guardrail_result is not None:
        update["os_inventory_guardrail"] = {
            "classification": guardrail_result["classification"],
            "movements": guardrail_result["movements"],
            "smartolt": guardrail_result["smartolt"],
            "smartolt_override_applied":
                guardrail_result["smartolt_override_applied"],
            "audit_ids": guardrail_result["audit_ids"],
        }
        if guardrail_result.get("os_pending_conciliation"):
            update["status"] = "pendente_conciliacao"
            update["pending_conciliation_reason"] = (
                "SmartOLT indisponível na finalização — fila de reconciliação.")
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

    # iter195 — RETIRADA fechada pelo gestor: transfere o equipamento do
    # cliente para o estoque do técnico, como se o técnico tivesse feito
    # toda a retirada (auto_close_service_from_ticket + workflow de comprovante).
    # Pedido do usuário 10/02/2026: "o gestor pode finalizar e o equipamento
    # dado retirada do cliente e transferido para o estoque do tecnico
    # automaticamente como se fosse ele ter feito todo o processo de retirada".
    if (payload.action == "encerrar"
            and t.get("type") == "retirada"
            and payload.completion_data is not None):
        try:
            company_id = t.get("company_id") or DEMO_COMPANY_ID
            cd = dict(payload.completion_data or {})
            # Auto-resolve MAC/SN da ONT instalada no cliente quando o gestor
            # não informou. Lookup em stok_services -> client_id -> stok_onts.
            if not cd.get("ont") and not cd.get("ont_sn"):
                svc = await db.stok_services.find_one(
                    {"ticket_id": ticket_id, "company_id": company_id,
                     "status": "ativo"},
                    {"_id": 0, "client_id": 1},
                )
                if svc and svc.get("client_id"):
                    cur_ont = await db.stok_onts.find_one(
                        {"company_id": company_id,
                         "location_type": "cliente",
                         "location_id": svc["client_id"]},
                        {"_id": 0, "mac": 1, "scan_sn": 1},
                    )
                    if cur_ont:
                        if cur_ont.get("mac") and not str(
                                cur_ont["mac"]).startswith(("AUTOSN_", "SN-")):
                            cd["ont"] = cur_ont["mac"]
                        if cur_ont.get("scan_sn"):
                            cd["ont_sn"] = cur_ont["scan_sn"]
            # Marca o ator (gestor) para auditoria do withdraw
            cd.setdefault("closed_by_email", user.get("email"))
            # Só dispara o move se temos algum identificador
            if cd.get("ont") or cd.get("ont_sn"):
                from routes.stok import auto_close_service_from_ticket
                tech_id = t.get("assigned_collaborator_id")
                tech_name = t.get("collaborator_name") or "técnico"
                close_result = await auto_close_service_from_ticket(
                    ticket_id=ticket_id,
                    company_id=company_id,
                    completion_data=cd,
                    technician_id=tech_id,
                    technician_name=tech_name,
                )
                logger.info("[lousa] admin retirada auto-close: %s",
                            close_result)
                # Workflow de retirada: comprovante WhatsApp + remoção SmartOLT
                try:
                    from services.retirada_workflow import (
                        send_retirada_comprovante,
                        request_smartolt_remove,
                    )
                    full_t = await db.tickets.find_one(
                        {"id": ticket_id}, {"_id": 0})
                    # Best-effort sem BackgroundTasks (admin endpoint não tem o
                    # parâmetro; chamamos diretamente em fire-and-forget).
                    import asyncio as _aio
                    _aio.create_task(send_retirada_comprovante(
                        company_id=company_id,
                        ticket=full_t,
                        technician_name=tech_name,
                        ont_mac_sn=cd.get("ont") or cd.get("ont_sn"),
                    ))
                    _aio.create_task(request_smartolt_remove(
                        company_id=company_id,
                        ticket=full_t,
                        smartolt_onu=None,
                    ))
                except Exception as e:
                    logger.warning(
                        "[lousa] admin retirada workflow falhou: %s", e)
            else:
                logger.info(
                    "[lousa] admin retirada SEM MAC/SN — ONT não foi movida "
                    "(cliente provavelmente sem ONT registrada no estoque).")
        except Exception as e:
            logger.warning("[lousa] admin retirada auto-transfer falhou: %s", e)

    # iter196 — INSTALAÇÃO/TROCA fechada pelo gestor: baixa ONT do estoque
    # do técnico, vincula ao cliente, e marca a porta da CTO como ocupada.
    # Pedido do usuário 10/02/2026: "faça isso também em instalação, o gestor
    # também pode fechar uma OS de instalação, aparece a opção do estoque do
    # técnico a ser escolhido, ao ser escolhido o estoque dele é dado baixa
    # e transferido para o cliente, e se pergunta a porta e registra o
    # cliente, ONT, CTO e porta da CTO".
    if (payload.action == "encerrar"
            and t.get("type") in ("instalacao", "troca")
            and payload.completion_data is not None):
        try:
            company_id = t.get("company_id") or DEMO_COMPANY_ID
            cd = dict(payload.completion_data or {})
            cd.setdefault("closed_by_email", user.get("email"))
            tech_id = t.get("assigned_collaborator_id")
            tech_name = t.get("collaborator_name") or "técnico"
            # iter197 — SN prevalente: dispara o move se SN OU MAC informado.
            # auto_close_service_from_ticket repassa ambos via completion_data
            # e _move_ont_for_install busca primeiro por scan_sn.
            if cd.get("ont") or cd.get("ont_sn"):
                from routes.stok import auto_close_service_from_ticket
                close_result = await auto_close_service_from_ticket(
                    ticket_id=ticket_id,
                    company_id=company_id,
                    completion_data=cd,
                    technician_id=tech_id,
                    technician_name=tech_name,
                )
                logger.info("[lousa] admin instalacao auto-close: %s",
                            close_result)
            # Vincula porta da CTO ao cliente.
            # iter215aa — usa _smart_link_client_to_port (mesma regra de
            # exclusividade do fluxo público: porta ocupada por outro
            # cliente bloqueia; cliente em outra porta libera a antiga).
            cto_id = cd.get("cto_id")
            cto_port = cd.get("cto_port_number")
            if cto_id and cto_port:
                try:
                    cs = t.get("client_snapshot") or {}
                    await _smart_link_client_to_port(
                        company_id=company_id,
                        cto_id=cto_id,
                        port_number=int(cto_port),
                        client_id=cs.get("id"),
                        client_name=cs.get("name"),
                        client_pppoe=(cs.get("pppoe_user")
                                      or t.get("pppoe_user")),
                        actor_email=user.get("email"),
                        actor_id=user.get("id"),
                        actor_name=(user.get("name")
                                    or user.get("email")),
                        ticket_id=ticket_id,
                    )
                except HTTPException:
                    raise
                except Exception as e:
                    logger.warning(
                        "[lousa] vínculo CTO porta admin falhou: %s", e)
        except Exception as e:
            logger.warning(
                "[lousa] admin instalacao auto-transfer falhou: %s", e)

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
    try:
        from services.event_bus import emit_event
        await emit_event(
            "FIELD_OS_STARTED",
            company_id=t.get("company_id") or DEMO_COMPANY_ID,
            user_id=user.get("id"),
            source="lousa.admin_open",
            severity="media",
            payload={"ticket_id": ticket_id,
                     "assigned_collaborator_id": t.get("assigned_collaborator_id"),
                     "opened_by": "admin"},
        )
        # CTO 13/06/2026 — Evento canônico operacional "ticket.updated"
        await emit_event(
            "ticket.updated",
            company_id=t.get("company_id") or DEMO_COMPANY_ID,
            user_id=user.get("id"),
            source="lousa.admin_open",
            severity="media",
            payload={"ticket_id": ticket_id, "status": "aberta",
                     "transition": "pendente->aberta"},
        )
    except Exception:
        pass
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


# iter223 — Geofence radius configurável por empresa
class GeofenceSettingsIn(BaseModel):
    geofence_radius_m: int = Field(default=100, ge=20, le=5000)


@router.get("/lousa/geofence/settings")
async def get_geofence_settings(
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Lê o raio de geofence (em metros) usado pra bloquear finalização
    de OS fora do endereço do cliente. Default 100m."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.settings.find_one(
        {"id": cid}, {"_id": 0, "geofence_radius_m": 1,
                       "geofence_updated_at": 1,
                       "geofence_updated_by": 1}) or {}
    try:
        radius = int(doc.get("geofence_radius_m") or 100)
    except (TypeError, ValueError):
        radius = 100
    return {
        "geofence_radius_m": max(20, min(radius, 5000)),
        "updated_at": doc.get("geofence_updated_at"),
        "updated_by": doc.get("geofence_updated_by"),
        "min_m": 20, "max_m": 5000, "default_m": 100,
    }


@router.put("/lousa/geofence/settings")
async def put_geofence_settings(
    payload: GeofenceSettingsIn,
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Atualiza o raio de geofence. Aceita 20–5000m."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    await db.settings.update_one(
        {"id": cid},
        {"$set": {
            "id": cid,
            "geofence_radius_m": int(payload.geofence_radius_m),
            "geofence_updated_at": now_iso(),
            "geofence_updated_by": user.get("email") or user.get("id"),
        }},
        upsert=True,
    )
    return {"ok": True, "geofence_radius_m": payload.geofence_radius_m}


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
         "exclude_from_kpis": {"$ne": True},  # iter211bj
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


# ============================================================================
# iter176 — Métricas de qualidade do OCR
# ============================================================================
class OcrCorrectionIn(BaseModel):
    """Reporta uma correção manual do técnico após a leitura da IA."""
    ticket_id: Optional[str] = None
    collaborator_id: Optional[str] = None
    original_mac: Optional[str] = None   # detectado pela IA
    original_sn: Optional[str] = None    # detectado pela IA
    corrected_mac: Optional[str] = None  # valor após edição manual
    corrected_sn: Optional[str] = None
    ont_model: Optional[str] = None
    confidence: Optional[str] = None     # confiança reportada pela IA


@router.post("/lousa/public/ocr-correction")
async def public_ocr_correction(payload: OcrCorrectionIn):
    """Registra uma correção manual após o OCR. Endpoint público (chamado
    diretamente pelo LousaMobile que opera com `cid=` em vez de JWT).
    Best-effort: erros são silenciados pois é só métrica.
    """
    try:
        # Normaliza valores p/ comparação
        def _norm(s: Optional[str]) -> Optional[str]:
            if not s:
                return None
            return s.strip().upper().replace(":", "").replace("-", "")
        orig_mac_n = _norm(payload.original_mac)
        corr_mac_n = _norm(payload.corrected_mac)
        orig_sn_n = _norm(payload.original_sn)
        corr_sn_n = _norm(payload.corrected_sn)
        changed_mac = (orig_mac_n != corr_mac_n) and bool(corr_mac_n)
        changed_sn = (orig_sn_n != corr_sn_n) and bool(corr_sn_n)
        if not changed_mac and not changed_sn:
            return {"ok": True, "logged": False, "reason": "no_change"}

        # Tenta resolver company_id via collaborator/ticket
        cid = DEMO_COMPANY_ID
        if payload.collaborator_id:
            col = await db.collaborators.find_one(
                {"id": payload.collaborator_id}, {"_id": 0, "company_id": 1})
            if col:
                cid = col.get("company_id", cid)
        elif payload.ticket_id:
            tk = await db.tickets.find_one(
                {"id": payload.ticket_id}, {"_id": 0, "company_id": 1})
            if tk:
                cid = tk.get("company_id", cid)

        await db.stok_ocr_corrections.insert_one({
            "id": f"ocr-corr-{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "ticket_id": payload.ticket_id,
            "collaborator_id": payload.collaborator_id,
            "original_mac": payload.original_mac,
            "original_sn": payload.original_sn,
            "corrected_mac": payload.corrected_mac,
            "corrected_sn": payload.corrected_sn,
            "changed_mac": changed_mac,
            "changed_sn": changed_sn,
            "ont_model": (payload.ont_model or "").strip()[:120] or None,
            "confidence": payload.confidence,
            "created_at": now_iso(),
        })
        return {"ok": True, "logged": True,
                  "changed_mac": changed_mac, "changed_sn": changed_sn}
    except Exception as e:
        logger.warning("[ocr-correction] insert falhou: %s", e)
        return {"ok": False, "error": str(e)[:100]}


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
    from datetime import datetime
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
            try:
                from services.event_bus import emit_event
                await emit_event(
                    "ticket.updated",
                    company_id=(open_ticket or {}).get("company_id"),
                    source="lousa",
                    payload={},
                )
            except Exception:
                pass
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
        try:
            from services.event_bus import emit_event
            await emit_event(
                "ticket.updated",
                company_id=(open_ticket or {}).get("company_id"),
                source="lousa",
                payload={},
            )
        except Exception:
            pass
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


# ─────────────────────────────────────────────────────────────
# AUTO-DISTRIBUIÇÃO NA GRADE DE HORÁRIO (iter237)
# ─────────────────────────────────────────────────────────────

class AutoDistributeIn(BaseModel):
    collaborator_id: Optional[str] = None  # se None, processa todos do tenant
    slot_minutes: int = 60                   # 1 bolha por hora por padrão
    work_start_hour: int = 8                 # janela de trabalho do dia
    work_end_hour: int = 18
    allow_double_per_slot: bool = True       # último caso: 2 por slot


@router.post("/lousa/auto-distribute")
async def lousa_auto_distribute(payload: AutoDistributeIn,
                                  user: dict = Depends(get_current_user)):
    """Distribui bolhas PENDENTES sem horário travado em slots da grade,
    em ordem logística (nearest-neighbor a partir do GPS do técnico).

    Regras (definidas pelo Vando):
    1. Bolhas com priority ∈ {urgente, horario, prioridade} NÃO se movem
       — elas têm slot fixo respeitado pela alocação.
    2. Bolhas normais sem horário ou com horário "frouxo" são alocadas
       no próximo slot livre, escolhendo a mais PRÓXIMA do ponto atual
       (GPS do técnico ou bolha anterior já alocada).
    3. Se todos os slots estiverem ocupados, permite 2 por slot (último
       caso) escolhendo o slot cuja vizinha geográfica é mais próxima.
    4. Nunca deixa bolha sem horário na grade — todas vão pra algum slot.
    """
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    today = _today_br_iso()
    # Lista de colaboradores a processar
    coll_filter: dict = {"company_id": company_id}
    if payload.collaborator_id:
        coll_filter = {"id": payload.collaborator_id}
    colls = await db.collaborators.find(
        coll_filter,
        {"_id": 0, "id": 1, "name": 1, "last_position": 1},
    ).to_list(1000)
    summary = []
    for col in colls:
        moved = await _auto_distribute_one(col, today, payload)
        if moved:
            summary.append(moved)
    return {"ok": True, "today": today,
            "collaborators_processed": len(summary), "details": summary}


async def _auto_distribute_one(col: dict, today: str,
                                 payload: "AutoDistributeIn") -> Optional[dict]:
    """Aloca bolhas flexíveis na grade de horário do colaborador."""
    cid = col["id"]
    # 1) Lista todas as bolhas pendentes do tech no dia
    cur = db.tickets.find(
        {
            "assigned_collaborator_id": cid,
            "status": {"$in": ["pendente", "aguardando_atendimento"]},
        },
        {"_id": 0, "id": 1, "priority": 1, "scheduled_time": 1,
          "client_snapshot": 1, "service_date": 1, "opened_at": 1,
          "created_at": 1, "position": 1},
    )
    tickets = []
    async for t in cur:
        if _ticket_day_iso(t) != today:
            continue
        tickets.append(t)
    if not tickets:
        return None

    # 2) Separa fixas vs flexíveis
    FIXED_PRIORITIES = {"urgente", "horario", "prioridade"}
    fixed = [t for t in tickets if t.get("priority") in FIXED_PRIORITIES
              and t.get("scheduled_time")]
    flex = [t for t in tickets if t not in fixed]
    if not flex:
        return {"collaborator_id": cid, "name": col.get("name"),
                "moved": 0, "reason": "Todas as bolhas têm horário fixo."}

    # 3) Gera slots da janela de trabalho
    slot_min = max(15, int(payload.slot_minutes))
    slots = []
    h = int(payload.work_start_hour)
    m = 0
    while h < int(payload.work_end_hour):
        slots.append(f"{h:02d}:{m:02d}")
        m += slot_min
        if m >= 60:
            h += m // 60
            m = m % 60
    if not slots:
        return None

    # 4) Marca slots ocupados pelas fixas
    occupied = {}  # slot -> [ticket_id]
    for t in fixed:
        st = (t.get("scheduled_time") or "")[:5]
        if st in slots:
            occupied.setdefault(st, []).append(t["id"])

    # 5) Ponto de partida: GPS atual do tech (last_position do collaborator)
    last = col.get("last_position") or {}
    cur_lat = last.get("lat")
    cur_lng = last.get("lng")
    # Se não tem GPS, parte da 1ª bolha fixa (se houver)
    if not (isinstance(cur_lat, (int, float))
            and isinstance(cur_lng, (int, float))) and fixed:
        snap = fixed[0].get("client_snapshot") or {}
        if isinstance(snap.get("latitude"), (int, float)):
            cur_lat = float(snap["latitude"])
            cur_lng = float(snap["longitude"])

    # 6) Itera flex em ordem de proximidade (nearest-neighbor)
    flex_with_geo = []
    flex_without_geo = []
    for t in flex:
        snap = t.get("client_snapshot") or {}
        lat = snap.get("latitude")
        lng = snap.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            t["_lat"] = float(lat)
            t["_lng"] = float(lng)
            flex_with_geo.append(t)
        else:
            flex_without_geo.append(t)

    def _next_nearest(lat, lng, pool):
        if lat is None or not pool:
            return pool[0] if pool else None
        return min(pool, key=lambda x: _haversine_km(
            lat, lng, x["_lat"], x["_lng"]))

    # Slots ainda livres
    free_slots = [s for s in slots if s not in occupied]
    moved = []
    pool = flex_with_geo[:]

    for slot in free_slots:
        if not pool and not flex_without_geo:
            break
        if pool:
            nxt = _next_nearest(cur_lat, cur_lng, pool)
            cur_lat, cur_lng = nxt["_lat"], nxt["_lng"]
            pool.remove(nxt)
        else:
            nxt = flex_without_geo.pop(0)
        await db.tickets.update_one(
            {"id": nxt["id"]},
            {"$set": {"scheduled_time": slot,
                       "auto_distributed_at": now_iso()}},
        )
        occupied.setdefault(slot, []).append(nxt["id"])
        moved.append({"ticket_id": nxt["id"], "slot": slot})

    # 7) Se sobrou bolha sem slot → permite 2 por slot
    remaining = pool + flex_without_geo
    if remaining and payload.allow_double_per_slot:
        for r in remaining:
            # escolhe slot com menos bolhas E geograficamente mais perto
            best_slot = min(slots, key=lambda s: (
                len(occupied.get(s, [])),
                _slot_proximity_cost(s, r, occupied, tickets),
            ))
            await db.tickets.update_one(
                {"id": r["id"]},
                {"$set": {"scheduled_time": best_slot,
                           "auto_distributed_at": now_iso(),
                           "auto_distributed_overflow": True}},
            )
            occupied.setdefault(best_slot, []).append(r["id"])
            moved.append({"ticket_id": r["id"], "slot": best_slot,
                            "overflow": True})

    return {"collaborator_id": cid, "name": col.get("name"),
            "moved": len(moved), "slots": moved}


def _slot_proximity_cost(slot: str, candidate: dict,
                            occupied: dict, all_tickets: list) -> float:
    """Custo geográfico de colocar `candidate` no `slot` — distância média
    ao ticket já alocado naquele slot."""
    if "_lat" not in candidate:
        return 999999.0
    ids_in_slot = occupied.get(slot, [])
    if not ids_in_slot:
        return 0.0
    by_id = {t["id"]: t for t in all_tickets}
    dists = []
    for tid in ids_in_slot:
        t = by_id.get(tid)
        if not t:
            continue
        snap = t.get("client_snapshot") or {}
        if isinstance(snap.get("latitude"), (int, float)):
            dists.append(_haversine_km(
                candidate["_lat"], candidate["_lng"],
                float(snap["latitude"]), float(snap["longitude"])))
    return min(dists) if dists else 50.0




# Toggles globais dos cards (ativar/desativar exibição no app do técnico)
DASHBOARD_CONFIG_DEFAULTS = {
    "show_performance": True,
    "show_achievements": True,
    "show_smart_route": True,
    "show_points": True,
    "enable_geofence_alerts": True,
    # CTO 12/06/2026 — card "Meu dia em campo" (métricas+GPS+atalhos
    # Isabella/Estoque/Frota) controlado globalmente. Default DESLIGADO
    # por decisão de produto.
    "show_meu_dia_em_campo": False,
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

    # ── Frota: score IA das vistorias semanais aprovadas (mesma janela) ────
    # Agrega por colaborador a média de ai_score e conta vistorias 90+
    if coll_ids:
        fleet_docs = await db.fleet_inspections.find({
            "collaborator_id": {"$in": coll_ids},
            "status": "approved",
            "ai_score": {"$ne": None},
            "ai_reviewed_at": {"$gte": cutoff},
        }, {"_id": 0, "collaborator_id": 1, "ai_score": 1}).to_list(2000)
        fleet_by_coll: Dict[str, Dict[str, Any]] = {}
        for f in fleet_docs:
            cid = f["collaborator_id"]
            sc = float(f.get("ai_score") or 0)
            fb = fleet_by_coll.setdefault(cid,
                {"scores": [], "count_90plus": 0})
            fb["scores"].append(sc)
            if sc >= 90:
                fb["count_90plus"] += 1
        # Attach fleet data nos items
        for it in items:
            fb = fleet_by_coll.get(it["collaborator_id"])
            if fb and fb["scores"]:
                it["fleet_score"] = round(sum(fb["scores"]) / len(fb["scores"]), 1)
                it["fleet_inspections_count"] = len(fb["scores"])
                it["fleet_count_90plus"] = fb["count_90plus"]
            else:
                it["fleet_score"] = None
                it["fleet_inspections_count"] = 0
                it["fleet_count_90plus"] = 0
        # Motorista do mês: maior fleet_score entre os que têm pelo menos 1
        # vistoria 90+ e ≥2 vistorias aprovadas no período
        eligible = [it for it in items
                     if (it.get("fleet_score") is not None
                          and it.get("fleet_inspections_count", 0) >= 2
                          and it.get("fleet_count_90plus", 0) >= 1)]
        if eligible:
            best = max(eligible, key=lambda x: (x["fleet_score"],
                                                  x["fleet_count_90plus"]))
            best["is_motorista_mes"] = True

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
            "closed_by_name": user.get("name") or user.get("email"),
            "closed_by_email": user.get("email"),
            "closed_by_role": user.get("role"),
            "admin_action": payload.action,
            "admin_notes": payload.notes,
        }
        if payload.action == "reagendar" and sched:
            update["scheduled_time"] = sched
            update["grid_slot"] = None
        await db.tickets.update_one({"id": tid}, {"$set": update})
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
        "rompimento": int(settings.get("sla_rompimento_minutes", 180)),
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




# ---------------------------------------------------------------------------
# Teste IPv6 obrigatório na finalização de OS
# ---------------------------------------------------------------------------
class TicketIpv6TestIn(BaseModel):
    score: int = Field(..., ge=0, le=10)
    ipv4_reachable: bool = False
    ipv6_reachable: bool = False
    dual_stack_ok: bool = False
    mtu_ok: bool = False
    dns_ipv6_ok: bool = False
    v4_addr: Optional[str] = None
    v6_addr: Optional[str] = None
    isp: Optional[str] = None
    latency_v4_ms: Optional[float] = None
    latency_v6_ms: Optional[float] = None
    raw_results: Optional[Dict[str, Any]] = None


@router.post("/lousa/tickets/{ticket_id}/ipv6-test")
async def save_ticket_ipv6_test(ticket_id: str, payload: TicketIpv6TestIn,
                                       user: dict = Depends(get_current_user)):
    """Persiste o resultado do Teste IPv6 no ticket (completion_data.ipv6_test).

    Chamado pelo app do colaborador na finalização. Marca
    `ipv6_inconsistente=True` se score < 8 (regra acordada).
    """
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0, "id": 1,
                                                          "completion_data": 1,
                                                          "company_id": 1})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    inconsistent = payload.score < 8
    ipv6_test_doc = {
        "score": payload.score,
        "max_score": 10,
        "ipv4_reachable": payload.ipv4_reachable,
        "ipv6_reachable": payload.ipv6_reachable,
        "dual_stack_ok": payload.dual_stack_ok,
        "mtu_ok": payload.mtu_ok,
        "dns_ipv6_ok": payload.dns_ipv6_ok,
        "v4_addr": payload.v4_addr,
        "v6_addr": payload.v6_addr,
        "isp": payload.isp,
        "latency_v4_ms": payload.latency_v4_ms,
        "latency_v6_ms": payload.latency_v6_ms,
        "ipv6_inconsistente": inconsistent,
        "tested_at": now_iso(),
        "tested_by_id": user.get("id"),
        "tested_by_name": user.get("name") or user.get("email"),
        "raw_results": payload.raw_results or {},
    }
    cd = t.get("completion_data") or {}
    cd["ipv6_test"] = ipv6_test_doc
    if inconsistent:
        cd["ipv6_inconsistente"] = True
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {"completion_data": cd, "updated_at": now_iso()}},
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
    return {"ok": True, "ipv6_inconsistente": inconsistent,
             "ipv6_test": ipv6_test_doc}


class TicketPingAutoIn(BaseModel):
    host: str
    port: int = 80
    packets: int = 10
    success: int = 0
    loss_pct: float = 0
    avg_ms: Optional[float] = None
    raw_results: Optional[List[Dict[str, Any]]] = None


@router.post("/lousa/tickets/{ticket_id}/ping-auto")
async def save_ticket_ping_auto(ticket_id: str, payload: TicketPingAutoIn,
                                       user: dict = Depends(get_current_user)):
    """Persiste resultado do ping automático (10 pacotes para 8.8.8.8:80)
    em `completion_data.ping_auto`."""
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0, "id": 1,
                                                          "completion_data": 1})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    ping_doc = {
        "host": payload.host,
        "port": payload.port,
        "packets": payload.packets,
        "success": payload.success,
        "loss_pct": payload.loss_pct,
        "avg_ms": payload.avg_ms,
        "tested_at": now_iso(),
        "tested_by_id": user.get("id"),
        "tested_by_name": user.get("name") or user.get("email"),
        "raw_results": (payload.raw_results or [])[:30],
    }
    cd = t.get("completion_data") or {}
    cd["ping_auto"] = ping_doc
    if payload.loss_pct > 30:
        cd["ping_inconsistente"] = True
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {"completion_data": cd, "updated_at": now_iso()}},
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
    return {"ok": True, "ping_auto": ping_doc,
             "ping_inconsistente": payload.loss_pct > 30}


# =============================================================================
# ONU Bridge — botão "Abrir ONT" no app do colaborador (iter232)
# =============================================================================
# Substitui o acesso direto ao painel SmartOLT. Técnico só consegue abrir a ONT
# do cliente enquanto a OS dele estiver aberta. Backend gera link único
# (token UUID, TTL 30min, revogado no fechamento da OS) que faz 302 redirect
# para `https://{subdomain}.smartolt.com/onu/view/{external_id}`.
#
# Política: técnico NUNCA vê a URL final da SmartOLT — só recebe o link
# `/api/lousa/onu-bridge/redirect/{token}` que ele abre no navegador.

_ONU_BRIDGE_TTL_MIN = 30


@router.post("/lousa/tickets/{ticket_id}/onu-bridge")
async def issue_onu_bridge_token(ticket_id: str,
                                       user: dict = Depends(get_current_user)):
    """Gera um link único pro técnico abrir a ONT do cliente desta OS.

    Regras de aceite:
      • OS deve existir, estar atribuída ao colaborador chamador e estar ABERTA
        (status diferente de closed/concluida/finalizado).
      • O subscriber da OS precisa ter ONU vinculada (smartolt_onu_sn ou
        smartolt_onu_external_id direto na ONU registrada).
    """
    cid = user.get("company_id")
    if not cid:
        raise HTTPException(403, "company_id ausente")
    tk = await db.tickets.find_one(
        {"id": ticket_id, "company_id": cid}, {"_id": 0})
    if not tk:
        raise HTTPException(404, "OS não encontrada")
    if (tk.get("status") or "").lower() in ("closed", "resolved",
                                                 "concluida", "finalizado"):
        raise HTTPException(409, "OS já está fechada — acesso à ONT bloqueado")

    # Só o técnico assignado pode emitir (ou gestor)
    user_id = user.get("id") or user.get("user_id")
    role = (user.get("role") or "").lower()
    assigned = tk.get("assigned_to") or tk.get("collaborator_id")
    if role not in ("gestor", "admin", "owner") and assigned and assigned != user_id:
        raise HTTPException(403, "OS atribuída a outro técnico")

    # Resolve ONU external_id via subscriber
    sub_id = tk.get("subscriber_id") or tk.get("client_id")
    if not sub_id:
        raise HTTPException(412, "OS sem subscriber vinculado")
    sub = await db.subscribers.find_one(
        {"$or": [{"id": sub_id}, {"_id": sub_id}],
         "company_id": cid},
        {"_id": 0, "smartolt_onu_sn": 1, "smartolt_onu_external_id": 1,
         "name": 1}) or {}
    onu_external_id = sub.get("smartolt_onu_external_id")
    onu_sn = sub.get("smartolt_onu_sn")
    onu_doc = None
    if onu_sn and not onu_external_id:
        onu_doc = await db.smartolt_onus.find_one(
            {"company_id": cid, "sn": onu_sn},
            {"_id": 0, "unique_external_id": 1, "sn": 1})
        if onu_doc:
            onu_external_id = onu_doc.get("unique_external_id")
    if not onu_external_id:
        raise HTTPException(412, "ONU não vinculada a este cliente no SmartOLT")

    # SmartOLT subdomain
    cfg = await db.smartolt_config.find_one(
        {"company_id": cid}, {"_id": 0, "subdomain": 1}) or {}
    subdomain = (cfg.get("subdomain") or "").strip().lower()
    if not subdomain:
        raise HTTPException(412, "SmartOLT não configurado pra esta empresa")

    # Gera token único — UUID v4 + persistência. TTL 30min.
    token = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(minutes=_ONU_BRIDGE_TTL_MIN)).isoformat()
    target_url = f"https://{subdomain}.smartolt.com/onu/view/{onu_external_id}"
    await db.onu_bridge_tokens.insert_one({
        "token": token,
        "company_id": cid,
        "ticket_id": ticket_id,
        "subscriber_id": sub_id,
        "onu_external_id": onu_external_id,
        "target_url": target_url,
        "issued_to_user_id": user_id,
        "issued_to_user_name": user.get("name") or user.get("email"),
        "issued_at": now.isoformat(),
        "expires_at": expires_at,
        "used_at": None,
        "revoked": False,
        "revoke_reason": None,
    })

    # Auditoria
    await db.audit_log.insert_one({
        "id": f"audit-{uuid.uuid4().hex[:12]}",
        "company_id": cid, "kind": "ONU_BRIDGE_ISSUED",
        "ticket_id": ticket_id, "subscriber_id": sub_id,
        "user_id": user_id, "onu_external_id": onu_external_id,
        "created_at": now.isoformat(),
    })

    # URL pública (relativa ao backend público)
    redirect_path = f"/api/lousa/onu-bridge/redirect/{token}"
    return {
        "ok": True,
        "token": token,
        "redirect_path": redirect_path,
        "expires_at": expires_at,
        "expires_in_minutes": _ONU_BRIDGE_TTL_MIN,
        "subscriber_name": sub.get("name"),
        "onu_sn": onu_sn,
    }


@router.get("/lousa/onu-bridge/redirect/{token}")
async def redirect_onu_bridge(token: str):
    """Endpoint público (sem auth — o token É a auth). Faz 302 redirect pra
    URL real da SmartOLT depois de validar token + OS aberta + não revogado."""
    from fastapi.responses import HTMLResponse, RedirectResponse

    def _deny(msg: str, code: int = 403) -> HTMLResponse:
        html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Acesso negado</title><meta name="viewport" content="width=device-width">
<style>body{{font-family:system-ui;background:#0f172a;color:#e2e8f0;
text-align:center;padding:40px 20px}}.box{{background:#1e293b;border-radius:12px;
padding:32px;max-width:380px;margin:auto;border:2px solid #ef4444}}
h1{{color:#ef4444;margin:0 0 12px;font-size:18px}}
p{{color:#cbd5e1;font-size:14px;line-height:1.5}}</style></head><body>
<div class="box"><h1>🔒 Acesso à ONT bloqueado</h1>
<p>{msg}</p>
<p style="margin-top:16px;font-size:12px;color:#64748b">
Volte ao app e abra um novo link a partir da OS aberta.</p></div></body></html>"""
        return HTMLResponse(html, status_code=code)

    rec = await db.onu_bridge_tokens.find_one({"token": token})
    if not rec:
        return _deny("Link inválido ou expirado.", 404)
    if rec.get("revoked"):
        reason = rec.get("revoke_reason") or "OS encerrada"
        return _deny(f"Link revogado: {reason}", 410)
    try:
        exp = datetime.fromisoformat(rec["expires_at"])
    except Exception:
        exp = datetime.now(timezone.utc) - timedelta(seconds=1)
    if datetime.now(timezone.utc) > exp:
        return _deny("Link expirou (validade 30min). Gere um novo no app.", 410)

    # Re-valida OS aberta no momento do clique
    tk = await db.tickets.find_one(
        {"id": rec["ticket_id"], "company_id": rec["company_id"]},
        {"_id": 0, "status": 1}) or {}
    if (tk.get("status") or "").lower() in ("closed", "resolved",
                                                 "concluida", "finalizado"):
        await db.onu_bridge_tokens.update_one(
            {"token": token},
            {"$set": {"revoked": True, "revoke_reason": "OS fechada",
                       "revoked_at": now_iso()}})
        return _deny("A OS foi fechada — acesso revogado.", 410)

    # Marca uso + audit + 302
    await db.onu_bridge_tokens.update_one(
        {"token": token}, {"$set": {"used_at": now_iso()}})
    await db.audit_log.insert_one({
        "id": f"audit-{uuid.uuid4().hex[:12]}",
        "company_id": rec["company_id"], "kind": "ONU_BRIDGE_REDIRECT",
        "ticket_id": rec["ticket_id"], "user_id": rec.get("issued_to_user_id"),
        "onu_external_id": rec["onu_external_id"],
        "created_at": now_iso(),
    })
    return RedirectResponse(url=rec["target_url"], status_code=302)


async def _revoke_onu_bridge_tokens_for_ticket(ticket_id: str,
                                                    reason: str) -> int:
    """Revoga todos os tokens da OS quando ela é fechada/cancelada.
    Retorna a quantidade afetada."""
    try:
        res = await db.onu_bridge_tokens.update_many(
            {"ticket_id": ticket_id, "revoked": False},
            {"$set": {"revoked": True, "revoke_reason": reason,
                       "revoked_at": now_iso()}})
        return res.modified_count
    except Exception as e:
        logger.warning("[onu_bridge] revoke falhou ticket=%s: %s", ticket_id, e)
        return 0

