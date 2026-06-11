"""OPERAÇÃO RELACIONAMENTO 360° — Follow-up automático e Reabertura.

  F4. schedule_followup           — agenda mensagem de follow-up baseada no outcome
  F4b. run_due_followups          — executa follow-ups vencidos (worker cron)
  F8.  detect_and_reopen_case     — reabre OS quando subscriber volta com problema
                                     do mesmo tipo em <30 dias

Coleções usadas:
  • isabella_followups       — fila de follow-ups agendados
  • tickets                  — OS (já existente)
  • aihub_wa_messages        — pra disparar a mensagem
  • executive_ledger         — registra ganho (reopened = problema resolvido sem custo extra)
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["wa.message.persisted"],
    "company_id_required": True,
}

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db

logger = logging.getLogger("ponto.isabella_followup")


# ===================== F4. FOLLOW-UP AUTOMÁTICO =====================

FOLLOWUP_RULES: List[Dict[str, Any]] = [
    # outcome -> {delay_hours, template_key}
    {
        "trigger": "agendou",
        "delay_hours": 24,
        "template": ("Oi! Aqui é a Isabella da Ligo. Sua visita ainda tá "
                      "marcada pro horário combinado? Qualquer ajuste me "
                      "chama por aqui."),
    },
    {
        "trigger": "problema_tecnico",
        "delay_hours": 4,
        "template": ("Oi! Voltando ao seu chamado de pouco tempo atrás — "
                      "tá tudo funcionando agora? Me confirma só pra eu "
                      "fechar com a equipe."),
    },
    {
        "trigger": "cobrou",
        "delay_hours": 48,
        "template": ("Oi! Consegui ajudar com a fatura? Se ainda não rolou "
                      "o pagamento, posso te enviar a 2ª via outra vez."),
    },
    {
        "trigger": "ofertou",
        "delay_hours": 72,
        "template": ("Oi! Pensou sobre aquela proposta que te mandei? "
                      "Qualquer dúvida tô aqui."),
    },
    {
        "trigger": "resolveu",
        "delay_hours": 168,  # 7 dias
        "template": ("Oi! Tô passando aqui pra ver se tudo continua "
                      "tranquilo depois daquela conversa. Conta como tá."),
    },
]


async def schedule_followup(*, company_id: str, phone: str,
                                 subscriber_id: Optional[str],
                                 outcomes: Dict[str, bool],
                                 last_reply_id: Optional[str] = None) -> int:
    """Agenda follow-ups baseado nos outcomes detectados.

    Retorna o número de follow-ups agendados.
    """
    if not outcomes:
        return 0
    scheduled = 0
    now = datetime.now(timezone.utc)
    for rule in FOLLOWUP_RULES:
        if not outcomes.get(rule["trigger"]):
            continue
        # Já existe followup pendente do mesmo tipo nesta janela?
        existing = await db.isabella_followups.find_one({
            "company_id": company_id, "phone": phone,
            "trigger": rule["trigger"], "status": "scheduled",
        })
        if existing:
            continue
        due_at = (now + timedelta(hours=rule["delay_hours"])).isoformat()
        try:
            await db.isabella_followups.insert_one({
                "id": f"fup-{uuid.uuid4().hex[:10]}",
                "company_id": company_id,
                "phone": phone,
                "subscriber_id": subscriber_id,
                "trigger": rule["trigger"],
                "template": rule["template"],
                "due_at": due_at,
                "status": "scheduled",
                "last_reply_id": last_reply_id,
                "created_at": now.isoformat(),
            })
            scheduled += 1
        except Exception as e:
            logger.info("[followup] schedule skip: %s", e)
    return scheduled


async def run_due_followups(limit: int = 50) -> Dict[str, int]:
    """Executa follow-ups que venceram. Para ser chamado por cron/worker.

    Para cada followup vencido:
      - Verifica se o cliente já mandou nova mensagem (cancela se sim).
      - Envia a mensagem template via Twilio (route existente).
      - Marca como `sent`.
    Retorna estatísticas {due, sent, cancelled, errors}.
    """
    now = datetime.now(timezone.utc)
    stats = {"due": 0, "sent": 0, "cancelled": 0, "errors": 0}

    cursor = db.isabella_followups.find({
        "status": "scheduled",
        "due_at": {"$lte": now.isoformat()},
    }).limit(limit)

    async for f in cursor:
        stats["due"] += 1
        fid = f.get("id")
        phone = f.get("phone")
        cid = f.get("company_id")
        try:
            # Cliente já reabriu conversa? cancela follow-up
            since = f.get("created_at")
            new_msg = await db.aihub_wa_messages.find_one({
                "company_id": cid, "phone": phone,
                "direction": "inbound", "created_at": {"$gt": since},
            })
            if new_msg:
                await db.isabella_followups.update_one(
                    {"id": fid}, {"$set": {"status": "cancelled",
                                              "reason": "client_replied",
                                              "done_at": now.isoformat()}})
                stats["cancelled"] += 1
                continue

            # Envia via canal Twilio (delegando à rota existente)
            sent = await _send_followup_via_twilio(cid, phone, f.get("template"))
            if sent:
                await db.isabella_followups.update_one(
                    {"id": fid}, {"$set": {"status": "sent",
                                              "done_at": now.isoformat()}})
                stats["sent"] += 1
            else:
                await db.isabella_followups.update_one(
                    {"id": fid}, {"$set": {"status": "failed",
                                              "done_at": now.isoformat()}})
                stats["errors"] += 1
        except Exception as e:
            logger.warning("[followup] run %s: %s", fid, e)
            stats["errors"] += 1
    return stats


async def _send_followup_via_twilio(company_id: str, phone: str,
                                          template: str) -> bool:
    """Insere mensagem outbound na fila do worker isabella_queue.
    O worker existente picará a mensagem e enviará via Twilio."""
    try:
        await db.isabella_queue.insert_one({
            "id": f"job-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "phone": phone,
            "channel": "twilio",
            "text": template,
            "status": "queued",
            "attempts": 0,
            "source": "followup_scheduler",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc)
                            + timedelta(hours=4)).isoformat(),
        })
        # Registra o outbound também em aihub_wa_messages pra fluxo de
        # história/contexto
        await db.aihub_wa_messages.insert_one({
            "id": f"msg-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "phone": phone,
            "direction": "outbound",
            "text": template,
            "channel": "twilio",
            "auto_reply": True,
            "agent_name": "Isabella",
            "source": "followup_scheduler",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            from services.event_bus import emit_event
            await emit_event(
                "wa.message.persisted",
                company_id=company_id,
                source="isabella_followup",
                payload={},
            )
        except Exception:
            pass
        return True
    except Exception as e:
        logger.warning("[followup] _send falhou: %s", e)
        return False


# ===================== F8. REABERTURA AUTOMÁTICA =====================

REOPEN_WORDS = re.compile(
    r"\b(voltou|caiu\s+de\s+novo|n[ãa]o\s+resolveu|continua\s+(igual|"
    r"sem|com\s+problema)|outra\s+vez|de\s+novo|novamente)\b",
    re.IGNORECASE,
)

# Tipos de problema que costumam ter alta reincidência
HIGH_REINCIDENCE_TYPES = {"lentidão", "lentidao", "sem internet",
                            "ONU offline", "ONU_OFFLINE", "ONU_LOW_SIGNAL",
                            "wifi_ruim", "rompimento"}


async def detect_and_reopen_case(*, company_id: str, phone: str,
                                       subscriber_id: Optional[str],
                                       user_text: str) -> Optional[str]:
    """Verifica se este `user_text` é reabertura de OS recente.

    Critérios:
      1. Cliente menciona "voltou", "de novo", "não resolveu", etc; OU
      2. Subscriber tem ticket CLOSED do mesmo tipo nos últimos 30 dias.

    Se sim:
      - Reabre o último ticket (status='reopened') OU cria novo apontando
        para o anterior.
      - Registra no executive_ledger (ISABELLA_CASE_REOPENED).
      - Devolve `ticket_id` reaberto.
    """
    if not subscriber_id:
        return None

    has_complaint = bool(REOPEN_WORDS.search(user_text or ""))

    cutoff_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    last_ticket = await db.tickets.find_one(
        {"company_id": company_id, "subscriber_id": subscriber_id,
         "created_at": {"$gte": cutoff_30d},
         "type": {"$in": list(HIGH_REINCIDENCE_TYPES)}},
        {"_id": 0, "id": 1, "type": 1, "status": 1, "created_at": 1},
        sort=[("created_at", -1)],
    )
    if not last_ticket:
        return None

    closed_recently = last_ticket.get("status") in ("closed", "resolved",
                                                       "finalizado")
    if not (has_complaint or closed_recently):
        # Sem sinal claro de reabertura
        return None

    now_iso = datetime.now(timezone.utc).isoformat()
    new_ticket_id = f"tk-{uuid.uuid4().hex[:10]}"
    try:
        await db.tickets.insert_one({
            "id": new_ticket_id,
            "company_id": company_id,
            "subscriber_id": subscriber_id,
            "phone": phone,
            "type": last_ticket.get("type"),
            "status": "reopened",
            "parent_ticket_id": last_ticket.get("id"),
            "reopen_reason": "isabella_relationship_360",
            "user_text": (user_text or "")[:300],
            "created_at": now_iso,
        })
        await db.executive_ledger.insert_one({
            "id": f"led-{uuid.uuid4().hex[:10]}",
            "action_id": f"reopen-{uuid.uuid4().hex[:12]}",
            "company_id": company_id,
            "subscriber_id": subscriber_id,
            "phone": phone,
            "kind": "ISABELLA_CASE_REOPENED",
            "category": "retention",
            "parent_ticket_id": last_ticket.get("id"),
            "new_ticket_id": new_ticket_id,
            "expected_brl": 0,
            "actual_BRL": 0,
            "status": "reopened",
            "created_at": now_iso,
        })
        return new_ticket_id
    except Exception as e:
        logger.warning("[reopener] falha: %s", e)
        return None
