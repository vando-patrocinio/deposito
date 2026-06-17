"""Retry de mensagens IA que falharam por sidecar offline.

Quando o sidecar Baileys cai (max_retries esgotado), mensagens geradas
pela IA ficam marcadas `delivery_status=failed_send|failed_timeout` no
banco — o cliente nunca recebeu, mas a IA não re-tenta automaticamente.

Esta rota varre falhas das últimas N horas e re-envia via wa_dispatcher
(que agora encontra o sidecar de volta saudável).

Uso:
    POST /api/whatsapp-baileys/retry-failed-send
    {
      "hours": 24,
      "phone": "551147099675"   # opcional, filtra um cliente
    }

Resposta:
    { ok, scanned, retried, succeeded, failed, items: [...] }
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core import require_role
from database import db
from services import wa_dispatcher

logger = logging.getLogger("wa.retry_failed")
router = APIRouter(prefix="/api/whatsapp-baileys", tags=["wa-baileys-retry"])


class RetryIn(BaseModel):
    hours: int = 24
    phone: Optional[str] = None
    dry_run: bool = False
    # CTO 17/02/2026 — quando True, ignora o dispatcher e manda direto pro
    # sidecar Baileys local (channel-1). Útil quando Evolution está down e
    # o dispatcher continua tentando por ela.
    force_sidecar_direct: bool = True


async def _send_via_sidecar_direct(phone: str, text: str) -> Dict[str, Any]:
    """Bypass dispatcher — envia direto pro sidecar Baileys local channel-1."""
    base = os.environ.get("WA_SIDECAR_URL_CH1") or os.environ.get("WA_SIDECAR_URL")
    if not base:
        return {"ok": False, "reason": "no_sidecar_url"}
    token = os.environ.get("WA_SIDECAR_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=30.0) as cli:
            r = await cli.post(f"{base}/send",
                                json={"phone": phone, "text": text},
                                headers=headers)
            ok = r.status_code == 200
            try:
                payload = r.json()
            except Exception:
                payload = {"raw": r.text[:200]}
            return {"ok": ok and bool(payload.get("ok")),
                    "status": r.status_code,
                    "response": payload,
                    "reason": (payload.get("error") if not ok else None)}
    except Exception as e:
        return {"ok": False, "reason": f"sidecar_direct_exception:{e}"}


@router.post("/retry-failed-send")
async def retry_failed_send(
    payload: RetryIn,
    user: dict = Depends(require_role("gestor", "administrador", "auditor")),
) -> Dict[str, Any]:
    """Re-tenta mensagens IA com delivery_status=failed_send/failed_timeout."""
    cid = user.get("company_id") or "co-demo"
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=max(1, min(168, payload.hours)))).isoformat()
    query: Dict[str, Any] = {
        "direction": "outbound",
        "auto_reply": True,
        "delivery_status": {"$in": ["failed_send", "failed_timeout"]},
        "created_at": {"$gte": cutoff},
        "company_id": cid,
    }
    if payload.phone:
        query["phone"] = "".join(c for c in payload.phone if c.isdigit())

    scanned = 0
    retried = 0
    succeeded = 0
    failed = 0
    items = []

    cursor = db.aihub_wa_messages.find(query,
        {"_id": 0, "id": 1, "message_id": 1, "external_id": 1, "phone": 1,
         "text": 1, "delivery_status": 1, "created_at": 1}).sort("created_at", 1)
    docs = []
    async for m in cursor:
        docs.append(m)
        scanned += 1

    for m in docs:
        mid = (m.get("id") or m.get("message_id") or m.get("external_id"))
        phone = m.get("phone")
        text = m.get("text") or ""
        if not phone or not text:
            failed += 1
            items.append({"id": mid, "phone": phone, "status": "skip_empty"})
            continue
        retried += 1
        if payload.dry_run:
            items.append({"id": mid, "phone": phone, "status": "dry_run"})
            continue
        try:
            if payload.force_sidecar_direct:
                r = await _send_via_sidecar_direct(phone=phone, text=text)
            else:
                r = await wa_dispatcher.send_text(
                    company_id=cid, to=phone, text=text)
            ok = bool(r.get("ok"))
            if ok:
                succeeded += 1
                # Marca como reenviado no DB — usa phone+created_at como chave
                # composta quando nenhum identificador único existir.
                filt: Dict[str, Any] = {
                    "phone": phone, "created_at": m.get("created_at")}
                if m.get("external_id"):
                    filt = {"external_id": m["external_id"]}
                elif mid:
                    filt = {"id": mid}
                await db.aihub_wa_messages.update_one(filt, {"$set": {
                    "delivery_status": "sent",
                    "retry_applied_at": datetime.now(timezone.utc).isoformat(),
                    "retry_new_message_id": r.get("id"),
                    "retry_via": ("sidecar_direct"
                                   if payload.force_sidecar_direct
                                   else "dispatcher"),
                    "retry_reason": "sidecar_was_offline_at_first_attempt",
                }})
                items.append({"id": mid, "phone": phone,
                               "status": "sent",
                               "via": ("sidecar_direct"
                                        if payload.force_sidecar_direct
                                        else "dispatcher")})
            else:
                failed += 1
                items.append({"id": mid, "phone": phone,
                               "status": "still_failed",
                               "reason": r.get("reason") or r.get("error")})
        except Exception as e:  # noqa: BLE001
            failed += 1
            items.append({"id": mid, "phone": phone,
                           "status": "exception", "error": str(e)[:200]})
            logger.exception("[retry] mid=%s exc", mid)

    logger.info(
        "[retry] cid=%s scanned=%d retried=%d succeeded=%d failed=%d phone=%s",
        cid, scanned, retried, succeeded, failed, payload.phone)

    return {
        "ok": True,
        "scanned": scanned,
        "retried": retried,
        "succeeded": succeeded,
        "failed": failed,
        "dry_run": payload.dry_run,
        "force_sidecar_direct": payload.force_sidecar_direct,
        "items": items,
    }
