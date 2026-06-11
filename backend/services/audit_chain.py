"""AUDIT CHAIN — cadeia criptográfica imutável de auditoria.

Cada registro contém:
  audit_id
  previous_hash    (SHA-256 do registro imediatamente anterior da mesma chain)
  current_hash     (SHA-256 do conteúdo + previous_hash)
  timestamp
  actor
  action
  payload_hash     (SHA-256 do payload)
  chain_key        (segrega chains por domínio: campaign|incident|opp|...)

A integridade da cadeia pode ser verificada por `verify_chain` — qualquer
adulteração quebra o hash subsequente.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "shield",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db

log = logging.getLogger("ponto.audit_chain")
GENESIS = "0" * 64


def _now():
    return datetime.now(timezone.utc).isoformat()


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _payload_hash(payload: Dict[str, Any]) -> str:
    return _sha256(json.dumps(payload, sort_keys=True, default=str))


async def ensure_indexes() -> None:
    try:
        await db.audit_chain.create_index(
            [("chain_key", 1), ("seq", -1)])
        await db.audit_chain.create_index(
            [("chain_key", 1), ("current_hash", 1)], unique=True)
        await db.audit_chain.create_index([("audit_id", 1)], unique=True)
    except Exception as e:
        log.warning("[audit_chain] indexes: %s", e)


async def _last_for(chain_key: str) -> Optional[Dict[str, Any]]:
    return await db.audit_chain.find_one(
        {"chain_key": chain_key}, {"_id": 0},
        sort=[("seq", -1)])


async def append(*, chain_key: str, actor: str, action: str,
                   payload: Dict[str, Any]) -> Dict[str, Any]:
    """Acrescenta um registro à cadeia."""
    last = await _last_for(chain_key)
    prev_hash = (last or {}).get("current_hash") or GENESIS
    seq = ((last or {}).get("seq") or 0) + 1
    ts = _now()
    p_hash = _payload_hash(payload or {})
    audit_id = f"audit-{uuid.uuid4().hex[:14]}"
    body = (f"{audit_id}|{chain_key}|{seq}|{ts}|{actor}|{action}|"
            f"{p_hash}|{prev_hash}")
    cur_hash = _sha256(body)
    doc = {
        "audit_id": audit_id,
        "chain_key": chain_key,
        "seq": seq,
        "ts": ts,
        "actor": actor,
        "action": action,
        "payload": payload or {},
        "payload_hash": p_hash,
        "previous_hash": prev_hash,
        "current_hash": cur_hash,
    }
    await db.audit_chain.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def verify_chain(chain_key: str) -> Dict[str, Any]:
    """Verifica integridade da cadeia inteira (re-hash + comparação).

    SEGURANÇA: recomputa payload_hash a partir do payload atual para
    detectar adulteração do conteúdo do payload, não apenas do hash.
    """
    cur = db.audit_chain.find(
        {"chain_key": chain_key}, {"_id": 0}).sort("seq", 1)
    prev_hash = GENESIS
    n = 0
    broken_at: Optional[int] = None
    async for r in cur:
        n += 1
        # 1) payload_hash bate com payload atual?
        recomputed_p_hash = _payload_hash(r.get("payload") or {})
        if recomputed_p_hash != r["payload_hash"]:
            return {"ok": False, "chain_key": chain_key,
                    "records_verified": n, "broken_at": r["seq"],
                    "reason": "payload_tampered",
                    "expected_payload_hash": recomputed_p_hash,
                    "stored_payload_hash": r["payload_hash"]}
        # 2) current_hash bate com body recomputado?
        body = (f"{r['audit_id']}|{r['chain_key']}|{r['seq']}|{r['ts']}|"
                f"{r['actor']}|{r['action']}|{r['payload_hash']}|"
                f"{prev_hash}")
        expected = _sha256(body)
        if expected != r["current_hash"] or prev_hash != r["previous_hash"]:
            broken_at = r["seq"]
            return {"ok": False, "chain_key": chain_key,
                    "records_verified": n, "broken_at": broken_at,
                    "reason": "chain_broken",
                    "expected": expected, "found": r["current_hash"]}
        prev_hash = r["current_hash"]
    return {"ok": True, "chain_key": chain_key,
            "records_verified": n}


async def chain_keys() -> List[str]:
    return await db.audit_chain.distinct("chain_key")
