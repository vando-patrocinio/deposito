"""Análise do histórico do cliente para enriquecer o contexto da Isabella IA.

Quando um cliente entra em contato, esta lib examina:
  1. Tickets passados (reparo / instalação / configuração) — últimos 90 dias
  2. Conversas WhatsApp anteriores em TODOS os telefones do mesmo subscriber
  3. Status histórico do equipamento (LOS / Offline anteriores via SmartOLT)

E classifica o problema atual como:
  - **persistente**: 3+ tickets de mesmo tipo nos últimos 30 dias
  - **recorrente**: 2 tickets do tipo nos últimos 60 dias
  - **esporádico**: 1 ticket nos últimos 90 dias
  - **eventual** (default): primeiro contato ou nada relevante encontrado

A análise é injetada como bloco "=== HISTÓRICO DO CLIENTE ===" no system
prompt da Isabella para que ela possa adaptar o tom e a estratégia:
  - persistente → reconhecer o transtorno, oferecer compensação/troca de equipamento
  - recorrente → mencionar "vi que isso já aconteceu antes" e ir mais a fundo
  - esporádico → tratamento padrão sem alarmar
  - eventual → fluxo normal V6.70

Este módulo é PURE — não muta nada no banco, só lê.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db

logger = logging.getLogger("ponto.customer_history")


async def analyze_customer_history(
    company_id: str,
    subscriber_id: Optional[str],
    current_phone: Optional[str] = None,
) -> Dict[str, Any]:
    """Devolve dict com estatísticas + classificação do problema.

    Estrutura:
      {
        "found": bool,
        "subscriber_id": str | None,
        "stats": {
          "tickets_30d_repair": int,
          "tickets_60d_repair": int,
          "tickets_90d_repair": int,
          "tickets_30d_total": int,
          "last_ticket_age_days": int | None,
          "last_ticket_type": str | None,
          "last_ticket_status": str | None,
          "phones_count": int,
          "first_contact_days_ago": int | None,
          "total_inbound_msgs_90d": int,
        },
        "classification": "persistente" | "recorrente" | "esporádico" | "eventual",
        "summary": str,  # texto humano pra injetar no prompt
      }
    """
    if not subscriber_id:
        return {
            "found": False,
            "subscriber_id": None,
            "stats": {},
            "classification": "eventual",
            "summary": "",
        }

    now = datetime.now(timezone.utc)
    since_30 = (now - timedelta(days=30)).isoformat()
    since_60 = (now - timedelta(days=60)).isoformat()
    since_90 = (now - timedelta(days=90)).isoformat()

    base = {"company_id": company_id, "client_id": subscriber_id}
    repair_base = {**base, "type": "reparo"}

    tickets_30d_repair = await db.tickets.count_documents(
        {**repair_base, "created_at": {"$gte": since_30}}
    )
    tickets_60d_repair = await db.tickets.count_documents(
        {**repair_base, "created_at": {"$gte": since_60}}
    )
    tickets_90d_repair = await db.tickets.count_documents(
        {**repair_base, "created_at": {"$gte": since_90}}
    )
    tickets_30d_total = await db.tickets.count_documents(
        {**base, "created_at": {"$gte": since_30}}
    )

    last_ticket = await db.tickets.find_one(
        base,
        {"_id": 0, "type": 1, "status": 1, "priority": 1, "created_at": 1,
         "ai_diagnosis": 1},
        sort=[("created_at", -1)],
    )

    last_ticket_age_days: Optional[int] = None
    last_ticket_type: Optional[str] = None
    last_ticket_status: Optional[str] = None
    last_diagnosis: Optional[str] = None
    if last_ticket:
        try:
            dt = datetime.fromisoformat(
                last_ticket["created_at"].replace("Z", "+00:00")
            )
            last_ticket_age_days = (now - dt).days
        except Exception:
            pass
        last_ticket_type = last_ticket.get("type")
        last_ticket_status = last_ticket.get("status")
        last_diagnosis = (last_ticket.get("ai_diagnosis") or {}).get("status")

    # Telefones do subscriber
    phones = await db.subscriber_phones.find(
        {"company_id": company_id, "subscriber_id": subscriber_id},
        {"_id": 0, "normalized_number": 1},
    ).to_list(20)
    phone_numbers = [p["normalized_number"] for p in phones
                      if p.get("normalized_number")]

    # Primeira interação WhatsApp ever
    first_msg = await db.aihub_wa_messages.find_one(
        {"company_id": company_id,
         "phone": {"$in": phone_numbers} if phone_numbers else current_phone},
        {"_id": 0, "created_at": 1},
        sort=[("created_at", 1)],
    )
    first_contact_days_ago: Optional[int] = None
    if first_msg:
        try:
            dt = datetime.fromisoformat(
                first_msg["created_at"].replace("Z", "+00:00")
            )
            first_contact_days_ago = (now - dt).days
        except Exception:
            pass

    total_inbound_msgs_90d = await db.aihub_wa_messages.count_documents({
        "company_id": company_id,
        "phone": {"$in": phone_numbers} if phone_numbers else current_phone,
        "direction": "inbound",
        "created_at": {"$gte": since_90},
    })

    # Classificação
    if tickets_30d_repair >= 3:
        classification = "persistente"
    elif tickets_60d_repair >= 2:
        classification = "recorrente"
    elif tickets_90d_repair >= 1:
        classification = "esporádico"
    else:
        classification = "eventual"

    stats = {
        "tickets_30d_repair": int(tickets_30d_repair),
        "tickets_60d_repair": int(tickets_60d_repair),
        "tickets_90d_repair": int(tickets_90d_repair),
        "tickets_30d_total": int(tickets_30d_total),
        "last_ticket_age_days": last_ticket_age_days,
        "last_ticket_type": last_ticket_type,
        "last_ticket_status": last_ticket_status,
        "last_ticket_diagnosis": last_diagnosis,
        "phones_count": len(phone_numbers),
        "first_contact_days_ago": first_contact_days_ago,
        "total_inbound_msgs_90d": int(total_inbound_msgs_90d),
    }

    return {
        "found": True,
        "subscriber_id": subscriber_id,
        "stats": stats,
        "classification": classification,
        "summary": _build_summary(classification, stats),
    }


def _build_summary(classification: str, stats: Dict[str, Any]) -> str:
    """Texto humano resumindo o histórico — vai pro prompt da Isabella."""
    parts = []

    # Cabeçalho com classificação
    badges = {
        "persistente": "🔴 PROBLEMA PERSISTENTE",
        "recorrente": "🟠 PROBLEMA RECORRENTE",
        "esporádico": "🟡 PROBLEMA ESPORÁDICO",
        "eventual": "🟢 PRIMEIRO CONTATO / EVENTUAL",
    }
    parts.append(badges.get(classification, "🟢 EVENTUAL"))

    t30 = stats.get("tickets_30d_repair", 0)
    t60 = stats.get("tickets_60d_repair", 0)
    t90 = stats.get("tickets_90d_repair", 0)
    last_age = stats.get("last_ticket_age_days")
    last_type = stats.get("last_ticket_type")
    last_diag = stats.get("last_ticket_diagnosis")
    fcd = stats.get("first_contact_days_ago")
    msgs90 = stats.get("total_inbound_msgs_90d", 0)

    if classification == "persistente":
        parts.append(
            f"Esse cliente abriu **{t30} chamados técnicos no último mês**. "
            "Histórico recorrente — reconheça o transtorno COM EMPATIA usando o "
            "PRIMEIRO NOME REAL do cliente (extraia do bloco VERIFICAÇÃO DA CONEXÃO, "
            "campo 'Nome' ou 'Apelido'). Modelo de frase: "
            "\"[PrimeiroNome], vi aqui que você teve várias ocorrências esse mês — "
            "lamento muito pelo desconforto.\" "
            "⚠️ NUNCA invente nome — se não houver bloco com dados reais, use saudação neutra. "
            "Considere oferecer compensação (crédito na próxima fatura), "
            "trocar a ONT (se 3+ LOS) ou escalar pra Supervisor."
        )
    elif classification == "recorrente":
        parts.append(
            f"Cliente abriu **{t60} chamados de reparo nos últimos 60 dias**. "
            "Mencione naturalmente que viu o histórico: \"Vi aqui que você "
            "já teve um problema parecido recentemente, vamos investigar a "
            "fundo dessa vez pra resolver de vez.\""
        )
    elif classification == "esporádico":
        parts.append(
            f"Cliente teve **{t90} chamado de reparo nos últimos 90 dias**. "
            "Tratamento padrão, mas mostre cuidado em resolver bem dessa vez."
        )

    if last_age is not None and last_type:
        parts.append(
            f"Último chamado: {last_type} ({last_age} dia(s) atrás)"
            + (f" · diagnóstico: {last_diag}" if last_diag else "")
            + "."
        )

    if fcd is not None and fcd > 0:
        parts.append(f"Cliente da casa há {fcd} dias.")

    if msgs90 > 0:
        parts.append(f"{msgs90} mensagens recebidas nos últimos 90 dias.")

    return " ".join(parts)


def format_history_for_prompt(analysis: Dict[str, Any]) -> str:
    """Bloco pra injetar no system prompt."""
    if not analysis or not analysis.get("found"):
        return ""
    cls = analysis.get("classification", "eventual")
    summary = analysis.get("summary", "")
    return (
        "=== HISTÓRICO DO CLIENTE (análise de 90 dias) ===\n"
        f"Classificação: **{cls.upper()}**\n"
        f"{summary}\n\n"
        "⚠️ Use esse histórico pra ADAPTAR o tom da resposta. "
        "NÃO recite os números crus pro cliente (\"você teve 3 chamados\") — "
        "mencione naturalmente (\"vi que isso aconteceu outras vezes esse mês\"). "
        "Cliente persistente merece tratamento DIFERENCIADO: empatia REAL, "
        "compensação proativa, solução definitiva (troca de equipamento se "
        "for o caso). Não trate como se fosse o primeiro contato.\n"
    )
