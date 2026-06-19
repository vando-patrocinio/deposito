"""Voz da Jerusa — chamadas de voz turno-a-turno.

Pipeline (turno-a-turno, simples e confiável):
   browser/SIP envia áudio → Whisper STT → LLM (agente Jerusa) → OpenAI TTS → mp3 de volta

Endpoints:
- POST /api/voice/sessions/start          → cria sessão + saudação em áudio (Jerusa)
- POST /api/voice/sessions/{sid}/turn     → multipart com audio do cliente; retorna {transcript, reply_text, reply_audio_b64}
- POST /api/voice/sessions/{sid}/end      → salva a chamada no histórico (aihub_calls)
- POST /api/voice/sip/incoming            → webhook stub p/ MagnusBilling/AGI plugar depois

Tudo via EMERGENT_LLM_KEY (Whisper + LLM + TTS). Sem chaves extras.
"""
from __future__ import annotations


from services.exception_sanitizer import safe_detail  # SECURITY_LOCK ART.13
NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import base64
import logging
import time
import uuid
from io import BytesIO
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, EMERGENT_LLM_KEY, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.voice")
router = APIRouter(prefix="/api/voice", tags=["voice"])


# ---------------------------------------------------------------------------
# Configuração da Jerusa (padrão)
# ---------------------------------------------------------------------------
JERUSA_DEFAULT_NAME = "Jerusa"
JERUSA_DEFAULT_GREETING = (
    "Olá! Aqui é a Jerusa, da Ligo Fibra. Em que posso te ajudar hoje?"
)
JERUSA_DEFAULT_PROMPT = """Você é a JERUSA, atendente virtual de uma empresa de internet (provedor ISP).

Estilo:
- Português brasileiro coloquial, voz feminina, simpática mas objetiva.
- Frases curtas (1-2 sentenças por vez). Você está ao TELEFONE — não use formatação, listas, emojis ou markdown. Apenas texto natural que será lido em voz alta.
- Não repita "Olá" toda vez. Cumprimente uma vez no início e siga a conversa.

O que você FAZ:
1. Identifica o cliente: peça nome completo e CPF se ainda não souber.
2. Entende o problema: lentidão, sem sinal, dúvida na fatura, mudança de plano, agendamento de visita.
3. Resolve quando possível ou cria um chamado/agendamento.
4. Encerra educadamente quando o cliente disser que não precisa de mais nada.

Regras:
- Se o cliente pedir para falar com humano, diga "Vou te transferir, um momento" e encerre.
- Se a chamada estiver muda há muito tempo, pergunte "Você ainda está aí?".
- NUNCA invente dados (CPF, plano, valor) — peça ao cliente ou diga que vai verificar.
"""

JERUSA_TTS_VOICE = "nova"  # voz feminina energética, boa em pt-BR
JERUSA_TTS_MODEL = "tts-1"  # rápido, latência baixa
JERUSA_STT_MODEL = "whisper-1"
JERUSA_LLM_PROVIDER = "openai"
JERUSA_LLM_MODEL = "gpt-4o-mini"  # rápido para conversação

# Cache em memória do mp3 da saudação default (evita chamar TTS a cada ligação)
_GREETING_CACHE: Dict[str, bytes] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


async def _ensure_jerusa_agent(company_id: str) -> dict:
    """Garante que existe um agente Jerusa configurado. Cria se necessário."""
    agent = await db.aihub_agents.find_one(
        {"company_id": company_id, "name": JERUSA_DEFAULT_NAME},
        {"_id": 0},
    )
    if agent:
        return agent
    aid = f"agent-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": aid,
        "company_id": company_id,
        "name": JERUSA_DEFAULT_NAME,
        "description": "Atendente virtual de voz (telefone/WebRTC).",
        "initial_message": JERUSA_DEFAULT_GREETING,
        "system_prompt": JERUSA_DEFAULT_PROMPT,
        "model_provider": JERUSA_LLM_PROVIDER,
        "model_name": JERUSA_LLM_MODEL,
        "temperature": 0.6,
        "max_tokens": 350,  # respostas curtas para voz
        "tools_enabled": ["transfer_to_human", "hangup"],
        "form_fields": [],
        "active": True,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": "system:voice",
    }
    await db.aihub_agents.insert_one(dict(doc))
    doc.pop("_id", None)
    logger.info("[voice] Jerusa agent criado em %s (id=%s)", company_id, aid)
    return doc


