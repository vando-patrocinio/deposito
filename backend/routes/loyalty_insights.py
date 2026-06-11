"""Insights de Relacionamento + Análise Chamados/Cancelamento + IA Winback.

Endpoints:
  - GET  /api/customer/loyalty/relationship-score
        → top clientes por relacionamento (pagamentos + chamados fechados)
  - GET  /api/customer/loyalty/tickets-vs-cancellations
        → série mensal: cancelamentos x chamados/títulos
  - POST /api/customer/loyalty-ai/winback-ready
        → IA analisa quem está na hora ideal de receber promoção
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

logger = logging.getLogger("ponto.loyalty_insights")
router = APIRouter(prefix="/api/customer", tags=["loyalty-insights"])

MODEL_NAME = "anthropic/claude-sonnet-4.6"

MONTHS_PT = ["jan", "fev", "mar", "abr", "mai", "jun",
              "jul", "ago", "set", "out", "nov", "dez"]


@router.get("/loyalty/relationship-score")
async def relationship_score(
    limit: int = 50,
    status: str = "Ativo",
    user: dict = Depends(require_role("gestor")),
):
    """Ranking de clientes por SCORE DE RELACIONAMENTO baseado em:
      - títulos pagos (peso 3)
      - chamados fechados (peso 1)
      - chamados abertos NÃO RESOLVIDOS (penalty -2)
      - títulos vencidos (penalty -5)
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    flt = {"company_id": cid}
    if status and status != "all":
        flt["status"] = status

    cursor = db.loyalty_imported_db.find(
        flt,
        {"_id": 0, "name": 1, "document": 1, "phone1": 1, "phone2": 1,
         "phone3": 1, "email": 1, "plan_name": 1, "monthly_fee": 1,
         "city": 1, "district": 1, "activation_date": 1,
         "installation_date": 1, "status": 1,
         "tickets_open": 1, "tickets_closed": 1,
         "invoices_paid": 1, "invoices_overdue": 1, "total_overdue": 1},
    ).limit(10000)

    items: list[dict] = []
    async for r in cursor:
        paid = r.get("invoices_paid") or 0
        closed = r.get("tickets_closed") or 0
        open_t = r.get("tickets_open") or 0
        overdue = r.get("invoices_overdue") or 0
        # Score = pagamentos*3 + chamados_fechados*1 - chamados_abertos*2 - vencidos*5
        score = paid * 3 + closed * 1 - open_t * 2 - overdue * 5
        items.append({
            "name": r.get("name") or "",
            "document": r.get("document") or "",
            "phones": [p for p in [r.get("phone1"), r.get("phone2"),
                                      r.get("phone3")] if p],
            "email": r.get("email"),
            "plan_name": r.get("plan_name") or "",
            "monthly_fee": r.get("monthly_fee"),
            "city": r.get("city") or "",
            "status": r.get("status"),
            "invoices_paid": paid,
            "tickets_closed": closed,
            "tickets_open": open_t,
            "invoices_overdue": overdue,
            "total_overdue": r.get("total_overdue") or 0,
            "score": score,
        })
    items.sort(key=lambda x: -x["score"])
    top = items[:limit]
    # Estatísticas agregadas
    total_paid = sum(i["invoices_paid"] for i in items)
    total_closed = sum(i["tickets_closed"] for i in items)
    total_open = sum(i["tickets_open"] for i in items)
    total_overdue_money = sum(i["total_overdue"] for i in items)
    return {
        "items": top,
        "count": len(top),
        "total_evaluated": len(items),
        "totals": {
            "invoices_paid": total_paid,
            "tickets_closed": total_closed,
            "tickets_open": total_open,
            "total_overdue_money": round(total_overdue_money, 2),
        },
    }


