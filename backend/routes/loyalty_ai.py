"""Clientes IA — análise inteligente da base de fidelidade com Claude via OpenRouter.

Endpoints:
  - GET  /api/customer/loyalty-ai/insights  → análise atual cacheada (24h)
  - POST /api/customer/loyalty-ai/regenerate → recomputa (força refresh)

A IA recebe um RESUMO ESTATÍSTICO da base (não envia dados pessoais
brutos pra LLM) e devolve:
  1. Top 5 oportunidades de winback (clientes desativados)
  2. Top 5 oportunidades de upgrade (clientes ativos)
  3. VIPs em risco de churn
  4. Estratégias de retenção priorizadas
  5. Plano de ação concreto com prazo

iter215j — Modelo: anthropic/claude-sonnet-4.5 via OpenRouter (chave
configurada em Configurações → AI Keys). Não usa Emergent LLM Key.
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

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, require_role
from database import db
from services.motor_ia import chat_completion

logger = logging.getLogger("ponto.loyalty_ai")
router = APIRouter(prefix="/api/customer/loyalty-ai", tags=["loyalty-ai"])

CACHE_HOURS = 24
# iter215j — Modelo Claude mais recente disponível no OpenRouter
# (Sonnet 4.6 — lançado 17/02/2026, 1M context).
MODEL_NAME = "anthropic/claude-sonnet-4.6"


async def _build_summary(cid: str) -> dict:
    """Monta resumo agregado pra alimentar a IA (sem dados pessoais).
    Inclui:
      - Distribuição por status, tempo de casa, plano
      - Top motivos / praças de churn
      - Migração: regiões com mais oportunidades
    """
    # === Base XLSX agregada ===
    total = await db.loyalty_imported_db.count_documents({"company_id": cid})

    by_status_cur = db.loyalty_imported_db.aggregate([
        {"$match": {"company_id": cid}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ])
    by_status = [{"status": s["_id"] or "—", "count": s["count"]}
                  async for s in by_status_cur]

    by_city_cur = db.loyalty_imported_db.aggregate([
        {"$match": {"company_id": cid}},
        {"$group": {"_id": "$city", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ])
    by_city = [{"city": c["_id"] or "—", "count": c["count"]}
                async for c in by_city_cur]

    # Top planos perdidos (desativados)
    by_plan_lost_cur = db.loyalty_imported_db.aggregate([
        {"$match": {"company_id": cid, "status": "Desativado"}},
        {"$group": {"_id": "$plan_name", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 15},
    ])
    plans_lost = [{"plan": p["_id"] or "—", "count": p["count"]}
                   async for p in by_plan_lost_cur]

    # Top planos ativos
    by_plan_active_cur = db.loyalty_imported_db.aggregate([
        {"$match": {"company_id": cid, "status": "Ativo"}},
        {"$group": {
            "_id": "$plan_name",
            "count": {"$sum": 1},
            "avg_fee": {"$avg": "$monthly_fee"},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 15},
    ])
    plans_active = [
        {"plan": p["_id"] or "—", "count": p["count"],
         "avg_fee": round(p.get("avg_fee") or 0, 2)}
        async for p in by_plan_active_cur
    ]

    # === Churn rate ===
    total_active = sum(s["count"] for s in by_status if s["status"] == "Ativo")
    total_deact = sum(s["count"] for s in by_status if s["status"] == "Desativado")
    churn_pct = round(100 * total_deact / max(1, total_active + total_deact), 1)

    # === Desativados recentes (≤90 dias) por cidade — alvo prioritário ===
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    recent_lost_cur = db.loyalty_imported_db.aggregate([
        {"$match": {
            "company_id": cid, "status": "Desativado",
            "cancellation_date": {"$gte": cutoff},
        }},
        {"$group": {"_id": "$city", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 8},
    ])
    recent_lost = [{"city": c["_id"] or "—", "count": c["count"]}
                    async for c in recent_lost_cur]
    total_recent_lost = sum(c["count"] for c in recent_lost)

    # === VIPs (5+ anos) cancelados — alvo de winback premium ===
    vips_lost_cur = db.loyalty_imported_db.aggregate([
        {"$match": {"company_id": cid, "status": "Desativado",
                       "installation_date": {"$ne": None},
                       "cancellation_date": {"$ne": None}}},
        {"$addFields": {
            "tenure_days": {"$divide": [
                {"$subtract": [
                    {"$dateFromString": {"dateString": "$cancellation_date"}},
                    {"$dateFromString": {"dateString": "$installation_date"}},
                ]},
                1000 * 60 * 60 * 24,
            ]},
        }},
        {"$match": {"tenure_days": {"$gte": 1825}}},  # 5 anos
        {"$count": "vips_lost"},
    ])
    vips_lost = 0
    async for v in vips_lost_cur:
        vips_lost = v.get("vips_lost", 0)

    return {
        "total_base": total,
        "total_active": total_active,
        "total_deactivated": total_deact,
        "churn_rate_pct": churn_pct,
        "by_status": by_status,
        "top_cities": by_city,
        "top_plans_active": plans_active,
        "top_plans_lost": plans_lost,
        "recent_lost_90d": recent_lost,
        "total_recent_lost_90d": total_recent_lost,
        "vips_lost_5y_plus": vips_lost,
    }


def _build_prompt(summary: dict) -> str:
    return f"""Você é um especialista em ESTRATÉGIA DE RETENÇÃO e