async def _stt_transcribe(audio_bytes: bytes, filename: str,
                            company_id: str = "") -> str:
    """Transcreve áudio (webm/mp3/wav/m4a) em pt-BR via Motor IA (OpenAI direto)."""
    try:
        from services.motor_ia import transcribe_audio
        return (await transcribe_audio(company_id or DEMO_COMPANY_ID,
                                          audio_bytes, filename) or "").strip()
    except RuntimeError as e:
        raise HTTPException(503, safe_detail(503, e)) from e
    except Exception as e:
        logger.warning("[voice.stt] falhou: %s", e)
        raise HTTPException(502, safe_detail(502, e, "STT falhou:")) from e


async def _tts_speak(text: str, voice: Optional[str] = None,
                       company_id: str = "") -> bytes:
    """Gera mp3 de voz pt-BR via Motor IA (OpenAI direto)."""
    if not text or not text.strip():
        raise HTTPException(400, "Texto vazio para TTS.")
    try:
        from services.motor_ia import text_to_speech
        return await text_to_speech(company_id or DEMO_COMPANY_ID,
                                       text[:4000], voice=voice)
    except RuntimeError as e:
        raise HTTPException(503, safe_detail(503, e)) from e
    except Exception as e:
        logger.warning("[voice.tts] falhou: %s", e)
        raise HTTPException(502, safe_detail(502, e, "TTS falhou:")) from e


async def _llm_reply(agent: dict, session_id: str, user_text: str,
                       company_id: str = "") -> str:
    """Chama o LLM da Jerusa via Motor IA (OpenRouter)."""
    try:
        from services.motor_ia import chat_completion
    except ImportError as e:
        raise HTTPException(500, safe_detail(500, e, "motor_ia indisponível:")) from e
    # Personalidade & Expertise — injeta blocos de info da empresa
    sys_prompt = agent["system_prompt"]
    extra = []
    if agent.get("company_info"):
        extra.append(f"=== INFORMAÇÕES DA EMPRESA ===\n{agent['company_info']}")
    if agent.get("pricing_info"):
        extra.append(f"=== PREÇOS E VALORES ===\n{agent['pricing_info']}")
    if agent.get("priority_situations"):
        extra.append(f"=== SITUAÇÕES PRIORITÁRIAS ===\n{agent['priority_situations']}")
    if "schedule_lousa_ticket" in (agent.get("tools_enabled") or []):
        extra.append(
            "=== AGENDAMENTO DE VISITA TÉCNICA ===\n"
            "Quando o cliente pedir agendamento (instalação/reparo/visita), "
            "colete: nome completo, endereço com número, bairro, telefone, "
            "tipo (instalação/reparo/retirada) e descrição do problema. "
            "Confirme em voz alta e diga \"vou agendar agora\" — o sistema "
            "criará automaticamente uma bolha na Lousa para o próximo técnico "
            "disponível atender. NUNCA prometa horário específico — apenas "
            "diga \"o técnico entrará em contato\"."
        )
    if extra:
        sys_prompt += "\n\n" + "\n\n".join(extra)
    # Histórico curto (voz tem latência, manter compacto)
    history = await db.aihub_messages.find(
        {"session_id": session_id},
        {"_id": 0, "role": 1, "content": 1},
    ).sort("created_at", 1).to_list(12)
    messages = [{"role": "system", "content": sys_prompt}]
    for h in history[-7:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_text})
    try:
        result = await chat_completion(
            company_id or DEMO_COMPANY_ID,
            messages=messages,
            temperature=agent.get("temperature", 0.6),
            max_tokens=agent.get("max_tokens", 350),
            purpose="atendimento",
            agent="voice_ai",
        )
        return (result.get("content") or "").strip()
    except Exception as e:
        logger.warning("[voice.llm] session=%s falhou: %s", session_id, e)
        raise HTTPException(502, safe_detail(502, e, "LLM falhou:")) from e


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
class StartSessionIn(BaseModel):
    caller: Optional[str] = None       # telefone do chamador (se for SIP)
    channel: str = "browser"            # browser | sip


