"""Motor IA — unifica TODAS as chamadas de IA (texto, áudio) em um único
ponto, usando OpenRouter como gateway primário multi-provedor.

Por que um único motor?
  OpenRouter já é um gateway que roteia para 400+ modelos (OpenAI, Anthropic,
  Google, Meta, Mistral, etc) e tem **fallback nativo via parâmetro `models`**.
  Ter um segundo motor seria redundante — o fallback já está dentro do OpenRouter.

Áudio (Whisper STT / TTS):
  OpenRouter NÃO suporta endpoints de áudio. Para STT/TTS usamos uma chave
  OpenAI direta opcional (campo `openai_audio_key`). Se não configurada,
  retornamos erro 503 instando o admin a configurar na aba Motor IA.

Config persistida em `motor_ia_config` (Mongo), por company_id:
  - openrouter_api_key (string, plaintext — pode ser cifrado em release futuro)
  - default_text_model        (str, ex.: "anthropic/claude-sonnet-4.5")
  - fallback_models           (list[str], chain de fallback)
  - openai_audio_key          (str, opcional, somente Whisper/TTS)
  - tts_voice                 (str, voz padrão TTS, ex.: "nova")
  - enabled                   (bool)
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from core import DEMO_COMPANY_ID, EMERGENT_LLM_KEY, now_iso
from database import db

logger = logging.getLogger(__name__)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


class AgentDisabledError(RuntimeError):
    """Lançado quando o agente foi desligado pelo admin (kill-switch)."""
    def __init__(self, agent_id: str):
        super().__init__(f"Agente '{agent_id}' está desativado pelo administrador.")
        self.agent_id = agent_id


# Catálogo de agentes que podem ser ligados/desligados via painel.
# Mantido em sync com os `agent=` usados em chat_completion(). Ordem é a
# ordem de exibição no modal de controle.
AGENT_CATALOG: List[Dict[str, str]] = [
    {"id": "smartolt_ai",         "label": "SmartOLT AI",
     "group": "Rede óptica",
     "description": "Detecção e análise de panes na rede óptica (PON/ONU)."},
    {"id": "proactive_outage_context", "label": "Contexto de Pane (proativo)",
     "group": "Rede óptica",
     "description": "Redige snippet de histórico de OLT para notificação WhatsApp."},
    {"id": "sentinela_lousa",     "label": "Sentinela Lousa",
     "group": "Operação · Lousa",
     "description": "Monitora SLA, inatividade e sobrecarga de técnicos."},
    {"id": "lousa_triagem",       "label": "Lousa AI · Triagem",
     "group": "Operação · Lousa",
     "description": "Classifica novos tickets (tipo, prioridade, técnico, SLA)."},
    {"id": "copilot_ai",          "label": "Co-Pilot IA",
     "group": "Atendimento",
     "description": "Dicas internas (não visíveis ao cliente) durante atendimentos."},
    {"id": "isabella_whatsapp",   "label": "Isabella (WhatsApp)",
     "group": "Atendimento",
     "description": "Atendimento automático via WhatsApp (Baileys)."},
    {"id": "voice_ai",            "label": "Voice AI",
     "group": "Atendimento",
     "description": "Atendimento por voz / SIP."},
    {"id": "central_ia_eval",     "label": "Central IA · Avaliação",
     "group": "Qualidade",
     "description": "Avalia CSAT/sentimento/FCR de conversas finalizadas."},
    {"id": "central_ia_coach",    "label": "Central IA · Coaching",
     "group": "Qualidade",
     "description": "Gera coaching para atendentes pós-conversa."},
    {"id": "aihub_chat",          "label": "AI Hub · Chat",
     "group": "AI Hub",
     "description": "Chat com agentes customizados criados no AI Hub."},
    {"id": "aihub_textgen",       "label": "AI Hub · TextGen",
     "group": "AI Hub",
     "description": "Geração/aprimoramento de texto em formulários."},
    {"id": "ai_dashboard_insight","label": "Dashboard Insights",
     "group": "Insights & Analytics",
     "description": "Insights automáticos sobre dashboards operacionais."},
    {"id": "churn_insight",       "label": "Churn Insight",
     "group": "Insights & Analytics",
     "description": "Briefing executivo do dashboard de churn (Claude Sonnet 4.5)."},
    {"id": "secretaria_ia",       "label": "Secretária IA (Ligo)",
     "group": "Assistente Executivo",
     "description": "Assistente executiva. Responde perguntas do gestor sobre dados do sistema, integrada ao WhatsApp e GPT customizado."},
    {"id": "alvaro_ai",           "label": "Alvaro IA · Analista",
     "group": "Insights & Analytics",
     "description": "Analisa conversas WhatsApp das últimas 24h e gera relatório consolidado (Deepseek)."},
    {"id": "disparo_ia",          "label": "Disparo IA · Estrategista",
     "group": "Comunicação ativa",
     "description": "Estrategista que orquestra Alvaro (insights) + Isabella (execução) para criar campanhas WhatsApp ativas (Claude Sonnet 4.5)."},
]
AGENT_IDS = {a["id"] for a in AGENT_CATALOG}

DEFAULT_TEXT_MODEL = "anthropic/claude-sonnet-4.5"
DEFAULT_FALLBACKS = [
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-3.5-sonnet",
    "openai/gpt-4o-mini",
    "google/gemini-2.0-flash-exp:free",
    "meta-llama/llama-3.3-70b-instruct",
]
DEFAULT_TTS_VOICE = "nova"

# Motor DEDICADO para Agentes de Atendimento (WhatsApp/Jerusa).
# DeepSeek é forte em pt-BR e tem custo ~10x menor que GPT-4o.
# Atendimento NÃO pode usar outros modelos — política do negócio.
ATENDIMENTO_MODEL = "deepseek/deepseek-chat"
ATENDIMENTO_FALLBACKS = ["deepseek/deepseek-r1", "deepseek/deepseek-chat-v3.1"]


async def get_motor_config(company_id: str) -> Dict[str, Any]:
    """Lê config do motor para a empresa. Cria default se não existir."""
    doc = await db.motor_ia_config.find_one(
        {"company_id": company_id}, {"_id": 0}
    )
    if not doc:
        doc = {
            "company_id": company_id,
            "openrouter_api_key": "",
            "default_text_model": DEFAULT_TEXT_MODEL,
            "fallback_models": DEFAULT_FALLBACKS,
            "atendimento_model": ATENDIMENTO_MODEL,
            "atendimento_fallbacks": ATENDIMENTO_FALLBACKS,
            "openai_audio_key": "",
            "tts_voice": DEFAULT_TTS_VOICE,
            "enabled": False,
            "created_at": now_iso(),
        }
        await db.motor_ia_config.insert_one(dict(doc))
        doc.pop("_id", None)
    # Backfill atendimento fields para docs antigos
    if "atendimento_model" not in doc:
        doc["atendimento_model"] = ATENDIMENTO_MODEL
    if "atendimento_fallbacks" not in doc:
        doc["atendimento_fallbacks"] = ATENDIMENTO_FALLBACKS
    return doc


async def save_motor_config(company_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Persiste config (upsert). Permite atualização parcial."""
    update: Dict[str, Any] = {"updated_at": now_iso()}
    for k in ("openrouter_api_key", "default_text_model", "fallback_models",
                "atendimento_model", "atendimento_fallbacks",
                "openai_audio_key", "tts_voice", "enabled"):
        if k in payload:
            update[k] = payload[k]
    await db.motor_ia_config.update_one(
        {"company_id": company_id},
        {"$set": update,
         "$setOnInsert": {"company_id": company_id, "created_at": now_iso()}},
        upsert=True,
    )
    return await get_motor_config(company_id)


def _mask_key(k: Optional[str]) -> str:
    if not k:
        return ""
    s = str(k)
    if len(s) <= 8:
        return "***"
    return f"{s[:6]}...{s[-4:]}"


async def get_safe_config(company_id: str) -> Dict[str, Any]:
    """Versão da config para o frontend — mascara API keys."""
    cfg = await get_motor_config(company_id)
    return {
        **cfg,
        "openrouter_api_key": _mask_key(cfg.get("openrouter_api_key")),
        "openai_audio_key": _mask_key(cfg.get("openai_audio_key")),
        "has_openrouter_key": bool(cfg.get("openrouter_api_key")),
        "has_audio_key": bool(cfg.get("openai_audio_key")),
    }


def _build_text_client(api_key: str):
    """Instancia cliente OpenAI apontando para OpenRouter."""
    from openai import AsyncOpenAI
    return AsyncOpenAI(base_url=OPENROUTER_BASE, api_key=api_key,
                        default_headers={
                            "HTTP-Referer": "https://emergentagent.com",
                            "X-Title": "PontolA Atendimento IA",
                        })


async def chat_completion(company_id: str,
                            messages: List[Dict[str, str]],
                            model: Optional[str] = None,
                            temperature: float = 0.7,
                            max_tokens: int = 500,
                            json_mode: bool = False,
                            purpose: str = "general",
                            agent: Optional[str] = None) -> Dict[str, Any]:
    """Gera resposta de chat via OpenRouter. Caller passa lista de messages
    (formato OpenAI: [{role, content}, ...]).

    Args:
        purpose: "atendimento" força DeepSeek (motor dedicado para agentes
                 de atendimento WhatsApp/Jerusa). "general" usa o modelo
                 configurado em motor_ia_config (default OpenAI/GPT-4o-mini).
        agent: identificador do agente chamador (ex.: "smartolt_ai",
               "sentinela_lousa", "lousa_triagem"). Usado para o dashboard
               de custos. Se None, usa `purpose`.

    Returns: {"content": str, "model": str, "provider": str}.
    Raises RuntimeError se motor não configurado.
    """
    cid = company_id or DEMO_COMPANY_ID
    cfg = await get_motor_config(cid)
    api_key = cfg.get("openrouter_api_key") or ""

    # Kill-switch por agente (configurado em Motor IA → Painel de Agentes).
    # Se o agente foi desligado pelo admin, aborta antes de gastar tokens.
    agent_id = agent or purpose
    if agent_id and agent_id not in ("general",):
        if not await is_agent_enabled(cid, agent_id):
            raise AgentDisabledError(agent_id)

    if not cfg.get("enabled") or not api_key:
        # Fallback de segurança: se admin não configurou ainda, cai pra
        # EMERGENT_LLM_KEY (compat com setup antigo). Loga warning.
        if EMERGENT_LLM_KEY:
            logger.warning("[motor-ia] cfg ausente — usando EMERGENT_LLM_KEY fallback")
            return await _emergent_chat_fallback(messages, model, temperature, max_tokens)
        raise RuntimeError("Motor IA não configurado. Configure em Sistemas → Motor IA.")

    # REGRA DE NEGÓCIO: agentes de atendimento usam APENAS DeepSeek.
    # Ignora `model` recebido do caller e força configuração de atendimento.
    if purpose == "atendimento":
        primary = cfg.get("atendimento_model") or ATENDIMENTO_MODEL
        fallbacks = [m for m in (cfg.get("atendimento_fallbacks") or ATENDIMENTO_FALLBACKS)
                       if m != primary]
    else:
        primary = model or cfg.get("default_text_model") or DEFAULT_TEXT_MODEL
        fallbacks = [m for m in (cfg.get("fallback_models") or []) if m != primary]

    extra_body: Dict[str, Any] = {}
    if fallbacks:
        # OpenRouter limita o array `models` a no máximo 3 itens.
        chain = ([primary] + fallbacks)[:3]
        extra_body["models"] = chain

    client = _build_text_client(api_key)
    kwargs: Dict[str, Any] = {
        "model": primary,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "extra_body": extra_body,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = await client.chat.completions.create(**kwargs)
    content = (resp.choices[0].message.content or "").strip()
    used_model = getattr(resp, "model", primary)
    provider = getattr(resp, "provider", None) or "openrouter"

    # Detecta resposta corrompida (modelo gerou token garbage no meio).
    # Causas comuns: V4 Pro instável, context overflow, repetition penalty 0.
    # Se detectada, tenta automaticamente os fallbacks na ordem.
    if _is_garbage_response(content):
        logger.warning(
            "[motor-ia] resposta corrompida detectada (model=%s, len=%d). "
            "Iniciando retry com fallbacks...",
            used_model, len(content),
        )
        for fb_model in fallbacks:
            try:
                kwargs["model"] = fb_model
                kwargs["extra_body"] = {}  # sem cadeia OR
                resp2 = await client.chat.completions.create(**kwargs)
                content2 = (resp2.choices[0].message.content or "").strip()
                if not _is_garbage_response(content2):
                    content = content2
                    used_model = getattr(resp2, "model", fb_model)
                    provider = getattr(resp2, "provider", None) or "openrouter"
                    logger.info("[motor-ia] fallback %s gerou resposta limpa.", fb_model)
                    break
                logger.warning("[motor-ia] fallback %s também corrompido.", fb_model)
            except Exception as e:
                logger.warning("[motor-ia] fallback %s ERRO: %s", fb_model, e)

    # Registra uso (best-effort, não bloqueia resposta)
    try:
        usage = getattr(resp, "usage", None)
        pt = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        ct = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
        await _log_usage(cid, agent or purpose, used_model, provider, pt, ct)
    except Exception as e:
        logger.warning(f"[motor-ia] usage log falhou: {e}")

    return {
        "content": content,
        "model": used_model,
        "provider": provider,
    }


def _is_garbage_response(text: str) -> bool:
    """Detecta respostas corrompidas/incoerentes que LLMs instáveis produzem
    quando entram em loop. Sinais:
    - Mais de 4% de caracteres em scripts estrangeiros (CJK, Cyrillic, Coreano,
      Árabe, Hebraico, Tailandês, Grego, etc.) — IA pt-BR não deve emitir isso.
    - Sequências de palavras-coladas estilo "PROMLesterNOT" (uppercase no meio
      de minúsculas, multiple times)
    - Caracteres de controle não-imprimíveis
    """
    if not text or len(text) < 20:
        return False

    # 1) Conta chars em scripts não-latinos (mas permite emoji + acentos PT-BR)
    foreign = 0
    countable = 0
    for ch in text:
        cp = ord(ch)
        # Pular whitespace, pontuação ASCII e quebras
        if cp < 0x80:
            countable += 1
            continue
        # Emoji range (Misc Symbols, Pictographs, etc.) — não conta como garbage
        if (0x2600 <= cp <= 0x27BF) or (0x1F000 <= cp <= 0x1FFFF):
            countable += 1
            continue
        # Acentos latinos (Latin-1 Supplement + Latin Extended-A/B): permitido
        if 0x00C0 <= cp <= 0x024F:
            countable += 1
            continue
        # Pontuação geral
        if 0x2000 <= cp <= 0x206F:
            countable += 1
            continue
        # Qualquer outro chunk fora desses é foreign (cyrillic, CJK, greek,
        # arabic, hebrew, korean, thai, japanese kana...)
        foreign += 1
        countable += 1
    if countable > 0 and foreign / countable > 0.04:
        return True

    # 2) Palavras coladas (loop de geração): "PROMLesterNOT", "ridgeáriaToday"
    # Regex captura uppercase no meio de minúsculas — 2+ ocorrências = suspeito
    import re as _re
    weird_caps = _re.findall(r"\b[a-záéíóúâêôãõç]{2,}[A-Z][a-záéíóúâêôãõç]{2,}", text)
    if len(weird_caps) >= 2:
        return True

    # 3) Sequências curtas de palavras + UPPERCASE puro (não-acrônimo) — sinal
    # de "lixo gerado": "PROMLesterNOT_db003 Recall removes753anske"
    # Detecta 3+ palavras seguidas com mix CAPS/digit caótico
    chunks = _re.findall(r"[A-Z]{2,}[a-z]+\w*[A-Z]", text)
    if len(chunks) >= 3:
        return True

    # 4) Caracteres de controle não-permitidos
    control = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\r\t")
    if control > 2:
        return True

    return False


# ---------------------------------------------------------------------------
# Tabela de preços (USD por 1M tokens) — best-effort, mantida manualmente.
# Fonte: openrouter.ai/models. Atualizar conforme novos modelos forem usados.
# ---------------------------------------------------------------------------
MODEL_PRICING: Dict[str, Dict[str, float]] = {
    # Anthropic
    "anthropic/claude-sonnet-4.5":      {"in": 3.0,  "out": 15.0},
    "anthropic/claude-4.5-sonnet":      {"in": 3.0,  "out": 15.0},
    "anthropic/claude-opus-4.5":        {"in": 15.0, "out": 75.0},
    "anthropic/claude-haiku-4.5":       {"in": 0.8,  "out": 4.0},
    "anthropic/claude-3.5-sonnet":      {"in": 3.0,  "out": 15.0},
    "anthropic/claude-3-haiku":         {"in": 0.25, "out": 1.25},
    # OpenAI
    "openai/gpt-4o":                    {"in": 2.5,  "out": 10.0},
    "openai/gpt-4o-mini":               {"in": 0.15, "out": 0.6},
    # DeepSeek
    "deepseek/deepseek-chat":           {"in": 0.27, "out": 1.10},
    "deepseek/deepseek-r1":             {"in": 0.55, "out": 2.19},
    "deepseek/deepseek-chat-v3.1":      {"in": 0.27, "out": 1.10},
    "deepseek/deepseek-v4-flash":       {"in": 0.27, "out": 1.10},
    # Google / Meta (free/cheap)
    "google/gemini-2.0-flash-exp:free": {"in": 0.0,  "out": 0.0},
    "meta-llama/llama-3.3-70b-instruct":{"in": 0.59, "out": 0.79},
}


def _estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estima custo em USD baseado na tabela acima. Faz match case-insensitive
    e tenta também por prefixo (ex.: 'anthropic/claude-4.5-sonnet-20250929'
    casa com 'anthropic/claude-4.5-sonnet')."""
    if not model:
        return 0.0
    m = model.lower()
    price = MODEL_PRICING.get(m)
    if not price:
        # tenta por prefixo
        for k, v in MODEL_PRICING.items():
            if m.startswith(k):
                price = v
                break
    if not price:
        return 0.0
    return round(
        (prompt_tokens / 1_000_000) * price["in"]
        + (completion_tokens / 1_000_000) * price["out"],
        6,
    )


async def _log_usage(company_id: str, agent: str, model: str,
                       provider: str, prompt_tokens: int, completion_tokens: int):
    """Persiste uma linha em `motor_ia_usage` (best-effort)."""
    if prompt_tokens == 0 and completion_tokens == 0:
        return
    cost = _estimate_cost_usd(model, prompt_tokens, completion_tokens)
    await db.motor_ia_usage.insert_one({
        "company_id": company_id,
        "agent": agent or "general",
        "model": model,
        "provider": provider,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "estimated_cost_usd": cost,
        "created_at": now_iso(),
    })

    # Check de orçamento (best-effort, não bloqueia). Loga warn quando
    # gasto do mês ultrapassa o threshold ou o limite. Só executa se
    # orçamento estiver habilitado para a company.
    try:
        await _check_budget_alert(company_id)
    except Exception as e:
        logger.debug(f"[motor-ia] budget check falhou: {e}")


async def _check_budget_alert(company_id: str):
    """Compara gasto do mês com o limite configurado e loga alerta."""
    from datetime import datetime, timezone
    budget = await db.motor_ia_budget.find_one(
        {"company_id": company_id, "enabled": True}, {"_id": 0})
    if not budget:
        return
    limit = float(budget.get("monthly_limit_usd") or 0)
    if limit <= 0:
        return
    threshold_pct = int(budget.get("warn_threshold_pct") or 80)
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    pipe = [
        {"$match": {"company_id": company_id, "created_at": {"$gte": start}}},
        {"$group": {"_id": None, "spent": {"$sum": "$estimated_cost_usd"}}},
    ]
    agg = await db.motor_ia_usage.aggregate(pipe).to_list(1)
    spent = float(agg[0]["spent"]) if agg else 0.0
    used_pct = (spent / limit) * 100
    if used_pct >= 100:
        logger.warning(
            f"[motor-ia][BUDGET] Limite mensal EXCEDIDO para {company_id}: "
            f"${spent:.4f} / ${limit:.2f} ({used_pct:.1f}%)")
    elif used_pct >= threshold_pct:
        logger.warning(
            f"[motor-ia][BUDGET] Aviso de orçamento {company_id}: "
            f"${spent:.4f} / ${limit:.2f} ({used_pct:.1f}%) — threshold {threshold_pct}%")


async def _emergent_chat_fallback(messages, model, temperature, max_tokens):
    """Fallback temporário usando emergentintegrations (sai depois)."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    import uuid
    session_id = f"motoria-{uuid.uuid4().hex[:8]}"
    sys_prompt = next((m["content"] for m in messages if m["role"] == "system"), "")
    user_msg = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message=sys_prompt,
    ).with_model("openai", "gpt-5-mini").with_max_tokens(max_tokens)
    out = await chat.send_message(UserMessage(text=user_msg))
    return {"content": str(out).strip(), "model": "gpt-5-mini (emergent)", "provider": "emergent"}


# ---------------------------------------------------------------------------
# Áudio — OpenAI direto (OpenRouter não suporta)
# ---------------------------------------------------------------------------
async def transcribe_audio(company_id: str, audio_bytes: bytes,
                              filename: str = "audio.webm") -> str:
    """Transcreve áudio usando Whisper. Requer openai_audio_key configurada."""
    cfg = await get_motor_config(company_id or DEMO_COMPANY_ID)
    key = cfg.get("openai_audio_key") or ""
    if not key:
        # Compat: usa EMERGENT_LLM_KEY como fallback se admin não configurou ainda
        if EMERGENT_LLM_KEY:
            from emergentintegrations.llm.openai import OpenAISpeechToText
            stt = OpenAISpeechToText(api_key=EMERGENT_LLM_KEY)
            return await stt.transcribe(audio_bytes, filename=filename)
        raise RuntimeError("OpenAI audio key não configurada. Configure em Sistemas → Motor IA.")
    # OpenAI direto via SDK
    from openai import AsyncOpenAI
    import io
    client = AsyncOpenAI(api_key=key)
    f = io.BytesIO(audio_bytes)
    f.name = filename
    resp = await client.audio.transcriptions.create(model="whisper-1", file=f)
    return resp.text


async def text_to_speech(company_id: str, text: str,
                            voice: Optional[str] = None) -> bytes:
    """Gera áudio MP3 a partir de texto via OpenAI TTS."""
    cfg = await get_motor_config(company_id or DEMO_COMPANY_ID)
    key = cfg.get("openai_audio_key") or ""
    v = voice or cfg.get("tts_voice") or DEFAULT_TTS_VOICE
    if not key:
        if EMERGENT_LLM_KEY:
            from emergentintegrations.llm.openai import OpenAITextToSpeech
            tts = OpenAITextToSpeech(api_key=EMERGENT_LLM_KEY)
            return await tts.synthesize(text, voice=v)
        raise RuntimeError("OpenAI audio key não configurada. Configure em Sistemas → Motor IA.")
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=key)
    resp = await client.audio.speech.create(model="tts-1", voice=v, input=text)
    return resp.content


async def test_motor(company_id: str) -> Dict[str, Any]:
    """Smoke test rápido — chama OpenRouter com 'ping' pra validar credenciais."""
    try:
        r = await chat_completion(
            company_id,
            [{"role": "user", "content": "Responda apenas: ok"}],
            max_tokens=10, temperature=0,
        )
        return {"ok": True, "model": r["model"], "provider": r["provider"],
                "sample": r["content"][:100]}
    except Exception as e:
        return {"ok": False, "error": str(e)}



# ---------------------------------------------------------------------------
# Kill-switch por agente
# ---------------------------------------------------------------------------

async def is_agent_enabled(company_id: str, agent_id: str) -> bool:
    """Retorna False se o agente foi desligado pelo admin. Default True
    (sem registro = ativo). Agentes desconhecidos passam (default True)."""
    if not agent_id or agent_id not in AGENT_IDS:
        return True
    doc = await db.ai_agent_switches.find_one(
        {"company_id": company_id, "agent_id": agent_id},
        {"_id": 0, "enabled": 1},
    )
    if not doc:
        return True
    return bool(doc.get("enabled", True))


async def get_agents_state(company_id: str) -> List[Dict[str, Any]]:
    """Retorna catálogo de agentes com estado atual (enabled + metadata)."""
    cur = db.ai_agent_switches.find(
        {"company_id": company_id},
        {"_id": 0, "agent_id": 1, "enabled": 1, "updated_at": 1,
         "updated_by": 1, "paused_until": 1},
    )
    state: Dict[str, Dict[str, Any]] = {}
    async for d in cur:
        state[d["agent_id"]] = d
    out = []
    for a in AGENT_CATALOG:
        s = state.get(a["id"], {})
        out.append({
            "id": a["id"],
            "label": a["label"],
            "group": a.get("group") or "Outros",
            "description": a["description"],
            "enabled": bool(s.get("enabled", True)),
            "updated_at": s.get("updated_at"),
            "updated_by": s.get("updated_by"),
            "paused_until": s.get("paused_until"),
        })
    return out


