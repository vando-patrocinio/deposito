"""OPERAÇÃO MEMÓRIA DE CURTO PRAZO OBRIGATÓRIA — Isabella.

Quando o cliente responde com mensagens curtas (sim/ok/pode/agora/etc), a
Isabella tem de interpretar como CONTINUAÇÃO da última pergunta dela, e
nunca abrir novo fluxo comercial.

Pipeline:
  1. `analyze_short_term_context(company_id, phone)` → devolve:
       • last_isabella_question (string)
       • current_user_text é resposta curta?
       • assunto aberto (reparo/cobrança/agendamento/etc)
  2. `inject_memory_block(analysis)` → bloco para system prompt.
  3. `enforce_memory_on_reply(analysis, reply)` → reescreve resposta se
     ela mudou de assunto.
  4. Registra `context_recovered=true` ou `context_error=true` em
     `ai_evaluations`.
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

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db


SHORT_REPLIES = {
    "sim", "não", "nao", "ok", "okay", "quero", "pode",
    "isso", "essa", "esse", "ele", "ela", "hoje", "amanhã",
    "amanha", "agora", "claro", "confirmo", "confirmado",
    "beleza", "certo", "perfeito", "tá", "ta", "blz", "uhum",
    "aham", "yes",
}


OPEN_TOPIC_PATTERNS: List[tuple] = [
    ("reparo", re.compile(
        r"\b(sem\s+internet|caiu|offline|lento|lerd[oa]|wifi|sinal|fibra|"
        r"modem|onu|n[ãa]o\s+funciona)\b", re.IGNORECASE)),
    ("cobranca", re.compile(
        r"\b(2[ªa]?\s*via|segunda\s+via|boleto|pagar|fatura|atrasad|cobran|"
        r"pix|negocia)\b", re.IGNORECASE)),
    ("cancelamento", re.compile(
        r"\b(cancelar|encerrar|sair|tirar\s+o\s+plano)\b", re.IGNORECASE)),
    ("agendamento", re.compile(
        r"\b(agendar|visita|t[ée]cnico|hor[áa]rio|amanh[ãa]|"
        r"\d{1,2}h|\d{1,2}:\d{2})\b", re.IGNORECASE)),
    ("os", re.compile(r"\b(OS|chamado|protocolo)\s*#?\d", re.IGNORECASE)),
]


COMMERCIAL_FORBIDDEN = re.compile(
    r"\b(quer\s+(contratar|conhecer)|posso\s+(te\s+)?(oferecer|apresentar)|"
    r"playhub|ligo\s*security|ligo\s*m[óo]vel|chip\s*5g|streaming|"
    r"plano\s+mais\s+r[áa]pido|upgrade|combo|indique\s+e\s+ganhe|"
    r"que\s+tal\s+(adicionar|incluir|conhecer))\b", re.IGNORECASE)


def _is_short_reply(text: str) -> bool:
    if not text:
        return False
    s = text.strip().lower().rstrip(".!?,")
    if len(s) <= 30 and s in SHORT_REPLIES:
        return True
    # Múltiplas palavras mas todas curtas (ex: "pode sim")
    tokens = re.split(r"\s+", s)
    if len(tokens) <= 3 and all(t in SHORT_REPLIES or len(t) <= 3 for t in tokens):
        return True
    return False


def _detect_open_topic(texts: List[str]) -> Optional[str]:
    """Olha últimos textos do CLIENTE para detectar assunto aberto."""
    blob = " ".join(t or "" for t in texts)
    for tag, pat in OPEN_TOPIC_PATTERNS:
        if pat.search(blob):
            return tag
    return None


def _detect_correction(user_text: str) -> bool:
    """Detecta se cliente está corrigindo a IA."""
    return bool(re.search(
        r"\b(da\s+onde\s+voc[êe]\s+tirou|n[ãa]o\s+foi\s+isso|"
        r"voc[êe]\s+entendeu\s+errado|n[ãa]o\s+estou\s+falando\s+disso|"
        r"nada\s+a\s+ver|n[ãa]o\s+era\s+isso)\b", user_text or "",
        re.IGNORECASE))


async def analyze_short_term_context(*, company_id: str, phone: str,
                                          user_text: str) -> Dict[str, Any]:
    """Lê últimos 6 turns (3 isabella + 3 cliente) e devolve análise."""
    # Últimas 6 mensagens da conversa
    recent: List[Dict[str, Any]] = []
    async for m in db.aihub_wa_messages.find(
            {"company_id": company_id, "phone": phone},
            {"_id": 0, "direction": 1, "text": 1, "created_at": 1}
    ).sort("created_at", -1).limit(6):
        recent.append(m)
    recent.reverse()  # cronológico

    last_isabella_question: Optional[str] = None
    last_isabella_text: Optional[str] = None
    prev_user_texts: List[str] = []
    for m in recent:
        if m.get("direction") == "outbound":
            txt = m.get("text") or ""
            last_isabella_text = txt
            # Pega a última frase que termina em "?" ou propõe escolha
            for sent in re.split(r"(?<=[\.\!\?])\s+", txt):
                if "?" in sent or re.search(r"\b(prefere|quer|pode|posso)\b",
                                              sent, re.IGNORECASE):
                    last_isabella_question = sent.strip()
        elif m.get("direction") == "inbound":
            prev_user_texts.append(m.get("text", ""))

    is_short = _is_short_reply(user_text)
    open_topic = _detect_open_topic(prev_user_texts + [user_text])
    is_correction = _detect_correction(user_text)

    return {
        "user_text": user_text,
        "last_isabella_text": last_isabella_text,
        "last_isabella_question": last_isabella_question,
        "is_short_reply": is_short,
        "open_topic": open_topic,
        "is_correction": is_correction,
        "history_count": len(recent),
    }


def inject_memory_block(analysis: Dict[str, Any]) -> str:
    """Devolve bloco a apender no system prompt da Isabella."""
    if not analysis:
        return ""
    blocks: List[str] = []

    if analysis.get("last_isabella_question"):
        blocks.append(
            "=== MEMÓRIA DE CURTO PRAZO (OBRIGATÓRIO) ===\n"
            f"SUA ÚLTIMA PERGUNTA foi: \"{analysis['last_isabella_question']}\"\n"
            "Antes de responder, releia essa pergunta.\n"
            "PRIORIDADE MÁXIMA: a resposta atual do cliente está "
            "respondendo a essa pergunta — não inicie novo assunto."
        )

    if analysis.get("is_short_reply"):
        blocks.append(
            "=== RESPOSTA CURTA DETECTADA ===\n"
            f"O cliente respondeu apenas: \"{analysis['user_text']}\".\n"
            "PROIBIDO abrir novo fluxo comercial (PlayHub, Ligo Security, "
            "Ligo Móvel, upgrade, indique-e-ganhe, combo). Interprete como "
            "CONTINUAÇÃO direta da sua última pergunta."
        )

    if analysis.get("open_topic"):
        blocks.append(
            "=== ASSUNTO ABERTO ===\n"
            f"Há assunto operacional aberto: **{analysis['open_topic']}**.\n"
            "REGRA: resolva esse assunto ANTES de propor venda/cross-sell.\n"
            "Sequência: entender → diagnosticar → resolver → confirmar → "
            "registrar outcome → SÓ DEPOIS avaliar oportunidade comercial."
        )

    if analysis.get("is_correction"):
        blocks.append(
            "=== CLIENTE CORRIGIU VOCÊ ===\n"
            "O cliente sinalizou que você entendeu errado. RESPOSTA OBRIGATÓRIA:\n"
            "1. Reconheça o erro brevemente (1 frase).\n"
            "2. Volte ao contexto anterior.\n"
            "3. Continue o atendimento correto.\n"
            "Modelo: \"Você tem razão. Interpretei errado. Voltando: você "
            "queria <X>. Vou seguir por aí.\""
        )

    return "\n\n".join(blocks)


def enforce_memory_on_reply(analysis: Dict[str, Any], reply: str) -> Dict[str, Any]:
    """Verifica se a reply violou a memória de curto prazo.

    Retorna {reply, context_recovered, context_error, violations}.
    """
    out = {"reply": reply, "context_recovered": False,
           "context_error": False, "violations": []}
    if not reply or not analysis:
        return out

    # Se cliente respondeu curto / há assunto aberto, reply NÃO pode iniciar
    # fluxo comercial.
    is_protected = (analysis.get("is_short_reply")
                    or analysis.get("open_topic") in
                    ("reparo", "cobranca", "cancelamento", "agendamento"))
    has_commercial = bool(COMMERCIAL_FORBIDDEN.search(reply))
    if is_protected and has_commercial:
        out["context_error"] = True
        out["violations"].append("commercial_intent_on_short_reply")
        # Reescreve: remove sentenças comerciais e força reconexão
        safe_sentences: List[str] = []
        for sent in re.split(r"(?<=[\.\!\?])\s+", reply.strip()):
            if COMMERCIAL_FORBIDDEN.search(sent):
                continue
            safe_sentences.append(sent)
        if safe_sentences:
            out["reply"] = " ".join(safe_sentences).strip()
        else:
            last_q = (analysis.get("last_isabella_question") or "").strip()
            if last_q:
                out["reply"] = ("Perfeito, vou seguir nessa direção então. "
                                 + last_q)
            else:
                out["reply"] = ("Perfeito. Vou continuar resolvendo seu "
                                 "atendimento por aqui.")
        out["context_recovered"] = True

    # Caso o cliente tenha corrigido E a reply ainda não reconhece, marca erro
    if analysis.get("is_correction") and "raz" not in reply.lower() \
            and "interpret" not in reply.lower():
        out["context_error"] = True
        out["violations"].append("ignored_correction")

    return out


async def log_memory_event(*, company_id: str, phone: str,
                              subscriber_id: Optional[str],
                              analysis: Dict[str, Any],
                              enforcement: Dict[str, Any]) -> None:
    """Grava context_recovered / context_error em ai_evaluations."""
    if not (enforcement.get("context_recovered") or enforcement.get("context_error")):
        return
    try:
        await db.ai_evaluations.insert_one({
            "id": f"mem-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "phone": phone,
            "subscriber_id": subscriber_id,
            "kind": "SHORT_TERM_MEMORY",
            "context_recovered": enforcement.get("context_recovered", False),
            "context_error": enforcement.get("context_error", False),
            "violations": enforcement.get("violations", []),
            "last_isabella_question": analysis.get("last_isabella_question"),
            "user_text": analysis.get("user_text", "")[:200],
            "open_topic": analysis.get("open_topic"),
            "is_short_reply": analysis.get("is_short_reply"),
            "is_correction": analysis.get("is_correction"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass
