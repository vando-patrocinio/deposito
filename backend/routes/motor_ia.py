"""Motor IA — endpoints REST para a aba Sistemas → Motor IA."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, require_role
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
             "models": ["openai/gpt-4o-mini", "anthropic/claude-3-haiku",
                          "google/gemini-2.0-flash-exp:free"]},
            {"id": "balanced", "label": "Equilíbrio (recomendado)",
             "models": ["openai/gpt-4o", "anthropic/claude-3.5-sonnet",
                          "meta-llama/llama-3.3-70b-instruct"]},
            {"id": "premium", "label": "Qualidade máxima",
             "models": ["anthropic/claude-3.5-sonnet", "openai/gpt-4o",
                          "google/gemini-2.0-flash-thinking-exp"]},
            {"id": "free", "label": "Apenas grátis (limite por dia)",
             "models": ["google/gemini-2.0-flash-exp:free",
                          "meta-llama/llama-3.3-70b-instruct:free"]},
        ],
        "default_fallbacks": DEFAULT_FALLBACKS,
    }
