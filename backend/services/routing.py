"""Roteador IA — escolhe qual agente responde a uma conversa nova.

Quando há múltiplos agentes ativos no WhatsApp auto-reply, este módulo
classifica a primeira mensagem do cliente e escolhe o agente cujo
`routing_intent` melhor cobre a intenção. A decisão é persistida em
`wa_conversations.routed_agent_id` para que mensagens subsequentes do
mesmo cliente continuem com o mesmo agente (sem reclassificar).

Estratégias (em ordem de prioridade):
  1. Match por palavras-chave (regex case-insensitive) nas
     `routing_intent` — extração simples de termos óbvios (preço,
     fatura, sem sinal etc). Funciona offline, sem LLM.
  2. Se nenhuma keyword bate ou há empate, chama o LLM com a lista
     de agentes + intent + a mensagem para classificar.
  3. Fallback: pega o agente do `whatsapp_auto_reply.agent_name`
     (compatibilidade — comportamento antigo).
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from database import db

logger = logging.getLogger("ponto.routing")

# Keywords genéricas em PT-BR — usadas como atalho rápido para matchar
# `routing_intent`. NÃO alteram nada se o gestor não usar essas palavras
# nos textos dele.
_QUICK_BUCKETS: Dict[str, List[str]] = {
    "vendas": [r"\bpre[çc]o", r"\bplano", r"\bcontrat", r"\bassinar",
                r"\bcombo", r"\boferta", r"\bcoberur", r"\bvender", r"\bvenda"],
    "suporte": [r"\bsinal", r"\bsem internet", r"\bcaiu", r"\blento",
                 r"\blentid[aã]o", r"\bn[aã]o funciona", r"\binstabil",
                 r"\boff", r"\bdesconect"],
    "financeiro": [r"\bfatura", r"\b2[ªa] via", r"\bsegunda via",
                    r"\bcobran[çc]a", r"\bvencido", r"\bvenc(e|imento)",
                    r"\bpaga(r|mento)", r"\bdesbloque", r"\bnegoci"],
    "agendamento": [r"\bvisita", r"\bagendar", r"\bagendamento",
                     r"\bremarcar", r"\btecnico chegar"],
    "cancelamento": [r"\bcancela", r"\bdescontinu", r"\bdesligar plano"],
}


def _keyword_matches(text: str, intent: str) -> int:
    """Conta quantas keywords do `intent` (livre, em PT-BR) batem no `text`."""
    if not text or not intent:
        return 0
    text_l = text.lower()
    score = 0
    # 1. Tokens diretos do intent (palavras com ≥4 chars)
    for tok in re.findall(r"[a-zà-ú]{4,}", intent.lower()):
        if tok in text_l:
            score += 2
    # 2. Buckets genéricos: se o intent contém uma bucket key, aplica regex
    for bucket, patterns in _QUICK_BUCKETS.items():
        if bucket in intent.lower():
            for pat in patterns:
                if re.search(pat, text_l):
                    score += 3
    return score


async def pick_agent_for_message(company_id: str, phone: str,
                                   user_text: str,
                                   default_agent: Optional[dict] = None
                                   ) -> Optional[dict]:
    """Escolhe um agente para responder a `user_text`.

    1. Se a conversa já tem `routed_agent_id`, retorna esse agente (consistência).
    2. Se há só 1 agente ativo, retorna ele.
    3. Senão, computa score por keywords. Vencedor wins.
    4. Empate ou tudo zero → LLM classifier (se motor_ia disponível).
    5. Falha → `default_agent`.

    Sempre persiste a escolha em `wa_conversations.routed_agent_id`.
    """
    # 1. Conversa já roteada?
    conv = await db.wa_conversations.find_one(
        {"company_id": company_id, "phone": phone},
        {"_id": 0, "routed_agent_id": 1},
    )
    if conv and conv.get("routed_agent_id"):
        a = await db.aihub_agents.find_one(
            {"id": conv["routed_agent_id"], "company_id": company_id,
             "active": {"$ne": False}},
            {"_id": 0},
        )
        if a:
            return a

    # 2. Lista agentes ativos
    agents = await db.aihub_agents.find(
        {"company_id": company_id, "active": {"$ne": False}},
        {"_id": 0},
    ).to_list(50)
    if not agents:
        return default_agent
    if len(agents) == 1:
        await _persist_routing(company_id, phone, agents[0]["id"], reason="single_agent")
        return agents[0]

    # 3. Keyword scoring (apenas agentes com routing_intent preenchido)
    candidates: List[Dict[str, Any]] = []
    for a in agents:
        intent = (a.get("routing_intent") or "").strip()
        score = _keyword_matches(user_text, intent) if intent else 0
        candidates.append({"agent": a, "score": score, "intent": intent})
    candidates.sort(key=lambda c: -c["score"])
    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else {"score": 0}

    # 4. Decide
    if top["score"] >= 3 and top["score"] > second["score"]:
        await _persist_routing(company_id, phone, top["agent"]["id"], reason="keyword")
        return top["agent"]

    # 5. LLM classifier (só se houver intents cadastrados)
    intents_present = [c for c in candidates if c["intent"]]
    if intents_present:
        chosen = await _llm_classify(company_id, user_text, intents_present)
        if chosen:
            await _persist_routing(company_id, phone, chosen["id"], reason="llm")
            return chosen

    # 6. Fallback — default_agent (auto-reply config) ou primeiro da lista
    fallback = default_agent or agents[0]
    await _persist_routing(company_id, phone, fallback["id"], reason="fallback")
    return fallback


async def _llm_classify(company_id: str, user_text: str,
                         candidates: List[Dict[str, Any]]) -> Optional[dict]:
    """Chama motor_ia pra classificar. Retorna None em falha."""
    try:
        from services.motor_ia import chat_completion
    except ImportError:
        return None

    options = "\n".join(
        f"{i+1}. {c['agent']['name']}: {c['intent']}"
        for i, c in enumerate(candidates)
    )
    sys = (
        "Você é um roteador. Recebe a primeira mensagem de um cliente em "
        "português do Brasil e escolhe QUAL agente vai atender, com base "
        "na especialidade declarada de cada um. Responda EXCLUSIVAMENTE com "
        "o NÚMERO (1, 2, 3...) do agente escolhido, sem mais nada."
    )
    user = (
        f"MENSAGEM DO CLIENTE:\n{user_text[:500]}\n\n"
        f"AGENTES DISPONÍVEIS:\n{options}\n\n"
        "Responda APENAS com o número do agente. Se não tiver certeza, "
        "escolha o que parece mais genérico."
    )
    try:
        result = await chat_completion(
            company_id,
            messages=[{"role": "system", "content": sys},
                       {"role": "user", "content": user}],
            temperature=0.0, max_tokens=10,
            purpose="atendimento", agent="router_ia",
        )
        raw = (result.get("content") or "").strip()
        m = re.search(r"[1-9]\d*", raw)
        if m:
            idx = int(m.group(0)) - 1
            if 0 <= idx < len(candidates):
                return candidates[idx]["agent"]
    except Exception as e:
        logger.info("[routing] LLM classify falhou: %s", e)
    return None


async def _persist_routing(company_id: str, phone: str, agent_id: str,
                            reason: str) -> None:
    try:
        await db.wa_conversations.update_one(
            {"company_id": company_id, "phone": phone},
            {"$set": {
                "company_id": company_id,
                "phone": phone,
                "routed_agent_id": agent_id,
                "routed_reason": reason,
                "routed_at": __import__("core").now_iso(),
            }},
            upsert=True,
        )
    except Exception as e:
        logger.warning("[routing] persist falhou: %s", e)
