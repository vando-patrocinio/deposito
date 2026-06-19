"""Motor IA — endpoints REST para a aba Sistemas → Motor IA."""
from __future__ import annotations


from services.exception_sanitizer import safe_detail  # SECURITY_LOCK ART.13
NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, require_role
from database import db
from services.motor_ia import (
    get_motor_config, get_safe_config, save_motor_config, test_motor,
    DEFAULT_FALLBACKS, AGENT_CATALOG, get_agents_state, set_agent_state,
    get_agent_history,
)

router = APIRouter(prefix="/api/motor-ia", tags=["motor-ia"])


class MotorConfigIn(BaseModel):
    openrouter_api_key: Optional[str] = Field(None, max_length=200)
    default_text_model: Optional[str] = Field(None, max_length=120)
    fallback_models: Optional[List[str]] = None
    atendimento_model: Optional[str] = Field(None, max_length=120)
    atendimento_fallbacks: Optional[List[str]] = None
    openai_audio_key: Optional[str] = Field(None, max_length=200)
    tts_voice: Optional[str] = Field(None, max_length=20)
    enabled: Optional[bool] = None


@router.get("/config")
async def read_config(user: dict = Depends(require_role("administrador"))):
    """Retorna config com keys mascaradas (segurança)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await get_safe_config(cid)


@router.put("/config")
async def update_config(payload: MotorConfigIn,
                          user: dict = Depends(require_role("administrador"))):
    """Atualiza config. Keys vazias preservam valores existentes;
    para limpar uma key, mandar string com 'CLEAR'."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    data = payload.model_dump(exclude_none=True)
    # Modelo de atendimento — antes era restrito a DeepSeek. Hoje aceitamos
    # qualquer modelo do OpenRouter (DeepSeek/Claude/Gemini/GPT). Validação
    # mínima: formato "vendor/modelo".
    if "atendimento_model" in data and data["atendimento_model"]:
        if "/" not in str(data["atendimento_model"]):
            raise HTTPException(
                400,
                "Use o formato 'vendor/modelo' (ex.: deepseek/deepseek-chat, "
                "anthropic/claude-3.5-sonnet, openai/gpt-4o-mini).",
            )
    if "atendimento_fallbacks" in data and data["atendimento_fallbacks"]:
        data["atendimento_fallbacks"] = [
            m for m in data["atendimento_fallbacks"]
            if isinstance(m, str) and "/" in m
        ]
    # Permite "CLEAR" para apagar uma key
    for k in ("openrouter_api_key", "openai_audio_key"):
        if data.get(k) == "CLEAR":
            data[k] = ""
        elif data.get(k) == "":
            # String vazia significa "não alterar" — usuário não digitou nova
            data.pop(k, None)
    await save_motor_config(cid, data)
    return await get_safe_config(cid)


