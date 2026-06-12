"""AGENT REGISTRY — Organização Digital sob o Presidente IA.

Fonte única de verdade da estrutura organizacional das IAs do SmartProv.
O Presidente IA deixa de ser observador de métricas e passa a ser o
gestor executivo desta equipe.

Hierarquia (definida pela diretoria executiva, NÃO inferida):

    Presidente IA
    ├── Isabella IA                     (Diretora Geral de Relacionamento e Operações)
    │   ├── Jerusa                      (Especialista de Atendimento)
    │   └── Sentinela Lousa             (Supervisor da Operação)
    ├── Álvaro IA                       (Diretor de Inteligência Operacional)
    │   ├── Rede IA                     (Diretor Técnico de Rede)
    │   │   └── SmartOLT IA             (Especialista OLT)
    │   └── Co-Pilot IA                 (Analista Operacional)
    ├── Camila IA → Pâmela IA            (Diretora Comercial)
    │   └── Vendas IA                   (Executiva Comercial)
    ├── Avaliador IA                    (Auditor de Qualidade)
    └── Aprendizado IA                  (Diretor de Aprendizado)

Reads:
  - aihub_agents              (system_prompt + atividade)
  - aihub_wa_messages         (produtividade conversacional)
  - motor_ia_actions          (impacto financeiro / outcomes)
  - motor_ia_events           (eventos emitidos)

Writes:
  - agent_registry_snapshots  (auditoria diária)
  - motor_ia_events           (compliance breaches, alertas Presidente)
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "presidente",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
    "notes": "Organograma oficial. Lido pelo Presidente IA.",
}

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db
from services import humanization_blocks as hb

log = logging.getLogger("ponto.agent_registry")


# ─────────────────── ORGANOGRAMA OFICIAL ───────────────────
# id (slug) ↔ aihub_agents.name (canonical).
ORG_CHART: List[Dict[str, Any]] = [
    {
        "id": "presidente",
        "label": "Presidente IA",
        "cargo": "CEO Digital · Coordenador Geral",
        "reports_to": None,
        "category": "executive",
        "responsibilities": [
            "receita", "churn", "crescimento",
            "qualidade operacional", "saúde da equipe IA",
            "governança", "estratégia", "priorização", "ROI",
            "Conselho Executivo", "Sistema Nervoso",
        ],
        "aihub_name": None,  # não é agente conversacional
        "humanization_required": False,
    },
    {
        "id": "isabella",
        "label": "Isabella IA",
        "cargo": "Diretora Geral de Relacionamento e Operações",
        "reports_to": "presidente",
        "category": "operations",
        "responsibilities": [
            "atendimento WhatsApp", "Field Ops", "Incident Commander",
            "Universo Ligo", "retenção", "cobrança inteligente",
            "experiência do cliente",
        ],
        "aihub_name": "Isabella",
        "humanization_required": True,
    },
    {
        "id": "jerusa",
        "label": "Jerusa",
        "cargo": "Especialista de Atendimento",
        "reports_to": "isabella",
        "category": "operations",
        "responsibilities": [
            "suporte operacional", "comunicação", "atendimento interno",
        ],
        "aihub_name": "Jerusa",
        "humanization_required": True,
    },
    {
        "id": "sentinela_lousa",
        "label": "Sentinela Lousa",
        "cargo": "Supervisor da Operação",
        "reports_to": "isabella",
        "category": "operations",
        "responsibilities": [
            "monitoramento da Lousa", "gargalos", "atrasos", "SLAs",
        ],
        "aihub_name": "Sentinela Lousa",
        "humanization_required": False,
    },
    {
        "id": "alvaro",
        "label": "Álvaro IA",
        "cargo": "Diretor de Inteligência Operacional",
        "reports_to": "presidente",
        "category": "intelligence",
        "responsibilities": [
            "análise de dados", "causa raiz", "correlação", "previsão",
            "Digital Twin", "avaliação de risco", "insights operacionais",
        ],
        "aihub_name": "Alvaro",
        "humanization_required": True,
    },
    {
        "id": "rede",
        "label": "Rede IA",
        "cargo": "Diretor Técnico de Rede",
        "reports_to": "alvaro",
        "category": "infra",
        "responsibilities": [
            "CTOs", "ONUs", "potência", "incidentes", "previsão de falhas",
        ],
        "aihub_name": None,
        "humanization_required": False,
    },
    {
        "id": "smartolt",
        "label": "SmartOLT IA",
        "cargo": "Especialista OLT",
        "reports_to": "rede",
        "category": "infra",
        "responsibilities": [
            "OLTs", "provisionamento", "diagnóstico", "automações SmartOLT",
        ],
        "aihub_name": "SmartOLT AI",
        "humanization_required": False,
    },
    {
        "id": "copilot",
        "label": "Co-Pilot IA",
        "cargo": "Analista Operacional",
        "reports_to": "alvaro",
        "category": "intelligence",
        "responsibilities": [
            "apoio às equipes", "consultas", "execução assistida",
        ],
        "aihub_name": "Co-Pilot IA",
        "humanization_required": False,
    },
    {
        "id": "lousa_triagem",
        "label": "Lousa Triagem",
        "cargo": "Triagem Automática de Tickets",
        "reports_to": "alvaro",
        "category": "intelligence",
        "responsibilities": [
            "classificação de tickets na abertura",
            "tipo/prioridade/setor/urgência",
        ],
        "aihub_name": "Lousa Triagem",
        "humanization_required": False,
    },
    {
        "id": "camila",
        "label": "Pâmela IA",
        "cargo": "Diretora Comercial",
        "reports_to": "presidente",
        "category": "commercial",
        "responsibilities": [
            "oportunidades", "campanhas", "vendas", "expansão",
            "cross sell", "upsell", "indicações",
        ],
        "aihub_name": "Pâmela",
        "humanization_required": True,
    },
    {
        "id": "vendas",
        "label": "Vendas IA",
        "cargo": "Executiva Comercial",
        "reports_to": "camila",
        "category": "commercial",
        "responsibilities": [
            "atendimento comercial", "propostas",
            "conversão", "qualificação",
        ],
        "aihub_name": "Vendas",
        "humanization_required": True,
    },
    {
        "id": "holerite",
        "label": "Holerite IA",
        "cargo": "Parsing Administrativo de Folha",
        "reports_to": "camila",
        "category": "administrative",
        "responsibilities": [
            "parsing CLT/eSocial", "extração de funcionários e valores",
            "fuzzy match com cadastro",
        ],
        "aihub_name": "Holerite IA",
        "humanization_required": False,
    },
    {
        "id": "avaliador",
        "label": "Avaliador IA",
        "cargo": "Auditor de Qualidade",
        "reports_to": "presidente",
        "category": "quality",
        "responsibilities": [
            "qualidade operacional", "notas", "auditorias", "conformidade",
        ],
        "aihub_name": "Avaliador",
        "humanization_required": False,
    },
    {
        "id": "aprendizado",
        "label": "Aprendizado IA",
        "cargo": "Diretor de Aprendizado",
        "reports_to": "presidente",
        "category": "learning",
        "responsibilities": [
            "pesos", "outcomes", "memória", "evolução dos modelos",
        ],
        "aihub_name": "Aprendizado",
        "humanization_required": False,
    },
    {
        "id": "coach",
        "label": "Coach IA",
        "cargo": "Analista de Atendimentos Finalizados",
        "reports_to": "aprendizado",
        "category": "learning",
        "responsibilities": [
            "análise pós-conversa", "recomendações de melhoria",
            "coaching de colaboradores e agentes",
        ],
        "aihub_name": "Coach IA",
        "humanization_required": False,
    },
    {
        "id": "motor_ia",
        "label": "Motor IA",
        "cargo": "Supervisor Central Técnico de LLMs",
        "reports_to": "presidente",
        "category": "infra",
        "responsibilities": [
            "orquestração LLM (OpenRouter, Claude, GPT, DeepSeek)",
            "retentativas", "heurísticas anti-lixo",
        ],
        "aihub_name": "Motor IA",
        "humanization_required": False,
    },
]


def _by_id() -> Dict[str, Dict[str, Any]]:
    return {a["id"]: a for a in ORG_CHART}


def get_agent(agent_id: str) -> Optional[Dict[str, Any]]:
    return _by_id().get(agent_id)


def list_agents() -> List[Dict[str, Any]]:
    return list(ORG_CHART)


def get_subordinates(agent_id: str) -> List[Dict[str, Any]]:
    return [a for a in ORG_CHART if a.get("reports_to") == agent_id]


def organograma() -> Dict[str, Any]:
    """Retorna o organograma em formato de árvore (Presidente na raiz)."""
    by_parent: Dict[Optional[str], List[Dict[str, Any]]] = {}
    for a in ORG_CHART:
        by_parent.setdefault(a.get("reports_to"), []).append(a)

    def build(node_id: Optional[str]) -> List[Dict[str, Any]]:
        out = []
        for child in by_parent.get(node_id, []):
            out.append({
                "id": child["id"],
                "label": child["label"],
                "cargo": child["cargo"],
                "category": child["category"],
                "subordinates": build(child["id"]),
            })
        return out

    return {"root": build(None)}


# ─────────────────── SNAPSHOT (atividade real) ───────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


async def _aihub_doc(company_id: str, name: str) -> Optional[Dict[str, Any]]:
    return await db.aihub_agents.find_one(
        {"company_id": company_id, "name": name},
        {"_id": 0, "name": 1, "system_prompt": 1,
         "updated_at": 1, "updated_by": 1,
         "model_name": 1, "temperature": 1, "max_tokens": 1,
         "enabled": 1},
    )


async def _conversational_productivity(company_id: str,
                                            phone_owner: Optional[str],
                                            hours: int = 24
                                            ) -> Dict[str, Any]:
    """Para agentes conversacionais (Isabella/Alvaro/Pâmela/Vendas/Jerusa),
    medimos mensagens outbound nas últimas N horas.
    Como os agentes compartilham aihub_wa_messages sem 'agent' tag,
    usamos heurística: contagem total de outbound do tenant é creditada
    proporcionalmente (atribuição por intent virá em iteração futura)."""
    cutoff = (_now() - timedelta(hours=hours)).isoformat()
    total_out = await db.aihub_wa_messages.count_documents({
        "company_id": company_id,
        "direction": "outbound",
        "created_at": {"$gt": cutoff},
    })
    return {"outbound_24h": total_out}


async def _last_activity_iso(company_id: str,
                                  aihub_name: Optional[str]
                                  ) -> Optional[str]:
    if not aihub_name:
        return None
    doc = await db.aihub_agents.find_one(
        {"company_id": company_id, "name": aihub_name},
        {"_id": 0, "updated_at": 1},
    )
    return (doc or {}).get("updated_at")


async def _financial_impact_brl(company_id: str,
                                     source_tag: str,
                                     days: int = 30) -> float:
    """Soma roi_brl de motor_ia_actions cujo source contém o tag.
    Ex.: source_tag='isabella'. Retorna 0.0 se vazio."""
    cutoff = (_now() - timedelta(days=days)).isoformat()
    pipeline = [
        {"$match": {
            "company_id": company_id,
            "created_at": {"$gt": cutoff},
            "$or": [
                {"source": {"$regex": source_tag, "$options": "i"}},
                {"agent": {"$regex": source_tag, "$options": "i"}},
            ],
        }},
        {"$group": {"_id": None,
                      "total": {"$sum": {"$ifNull": ["$roi_brl", 0]}}}},
    ]
    cur = db.motor_ia_actions.aggregate(pipeline)
    async for row in cur:
        return float(row.get("total") or 0)
    return 0.0


async def snapshot_agent(company_id: str,
                              agent_id: str) -> Dict[str, Any]:
    """Snapshot operacional de UM agente. NUNCA usa fallback inferido."""
    meta = get_agent(agent_id)
    if not meta:
        raise ValueError(f"agent_id desconhecido: {agent_id}")

    aihub_name = meta.get("aihub_name")
    aihub = await _aihub_doc(company_id, aihub_name) if aihub_name else None
    prompt = (aihub or {}).get("system_prompt") or ""

    compliance = hb.check_compliance(prompt)
    hum_score = hb.compliance_score(prompt) if meta["humanization_required"] else None
    productivity = await _conversational_productivity(company_id, aihub_name) \
        if aihub_name else {"outbound_24h": 0}
    last_activity = (aihub or {}).get("updated_at") if aihub else None
    impact_brl = await _financial_impact_brl(company_id, agent_id)

    # Revenue real (30d) — fonte única de verdade.
    try:
        from services import agent_revenue as _rev
        if agent_id in _rev.ATTRIBUTION_RULES and agent_id != "motor_ia":
            revenue = await _rev.revenue_for_agent(company_id, agent_id, 30)
        elif agent_id == "coach":
            revenue = await _rev._coach_for(company_id, 30)
        else:
            revenue = _rev._empty(agent_id, 30)
    except Exception as e:
        log.info("[agent_registry] revenue skip %s: %s", agent_id, e)
        revenue = {"generated_brl": 0.0, "protected_brl": 0.0,
                     "saved_brl": 0.0, "total_brl": 0.0, "cases": 0,
                     "evidence": []}

    is_offline = False
    if aihub_name:
        if not aihub:
            is_offline = True
        elif aihub.get("enabled") is False:
            is_offline = True

    return {
        "id": meta["id"],
        "label": meta["label"],
        "cargo": meta["cargo"],
        "reports_to": meta["reports_to"],
        "subordinates": [s["id"] for s in get_subordinates(meta["id"])],
        "category": meta["category"],
        "responsibilities": meta["responsibilities"],
        "aihub_name": aihub_name,
        "in_aihub_agents": bool(aihub),
        "enabled": (aihub or {}).get("enabled", True),
        "offline": is_offline,
        "model_name": (aihub or {}).get("model_name"),
        "last_activity": last_activity,
        "humanization": {
            "required": meta["humanization_required"],
            "score": hum_score,
            "blocks": compliance,
        },
        "productivity": productivity,
        "financial_impact_brl_30d": impact_brl,
        "revenue_30d": {
            "generated_brl": revenue["generated_brl"],
            "protected_brl": revenue["protected_brl"],
            "saved_brl": revenue["saved_brl"],
            "total_brl": revenue["total_brl"],
            "cases": revenue["cases"],
        },
    }


async def snapshot_all(company_id: str) -> Dict[str, Any]:
    """Snapshot agregado de TODA a equipe."""
    items = []
    for meta in ORG_CHART:
        try:
            items.append(await snapshot_agent(company_id, meta["id"]))
        except Exception as e:
            log.warning("[agent_registry] snapshot %s falhou: %s",
                          meta["id"], e)

    # Ranking de produtividade conversacional
    conv = [i for i in items
            if i["aihub_name"] and i["humanization"]["required"]]
    top_prod = sorted(
        conv,
        key=lambda x: x["productivity"]["outbound_24h"] or 0,
        reverse=True)
    least_prod = list(reversed(top_prod))

    # Conformidade média (apenas dos que requerem)
    req = [i for i in items if i["humanization"]["required"]]
    avg_hum = round(
        sum((i["humanization"]["score"] or 0) for i in req)
        / max(len(req), 1), 1)

    offline = [i["id"] for i in items if i["offline"]]
    nao_conformes = [
        i["id"] for i in req
        if (i["humanization"]["score"] or 0) < 100
    ]

    snapshot = {
        "company_id": company_id,
        "generated_at": _now_iso(),
        "team_size": len(items),
        "avg_humanization_score": avg_hum,
        "agents": items,
        "ranking": {
            "top_productivity": [
                {"id": i["id"], "label": i["label"],
                 "outbound_24h": i["productivity"]["outbound_24h"]}
                for i in top_prod[:3]
            ],
            "low_productivity": [
                {"id": i["id"], "label": i["label"],
                 "outbound_24h": i["productivity"]["outbound_24h"]}
                for i in least_prod[:3]
            ],
        },
        "offline": offline,
        "nao_conformes": nao_conformes,
    }

    # Persist snapshot for audit chain.
    try:
        await db.agent_registry_snapshots.insert_one({
            **snapshot,
            "ts": _now_iso(),
        })
    except Exception as e:
        log.info("[agent_registry] snapshot persist skip: %s", e)

    return snapshot