async def set_agent_state(company_id: str, agent_id: str,
                            enabled: bool, user_label: Optional[str] = None,
                            paused_until: Optional[str] = None) -> Dict[str, Any]:
    """Persiste estado do kill-switch e registra histórico (auditoria).

    Args:
      paused_until: ISO datetime UTC. Se enabled=False e paused_until informado,
        o auto-resume worker irá reativar automaticamente após essa hora.
        Se enabled=True, paused_until é limpo.

    Lança ValueError se agent_id inválido."""
    if agent_id not in AGENT_IDS:
        raise ValueError(f"Agente desconhecido: {agent_id}")

    prev = await db.ai_agent_switches.find_one(
        {"company_id": company_id, "agent_id": agent_id},
        {"_id": 0, "enabled": 1},
    )
    prev_enabled = bool(prev.get("enabled", True)) if prev else True
    changed = prev_enabled != bool(enabled)

    ts = now_iso()
    set_doc = {
        "enabled": bool(enabled),
        "updated_at": ts,
        "updated_by": user_label or "system",
    }
    # paused_until só faz sentido quando estamos PAUSANDO
    if not enabled and paused_until:
        set_doc["paused_until"] = paused_until
    elif enabled:
        # Limpa qualquer agendamento prévio ao reativar
        set_doc["paused_until"] = None

    await db.ai_agent_switches.update_one(
        {"company_id": company_id, "agent_id": agent_id},
        {"$set": set_doc,
         "$setOnInsert": {"company_id": company_id, "agent_id": agent_id}},
        upsert=True,
    )

    if changed:
        await db.ai_agent_switch_history.insert_one({
            "company_id": company_id,
            "agent_id": agent_id,
            "previous_enabled": prev_enabled,
            "enabled": bool(enabled),
            "changed_by": user_label or "system",
            "changed_at": ts,
            "paused_until": paused_until if not enabled else None,
        })

    return {"agent_id": agent_id, "enabled": bool(enabled),
              "changed": changed, "paused_until": paused_until if not enabled else None}