@router.post("/sessions/start")
async def start_session(payload: StartSessionIn,
                          user: dict = Depends(require_role("gestor"))):
    """Inicia sessão de voz com a Jerusa. Retorna a saudação inicial em áudio."""
    cid = _cid(user)
    agent = await _ensure_jerusa_agent(cid)
    session_id = f"voice-{uuid.uuid4().hex[:12]}"

    greeting = agent.get("initial_message") or JERUSA_DEFAULT_GREETING
    started_at = time.time()
    # Cacheia o mp3 da saudação por agente — saudação é determinística
    cache_key = f"{agent['id']}::{greeting}"
    cached = _GREETING_CACHE.get(cache_key)
    if cached is not None:
        audio = cached
        audio_ms = 0  # 0ms = cache hit
    else:
        audio = await _tts_speak(greeting, company_id=cid)
        audio_ms = int((time.time() - started_at) * 1000)
        _GREETING_CACHE[cache_key] = audio

    # Persiste mensagem inicial da Jerusa
    await db.aihub_messages.insert_one({
        "id": f"msg-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "agent_id": agent["id"],
        "session_id": session_id,
        "role": "assistant",
        "content": greeting,
        "created_at": now_iso(),
        "channel": payload.channel,
    })

    # Cria registro da chamada
    await db.aihub_calls.insert_one({
        "id": f"call-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "session_id": session_id,
        "agent_id": agent["id"],
        "agent_name": agent["name"],
        "caller": payload.caller,
        "channel": payload.channel,
        "status": "in_progress",
        "started_at": now_iso(),
        "transcript_lines": [{"role": "assistant", "text": greeting}],
    })

    return {
        "session_id": session_id,
        "agent": {"id": agent["id"], "name": agent["name"]},
        "greeting_text": greeting,
        "greeting_audio_b64": base64.b64encode(audio).decode("ascii"),
        "audio_mime": "audio/mpeg",
        "tts_ms": audio_ms,
    }


@router.post("/sessions/{sid}/turn")
async def session_turn(sid: str,
                        audio: UploadFile = File(...),
                        client_text: str = Form(""),
                        user: dict = Depends(require_role("gestor"))):
    """Recebe um turno de voz do usuário e devolve resposta em áudio.

    `audio`: webm/mp3/wav/m4a (qualquer formato Whisper aceita).
    `client_text` (opcional): se o frontend já tiver transcrito, pula STT.
    """
    cid = _cid(user)
    call = await db.aihub_calls.find_one(
        {"company_id": cid, "session_id": sid}, {"_id": 0})
    if not call:
        raise HTTPException(404, "Sessão de voz não encontrada.")
    if call.get("status") not in (None, "in_progress"):
        raise HTTPException(400, f"Sessão já encerrada (status={call.get('status')}).")

    agent = await db.aihub_agents.find_one(
        {"company_id": cid, "id": call["agent_id"]}, {"_id": 0})
    if not agent:
        raise HTTPException(404, "Agente Jerusa não encontrado para esta sessão.")

    # 1. STT (se cliente não enviou texto pronto)
    t0 = time.time()
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(400, "Áudio vazio.")
    if len(audio_bytes) > 20 * 1024 * 1024:
        raise HTTPException(413, "Áudio muito grande (>20MB).")

    if client_text and client_text.strip():
        transcript = client_text.strip()
        stt_ms = 0
    else:
        transcript = await _stt_transcribe(audio_bytes, audio.filename or "audio.webm",
                                              company_id=cid)
        stt_ms = int((time.time() - t0) * 1000)

    if not transcript:
        # Áudio sem fala detectada — peça gentilmente para repetir
        repeat_text = "Não consegui ouvir direito, pode repetir por favor?"
        repeat_audio = await _tts_speak(repeat_text, company_id=cid)
        return {
            "transcript": "",
            "reply_text": repeat_text,
            "reply_audio_b64": base64.b64encode(repeat_audio).decode("ascii"),
            "audio_mime": "audio/mpeg",
            "stt_ms": stt_ms,
            "llm_ms": 0,
            "tts_ms": 0,
            "no_speech": True,
        }

    # Persiste turno do usuário
    await db.aihub_messages.insert_one({
        "id": f"msg-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "agent_id": agent["id"],
        "session_id": sid,
        "role": "user",
        "content": transcript,
        "created_at": now_iso(),
        "channel": call.get("channel", "browser"),
    })

    # 2. LLM
    t1 = time.time()
    reply_text = await _llm_reply(agent, sid, transcript, company_id=cid)
    llm_ms = int((time.time() - t1) * 1000)

    if not reply_text:
        reply_text = "Desculpe, não entendi. Pode reformular?"

    # Persiste resposta
    await db.aihub_messages.insert_one({
        "id": f"msg-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "agent_id": agent["id"],
        "session_id": sid,
        "role": "assistant",
        "content": reply_text,
        "created_at": now_iso(),
        "channel": call.get("channel", "browser"),
    })

    # 3. TTS
    t2 = time.time()
    reply_audio = await _tts_speak(reply_text, company_id=cid)
    tts_ms = int((time.time() - t2) * 1000)

    # Atualiza transcript da chamada
    await db.aihub_calls.update_one(
        {"company_id": cid, "session_id": sid},
        {"$push": {"transcript_lines": {
            "$each": [
                {"role": "user", "text": transcript},
                {"role": "assistant", "text": reply_text},
            ]
        }}, "$set": {"updated_at": now_iso()}},
    )

    return {
        "transcript": transcript,
        "reply_text": reply_text,
        "reply_audio_b64": base64.b64encode(reply_audio).decode("ascii"),
        "audio_mime": "audio/mpeg",
        "stt_ms": stt_ms,
        "llm_ms": llm_ms,
        "tts_ms": tts_ms,
    }


