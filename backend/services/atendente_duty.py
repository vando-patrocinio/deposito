"""iter215an — Regra global de atendimento por ponto.

Colaboradores internos com acesso ao Atendimento IA (gestor / administrador /
vendedor) só conseguem operar o chat se estiverem com PONTO BATIDO no estado
correto:

  • Após "Entrada" ou "Fim intervalo" → ON DUTY (chat liberado)
  • Após "Início intervalo" ou "Saída"      → OFF DUTY (chat bloqueado)
  • Sem nenhum registro hoje              → OFF DUTY (chat bloqueado)

Ao bater "Início intervalo" ou "Saída", as conversas atribuídas ao
colaborador são transferidas automaticamente para outro humano online
(o de MENOR CARGA). Se ninguém estiver disponível, o ponto é BLOQUEADO
com mensagem clara.
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
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from database import db

logger = logging.getLogger("atendente_duty")

# Cargos/roles que devem seguir essa regra (apenas user-side; o cargo do
# colaborador é checado via flag `can_attend_whatsapp` no `users`/`collaborators`).
ROLES_AFETADOS = {"gestor", "administrador", "vendedor"}

# Eventos do clock_records (existentes em routes/clock.py)
EV_ENTRADA = "Entrada"
EV_INICIO_INT = "Início intervalo"
EV_FIM_INT = "Fim intervalo"
EV_SAIDA = "Saída"
EV_OFFDUTY = {EV_INICIO_INT, EV_SAIDA}
EV_ONDUTY = {EV_ENTRADA, EV_FIM_INT}


def _today_brt_str() -> str:
    """Data de hoje em America/Sao_Paulo (UTC-3)."""
    from datetime import timedelta
    now = datetime.now(timezone.utc) - timedelta(hours=3)
    return now.strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _last_clock_event(collaborator_id: str) -> Optional[Dict[str, Any]]:
    """Último registro VÁLIDO de hoje (ignora Recusado/Bloqueado)."""
    today = _today_brt_str()
    cursor = db.clock_records.find(
        {"collaborator_id": collaborator_id, "date": today,
         "status": {"$nin": ["Recusado", "Bloqueado"]}},
        {"_id": 0, "type": 1, "time": 1, "status": 1, "date": 1},
    ).sort("time", -1).limit(1)
    docs = await cursor.to_list(1)
    return docs[0] if docs else None


async def _collaborator_for_user(company_id: str,
                                   user_id: Optional[str],
                                   email: Optional[str]
                                   ) -> Optional[Dict[str, Any]]:
    """Encontra o colaborador vinculado a um user (por email)."""
    query: Dict[str, Any] = {"company_id": company_id}
    if email:
        query["email"] = email
    elif user_id:
        query["user_id"] = user_id
    else:
        return None
    return await db.collaborators.find_one(
        query, {"_id": 0, "id": 1, "name": 1, "cargo": 1, "email": 1,
                "user_id": 1, "can_attend_whatsapp": 1})


async def my_workload_snapshot(company_id: str, user: Dict[str, Any]
                                  ) -> Dict[str, Any]:
    """iter215ao — KPI live pro header do chat: total de conversas
    humanas abertas pra mim e segundos desde o ÚLTIMO evento de Entrada
    (ou Fim intervalo) do dia."""
    uid = (user or {}).get("id")
    open_count = 0
    if uid:
        open_count = await db.wa_conversations.count_documents({
            "company_id": company_id,
            "assignee_user_id": uid,
            "assignee_role": "human",
            "status": {"$ne": "closed"},
        })
    seconds_since_entrada: Optional[int] = None
    last_onduty_event: Optional[str] = None
    coll = await _collaborator_for_user(
        company_id, user.get("id"), user.get("email")) if user else None
    if coll:
        today = _today_brt_str()
        # Pega o ÚLTIMO evento on-duty de hoje (Entrada ou Fim intervalo)
        cur = db.clock_records.find(
            {"collaborator_id": coll["id"], "date": today,
             "type": {"$in": list(EV_ONDUTY)},
             "status": {"$nin": ["Recusado", "Bloqueado"]}},
            {"_id": 0, "type": 1, "time": 1, "created_at": 1},
        ).sort("time", -1).limit(1)
        docs = await cur.to_list(1)
        if docs:
            last_onduty_event = docs[0]["type"]
            # Calcula segundos via "created_at" se houver, senão via "time"
            ca = docs[0].get("created_at")
            if ca:
                try:
                    dt = datetime.fromisoformat(ca.replace("Z", "+00:00"))
                    delta = datetime.now(timezone.utc) - dt
                    seconds_since_entrada = max(0, int(delta.total_seconds()))
                except Exception:
                    seconds_since_entrada = None
    return {
        "my_open_conversations": open_count,
        "seconds_since_last_onduty": seconds_since_entrada,
        "last_onduty_event": last_onduty_event,
    }


async def is_user_on_duty(company_id: str, user: Dict[str, Any]
                            ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Retorna (on_duty, reason, last_event). Reason é mensagem amigável."""
    role = (user or {}).get("role") or ""
    if role not in ROLES_AFETADOS:
        # Outros roles (auditor, colaborador externo, etc.) — não
        # bloqueamos por ponto aqui (auditor é read-only por definição).
        return True, "role_not_affected", None
    coll = await _collaborator_for_user(
        company_id, user.get("id"), user.get("email"))
    if not coll:
        # Usuário não tem colaborador vinculado → sem ponto não acessa.
        return False, ("Seu usuário não está vinculado a um colaborador "
                        "com batimento de ponto. Procure o gestor."), None
    last = await _last_clock_event(coll["id"])
    if not last:
        return False, ("Você ainda não bateu o ponto de Entrada hoje. "
                        "Bata o ponto pra liberar o atendimento."), None
    if last["type"] in EV_ONDUTY:
        return True, "on_duty", last
    if last["type"] == EV_INICIO_INT:
        return False, ("Você está em intervalo (almoço). Bata o ponto de "
                        "Fim intervalo pra voltar a atender."), last
    if last["type"] == EV_SAIDA:
        return False, ("Seu expediente terminou hoje. Bata Entrada amanhã "
                        "ou peça pro gestor reabrir."), last
    return False, "off_duty", last