async def get_agent_history(company_id: str, days: int = 30) -> List[Dict[str, Any]]:
    """Retorna eventos de mudança ordenados (mais recente primeiro)."""
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cur = db.ai_agent_switch_history.find(
        {"company_id": company_id, "changed_at": {"$gte": cutoff}},
        {"_id": 0},
    ).sort("changed_at", -1).limit(500)
    return [d async for d in cur]



# ---------------------------------------------------------------------------
# Auto-resume worker: reativa agentes quando `paused_until` vence
# ---------------------------------------------------------------------------
import asyncio  # noqa: E402

_auto_resume_task: Optional[asyncio.Task] = None
AUTO_RESUME_CHECK_SECONDS = 60


async def _auto_resume_loop():
    while True:
        try:
            from datetime import datetime, timezone
            now_iso_str = datetime.now(timezone.utc).isoformat()
            cursor = db.ai_agent_switches.find(
                {"enabled": False,
                 "paused_until": {"$ne": None, "$lt": now_iso_str}},
                {"_id": 0, "company_id": 1, "agent_id": 1, "paused_until": 1},
            )
            async for doc in cursor:
                try:
                    await set_agent_state(
                        doc["company_id"], doc["agent_id"],
                        enabled=True, user_label="auto_resume",
                    )
                    logger.info(
                        "[motor-ia] auto-resume %s/%s (paused_until=%s)",
                        doc["company_id"], doc["agent_id"],
                        doc.get("paused_until"))
                except Exception as e:
                    logger.warning("[motor-ia] auto-resume falhou: %s", e)
        except Exception as e:
            logger.exception("[motor-ia] auto-resume loop err: %s", e)
        await asyncio.sleep(AUTO_RESUME_CHECK_SECONDS)


def start_auto_resume_worker():
    global _auto_resume_task
    if _auto_resume_task and not _auto_resume_task.done():
        return
    _auto_resume_task = asyncio.create_task(_auto_resume_loop())
    logger.info("[motor-ia] auto-resume worker iniciado (check %ds)",
                  AUTO_RESUME_CHECK_SECONDS)


def stop_auto_resume_worker():
    global _auto_resume_task
    if _auto_resume_task and not _auto_resume_task.done():
        _auto_resume_task.cancel()
