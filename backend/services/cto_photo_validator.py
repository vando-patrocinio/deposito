"""CTO Photo Validator — Sentinela IA do cadastro (iter180).

Análise automática da foto enviada pelo técnico no cadastro de CTO/CE/Cabo
e nas OS. Combina 3 sinais:

  1. **Duplicidade** — pHash (8x8 hash perceptual) cruzado com fotos
     submetidas pela mesma empresa nos últimos 90 dias.
  2. **GPS** — extrai coordenadas do EXIF da foto e compara com o pino
     informado pelo técnico (tolerância 100 m).
  3. **Visual (Claude Sonnet 4.5 vision)** — detecta se há CTO/CE na
     foto, condição física (`ok` / `quebrada` / `sem_tampa`) e
     `quality_score` (nitidez/enquadramento).

Score final é uma média ponderada (visual 60% · GPS 25% · dedupe 15%).
Se < 85 → ação `retake`. Se OK porém condition ∈ {quebrada, sem_tampa}
→ ação `open_ticket` (mantém foto, sugere abrir chamado).

Sem chave LLM (env não configurada) o service degrada para apenas
duplicidade + GPS (visual_score = 100), mantendo o fluxo do app
funcional em ambientes de dev.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "infra-team",
    "domain": "rede",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import base64
import hashlib
import io
import json
import logging
import math
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from PIL import ExifTags, Image

from database import db

log = logging.getLogger("cto_photo_validator")

# -----------------------------------------------------------------------------
# Defaults (ajustáveis por env / motor IA depois)
# -----------------------------------------------------------------------------
GPS_TOLERANCE_M = 150              # tolerância em metros entre EXIF GPS e pino
DEDUPE_LOOKBACK_DAYS = 90
DEDUPE_HAMMING_THRESHOLD = 5       # ≤5 bits diferentes em pHash 64-bit → match
APPROVAL_MIN_SCORE = 85
WEIGHTS = {"visual": 0.60, "gps": 0.25, "dedupe": 0.15}

CLAUDE_MODEL = "claude-sonnet-4-5-20250929"

_VISION_PROMPT = """\
Você é a Sentinela IA da rede FTTH. Analise APENAS o que aparece na foto.
A foto é uma submissão de campo de um técnico que diz ter instalado ou
visitado uma CAIXA TERMINAL ÓPTICA (CTO) ou CAIXA DE EMENDA (CE).

