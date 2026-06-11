"""
Alvaro IA — Resumo de Atendimento por OS (iter211ay)

Para uma OS específica, busca o relato + o histórico de WhatsApp do cliente
(últimas 30 mensagens das últimas 48h) e gera um resumo conciso do que a
atendente fez, se o procedimento foi executado e quais testes foram aplicados.

O resumo é cacheado em `db.alvaro_os_summaries` por 6 horas para evitar
re-processar a cada abertura da OS.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "operacoes",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Path

from core import DEMO_COMPANY_ID, EMERGENT_LLM_KEY, get_current_user
from database import db

logger = logging.getLogger("alvaro.os_summary")
router = APIRouter(prefix="/api/alvaro/os-summary", tags=["alvaro-ia"])

_CACHE_HOURS = 6
_MAX_MSGS = 30  # últimas N msgs do whatsapp pra inferir contexto

_SYSTEM = (
    "Você é Álvaro, um especialista em atendimento técnico de provedores de "
    "internet. Receberá: (1) o RELATO da atendente sobre o chamado e "
    "(2) o HISTÓRICO de mensagens WhatsApp recentes com o cliente.\n\n"
    "Sua tarefa: produzir um JSON com 3 campos curtos, em PT-BR, para "
    "orientar o técnico que vai fazer a visita:\n"
    "• `entendimento` (1 frase curta) — o que a atendente entendeu do problema.\n"
    "• `procedimentos` (lista de até 4 strings curtas) — passos/tentativas que "
    "  já foram feitos (ex: 'Cliente reiniciou o roteador', 'Foi feito reboot "
    "  via SmartOLT', 'Cliente confirmou que LED PON está vermelho').\n"
    "• `testes` (lista de até 3 strings) — testes/diagnósticos identificados "
    "  no chat ou relato (ex: 'Ping para 8.8.8.8 falhou', 'Sinal Rx -28 dBm').\n\n"
    "Se a informação não estiver disponível, retorne lista vazia. "
    "NÃO invente. Saída APENAS JSON válido."
)


@router.get("/{ticket_id}")
async def get_os_summary(
    ticket_id: str = Path(...),
    user: dict = Depends(get_current_user),
):
    """Retorna o resumo Alvaro pra um ticket (cacheado por 6h)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID

    # 1) Busca cache válido
    cached = await db.alvaro_os_summaries.find_one(
        {"ticket_id": ticket_id, "company_id": cid}, {"_id": 0},
    )
    if cached:
        try:
            ts = datetime.fromisoformat(cached["computed_at"].replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
            if age_h < _CACHE_HOURS:
                return {**cached, "from_cache": True, "age_hours": round(age_h, 2)}
        except Exception:
            pass

    # 2) Carrega o ticket pra pegar relato + telefone do cliente
    ticket = await db.lousa_tickets.find_one(
        {"id": ticket_id}, {"_id": 0, "client_snapshot": 1, "type": 1,
                              "created_at": 1, "client_id": 1},
    )
    if not ticket:
        raise HTTPException(404, "OS não encontrada")
    cs = ticket.get("client_snapshot") or {}
    relato = (cs.get("relato") or "").strip()
    phone = (cs.get("phone") or "").strip()

    if not relato and not phone:
        return {"ticket_id": ticket_id,
                "entendimento": "Sem relato e sem telefone — não há contexto para análise.",
                "procedimentos": [], "testes": [],
                "from_cache": False, "computed_at": _now_iso()}

    # 3) Busca histórico de WhatsApp do cliente (últimas 48h, max 30 msgs)
    msgs: list = []
    if phone:
        # Normaliza telefone (pega só dígitos)
        ph_norm = "".join(c for c in phone if c.isdigit())
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        cur = db.aihub_wa_messages.find(
            {"company_id": cid,
              "phone": {"$regex": ph_norm[-9:] if len(ph_norm) >= 9 else ph_norm},
              "created_at": {"$gte": cutoff}},
            {"_id": 0, "direction": 1, "text": 1, "created_at": 1},
        ).sort("created_at", -1).limit(_MAX_MSGS)
        async for m in cur:
            msgs.append(m)
        msgs.reverse()  # cronológico

    # 4) Monta prompt e chama Claude via Emergent LLM
    summary = await _llm_summarize(relato, msgs)

    # 5) Salva cache
    doc = {
        "id": f"alvosm-{uuid.uuid4().hex[:10]}",
        "ticket_id": ticket_id, "company_id": cid,
        "entendimento": summary.get("entendimento", ""),
        "procedimentos": summary.get("procedimentos", []),
        "testes": summary.get("testes", []),
        "computed_at": _now_iso(),
        "input_msg_count": len(msgs),
        "input_relato_len": len(relato),
    }
    await db.alvaro_os_summaries.update_one(
        {"ticket_id": ticket_id, "company_id": cid},
        {"$set": doc}, upsert=True,
    )
    return {**doc, "from_cache": False, "age_hours": 0}


async def _llm_summarize(relato: str, msgs: list) -> dict:
    """Chama Claude Sonnet via Emergent LLM. Fallback resiliente em falha."""
    if not EMERGENT_LLM_KEY:
        logger.warning("[alvaro-os-summary] sem EMERGENT_LLM_KEY")
        return {"entendimento": relato[:200] or "Sem relato registrado.",
                "procedimentos": [], "testes": []}

    chat_lines = []
    for m in msgs[-_MAX_MSGS:]:
        who = "Cliente" if m.get("direction") == "inbound" else "Atendente"
        txt = (m.get("text") or "").strip().replace("\n", " ")
        if not txt:
            continue
        chat_lines.append(f"{who}: {txt[:300]}")
    chat_block = "\n".join(chat_lines) if chat_lines else "(sem histórico WhatsApp)"

    prompt = (
        f"RELATO DA ATENDENTE:\n{relato or '(não fornecido)'}\n\n"
        f"HISTÓRICO WHATSAPP (cronológico, últimas 48h):\n{chat_block}\n\n"
        f"Retorne o JSON pedido."
    )

    try:
        # noqa: PLC0415 — import lazy pra não pesar startup
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"alvaro-os-{uuid.uuid4().hex[:8]}",
            system_message=_SYSTEM,
        ).with_model("anthropic", "claude-sonnet-4-6")
        raw = await chat.send_message(UserMessage(text=prompt))
        text = _strip_json(raw)
        data = json.loads(text)
        return {
            "entendimento": str(data.get("entendimento") or "")[:300],
            "procedimentos": [str(x)[:120] for x in (data.get("procedimentos") or [])][:4],
            "testes": [str(x)[:120] for x in (data.get("testes") or [])][:3],
        }
    except Exception as e:
        logger.exception("[alvaro-os-summary] LLM falhou: %s", e)
        return {"entendimento": (relato[:200] or "Não foi possível gerar resumo agora."),
                "procedimentos": [], "testes": []}


def _strip_json(raw: str) -> str:
    """Remove cercas ``` e texto antes/depois do JSON."""
    t = (raw or "").strip()
    if t.startswith("```"):
        # remove primeira cerca + linguagem opcional
        t = t.split("\n", 1)[1] if "\n" in t else t.lstrip("` ")
    if t.endswith("```"):
        t = t.rsplit("```", 1)[0]
    # Achata início até primeiro {
    i = t.find("{")
    if i > 0:
        t = t[i:]
    return t.strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
