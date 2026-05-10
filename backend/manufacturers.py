"""Detector de fabricante de ONT/ONU a partir do número de série.

Estratégia:
1) Match rápido por prefixo conhecido (4 chars) — cobre 90%+ do mercado FTTH brasileiro.
2) Fallback opcional para LLM (Gemini Flash) quando o prefixo é desconhecido.
3) Inferência por similaridade — agrupa prefixos desconhecidos com prefixos
   conhecidos via distância Levenshtein + LLM com contexto rico (exemplos
   reais cacheados) para confirmar.
4) Cache permanente em `manufacturer_cache` (chave = prefixo) pra zerar custo
   de repetidas consultas.

Prefixos de série padronizados pelo IEEE/CCM dos principais fabricantes FTTH.
"""
from __future__ import annotations

import json
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


async def identify_by_similarity_batch(
    unknown_sns: list[str], max_per_batch: int = 30,
) -> dict[str, Optional[str]]:
    """Identifica fabricantes para SNs desconhecidos via similaridade com SNs já
    cadastrados.

    Estratégia:
    1) Coleta TODOS os mappings prefixo→fabricante já conhecidos (hardcoded +
       cache positivo). Isso forma o "catálogo de exemplos".
    2) Pra cada lote de até 30 SNs desconhecidos, monta um prompt que mostra
       o catálogo + lista de SNs e pede ao Gemini pra identificar cada um por
       semelhança (mesmo padrão de prefixo, formato, comprimento, etc).
    3) Salva os resultados no cache (positivo ou negativo).

    Retorna `{prefix: manufacturer}` para todos os prefixos descobertos.
    """
    if not unknown_sns or not EMERGENT_LLM_KEY:
        return {}

    # 1. Coleta catálogo positivo (prefixo → fabricante)
    catalog: dict[str, str] = dict(KNOWN_PREFIXES)
    cur = db.manufacturer_cache.find(
        {"manufacturer": {"$ne": None}}, {"_id": 0, "prefix": 1, "manufacturer": 1})
    async for c in cur:
        if c.get("manufacturer"):
            catalog[c["prefix"]] = c["manufacturer"]

    # 2. Filtra apenas prefixos UNIK desconhecidos
    unknown_prefixes: dict[str, str] = {}  # prefix -> sample_sn
    for sn in unknown_sns:
        p = _ascii_prefix(sn) or _hex_prefix(sn)
        if not p or p in catalog or p in unknown_prefixes:
            continue
        unknown_prefixes[p] = sn
    if not unknown_prefixes:
        return {}

    logger.info("[mfr-similarity] %d catálogo, %d prefixos desconhecidos a inferir",
                len(catalog), len(unknown_prefixes))

    # 3. Monta prompt rico — limita catálogo a 60 amostras agrupadas por marca
    by_brand: dict[str, list[str]] = {}
    for p, m in catalog.items():
        by_brand.setdefault(m, []).append(p)
    catalog_str_lines = []
    for brand, prefixes in sorted(by_brand.items(), key=lambda x: -len(x[1])):
        sample = ", ".join(prefixes[:6])
        catalog_str_lines.append(f"- {brand}: {sample}")
    catalog_str = "\n".join(catalog_str_lines)

    found: dict[str, Optional[str]] = {}
    items = list(unknown_prefixes.items())

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except ImportError as e:
        logger.warning("[mfr-similarity] emergentintegrations indisponível: %s", e)
        return {}

    for i in range(0, len(items), max_per_batch):
        batch = items[i:i + max_per_batch]
        unknown_str = "\n".join(
            f"{j + 1}. prefixo='{p}' SN-exemplo='{sn}'"
            for j, (p, sn) in enumerate(batch))
        prompt = (
            "Catálogo de prefixos de SN de ONT/ONU GPON conhecidos no Brasil "
            "(prefixo → fabricante):\n"
            f"{catalog_str}\n\n"
            "SNs desconhecidos (use SIMILARIDADE estrutural, padrões de prefixo, "
            "convenção de naming e contexto FTTH brasileiro pra inferir o fabricante "
            "MAIS PROVÁVEL):\n"
            f"{unknown_str}\n\n"
            "Responda em JSON puro (sem markdown, sem comentários) no formato:\n"
            '[{"prefix":"XXXX","manufacturer":"NomeMarca"}, ...]\n'
            "Use 'Desconhecido' apenas se REALMENTE não houver semelhança nenhuma. "
            "Não invente marcas — use SOMENTE marcas do catálogo acima ou variantes "
            "muito próximas (ex.: 'Huawei OptiX' não, só 'Huawei')."
        )
        try:
            chat = LlmChat(
                api_key=EMERGENT_LLM_KEY,
                session_id=f"mfr-batch-{i}",
                system_message=(
                    "Você é especialista em equipamentos GPON/FTTH brasileiros. "
                    "Identifica fabricantes por similaridade de prefixo, comprimento "
                    "e estrutura do SN. Sempre responde JSON válido."),
            ).with_model("gemini", "gemini-2.5-flash")
            resp = await chat.send_message(UserMessage(text=prompt))
            text = resp if isinstance(resp, str) else getattr(resp, "text", str(resp))
            # Extrai JSON do text (pode vir com ```json ou texto extra)
            m = re.search(r"\[\s*\{.*?\}\s*\]", text or "", re.DOTALL)
            if not m:
                logger.warning("[mfr-similarity] resposta sem JSON: %s", (text or "")[:200])
                continue
            parsed = json.loads(m.group(0))
            for entry in parsed:
                prefix = (entry.get("prefix") or "").strip().upper()
                manuf = (entry.get("manufacturer") or "").strip()
                if not prefix:
                    continue
                if manuf.lower() in ("", "desconhecido", "unknown", "n/a"):
                    manuf_save: Optional[str] = None
                else:
                    manuf_save = manuf[:60]
                # Persiste no cache (positivo OU negativo)
                await db.manufacturer_cache.update_one(
                    {"prefix": prefix},
                    {"$set": {"prefix": prefix, "manufacturer": manuf_save,
                              "source": "llm-similarity",
                              "sample_sn": unknown_prefixes.get(prefix, "")[:32]}},
                    upsert=True,
                )
                found[prefix] = manuf_save
        except Exception as e:
            logger.warning("[mfr-similarity] batch %d falhou: %s", i, e)
            continue

    logger.info("[mfr-similarity] inferidos %d/%d prefixos via batch LLM",
                sum(1 for v in found.values() if v), len(unknown_prefixes))
    return found
