"""Constrói o contexto histórico (turns) para passar à LLM da Isabella.

Lê as últimas N mensagens da conversa em `aihub_wa_messages` e devolve
uma lista de turns no formato OpenAI ChatML, com truncate inteligente por
tokens (~4 caracteres por token) pra não estourar o limite do modelo.
"""
from __future__ import annotations

import logging
from typing import List

from database import db

logger = logging.getLogger("ponto.ai_history")

# Limite default (100 mensagens) — usuário pediu janela maior pra IA entender
# conversas longas. Cap por orçamento de tokens evita estourar a janela do LLM.
# 5000 tokens deixa margem segura (~15%) considerando que ~4 chars/token
# subestima ligeiramente PT-BR vs tiktoken cl100k.
DEFAULT_HISTORY_LIMIT = 100
DEFAULT_TOKEN_BUDGET = 5000  # ~20KB de texto — sobra espaço pro system prompt


def _approx_tokens(text: str) -> int:
    """Aproximação grosseira (~4 chars/token em PT-BR). Suficiente para
    decidir corte sem chamar um tokenizer pesado."""
    if not text:
        return 0
    return max(1, len(text) // 4)


async def fetch_history_turns(company_id: str, phone: str,
                                 limit: int = DEFAULT_HISTORY_LIMIT,
                                 token_budget: int = DEFAULT_TOKEN_BUDGET,
                                 exclude_msg_id: str | None = None) -> List[dict]:
    """Retorna histórico no formato [{role: 'user'|'assistant', content: '...'}, ...]
    do mais antigo pro mais recente, truncado pelo orçamento de tokens.

    Respeita `wa_conversations.context_reset_at` — quando o gestor zera
    o contexto pra teste, msgs anteriores ao reset NÃO entram no histórico
    enviado pro LLM (mas continuam no banco pra auditoria).
    """
    q: dict = {"company_id": company_id, "phone": phone}

    # Aplica filtro de reset de contexto, se houver
    try:
        conv = await db.wa_conversations.find_one(
            {"company_id": company_id, "phone": phone},
            {"_id": 0, "context_reset_at": 1},
        )
        reset_at = (conv or {}).get("context_reset_at")
        if reset_at:
            q["created_at"] = {"$gt": reset_at}
    except Exception as e:
        logger.info("[ai_history] reset_at lookup skip: %s", e)

    docs = await db.aihub_wa_messages.find(
        q,
        {"_id": 0, "id": 1, "direction": 1, "text": 1, "auto_reply": 1,
         "is_correction": 1, "created_at": 1, "is_internal_note": 1},
    ).sort("created_at", -1).limit(limit).to_list(limit)
    # Reverte para ordem cronológica
    docs.reverse()

    turns: List[dict] = []
    used_tokens = 0
    for d in docs:
        if exclude_msg_id and d.get("id") == exclude_msg_id:
            continue
        if d.get("is_internal_note"):
            continue  # notas do co-piloto não vão pro modelo
        text = (d.get("text") or "").strip()
        if not text:
            continue
        role = "assistant" if d.get("direction") == "outbound" else "user"
        t = _approx_tokens(text)
        used_tokens += t
        turns.append({"role": role, "content": text})
        if used_tokens >= token_budget:
            # Corta os mais antigos primeiro (FIFO)
            while turns and used_tokens > token_budget:
                first = turns.pop(0)
                used_tokens -= _approx_tokens(first["content"])
            break

    # Consolida turns consecutivos do mesmo role (LLMs preferem alternância)
    consolidated: List[dict] = []
    for t in turns:
        if consolidated and consolidated[-1]["role"] == t["role"]:
            consolidated[-1]["content"] += "\n" + t["content"]
        else:
            consolidated.append(dict(t))
    return consolidated
