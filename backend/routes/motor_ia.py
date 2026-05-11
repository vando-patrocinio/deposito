"""Motor IA — endpoints REST para a aba Sistemas → Motor IA."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, require_role
from database import db
from services.motor_ia import (
    get_motor_config, get_safe_config, save_motor_config, test_motor,
    DEFAULT_FALLBACKS,
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
    # REGRA DE NEGÓCIO: motor de atendimento deve ser DeepSeek.
    # Rejeita modelos que não tenham prefixo "deepseek/".
    if "atendimento_model" in data and data["atendimento_model"]:
        if not str(data["atendimento_model"]).lower().startswith("deepseek/"):
            raise HTTPException(
                400,
                "O motor de atendimento deve ser DeepSeek "
                "(modelo precisa começar com 'deepseek/').",
            )
    if "atendimento_fallbacks" in data and data["atendimento_fallbacks"]:
        data["atendimento_fallbacks"] = [
            m for m in data["atendimento_fallbacks"]
            if str(m).lower().startswith("deepseek/")
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
    "aihub_chat":         "AI Hub · Chat",
    "aihub_textgen":      "AI Hub · TextGen",
    "central_ia_eval":    "Central IA · Avaliação",
    "central_ia_coach":   "Central IA · Coaching",
    "voice_ai":           "Voice AI",
    "ai_dashboard_insight": "Dashboard Insights",
    "general":            "Outros (geral)",
    "atendimento":        "Atendimento (legado)",
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
            "cost_usd": {"$sum": "$estimated_cost_usd"},
            "calls": {"$sum": 1},
        }},
    ]
    tot = await db.motor_ia_usage.aggregate(pipe_totals).to_list(1)
    totals = tot[0] if tot else {
        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        "cost_usd": 0.0, "calls": 0,
    }
    totals.pop("_id", None)

    # Por agente
    pipe_agents = [
        {"$match": match},
        {"$group": {
            "_id": "$agent",
            "prompt_tokens": {"$sum": "$prompt_tokens"},
            "completion_tokens": {"$sum": "$completion_tokens"},
            "total_tokens": {"$sum": "$total_tokens"},
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
            "cost_usd": round(float(totals.get("cost_usd") or 0), 4),
        },
        "by_agent": by_agent,
        "by_model": by_model,
        "daily": daily,
    }

