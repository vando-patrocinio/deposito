"""Comunicação HTTP com o Baileys sidecar (Node.js, porta 3002 por padrão).

Centraliza:
  - URL base e token de autenticação
  - 3 variantes de chamadas (GET, POST com HTTP raise, POST silencioso)

Extraído de routes/whatsapp_baileys.py em iter106 (refactor).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException

logger = logging.getLogger("ponto.wa_baileys")

SIDECAR_BASE = os.environ.get("WA_SIDECAR_URL", "http://127.0.0.1:3002").rstrip("/")
SIDECAR_TOKEN = os.environ.get("WA_SIDECAR_TOKEN", "")
WA_INBOUND_TOKEN = os.environ.get("WA_INBOUND_TOKEN", "")


def _sidecar_headers() -> dict:
    """Headers padrão para chamadas ao sidecar — adiciona Bearer quando configurado."""
    return {"Authorization": f"Bearer {SIDECAR_TOKEN}"} if SIDECAR_TOKEN else {}


async def _sidecar_get(path: str) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(headers=_sidecar_headers(), timeout=8.0) as cli:
            r = await cli.get(f"{SIDECAR_BASE}{path}")
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        logger.warning("[wa-baileys] sidecar GET %s falhou: %s", path, e)
        raise HTTPException(503,
                            f"WhatsApp sidecar indisponível: {e}") from e


async def _sidecar_post(path: str, payload: Optional[dict] = None) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(headers=_sidecar_headers(), timeout=15.0) as cli:
            r = await cli.post(f"{SIDECAR_BASE}{path}", json=payload or {})
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text}
            if r.status_code >= 400:
                detail = body.get("error") or body.get("raw") or f"HTTP {r.status_code}"
                raise HTTPException(r.status_code, detail)
            return body
    except httpx.HTTPError as e:
        logger.warning("[wa-baileys] sidecar POST %s falhou: %s", path, e)
        raise HTTPException(503,
                            f"WhatsApp sidecar indisponível: {e}") from e


async def _sidecar_post_silent(path: str, payload: dict, timeout: float = 50.0
                                ) -> Dict[str, Any]:
    """Como _sidecar_post mas não levanta HTTPException — devolve dict com
    `ok=False` em caso de erro. Útil pra envios em background (boleto PDF)
    onde queremos persistir falha mas seguir a vida.
    """
    return await _sidecar_post_silent_at(SIDECAR_BASE, path, payload, timeout)


async def _sidecar_post_silent_at(base_url: str, path: str, payload: dict,
                                    timeout: float = 50.0) -> Dict[str, Any]:
    """Variante multi-canal: envia para qualquer sidecar (porta diferente).

    Usado pelos serviços outbound (mass_messaging, sales_outreach,
    disparo_boleto) que resolvem o canal via `get_default_outbound_channel`
    ou override por campanha.
    """
    try:
        async with httpx.AsyncClient(headers=_sidecar_headers(),
                                        timeout=timeout) as cli:
            r = await cli.post(f"{base_url.rstrip('/')}{path}", json=payload)
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text}
            if r.status_code >= 400:
                return {"ok": False,
                        "error": body.get("error") or f"HTTP {r.status_code}"}
            return body
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _sidecar_post_at(base_url: str, path: str,
                            payload: Optional[dict] = None) -> Dict[str, Any]:
    """Variante multi-canal de _sidecar_post (com HTTPException)."""
    try:
        async with httpx.AsyncClient(headers=_sidecar_headers(),
                                        timeout=15.0) as cli:
            r = await cli.post(f"{base_url.rstrip('/')}{path}",
                                json=payload or {})
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text}
            if r.status_code >= 400:
                detail = body.get("error") or body.get("raw") or f"HTTP {r.status_code}"
                raise HTTPException(r.status_code, detail)
            return body
    except httpx.HTTPError as e:
        logger.warning("[wa-baileys] sidecar POST %s @ %s falhou: %s",
                        path, base_url, e)
        raise HTTPException(503,
                            f"WhatsApp sidecar indisponível: {e}") from e

