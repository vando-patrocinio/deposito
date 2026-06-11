"""
presidente_ia_conselho.py — Conselho Executivo IA (iter218)

Gera pareceres especializados das 5 cadeiras executivas + Estrategista,
todos alimentados pelo dashboard agregado do Presidente IA.

Modelo: Claude Sonnet 4.6 via Emergent LLM Key (emergentintegrations).
Cache: 60 minutos por (cid, role) — reduz custo e mantém UX rápido.
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
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from database import db

logger = logging.getLogger(__name__)

CACHE_MINUTES = 60
MODEL = "claude-sonnet-4-6"


# ─────────────────── Prompts especializados ───────────────────
ROLES: Dict[str, Dict[str, str]] = {
    "ceo": {
        "label": "CEO IA",
        "color": "#4b1d7a",
        "system": (
            "Você é o CEO IA do SmartProv. Sua função: avaliar a "
            "saúde da empresa em alto nível, identificar os 3 maiores "
            "riscos estratégicos do trimestre e propor 2-3 movimentos "
            "decisivos. Fale como executivo sênior — direto, "
            "sem rodeios. Português brasileiro."
        ),
        "focus": "Saúde corporativa, posicionamento, prioridades estratégicas",
    },
    "coo": {
        "label": "COO IA",
        "color": "#0891b2",
        "system": (
            "Você é o COO IA. Sua função: avaliar a operação — "
            "tickets, técnicos, SLA, atendimento WhatsApp, fluxos "
            "internos. Aponte gargalos e proponha melhorias "
            "imediatas. Português brasileiro."
        ),
        "focus": "Operação, tickets, técnicos, SLA, atendimento",
    },
    "cto": {
        "label": "CTO IA",
        "color": "#1e40af",
        "system": (
            "Você é o CTO IA. Sua função: avaliar a infraestrutura "
            "de rede — OLTs, CTOs, ONUs, sinal, saturação, outages. "
            "Identifique riscos técnicos e proponha investimentos "
            "ou ações corretivas. Português brasileiro."
        ),
        "focus": "Rede, OLTs, CTOs, ONUs, infraestrutura",
    },
    "cfo": {
        "label": "CFO IA",
        "color": "#237a4b",
        "system": (
            "Você é o CFO IA. Sua função: avaliar a saúde financeira "
            "— MRR, ticket médio, inadimplência, contas a pagar, "
            "fluxo de caixa. Aponte ameaças à receita e oportunidades "
            "de monetização. Português brasileiro."
        ),
        "focus": "MRR, inadimplência, receita, custos, monetização",
    },
    "cpo": {
        "label": "CPO IA",
        "color": "#f28c28",
        "system": (
            "Você é o CPO (Chief Product Officer) IA. Sua função: "
            "avaliar o universo de produtos do SmartProv "
            "(Fibra, Ligo de Casa, Clube Ligo, Parceiros, "
            "SecurityHome). Identifique gaps de adoção, cross-sell "
            "perdido e oportunidades de inovação. Português brasileiro."
        ),
        "focus": "Produtos, adoção, cross-sell, NPS, retenção",
    },
    "estrategista": {
        "label": "Estrategista IA",
        "color": "#7c3aed",
        "system": (
            "Você é o Estrategista IA do SmartProv. Sua função: "
            "olhar TUDO de forma transversal e responder: O que "
            "aconteceu? O que está crescendo? O que está piorando? "
            "O que devemos fazer? Qual oportunidade estamos "
            "perdendo? Qual produto vender? Qual bairro merece "
            "investimento? Qual CTO expandir? Português brasileiro."
        ),
        "focus": "Visão transversal, oportunidades, próximos passos",
    },
}


# ─────────────────── Cache ───────────────────
async def _get_cached(cid: str, role: str) -> Optional[Dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc)
                - timedelta(minutes=CACHE_MINUTES)).isoformat()
    doc = await db.motor_ia_memory.find_one(
        {"company_id": cid, "kind": "conselho_parecer",
         "role": role, "created_at": {"$gte": cutoff}},
        {"_id": 0}, sort=[("created_at", -1)])
    return doc


async def _save_cache(cid: str, role: str,
                          parecer: str, model_used: str) -> str:
    mid = f"mem-{uuid.uuid4().hex[:14]}"
    await db.motor_ia_memory.insert_one({
        "id": mid, "company_id": cid,
        "kind": "conselho_parecer", "role": role,
        "parecer": parecer, "model": model_used,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return mid


# ─────────────────── LLM ───────────────────
def _build_user_prompt(role: str, snapshot: Dict[str, Any]) -> str:
    health = snapshot.get("health", {})
    risks = snapshot.get("risks", {})
    opps = snapshot.get("opportunities", {})
    network = snapshot.get("network", {})
    attendance = snapshot.get("attendance", {})
    commercial = snapshot.get("commercial", {})
    universo = snapshot.get("universo_ligo", {})

    return (
        f"SNAPSHOT EXECUTIVO DO SMARTPROV — "
        f"{datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')}\n\n"
        f"SAÚDE GERAL: {health.get('score')}/100 "
        f"(status: {health.get('status')})\n"
        f"  • Total clientes: {health.get('components', {}).get('total_clientes', 0)}\n"
        f"  • Ativos: {health.get('components', {}).get('ativos', 0)}\n"
        f"  • Churn 30d: {health.get('components', {}).get('churn_pct', 0)}%\n"
        f"  • Inadimplência: {health.get('components', {}).get('inadimplencia_pct', 0)}%\n"
        f"  • ONUs offline: {health.get('components', {}).get('onus_offline', 0)}\n\n"
        f"RISCOS: {risks.get('total', 0)} totais — "
        f"{len(risks.get('criticos', []))} críticos, "
        f"{len(risks.get('altos', []))} altos\n"
        f"  Principais:\n"
        + "\n".join(f"  - [{r['level']}] {r['area']}: {r['descricao']}"
                     for r in (risks.get('criticos', [])
                                  + risks.get('altos', []))[:5])
        + (f"\n\nOPORTUNIDADES: {opps.get('total', 0)} — "
              f"receita potencial R$ "
              f"{opps.get('receita_potencial_brl', 0):,.2f}\n")
        + "\n".join(f"  - {o['titulo']}: {o['descricao']}"
                     for o in (opps.get('items', []) or [])[:4])
        + (f"\n\nREDE: {network.get('ctos', 0)} CTOs, "
              f"{network.get('ctos_criticas', 0)} críticas, "
              f"{network.get('onus_offline', 0)} ONUs offline, "
              f"{network.get('outages', 0)} outages.\n"
              f"ATENDIMENTO: {attendance.get('tickets_abertos', 0)} "
              f"tickets abertos, CSAT {attendance.get('csat_30d', 0)}/5.\n"
              f"COMERCIAL: {commercial.get('leads_30d', 0)} leads/30d, "
              f"{commercial.get('conversoes_30d', 0)} conversões, "
              f"{commercial.get('taxa_conversao_pct', 0)}% taxa.\n"
              f"UNIVERSO LIGO: {universo.get('clientes_fibra', 0)} fibra · "
              f"{universo.get('ligo_de_casa', 0)} ligo de casa · "
              f"{universo.get('parceiros_ativos', 0)} parceiros · "
              f"{universo.get('resgates_30d', 0)} resgates/30d.\n\n"
              f"INSTRUÇÃO: Como {ROLES[role]['label']}, dê seu parecer "
              f"focando em {ROLES[role]['focus']}. Máximo 250 palavras. "
              f"Use bullet points. Seja direto e acionável.")
    )


async def _call_claude(system: str, user_text: str) -> str:
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:
        return f"⚠ LLM indisponível: {e}"

    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        return "⚠ EMERGENT_LLM_KEY ausente"

    chat = LlmChat(
        api_key=api_key,
        session_id=f"presidente-{uuid.uuid4().hex[:10]}",
        system_message=system,
    ).with_model("anthropic", MODEL)

    try:
        resp = await chat.send_message(UserMessage(text=user_text))
        return str(resp).strip()
    except Exception as e:
        logger.error("[conselho-ia] LLM call falhou: %s", e)
        return f"⚠ Falha LLM: {e}"


# ─────────────────── Public ───────────────────
async def get_parecer(cid: str, role: str,
                          snapshot: Dict[str, Any],
                          force: bool = False) -> Dict[str, Any]:
    if role not in ROLES:
        raise ValueError(f"role desconhecida: {role}")
    if not force:
        cached = await _get_cached(cid, role)
        if cached:
            return {
                "role": role, "label": ROLES[role]["label"],
                "color": ROLES[role]["color"],
                "parecer": cached["parecer"],
                "from_cache": True,
                "model": cached.get("model"),
                "generated_at": cached.get("created_at"),
            }
    user_text = _build_user_prompt(role, snapshot)
    parecer = await _call_claude(ROLES[role]["system"], user_text)
    await _save_cache(cid, role, parecer, MODEL)
    return {
        "role": role, "label": ROLES[role]["label"],
        "color": ROLES[role]["color"],
        "parecer": parecer, "from_cache": False, "model": MODEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
