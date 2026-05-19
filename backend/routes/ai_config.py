"""Endpoint unificado para configuração de IA (card único na UI Settings).

Funcionalidades:
- GET  /api/ai-config              → status de cada provider + ordem da cascata
- PUT  /api/ai-config/chain        → reordena cascata (drag-and-drop)
- PUT  /api/ai-config/key/{prov}   → atualiza UMA chave (trocar chave)
- POST /api/ai-config/test/{prov}  → pinga o provider com mensagem curta

Cascata: 1º da lista = principal. Demais = fallback automático se o
principal cair. Cada agente de atendimento (Isabella, Jerusa) usa a chain.
"""
from __future__ import annotations

import time as _t
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, get_current_user, require_role, save_settings, get_settings
from database import db
from services.ai_keys import invalidate_cache, resolve_keys

router = APIRouter(prefix="/api/ai-config", tags=["ai-config"])

ALLOWED_PROVIDERS = ["gemini", "anthropic", "openai"]
DEFAULT_CHAIN = ["gemini", "anthropic", "openai"]


PROVIDER_META = {
    "gemini": {
        "label": "Google Gemini",
        "model": "gemini-2.5-flash",
        "icon": "sparkles",
        "color": "#4285f4",
        "prefix": "AIza",
        "key_help": "AIzaSy... — obter em aistudio.google.com/apikey (2M tokens/dia free)",
        "strengths": ["Vision (imagens/PDFs)", "Rápido", "Free tier alto"],
    },
    "anthropic": {
        "label": "Anthropic Claude",
        "model": "claude-sonnet-4-5",
        "icon": "brain",
        "color": "#cc785c",
        "prefix": "sk-ant-",
        "key_help": "sk-ant-api03-... — obter em console.anthropic.com/settings/keys",
        "strengths": ["Conversação natural", "Vendas/persuasão", "Alta qualidade"],
    },
    "openai": {
        "label": "OpenAI GPT",
        "model": "gpt-5-mini",
        "icon": "cpu",
        "color": "#10a37f",
        "prefix": "sk-",
        "key_help": "sk-proj-... — obter em platform.openai.com/api-keys",
        "strengths": ["Whisper (áudio)", "TTS (voz)", "Tool-use"],
    },
}


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------
def _mask_key(key: Optional[str]) -> str:
    if not key:
        return ""
    if key.startswith("sk-ant-"):
        return f"sk-ant-...{key[-4:]}"
    if key.startswith("AIza"):
        return f"AIza...{key[-4:]}"
    if key.startswith("sk-"):
        return f"sk-...{key[-4:]}"
    return f"***{key[-4:]}"


async def _get_chain(company_id: str) -> List[str]:
    cfg = await db.motor_ia_config.find_one(
        {"company_id": company_id}, {"_id": 0, "atendimento_provider_chain": 1},
    )
    chain = (cfg or {}).get("atendimento_provider_chain") or []
    # Sanitiza: remove duplicatas e providers desconhecidos
    seen = set()
    out: List[str] = []
    for p in chain:
        if p in ALLOWED_PROVIDERS and p not in seen:
            out.append(p)
            seen.add(p)
    if not out:
        return DEFAULT_CHAIN
    # Completa providers faltando no final (pra não excluir um por engano)
    for p in DEFAULT_CHAIN:
        if p not in seen:
            out.append(p)
    return out


# -------------------------------------------------------------------------
# Schemas
# -------------------------------------------------------------------------
class ChainUpdate(BaseModel):
    chain: List[str] = Field(..., min_length=1, max_length=3)


class KeyUpdate(BaseModel):
    api_key: str = Field(..., min_length=10, max_length=500)