@router.post("/test")
async def test_motor_endpoint(user: dict = Depends(require_role("administrador"))):
    """Faz uma chamada de teste no OpenRouter pra validar credenciais."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await test_motor(cid)


# Budget mensal — GET/PUT (iter232) ---------------------------------------
@router.get("/budget")
async def read_budget(user: dict = Depends(require_role("gestor"))):
    """Retorna limite mensal e gasto atual do mês.

    Leitura liberada para gestor (necessário para BudgetAlertBadge no TopBar e
    cards de uso). Escrita (PUT) continua restrita a administrador.
    """
    from datetime import datetime, timezone
    cid = user.get("company_id") or DEMO_COMPANY_ID
    b = await db.motor_ia_budget.find_one({"company_id": cid}, {"_id": 0}) or {}
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0,
                          microsecond=0).isoformat()
    pipe = [
        {"$match": {"company_id": cid, "created_at": {"$gte": start}}},
        {"$group": {"_id": None, "spent": {"$sum": "$estimated_cost_usd"}}},
    ]
    agg = await db.motor_ia_usage.aggregate(pipe).to_list(1)
    spent = float(agg[0]["spent"]) if agg else 0.0
    limit = float(b.get("monthly_limit_usd") or 0)
    return {
        "monthly_limit_usd": limit,
        "spent_month_usd": round(spent, 4),
        "used_pct": round((spent / limit * 100), 1) if limit else 0,
        "warn_threshold_pct": int(b.get("warn_threshold_pct") or 80),
        "enabled": bool(b.get("enabled", True)),
    }


class BudgetIn(BaseModel):
    monthly_limit_usd: float = Field(..., ge=0, le=100000)
    warn_threshold_pct: Optional[int] = Field(80, ge=10, le=99)


@router.put("/budget")
async def update_budget(payload: BudgetIn,
                          user: dict = Depends(require_role("administrador"))):
    """Atualiza limite mensal de gasto do Motor IA (US$)."""
    from datetime import datetime, timezone
    cid = user.get("company_id") or DEMO_COMPANY_ID
    now = datetime.now(timezone.utc).isoformat()
    await db.motor_ia_budget.update_one(
        {"company_id": cid},
        {"$set": {"company_id": cid,
                    "monthly_limit_usd": float(payload.monthly_limit_usd),
                    "warn_threshold_pct": int(payload.warn_threshold_pct or 80),
                    "enabled": True,
                    "updated_at": now,
                    "updated_by": user.get("email") or user.get("id")}},
        upsert=True)
    return await read_budget(user=user)



@router.get("/models/suggested")
async def suggested_models(user: dict = Depends(require_role("gestor"))):
    """Lista curada de modelos recomendados por tier."""
    return {
        "tiers": [
            {"id": "fast", "label": "Rápido & barato",
             "models": ["anthropic/claude-haiku-4.5", "openai/gpt-4o-mini",
                          "google/gemini-2.0-flash-exp:free"]},
            {"id": "balanced", "label": "Equilíbrio (recomendado)",
             "models": ["anthropic/claude-sonnet-4.5", "openai/gpt-4o",
                          "meta-llama/llama-3.3-70b-instruct"]},
            {"id": "premium", "label": "Qualidade máxima",
             "models": ["anthropic/claude-opus-4.5", "anthropic/claude-sonnet-4.5",
                          "openai/gpt-4o"]},
            {"id": "free", "label": "Apenas grátis (limite por dia)",
             "models": ["google/gemini-2.0-flash-exp:free",
                          "meta-llama/llama-3.3-70b-instruct:free"]},
        ],
        "default_fallbacks": DEFAULT_FALLBACKS,
    }


# ---------------------------------------------------------------------------
# Dashboard de custos — agrega tokens/USD do collection `motor_ia_usage`
# ---------------------------------------------------------------------------

# Mapeamento de agentes para rótulos amigáveis exibidos no dashboard.
AGENT_LABELS: Dict[str, str] = {
    "smartolt_ai":        "SmartOLT AI",
    "sentinela_lousa":    "Sentinela Lousa",
    "lousa_triagem":      "Lousa Triagem",
    "copilot_ai":         "Co-Pilot IA",
    "isabella_whatsapp":  "Isabella (WhatsApp)",
    "isabella_vision":    "Isabella · Visão (imagens)",
    "isabella_tts":       "Isabella · TTS (voz)",
    "isabella_stt":       "Isabella · STT (Whisper)",
    "aihub_chat":         "AI Hub · Chat",
    "aihub_textgen":      "AI Hub · TextGen",
    "central_ia_eval":    "Central IA · Avaliação",
    "central_ia_coach":   "Central IA · Coaching",
    "voice_ai":           "Voice AI",
    "ai_dashboard_insight": "Dashboard Insights",
    "churn_insight":      "Churn Insight",
    "proactive_outage_context": "Contexto de Pane (proativo)",
    "general":            "Outros (geral)",
    "atendimento":        "Atendimento (legado)",
}


# Rótulos amigáveis por serviço (text / vision / stt / tts).
SERVICE_LABELS: Dict[str, str] = {
    "text":   "Texto (LLM)",
    "vision": "Visão (Gemini)",
    "stt":    "Áudio → Texto (Whisper)",
    "tts":    "Texto → Voz (TTS)",
}


@router.get("/usage")
async def usage_dashboard(
    days: int = Query(30, ge=1, le=90),
    user: dict = Depends(require_role("gestor")),
):
    """Retorna agregação de tokens e custo estimado (USD) por agente,
    por modelo, e série temporal diária — para o dashboard "Custo do Motor IA"."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    match = {"company_id": cid, "created_at": {"$gte": cutoff}}

    # Totais gerais
    pipe_totals = [
        {"$match": match},
        {"$group": {
            "_id": None,
            "prompt_tokens": {"$sum": "$prompt_tokens"},
            "completion_tokens": {"$sum": "$completion_tokens"},
            "total_tokens": {"$sum": "$total_tokens"},
            "cache_read_tokens": {"$sum": {"$ifNull": ["$cache_read_tokens", 0]}},
            "cache_write_tokens": {"$sum": {"$ifNull": ["$cache_write_tokens", 0]}},
            "cost_usd": {"$sum": "$estimated_cost_usd"},
            "calls": {"$sum": 1},
        }},
    ]
    tot = await db.motor_ia_usage.aggregate(pipe_totals).to_list(1)
    totals = tot[0] if tot else {
        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        "cache_read_tokens": 0, "cache_write_tokens": 0,
        "cost_usd": 0.0, "calls": 0,
    }
    totals.pop("_id", None)

    # Cache hit rate: % de input tokens vindos do cache vs total input
    cache_read = totals.get("cache_read_tokens") or 0
    cache_write = totals.get("cache_write_tokens") or 0
    pt = totals.get("prompt_tokens") or 0
    total_input_tokens = cache_read + pt + cache_write
    if total_input_tokens > 0:
        totals["cache_hit_rate_pct"] = round(cache_read / total_input_tokens * 100, 1)
    else:
        totals["cache_hit_rate_pct"] = 0.0
    # Economia em USD: tokens cacheados × (preço normal - 10%)
    # Estima média ponderada pelos modelos usados — simples: 90% do custo
    # equivalente em prompt_tokens normais.
    if cache_read > 0:
        # Custo dos cacheados se fossem normais
        from services.motor_ia import _estimate_cost_usd
        # Usa o modelo mais usado pra estimar — fallback: claude-sonnet
        most_model = "anthropic/claude-sonnet-4-5"
        full_cost_if_no_cache = _estimate_cost_usd(most_model, cache_read, 0)
        actual_cost_with_cache = full_cost_if_no_cache * 0.10
        totals["cache_savings_usd"] = round(
            full_cost_if_no_cache - actual_cost_with_cache, 4)
    else:
        totals["cache_savings_usd"] = 0.0

    # Por agente
    pipe_agents = [
        {"$match": match},
        {"$group": {
            "_id": "$agent",
            "prompt_tokens": {"$sum": "$prompt_tokens"},
            "completion_tokens": {"$sum": "$completion_tokens"},
            "total_tokens": {"$sum": "$total_tokens"},
            "units": {"$sum": {"$ifNull": ["$units", 0]}},
            "service": {"$first": {"$ifNull": ["$service", "text"]}},
            "unit_type": {"$first": {"$ifNull": ["$unit_type", "token"]}},
            "cost_usd": {"$sum": "$estimated_cost_usd"},
            "calls": {"$sum": 1},
        }},
        {"$sort": {"cost_usd": -1, "total_tokens": -1}},
    ]
    agents_raw = await db.motor_ia_usage.aggregate(pipe_agents).to_list(50)
    by_agent = []
    for r in agents_raw:
        aid = r.get("_id") or "unknown"
        by_agent.append({
            "agent": aid,
            "label": AGENT_LABELS.get(aid, aid),
            "service": r.get("service") or "text",
            "unit_type": r.get("unit_type") or "token",
            "units": int(r.get("units") or 0),
            "prompt_tokens": int(r.get("prompt_tokens") or 0),
            "completion_tokens": int(r.get("completion_tokens") or 0),
            "total_tokens": int(r.get("total_tokens") or 0),
            "cost_usd": round(float(r.get("cost_usd") or 0), 4),
            "calls": int(r.get("calls") or 0),
        })

    # Por modelo
    pipe_models = [
        {"$match": match},
        {"$group": {
            "_id": "$model",
            "total_tokens": {"$sum": "$total_tokens"},
            "cost_usd": {"$sum": "$estimated_cost_usd"},
            "calls": {"$sum": 1},
        }},
        {"$sort": {"cost_usd": -1}},
    ]
    models_raw = await db.motor_ia_usage.aggregate(pipe_models).to_list(20)
    by_model = [
        {"model": r.get("_id") or "unknown",
         "total_tokens": int(r.get("total_tokens") or 0),
         "cost_usd": round(float(r.get("cost_usd") or 0), 4),
         "calls": int(r.get("calls") or 0)}
        for r in models_raw
    ]

    # Por serviço (text / vision / stt / tts) — chamadas legacy sem `service`
    # ficam agrupadas como "text" via $ifNull.
    pipe_services = [
        {"$match": match},
        {"$group": {
            "_id": {"$ifNull": ["$service", "text"]},
            "cost_usd": {"$sum": "$estimated_cost_usd"},
            "calls": {"$sum": 1},
            "total_tokens": {"$sum": "$total_tokens"},
            "units": {"$sum": {"$ifNull": ["$units", 0]}},
        }},
        {"$sort": {"cost_usd": -1}},
    ]
    services_raw = await db.motor_ia_usage.aggregate(pipe_services).to_list(20)
    by_service = []
    for r in services_raw:
        sid = r.get("_id") or "text"
        # Define unidade exibida por serviço
        if sid == "vision":
            unit_type, unit_label = "image", "imagens"
        elif sid == "stt":
            unit_type, unit_label = "second", "seg"
        elif sid == "tts":
            unit_type, unit_label = "char", "chars"
        else:
            unit_type, unit_label = "token", "tokens"
        by_service.append({
            "service": sid,
            "label": SERVICE_LABELS.get(sid, sid),
            "cost_usd": round(float(r.get("cost_usd") or 0), 4),
            "calls": int(r.get("calls") or 0),
            "total_tokens": int(r.get("total_tokens") or 0),
            "units": int(r.get("units") or 0),
            "unit_type": unit_type,
            "unit_label": unit_label,
        })

    # Série diária
    pipe_daily = [
        {"$match": match},
        {"$group": {
            "_id": {"$substr": ["$created_at", 0, 10]},
            "total_tokens": {"$sum": "$total_tokens"},
            "cost_usd": {"$sum": "$estimated_cost_usd"},
        }},
        {"$sort": {"_id": 1}},
    ]
    daily_raw = await db.motor_ia_usage.aggregate(pipe_daily).to_list(95)
    daily = [
        {"date": r.get("_id"),
         "total_tokens": int(r.get("total_tokens") or 0),
         "cost_usd": round(float(r.get("cost_usd") or 0), 4)}
        for r in daily_raw if r.get("_id")
    ]

    return {
        "window_days": days,
        "totals": {
            "calls": int(totals.get("calls") or 0),
            "prompt_tokens": int(totals.get("prompt_tokens") or 0),
            "completion_tokens": int(totals.get("completion_tokens") or 0),
            "total_tokens": int(totals.get("total_tokens") or 0),
            "cache_read_tokens": int(totals.get("cache_read_tokens") or 0),
            "cache_write_tokens": int(totals.get("cache_write_tokens") or 0),
            "cache_hit_rate_pct": float(totals.get("cache_hit_rate_pct") or 0.0),
            "cache_savings_usd": round(float(totals.get("cache_savings_usd") or 0), 4),
            "cost_usd": round(float(totals.get("cost_usd") or 0), 4),
        },
        "by_agent": by_agent,
        "by_model": by_model,
        "by_service": by_service,
        "daily": daily,
    }