class EndSessionIn(BaseModel):
    reason: Optional[str] = "user_hangup"


@router.post("/sessions/{sid}/end")
async def end_session(sid: str, payload: EndSessionIn,
                        user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    call = await db.aihub_calls.find_one(
        {"company_id": cid, "session_id": sid}, {"_id": 0})
    if not call:
        raise HTTPException(404, "Sessão não encontrada.")

    started_at_iso = call.get("started_at") or now_iso()
    # Calcula duração aproximada (o ISO usa o now_iso da app)
    transcript_lines = call.get("transcript_lines") or []
    msg_count = await db.aihub_messages.count_documents(
        {"company_id": cid, "session_id": sid})

    await db.aihub_calls.update_one(
        {"company_id": cid, "session_id": sid},
        {"$set": {
            "status": "ended",
            "ended_at": now_iso(),
            "end_reason": payload.reason,
            "msg_count": msg_count,
        }},
    )
    return {
        "ok": True,
        "session_id": sid,
        "started_at": started_at_iso,
        "ended_at": now_iso(),
        "turns": msg_count,
        "transcript_lines": transcript_lines,
    }


@router.get("/sessions/{sid}")
async def get_session(sid: str, user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    call = await db.aihub_calls.find_one(
        {"company_id": cid, "session_id": sid}, {"_id": 0})
    if not call:
        raise HTTPException(404, "Sessão não encontrada.")
    return call


# ---------------------------------------------------------------------------
# SIP webhook stub (MagnusBilling/Asterisk AGI vai postar aqui)
# ---------------------------------------------------------------------------
@router.post("/sip/incoming")
async def sip_incoming(payload: Dict[str, Any]):
    """Stub para receber chamadas SIP. Em produção, MagnusBilling/Asterisk AGI
    deve postar áudio chunk-a-chunk; aqui só registramos o evento.

    ⚠️ SEGURANÇA: Endpoint SEM AUTH. Antes de habilitar SIP real em produção:
      - Adicionar IP allowlist no nginx (apenas IPs do servidor MagnusBilling)
      - OU implementar HMAC: header `X-Signature` = sha256(secret + body)
      Senão qualquer um pode injetar eventos em aihub_webhook_events.
    """
    company_id = payload.get("company_id") or DEMO_COMPANY_ID
    await db.aihub_webhook_events.insert_one({
        "id": f"wh-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "channel": "sip",
        "received_at": now_iso(),
        "payload": payload,
    })
    return {
        "ok": True,
        "note": "Stub. Para SIP real, implemente AGI script no Asterisk que "
                "chame /api/voice/sessions/start, depois faça streaming "
                "turno-a-turno via /api/voice/sessions/{sid}/turn.",
    }
