"""Isabella V14 — Oráculo de Memória Relacional.

Sistema de memória de ACONTECIMENTOS (não apenas mensagens) que faz a
Isabella parecer uma pessoa que acompanha a história do cliente.

ESTRATÉGIA DE EXTRAÇÃO (CTO 18/02/2026):
  Nível 1 — Regex/heurística (sempre): cobre ~70% dos casos de memória
            pessoal (prova, aniversário, viagem, casamento, mudança,
            empresa, filho/filha, cirurgia, vestibular, concurso).
            Custo: zero.
  Nível 2 — Claude Sonnet 4.5 via Emergent Key: roda APENAS quando o
            Nível 1 detecta `possible_memory == true` mas confidence
            < 0.80. Cobre os 30% sutis. Custo amortizado: ~$0.0003/msg.

3 COLLECTIONS (decisão CTO — não 1 collection genérica):
  • `customer_memory`   — acontecimentos relevantes (memórias)
  • `customer_promises` — promessas da Isabella com follow-up
  • `customer_timeline` — log cronológico de tudo (matéria-prima para
                              Watchtower Relacionamento, score de
                              relacionamento, churn emocional)

TTL POR TIPO:
  • TECNICA   → 30d
  • COMERCIAL → 90d
  • PESSOAL   → 180d
  • PROMESSA  → até resolução (sem TTL automático)
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from database import db

logger = logging.getLogger("ponto.customer_memory")

MEMORY_COLL = "customer_memory"
PROMISES_COLL = "customer_promises"
TIMELINE_COLL = "customer_timeline"

# ─── Tipos de memória ───────────────────────────────────────────
TYPE_TECNICA = "TECNICA"
TYPE_COMERCIAL = "COMERCIAL"
TYPE_FINANCEIRA = "FINANCEIRA"
TYPE_PESSOAL = "PESSOAL"

TTL_DAYS_BY_TYPE = {
    TYPE_TECNICA: 30,
    TYPE_FINANCEIRA: 30,
    TYPE_COMERCIAL: 90,
    TYPE_PESSOAL: 180,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── Indexes ────────────────────────────────────────────────────
async def ensure_indexes() -> None:
    try:
        await db[MEMORY_COLL].create_index(
            [("company_id", 1), ("phone", 1), ("memory_type", 1)],
            name="cid_phone_type_idx",
        )
        await db[MEMORY_COLL].create_index(
            [("company_id", 1), ("phone", 1), ("created_at", -1)],
            name="cid_phone_recency_idx",
        )
        await db[MEMORY_COLL].create_index(
            "expires_at", expireAfterSeconds=0, name="mem_ttl",
        )

        await db[PROMISES_COLL].create_index(
            [("company_id", 1), ("phone", 1), ("status", 1)],
            name="prom_cid_phone_st_idx",
        )
        await db[PROMISES_COLL].create_index(
            [("company_id", 1), ("status", 1), ("due_at", 1)],
            name="prom_due_idx",
        )

        await db[TIMELINE_COLL].create_index(
            [("company_id", 1), ("phone", 1), ("ts", -1)],
            name="tl_cid_phone_ts_idx",
        )
        # TIMELINE: TTL 365d (1 ano de história)
        await db[TIMELINE_COLL].create_index(
            "ts", expireAfterSeconds=365 * 86400, name="tl_ttl",
        )
    except Exception as e:
        logger.warning("[customer_memory] indexes: %s", e)


# ─── NÍVEL 1: Extração por regex/heurística ─────────────────────
# Cada padrão devolve (title, description, confidence)

PESSOAL_PATTERNS: List[Tuple[re.Pattern, str, float]] = [
    (re.compile(r"\b(min(ha)?|nosso?|m[eu])\s+filh[oa]\b.{0,40}?\b(prova|vestibular|enem|concurso|formatura|aniversari)\b",
                re.IGNORECASE),
     "filho/filha com evento acadêmico/pessoal", 0.85),
    (re.compile(r"\bvou\s+(viajar|sair\s+de\s+f[ée]rias|para\s+[A-ZÀ-Ý][a-zà-ý]+)\b",
                re.IGNORECASE),
     "vai viajar / férias", 0.82),
    (re.compile(r"\b(meu?|nosso?)\s+(anivers[áa]rio|casamento|noivado|formatura)\b",
                re.IGNORECASE),
     "evento pessoal (aniversário/casamento/noivado/formatura)", 0.88),
    (re.compile(r"\b(vou|estou|fiz)\s+(uma\s+)?cirurgi", re.IGNORECASE),
     "cirurgia", 0.90),
    (re.compile(r"\b(mudei|me\s+mudei|mudan[çc]a)\s+(de\s+endere[çc]o|de\s+casa|pra)\b",
                re.IGNORECASE),
     "mudança de endereço", 0.85),
    (re.compile(r"\b(abri|montei|criei|comecei)\s+(uma\s+)?(empresa|loja|neg[óo]cio|clinica)\b",
                re.IGNORECASE),
     "abriu empresa/negócio", 0.85),
    (re.compile(r"\b(meu\s+|minha\s+)?(esposa|marido|filh[oa]|m[ãa]e|pai|irm[ãa]o|av[óo])\s+(faleceu|morreu|t[áa]\s+doente)\b",
                re.IGNORECASE),
     "evento sensível familiar", 0.95),
]

COMERCIAL_PATTERNS: List[Tuple[re.Pattern, str, float]] = [
    (re.compile(r"\b(quero|gostaria de|tenho interesse em)\s+(upgrade|trocar de plano|aumentar|migrar)\b",
                re.IGNORECASE),
     "interesse em upgrade", 0.80),
    (re.compile(r"\b(link\s+dedicado|empresarial|pj|plano\s+pj)\b",
                re.IGNORECASE),
     "interesse em produto PJ / Link Dedicado", 0.78),
    (re.compile(r"\bligo\s*(tv|m[óo]vel|security)\b", re.IGNORECASE),
     "interesse em produto Universo Ligo", 0.78),
    (re.compile(r"\b(me\s+manda|envia|gostaria de uma?)\s+proposta\b",
                re.IGNORECASE),
     "solicitou proposta", 0.85),
    (re.compile(r"\b(d[áa]\s+pra\s+fazer\s+um\s+)?desconto\b", re.IGNORECASE),
     "solicitou desconto", 0.75),
]

FINANCEIRA_PATTERNS: List[Tuple[re.Pattern, str, float]] = [
    (re.compile(r"\b(vou\s+pagar|prometo\s+pagar|pago\s+at[ée])\b", re.IGNORECASE),
     "promessa de pagamento", 0.80),
    (re.compile(r"\b(combinamos|fizemos|fechamos)\s+(um\s+)?acordo\b", re.IGNORECASE),
     "acordo financeiro realizado", 0.85),
    (re.compile(r"\b(contesto|n[ãa]o\s+reconhe[çc]o|cobran[çc]a\s+indevida)\b",
                re.IGNORECASE),
     "contestação financeira", 0.82),
]

TECNICA_PATTERNS: List[Tuple[re.Pattern, str, float]] = [
    (re.compile(r"\b(trocaram?|troquei|trocou)\s+(a\s+|o\s+)?(onu|roteador|equipamento)\b",
                re.IGNORECASE),
     "troca de equipamento (ONU/roteador)", 0.80),
    (re.compile(r"\b(instala[çc][ãa]o|instalei|instalaram)\s+(recente|nova|essa\s+semana|hoje)\b",
                re.IGNORECASE),
     "instalação recente", 0.78),
]


def extract_memory_l1(user_text: str) -> Optional[Dict[str, Any]]:
    """Nível 1: regex/heurística. Devolve memória se houver match.

    Devolve None se nada relevante.
    Devolve dict com possible_memory=True e confidence baixa se o texto
    é SUSPEITO mas o regex não capturou exatamente — sinaliza ao Nível 2.
    """
    if not user_text or len(user_text.strip()) < 5:
        return None
    text = user_text.strip()

    # Pessoal (prioridade — mais relevante para o oráculo)
    for pat, title, conf in PESSOAL_PATTERNS:
        if pat.search(text):
            return {
                "memory_type": TYPE_PESSOAL,
                "title": title,
                "description": text[:300],
                "confidence": conf,
                "source": "regex_l1",
            }
    for pat, title, conf in COMERCIAL_PATTERNS:
        if pat.search(text):
            return {
                "memory_type": TYPE_COMERCIAL,
                "title": title,
                "description": text[:300],
                "confidence": conf,
                "source": "regex_l1",
            }
    for pat, title, conf in FINANCEIRA_PATTERNS:
        if pat.search(text):
            return {
                "memory_type": TYPE_FINANCEIRA,
                "title": title,
                "description": text[:300],
                "confidence": conf,
                "source": "regex_l1",
            }
    for pat, title, conf in TECNICA_PATTERNS:
        if pat.search(text):
            return {
                "memory_type": TYPE_TECNICA,
                "title": title,
                "description": text[:300],
                "confidence": conf,
                "source": "regex_l1",
            }

    # Sinal de "talvez tem memória" — texto longo com primeira pessoa +
    # tempo futuro/passado pessoal. Disparar Nível 2.
    if (len(text) > 50
            and re.search(r"\b(eu|meu|minha|gente|nosso)\b", text, re.IGNORECASE)
            and re.search(r"\b(vou|vai|fui|estava|fiz|tenho|vamos|amanh[ãa]|"
                            r"semana\s+que\s+vem|m[êe]s\s+que\s+vem)\b",
                            text, re.IGNORECASE)):
        return {
            "possible_memory": True,
            "confidence": 0.40,
            "source": "regex_l1_hint",
        }
    return None


# ─── NÍVEL 2: Claude Sonnet 4.5 (somente se Nível 1 sinalizar) ───
async def extract_memory_l2(user_text: str) -> Optional[Dict[str, Any]]:
    """Nível 2: Claude Sonnet 4.5 via Emergent Key.

    Roda APENAS quando L1 marca `possible_memory=True`. Retorna estrutura
    completa de memória, ou None se Claude decidir que não é relevante.
    """
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        import os
        api_key = os.environ.get("EMERGENT_LLM_KEY")
        if not api_key:
            logger.info("[customer_memory] L2 sem EMERGENT_LLM_KEY — skip")
            return None

        system_prompt = (
            "Você é um classificador de relevância de memórias para uma "
            "Customer Success AI de telecom (ISP). Recebe a mensagem de um "
            "cliente e decide se há um ACONTECIMENTO relevante para "
            "lembrar em conversas futuras.\n\n"
            "TIPOS DE MEMÓRIA: PESSOAL, COMERCIAL, FINANCEIRA, TECNICA.\n\n"
            "REGRA: \"Nossa internet caiu\" NÃO é memória (é problema "
            "operacional). \"Minha filha vai fazer prova amanhã\" É "
            "memória (PESSOAL).\n\n"
            "Responda APENAS em JSON válido neste formato:\n"
            "{\"is_memory\": true|false, \"memory_type\": \"PESSOAL|"
            "COMERCIAL|FINANCEIRA|TECNICA\", \"title\": \"breve título "
            "humano em pt-BR (até 60 chars)\", \"description\": \"resumo "
            "em 1 frase pt-BR (até 200 chars)\", \"confidence\": 0.0-1.0}"
            "\nSe is_memory=false, devolva apenas {\"is_memory\": false}."
        )
        chat = LlmChat(
            api_key=api_key,
            session_id=f"memory-l2-{uuid.uuid4().hex[:8]}",
            system_message=system_prompt,
        ).with_model("anthropic", "claude-sonnet-4-5-20250929")
        resp = await chat.send_message(UserMessage(text=user_text[:800]))
        import json
        # Sanity: extrai JSON do response
        text = (resp or "").strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group(0))
        if not data.get("is_memory"):
            return None
        return {
            "memory_type": data.get("memory_type") or TYPE_PESSOAL,
            "title": (data.get("title") or "")[:80],
            "description": (data.get("description") or "")[:300],
            "confidence": float(data.get("confidence") or 0.7),
            "source": "claude_l2",
        }
    except Exception as e:
        logger.info("[customer_memory] L2 falhou: %s", e)
        return None


# ─── Persistência ──────────────────────────────────────────────
async def save_memory(
    *,
    company_id: str,
    phone: str,
    subscriber_id: Optional[str],
    memory_type: str,
    title: str,
    description: str,
    confidence: float,
    source: str = "regex_l1",
    source_msg_id: Optional[str] = None,
) -> str:
    """Persiste uma memória. Dedup leve: se já existe memória do mesmo
    tipo+título nas últimas 24h, apenas atualiza last_used_at."""
    now = _now()
    ttl_days = TTL_DAYS_BY_TYPE.get(memory_type, 90)
    expires_at = now + timedelta(days=ttl_days)
    # Dedup: mesmo phone + type + title em 24h
    cutoff_24h = now - timedelta(hours=24)
    existing = await db[MEMORY_COLL].find_one({
        "company_id": company_id, "phone": phone,
        "memory_type": memory_type, "title": title,
        "created_at": {"$gte": cutoff_24h},
    })
    if existing:
        await db[MEMORY_COLL].update_one(
            {"_id": existing["_id"]},
            {"$set": {"last_used_at": now, "description": description},
             "$inc": {"hit_count": 1}},
        )
        return existing["_id"]
    mid = f"mem-{uuid.uuid4().hex[:12]}"
    await db[MEMORY_COLL].insert_one({
        "_id": mid,
        "company_id": company_id,
        "phone": phone,
        "subscriber_id": subscriber_id,
        "memory_type": memory_type,
        "title": title,
        "description": description,
        "confidence": confidence,
        "source": source,
        "source_msg_id": source_msg_id,
        "created_at": now,
        "expires_at": expires_at,
        "last_used_at": None,
        "follow_up_required": memory_type == TYPE_PESSOAL and confidence >= 0.80,
        "hit_count": 0,
    })
    await _log_timeline(company_id=company_id, phone=phone,
                          subscriber_id=subscriber_id,
                          kind="memory_created",
                          payload={"memory_id": mid, "type": memory_type,
                                     "title": title})
    return mid


async def _log_timeline(
    *, company_id: str, phone: str,
    subscriber_id: Optional[str],
    kind: str, payload: Dict[str, Any],
) -> None:
    try:
        await db[TIMELINE_COLL].insert_one({
            "_id": f"tl-{uuid.uuid4().hex[:14]}",
            "company_id": company_id,
            "phone": phone,
            "subscriber_id": subscriber_id,
            "kind": kind,
            "payload": payload,
            "ts": _now(),
        })
    except Exception as e:
        logger.debug("[customer_memory] timeline log skip: %s", e)


# ─── Pipeline principal: chamado após cada inbound ──────────────
async def capture_from_inbound(
    *,
    company_id: str,
    phone: str,
    subscriber_id: Optional[str],
    user_text: str,
    source_msg_id: Optional[str] = None,
) -> Optional[str]:
    """Pipeline completo de extração:
      1) Tenta Nível 1 (regex).
      2) Se L1 retornou memória sólida → persiste.
      3) Se L1 marcou possible_memory → chama L2 (Claude).
      4) Persiste timeline event sempre (inbound recebido).
    """
    await _log_timeline(company_id=company_id, phone=phone,
                          subscriber_id=subscriber_id,
                          kind="inbound",
                          payload={"text": (user_text or "")[:200],
                                     "source_msg_id": source_msg_id})

    l1 = extract_memory_l1(user_text)
    if not l1:
        return None

    if l1.get("possible_memory") and not l1.get("memory_type"):
        # Sobe pra L2
        l2 = await extract_memory_l2(user_text)
        if not l2:
            return None
        return await save_memory(
            company_id=company_id, phone=phone,
            subscriber_id=subscriber_id,
            memory_type=l2["memory_type"], title=l2["title"],
            description=l2["description"], confidence=l2["confidence"],
            source=l2["source"], source_msg_id=source_msg_id,
        )

    # L1 captura direta
    return await save_memory(
        company_id=company_id, phone=phone,
        subscriber_id=subscriber_id,
        memory_type=l1["memory_type"], title=l1["title"],
        description=l1["description"], confidence=l1["confidence"],
        source=l1["source"], source_msg_id=source_msg_id,
    )


# ─── Promessas — captura de outbound (Isabella prometeu algo) ───
PROMISE_PATTERNS = [
    re.compile(r"\bvou\s+(verificar|checar|olhar|conferir|ver|consultar)\b",
                re.IGNORECASE),
    re.compile(r"\bdeixa\s+(eu\s+|que\s+eu\s+)?(verifico|cheko|confiro|olho)\b",
                re.IGNORECASE),
    re.compile(r"\b(te\s+)?retorno\s+(em\s+breve|j[áa]|assim\s+que|logo)\b",
                re.IGNORECASE),
    re.compile(r"\bvou\s+(passar|encaminhar|abrir\s+chamado|solicitar)\b",
                re.IGNORECASE),
    re.compile(r"\baguarda\s+(um\s+)?(instante|momento|minuto)\b", re.IGNORECASE),
]


def detect_promise(reply_text: str) -> Optional[str]:
    """Detecta se Isabella fez uma promessa. Devolve o trecho da promessa."""
    if not reply_text:
        return None
    for pat in PROMISE_PATTERNS:
        m = pat.search(reply_text)
        if m:
            # Captura a frase inteira que contém o match
            start = max(0, reply_text.rfind(".", 0, m.start()) + 1)
            end = reply_text.find(".", m.end())
            end = end if end > 0 else len(reply_text)
            return reply_text[start:end].strip()[:200]
    return None


async def register_promise(
    *,
    company_id: str,
    phone: str,
    subscriber_id: Optional[str],
    promise_text: str,
    context_user_text: str = "",
) -> str:
    """Registra promessa aberta. Será usada na próxima conversa."""
    pid = f"prom-{uuid.uuid4().hex[:12]}"
    now = _now()
    await db[PROMISES_COLL].insert_one({
        "_id": pid,
        "company_id": company_id,
        "phone": phone,
        "subscriber_id": subscriber_id,
        "promise_text": promise_text[:300],
        "context_user_text": context_user_text[:200],
        "status": "pending",
        "created_at": now,
        "due_at": now + timedelta(hours=24),
        "resolved_at": None,
    })
    await _log_timeline(company_id=company_id, phone=phone,
                          subscriber_id=subscriber_id,
                          kind="promise_made",
                          payload={"promise_id": pid,
                                     "text": promise_text[:120]})
    return pid


async def list_open_promises(*, company_id: str, phone: str,
                                  limit: int = 3) -> List[Dict[str, Any]]:
    cursor = db[PROMISES_COLL].find(
        {"company_id": company_id, "phone": phone, "status": "pending"},
        {"_id": 1, "promise_text": 1, "created_at": 1,
         "context_user_text": 1},
    ).sort("created_at", -1).limit(limit)
    return await cursor.to_list(limit)


async def resolve_promise(*, promise_id: str) -> None:
    await db[PROMISES_COLL].update_one(
        {"_id": promise_id},
        {"$set": {"status": "resolved", "resolved_at": _now()}},
    )


# ─── Memory Block — injeção no system prompt ───────────────────
async def build_memory_oracle_block(
    *, company_id: str, phone: str,
    subscriber_id: Optional[str] = None,
) -> str:
    """Bloco compacto para system prompt da Isabella V14.

    Prioridade (regra de abertura — máx 2 referências):
      1. Promessas abertas (sempre topo)
      2. 1 memória pessoal recente (se houver)
      3. Última memória comercial em curso (se sem pessoal)

    Devolve string vazia se cliente é novo — evita poluir prompt.
    """
    parts: List[str] = []
    try:
        # 1. Promessas
        promises = await list_open_promises(company_id=company_id,
                                                phone=phone, limit=2)
        if promises:
            for p in promises:
                parts.append(
                    "PROMESSA EM ABERTO: você disse «"
                    f"{p['promise_text']}». Mencione isso logo no início, "
                    "sem o cliente precisar pedir. "
                    "(\"Sobre o que eu havia ficado de verificar...\")"
                )
                # Marca uso
                await _log_timeline(
                    company_id=company_id, phone=phone,
                    subscriber_id=subscriber_id,
                    kind="promise_recalled",
                    payload={"promise_id": p["_id"]})

        # 2. Memórias por prioridade (PESSOAL → COMERCIAL → outras)
        pessoal = await db[MEMORY_COLL].find_one(
            {"company_id": company_id, "phone": phone,
             "memory_type": TYPE_PESSOAL,
             "expires_at": {"$gte": _now()}},
            sort=[("created_at", -1)],
        )
        comercial = None
        if not pessoal:
            comercial = await db[MEMORY_COLL].find_one(
                {"company_id": company_id, "phone": phone,
                 "memory_type": TYPE_COMERCIAL,
                 "expires_at": {"$gte": _now()}},
                sort=[("created_at", -1)],
            )

        chosen = pessoal or comercial
        if chosen:
            created = chosen["created_at"]
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            days_ago = (_now() - created).days
            when = ("hoje" if days_ago == 0 else
                    "ontem" if days_ago == 1 else
                    f"há {days_ago} dias")
            parts.append(
                f"MEMÓRIA RELACIONAL ({chosen['memory_type'].lower()}, "
                f"{when}): {chosen['title']}. "
                f"O cliente comentou: «{chosen['description'][:160]}». "
                "Se fizer sentido na abertura, mencione com naturalidade "
                "(\"vi aqui que...\", \"você comentou comigo que...\"). "
                "NUNCA diga \"identifiquei em meu banco de dados\"."
            )
            await db[MEMORY_COLL].update_one(
                {"_id": chosen["_id"]},
                {"$set": {"last_used_at": _now()},
                 "$inc": {"hit_count": 1}},
            )
    except Exception as e:
        logger.info("[customer_memory] block skip: %s", e)

    if not parts:
        return ""

    return (
        "=== ORÁCULO DE MEMÓRIA RELACIONAL (Isabella V14) ===\n"
        + "\n".join("• " + p for p in parts)
        + "\n\nREGRA: máximo 2 referências na abertura. Soe natural, "
          "como alguém da equipe da Ligo que acompanha o cliente — "
          "nunca como um CRM."
    )


# ═══════════════════════════════════════════════════════════════
# V15 — ORÁCULO RELACIONAL ABSOLUTO
# Adiciona: Prioridade 2 (problemas recentes), Prioridade 4 (VIP),
#           Regra de Afirmações (evidências auditáveis).
# ═══════════════════════════════════════════════════════════════

async def _recent_problems_block(
    *, company_id: str, subscriber_id: Optional[str],
) -> Optional[str]:
    """Prioridade 2 — Reparos/instalações/mudanças/financeiro recente.

    Lê `tickets` (últimos 30d) e `executive_ledger` (financeiro).
    Devolve string curta para Isabella mencionar com naturalidade.
    """
    if not subscriber_id:
        return None
    try:
        cutoff_iso = (_now() - timedelta(days=30)).isoformat()
        # Reparo aberto (prioridade máxima dentro de Problemas)
        open_tk = await db.tickets.find_one(
            {"company_id": company_id, "client_id": subscriber_id,
             "status": {"$in": ["aberta", "pendente",
                                   "open", "in_progress", "scheduled"]}},
            {"_id": 0, "id": 1, "type": 1, "status": 1, "created_at": 1,
             "scheduled_time": 1, "atlaz_assunto": 1},
            sort=[("created_at", -1)],
        )
        if open_tk:
            typ = open_tk.get("atlaz_assunto") or open_tk.get("type") or "OS"
            sched = open_tk.get("scheduled_time") or ""
            when = f"agendada para {sched[:10]}" if sched else "em andamento"
            return (f"REPARO/OS EM ABERTO: {typ} ({when}). "
                    "Demonstre que sabe da situação antes do cliente falar. "
                    "Ex.: «vi que estamos acompanhando seu chamado, "
                    "queria saber se a equipe já passou aí».")

        # Reparo encerrado recente (≤ 7 dias) → follow-up natural
        cutoff_7d_iso = (_now() - timedelta(days=7)).isoformat()
        closed_tk = await db.tickets.find_one(
            {"company_id": company_id, "client_id": subscriber_id,
             "status": {"$in": ["encerrada", "finalizada", "closed"]},
             "closed_at": {"$gte": cutoff_7d_iso}},
            {"_id": 0, "id": 1, "type": 1, "closed_at": 1,
             "outcome": 1, "atlaz_assunto": 1},
            sort=[("closed_at", -1)],
        )
        if closed_tk:
            typ = closed_tk.get("atlaz_assunto") or closed_tk.get("type") or "OS"
            return (f"REPARO RECENTE ENCERRADO: {typ}. Faça follow-up "
                    "natural na abertura. Ex.: «vi que tivemos um "
                    "reparo aí recentemente, ficou tudo certo depois "
                    "da visita?»")

        # Histórico financeiro: ledger 30d
        ledger = await db.executive_ledger.find_one(
            {"company_id": company_id, "subscriber_id": subscriber_id,
             "created_at": {"$gte": cutoff_iso},
             "category": {"$in": ["financeiro", "cobranca", "negociacao"]}},
            {"_id": 0, "kind": 1, "created_at": 1, "actual_BRL": 1},
            sort=[("created_at", -1)],
        )
        if ledger:
            kind = ledger.get("kind") or "evento"
            return (f"FINANCEIRO RECENTE: {kind}. Se o cliente tocar "
                    "no assunto, use o histórico para personalizar.")
    except Exception as e:
        logger.info("[v15] recent_problems_block skip: %s", e)
    return None


async def _vip_block(
    *, company_id: str, subscriber_id: Optional[str],
) -> Optional[str]:
    """Prioridade 4 — Reconhecimento de cliente VIP / histórico.

    Critérios (cada um soma pontos; >= 2 pontos = VIP):
      • Tempo de casa >= 3 anos
      • Cliente PJ / empresarial
      • Indicou >= 1 amigo (referral_code presente em outro subscriber)
      • Plano premium (>= R$ 150/mês)
      • Zero inadimplência registrada nos últimos 12 meses
    """
    if not subscriber_id:
        return None
    try:
        sub = await db.subscribers.find_one(
            {"company_id": company_id, "id": subscriber_id},
            {"_id": 0, "name": 1, "activation_date": 1, "plan_price": 1,
             "plan_name": 1, "tags": 1, "referral_code": 1,
             "contract_status": 1},
        )
        if not sub:
            return None

        score = 0
        signals: List[str] = []

        # Tempo de casa
        activation = sub.get("activation_date")
        years_with_us = 0.0
        if activation:
            try:
                dt = (datetime.fromisoformat(activation.replace("Z", "+00:00"))
                      if isinstance(activation, str) else activation)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                years_with_us = (_now() - dt).days / 365.25
                if years_with_us >= 3:
                    score += 2
                    signals.append(
                        f"está conosco há {years_with_us:.1f} anos")
                elif years_with_us >= 1:
                    score += 1
                    signals.append(
                        f"está conosco há {years_with_us:.1f} anos")
            except Exception:
                pass

        # PJ / empresarial
        tags = sub.get("tags") or []
        plan_name = (sub.get("plan_name") or "").lower()
        if any("empresa" in (t or "").lower() or "pj" in (t or "").lower()
                for t in tags) or "pj" in plan_name or "dedicado" in plan_name:
            score += 2
            signals.append("conta empresarial / PJ")

        # Indicações (referral_code do sub aparece em outros subscribers)
        ref = sub.get("referral_code")
        if ref:
            n_ref = await db.subscribers.count_documents(
                {"company_id": company_id, "metadata.referred_by": ref})
            if n_ref >= 1:
                score += 2
                signals.append(f"indicou {n_ref} amigo(s)")

        # Plano premium
        price = sub.get("plan_price") or 0
        try:
            price_f = float(price)
        except (TypeError, ValueError):
            price_f = 0.0
        if price_f >= 250:
            score += 2
            signals.append(f"plano premium (R$ {price_f:.0f}/mês)")
        elif price_f >= 150:
            score += 1
            signals.append(f"plano de R$ {price_f:.0f}/mês")

        if score < 2:
            return None

        signals_str = " e ".join(signals[:2])
        return (
            f"CLIENTE VIP (score={score}): {signals_str}. "
            "Reconheça a relação histórica com naturalidade e SEM "
            "bajulação. Ex.: «você já está conosco há um tempo, "
            "obrigada pela confiança» — apenas uma vez, sem repetir."
        )
    except Exception as e:
        logger.info("[v15] vip_block skip: %s", e)
        return None


async def _evidence_block(
    *, company_id: str, subscriber_id: Optional[str],
) -> Optional[str]:
    """Regra de Afirmações — Evidências auditáveis disponíveis.

    Lê `isabella_factual_claims` com `audit_passed=True` cuja
    `audited_at + ttl_minutes >= now` e `consumed_by` ainda NULL.
    Injeta no prompt como fonte única para afirmações factuais.
    """
    if not subscriber_id:
        return None
    try:
        now = _now()
        cursor = db.isabella_factual_claims.find(
            {"company_id": company_id, "entity_id": subscriber_id,
             "audit_passed": True, "consumed_by": None},
            {"_id": 0, "id": 1, "domain": 1, "evidence": 1,
             "audited_at": 1, "ttl_minutes": 1},
        ).sort("audited_at", -1).limit(5)
        rows = await cursor.to_list(5)
        valid: List[Dict[str, Any]] = []
        for r in rows:
            try:
                aud = r.get("audited_at")
                dt = (datetime.fromisoformat(aud.replace("Z", "+00:00"))
                      if isinstance(aud, str) else aud)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                ttl = int(r.get("ttl_minutes") or 30)
                if dt + timedelta(minutes=ttl) >= now:
                    valid.append(r)
            except Exception:
                continue
        if not valid:
            return None

        lines = ["EVIDÊNCIAS AUDITADAS DISPONÍVEIS (use SOMENTE estas "
                 "para afirmações factuais):"]
        for v in valid[:3]:
            ev_compact = ", ".join(
                f"{k}={str(val)[:60]}"
                for k, val in (v.get("evidence") or {}).items()
                if val is not None
            )[:280]
            lines.append(
                f"  • [{v['domain']}] evidence_id={v['id']}: {ev_compact}"
            )
        lines.append(
            "REGRA DURA: qualquer afirmação técnica/financeira/cadastro "
            "DEVE vir destas evidências. Se o cliente perguntar algo "
            "que NÃO está aqui, responda «deixa eu confirmar isso para "
            "você» — NUNCA invente."
        )
        return "\n".join(lines)
    except Exception as e:
        logger.info("[v15] evidence_block skip: %s", e)
        return None


async def build_v15_oracle_block(
    *,
    company_id: str,
    phone: str,
    subscriber_id: Optional[str] = None,
) -> str:
    """V15 — Oráculo Relacional Absoluto.

    Orquestra TODAS as 4 prioridades respeitando o limite de 2
    referências naturais na abertura:

      1. Promessas abertas
      2. Problemas técnicos/financeiros recentes
      3. Memória pessoal recente
      4. VIP / histórico de relacionamento

    Sempre injeta o bloco de Evidências Auditadas (Regra de Afirmações).

    Devolve string vazia se cliente é novo e sem evidências.
    """
    references: List[Tuple[int, str]] = []  # (priority, text)
    extra_blocks: List[str] = []

    try:
        # Prioridade 1: Promessas
        promises = await list_open_promises(
            company_id=company_id, phone=phone, limit=1,
        )
        if promises:
            p = promises[0]
            references.append((1,
                f"PROMESSA EM ABERTO (P1): você disse «{p['promise_text']}». "
                "Comece a conversa por aqui antes do cliente cobrar. "
                "Ex.: «sobre o que eu havia ficado de verificar...»"))
            try:
                await _log_timeline(
                    company_id=company_id, phone=phone,
                    subscriber_id=subscriber_id,
                    kind="promise_recalled",
                    payload={"promise_id": p["_id"]})
            except Exception:
                pass

        # Prioridade 2: Problemas recentes (técnico/financeiro)
        probs = await _recent_problems_block(
            company_id=company_id, subscriber_id=subscriber_id,
        )
        if probs:
            references.append((2, probs))

        # Prioridade 3: Memória pessoal (depois comercial)
        pessoal = await db[MEMORY_COLL].find_one(
            {"company_id": company_id, "phone": phone,
             "memory_type": TYPE_PESSOAL,
             "expires_at": {"$gte": _now()}},
            sort=[("created_at", -1)],
        )
        comercial = None
        if not pessoal:
            comercial = await db[MEMORY_COLL].find_one(
                {"company_id": company_id, "phone": phone,
                 "memory_type": TYPE_COMERCIAL,
                 "expires_at": {"$gte": _now()}},
                sort=[("created_at", -1)],
            )
        chosen_mem = pessoal or comercial
        if chosen_mem:
            created = chosen_mem["created_at"]
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            days_ago = (_now() - created).days
            when = ("hoje" if days_ago == 0 else
                    "ontem" if days_ago == 1 else
                    f"há {days_ago} dias")
            mtype = chosen_mem["memory_type"].lower()
            references.append((3,
                f"MEMÓRIA RELACIONAL ({mtype}, {when}): "
                f"{chosen_mem['title']}. Cliente comentou: "
                f"«{chosen_mem['description'][:140]}». "
                "Mencione com naturalidade (\"vi aqui que...\", \"você "
                "comentou...\"). NUNCA diga \"identifiquei no banco\"."
            ))
            await db[MEMORY_COLL].update_one(
                {"_id": chosen_mem["_id"]},
                {"$set": {"last_used_at": _now()},
                 "$inc": {"hit_count": 1}},
            )

        # Prioridade 4: VIP
        vip = await _vip_block(
            company_id=company_id, subscriber_id=subscriber_id,
        )
        if vip:
            references.append((4, vip))

        # Evidências (sempre injetado se houver — regra dura)
        evid = await _evidence_block(
            company_id=company_id, subscriber_id=subscriber_id,
        )
        if evid:
            extra_blocks.append(evid)

    except Exception as e:
        logger.info("[v15] oracle build skip: %s", e)

    # ENFORCE: máximo 2 referências naturais na abertura
    references.sort(key=lambda x: x[0])  # menor prioridade primeiro
    chosen_refs = [r[1] for r in references[:2]]

    if not chosen_refs and not extra_blocks:
        return ""

    out: List[str] = [
        "=== ORÁCULO RELACIONAL ABSOLUTO (Isabella V15) ===",
    ]
    if chosen_refs:
        out.append("REFERÊNCIAS PRIORITÁRIAS (use no máximo estas DUAS, "
                   "com naturalidade — não é relatório):")
        for ref in chosen_refs:
            out.append("• " + ref)
    if extra_blocks:
        out.append("")
        out.extend(extra_blocks)
    out.append("")
    out.append(
        "REGRAS DE OURO V15:\n"
        "1. Soe como alguém da Ligo que acompanha o cliente — não CRM.\n"
        "2. Máx 2 referências. Naturais. Não enumere todas.\n"
        "3. Afirmações factuais (técnico/financeiro/cadastro) SOMENTE "
        "vindas das EVIDÊNCIAS acima. Sem evidência → «deixa eu "
        "confirmar isso para você» (NUNCA inventar).\n"
        "4. VIP: reconheça com naturalidade, sem bajulação."
    )
    return "\n".join(out)
