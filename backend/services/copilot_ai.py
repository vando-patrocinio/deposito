"""Co-Pilot IA — assistente interno do atendente humano.

Quando uma conversa WhatsApp está atribuída a um humano (assignee_role="human")
e chega uma nova mensagem inbound do cliente, o Co-Pilot:
1. Analisa o contexto da conversa (últimas mensagens, perfil do cliente,
   outage ativo, status financeiro/conexão se disponível)
2. Gera uma única dica curta em PT-BR (intenção · sentimento · próxima ação)
3. Insere como `direction="internal"` em `aihub_wa_messages` —
   visível APENAS para o atendente humano no chat. O cliente NUNCA vê.

Anti-spam:
- Só dispara se conversa está com humano (não-IA, não-grupo, não-fechada)
- Dedup por message_id da última inbound (1 dica por inbound)
- Skip se a inbound é muito curta (<6 chars)
- Falha graciosamente (silencioso) se LLM indisponível

Diferença de SmartOLT internal notes:
- SmartOLT: nota fixa baseada em pane detectada (template)
- Co-Pilot: nota DINÂMICA gerada por LLM analisando a conversa específica
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from core import now_iso
from database import db

logger = logging.getLogger("copilot_ai")

# Tamanhos mínimos / máximos
MIN_INBOUND_CHARS = 6
HIST_LIMIT = 8       # últimas N msgs pro contexto
MAX_HINT_CHARS = 280  # nota interna curta


SYSTEM_PROMPT = (
    "Você é um Co-Pilot interno que ajuda atendentes HUMANOS durante "
    "conversas de WhatsApp com clientes de um provedor de internet (ISP). "
    "Sua função é dar 1 (uma) dica curta e acionável ao atendente, em "
    "português brasileiro, no estilo cartão de cola. NUNCA fale com o "
    "cliente — só com o atendente. Seja específico e objetivo.\n\n"
    "FORMATO OBRIGATÓRIO (≤ 4 linhas, ≤ 280 chars):\n"
    "• Intenção: <2-4 palavras (ex: pedido de desconto, problema técnico, "
    "cancelamento, dúvida fatura, etc)>\n"
    "• Sentimento: <calmo | neutro | preocupado | irritado | frustrado>\n"
    "• Sugestão: <ação concreta e específica, 1 frase>\n"
    "• Atenção: <opcional — risco/oportunidade que o atendente pode não ter visto>\n\n"
    "REGRAS:\n"
    "- NÃO repita o que o cliente disse. NÃO escreva resposta pronta pro cliente.\n"
    "- Se houver pane confirmada no contexto, lembre o atendente para mencionar isso.\n"
    "- Se cliente está irritado, sugira tom de empatia + dado concreto.\n"
    "- Se cliente fez pergunta técnica, sugira o que validar primeiro (sinal, fatura, plano).\n"
    "- NÃO use emojis. NÃO use markdown. Texto puro."
)


async def _conversation_context(company_id: str, phone: str,
                                  subscriber_ctx: Optional[str] = None,
                                  outage_ctx: Optional[str] = None) -> str:
    """Monta contexto textual: perfil + outage + últimas N mensagens."""
    parts: List[str] = []
    if subscriber_ctx:
        parts.append(f"PERFIL CLIENTE: {subscriber_ctx}")
    if outage_ctx:
        parts.append(f"PANE ATIVA NA REGIÃO: {outage_ctx}")
    # Histórico curto — exclui notas internas (não interessa ao copilot)
    msgs = await db.aihub_wa_messages.find(
        {"company_id": company_id, "phone": phone,
         "direction": {"$ne": "internal"}},
        {"_id": 0, "direction": 1, "text": 1, "auto_reply": 1},
    ).sort("created_at", -1).limit(HIST_LIMIT).to_list(HIST_LIMIT)
    msgs.reverse()
    if msgs:
        lines = ["HISTÓRICO RECENTE (mais antiga primeiro):"]
        for m in msgs:
            d = m.get("direction")
            tag = "CLIENTE" if d == "inbound" else (
                "IA" if m.get("auto_reply") else "ATENDENTE")
            txt = (m.get("text") or "").strip().replace("\n", " ")
            if len(txt) > 240:
                txt = txt[:237] + "…"
            lines.append(f"[{tag}] {txt}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


async def _outage_context_for(company_id: str, phone: str) -> Optional[str]:
    try:
        from services.smartolt_ai import get_outage_for_phone
        o = await get_outage_for_phone(company_id, phone)
        if o:
            return (f"OLT {o.get('olt_name')} placa {o.get('board')} "
                    f"porta {o.get('port')} · {o.get('los_count')}/"
                    f"{o.get('total_count')} ONUs em LOS ({o.get('severity_pct')}%)")
    except Exception:
        pass
    return None


async def maybe_insert_copilot_hint(*, company_id: str, phone: str,
                                       last_inbound_text: str,
                                       last_inbound_id: Optional[str],
                                       subscriber_ctx: Optional[str] = None) -> Optional[str]:
    """Tenta gerar e inserir uma dica do Co-Pilot. Retorna o texto inserido
    ou None (se pulado por qualquer motivo).
    """
    if not last_inbound_text or len(last_inbound_text.strip()) < MIN_INBOUND_CHARS:
        return None

    # Dedup — já tem dica do co-pilot pra esta msg_id?
    if last_inbound_id:
        existing = await db.aihub_wa_messages.find_one(
            {"company_id": company_id, "phone": phone,
             "direction": "internal", "internal_kind": "copilot_hint",
             "trigger_message_id": last_inbound_id},
            {"_id": 0, "id": 1},
        )
        if existing:
            return None

    outage_ctx = await _outage_context_for(company_id, phone)
    ctx_text = await _conversation_context(company_id, phone,
                                              subscriber_ctx, outage_ctx)
    user_prompt = (
        f"{ctx_text}\n\n"
        f"ÚLTIMA MENSAGEM DO CLIENTE (a que o atendente precisa responder agora):\n"
        f"\"{last_inbound_text.strip()}\"\n\n"
        "Gere a dica no formato exigido."
    )

    try:
        from services.motor_ia import chat_completion
    except ImportError:
        return None

    try:
        result = await chat_completion(
            company_id,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            max_tokens=180,
            purpose="copilot",
        )
        hint = (result.get("content") or "").strip()
    except Exception as e:
        logger.info("[copilot-ai] LLM falhou (silencioso): %s", e)
        return None

    if not hint:
        return None
    # Sanitização defensiva: remove markdown stars e limita tamanho
    hint = re.sub(r"\*+", "", hint).strip()
    if len(hint) > MAX_HINT_CHARS:
        hint = hint[:MAX_HINT_CHARS - 1].rstrip() + "…"

    await db.aihub_wa_messages.insert_one({
        "id": f"wam-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "direction": "internal",        # NUNCA enviado via Baileys
        "internal_kind": "copilot_hint",  # tipo específico p/ UI roxa
        "phone": phone,
        "text": hint,
        "trigger_message_id": last_inbound_id,
        "auto_reply": True,
        "created_at": now_iso(),
        "is_internal_note": True,
        "visible_to_client": False,
        "source_model": result.get("model"),
    })
    logger.info("[copilot-ai] hint inserida para %s: %s", phone, hint[:80])
    return hint


async def count_hints_24h(company_id: str) -> int:
    """Conta dicas geradas nas últimas 24h (pro fluxograma)."""
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    return await db.aihub_wa_messages.count_documents({
        "company_id": company_id,
        "direction": "internal",
        "internal_kind": "copilot_hint",
        "created_at": {"$gte": cutoff},
    })


async def hints_per_user_24h(company_id: str) -> Dict[str, int]:
    """Dicas direcionadas a cada atendente humano nas últimas 24h.

    Como atribuímos a dica? Pela `assignee_user_id` da conversa no momento
    da inserção. Se conversa não tinha humano atribuído, conta como "none".
    """
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    # Phones que receberam hints
    phones: List[str] = await db.aihub_wa_messages.distinct(
        "phone",
        {"company_id": company_id, "direction": "internal",
         "internal_kind": "copilot_hint",
         "created_at": {"$gte": cutoff}},
    )
    if not phones:
        return {}
    counts: Dict[str, int] = {}
    async for c in db.wa_conversations.find(
        {"company_id": company_id, "phone": {"$in": phones},
         "assignee_user_id": {"$nin": [None, ""]}},
        {"_id": 0, "phone": 1, "assignee_user_id": 1},
    ):
        uid = c.get("assignee_user_id")
        ph = c.get("phone")
        # Conta quantos hints aquele phone teve
        n = await db.aihub_wa_messages.count_documents({
            "company_id": company_id, "phone": ph,
            "direction": "internal", "internal_kind": "copilot_hint",
            "created_at": {"$gte": cutoff},
        })
        counts[uid] = counts.get(uid, 0) + n
    return counts