async def list_online_attendants(company_id: str,
                                    exclude_user_id: Optional[str] = None
                                    ) -> List[Dict[str, Any]]:
    """Lista usuários (id, name, role) atualmente ON DUTY para receber
    conversas. Critério: último ponto VÁLIDO de hoje é Entrada ou Fim
    intervalo (regra 3a definida pelo usuário)."""
    users = await db.users.find(
        {"company_id": company_id,
         "active": {"$ne": False},
         "role": {"$in": list(ROLES_AFETADOS)},
         "is_ai_agent": {"$ne": True}},
        {"_id": 0, "id": 1, "name": 1, "role": 1, "email": 1},
    ).to_list(500)
    online: List[Dict[str, Any]] = []
    for u in users:
        if exclude_user_id and u["id"] == exclude_user_id:
            continue
        coll = await _collaborator_for_user(
            company_id, u.get("id"), u.get("email"))
        if not coll:
            continue
        last = await _last_clock_event(coll["id"])
        if not last:
            continue
        if last["type"] in EV_ONDUTY:
            online.append({**u, "collaborator_id": coll["id"]})
    return online


async def pick_least_loaded(company_id: str,
                              candidates: List[Dict[str, Any]]
                              ) -> Optional[Dict[str, Any]]:
    """Retorna o candidato com menos conversas humanas abertas (load
    balancing). Empate → ordem alfabética."""
    if not candidates:
        return None
    counts: List[Tuple[int, str, Dict[str, Any]]] = []
    for c in candidates:
        n = await db.wa_conversations.count_documents({
            "company_id": company_id,
            "assignee_user_id": c["id"],
            "assignee_role": "human",
            "status": {"$ne": "closed"},
        })
        counts.append((n, (c.get("name") or "").lower(), c))
    counts.sort(key=lambda t: (t[0], t[1]))
    return counts[0][2]