# -------------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------------
@router.get("")
async def get_ai_config(user: dict = Depends(get_current_user)):
    """Retorna status de cada provider + ordem atual da cascata."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    s = await get_settings(cid)
    chain = await _get_chain(cid)
    keys_map = {
        "gemini": s.gemini_api_key,
        "anthropic": s.anthropic_api_key,
        "openai": s.openai_api_key,
    }
    providers = []
    for prov in ALLOWED_PROVIDERS:
        meta = PROVIDER_META[prov]
        key = keys_map.get(prov) or ""
        providers.append({
            "id": prov,
            "label": meta["label"],
            "model": meta["model"],
            "icon": meta["icon"],
            "color": meta["color"],
            "prefix": meta["prefix"],
            "key_help": meta["key_help"],
            "strengths": meta["strengths"],
            "configured": bool(key),
            "key_masked": _mask_key(key),
            "is_primary": (chain[0] == prov) if chain else False,
            "position": chain.index(prov) if prov in chain else -1,
        })
    # Ordena na ordem da cascata
    chain_pos = {p: i for i, p in enumerate(chain)}
    providers.sort(key=lambda p: chain_pos.get(p["id"], 999))
    return {
        "chain": chain,
        "providers": providers,
        "primary_provider": chain[0] if chain else None,
        "fallback_providers": chain[1:] if len(chain) > 1 else [],
    }


@router.put("/chain")
async def update_chain(payload: ChainUpdate, user: dict = Depends(require_role("auditor"))):
    """Atualiza a ordem da cascata (drag-and-drop)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    chain = []
    seen = set()
    for p in payload.chain:
        if p not in ALLOWED_PROVIDERS:
            raise HTTPException(400, f"Provider inválido: {p}")
        if p in seen:
            continue
        chain.append(p)
        seen.add(p)
    if not chain:
        raise HTTPException(400, "Cascata vazia")
    await db.motor_ia_config.update_one(
        {"company_id": cid},
        {"$set": {
            "atendimento_provider_chain": chain,
            "atendimento_provider": chain[0],  # compat com código antigo
        }},
        upsert=True,
    )
    # Invalida cache de ai_keys (settings_by_company → resolve_keys)
    invalidate_cache(cid)
    return {"ok": True, "chain": chain, "primary": chain[0]}


@router.put("/key/{provider}")
async def update_key(provider: str, payload: KeyUpdate,
                       user: dict = Depends(require_role("auditor"))):
    """Atualiza UMA chave de provider."""
    if provider not in ALLOWED_PROVIDERS:
        raise HTTPException(400, f"Provider inválido: {provider}")
    cid = user.get("company_id") or DEMO_COMPANY_ID
    key_field = f"{provider}_api_key"
    new_key = payload.api_key.strip()
    if not new_key:
        raise HTTPException(400, "Chave vazia")
    # Valida prefixo
    meta = PROVIDER_META[provider]
    if not new_key.startswith(meta["prefix"]):
        raise HTTPException(400,
                              f"Chave do {meta['label']} deve começar com '{meta['prefix']}'.")
    await save_settings({key_field: new_key}, cid)
    invalidate_cache(cid)
    return {"ok": True, "provider": provider, "key_masked": _mask_key(new_key)}


@router.delete("/key/{provider}")
async def remove_key(provider: str,
                       user: dict = Depends(require_role("auditor"))):
    """Remove uma chave de provider."""
    if provider not in ALLOWED_PROVIDERS:
        raise HTTPException(400, f"Provider inválido: {provider}")
    cid = user.get("company_id") or DEMO_COMPANY_ID
    key_field = f"{provider}_api_key"
    # save_settings ignora None — usar update direto
    await db.settings_by_company.update_one(
        {"company_id": cid},
        {"$unset": {key_field: ""}},
    )
    # Limpa cache do settings (in-memory)
    try:
        from core import _settings_cache
        _settings_cache.pop(cid, None)
    except Exception:
        pass
    invalidate_cache(cid)
    return {"ok": True, "provider": provider}


@router.post("/test/{provider}")
async def test_provider(provider: str, user: dict = Depends(get_current_user)):
    """Faz uma chamada real ao provider e mede latência."""
    if provider not in ALLOWED_PROVIDERS:
        raise HTTPException(400, f"Provider inválido: {provider}")
    cid = user.get("company_id") or DEMO_COMPANY_ID
    keys = await resolve_keys(cid)
    api_key = keys.get(provider)
    if not api_key:
        return {"ok": False, "provider": provider,
                "error": "Sem chave configurada para este provider."}
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        meta = PROVIDER_META[provider]
        session_id = f"test-{provider}-{int(_t.time())}"
        chat = LlmChat(
            api_key=api_key, session_id=session_id,
            system_message="Você é um assistente. Responda apenas 'OK'.",
        ).with_model(provider, meta["model"])
        t0 = _t.time()
        out = await chat.send_message(UserMessage(
            text="Diga apenas a palavra OK em maiúsculas e nada mais.",
        ))
        latency_ms = int((_t.time() - t0) * 1000)
        return {
            "ok": True,
            "provider": provider,
            "model": meta["model"],
            "latency_ms": latency_ms,
            "response_preview": str(out).strip()[:100],
        }
    except Exception as e:
        msg = str(e)
        return {
            "ok": False,
            "provider": provider,
            "error": msg[:300],
        }
