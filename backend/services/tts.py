"""Text-to-Speech via OpenAI (gpt-4o-mini-tts).

Usa o EMERGENT_LLM_KEY como fallback se a empresa não tiver `openai_audio_key`
configurada em Motor IA → Sistemas.

Geração mais barata: voice "nova" (feminina pt-BR) · formato OGG/Opus
(o que o WhatsApp prefere pra voice notes — tamanho menor, melhor UX).
"""

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import os
from typing import Optional

import httpx

from core import EMERGENT_LLM_KEY
from database import db

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "nova"           # feminina, mais natural em pt-BR
DEFAULT_MODEL = "gpt-4o-mini-tts"  # mais barato; "tts-1-hd" se quiser premium
DEFAULT_FORMAT = "opus"           # WhatsApp prefere


async def _get_api_key(company_id: str) -> Optional[str]:
    """Prioriza chave da empresa; senão usa Emergent universal."""
    settings = await db.motor_ia.find_one(
        {"company_id": company_id}, {"_id": 0, "openai_audio_key": 1},
    ) or {}
    return (settings.get("openai_audio_key")
            or os.environ.get("OPENAI_AUDIO_KEY")
            or EMERGENT_LLM_KEY)


async def synthesize_speech(
    company_id: str, text: str, voice: str = DEFAULT_VOICE,
    model: str = DEFAULT_MODEL, audio_format: str = DEFAULT_FORMAT,
) -> Optional[bytes]:
    """Gera áudio TTS. Retorna bytes (OGG/Opus por padrão).

    Limita texto a 4096 chars (limite da API). Trunca silenciosamente.
    Retorna None em qualquer erro (chamador deve fallback pra texto).
    """
    text = (text or "").strip()
    if not text:
        return None
    if len(text) > 4096:
        text = text[:4093] + "..."

    api_key = await _get_api_key(company_id)
    if not api_key:
        logger.info("[tts] sem API key — pulando TTS")
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as cli:
            r = await cli.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {api_key}",
                          "Content-Type": "application/json"},
                json={
                    "model": model,
                    "voice": voice,
                    "input": text,
                    "response_format": audio_format,
                },
            )
            if r.status_code != 200:
                logger.warning("[tts] HTTP %s · %s",
                                r.status_code, r.text[:200])
                return None
            # Loga uso (chars) no Motor IA Usage
            try:
                from services.motor_ia import log_usage_units
                await log_usage_units(company_id, "isabella_tts", model,
                                      "tts", len(text), unit_type="char",
                                      provider="openai")
            except Exception as e:
                logger.debug("[tts] usage log falhou: %s", e)
            return r.content
    except Exception as e:
        logger.warning("[tts] erro %s", e)
        return None
