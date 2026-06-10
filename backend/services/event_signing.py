"""EVENT SIGNING — assinatura HMAC-SHA256 + verificação + anti-replay.

Wrapper sobre o event_bus que adiciona:
  • signature = HMAC(secret, canonical_payload)
  • nonce + ts para prevenir replay
  • verify_signature() valida assinatura + janela temporal
  • Persistência em `signed_events_processed` com TTL para anti-replay
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from database import db

log = logging.getLogger("ponto.event_signing")

REPLAY_WINDOW_SECONDS = 300  # 5 min


def _secret() -> bytes:
    """Chave de assinatura. Preferencialmente do vault, fallback ENV."""
    key = (os.environ.get("EVENT_SIGNING_KEY")
           or os.environ.get("SECRETS_MASTER_KEY")
           or "smartprov-event-signing-default-key-rotate-asap")
    return key.encode() if isinstance(key, str) else key


def _canonical(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       default=str)


def sign(payload: Dict[str, Any], *,
          event_type: str,
          company_id: Optional[str] = None) -> Dict[str, Any]:
    """Envelopa o payload com nonce/ts/signature."""
    nonce = uuid.uuid4().hex[:16]
    ts = int(time.time())
    canonical = (f"{event_type}|{company_id or '*'}|{ts}|{nonce}|"
                  f"{_canonical(payload)}")
    sig = hmac.new(_secret(), canonical.encode(), hashlib.sha256).hexdigest()
    return {
        "event_type": event_type, "company_id": company_id,
        "ts": ts, "nonce": nonce, "signature": sig,
        "payload": payload,
    }


def verify_signature(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Verifica HMAC. Retorna {ok, reason, signature_valid, ts_valid}."""
    try:
        canonical = (f"{envelope['event_type']}|"
                      f"{envelope.get('company_id') or '*'}|"
                      f"{envelope['ts']}|{envelope['nonce']}|"
                      f"{_canonical(envelope['payload'])}")
        expected = hmac.new(_secret(), canonical.encode(),
                              hashlib.sha256).hexdigest()
        sig_ok = hmac.compare_digest(expected, envelope.get("signature", ""))
        age = int(time.time()) - int(envelope.get("ts") or 0)
        ts_ok = 0 <= age <= REPLAY_WINDOW_SECONDS
        return {"ok": sig_ok and ts_ok,
                "signature_valid": sig_ok,
                "ts_valid": ts_ok, "age_seconds": age,
                "reason": None if (sig_ok and ts_ok)
                          else ("bad_signature" if not sig_ok
                                else "expired_or_future")}
    except KeyError as e:
        return {"ok": False, "reason": f"missing_field:{e}"}


async def consume(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Valida + grava nonce em `signed_events_processed` (anti-replay)."""
    v = verify_signature(envelope)
    if not v["ok"]:
        return {"accepted": False, **v}
    nonce = envelope["nonce"]
    try:
        await db.signed_events_processed.insert_one({
            "nonce": nonce, "event_type": envelope["event_type"],
            "company_id": envelope.get("company_id"),
            "ts": envelope["ts"],
            "consumed_at": datetime.now(timezone.utc).isoformat()})
    except Exception:
        # duplicate key → replay attempt
        return {"accepted": False, "reason": "replay_detected"}
    return {"accepted": True, **v}


async def ensure_indexes() -> None:
    try:
        await db.signed_events_processed.create_index(
            "nonce", unique=True, name="anti_replay_nonce")
        # TTL: limpa nonces após 1 hora
        await db.signed_events_processed.create_index(
            "consumed_at", expireAfterSeconds=3600,
            name="anti_replay_ttl")
    except Exception as e:
        log.warning("[event_signing] indexes: %s", e)
