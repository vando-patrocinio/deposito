"""
wa_dispatcher.py — Ponto único de envio de WhatsApp do Presidente IA.
Centraliza para que mocks/feature-flags fiquem aqui (e não espalhados).

Em produção:
    - Procura sessão Baileys ativa em `wa_baileys_sessions` (company_id).
    - Chama o sidecar HTTP do Baileys (FASTAPI_BAILEYS_URL) com payload
      JSON {to, text}.
    - Em ausência da sessão, retorna {ok:false, reason:"no_session"}.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict

import httpx

from database import db

log = logging.getLogger("wa_dispatcher")


def _baileys_url() -> str:
    return os.environ.get("BAILEYS_SIDECAR_URL", "")


async def send_text(*, company_id: str, to: str,
                       text: str) -> Dict[str, Any]:
    """Envia texto via Baileys. Retorna {ok, id|reason}."""
    sess = await db.wa_baileys_sessions.find_one(
        {"company_id": company_id, "status": "open"})
    if not sess:
        return {"ok": False, "reason": "no_session"}
    url = _baileys_url()
    if not url:
        return {"ok": False, "reason": "BAILEYS_SIDECAR_URL_missing"}
    msg_id = f"wa-{uuid.uuid4().hex[:12]}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(
                f"{url}/send",
                json={"company_id": company_id, "to": to,
                       "text": text, "id": msg_id})
            r.raise_for_status()
            return {"ok": True, "id": msg_id, "response": r.json()}
    except Exception as e:  # noqa: BLE001
        log.warning("[wa_dispatcher] falha: %s", e)
        return {"ok": False, "reason": str(e)}
