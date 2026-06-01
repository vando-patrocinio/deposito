"""KPI · Retenção / Churn — análise dos motivos de cancelamento das OS de
retirada finalizadas.

GET /api/kpis/churn-reasons?period_days=30 → agregado por categoria,
                                              top 10 detalhes, série diária.

Lê de `tickets` onde `type=retirada`, `status=fechado` e
`completion_data.cancel_reason_category` está preenchido.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, EMERGENT_LLM_KEY, get_current_user
from database import db

logger = logging.getLogger("kpi_churn")

router = APIRouter()

# Catálogo de categorias com label + cor (espelha o frontend)
CATEGORY_META: Dict[str, Dict[str, str]] = {
    "preco":        {"label": "Preço / custo elevado",        "color": "#dc2626", "icon": "💰"},
    "atendimento":  {"label": "Insatisfação com atendimento",  "color": "#ea580c", "icon": "📞"},
    "qualidade":    {"label": "Problemas técnicos / qualidade", "color": "#d97706", "icon": "📡"},
    "mudanca":      {"label": "Mudança de endereço",            "color": "#0891b2", "icon": "🚚"},
    "concorrente":  {"label": "Migração para concorrente",      "color": "#7c3aed", "icon": "🔁"},
    "financeiro":   {"label": "Dificuldade financeira",         "color": "#65a30d", "icon": "💳"},
    "nao_usa":      {"label": "Não usa mais",                   "color": "#64748b", "icon": "🛌"},
    "outros":       {"label": "Outros",                         "color": "#94a3b8", "icon": "❓"},
}


class CategoryAgg(BaseModel):
    key: str
    label: str
    icon: str
    color: str
    count: int
    pct: float


class DailyPoint(BaseModel):
    date: str
    total: int


class DetailEntry(BaseModel):
    ticket_id: str
    client_name: str
    category: str
    category_label: str
    observacoes: str
    closed_at: Optional[str]
    technician: Optional[str]


class ChurnReasonsResp(BaseModel):
    period_days: int
    period_start: str
    period_end: str
    total_retiradas: int
    total_categorized: int
    coverage_pct: float
    categories: List[CategoryAgg]
    top_category: Optional[CategoryAgg]
    daily: List[DailyPoint]
    recent_details: List[DetailEntry]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/api/kpis/churn-reasons", response_model=ChurnReasonsResp)
async def churn_reasons(
    period_days: int = Query(30, ge=1, le=365),
    user: dict = Depends(get_current_user),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    end = _now_utc()
    start = end - timedelta(days=period_days)

    query: Dict[str, Any] = {
        "company_id": cid,
        "type": "retirada",
        "status": "fechado",
        "closed_at": {"$gte": start.isoformat(), "$lte": end.isoformat()},
    }

    docs: List[Dict[str, Any]] = await db.tickets.find(
        query,
        {
            "_id": 0, "id": 1, "client_snapshot": 1, "closed_at": 1,
            "completion_data": 1, "collaborator_id": 1, "closed_by_name": 1,
        },
    ).to_list(length=2000)

    total_retiradas = len(docs)
    counts: Dict[str, int] = {}
    daily_map: Dict[str, int] = {}
    details: List[DetailEntry] = []

    for d in docs:
        cd = d.get("completion_data") or {}
        cat = cd.get("cancel_reason_category")
        if not cat:
            continue
        key = cat if cat in CATEGORY_META else "outros"
        counts[key] = counts.get(key, 0) + 1
        ca_iso = d.get("closed_at") or ""
        day = ca_iso[:10] if ca_iso else ""
        if day:
            daily_map[day] = daily_map.get(day, 0) + 1
        details.append(DetailEntry(
            ticket_id=d.get("id", ""),
            client_name=(d.get("client_snapshot") or {}).get("name", "—"),
            category=key,
            category_label=CATEGORY_META[key]["label"],
            observacoes=(cd.get("observacoes") or "").strip(),
            closed_at=d.get("closed_at"),
            technician=d.get("closed_by_name"),
        ))

    total_categorized = sum(counts.values())
    coverage = (total_categorized / total_retiradas * 100.0) if total_retiradas else 0.0

    cats: List[CategoryAgg] = []
    for key, meta in CATEGORY_META.items():
        cnt = counts.get(key, 0)
        cats.append(CategoryAgg(
            key=key, label=meta["label"], icon=meta["icon"], color=meta["color"],
            count=cnt,
            pct=round((cnt / total_categorized * 100.0) if total_categorized else 0.0, 1),
        ))
    cats.sort(key=lambda c: c.count, reverse=True)
    top = cats[0] if cats and cats[0].count > 0 else None

    # Série diária preenchida (zero-fill)
    daily: List[DailyPoint] = []
    cursor = start
    while cursor <= end:
        day = cursor.strftime("%Y-%m-%d")
        daily.append(DailyPoint(date=day, total=daily_map.get(day, 0)))
        cursor += timedelta(days=1)

    details.sort(key=lambda x: x.closed_at or "", reverse=True)

    return ChurnReasonsResp(
        period_days=period_days,
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        total_retiradas=total_retiradas,
        total_categorized=total_categorized,
        coverage_pct=round(coverage, 1),
        categories=cats,
        top_category=top,
        daily=daily,
        recent_details=details[:20],
    )



_AI_SYSTEM = """Você é o NEO, analista sênior de retenção de uma operadora de \
internet brasileira (ISP). Receberá uma lista de motivos de cancelamento \
preenchidos pelos técnicos no momento da retirada do equipamento.

