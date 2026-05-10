"""Detector de fabricante de ONT/ONU a partir do número de série.

Estratégia:
1) Match rápido por prefixo conhecido (4 chars) — cobre 90%+ do mercado FTTH brasileiro.
2) Fallback opcional para LLM (Gemini Flash) quando o prefixo é desconhecido.
3) Cache permanente em `manufacturer_cache` (chave = prefixo) pra zerar custo
   de repetidas consultas.

Prefixos de série padronizados pelo IEEE/CCM dos principais fabricantes FTTH.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from core import EMERGENT_LLM_KEY
from database import db

logger = logging.getLogger("ponto.manufacturers")

# Prefixos hex (4 chars) → fabricante.
# Fonte: IEEE OUI registry + relatórios de campo de provedores brasileiros.
KNOWN_PREFIXES: dict[str, str] = {
    "HWTC": "Huawei",
    "HWHW": "Huawei",
    "ZTEG": "ZTE",
    "ZNTS": "ZTE",
    "FHTT": "Fiberhome",
    "FHEC": "Fiberhome",
    "GPON": "Generic GPON",
    "ALCL": "Nokia/Alcatel-Lucent",
    "NOKA": "Nokia",
    "NKEC": "Nokia",
    "INTL": "Intelbras",
    "ITBS": "Intelbras",
    "PACE": "Pace",
    "TPLG": "TP-Link",
    "TPLK": "TP-Link",
    "MRCG": "Mercusys",
    "MERC": "Mercusys",
    "GWCK": "GreatWall",
    "GWFS": "GreatWall",
    "DSNW": "Datacom",
    "DTCM": "Datacom",
    "PARK": "Parks",
    "PRKS": "Parks",
    "VSOL": "V-SOL",
    "VSOI": "V-SOL",
    "BDCM": "BDCom",
    "RAIS": "Raisecom",
    "MTSC": "MaxLink",
    "CIGG": "C-Data",
    "CDTL": "C-Data",
    "EFLW": "EnFlow",
    "ALPH": "Alphalink",
    "PTIN": "PT Inovação",
    "GTUS": "GTUS",
    "MSTC": "MasterCom",
    "STEC": "Smartec",
    "TWCH": "Twibi",
    "FTTX": "FTTX Generic",
}


def _hex_prefix(sn: str) -> str:
    """SN típica de ONU GPON: 8 chars hex (4 vendor + 4 serial).
    Aceita formatos com espaço/hífen.
    """
    cleaned = re.sub(r"[^A-Fa-f0-9]", "", sn or "")
    return (cleaned[:4] or "").upper()


def _ascii_prefix(sn: str) -> str:
    """Prefixo ASCII de 4 chars (alguns fabricantes usam letras puras)."""
    cleaned = re.sub(r"[^A-Za-z]", "", sn or "")
    return (cleaned[:4] or "").upper()


async def identify_manufacturer(sn: str) -> Optional[str]:
    """Retorna o nome do fabricante. Tenta:
    1. Lookup hardcoded (KNOWN_PREFIXES).
    2. Cache em DB.
    3. LLM Gemini (se EMERGENT_LLM_KEY disponível).
    Retorna None se tudo falhar (UI mostra "Desconhecido").
    """
    if not sn or len(sn) < 4:
        return None

    # 1. Hardcoded — caso 90%
    for cand in (_ascii_prefix(sn), _hex_prefix(sn)):
        if cand in KNOWN_PREFIXES:
            return KNOWN_PREFIXES[cand]

    # 2. Cache (DB)
    prefix = _ascii_prefix(sn) or _hex_prefix(sn)
    if not prefix:
        return None
    cached = await db.manufacturer_cache.find_one(
        {"prefix": prefix}, {"_id": 0, "manufacturer": 1})
    if cached and cached.get("manufacturer"):
        return cached["manufacturer"]

    # 3. LLM fallback — só se chave disponível e não temos cache "negativo"
    if not EMERGENT_LLM_KEY:
        return None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"mfr-lookup-{prefix}",
            system_message=(
                "Você é um especialista em equipamentos GPON/FTTH. "
                "Recebe um número de série de ONU/ONT e identifica o fabricante "
                "olhando os primeiros 4 caracteres (vendor ID padrão IEEE). "
                "Responda APENAS com o nome do fabricante (ex.: Huawei, ZTE, Fiberhome, Intelbras). "
                "Se não tiver certeza absoluta, responda exatamente 'Desconhecido'."
            ),
        ).with_model("gemini", "gemini-2.5-flash")
        resp = await chat.send_message(UserMessage(
            text=f"Número de série: {sn}\nPrefixo: {prefix}\nFabricante:"))
        text = resp if isinstance(resp, str) else getattr(resp, "text", str(resp))
        text = (text or "").strip().split("\n")[0].strip(" .,:;\"'")
        if not text or text.lower() in ("desconhecido", "unknown", "n/a", ""):
            mfr: Optional[str] = None
        else:
            mfr = text[:60]
        await db.manufacturer_cache.update_one(
            {"prefix": prefix},
            {"$set": {"prefix": prefix, "manufacturer": mfr,
                      "source": "llm", "sample_sn": sn[:32]}},
            upsert=True,
        )
        return mfr
    except Exception as e:
        logger.warning("[mfr] LLM lookup falhou para %s: %s", prefix, e)
        return None
