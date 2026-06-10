"""OPERAÇÃO MEMÓRIA TOTAL — Long-Term Memory Retriever da Isabella.

Recupera o histórico operacional do assinante das últimas N janelas
(15d/30d/60d) e produz um bloco compacto pra injetar no system prompt
da Isabella. Sem isso, ela responde como se nunca tivesse falado com o
cliente — quebra de identidade da Customer Success Director.

Fontes consultadas (todas via MongoDB real, política Zero Mocks):
  • `aihub_wa_messages`     — turnos antigos (resumo agregado)
  • `ai_evaluations`        — outcomes, NPS, OS_LEARNING, memória curta
  • `tickets`               — OS abertas/fechadas e tipo (reparo, lentidão)
  • `executive_ledger`      — eventos financeiros (truck roll evitado, etc)
  • `wa_conversations`      — primeiro contato, identidade resolvida
  • `subscribers`           — plano, status contratual

A função `inject_long_term_block` devolve string pronta pro system prompt.
A função `summarize_subscriber_history` devolve um dict estruturado pra
debug/testes.

Cada janela cronológica responde a uma pergunta específica:
  • 15 dias  → "o que aconteceu recentemente?"
  • 30 dias  → "qual o padrão do último mês?"
  • 60 dias  → "ele é cliente recorrente em problemas?"
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db

logger = logging.getLogger("ponto.long_term_memory")

WINDOWS_DAYS = (15, 30, 60)
MAX_OS_LIST = 5
MAX_OUTCOMES = 5


def _iso_cutoff(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def _count_messages_window(company_id: str, phone: str,
                                    cutoff: datetime) -> Dict[str, int]:
    """Conta mensagens inbound/outbound numa janela."""
    pipeline = [
        {"$match": {"company_id": company_id, "phone": phone,
                     "created_at": {"$gte": cutoff.isoformat()}}},
        {"$group": {"_id": "$direction", "n": {"$sum": 1}}},
    ]
    out = {"inbound": 0, "outbound": 0}
    async for d in db.aihub_wa_messages.aggregate(pipeline):
        if d.get("_id") in out:
            out[d["_id"]] = d["n"]
    return out


async def _tickets_window(company_id: str, subscriber_id: Optional[str],
                              cutoff: datetime) -> List[Dict[str, Any]]:
    """Recupera OS recentes do assinante."""
    if not subscriber_id:
        return []
    cursor = db.tickets.find(
        {"company_id": company_id, "subscriber_id": subscriber_id,
         "created_at": {"$gte": cutoff.isoformat()}},
        {"_id": 0, "id": 1, "type": 1, "status": 1, "created_at": 1,
         "closed_at": 1, "summary": 1, "reason": 1},
    ).sort("created_at", -1).limit(MAX_OS_LIST)
    return await cursor.to_list(MAX_OS_LIST)


async def _outcomes_window(company_id: str, phone: str,
                                subscriber_id: Optional[str],
                                cutoff: datetime) -> List[Dict[str, Any]]:
    """Última lista de outcomes/NPS gravados em ai_evaluations."""
    q: Dict[str, Any] = {"company_id": company_id,
                          "created_at": {"$gte": cutoff.isoformat()}}
    if subscriber_id:
        q["$or"] = [{"subscriber_id": subscriber_id}, {"phone": phone}]
    else:
        q["phone"] = phone
    cursor = db.ai_evaluations.find(
        q,
        {"_id": 0, "kind": 1, "outcome": 1, "outcomes": 1, "nps_inferido": 1,
         "nps_motivo": 1, "tags": 1, "created_at": 1,
         "memoria_operacional": 1, "user_text": 1},
    ).sort("created_at", -1).limit(MAX_OUTCOMES)
    return await cursor.to_list(MAX_OUTCOMES)


async def _ledger_window(company_id: str, subscriber_id: Optional[str],
                              cutoff: datetime) -> List[Dict[str, Any]]:
    """Eventos financeiros (truck roll evitado, etc)."""
    if not subscriber_id:
        return []
    cursor = db.executive_ledger.find(
        {"company_id": company_id, "subscriber_id": subscriber_id,
         "created_at": {"$gte": cutoff.isoformat()}},
        {"_id": 0, "kind": 1, "category": 1, "actual_BRL": 1,
         "valor_confirmado_brl": 1, "created_at": 1, "status": 1},
    ).sort("created_at", -1).limit(MAX_OUTCOMES)
    return await cursor.to_list(MAX_OUTCOMES)


async def _first_contact(company_id: str, phone: str) -> Optional[str]:
    """Quando foi o primeiro contato com este número."""
    doc = await db.aihub_wa_messages.find_one(
        {"company_id": company_id, "phone": phone},
        {"_id": 0, "created_at": 1},
        sort=[("created_at", 1)],
    )
    return (doc or {}).get("created_at")


async def _subscriber_profile(company_id: str,
                                  subscriber_id: Optional[str]) -> Dict[str, Any]:
    """Dados contratuais do assinante."""
    if not subscriber_id:
        return {}
    doc = await db.subscribers.find_one(
        {"company_id": company_id, "id": subscriber_id},
        {"_id": 0, "name": 1, "plan": 1, "status": 1, "city": 1,
         "neighborhood": 1, "due_day": 1},
    ) or await db.subscribers.find_one(
        {"company_id": company_id, "_id": subscriber_id},
        {"_id": 0, "name": 1, "plan": 1, "status": 1, "city": 1,
         "neighborhood": 1, "due_day": 1},
    )
    return doc or {}


async def summarize_subscriber_history(*, company_id: str, phone: str,
                                            subscriber_id: Optional[str] = None
                                            ) -> Dict[str, Any]:
    """Devolve estrutura compacta com memória de 15/30/60 dias.

    Estrutura retornada::

        {
          "phone": "...",
          "subscriber_id": "...",
          "first_contact": "2025-10-01T...",
          "profile": {name, plan, status, ...},
          "windows": {
            15: {messages: {inbound, outbound}, tickets: [...],
                  outcomes: [...], ledger: [...]},
            30: {...},
            60: {...},
          },
        }
    """
    summary: Dict[str, Any] = {
        "phone": phone,
        "subscriber_id": subscriber_id,
        "windows": {},
    }
    summary["first_contact"] = await _first_contact(company_id, phone)
    summary["profile"] = await _subscriber_profile(company_id, subscriber_id)

    for days in WINDOWS_DAYS:
        cutoff = _iso_cutoff(days)
        messages = await _count_messages_window(company_id, phone, cutoff)
        tickets = await _tickets_window(company_id, subscriber_id, cutoff)
        outcomes = await _outcomes_window(company_id, phone,
                                              subscriber_id, cutoff)
        ledger = await _ledger_window(company_id, subscriber_id, cutoff)
        summary["windows"][days] = {
            "messages": messages,
            "tickets": tickets,
            "outcomes": outcomes,
            "ledger": ledger,
        }
    return summary


def _fmt_ticket(t: Dict[str, Any]) -> str:
    typ = t.get("type") or "OS"
    st = t.get("status") or "?"
    when = (t.get("created_at") or "")[:10]
    extra = t.get("summary") or t.get("reason") or ""
    extra = f" — {extra}" if extra else ""
    return f"  - [{when}] {typ} ({st}){extra}"


def _fmt_outcome(o: Dict[str, Any]) -> str:
    when = (o.get("created_at") or "")[:10]
    kind = o.get("kind") or ""
    outs = o.get("outcomes") or ([o.get("outcome")] if o.get("outcome") else [])
    outs = ", ".join(str(x) for x in outs if x)
    nps = o.get("nps_inferido")
    bits = [f"[{when}]"]
    if kind:
        bits.append(kind)
    if outs:
        bits.append(outs)
    if nps is not None:
        bits.append(f"NPS≈{nps}")
    return "  - " + " | ".join(bits)


def _fmt_ledger(le: Dict[str, Any]) -> str:
    when = (le.get("created_at") or "")[:10]
    kind = le.get("kind") or le.get("category") or "EVENTO"
    brl = le.get("actual_BRL") or le.get("valor_confirmado_brl") or 0
    return f"  - [{when}] {kind} — R$ {brl}"


def inject_long_term_block(summary: Dict[str, Any]) -> str:
    """Devolve o bloco pronto pra concatenar no system prompt.

    Retorna string vazia se NÃO houver histórico relevante (cliente
    novo) — evita poluir o prompt sem necessidade.
    """
    if not summary:
        return ""
    profile = summary.get("profile") or {}
    windows = summary.get("windows") or {}

    # Verifica se tem qualquer histórico relevante
    has_any = any(
        (w.get("tickets") or w.get("outcomes") or w.get("ledger")
         or (w.get("messages") or {}).get("inbound", 0) > 0)
        for w in windows.values()
    )
    if not has_any and not summary.get("first_contact"):
        return ""

    lines: List[str] = ["=== MEMÓRIA HISTÓRICA DO ASSINANTE (OBRIGATÓRIO LER) ==="]

    if summary.get("first_contact"):
        first = (summary["first_contact"] or "")[:10]
        lines.append(f"Primeiro contato registrado: {first}")
    if profile.get("name"):
        lines.append(f"Cliente: {profile['name']} | Plano: "
                     f"{profile.get('plan','?')} | Status: "
                     f"{profile.get('status','?')}")

    # Snapshot por janela — só monta seção se houver conteúdo
    for days in WINDOWS_DAYS:
        w = windows.get(days) or {}
        msgs = w.get("messages") or {}
        tickets = w.get("tickets") or []
        outcomes = w.get("outcomes") or []
        ledger = w.get("ledger") or []
        if not (tickets or outcomes or ledger or msgs.get("inbound", 0)):
            continue
        lines.append(f"\n— Janela {days}d —")
        if msgs.get("inbound", 0) or msgs.get("outbound", 0):
            lines.append(
                f"  Mensagens: {msgs.get('inbound',0)} do cliente, "
                f"{msgs.get('outbound',0)} suas (Isabella)."
            )
        if tickets:
            lines.append(f"  OS ({len(tickets)} no período):")
            for t in tickets:
                lines.append(_fmt_ticket(t))
        if outcomes:
            lines.append("  Outcomes/NPS recentes:")
            for o in outcomes:
                lines.append(_fmt_outcome(o))
        if ledger:
            lines.append("  Eventos financeiros:")
            for le in ledger:
                lines.append(_fmt_ledger(le))

    lines.append(
        "\nREGRA: use essa memória pra contextualizar. Se o cliente "
        "mencionar algo de 15/30/60 dias atrás, você já sabe. NÃO "
        "PERGUNTE de novo se já está aqui. Mostre que se lembra "
        "(\"vi aqui que abrimos OS dia X\", \"da última vez seu sinal "
        "voltou\", etc)."
    )
    return "\n".join(lines)


async def build_long_term_block(*, company_id: str, phone: str,
                                     subscriber_id: Optional[str] = None) -> str:
    """Atalho one-shot: gera o bloco pra injetar no system prompt."""
    try:
        summary = await summarize_subscriber_history(
            company_id=company_id, phone=phone, subscriber_id=subscriber_id)
        return inject_long_term_block(summary)
    except Exception as e:
        logger.warning("[long_term_memory] falha ao montar bloco: %s", e)
        return ""