# ---------------------------------------------------------------------------
# Orçamento mensal — alertas de gasto
# ---------------------------------------------------------------------------

class ServiceLimits(BaseModel):
    vision: Optional[float] = Field(None, ge=0, le=1000)
    stt:    Optional[float] = Field(None, ge=0, le=1000)
    tts:    Optional[float] = Field(None, ge=0, le=1000)
    text:   Optional[float] = Field(None, ge=0, le=1000)


class BudgetIn(BaseModel):
    monthly_limit_usd: Optional[float] = Field(None, ge=0, le=10000)
    warn_threshold_pct: Optional[int] = Field(None, ge=1, le=100)
    enabled: Optional[bool] = None
    # Limites diários (USD). Se 0 ou None, desativado para aquele serviço.
    daily_limit_usd: Optional[float] = Field(None, ge=0, le=1000)
    daily_service_limits: Optional[ServiceLimits] = None


async def _get_budget(cid: str) -> Dict[str, Any]:
    doc = await db.motor_ia_budget.find_one({"company_id": cid}, {"_id": 0})
    if not doc:
        doc = {
            "company_id": cid,
            "monthly_limit_usd": 50.0,
            "warn_threshold_pct": 80,
            "enabled": False,
            "daily_limit_usd": 0.0,
            "daily_service_limits": {
                "vision": 0.0, "stt": 0.0, "tts": 0.0, "text": 0.0,
            },
        }
    # Garantia de campos novos em registros antigos
    doc.setdefault("daily_limit_usd", 0.0)
    doc.setdefault("daily_service_limits",
                    {"vision": 0.0, "stt": 0.0, "tts": 0.0, "text": 0.0})
    return doc


