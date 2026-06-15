"""DATA PROVENANCE — source flag + stale warning.

Spec CEO 15/06/2026 (cto_inbox cto-5d5c9c8aeef94c, itens 9+10 do audit):
- Todo payload crítico deve carregar source=prod|test|mock.
- Snapshot/coleção com `_collected_at` > 24h deve marcar stale_warning=True
  e Presidente IA NÃO deve recomendar decisão executiva nesse caso.

ENV:
- DATA_SOURCE_MODE = prod|test|mock (default prod).
- DATA_STALE_HOURS = float horas (default 24).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

ALLOWED_SOURCES = {"prod", "test", "mock"}


def current_source() -> str:
    """Lê DATA_SOURCE_MODE do .env. Default prod. Fail-safe valida enum."""
    val = (os.environ.get("DATA_SOURCE_MODE") or "prod").lower().strip()
    if val not in ALLOWED_SOURCES:
        # Fallback explícito com warning seria duplicação aqui — apenas força prod.
        return "prod"
    return val


def stale_threshold_hours() -> float:
    try:
        return float(os.environ.get("DATA_STALE_HOURS") or 24)
    except (TypeError, ValueError):
        return 24.0


def parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Aceita "2026-06-15T05:55:11.768469+00:00" ou variações com Z
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def freshness_block(collected_at_iso: Optional[str]) -> dict:
    """Calcula bloco de frescor do dado.

    Retorna:
      {
        source: "prod|test|mock",
        collected_at: ISO|None,
        stale_hours: float|None,
        stale_threshold_hours: float,
        stale_warning: bool,
        decision_safe: bool,   # False se stale (Presidente IA não deve decidir),
        message: str,
      }
    """
    src = current_source()
    threshold = stale_threshold_hours()
    dt = parse_iso(collected_at_iso)
    now = datetime.now(timezone.utc)

    stale_hours: Optional[float]
    stale: bool
    if dt is None:
        stale_hours = None
        stale = True  # sem timestamp -> conservador: trata como stale
        msg = ("Dado sem timestamp _collected_at. Tratando como stale por "
               "segurança. Não recomendar decisão executiva.")
    else:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta_h = (now - dt).total_seconds() / 3600.0
        stale_hours = round(delta_h, 2)
        stale = delta_h > threshold
        if stale:
            msg = (f"ATENÇÃO: snapshot tem {stale_hours}h (limite "
                   f"{threshold}h). Dado congelado — Presidente IA NÃO deve "
                   f"recomendar decisão executiva sem atualizar.")
        else:
            msg = "Dado fresco."

    return {
        "source": src,
        "collected_at": collected_at_iso,
        "stale_hours": stale_hours,
        "stale_threshold_hours": threshold,
        "stale_warning": stale,
        "decision_safe": (src == "prod") and (not stale),
        "message": msg,
    }


def tag_payload(payload: dict, collected_at_iso: Optional[str] = None) -> dict:
    """Anexa `_data_provenance` em qualquer dict de resposta sem clobber."""
    payload = dict(payload)  # cópia rasa pra não mutar input
    payload["_data_provenance"] = freshness_block(collected_at_iso)
    payload.setdefault("source", current_source())
    return payload