WINBACK pra provedores de internet (ISP). Analise os dados abaixo e
retorne um JSON estruturado com plano de ação concreto.

# DADOS DA BASE
- Total de clientes na base: {summary['total_base']:,}
- Ativos: {summary['total_active']:,} | Desativados: {summary['total_deactivated']:,}
- Taxa de churn: {summary['churn_rate_pct']}%
- VIPs (5+ anos) que cancelaram: {summary['vips_lost_5y_plus']}
- Cancelamentos últimos 90 dias: {summary['total_recent_lost_90d']}

## Top cidades:
{json.dumps(summary['top_cities'], indent=2, ensure_ascii=False)}

## Planos ativos (com volume + ticket médio):
{json.dumps(summary['top_plans_active'], indent=2, ensure_ascii=False)}

## Top planos PERDIDOS (mais cancelados):
{json.dumps(summary['top_plans_lost'], indent=2, ensure_ascii=False)}

## Cancelamentos recentes (90d) por cidade:
{json.dumps(summary['recent_lost_90d'], indent=2, ensure_ascii=False)}

# RESPOSTA EM JSON
Retorne SOMENTE um JSON válido com a seguinte estrutura (sem texto extra,
sem markdown, sem ```json):

{{
  "executive_summary": "Resumo executivo em 2-3 frases (português BR).",
  "health_score": <0-100>,
  "top_winback_opportunities": [
    {{
      "title": "string curta (até 60 chars)",
      "description": "descrição prática (até 200 chars)",
      "target_segment": "segmento específico (ex: 'Cancelados Rio últimos 60d com plano 100-300MB')",
      "estimated_impact": "ex: 'Recuperar 40-60 clientes/mês'",
      "priority": "alta|media|baixa",
      "action_steps": ["passo 1", "passo 2", "passo 3"]
    }}
  ],
  "top_retention_strategies": [
    {{
      "title": "string",
      "description": "string",
      "target_segment": "string",
      "estimated_impact": "string",
      "priority": "alta|media|baixa",
      "action_steps": ["..."]
    }}
  ],
  "upgrade_opportunities": [
    {{
      "title": "string",
      "description": "string",
      "target_segment": "string",
      "estimated_impact": "string",
      "priority": "alta|media|baixa",
      "action_steps": ["..."]
    }}
  ],
  "risk_alerts": ["alerta 1", "alerta 2", "alerta 3"],
  "30_day_action_plan": [
    {{"week": 1, "actions": ["...", "..."]}},
    {{"week": 2, "actions": ["..."]}},
    {{"week": 3, "actions": ["..."]}},
    {{"week": 4, "actions": ["..."]}}
  ]
}}

Foque em ações ACIONÁVEIS, NÚMEROS e SEGMENTAÇÃO. Liste mín 3, máx 5 itens em cada categoria.
"""


def _parse_json_response(text: str) -> Optional[dict]:
    """Extrai JSON de uma resposta da LLM, tolerando markdown wrappers."""
    if not text:
        return None
    # Tenta direto
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Extrai bloco entre primeiro { e último }
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


async def _run_claude(company_id: str, prompt: str) -> dict:
    """Chama Claude via OpenRouter (motor_ia.chat_completion) e devolve dict."""
    try:
        result = await chat_completion(
            company_id=company_id,
            messages=[
                {"role": "system", "content": (
                    "Você é um analista sênior de retenção em ISP brasileiro. "
                    "Devolva SEMPRE JSON puro, sem markdown, sem ```json."
                )},
                {"role": "user", "content": prompt},
            ],
            model=MODEL_NAME,
            temperature=0.5,
            max_tokens=8000,
            json_mode=True,
            purpose="general",
            agent="loyalty_ai",
        )
    except RuntimeError as e:
        # Motor IA não configurado — orienta o user
        raise HTTPException(
            500,
            f"OpenRouter não configurado. {e}. "
            "Vá em Configurações → AI Keys e adicione sua chave OpenRouter.",
        )
    except Exception as e:
        logger.exception("[loyalty-ai] Falha chamando Claude via OpenRouter")
        raise HTTPException(502, f"Falha no LLM: {e}")
    text = result.get("content") or ""
    parsed = _parse_json_response(text)
    if not parsed:
        logger.error("[loyalty-ai] resposta inválida: %s", text[:500])
        raise HTTPException(502, "LLM retornou formato inválido.")
    return {"parsed": parsed,
            "model": result.get("model") or MODEL_NAME,
            "provider": result.get("provider") or "openrouter"}


