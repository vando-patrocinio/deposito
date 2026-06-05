"""Geração e cache de imagens do programa Indique e Ganhe.

Usa Gemini Nano Banana via Emergent LLM Key. Cada slot é gerado 1x e
servido como arquivo PNG estático em disco (`/app/backend/assets/referrals`).

Identidade visual Ligo Fibra:
- Roxo principal: #5B2A86 (deep purple) e #7B1FA2 (vibrant)
- Laranja: #FF9800 / #FB923C
- Estilo: 3D ilustração premium, alegre, fotorrealismo cinematográfico
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import uuid
from pathlib import Path
from typing import Dict

logger = logging.getLogger("ponto.referrals.imagegen")

# Diretório onde os PNGs ficam (cache persistente em disco).
ASSETS_DIR = Path("/app/backend/assets/referrals")
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

# Slots de imagem disponíveis — cada slot tem prompt fixo na brand Ligo
BRAND_STYLE = (
    "Premium 3D cinematic illustration, brand colors deep purple #5B2A86 "
    "and vivid orange #FF9800, joyful clean background with subtle confetti "
    "and bokeh, high quality marketing asset, no text, no watermarks, no logos"
)

IMAGE_SLOTS: Dict[str, str] = {
    "hero": (
        "Two happy young Brazilian friends celebrating, hugging and smiling "
        "at smartphone showing PIX payment confirmation, real BRL R$ 50 "
        "bills flying around like confetti. Purple gradient background "
        "with orange highlights. Cheerful, vibrant, modern. " + BRAND_STYLE
    ),
    "money_pix": (
        "A glowing smartphone screen displaying PIX transfer success with "
        "bright orange R$ 50 banknotes coming out, fiber optic strands "
        "glowing in purple light, hand holding it. " + BRAND_STYLE
    ),
    "celebration": (
        "Happy person celebrating victory with arms up, golden trophy and "
        "rain of money in background, confetti, fireworks. Studio lighting "
        "purple and orange. " + BRAND_STYLE
    ),
    "home_fiber": (
        "Cozy modern Brazilian house at night, glowing fiber optic cable "
        "delivering light to the home, family in living room enjoying "
        "high speed internet on smart TV. Purple sky with orange sunset. "
        + BRAND_STYLE
    ),
}

# Cards de milestone — personalizados com nome + tier
MILESTONE_DIR = ASSETS_DIR / "milestones"
MILESTONE_DIR.mkdir(parents=True, exist_ok=True)

MILESTONE_PROMPTS: Dict[int, str] = {
    1: (  # Bronze (5 indicações)
        "Happy Brazilian person holding a shiny bronze medal smiling at camera, "
        "stack of R$ 50 bills in the other hand, fireworks behind, "
        "purple background with orange highlights. " + BRAND_STYLE
    ),
    2: (  # Prata (10)
        "Brazilian person holding a silver trophy with both hands, joyful "
        "expression, golden coins raining around, purple deep background, "
        "orange spotlight. " + BRAND_STYLE
    ),
    3: (  # Ouro (20)
        "Brazilian person crowned with golden laurel, holding a golden cup, "
        "huge celebration with confetti and fireworks, R$ 50 bills flying, "
        "purple stadium background with orange floodlights. " + BRAND_STYLE
    ),
    4: (  # Diamante (30)
        "Brazilian person on top of mountain holding a sparkling diamond "
        "trophy, sunrise behind, confetti and money in the air, victorious "
        "pose, purple dawn sky with orange sunrise. " + BRAND_STYLE
    ),
}


def milestone_path(subscriber_id: str, tier_level: int) -> Path:
    safe_id = subscriber_id.replace("/", "_")
    return MILESTONE_DIR / f"{safe_id}_t{tier_level}.png"


def has_milestone(subscriber_id: str, tier_level: int) -> bool:
    p = milestone_path(subscriber_id, tier_level)
    return p.exists() and p.stat().st_size > 1024


async def generate_milestone_card(
    subscriber_id: str,
    tier_level: int,
    first_name: str,
    force: bool = False,
) -> Dict[str, str]:
    """Gera card personalizado de vitória do cliente.

    Imagem inclui um espaço/sinalização pra exibir o nome do cliente
    (front-end pode sobrepor texto sobre ela depois — Gemini não é
    confiável pra textos longos, então mantemos a imagem genérica do
    tier e o nome é overlay HTML).
    """
    if tier_level not in MILESTONE_PROMPTS:
        raise ValueError(f"Tier inválido: {tier_level}")
    out = milestone_path(subscriber_id, tier_level)
    if has_milestone(subscriber_id, tier_level) and not force:
        return {"ok": True, "path": str(out), "cached": True,
                "tier_level": tier_level}

    api_key = os.getenv("EMERGENT_LLM_KEY")
    if not api_key:
        return {"ok": False, "error": "EMERGENT_LLM_KEY ausente"}

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:
        return {"ok": False, "error": f"emergentintegrations missing: {e}"}

    prompt = MILESTONE_PROMPTS[tier_level]
    sid = f"milestone-{subscriber_id}-t{tier_level}-{uuid.uuid4().hex[:6]}"
    chat = LlmChat(
        api_key=api_key, session_id=sid,
        system_message="You are an expert marketing illustrator.",
    )
    chat.with_model("gemini", "gemini-3.1-flash-image-preview") \
        .with_params(modalities=["image", "text"])

    try:
        _text, images = await chat.send_message_multimodal_response(
            UserMessage(text=prompt))
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    if not images:
        return {"ok": False, "error": "Sem imagem"}

    try:
        out.write_bytes(base64.b64decode(images[0]["data"]))
    except Exception as e:
        return {"ok": False, "error": f"write fail: {e}"}
    logger.info("[referrals.img] milestone t%s gen for %s (%d bytes)",
                  tier_level, subscriber_id, out.stat().st_size)
    return {"ok": True, "path": str(out), "cached": False,
            "tier_level": tier_level}


def asset_path(slug: str) -> Path:
    return ASSETS_DIR / f"{slug}.png"


def has_asset(slug: str) -> bool:
    p = asset_path(slug)
    return p.exists() and p.stat().st_size > 1024  # > 1KB = válido


async def generate_slot(slug: str, force: bool = False) -> Dict[str, str]:
    """Gera 1 imagem via Gemini Nano Banana e salva em disco.

    Idempotente: se já existe e force=False, retorna sem regenerar.
    """
    if slug not in IMAGE_SLOTS:
        raise ValueError(f"Slug inválido: {slug}. Use: {list(IMAGE_SLOTS)}")
    out_path = asset_path(slug)
    if has_asset(slug) and not force:
        return {"ok": True, "slug": slug, "path": str(out_path),
                "cached": True}

    api_key = os.getenv("EMERGENT_LLM_KEY")
    if not api_key:
        return {"ok": False, "error": "EMERGENT_LLM_KEY ausente"}

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:
        return {"ok": False, "error": f"emergentintegrations missing: {e}"}

    prompt = IMAGE_SLOTS[slug]
    sid = f"referral-img-{slug}-{uuid.uuid4().hex[:6]}"
    chat = LlmChat(
        api_key=api_key, session_id=sid,
        system_message="You are an expert marketing illustrator.",
    )
    chat.with_model("gemini", "gemini-3.1-flash-image-preview") \
        .with_params(modalities=["image", "text"])

    msg = UserMessage(text=prompt)
    try:
        _text, images = await chat.send_message_multimodal_response(msg)
    except Exception as e:
        logger.warning("[referrals.img] %s gen failed: %s", slug, e)
        return {"ok": False, "error": str(e)[:200]}

    if not images:
        return {"ok": False, "error": "Nenhuma imagem retornada"}

    img = images[0]
    try:
        out_path.write_bytes(base64.b64decode(img["data"]))
    except Exception as e:
        return {"ok": False, "error": f"write fail: {e}"}
    logger.info("[referrals.img] generated %s -> %s (%d bytes)",
                  slug, out_path, out_path.stat().st_size)
    return {"ok": True, "slug": slug, "path": str(out_path), "cached": False}


async def ensure_all_assets() -> Dict[str, dict]:
    """Gera todos os slots faltantes em paralelo."""
    results = await asyncio.gather(
        *[generate_slot(s) for s in IMAGE_SLOTS],
        return_exceptions=True,
    )
    return {s: r if not isinstance(r, Exception) else {"ok": False,
                                                         "error": str(r)}
            for s, r in zip(IMAGE_SLOTS, results)}
