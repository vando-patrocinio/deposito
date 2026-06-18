"""Factual Claim Binder — vincula claims auditados aos outbounds reais.

V15.2 revelou Trust=0% porque o link `claim_id → outbound_msg_id` nunca
foi implementado nos caminhos reais. Este módulo resolve isso:

  1. `bind_active_claims_to_outbound()` — após cada outbound bem-sucedido
     da Isabella, busca claims ativos (audit_passed, dentro do TTL,
     consumed_by=null) do subscriber e os marca como consumed pela
     mensagem outbound. Heurística pragmática: se houve claim ativo
     no momento do envio, presume-se que foi usado no contexto da
     resposta (o V15 oracle block já o injetou no prompt).

  2. `list_active_claims_for_subscriber()` — helper para inspetor de
     evidências (debug + futura UI).

Filosofia: "se a evidência foi entregue ao LLM no prompt, ela conta
como base factual". Isso é heurístico mas reflete a realidade do
pipeline V15.
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db

logger = logging.getLogger("ponto.factual_claim_binder")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def list_active_claims_for_subscriber(
    *,
    company_id: str,
    subscriber_id: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Claims ativos (audit_passed, dentro do TTL, ainda não consumidos)."""
    cursor = db.isabella_factual_claims.find(
        {"company_id": company_id, "entity_id": subscriber_id,
         "audit_passed": True, "consumed_by": None},
        {"_id": 0, "id": 1, "domain": 1, "audited_at": 1,
         "ttl_minutes": 1, "evidence": 1},
    ).sort("audited_at", -1).limit(limit)
    rows = await cursor.to_list(limit)
    valid: List[Dict[str, Any]] = []
    now = _now()
    for r in rows:
        try:
            aud = r.get("audited_at")
            dt = (datetime.fromisoformat(aud.replace("Z", "+00:00"))
                  if isinstance(aud, str) else aud)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ttl = int(r.get("ttl_minutes") or 30)
            if dt + timedelta(minutes=ttl) >= now:
                valid.append(r)
        except Exception:
            continue
    return valid


async def bind_active_claims_to_outbound(
    *,
    company_id: str,
    subscriber_id: Optional[str],
    outbound_msg_id: str,
) -> Dict[str, Any]:
    """Marca como consumed todos os claims ativos do subscriber.

    Retorna dict com `bound_count` e `claim_ids`.
    Idempotente: claims já consumidos são ignorados.
    """
    if not subscriber_id or not outbound_msg_id:
        return {"bound_count": 0, "claim_ids": []}
    try:
        claims = await list_active_claims_for_subscriber(
            company_id=company_id, subscriber_id=subscriber_id, limit=10,
        )
        if not claims:
            return {"bound_count": 0, "claim_ids": []}
        now_iso = _now().isoformat()
        ids = [c["id"] for c in claims]
        res = await db.isabella_factual_claims.update_many(
            {"id": {"$in": ids}, "consumed_by": None},
            {"$set": {"consumed_by": outbound_msg_id,
                       "consumed_at": now_iso}},
        )
        logger.info(
            "[claim_binder] bound %d claims to msg=%s subscriber=%s",
            res.modified_count, outbound_msg_id, subscriber_id,
        )
        return {"bound_count": res.modified_count, "claim_ids": ids}
    except Exception as e:
        logger.warning("[claim_binder] bind falhou: %s", e)
        return {"bound_count": 0, "claim_ids": []}