@router.get("/insights")
async def get_insights(user: dict = Depends(require_role("gestor"))):
    """Retorna insights cacheados (24h). Se não houver, retorna 204."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.loyalty_ai_insights.find_one(
        {"company_id": cid}, {"_id": 0},
        sort=[("generated_at", -1)],
    )
    if not doc:
        return {"cached": False, "insights": None, "summary": None}
    # Verifica se ainda é válido
    try:
        gen = datetime.fromisoformat(doc["generated_at"].replace("Z", "+00:00"))
        if gen.tzinfo is None:
            gen = gen.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - gen).total_seconds() / 3600
    except Exception:
        age_h = 999
    return {
        "cached": True,
        "stale": age_h > CACHE_HOURS,
        "generated_at": doc["generated_at"],
        "age_hours": round(age_h, 1),
        "model": doc.get("model"),
        "summary": doc.get("summary"),
        "insights": doc.get("insights"),
    }


class RegenerateBody(BaseModel):
    force: bool = True


@router.post("/regenerate")
async def regenerate_insights(
    body: RegenerateBody = RegenerateBody(),  # noqa: B008
    user: dict = Depends(require_role("gestor")),
):
    """Recomputa análise via Claude (OpenRouter). Salva no cache."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    summary = await _build_summary(cid)
    if summary["total_base"] == 0:
        raise HTTPException(400, "Base vazia — importe a planilha XLSX primeiro.")
    prompt = _build_prompt(summary)
    result = await _run_claude(cid, prompt)
    insights = result["parsed"]
    now_iso = datetime.now(timezone.utc).isoformat()
    doc = {
        "company_id": cid,
        "generated_at": now_iso,
        "generated_by": user.get("email") or user.get("id"),
        "model": result["model"],
        "provider": result["provider"],
        "summary": summary,
        "insights": insights,
    }
    await db.loyalty_ai_insights.insert_one(doc)
    return {
        "ok": True,
        "generated_at": now_iso,
        "model": result["model"],
        "provider": result["provider"],
        "summary": summary,
        "insights": insights,
    }


# ----- "Top oportunidades" rápidas (sem LLM) — usadas no painel Desativados -
@router.get("/top-winback-targets")
async def top_winback_targets(
    limit: int = 50,
    user: dict = Depends(require_role("gestor")),
):
    """Lista clientes desativados COM MAIOR potencial de winback, baseada
    em score = tenure_anterior + ticket + tempo_desde_cancel."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cursor = db.loyalty_imported_db.find(
        {"company_id": cid, "status": "Desativado",
         "cancellation_date": {"$ne": None}},
        {"_id": 0},
    ).limit(5000)
    items: list[dict] = []
    now = datetime.now(timezone.utc)
    async for r in cursor:
        try:
            cancel = datetime.fromisoformat(
                r["cancellation_date"].replace("Z", "+00:00"))
            if cancel.tzinfo is None:
                cancel = cancel.replace(tzinfo=timezone.utc)
            days_since = (now - cancel).days
        except Exception:
            continue
        # Ignora cancelados há mais de 18 meses (gente fria) ou < 7 dias (muito quente)
        if days_since > 540 or days_since < 7:
            continue
        # Tenure antes do cancel
        tenure_months = 0
        inst = (r.get("installation_date") or r.get("activation_date")
                or r.get("registration_date"))
        if inst:
            try:
                d1 = datetime.fromisoformat(inst.replace("Z", "+00:00"))
                if d1.tzinfo is None:
                    d1 = d1.replace(tzinfo=timezone.utc)
                tenure_months = max(0, (cancel - d1).days / 30.4375)
            except Exception:
                pass
        fee = float(r.get("monthly_fee") or 0)
        # SCORE: tempo de casa (peso 2) + ticket (peso 1) - distância do cancel
        # quanto mais recente o cancel + mais antigo o cliente + mais alto o ticket = mais quente
        recency_bonus = max(0, 180 - days_since) / 180  # 0..1
        tenure_score = min(60, tenure_months) / 60  # cap 5y
        ticket_score = min(200, fee) / 200
        score = round(
            (tenure_score * 2 + ticket_score * 1.5 + recency_bonus * 2) * 100,
            1,
        )
        items.append({
            "name": r.get("name") or "",
            "document": r.get("document") or "",
            "phone": r.get("phone1") or "",
            "city": r.get("city") or "",
            "district": r.get("district") or "",
            "plan_name": r.get("plan_name") or "",
            "monthly_fee": fee,
            "tenure_months": round(tenure_months, 1),
            "days_since_cancel": days_since,
            "cancellation_date": r.get("cancellation_date"),
            "score": score,
        })
    items.sort(key=lambda x: -x["score"])
    return {
        "items": items[:limit],
        "count": len(items[:limit]),
        "total_evaluated": len(items),
    }
