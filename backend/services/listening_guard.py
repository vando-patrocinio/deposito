"""LISTENING GUARD — detecta intenção direta do cliente e corrige o prompt.

Cliente diz "Só quero instalar" / "Apenas isso" / "Não me pergunte X" e
a Isabella deve PARAR de qualificar e ir DIRETO ao ponto.

Esta camada:
  1. Analisa últimas 6 msgs do cliente.
  2. Detecta padrões de "intenção declarada" / "rejeição de pergunta".
  3. Gera bloco de prompt que ORDENA Isabella a agir, não perguntar.
  4. Pode reescrever resposta da Isabella se ela voltar a fazer
     pergunta que o cliente já recusou.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from database import db

log = logging.getLogger("ponto.listening_guard")

# Padrões de "intenção direta"
_DIRECT_INTENT_RX = [
    (re.compile(r"\b(s[óo]\s+quero|apenas\s+quero|s[óo]\s+preciso|"
                 r"quero\s+apenas|quero\s+s[óo])\b", re.IGNORECASE),
     "intent_direct"),
    (re.compile(r"\bvc\s+tem\?*$|voc[êe]\s+tem\?*$|tem\?*$",
                 re.IGNORECASE), "asks_availability"),
    (re.compile(r"\bnão\s+(precisa|quero|me)\s+pergunt", re.IGNORECASE),
     "rejects_questions"),
    (re.compile(r"\b(mas\s+)?pra\s+que\s+(essa|esta|isso)\s+pergunta",
                 re.IGNORECASE), "questions_question"),
    (re.compile(r"\bd[ãa]\s+pra|d[ãa]\s+sim|qual\s+o?\s+pre[çc]o",
                 re.IGNORECASE), "asks_price"),
    (re.compile(r"\b(quanto\s+custa|me\s+passa\s+(o\s+)?pre[çc]o)",
                 re.IGNORECASE), "asks_price"),
]

# Perguntas qualificatórias que Isabella tende a fazer e o cliente recusa
_QUALIFYING_QUESTIONS_RX = re.compile(
    r"(quantas?\s+pessoas|usam\s+a?\s*internet|quantos?\s+dispositivos|"
    r"endere[çc]o\s+atual|cadastro\s+atual|jogos?\s+online|streamings?\s+"
    r"que\s+usa|qual\s+(seu|o)\s+(plano|endere[çc]o))", re.IGNORECASE)


async def analyze_listening(*, company_id: str, phone: str,
                                user_text: str,
                                history_limit: int = 6) -> Dict[str, Any]:
    """Retorna o que o cliente declarou diretamente + perguntas que
    a Isabella não pode mais fazer.
    """
    # Última msg do cliente + history
    history: List[Dict[str, Any]] = []
    async for m in db.aihub_wa_messages.find(
            {"company_id": company_id, "phone": phone},
            {"_id": 0, "text": 1, "direction": 1, "created_at": 1}
        ).sort("created_at", -1).limit(history_limit * 2):
        history.append(m)
    history.reverse()

    inbound_texts = [m["text"] for m in history
                      if m.get("direction") == "inbound"]
    inbound_texts.append(user_text)  # current

    intents: List[str] = []
    direct_intent_text: Optional[str] = None
    last_inbound = (user_text or "").strip()
    # Detecta sinais no texto atual + 3 últimas inbound
    sample = " ".join((inbound_texts or [])[-4:]).lower()
    for rx, name in _DIRECT_INTENT_RX:
        if rx.search(sample):
            intents.append(name)
            if name == "intent_direct" and not direct_intent_text:
                direct_intent_text = last_inbound

    # Detecta que cliente já respondeu pergunta qualificatória
    # (e Isabella está repetindo)
    isabella_questions_repeated: List[str] = []
    isabella_outbound = [m["text"] for m in history
                          if m.get("direction") == "outbound"]
    if len(isabella_outbound) >= 2:
        last = isabella_outbound[-1] or ""
        prev = isabella_outbound[-2] or ""
        # Pega frases que terminam em "?" presentes em ambas
        q_last = set(re.findall(r"[^?.!]+\?", last.lower()))
        q_prev = set(re.findall(r"[^?.!]+\?", prev.lower()))
        repeated = q_last & q_prev
        for q in repeated:
            isabella_questions_repeated.append(q.strip())

    # Cliente rejeitou pergunta qualificatória?
    rejected_topics: List[str] = []
    for m in inbound_texts[-3:]:
        if _DIRECT_INTENT_RX[3][0].search(m or "") \
                or _DIRECT_INTENT_RX[0][0].search(m or "") \
                or _DIRECT_INTENT_RX[1][0].search(m or ""):
            # Se a últma outbound da Isabella tinha pergunta qualificatória,
            # esse tópico é rejeitado.
            if isabella_outbound:
                last_iso = isabella_outbound[-1] or ""
                if _QUALIFYING_QUESTIONS_RX.search(last_iso):
                    rejected_topics.append("qualifying_questions")
                break

    return {
        "intents": intents,
        "direct_intent_text": direct_intent_text,
        "isabella_questions_repeated": isabella_questions_repeated,
        "rejected_topics": list(set(rejected_topics)),
        "is_listening_violation_risk": (
            "intent_direct" in intents
            or "questions_question" in intents
            or "rejects_questions" in intents
            or bool(isabella_questions_repeated)
            or bool(rejected_topics)),
    }


def inject_listening_block(analysis: Dict[str, Any]) -> str:
    """Retorna bloco a anexar no system prompt forçando escuta."""
    if not analysis or not analysis.get("is_listening_violation_risk"):
        return ""
    parts: List[str] = ["=== MODO ESCUTA OBRIGATÓRIO ==="]
    if "intent_direct" in (analysis.get("intents") or []) \
            and analysis.get("direct_intent_text"):
        parts.append(
            f"O cliente DECLAROU intenção direta: "
            f"\"{analysis['direct_intent_text']}\".\n"
            "REGRA: vá DIRETO ao ponto. NÃO pergunte quantas pessoas usam, "
            "quantos dispositivos, endereço atual, jogos online ou streamings. "
            "Confirme a ação que ele pediu e SIGA — 1 bolha curta. "
            "Se faltar dado essencial pra prosseguir (ex: endereço novo), "
            "pergunte SOMENTE esse dado e nada mais.")
    if "questions_question" in (analysis.get("intents") or []):
        parts.append(
            "O cliente perguntou \"pra que essa pergunta?\". Você precisa "
            "EXPLICAR o motivo em 1 frase curta + dar a opção dele recusar.")
    if "rejects_questions" in (analysis.get("intents") or []):
        parts.append(
            "O cliente PEDIU EXPLICITAMENTE pra você parar de perguntar. "
            "Pare. Vá direto ao que ele quer.")
    if analysis.get("isabella_questions_repeated"):
        parts.append(
            "Você JÁ FEZ esta pergunta no turn anterior: "
            f"{analysis['isabella_questions_repeated']}. NÃO repita.")
    if "qualifying_questions" in (analysis.get("rejected_topics") or []):
        parts.append(
            "Cliente RECUSOU qualificação. Bloqueado nesta conversa: "
            "perguntas sobre pessoas/dispositivos/streamings/jogos.")
    parts.append(
        "FORMATO DA RESPOSTA: máximo 2 bolhas curtas (≤180 chars cada). "
        "NUNCA mais de 1 pergunta no turn inteiro. NUNCA cite o nome do "
        "cliente mais de 1x no turn inteiro.")
    return "\n".join(parts)


def rewrite_if_violates(reply: str, analysis: Dict[str, Any]) -> str:
    """Se a Isabella mesmo assim mandou pergunta qualificatória recusada,
    remove a frase ofensiva."""
    if not analysis or not analysis.get("is_listening_violation_risk"):
        return reply
    if "qualifying_questions" in (analysis.get("rejected_topics") or []) \
            or "intent_direct" in (analysis.get("intents") or []):
        cleaned = []
        for line in re.split(r"(?<=[\.!\?])\s+", reply):
            if _QUALIFYING_QUESTIONS_RX.search(line):
                continue
            cleaned.append(line)
        reply = " ".join(cleaned).strip()
    return reply
