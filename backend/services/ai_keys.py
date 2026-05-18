"""ai_keys.py — Helper central para resolver chaves de IA por empresa.

Estratégia:
  1. Tenta `settings_by_company.{anthropic|openai|gemini}_api_key` (BD).
  2. Fallback para env global `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY`.
  3. Último fallback: `EMERGENT_LLM_KEY` (transição) — pra não derrubar o app
     durante a migração. Quando todas as empresas tiverem suas keys, esse
     fallback pode ser removido.

Uso:
    from services.ai_keys import resolve_keys
    keys = await resolve_keys("co-xxx")
    chat = LlmChat(api_key=keys["anthropic"], ...).with_model("anthropic","claude-sonnet-4-5")
"""
from __future__ import annotations

import os
from typing import Dict, Optional

from core import EMERGENT_LLM_KEY
from database import db


# Cache simples (TTL via reload manual) — settings raramente muda
_cache: Dict[str, Dict[str, Optional[str]]] = {}


async def resolve_keys(company_id: str) -> Dict[str, Optional[str]]:
    """Retorna {anthropic, openai, gemini} pra empresa.

    Cada valor pode ser None (nenhuma key disponível em nenhum nível).
    """
    if not company_id:
        company_id = "_global"
    if company_id in _cache:
        return _cache[company_id]
    doc = await db.settings_by_company.find_one(
        {"company_id": company_id}, {"_id": 0,
                                       "anthropic_api_key": 1,
                                       "openai_api_key": 1,
                                       "gemini_api_key": 1},
    )
    anthropic = (doc or {}).get("anthropic_api_key") or \
                  os.environ.get("ANTHROPIC_API_KEY") or \
                  EMERGENT_LLM_KEY
    openai = (doc or {}).get("openai_api_key") or \
                os.environ.get("OPENAI_API_KEY") or \
                EMERGENT_LLM_KEY
    gemini = (doc or {}).get("gemini_api_key") or \
                os.environ.get("GEMINI_API_KEY") or \
                EMERGENT_LLM_KEY
    out = {"anthropic": anthropic, "openai": openai, "gemini": gemini}
    _cache[company_id] = out
    return out


def invalidate_cache(company_id: Optional[str] = None) -> None:
    """Limpa cache. Chame após PUT em /ai/keys."""
    if company_id is None:
        _cache.clear()
    else:
        _cache.pop(company_id, None)
        _cache.pop("_global", None)


async def is_using_emergent_key(company_id: str) -> Dict[str, bool]:
    """Diagnóstico: retorna quais provedores ainda usam a Emergent Universal Key
    (vs chave própria). Útil pra mostrar no painel admin "✓ Chave própria" ou
    "⚠ Usando Emergent (precisa configurar)".
    """
    keys = await resolve_keys(company_id)
    return {
        prov: (k == EMERGENT_LLM_KEY)
        for prov, k in keys.items()
    }
