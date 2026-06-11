"""Constrói o contexto histórico (turns) para passar à LLM da Isabella.

Lê as últimas N mensagens da conversa em `aihub_wa_messages` e devolve
uma lista de turns no formato OpenAI ChatML, com truncate inteligente por
tokens (~4 caracteres por token) pra não estourar o limite do modelo.

CORREÇÃO 2026-02-10: o algoritmo antigo iterava do mais antigo pro mais
recente e dava `break` ao estourar o budget — fazendo a Isabella esquecer
exatamente as mensagens MAIS RECENTES (as que importam). Agora iteramos
do mais recente pro mais antigo, acumulamos enquanto cabe no budget e
revertemos no final pra entregar em ordem cronológica.
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
from typing import List

from database import db

logger = logging.getLogger("ponto.ai_history")

# Janela ampliada: 200 mensagens é o teto físico de busca. O corte real é
# por orçamento de tokens (~6000) — garante ~30-40 turnos de conversa ativa.
DEFAULT_HISTORY_LIMIT = 200
DEFAULT_TOKEN_BUDGET = 6000  # ~24KB de texto — sobra espaço pro system prompt


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
    do mais antigo pro mais recente, garantindo que as mensagens MAIS
    RECENTES sempre entrem (descarta as mais antigas se exceder o budget).

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

    # Busca DESC (mais recentes primeiro) — vamos preservar essas
    docs = await db.aihub_wa_messages.find(
        q,
        {"_id": 0, "id": 1, "direction": 1, "text": 1, "auto_reply": 1,
         "is_correction": 1, "created_at": 1, "is_internal_note": 1},
    ).sort("created_at", -1).limit(limit).to_list(limit)

    # Itera do mais recente pro mais antigo, acumulando enquanto cabe
    turns_desc: List[dict] = []
    used_tokens = 0
    for d in docs:
        if exclude_msg_id and d.get("id") == exclude_msg_id:
            continue
        if d.get("is_internal_note"):
            continue  # notas do co-piloto não vão pro modelo
        text = (d.get("text") or "").strip()
        if not text:
            continue
        t = _approx_tokens(text)
        if used_tokens + t > token_budget and turns_desc:
            # Já temos contexto suficiente — corta as mais antigas
            break
        role = "assistant" if d.get("direction") == "outbound" else "user"
        turns_desc.append({"role": role, "content": text})
        used_tokens += t

    # Inverte para ordem cronológica (oldest → newest)
    turns = list(reversed(turns_desc))

    # Consolida turns consecutivos do mesmo role (LLMs preferem alternância)
    consolidated: List[dict] = []
    for t in turns:
        if consolidated and consolidated[-1]["role"] == t["role"]:
            consolidated[-1]["content"] += "\n" + t["content"]
        else:
            consolidated.append(dict(t))
    return consolidated
