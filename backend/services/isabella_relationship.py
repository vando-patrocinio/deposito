"""OPERAÇÃO RELACIONAMENTO 360° — Isabella Customer Success Director.

Este módulo concentra os fixes da auditoria de 2026-02-10:

  F3. register_isabella_outcome — grava ai_evaluations REAL pra cada outbound.
  F5. relationship_memory_block — bloco no system prompt com VIP score + última conversa.
  F6. universo_ligo_contextual — gatilho contextual após resolução.
  F7. encerramento_humanizado — detecta fim e sonda NPS.

A regra de ouro: a Isabella tem de fazer o cliente GOSTAR MAIS da Ligo depois
de conversar com ela. Cada função aqui sustenta essa promessa com gravação
em banco real, sem mocks.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
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
from typing import Any, Dict, List, Optional

from database import db

logger = logging.getLogger("ponto.isabella_relationship")


# ===================== F3. REGISTRO DE OUTCOME REAL =====================

OUTCOME_KEYWORDS: Dict[str, List[str]] = {
    "resolveu": [r"\bresolvi", r"\bresolvido", r"\bj[áa]\s+(funcionou|voltou|"
                  r"liberei|cred|gerei)", r"\bdesbloque", r"\bnormalizou"],
    "ofertou": [r"\bplayhub", r"\bligo\s*security", r"\bligo\s*m[óo]vel",
                  r"\bcombo", r"\bupgrade", r"\bindique\s*e\s*ganhe"],
    "vendeu": [r"\bcontrat(ado|amos)", r"\bativad", r"\binclu[íi]do no plano",
                r"\bpedido confirmado", r"\bvenda\s+fechada"],
    "reteve": [r"\bfic(ou|a)?\s+conosco", r"\breconsidera", r"\bn[ãa]o cancelou"],
    "cobrou": [r"\b2[ªa]?\s*via", r"\bpix", r"\bboleto", r"\bnegoci"],
    "agendou": [r"\bagendei\b", r"\bvisita\s+marcada", r"\bjanela\s+\d+h",
                  r"\bequipe\s+(t[ée]cnica\s+)?(j[áa]\s+)?(foi|est[áa])\s+acionada",
                  r"\breabri\s+(seu|o)\s+chamado"],
    "problema_tecnico": [r"\bonu", r"\bsinal", r"\bsem internet", r"\bcaiu",
                          r"\blentid"],
    "avisou_proativo": [r"\bvi\s+que", r"\bidentifiquei", r"\bdetectei",
                         r"\bj[áa]\s+abri\s+chamado", r"\bvi\s+aqui\b",
                         r"\bj[áa]\s+reabri"],
}

OUTCOME_NPS_HINTS = {
    "resolveu":          (8, "atendimento resolveu"),
    "vendeu":            (9, "venda fechada"),
    "reteve":            (8, "cliente retido"),
    "agendou":           (7, "agendamento confirmado"),
    "ofertou":           (6, "oferta apresentada"),
    "cobrou":            (6, "negociação financeira"),
    "problema_tecnico":  (5, "problema técnico em curso"),
    "avisou_proativo":   (8, "abordagem proativa"),
}


def _detect_outcomes(reply: str) -> Dict[str, bool]:
    """Detecta outcomes na resposta da Isabella via regex em PT-BR."""
    out = {k: False for k in OUTCOME_KEYWORDS}
    if not reply:
        return out
    r = reply.lower()
    for k, pats in OUTCOME_KEYWORDS.items():
        for pat in pats:
            if re.search(pat, r, re.IGNORECASE):
                out[k] = True
                break
    return out


def _infer_nps(outcomes: Dict[str, bool], reply: str, user_text: str) -> tuple:
    """Heurística simples: o melhor outcome dita um piso de NPS."""
    best = 5
    motivo = "atendimento padrão"
    for key, (n, m) in OUTCOME_NPS_HINTS.items():
        if outcomes.get(key) and n > best:
            best = n
            motivo = m
    # Pena: cliente irritado / corrigindo
    if re.search(r"\b(da\s+onde|nada\s+a\s+ver|n[ãa]o\s+era\s+isso|"
                  r"voc[êe]\s+entendeu\s+errado|nao\s+me\s+responde|\?{3,})\b",
                  user_text or "", re.IGNORECASE):
        best = max(2, best - 3)
        motivo = "cliente sinalizou frustração"
    return best, motivo


async def register_isabella_outcome(
        *, company_id: str, phone: str,
        subscriber_id: Optional[str],
        user_text: str, reply: str,
        outbound_msg_id: Optional[str] = None) -> Optional[str]:
    """Grava 1 doc em `ai_evaluations` por outbound real da Isabella.

    Retorna o id criado (ou None em caso de falha não-fatal).
    """
    if not reply:
        return None
    try:
        outcomes = _detect_outcomes(reply)
        nps, motivo = _infer_nps(outcomes, reply, user_text)
        tags = [k for k, v in outcomes.items() if v]
        doc = {
            "id": f"eval-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "phone": phone,
            "subscriber_id": subscriber_id,
            "kind": "ISABELLA_TURN",
            "outbound_msg_id": outbound_msg_id,
            "user_text": (user_text or "")[:500],
            "isabella_reply": (reply or "")[:800],
            "outcomes": outcomes,
            "outcome": next((k for k in ("vendeu", "resolveu", "reteve",
                                            "agendou", "cobrou", "ofertou",
                                            "avisou_proativo")
                              if outcomes.get(k)), "interacao"),
            "nps_inferido": nps,
            "nps_motivo": motivo,
            "tags": tags,
            "ai_attributed": "Isabella",
            "is_backfill": False,
            "exclude_from_metrics": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.ai_evaluations.insert_one(doc)
        return doc["id"]
    except Exception as e:
        logger.warning("[relationship] register_outcome falhou: %s", e)
        return None


# ===================== F5. RELATIONSHIP MEMORY BLOCK =====================

async def relationship_memory_block(
        *, company_id: str, phone: str,
        subscriber_id: Optional[str]) -> str:
    """Bloco compacto pra injetar no system prompt: histórico relacional."""
    parts: List[str] = []
    try:
        # Última conversa real (último outcome registrado)
        last = await db.ai_evaluations.find_one(
            {"company_id": company_id, "phone": phone,
             "kind": "ISABELLA_TURN",
             "exclude_from_metrics": {"$ne": True}},
            {"_id": 0, "created_at": 1, "outcome": 1, "tags": 1,
             "nps_inferido": 1, "isabella_reply": 1, "user_text": 1},
            sort=[("created_at", -1)],
        )
        if last:
            when = (last.get("created_at") or "")[:10]
            parts.append(
                f"Última conversa em {when}: outcome={last.get('outcome')}, "
                f"NPS≈{last.get('nps_inferido')}. Cliente perguntou: "
                f"\"{(last.get('user_text') or '')[:80]}\"."
            )

        # Recorrência: quantas tickets do mesmo tipo em 30d
        if subscriber_id:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            pipeline = [
                {"$match": {"company_id": company_id,
                              "subscriber_id": subscriber_id,
                              "created_at": {"$gte": cutoff}}},
                {"$group": {"_id": "$type", "n": {"$sum": 1}}},
                {"$sort": {"n": -1}},
            ]
            tk_pattern: List[str] = []
            async for d in db.tickets.aggregate(pipeline):
                if d.get("n", 0) > 1:
                    tk_pattern.append(f"{d['_id']} ({d['n']}x)")
            if tk_pattern:
                parts.append("⚠ Reincidência 30d: " + ", ".join(tk_pattern)
                              + ". Trate com CUIDADO REDOBRADO.")

        # VIP score (tem ledger positivo grande?)
        if subscriber_id:
            agg = await db.executive_ledger.aggregate([
                {"$match": {"company_id": company_id,
                              "subscriber_id": subscriber_id}},
                {"$group": {"_id": None,
                              "total": {"$sum": "$actual_BRL"}}},
            ]).to_list(1)
            if agg and (agg[0].get("total") or 0) > 500:
                parts.append(
                    f"💎 Cliente VIP: R$ {agg[0]['total']:.0f} preservados "
                    "pela Isabella até hoje."
                )
    except Exception as e:
        logger.info("[relationship] memory_block skip: %s", e)

    if not parts:
        return ""
    return ("=== MEMÓRIA DE RELACIONAMENTO (use pra personalizar) ===\n"
            + "\n".join("• " + p for p in parts)
            + "\nMostre que se lembra. Não repita perguntas que já tem "
              "resposta no histórico.")


# ===================== F6. UNIVERSO LIGO CONTEXTUAL =====================

UNIVERSO_LIGO_OFERTAS = [
    {
        "produto": "PlayHub",
        "valor": "R$ 19,90/mês",
        "gatilho_outcome": ["resolveu", "vendeu"],
        "pitch": ("Já que você curte assistir nas horas vagas, o PlayHub "
                  "tem +50 canais ao vivo + filmes — incluído na sua fatura. "
                  "Quer experimentar 7 dias grátis?"),
    },
    {
        "produto": "Ligo Security",
        "valor": "R$ 29,90/mês",
        "gatilho_outcome": ["resolveu", "reteve"],
        "pitch": ("E pra proteger sua casa quando você não tá, temos a "
                  "Ligo Security: alarme + câmera + app no celular. "
                  "Posso te enviar uma proposta sem compromisso?"),
    },
    {
        "produto": "Ligo Móvel",
        "valor": "R$ 39,90/mês",
        "gatilho_outcome": ["resolveu", "vendeu"],
        "pitch": ("Aproveitando, você sabia que a gente tem chip 5G também? "
                  "Ligo Móvel com 20GB por R$ 39,90 e o app já fica no "
                  "seu painel. Quer ver o plano?"),
    },
]


async def universo_ligo_contextual_pitch(
        *, company_id: str, phone: str,
        subscriber_id: Optional[str], reply: str) -> str:
    """Devolve uma sugestão de pitch APENAS se o contexto for adequado.

    Regras:
      - Cliente não pode ter recebido pitch nos últimos 30 dias.
      - O outbound atual da Isabella deve indicar resolução/sucesso.
      - Cliente não pode ter outcome="problema_tecnico" pendente.
    """
    if not reply:
        return ""
    outcomes = _detect_outcomes(reply)
    if outcomes.get("problema_tecnico") and not outcomes.get("resolveu"):
        return ""  # nunca empurrar venda durante problema
    if not (outcomes.get("resolveu") or outcomes.get("vendeu")
            or outcomes.get("agendou")):
        return ""

    # Já recebeu pitch nos últimos 30d? (verifica em ledger E em outcomes)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    recent_pitch = await db.executive_ledger.find_one({
        "company_id": company_id, "phone": phone,
        "kind": "UNIVERSO_LIGO_PITCH",
        "created_at": {"$gte": cutoff},
    })
    if not recent_pitch:
        recent_pitch = await db.ai_evaluations.find_one({
            "company_id": company_id, "phone": phone,
            "tags": "ofertou", "created_at": {"$gte": cutoff},
        })
    if recent_pitch:
        return ""

    # Escolhe a primeira oferta compatível
    for o in UNIVERSO_LIGO_OFERTAS:
        if any(outcomes.get(g) for g in o["gatilho_outcome"]):
            # Registra no ledger pra rastreio
            try:
                await db.executive_ledger.insert_one({
                    "id": f"led-{uuid.uuid4().hex[:10]}",
                    "action_id": f"ulp-{uuid.uuid4().hex[:12]}",
                    "company_id": company_id,
                    "subscriber_id": subscriber_id,
                    "phone": phone,
                    "kind": "UNIVERSO_LIGO_PITCH",
                    "category": "cross_sell",
                    "produto": o["produto"],
                    "expected_brl": 0,
                    "actual_BRL": 0,
                    "status": "proposed",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                logger.info("[universo_ligo] ledger insert skip: %s", e)
            return o["pitch"]
    return ""


# ===================== F7. ENCERRAMENTO HUMANIZADO =====================

CLOSING_PATTERNS = re.compile(
    r"\b(obrigad[oa]|valeu|brigad[oa]|tmj|abra[çc]o|tchau|at[ée]\s+mais|"
    r"perfeito|tudo certo|s[óo]\s+isso|nada\s+mais|nao\s+precisa\s+mais)\b",
    re.IGNORECASE,
)


def detect_closing_intent(user_text: str) -> bool:
    """O cliente está se despedindo / encerrando?"""
    if not user_text:
        return False
    return bool(CLOSING_PATTERNS.search(user_text))


async def humanized_closing_block(*, company_id: str, phone: str,
                                       subscriber_id: Optional[str],
                                       user_text: str) -> str:
    """Se detectar despedida, instrui a Isabella a encerrar com sondagem
    de NPS e plantar a próxima interação."""
    if not detect_closing_intent(user_text):
        return ""
    # Já mandou closing nos últimos 7d?
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    recent_close = await db.ai_evaluations.find_one({
        "company_id": company_id, "phone": phone,
        "kind": "ISABELLA_CLOSING", "created_at": {"$gte": cutoff},
    })
    if recent_close:
        return ""
    return (
        "=== ENCERRAMENTO HUMANIZADO (USE AGORA) ===\n"
        "O cliente está se despedindo. Faça assim:\n"
        "1. Agradeça pelo contato pelo NOME (se souber).\n"
        "2. Reconheça o que foi resolvido em 1 frase.\n"
        "3. Faça UMA pergunta curta de NPS: \"De 0 a 10, quanto você "
        "indicaria a Ligo pra um amigo hoje?\" (sem formulário, "
        "conversacional).\n"
        "4. Diga \"Pode me chamar a qualquer momento aqui no WhatsApp, "
        "tô sempre por aqui pela Ligo 💙\".\n"
        "PROIBIDO oferecer outro produto neste turno — é encerramento."
    )


async def log_closing(*, company_id: str, phone: str,
                          subscriber_id: Optional[str]) -> None:
    """Marca que o encerramento humanizado foi enviado."""
    try:
        await db.ai_evaluations.insert_one({
            "id": f"close-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "phone": phone,
            "subscriber_id": subscriber_id,
            "kind": "ISABELLA_CLOSING",
            "ai_attributed": "Isabella",
            "is_backfill": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass
