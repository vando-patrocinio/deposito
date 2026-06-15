"""DEPRECATED · services.presidente_ia_briefing
================================================

Renomeado para `services.ceo_briefing` em 15/06/2026 (Etapa 3 — Ligo
Executive OS · Consolidation).

⚠️  Este módulo continuará disponível como stub por **30 dias** (até 15/07/2026)
e depois será removido. Atualize seus imports para:

    from services import ceo_briefing
    # ou
    from services.ceo_briefing import <símbolo>

Todas as chamadas a este módulo são contabilizadas em
`deprecated_call_log` para o ranking semanal de migração.
"""
from __future__ import annotations

from services._deprecated_logger import log_deprecated
from services import ceo_briefing as _target

_LEGACY_PATH = "services.presidente_ia_briefing"
_TARGET_PATH = "services.ceo_briefing"


def __getattr__(name: str):
    if name.startswith("_"):
        raise AttributeError(name)
    log_deprecated(_LEGACY_PATH, _TARGET_PATH, symbol=name)
    return getattr(_target, name)


def __dir__():
    log_deprecated(_LEGACY_PATH, _TARGET_PATH, symbol="__dir__")
    return dir(_target)