Responda APENAS em JSON válido (sem markdown, sem ```), português.

Schema obrigatório:
{
  "has_cto": true|false,           // existe CTO/CE visível na foto?
  "condition": "ok"|"quebrada"|"sem_tampa"|"desconhecido",
  "quality_score": 0..100,         // nitidez/iluminação/enquadramento
  "reasoning": "frase curta máx 140 chars",
  "tags": ["..."]                  // ex.: poste, fachada, fios_soltos
}

Regras:
- has_cto=false se a foto for paisagem/pessoa/objeto não relacionado.
- condition="quebrada" se houver dano estrutural visível (rachadura,
  partes faltando, deformação severa). NÃO usar para sujeira leve.
- condition="sem_tampa" se a tampa estiver claramente ausente/aberta
  expondo splitters/conectores.
- quality_score < 50 se borrada, escuro demais, mostra só parte.
- Seja conservador. Em dúvida use condition="desconhecido".
"""


# =============================================================================
# 1) Image utilities
# =============================================================================
def _decode_data_url(data_url: str) -> Tuple[bytes, str]:
    """`data:image/jpeg;base64,...` → (bytes, mime). Aceita também
    base64 puro (sem prefixo). MIME default = image/jpeg."""
    if data_url.startswith("data:"):
        m = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", data_url)
        if not m:
            raise ValueError("data_url inválido")
        return base64.b64decode(m.group(2)), m.group(1)
    return base64.b64decode(data_url), "image/jpeg"


def _sha1(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def _phash_from_bytes(raw: bytes) -> str:
    """pHash 64-bit, retornado como hex de 16 chars."""
    import imagehash  # lazy
    img = Image.open(io.BytesIO(raw))
    return str(imagehash.phash(img, hash_size=8))


def _hamming_hex(a: str, b: str) -> int:
    """Distância de Hamming entre 2 strings hex de pHash."""
    return bin(int(a, 16) ^ int(b, 16)).count("1")


# =============================================================================
# 2) EXIF GPS
# =============================================================================
def _extract_exif_gps(raw: bytes) -> Optional[Tuple[float, float]]:
    """Lê coordenadas (lat,lng) do EXIF. Retorna None se ausente."""
    try:
        img = Image.open(io.BytesIO(raw))
        exif = img._getexif() or {}  # noqa: SLF001
    except Exception:
        return None
    if not exif:
        return None
    tag_map = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
    gps = tag_map.get("GPSInfo")
    if not gps:
        return None
    gps_tags = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps.items()}
    try:
        lat = _dms_to_decimal(gps_tags["GPSLatitude"],
                                gps_tags.get("GPSLatitudeRef", "N"))
        lng = _dms_to_decimal(gps_tags["GPSLongitude"],
                                gps_tags.get("GPSLongitudeRef", "E"))
        return lat, lng
    except Exception:
        return None


def _dms_to_decimal(dms, ref: str) -> float:
    d, m, s = (float(x) for x in dms)
    val = d + m / 60.0 + s / 3600.0
    if ref in ("S", "W"):
        val = -val
    return val


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


# =============================================================================
# 3) Vision (Claude Sonnet 4.5)
# =============================================================================
async def _vision_analyze(raw: bytes) -> Dict[str, Any]:
    """Chama Claude 4.5 vision. Em caso de chave ausente ou erro de rede
    devolve `{has_cto: true, condition: 'desconhecido', quality_score: 80}`
    para não travar o fluxo do app em ambientes degradados.
    """
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        log.info("[validator] EMERGENT_LLM_KEY ausente — pulando visão")
        return {"has_cto": True, "condition": "desconhecido",
                "quality_score": 80, "reasoning": "visão desabilitada",
                "tags": [], "_skipped": True}
    try:
        from emergentintegrations.llm.chat import (
            ImageContent, LlmChat, UserMessage,
        )
    except Exception as e:  # pragma: no cover
        log.warning("[validator] emergentintegrations indisponível: %s", e)
        return {"has_cto": True, "condition": "desconhecido",
                "quality_score": 80, "reasoning": "lib ausente",
                "tags": [], "_skipped": True}

    b64 = base64.b64encode(raw).decode("utf-8")
    session_id = f"cto-validate-{uuid.uuid4().hex[:8]}"
    chat = LlmChat(api_key=key, session_id=session_id,
                     system_message=_VISION_PROMPT).with_model(
        "anthropic", CLAUDE_MODEL,
    )
    msg = UserMessage(
        text="Analise esta foto e responda no JSON do schema.",
        file_contents=[ImageContent(image_base64=b64)],
    )
    try:
        raw_txt = await chat.send_message(msg)
    except Exception as e:
        log.warning("[validator] Claude vision falhou: %s", e)
        return {"has_cto": True, "condition": "desconhecido",
                "quality_score": 80, "reasoning": f"falha: {e}"[:140],
                "tags": [], "_skipped": True}

    text = (raw_txt or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text)
    try:
        parsed = json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        parsed = json.loads(m.group(0)) if m else {}

    return {
        "has_cto": bool(parsed.get("has_cto", True)),
        "condition": str(parsed.get("condition", "desconhecido")).lower(),
        "quality_score": max(0, min(100,
            int(parsed.get("quality_score") or 0))),
        "reasoning": str(parsed.get("reasoning") or "")[:140],
        "tags": [str(t)[:32] for t in (parsed.get("tags") or [])][:5],
    }


# =============================================================================
# 4) Public orchestrator
# =============================================================================
async def validate_photo(*, data_url: str, company_id: str,
                            collaborator_id: Optional[str],
                            element_type: str = "cto",
                            lat: Optional[float] = None,
                            lng: Optional[float] = None,
                            persist: bool = True) -> Dict[str, Any]:
    """Executa o pipeline completo de validação.

    Retorna:
      {
        "ok": bool,                  # score >= 85
        "score": int,                # 0..100
        "action": "approve"|"retake"|"open_ticket",
        "message": str,              # texto pronto para mostrar ao técnico
        "breakdown": {visual, gps, dedupe},
        "vision": {has_cto, condition, quality_score, reasoning, tags},
        "gps_check": {photo_lat, photo_lng, distance_m, ok},
        "dedupe": {duplicate_of, distance_bits},
        "phash": "...", "sha1": "...",
        "open_ticket_hint": optional dict (se condition em quebrada/sem_tampa)
      }
    """
    raw, _ = _decode_data_url(data_url)
    sha1 = _sha1(raw)
    phash = _phash_from_bytes(raw)

    # iter181 — Threshold configurável por empresa (Sentinela IA).
    # Default mudou de 85 → 69 conforme decisão do gestor (foto 79/100
    # estava sendo rejeitada indevidamente).
    company_settings = await db.settings.find_one(
        {"id": company_id}, {"_id": 0, "sentinela_min_score": 1},
    ) or {}
    min_score = company_settings.get("sentinela_min_score")
    if not isinstance(min_score, (int, float)) or not (0 <= min_score <= 100):
        min_score = 69
    min_score = int(min_score)

    # ---- DEDUPE ------------------------------------------------------------
    cutoff = (datetime.now(timezone.utc) - timedelta(days=DEDUPE_LOOKBACK_DAYS)
              ).isoformat()
    dup_match = None
    dup_distance = None
    cursor = db.cto_photo_validations.find(
        {"company_id": company_id, "created_at": {"$gte": cutoff}},
        {"_id": 0, "phash": 1, "sha1": 1, "cto_id": 1, "id": 1,
         "created_at": 1, "collaborator_id": 1},
    )
    async for prev in cursor:
        # Same byte-by-byte image = perfect duplicate
        if prev.get("sha1") == sha1:
            dup_match = prev
            dup_distance = 0
            break
        h = prev.get("phash")
        if not h:
            continue
        try:
            dist = _hamming_hex(phash, h)
        except Exception:
            continue
        if dist <= DEDUPE_HAMMING_THRESHOLD:
            dup_match = prev
            dup_distance = dist
            break
    dedupe_score = 100 if dup_match is None else max(0,
        int(round(100 * dup_distance / DEDUPE_HAMMING_THRESHOLD)),
    )

    # ---- GPS ---------------------------------------------------------------
    exif_gps = _extract_exif_gps(raw)
    gps_dist_m = None
    gps_score = 100  # sem EXIF → não penaliza (não dá pra confirmar)
    if exif_gps is not None and lat is not None and lng is not None:
        gps_dist_m = _haversine_m(exif_gps[0], exif_gps[1], lat, lng)
        if gps_dist_m <= GPS_TOLERANCE_M:
            gps_score = 100
        else:
            # >150m: cai 1 ponto por 10m, mínimo 0
            gps_score = max(0, int(100 - (gps_dist_m - GPS_TOLERANCE_M) / 10))

    # ---- VISION ------------------------------------------------------------
    vision = await _vision_analyze(raw)
    if not vision.get("has_cto"):
        visual_score = 20
    else:
        visual_score = vision.get("quality_score") or 70
        if vision.get("condition") in ("quebrada", "sem_tampa"):
            # foto ainda válida — só sinaliza chamado
            visual_score = max(visual_score, 75)

    # ---- SCORE -------------------------------------------------------------
    score = int(round(
        WEIGHTS["visual"] * visual_score
        + WEIGHTS["gps"] * gps_score
        + WEIGHTS["dedupe"] * dedupe_score,
    ))
    score = max(0, min(100, score))

    # ---- ACTION + MESSAGE --------------------------------------------------
    if not vision.get("has_cto"):
        action = "retake"
        message = (
            "A IA não identificou uma CTO/CE nesta foto. "
            "Aponte a câmera diretamente para a caixa e tente de novo."
        )
    elif dup_match is not None:
        action = "retake"
        message = (
            "Esta foto já foi enviada em outro cadastro. "
            "Tire uma nova foto no momento da instalação."
        )
    elif gps_dist_m is not None and gps_dist_m > GPS_TOLERANCE_M:
        action = "retake"
        message = (
            f"A foto foi tirada a {int(gps_dist_m)} m do ponto informado. "
            "Confirme se você está no local correto."
        )
    elif score < min_score:
        action = "retake"
        message = (
            "Qualidade da foto abaixo do mínimo aceitável "
            f"({score}/100, mínimo {min_score}). Tire uma nova foto "
            "mais nítida e enquadrada."
        )
    elif vision.get("condition") in ("quebrada", "sem_tampa"):
        action = "open_ticket"
        cond_label = (
            "quebrada" if vision.get("condition") == "quebrada" else "sem tampa"
        )
        message = (
            f"CTO detectada como {cond_label}. A foto está OK, mas "
            "recomendamos abrir um chamado de manutenção para esta caixa."
        )
    else:
        action = "approve"
        message = "Foto aprovada pela Sentinela IA."

    open_ticket_hint = None
    if vision.get("condition") in ("quebrada", "sem_tampa"):
        open_ticket_hint = {
            "type": "manutencao_rede",
            "priority": "alta" if vision.get("condition") == "quebrada"
                          else "media",
            "title": ("CTO quebrada"
                       if vision.get("condition") == "quebrada"
                       else "CTO sem tampa"),
            "summary": vision.get("reasoning", ""),
            "lat": lat, "lng": lng,
        }

    result: Dict[str, Any] = {
        "ok": action == "approve",
        "action": action,
        "score": score,
        "min_score": min_score,
        "message": message,
        "breakdown": {
            "visual": int(visual_score),
            "gps": int(gps_score),
            "dedupe": int(dedupe_score),
        },
        "vision": vision,
        "gps_check": {
            "photo_lat": exif_gps[0] if exif_gps else None,
            "photo_lng": exif_gps[1] if exif_gps else None,
            "reported_lat": lat, "reported_lng": lng,
            "distance_m": int(gps_dist_m) if gps_dist_m is not None else None,
            "tolerance_m": GPS_TOLERANCE_M,
        },
        "dedupe": {
            "duplicate_of": (dup_match or {}).get("id") if dup_match else None,
            "duplicate_cto_id": (dup_match or {}).get("cto_id")
                                  if dup_match else None,
            "distance_bits": dup_distance,
        },
        "phash": phash, "sha1": sha1,
        "open_ticket_hint": open_ticket_hint,
    }

    if persist:
        try:
            await db.cto_photo_validations.insert_one({
                "id": str(uuid.uuid4()),
                "company_id": company_id,
                "collaborator_id": collaborator_id,
                "element_type": element_type,
                "sha1": sha1, "phash": phash,
                "score": score, "action": action,
                "vision": vision,
                "gps_check": result["gps_check"],
                "dedupe": result["dedupe"],
                "lat": lat, "lng": lng,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            log.warning("[validator] persist falhou: %s", e)

    return result