@router.get("/budget")
async def read_budget(user: dict = Depends(require_role("gestor"))):
    """Retorna config de orçamento mensal (default 50 USD / 80% threshold)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _get_budget(cid)


@router.put("/budget")
async def update_budget(payload: BudgetIn,
                          user: dict = Depends(require_role("administrador"))):
    """Atualiza orçamento. Apenas administrador."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    data = payload.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "Nada para atualizar.")
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.motor_ia_budget.update_one(
        {"company_id": cid},
        {"$set": data,
         "$setOnInsert": {"company_id": cid,
                           "created_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return await _get_budget(cid)


@router.get("/budget/status")
async def budget_status(user: dict = Depends(require_role("gestor"))):
    """Compara gasto do mês corrente com o limite configurado.

    Status:
      - "ok"        → gasto < threshold de aviso
      - "warn"      → gasto entre threshold e 100%
      - "exceeded"  → gasto >= 100% do limite
      - "disabled"  → orçamento desativado
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    budget = await _get_budget(cid)

    # Início do mês corrente em UTC
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    pipe = [
        {"$match": {"company_id": cid, "created_at": {"$gte": start}}},
        {"$group": {"_id": None,
                      "cost_usd": {"$sum": "$estimated_cost_usd"},
                      "calls": {"$sum": 1}}},
    ]
    agg = await db.motor_ia_usage.aggregate(pipe).to_list(1)
    spent = float(agg[0]["cost_usd"]) if agg else 0.0
    calls = int(agg[0]["calls"]) if agg else 0

    limit = float(budget.get("monthly_limit_usd") or 0)
    threshold_pct = int(budget.get("warn_threshold_pct") or 80)
    enabled = bool(budget.get("enabled"))

    used_pct = round((spent / limit) * 100, 2) if limit > 0 else 0
    status = "disabled"
    if enabled and limit > 0:
        if used_pct >= 100:
            status = "exceeded"
        elif used_pct >= threshold_pct:
            status = "warn"
        else:
            status = "ok"

    # Projeção linear: gasto atual × (dias_no_mês / dia_atual)
    day = now.day
    # último dia do mês: avança 1 mês e volta 1 dia
    if now.month == 12:
        next_month = now.replace(year=now.year + 1, month=1, day=1)
    else:
        next_month = now.replace(month=now.month + 1, day=1)
    days_in_month = (next_month - timedelta(days=1)).day
    projected = round((spent / day) * days_in_month, 4) if day > 0 else 0

    return {
        "enabled": enabled,
        "monthly_limit_usd": limit,
        "warn_threshold_pct": threshold_pct,
        "month_start": start,
        "spent_usd": round(spent, 4),
        "calls": calls,
        "used_pct": used_pct,
        "projected_month_usd": projected,
        "status": status,
    }


@router.get("/budget/status/today")
async def budget_status_today(user: dict = Depends(require_role("gestor"))):
    """Retorna gasto do dia corrente quebrado por serviço + status de alerta
    contra os limites diários configurados.

    Alertas por serviço:
      - "ok"        → gasto < threshold (80% do limite)
      - "warn"      → gasto >= 80% e < 100%
      - "exceeded"  → gasto >= 100% do limite
      - "disabled"  → limite não configurado (0)
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    budget = await _get_budget(cid)
    threshold_pct = int(budget.get("warn_threshold_pct") or 80)
    daily_total_limit = float(budget.get("daily_limit_usd") or 0)
    service_limits = budget.get("daily_service_limits") or {}

    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0,
                              microsecond=0).isoformat()

    pipe = [
        {"$match": {"company_id": cid, "created_at": {"$gte": day_start}}},
        {"$group": {
            "_id": {"$ifNull": ["$service", "text"]},
            "cost_usd": {"$sum": "$estimated_cost_usd"},
            "calls": {"$sum": 1},
        }},
    ]
    rows = await db.motor_ia_usage.aggregate(pipe).to_list(20)
    by_service: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        sid = r.get("_id") or "text"
        by_service[sid] = {
            "spent_usd": round(float(r.get("cost_usd") or 0), 4),
            "calls": int(r.get("calls") or 0),
        }

    def _classify(spent: float, limit: float) -> str:
        if limit <= 0:
            return "disabled"
        used = (spent / limit) * 100
        if used >= 100:
            return "exceeded"
        if used >= threshold_pct:
            return "warn"
        return "ok"

    services_payload = []
    total_spent = 0.0
    alerts = []
    for sid in ("text", "vision", "stt", "tts"):
        spent = by_service.get(sid, {}).get("spent_usd", 0.0)
        calls = by_service.get(sid, {}).get("calls", 0)
        limit = float(service_limits.get(sid) or 0)
        st = _classify(spent, limit)
        total_spent += spent
        services_payload.append({
            "service": sid,
            "limit_usd": limit,
            "spent_usd": round(spent, 4),
            "calls": calls,
            "used_pct": round((spent / limit) * 100, 2) if limit > 0 else 0,
            "status": st,
        })
        if st in ("warn", "exceeded"):
            alerts.append({
                "service": sid,
                "status": st,
                "spent_usd": round(spent, 4),
                "limit_usd": limit,
            })

    total_status = _classify(total_spent, daily_total_limit)
    if total_status in ("warn", "exceeded"):
        alerts.append({
            "service": "total",
            "status": total_status,
            "spent_usd": round(total_spent, 4),
            "limit_usd": daily_total_limit,
        })

    return {
        "day_start": day_start,
        "daily_limit_usd": daily_total_limit,
        "warn_threshold_pct": threshold_pct,
        "total_spent_usd": round(total_spent, 4),
        "total_status": total_status,
        "services": services_payload,
        "alerts": alerts,
        "has_alerts": bool(alerts),
    }



# ---------------------------------------------------------------------------
# Kill-switch por agente
# ---------------------------------------------------------------------------

class AgentSwitchIn(BaseModel):
    enabled: bool
    paused_until_minutes: Optional[int] = Field(None, ge=1, le=24 * 60)


@router.get("/agents")
async def list_agents(user: dict = Depends(require_role("gestor"))):
    """Lista todos os agentes do catálogo com estado atual (ligado/desligado).
    Default: ativo (sem registro)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    agents = await get_agents_state(cid)
    return {"agents": agents, "total": len(agents),
            "enabled_count": sum(1 for a in agents if a["enabled"])}


@router.put("/agents/{agent_id}")
async def toggle_agent(agent_id: str, payload: AgentSwitchIn,
                          user: dict = Depends(require_role("administrador"))):
    """Liga/desliga um agente específico. Aceita `paused_until_minutes` para
    pausa temporizada (auto-resume worker reativa após o prazo)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    paused_until = None
    if not payload.enabled and payload.paused_until_minutes:
        paused_until = (datetime.now(timezone.utc)
                          + timedelta(minutes=payload.paused_until_minutes)).isoformat()
    try:
        result = await set_agent_state(
            cid, agent_id, payload.enabled,
            user_label=user.get("name") or user.get("email") or user.get("id"),
            paused_until=paused_until,
        )
    except ValueError as e:
        raise HTTPException(404, safe_detail(404, e)) from e
    return {"ok": True, **result}


@router.put("/agents/group/{group_name}")
async def toggle_group(group_name: str, payload: AgentSwitchIn,
                          user: dict = Depends(require_role("administrador"))):
    """Liga/desliga TODOS os agentes do grupo. Aceita `paused_until_minutes`
    para pausa temporizada (auto-resume worker reativa após o prazo)."""
    from services.motor_ia import AGENT_CATALOG
    cid = user.get("company_id") or DEMO_COMPANY_ID
    user_label = user.get("name") or user.get("email") or user.get("id")
    affected = [a["id"] for a in AGENT_CATALOG
                  if (a.get("group") or "Outros") == group_name]
    if not affected:
        raise HTTPException(404, f"Grupo '{group_name}' não encontrado.")
    paused_until = None
    if not payload.enabled and payload.paused_until_minutes:
        paused_until = (datetime.now(timezone.utc)
                          + timedelta(minutes=payload.paused_until_minutes)).isoformat()
    changed: List[str] = []
    for aid in affected:
        result = await set_agent_state(cid, aid, payload.enabled, user_label,
                                          paused_until=paused_until)
        if result.get("changed"):
            changed.append(aid)
    return {"ok": True, "group": group_name, "affected": affected,
              "changed": changed, "total": len(affected),
              "paused_until": paused_until}


@router.get("/agents/history")
async def agents_history(
    days: int = Query(7, ge=1, le=90),
    user: dict = Depends(require_role("gestor")),
):
    """Retorna histórico de mudanças + intervalos OFF/ON por agente
    (formato pronto pra timeline)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    start_iso = start.isoformat()
    end_iso = now.isoformat()

    events = await get_agent_history(cid, days=days)

    # Pega último evento ANTERIOR ao período pra cada agente (estado inicial)
    initial_state: Dict[str, bool] = {}
    cur = db.ai_agent_switch_history.find(
        {"company_id": cid, "changed_at": {"$lt": start_iso}},
        {"_id": 0, "agent_id": 1, "enabled": 1, "changed_at": 1},
    ).sort([("agent_id", 1), ("changed_at", -1)])
    seen = set()
    async for d in cur:
        aid = d["agent_id"]
        if aid in seen:
            continue
        seen.add(aid)
        initial_state[aid] = bool(d.get("enabled", True))

    by_agent: Dict[str, List[Dict[str, Any]]] = {}
    for ev in events:
        by_agent.setdefault(ev["agent_id"], []).append(ev)
    for aid in by_agent:
        by_agent[aid].sort(key=lambda x: x["changed_at"])

    intervals_by_agent: Dict[str, List[Dict[str, Any]]] = {}
    for cat in AGENT_CATALOG:
        aid = cat["id"]
        evs = by_agent.get(aid, [])
        current_state = initial_state.get(aid, True)
        intervals: List[Dict[str, Any]] = []
        cursor_ts = start_iso
        for ev in evs:
            ts = ev["changed_at"]
            if ts <= cursor_ts:
                continue
            intervals.append({"start": cursor_ts, "end": ts,
                                "enabled": current_state})
            current_state = bool(ev["enabled"])
            cursor_ts = ts
        if cursor_ts < end_iso:
            intervals.append({"start": cursor_ts, "end": end_iso,
                                "enabled": current_state})
        intervals_by_agent[aid] = intervals

    def _parse(ts: str) -> float:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()

    downtime_by_agent: Dict[str, Dict[str, Any]] = {}
    total_secs = (now - start).total_seconds()
    for aid, intervals in intervals_by_agent.items():
        off_secs = 0.0
        for it in intervals:
            if not it["enabled"]:
                off_secs += _parse(it["end"]) - _parse(it["start"])
        downtime_by_agent[aid] = {
            "off_seconds": int(off_secs),
            "off_pct": round((off_secs / total_secs) * 100, 1) if total_secs else 0,
        }

    return {
        "window_days": days,
        "window_start": start_iso,
        "window_end": end_iso,
        "events": events,
        "intervals_by_agent": intervals_by_agent,
        "downtime_by_agent": downtime_by_agent,
        "agents_catalog": [{"id": a["id"], "label": a["label"]} for a in AGENT_CATALOG],
        "incidents": await _gather_incidents(cid, start_iso, end_iso),
    }


async def _gather_incidents(cid: str, start_iso: str, end_iso: str) -> List[Dict[str, Any]]:
    """Coleta incidentes operacionais relevantes pra correlação:

      - network_outages → kind="outage", relevante a smartolt_ai / isabella_whatsapp
      - lousa_alerts    → kind="sentinela", relevante a sentinela_lousa
    """
    incidents: List[Dict[str, Any]] = []
    # Outages
    async for o in db.network_outages.find(
        {"company_id": cid,
         "first_detected_at": {"$gte": start_iso, "$lt": end_iso}},
        {"_id": 0, "id": 1, "first_detected_at": 1, "resolved_at": 1,
         "olt_name": 1, "severity_pct": 1, "los_count": 1, "total_count": 1,
         "status": 1},
    ).sort("first_detected_at", -1).limit(100):
        incidents.append({
            "id": o.get("id"),
            "kind": "outage",
            "start": o.get("first_detected_at"),
            "end": o.get("resolved_at") or end_iso,
            "active": o.get("status") == "active",
            "title": f"Pane {o.get('olt_name')}",
            "detail": f"{o.get('los_count', 0)}/{o.get('total_count', 0)} ONUs · {o.get('severity_pct', 0)}%",
            "affects": ["smartolt_ai", "isabella_whatsapp"],
        })
    # Sentinela alerts (kanban SLA, sobrecarga etc)
    async for a in db.lousa_alerts.find(
        {"company_id": cid,
         "first_detected_at": {"$gte": start_iso, "$lt": end_iso}},
        {"_id": 0, "id": 1, "kind": 1, "headline": 1, "severity": 1,
         "first_detected_at": 1, "last_seen_at": 1, "status": 1},
    ).sort("first_detected_at", -1).limit(100):
        incidents.append({
            "id": a.get("id"),
            "kind": "sentinela",
            "start": a.get("first_detected_at"),
            "end": a.get("last_seen_at") or end_iso,
            "active": a.get("status") == "active",
            "title": a.get("headline") or a.get("kind"),
            "detail": f"severidade: {a.get('severity', 'media')}",
            "affects": ["sentinela_lousa", "lousa_triagem"],
        })
    return incidents




