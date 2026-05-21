"""CTO Photo Inspector — análise via IA (vision) de fotos de CTO.

Usa Emergent LLM Key + Gemini 2.5 Flash (vision) para gerar tags,
severidade e recomendações sobre o estado físico da CTO.

Cache: análise é salva em `cto_photo_analyses` (por hash da imagem) para
evitar recomputar a cada visualização.
"""
import base64
import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from database import db

load_dotenv()
log = logging.getLogger("cto_photo_inspector")

_PROMPT = """\
Você é um INSPETOR TÉCNICO DE REDE FTTH (fibra ótica). Você está analisando
uma foto de uma CAIXA TERMINAL ÓPTICA (CTO) instalada em campo (poste ou
fachada). Sua missão é gerar uma análise objetiva da CONDIÇÃO FÍSICA dela.

INSTRUÇÕES IMPORTANTES:
- Responda APENAS em JSON válido (sem markdown, sem ```), sem comentários.
- Use português brasileiro.
- Seja conservador na severidade — só dê >70 se houver risco real.
- Se a foto não parecer ser de uma CTO (foto borrada, foto de pessoa,
  paisagem etc), retorne severity=0 e tags=[\"foto_nao_identificada\"].

Tags possíveis (use só as relevantes, máx 5):
  organizada, cabo_desorganizado, splice_exposto, sem_tampa, danificada,
  sujeira_acumulada, exposta_ao_sol, ferrugem, identificacao_ausente,
  identificacao_ok, fixacao_ruim, fixacao_ok, agua_infiltracao, foto_borrada,
  foto_nao_identificada

Schema de resposta:
{
  "severity": 0..100,
  "summary": "frase curta (máx 90 chars)",
  "tags": ["..."],
  "recommendations": ["...", "..."]   // 0 a 4 itens
}
"""


def _data_url_to_bytes_and_mime(data_url: str) -> tuple[bytes, str]:
    """data:image/jpeg;base64,XXX → (bytes, mime)."""
    m = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", data_url)
    if not m:
        raise ValueError("photo_data_url inválido (esperado data:image/...)")
    mime = m.group(1)
    raw = base64.b64decode(m.group(2))
    return raw, mime


def _sha1(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


async def analyze_cto_photo(data_url: str,
                              cto_id: Optional[str] = None,
                              ticket_id: Optional[str] = None,
                              force_refresh: bool = False) -> Dict[str, Any]:
    """Analisa uma foto via Gemini Vision. Resultado é cacheado por hash.

    Retorna: { severity, summary, tags[], recommendations[], cached, model }
    """
    raw, mime = _data_url_to_bytes_and_mime(data_url)
    if mime not in ("image/jpeg", "image/png", "image/webp"):
        raise ValueError(f"mime não suportado: {mime}")

    digest = _sha1(raw)

    # Cache lookup
    if not force_refresh:
        cached = await db.cto_photo_analyses.find_one({"sha1": digest},
                                                            {"_id": 0})
        if cached and cached.get("result"):
            r = dict(cached["result"])
            r["cached"] = True
            r["model"] = cached.get("model", "gemini-2.5-flash")
            return r

    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise RuntimeError("EMERGENT_LLM_KEY ausente no .env")

    # Lazy import — só carrega se realmente vai analisar
    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

    image_b64 = base64.b64encode(raw).decode("utf-8")
    image_content = ImageContent(image_base64=image_b64)

    session_id = f"cto-inspect-{uuid.uuid4().hex[:8]}"
    chat = LlmChat(
        api_key=api_key,
        session_id=session_id,
        system_message=_PROMPT,
    ).with_model("gemini", "gemini-2.5-flash")

    user_msg = UserMessage(
        text=("Analise esta foto e retorne o JSON conforme o schema. "
              "Nada além do JSON."),
        file_contents=[image_content],
    )

    raw_resp = await chat.send_message(user_msg)
    text = (raw_resp or "").strip()
    # remove fences ```json``` que o modelo às vezes coloca apesar do prompt
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text)

    try:
        parsed = json.loads(text)
    except Exception:
        # fallback — extrai primeiro bloco {...}
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            log.warning("Modelo retornou texto não-JSON: %r", text[:200])
            parsed = {"severity": 0, "summary": "Sem resposta estruturada",
                       "tags": [], "recommendations": []}
        else:
            try:
                parsed = json.loads(m.group(0))
            except Exception:
                parsed = {"severity": 0, "summary": text[:90],
                           "tags": [], "recommendations": []}

    # Sanitiza
    sev = int(parsed.get("severity") or 0)
    sev = max(0, min(100, sev))
    parsed["severity"] = sev
    parsed["summary"] = str(parsed.get("summary") or "")[:200]
    parsed["tags"] = [str(t)[:40] for t in (parsed.get("tags") or [])][:6]
    parsed["recommendations"] = [str(r)[:200] for r in
                                    (parsed.get("recommendations") or [])][:5]
    parsed["cached"] = False
    parsed["model"] = "gemini-2.5-flash"

    # Salva cache
    doc = {
        "id": str(uuid.uuid4()),
        "sha1": digest,
        "cto_id": cto_id, "ticket_id": ticket_id,
        "result": {k: v for k, v in parsed.items() if k not in ("cached",)},
        "model": "gemini-2.5-flash",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await db.cto_photo_analyses.update_one(
            {"sha1": digest}, {"$set": doc}, upsert=True,
        )
    except Exception as e:
        log.warning("Falha cache analyses: %s", e)

    return parsed
