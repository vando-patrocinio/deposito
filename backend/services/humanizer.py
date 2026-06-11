"""HUMANIZER — camada única de humanização para TODOS os canais.

Aplica de forma centralizada (anti-AI-slop):
  1. Anti-CPF Guardian (não pedir doc se identificado)
  2. Listening Guard (intenção direta, perguntas repetidas, recusa de qualificação)
  3. Short-Term Memory (respostas curtas, correções)
  4. Anti-Greeting em conversa contínua (<30min)
  5. Bubble Splitter (≤180c, 1 pergunta/bolha, nome 1x, hard cap 3)
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
    "notes": "Camada de humanização wired em Twilio + Baileys.",
}

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from database import db

log = logging.getLogger("ponto.humanizer")


# Regex anti-greeting reutilizável
_GREET_RX = re.compile(
    r"^\s*(?:oi|ol[áa]|opa|bom\s+dia|boa\s+tarde|boa\s+noite|"
    r"e\s+a[ií]|hey|hi|hello)"
    r"[\s,!]+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+[!,.\s]*\s*"
    r"[😊😄🙂🚀✨🎉☺️]?\s*",
    re.IGNORECASE)


async def _has_recent_outbound(*, company_id: str, phone: str,
                                  minutes: int = 30) -> bool:
    """Detecta conversa contínua (já interagiu nos últimos N min)."""
    try:
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(minutes=minutes)).isoformat()
        n = await db.aihub_wa_messages.count_documents(
            {"company_id": company_id, "phone": phone,
             "direction": "outbound",
             "created_at": {"$gt": cutoff}})
        return n > 0
    except Exception:
        return False


async def humanize_system_prompt(*, sys_prompt: str,
                                       company_id: str,
                                       phone: str,
                                       user_text: str) -> Tuple[str,
                                                                   Dict[str, Any]]:
    """Anexa todos os blocos de humanização ao system prompt antes do LLM.

    Retorna (sys_prompt_enriched, ctx) onde ctx tem:
      - link_for_guard (identificação)
      - listening_analysis (intent_direct, etc.)
      - short_term_analysis (resposta curta, correção)
      - is_continuous_conversation (bool)
    """
    ctx: Dict[str, Any] = {}
    # 1) Anti-CPF — identificação
    try:
        from phone_normalizer import link_phone_to_subscriber
        link = await link_phone_to_subscriber(phone, company_id)
        ctx["link_for_guard"] = link
        history_inbound: List[str] = []
        async for m in db.aihub_wa_messages.find(
                {"company_id": company_id, "phone": phone,
                 "direction": "inbound"},
                {"_id": 0, "text": 1}).sort("created_at", -1).limit(20):
            history_inbound.append(m.get("text", ""))
        from services.anti_cpf_guardian import inject_identification_block
        block = inject_identification_block(
            link, history_inbound=history_inbound)
        if block:
            sys_prompt += "\n\n" + block
    except Exception as e:
        log.info("[humanizer] anti_cpf skip: %s", e)

    # 2) Listening Guard
    try:
        from services.listening_guard import (analyze_listening,
                                                  inject_listening_block)
        la = await analyze_listening(
            company_id=company_id, phone=phone, user_text=user_text)
        ctx["listening_analysis"] = la
        block = inject_listening_block(la)
        if block:
            sys_prompt += "\n\n" + block
    except Exception as e:
        log.info("[humanizer] listening skip: %s", e)

    # 3) Short-Term Memory
    try:
        from services.short_term_memory_guard import (
            analyze_short_term_context, inject_memory_block,
        )
        sta = await analyze_short_term_context(
            company_id=company_id, phone=phone, user_text=user_text)
        ctx["short_term_analysis"] = sta
        block = inject_memory_block(sta)
        if block:
            sys_prompt += "\n\n" + block
    except Exception as e:
        log.info("[humanizer] short_term skip: %s", e)

    # 4) Conversa contínua → não saudar
    try:
        cont = await _has_recent_outbound(
            company_id=company_id, phone=phone, minutes=30)
        ctx["is_continuous_conversation"] = cont
        if cont:
            sys_prompt += (
                "\n\n=== CONVERSA CONTÍNUA ===\n"
                "Esta conversa está em ANDAMENTO (você já interagiu nos "
                "últimos 30min). NÃO comece com 'Oi <Nome>!' ou qualquer "
                "saudação. Vá DIRETO ao ponto. Cumprimento já foi feito.")
    except Exception as e:
        log.info("[humanizer] continuous skip: %s", e)

    # 5) ISABELLA ACTIONS — bloco que ensina os marcadores
    # [AGENDAR_VISITA] / [ABRIR_CHAMADO] para Isabella criar tickets
    # diretamente na Lousa.
    try:
        from services.isabella_actions import actions_prompt_block
        sys_prompt += "\n\n" + actions_prompt_block()
    except Exception as e:
        log.info("[humanizer] actions block skip: %s", e)

    return sys_prompt, ctx


async def humanize_reply(*, reply_text: str,
                            ctx: Dict[str, Any],
                            company_id: str,
                            phone: str) -> str:
    """Aplica rewriters pós-LLM (anti-CPF, listening) ao texto final."""
    if not reply_text:
        return reply_text
    # 1) Listening rewrite
    try:
        la = (ctx or {}).get("listening_analysis")
        if la:
            from services.listening_guard import rewrite_if_violates as _lg_rw
            reply_text = _lg_rw(reply_text, la)
    except Exception as e:
        log.info("[humanizer] listening rewrite skip: %s", e)
    # 2) Anti-CPF rewrite (apenas se identificado)
    try:
        link = (ctx or {}).get("link_for_guard")
        if link and link.get("subscriber_id"):
            from services.anti_cpf_guardian import (
                detect_violations, rewrite_if_violates as _cpf_rw,
            )
            vio = detect_violations(reply_text)
            if vio:
                reply_text = _cpf_rw(reply_text, link)
                log.warning("[humanizer] anti_cpf REWROTE phone=%s vio=%s",
                              phone, vio)
    except Exception as e:
        log.info("[humanizer] anti_cpf rewrite skip: %s", e)
    # 3) Anti-AI-SLOP — remove os 13 vícios que denunciam IA
    # (narração, confirmações vazias, frases corporativas, empatia
    # genérica, manual de instruções, blacklist). REGRA: entregue a
    # resposta. Pare de narrar que está trabalhando.
    try:
        from services.anti_ai_slop import deslop
        reply_text = deslop(reply_text)
    except Exception as e:
        log.info("[humanizer] deslop skip: %s", e)

    # 4) ISABELLA ACTIONS — executa marcadores [AGENDAR_VISITA] /
    # [ABRIR_CHAMADO] criando tickets reais na Lousa e substitui o
    # marcador pelo texto de confirmação ao cliente.
    try:
        from services.isabella_actions import execute_action_markers
        link = (ctx or {}).get("link_for_guard") or {}
        reply_text, actions_done = await execute_action_markers(
            reply_text=reply_text, company_id=company_id, phone=phone,
            subscriber_id=link.get("subscriber_id"),
            subscriber_name=link.get("subscriber_name"))
        if actions_done:
            log.info("[humanizer] %d action(s) executed: %s",
                       len(actions_done),
                       [a.get("type") for a in actions_done])
    except Exception as e:
        log.warning("[humanizer] action markers skip: %s", e)

    return reply_text


def _strip_repeated_greetings(bubbles: List[str]) -> List[str]:
    """Remove 'Oi <Nome>!' do início de cada bolha."""
    out: List[str] = []
    for b in bubbles:
        stripped = _GREET_RX.sub("", b).strip()
        if stripped:
            out.append(stripped)
        # se greeting era a bolha inteira, dropa silenciosamente
    return out


def bubbles_for_send(*, reply_text: str,
                       ctx: Optional[Dict[str, Any]] = None,
                       max_bubble_chars: int = 180,
                       max_bubbles: int = 3) -> List[str]:
    """Quebra reply em bolhas humanas. Se conversa contínua, remove saudação.

    Retorna lista pronta para envio sequencial com delay.
    """
    if not reply_text:
        return []
    try:
        from services.bubble_splitter import split_into_bubbles
        bubbles = split_into_bubbles(
            reply_text,
            max_bubble_chars=max_bubble_chars,
            max_bubbles=max_bubbles) or [reply_text[:max_bubble_chars]]
    except Exception as e:
        log.warning("[humanizer] bubble_splitter falhou: %s", e)
        bubbles = [reply_text[:max_bubble_chars]]
    # Anti-greet em conversa contínua
    if ctx and ctx.get("is_continuous_conversation"):
        bubbles = _strip_repeated_greetings(bubbles)
        if not bubbles:
            # fallback se TUDO era saudação
            bubbles = ["Pode mandar — sigo aqui."]
    return [b.strip() for b in bubbles if b.strip()]