async def transfer_conversations(company_id: str,
                                    from_user_id: str,
                                    to_user: Dict[str, Any],
                                    reason: str,
                                    actor_email: Optional[str] = None
                                    ) -> int:
    """Transfere TODAS as conversas humanas abertas do `from_user_id` para
    `to_user`. Retorna a quantidade transferida e loga handoff em
    `aihub_wa_messages` (mensagem interna, não enviada ao cliente)."""
    convs = await db.wa_conversations.find(
        {"company_id": company_id,
         "assignee_user_id": from_user_id,
         "assignee_role": "human",
         "status": {"$ne": "closed"}},
        {"_id": 0, "phone": 1},
    ).to_list(1000)
    if not convs:
        return 0
    now = _now_iso()
    await db.wa_conversations.update_many(
        {"company_id": company_id,
         "assignee_user_id": from_user_id,
         "assignee_role": "human",
         "status": {"$ne": "closed"}},
        {"$set": {
            "assignee_user_id": to_user["id"],
            "assignee_user_name": to_user.get("name"),
            "assignee_assigned_at": now,
            "assignee_reassigned_reason": reason,
            "updated_at": now,
        }},
    )
    # Marcador no histórico (não vai pro cliente — apenas dashboard).
    try:
        for cv in convs:
            await db.aihub_wa_messages.insert_one({
                "id": f"wam-{uuid.uuid4().hex[:10]}",
                "company_id": company_id,
                "direction": "internal",
                "phone": cv["phone"],
                "text": (f"[SISTEMA] Conversa reatribuída automaticamente "
                          f"para {to_user.get('name') or to_user['id']}. "
                          f"Motivo: {reason}."),
                "created_at": now,
                "actor_user": actor_email or "system",
                "is_handover_message": True,
                "is_internal": True,
                "auto_reply": False,
            })
    except Exception as e:
        logger.warning("[duty] log handover msg falhou: %s", e)
    logger.info(
        "[duty] transferidas %d conversas de user=%s para %s (motivo=%s)",
        len(convs), from_user_id, to_user.get("id"), reason)
    return len(convs)


async def enforce_offduty_clock_event(company_id: str,
                                        collaborator: Dict[str, Any],
                                        event_type: str
                                        ) -> Tuple[bool, str,
                                                    Optional[Dict[str, Any]],
                                                    int]:
    """Chamado pelo clock.create_clock_record ANTES de gravar.

    Se o colaborador tem usuário vinculado com role afetada e está batendo
    "Início intervalo" ou "Saída", precisamos:
      1. Localizar outro humano online.
      2. Se NÃO houver → bloquear (retorna allowed=False com mensagem).
      3. Se houver → transferir todas as conversas pro de menor carga e
         permitir o ponto.

    Retorna (allowed, reason, to_user, transferred_count).
    Para eventos ON DUTY (Entrada/Fim intervalo) sempre permite.
    """
    if event_type not in EV_OFFDUTY:
        return True, "ok", None, 0
    # Encontra o user vinculado a este colaborador (por email).
    user = await db.users.find_one(
        {"company_id": company_id,
         "email": collaborator.get("email"),
         "active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1, "role": 1, "email": 1},
    )
    if not user or user.get("role") not in ROLES_AFETADOS:
        # Colaborador externo (técnico, etc.) — não aplica essa regra.
        return True, "not_affected", None, 0
    # Quantas conversas humanas abertas ele tem?
    n_open = await db.wa_conversations.count_documents({
        "company_id": company_id,
        "assignee_user_id": user["id"],
        "assignee_role": "human",
        "status": {"$ne": "closed"},
    })
    if n_open == 0:
        return True, "no_active_conversations", None, 0
    # Procura outros online.
    online = await list_online_attendants(
        company_id, exclude_user_id=user["id"])
    if not online:
        return False, (
            f"Ponto BLOQUEADO: você tem {n_open} atendimento(s) "
            f"aberto(s) e NENHUM outro atendente online pra receber. "
            f"Peça pra um colega bater Entrada/Fim intervalo antes."
        ), None, 0
    target = await pick_least_loaded(company_id, online)
    if not target:
        return False, ("Sem destinatário válido pras conversas. "
                        "Peça pra um colega bater Entrada/Fim intervalo."
                        ), None, 0
    moved = await transfer_conversations(
        company_id=company_id,
        from_user_id=user["id"],
        to_user=target,
        reason=("colaborador entrou em INTERVALO" if event_type == EV_INICIO_INT
                else "colaborador encerrou EXPEDIENTE"),
        actor_email=user.get("email"),
    )
    return True, (
        f"{moved} conversa(s) transferida(s) para "
        f"{target.get('name') or target['id']}."
    ), target, moved