@router.get("/loyalty/tickets-vs-cancellations")
async def tickets_vs_cancellations(
    months: int = 13,
    user: dict = Depends(require_role("gestor")),
):
    """Série mensal: cancelamentos vs chamados/títulos da base.

    Como os chamados estão agregados POR CLIENTE (não por mês), a métrica
    "chamados_no_mes_X" é estimada via PROPORÇÃO: total_chamados ÷ meses_ativo.
    Para o mês corrente, retornamos contagens cumulativas reais.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    now = datetime.now(timezone.utc)

    # Cancelamentos por mês (real)
    cancels_by_ym: dict[str, int] = {}
    async for r in db.loyalty_imported_db.aggregate([
        {"$match": {"company_id": cid, "status": "Desativado",
                       "cancellation_date": {"$ne": None}}},
        {"$project": {"ym": {"$substr": ["$cancellation_date", 0, 7]}}},
        {"$group": {"_id": "$ym", "n": {"$sum": 1}}},
    ]):
        cancels_by_ym[r["_id"]] = r["n"]

    # Mesma coisa pra cadastros novos (NOVOS clientes, indicador positivo)
    new_by_ym: dict[str, int] = {}
    async for r in db.loyalty_imported_db.aggregate([
        {"$match": {"company_id": cid, "activation_date": {"$ne": None}}},
        {"$project": {"ym": {"$substr": ["$activation_date", 0, 7]}}},
        {"$group": {"_id": "$ym", "n": {"$sum": 1}}},
    ]):
        new_by_ym[r["_id"]] = r["n"]

    # Totais de chamados globais
    agg = await db.loyalty_imported_db.aggregate([
        {"$match": {"company_id": cid}},
        {"$group": {"_id": None,
                       "tk_open": {"$sum": "$tickets_open"},
                       "tk_closed": {"$sum": "$tickets_closed"},
                       "paid": {"$sum": "$invoices_paid"}}},
    ]).to_list(1)
    totals = agg[0] if agg else {"tk_open": 0, "tk_closed": 0, "paid": 0}

    # Gera série dos últimos N meses
    series = []
    for back in range(months):
        y = now.year
        m = now.month - back
        while m <= 0:
            m += 12
            y -= 1
        ym = f"{y}-{m:02d}"
        series.append({
            "ym": ym,
            "label": f"{MONTHS_PT[m - 1].capitalize()}/{str(y)[-2:]}",
            "year": y, "month": m,
            "cancellations": cancels_by_ym.get(ym, 0),
            "new_customers": new_by_ym.get(ym, 0),
        })
    series.reverse()  # asc por data

    # Trimestre atual
    cur_q = (now.month - 1) // 3 + 1
    q_months = [(now.year, mm)
                 for mm in range((cur_q - 1) * 3 + 1, cur_q * 3 + 1)]
    q_cancels = sum(cancels_by_ym.get(f"{y}-{m:02d}", 0)
                    for y, m in q_months)
    q_new = sum(new_by_ym.get(f"{y}-{m:02d}", 0) for y, m in q_months)

    return {
        "series": series,
        "current_quarter": {
            "label": f"{cur_q}º Trim/{str(now.year)[-2:]}",
            "year": now.year, "quarter": cur_q,
            "cancellations": q_cancels,
            "new_customers": q_new,
            "net_growth": q_new - q_cancels,
        },
        "globals": {
            "tickets_open_total": totals.get("tk_open", 0),
            "tickets_closed_total": totals.get("tk_closed", 0),
            "invoices_paid_total": totals.get("paid", 0),
        },
    }


def _parse_json_response(text: str) -> Optional[dict]:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


@router.post("/loyalty-ai/winback-ready")
async def winback_ready(user: dict = Depends(require_role("gestor"))):
    """IA Claude analisa quem está "na hora certa" de receber promoção.

    Critérios considerados:
      - Cancelamento recente (30-180 dias é hot)
      - Histórico de pagamentos (quanto mais, melhor)
      - Chamados majoritariamente RESOLVIDOS (relacionamento positivo)
      - Sem títulos vencidos (não foi calote)
      - Pelo menos 1 telefone válido
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=540)).isoformat()

    # Coleta candidatos com cancelamento ≤ 540 dias
    cands: list[dict] = []
    async for r in db.loyalty_imported_db.find(
        {"company_id": cid, "status": "Desativado",
         "cancellation_date": {"$gte": cutoff}},
        {"_id": 0},
    ).limit(5000):
        # Phones válidos
        phones = []
        for k in ("phone1", "phone2", "phone3"):
            p = (r.get(k) or "").strip()
            if p and len(p) >= 10 and p != "55":
                phones.append(p)
        if not phones:
            continue
        # Cancel age
        try:
            cd = datetime.fromisoformat(
                r["cancellation_date"].replace("Z", "+00:00"))
            if cd.tzinfo is None:
                cd = cd.replace(tzinfo=timezone.utc)
            days_since = (now - cd).days
        except Exception:
            continue
        if days_since < 14 or days_since > 540:
            continue
        # Engagement
        paid = r.get("invoices_paid") or 0
        closed = r.get("tickets_closed") or 0
        open_t = r.get("tickets_open") or 0
        overdue = r.get("invoices_overdue") or 0
        resolution_rate = (closed / (open_t + closed)) if (open_t + closed) > 0 else 0
        # Tenure antes
        tenure_m = 0
        inst = (r.get("installation_date") or r.get("activation_date")
                or r.get("registration_date"))
        if inst:
            try:
                d1 = datetime.fromisoformat(inst.replace("Z", "+00:00"))
                if d1.tzinfo is None:
                    d1 = d1.replace(tzinfo=timezone.utc)
                tenure_m = max(0, (cd - d1).days / 30.4375)
            except Exception:
                pass
        # Score determinístico (pré-IA)
        recency_bonus = max(0, 180 - days_since) / 180 if days_since <= 180 else 0
        tenure_score = min(60, tenure_m) / 60
        paid_score = min(60, paid) / 60
        resol_score = resolution_rate
        overdue_penalty = min(1.0, overdue / 6)
        score = round(
            (tenure_score * 25 + paid_score * 30 + resol_score * 20
              + recency_bonus * 25 - overdue_penalty * 30),
            1,
        )
        cands.append({
            "name": r.get("name") or "",
            "document": r.get("document") or "",
            "phones": phones,
            "email": r.get("email"),
            "city": r.get("city") or "",
            "district": r.get("district") or "",
            "plan_name": r.get("plan_name") or "",
            "monthly_fee": r.get("monthly_fee"),
            "tenure_months": round(tenure_m, 1),
            "days_since_cancel": days_since,
            "invoices_paid": paid,
            "tickets_closed": closed,
            "tickets_open": open_t,
            "invoices_overdue": overdue,
            "resolution_rate": round(resolution_rate, 2),
            "score": score,
        })
    cands.sort(key=lambda x: -x["score"])
    top_50 = cands[:50]

    if not top_50:
        return {"ok": False, "message": "Nenhum candidato elegível.",
                  "candidates": []}

    # IA categoriza em 3 tiers + sugere oferta personalizada
    prompt = f"""Você é um especialista em winback B2C para ISP brasileiro.
Analise os 50 ex-clientes ABAIXO e classifique cada um em 3 tiers de
prioridade pra receber promoção AGORA, com a oferta ideal pra cada perfil.

Dados de cada candidato:
- Tempo de casa antes do cancel (tenure_months)
- Dias desde o cancelamento (days_since_cancel)
- Histórico: títulos pagos, chamados fechados/abertos, títulos vencidos
- Plano que tinha, mensalidade, cidade

DADOS:
{json.dumps(top_50, indent=2, ensure_ascii=False)}

# RESPOSTA EM JSON (sem markdown):
{{
  "summary": "resumo executivo (2-3 frases) sobre o grupo analisado",
  "tiers": {{
    "tier_a_imediato": {{
      "count": <int>,
      "description": "perfil dos clientes neste tier",
      "recommended_offer": "oferta concreta (ex: 'plano original com 40% off por 3 meses')",
      "approach": "como abordar (WhatsApp + ligação + e-mail, em qual ordem)",
      "estimated_conversion": "ex: '30-40%'"
    }},
    "tier_b_promocional": {{...mesmo formato...}},
    "tier_c_cuidado": {{...mesmo formato — clientes com vencidos, histórico ruim, exigir cautela...}}
  }},
  "classification": [
    {{"document": "<cpf>", "tier": "A|B|C", "personalized_offer": "string", "reason": "string curta"}}
    /* 1 entrada por candidato */
  ],
  "global_warnings": ["alerta 1", "alerta 2"]
}}

REGRAS:
- Tier A: melhor relação, baixo risco, alta probabilidade de aceitar
- Tier B: relação ok, oferta padrão promocional
- Tier C: clientes com vencidos ou chamados problemáticos, abordar com cautela
- Use os números reais. Cite valores específicos quando possível.
"""

    try:
        result = await chat_completion(
            company_id=cid,
            messages=[
                {"role": "system", "content": (
                    "Você é um analista sênior de winback ISP. "
                    "Devolva SEMPRE JSON puro, sem markdown."
                )},
                {"role": "user", "content": prompt},
            ],
            model=MODEL_NAME,
            temperature=0.4,
            max_tokens=10000,
            json_mode=True,
            purpose="general",
            agent="loyalty_winback_ready",
        )
    except RuntimeError as e:
        raise HTTPException(
            500,
            f"OpenRouter não configurado: {e}",
        )
    except Exception as e:
        logger.exception("[winback-ready] LLM err")
        raise HTTPException(502, f"LLM err: {e}")
    text = result.get("content") or ""
    insights = _parse_json_response(text)
    if not insights:
        raise HTTPException(502, "LLM retornou formato inválido.")

    # Cria mapa cpf → tier+offer pra mergir
    cls_map = {c["document"]: c
                for c in (insights.get("classification") or [])}
    for cand in top_50:
        cls = cls_map.get(cand["document"], {})
        cand["ai_tier"] = cls.get("tier") or "B"
        cand["ai_offer"] = cls.get("personalized_offer") or ""
        cand["ai_reason"] = cls.get("reason") or ""

    now_iso = now.isoformat()
    doc = {
        "company_id": cid, "generated_at": now_iso,
        "generated_by": user.get("email") or user.get("id"),
        "model": result.get("model") or MODEL_NAME,
        "candidates": top_50,
        "insights": insights,
    }
    await db.loyalty_winback_ready.insert_one(doc)
    return {
        "ok": True,
        "generated_at": now_iso,
        "model": doc["model"],
        "total_eligible": len(cands),
        "top": top_50,
        "insights": insights,
    }


@router.get("/loyalty-ai/winback-ready")
async def get_last_winback_ready(
    user: dict = Depends(require_role("gestor")),
):
    """Retorna a última análise salva."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = await db.loyalty_winback_ready.find_one(
        {"company_id": cid}, {"_id": 0},
        sort=[("generated_at", -1)],
    )
    if not doc:
        return {"cached": False}
    try:
        gen = datetime.fromisoformat(
            doc["generated_at"].replace("Z", "+00:00"))
        if gen.tzinfo is None:
            gen = gen.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - gen).total_seconds() / 3600
    except Exception:
        age_h = 999
    return {"cached": True, "age_hours": round(age_h, 1), **doc}