Sua tarefa: identificar temas recorrentes nos textos livres, quantificar e \
sugerir ações práticas. Pense como um diretor de retenção que decide onde \
investir o próximo R$ pra reduzir o churn.

Responda APENAS em JSON válido com este schema EXATO:

{
  "themes": [
    {
      "title": "string curta (3-6 palavras) descrevendo o tema",
      "category": "preco|atendimento|qualidade|mudanca|concorrente|financeiro|nao_usa|outros",
      "count": int (quantos cancelamentos batem nesse tema),
      "evidence_quotes": ["citação 1 (max 80 chars)", "citação 2"],
      "recommended_action": "ação prática e específica (1-2 frases)",
      "potential_savings_clients_per_month": int (chute conservador, 0 se não estimar)
    }
  ],
  "executive_summary": "parágrafo único (max 600 chars) com a leitura geral",
  "top_risk": "categoria/tema que pede atenção URGENTE (max 120 chars)"
}

Regras:
- Identifique entre 3 e 6 temas mais relevantes.
- Se houver pouquíssimos dados (<5), gere temas amplos e marque counts baixos.
- evidence_quotes devem ser TRECHOS REAIS das observações, sem inventar.
- recommended_action deve ser acionável (ex: "Treinar atendentes em Q1 sobre tempo de resposta < 5min"), evitar genérico.
- Português do Brasil, sem hashtags, sem markdown."""


class ThemeOut(BaseModel):
    title: str
    category: str
    count: int
    evidence_quotes: List[str]
    recommended_action: str
    potential_savings_clients_per_month: int = 0


class AiInsightsResp(BaseModel):
    period_days: int
    sample_size: int
    themes: List[ThemeOut]
    executive_summary: str
    top_risk: str
    generated_at: str
    model: str = "claude-sonnet-4-6"


@router.post("/api/kpis/churn-reasons/ai-insights",
              response_model=AiInsightsResp)
async def churn_ai_insights(
    period_days: int = Query(30, ge=7, le=365),
    user: dict = Depends(get_current_user),
):
    """Analisa as observações de cancelamento via Claude 4.6 e devolve temas
    recorrentes + ações sugeridas. Cache leve: regenera no máximo a cada 30min
    por (company_id, period_days)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=period_days)

    cache_key = f"churn-ai:{cid}:{period_days}"
    try:
        cached = await db.aihub_cache.find_one({"key": cache_key}, {"_id": 0})
    except Exception:
        cached = None
    if cached:
        try:
            ts = datetime.fromisoformat(cached["generated_at"])
            if (end - ts).total_seconds() < 1800:  # 30min
                return AiInsightsResp(**cached["payload"])
        except Exception:
            pass

    docs = await db.tickets.find({
        "company_id": cid, "type": "retirada", "status": "fechado",
        "closed_at": {"$gte": start.isoformat(), "$lte": end.isoformat()},
    }, {
        "_id": 0, "id": 1, "client_snapshot": 1,
        "completion_data": 1, "closed_at": 1,
    }).to_list(length=500)

    samples: List[Dict[str, Any]] = []
    for d in docs:
        cd = d.get("completion_data") or {}
        obs = (cd.get("observacoes") or "").strip()
        cat = cd.get("cancel_reason_category")
        if not obs or not cat:
            continue
        samples.append({
            "categoria": cat,
            "obs": obs[:400],
            "data": (d.get("closed_at") or "")[:10],
        })

    if not samples:
        raise HTTPException(
            400,
            "Sem observações categorizadas no período. "
            "Aguarde os técnicos preencherem mais retiradas.",
        )

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage  # noqa: PLC0415
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"churn-ai-{uuid.uuid4().hex[:10]}",
            system_message=_AI_SYSTEM,
        ).with_model("anthropic", "claude-sonnet-4-6")

        prompt = ("Analise estes "
                  f"{len(samples)} cancelamentos da janela de "
                  f"{period_days} dias e devolva o JSON do schema. Dados:\n"
                  + json.dumps(samples, ensure_ascii=False, indent=0))

        resp = await chat.send_message(UserMessage(text=prompt))
        text = (resp or "").strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text)
        themes = [ThemeOut(**t) for t in (parsed.get("themes") or [])]
        out = AiInsightsResp(
            period_days=period_days,
            sample_size=len(samples),
            themes=themes,
            executive_summary=parsed.get("executive_summary", ""),
            top_risk=parsed.get("top_risk", ""),
            generated_at=end.isoformat(),
        )
        try:
            await db.aihub_cache.update_one(
                {"key": cache_key},
                {"$set": {
                    "key": cache_key,
                    "payload": out.dict(),
                    "generated_at": out.generated_at,
                }},
                upsert=True,
            )
        except Exception:
            pass
        return out
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("[churn-ai] falha: %s", e, exc_info=True)
        raise HTTPException(500, f"Análise IA falhou: {e}") from e
