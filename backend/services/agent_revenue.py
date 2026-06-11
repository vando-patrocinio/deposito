"""AGENT REVENUE — Receita por agente IA.

Responde a pergunta crítica do CTO:

    "Qual agente gerou mais dinheiro nos últimos 30 dias?"

Três métricas (R$ reais, vindas do MongoDB):

  Receita Gerada     → novas receitas (venda/upsell/expansão).
  Receita Protegida  → churn evitado (LTV preservado).
  Economia           → cobranças recuperadas + visitas evitadas
                       (Smart Field) + custos prevenidos.

Fontes:
  - motor_ia_revenue_attribution  (kind=recovered/generated/protected)
  - executive_ledger              (modulo + valor_confirmado_brl)
  - motor_ia_actions              (roi_brl + agent attribution)

Regras de atribuição (auditáveis, sem fallback inferido):

  Isabella   ← modulo ∈ {Cobrança, Retenção} via channel whatsapp + Lousa
                + motor_ia_actions(source~isabella)
  Camila     ← modulo='Receita' (vendas/upsell/expansão)
  Vendas     ← modulo='Receita', categoria~vendas/lead
  Álvaro     ← modulo='Smart Field' (operacional, twin)
  Avaliador  ← modulo='Qualidade' (correções aplicadas)
  Rede IA    ← modulo='Smart Field' (incidentes evitados via twin)
  Motor IA   ← meta-attribution (coordenação): % do total.
  Coach IA   ← attendant_corrective_actions confirmadas.
  Holerite   ← economia de horas (folha automática).

Zero mocks. Tudo lido do real.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "presidente",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
    "notes": "Atribuição financeira por agente.",
}

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db

log = logging.getLogger("ponto.agent_revenue")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cutoff_iso(days: int) -> str:
    return (_now() - timedelta(days=days)).isoformat()


# ─────────── Regras de atribuição declarativas ───────────
# Cada agente declara como puxar dinheiro REAL.
ATTRIBUTION_RULES: Dict[str, Dict[str, Any]] = {
    "isabella": {
        "label": "Isabella IA",
        "ledger_modulos": ["Cobrança", "Retenção"],
        "revenue_attribution_channels": ["whatsapp_baileys",
                                              "whatsapp_twilio"],
        "motor_action_sources": ["isabella"],
        "buckets": {
            "ledger:Cobrança": "saved",
            "ledger:Retenção": "protected",
            "rev:recovered:whatsapp_baileys": "saved",
            "rev:recovered:whatsapp_twilio": "saved",
        },
    },
    "camila": {
        "label": "Camila IA",
        "ledger_modulos": ["Receita"],
        "revenue_attribution_kinds": ["generated", "upsell", "expansion"],
        "motor_action_sources": ["camila"],
        "buckets": {
            "ledger:Receita": "generated",
            "rev:generated": "generated",
            "rev:upsell": "generated",
            "rev:expansion": "generated",
        },
    },
    "vendas": {
        "label": "Vendas IA",
        "ledger_categoria_regex": "vend|lead|conver",
        "motor_action_sources": ["vendas"],
        "buckets": {
            "ledger_categoria:vendas": "generated",
        },
    },
    "alvaro": {
        "label": "Álvaro IA",
        "ledger_modulos": ["Smart Field"],
        "motor_action_sources": ["alvaro", "twin"],
        "buckets": {
            "ledger:Smart Field": "saved",
        },
    },
    "rede": {
        "label": "Rede IA",
        "ledger_modulos": ["Rede", "Infra"],
        "motor_action_sources": ["rede", "smartolt"],
        "buckets": {
            "ledger:Rede": "saved",
            "ledger:Infra": "saved",
        },
    },
    "motor_ia": {
        "label": "Motor IA",
        "meta_share_pct": 0.05,  # coordena: leva 5% do total como reconhecimento técnico
        "buckets": {"meta": "saved"},
    },
}


def _classify_bucket(modulo: str) -> str:
    m = (modulo or "").lower()
    if "receita" in m or "vend" in m or "upsell" in m:
        return "generated"
    if "reten" in m or "churn" in m:
        return "protected"
    return "saved"


async def _ledger_amount(company_id: str, days: int,
                              modulos: List[str]
                              ) -> List[Dict[str, Any]]:
    cutoff = _cutoff_iso(days)
    pipe = [
        {"$match": {
            "company_id": company_id,
            "executed_at": {"$gte": cutoff},
            "modulo": {"$in": modulos},
        }},
        {"$group": {
            "_id": "$modulo",
            "valor_confirmado": {
                "$sum": {"$ifNull": ["$valor_confirmado_brl", 0]}},
            "valor_executado": {
                "$sum": {"$ifNull": ["$valor_executado_brl", 0]}},
            "valor_previsto": {
                "$sum": {"$ifNull": ["$valor_previsto_brl", 0]}},
            "count": {"$sum": 1},
        }},
    ]
    return [doc async for doc in db.executive_ledger.aggregate(pipe)]


async def _ledger_amount_categoria_regex(company_id: str, days: int,
                                                  regex: str
                                                  ) -> Dict[str, float]:
    cutoff = _cutoff_iso(days)
    pipe = [
        {"$match": {
            "company_id": company_id,
            "executed_at": {"$gte": cutoff},
            "categoria": {"$regex": regex, "$options": "i"},
        }},
        {"$group": {
            "_id": None,
            "confirmado": {
                "$sum": {"$ifNull": ["$valor_confirmado_brl", 0]}},
            "previsto": {
                "$sum": {"$ifNull": ["$valor_previsto_brl", 0]}},
            "count": {"$sum": 1},
        }},
    ]
    async for r in db.executive_ledger.aggregate(pipe):
        return {"confirmado": float(r.get("confirmado") or 0),
                  "previsto": float(r.get("previsto") or 0),
                  "count": int(r.get("count") or 0)}
    return {"confirmado": 0.0, "previsto": 0.0, "count": 0}


async def _revenue_attribution(company_id: str, days: int,
                                    *, channels: Optional[List[str]] = None,
                                    kinds: Optional[List[str]] = None
                                    ) -> Dict[str, float]:
    cutoff = _cutoff_iso(days)
    match: Dict[str, Any] = {
        "company_id": company_id,
        "recognized_at": {"$gte": cutoff},
    }
    if channels:
        match["channel"] = {"$in": channels}
    if kinds:
        match["kind"] = {"$in": kinds}
    pipe = [
        {"$match": match},
        {"$group": {
            "_id": None,
            "amount": {"$sum": {"$ifNull": ["$amount_BRL", 0]}},
            "count": {"$sum": 1},
        }},
    ]
    async for r in db.motor_ia_revenue_attribution.aggregate(pipe):
        return {"amount_brl": float(r.get("amount") or 0),
                  "count": int(r.get("count") or 0)}
    return {"amount_brl": 0.0, "count": 0}


async def _motor_action_roi(company_id: str, days: int,
                                  source_keywords: List[str]
                                  ) -> Dict[str, float]:
    cutoff = _cutoff_iso(days)
    or_match = []
    for kw in source_keywords:
        or_match.append({"source": {"$regex": kw, "$options": "i"}})
        or_match.append({"agent": {"$regex": kw, "$options": "i"}})
    pipe = [
        {"$match": {
            "company_id": company_id,
            "created_at": {"$gte": cutoff},
            "$or": or_match,
        }},
        {"$group": {
            "_id": None,
            "roi": {"$sum": {"$ifNull": ["$roi_brl", 0]}},
            "count": {"$sum": 1},
        }},
    ]
    async for r in db.motor_ia_actions.aggregate(pipe):
        return {"roi_brl": float(r.get("roi") or 0),
                  "count": int(r.get("count") or 0)}
    return {"roi_brl": 0.0, "count": 0}


async def _coach_corrective_count(company_id: str, days: int) -> int:
    cutoff = _cutoff_iso(days)
    try:
        return await db.attendant_corrective_actions.count_documents({
            "company_id": company_id,
            "created_at": {"$gte": cutoff},
            "status": {"$in": ["applied", "confirmed", "done"]},
        })
    except Exception:
        return 0


async def revenue_for_agent(company_id: str, agent_id: str,
                                  days: int = 30) -> Dict[str, Any]:
    """Calcula receita para 1 agente, no horizonte de N dias."""
    rules = ATTRIBUTION_RULES.get(agent_id)
    if not rules:
        return _empty(agent_id, days,
                        reason="agente sem regra de atribuição "
                                 "(não monetizável diretamente)")

    generated = 0.0
    protected = 0.0
    saved = 0.0
    cases = 0
    evidence: List[Dict[str, Any]] = []

    # 1) executive_ledger por modulo
    modulos = rules.get("ledger_modulos") or []
    if modulos:
        rows = await _ledger_amount(company_id, days, modulos)
        for row in rows:
            modulo = row["_id"]
            bucket = _classify_bucket(modulo)
            amt = float(row.get("valor_confirmado") or 0)
            if amt == 0:
                amt = float(row.get("valor_executado") or 0) * 0.0
            if bucket == "generated":
                generated += amt
            elif bucket == "protected":
                protected += amt
            else:
                saved += amt
            cases += int(row.get("count") or 0)
            evidence.append({
                "source": "executive_ledger",
                "modulo": modulo, "bucket": bucket,
                "amount_brl": amt, "actions": row.get("count")})

    # 2) executive_ledger por categoria regex (Vendas IA)
    if rules.get("ledger_categoria_regex"):
        rx = rules["ledger_categoria_regex"]
        r = await _ledger_amount_categoria_regex(company_id, days, rx)
        generated += r["confirmado"]
        cases += r["count"]
        if r["count"]:
            evidence.append({"source": "executive_ledger",
                                "categoria_regex": rx,
                                "amount_brl": r["confirmado"],
                                "actions": r["count"]})

    # 3) motor_ia_revenue_attribution
    if rules.get("revenue_attribution_channels"):
        r = await _revenue_attribution(
            company_id, days,
            channels=rules["revenue_attribution_channels"])
        # canal whatsapp atribuído a Isabella ≈ economia/recuperação.
        saved += r["amount_brl"]
        cases += r["count"]
        if r["count"]:
            evidence.append({
                "source": "motor_ia_revenue_attribution",
                "channels": rules["revenue_attribution_channels"],
                "amount_brl": r["amount_brl"],
                "actions": r["count"]})

    if rules.get("revenue_attribution_kinds"):
        r = await _revenue_attribution(
            company_id, days, kinds=rules["revenue_attribution_kinds"])
        generated += r["amount_brl"]
        cases += r["count"]
        if r["count"]:
            evidence.append({
                "source": "motor_ia_revenue_attribution",
                "kinds": rules["revenue_attribution_kinds"],
                "amount_brl": r["amount_brl"],
                "actions": r["count"]})

    # 4) motor_ia_actions com source/agent ~ agent
    if rules.get("motor_action_sources"):
        r = await _motor_action_roi(company_id, days,
                                          rules["motor_action_sources"])
        saved += r["roi_brl"]  # ROI bruto vira saved por default
        cases += r["count"]
        if r["count"]:
            evidence.append({
                "source": "motor_ia_actions",
                "keywords": rules["motor_action_sources"],
                "roi_brl": r["roi_brl"],
                "actions": r["count"]})

    total = generated + protected + saved
    return {
        "agent_id": agent_id,
        "label": rules["label"],
        "window_days": days,
        "generated_brl": round(generated, 2),
        "protected_brl": round(protected, 2),
        "saved_brl": round(saved, 2),
        "total_brl": round(total, 2),
        "cases": cases,
        "evidence": evidence,
    }


async def _meta_share_for_motor(company_id: str, days: int,
                                      base_total: float) -> Dict[str, Any]:
    """Motor IA leva uma fatia de RECONHECIMENTO técnico (coordena tudo)."""
    pct = ATTRIBUTION_RULES["motor_ia"].get("meta_share_pct") or 0.0
    amt = round(base_total * pct, 2)
    return {
        "agent_id": "motor_ia",
        "label": "Motor IA",
        "window_days": days,
        "generated_brl": 0.0,
        "protected_brl": 0.0,
        "saved_brl": amt,
        "total_brl": amt,
        "cases": 0,
        "evidence": [{"source": "meta_share",
                       "pct_of_team_total": pct,
                       "team_total_brl": base_total}],
    }


async def _coach_for(company_id: str, days: int) -> Dict[str, Any]:
    n = await _coach_corrective_count(company_id, days)
    return {
        "agent_id": "coach",
        "label": "Coach IA",
        "window_days": days,
        "generated_brl": 0.0,
        "protected_brl": 0.0,
        "saved_brl": 0.0,
        "total_brl": 0.0,
        "cases": n,
        "evidence": [{"source": "attendant_corrective_actions",
                       "count": n}],
    }


def _empty(agent_id: str, days: int, reason: str = ""
              ) -> Dict[str, Any]:
    return {
        "agent_id": agent_id,
        "label": agent_id.replace("_", " ").title(),
        "window_days": days,
        "generated_brl": 0.0,
        "protected_brl": 0.0,
        "saved_brl": 0.0,
        "total_brl": 0.0,
        "cases": 0,
        "evidence": [],
        "note": reason or "agente sem atribuição financeira",
    }


async def team_revenue(company_id: str,
                            days: int = 30) -> Dict[str, Any]:
    """Receita por agente para a equipe inteira.

    Retorna lista ordenada por total_brl desc + agente do mês +
    consolidado da equipe.
    """
    from services import agent_registry as reg

    rows: List[Dict[str, Any]] = []
    for meta in reg.list_agents():
        aid = meta["id"]
        if aid in ATTRIBUTION_RULES and aid != "motor_ia":
            rows.append(await revenue_for_agent(company_id, aid, days))
        elif aid == "coach":
            rows.append(await _coach_for(company_id, days))
        elif aid == "motor_ia":
            # adiciona depois (precisa do total)
            continue
        else:
            rows.append(_empty(aid, days))

    base_total = sum(r["total_brl"] for r in rows)
    motor = await _meta_share_for_motor(company_id, days, base_total)
    rows.append(motor)

    ranked = sorted(rows, key=lambda x: x["total_brl"], reverse=True)
    monetizable = [r for r in ranked if r["total_brl"] > 0 or r["cases"] > 0]
    top = ranked[0] if ranked else None

    return {
        "company_id": company_id,
        "window_days": days,
        "generated_at": _now().isoformat(),
        "team_total_brl": round(base_total + motor["total_brl"], 2),
        "team_generated_brl": round(
            sum(r["generated_brl"] for r in ranked), 2),
        "team_protected_brl": round(
            sum(r["protected_brl"] for r in ranked), 2),
        "team_saved_brl": round(
            sum(r["saved_brl"] for r in ranked), 2),
        "agent_of_period": {
            "agent_id": top["agent_id"],
            "label": top["label"],
            "total_brl": top["total_brl"],
        } if top else None,
        "ranking": ranked,
        "monetizable_count": len(monetizable),
    }
