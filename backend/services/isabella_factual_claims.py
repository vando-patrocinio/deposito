"""isabella_factual_claims — Padrão institucional CEO 17/02/2026.

Princípio fundamental:
    "Se não consegue provar, não pode afirmar."

Toda afirmação factual da Isabella DEVE passar pelo protocolo:
    1. CONFERIR    → identificar entidade
    2. ANALISAR    → consultar fontes
    3. CONFERIR    → validar freshness + consistência

Quem usa:
    * boleto_flow (financeiro)       — já integrado
    * smartolt_status (técnico)      — futuro
    * subscriber_status (cadastro)   — futuro
    * estoque_lookup (estoque)       — futuro
    * qualquer feature que faça afirmação factual ao cliente

Como usar:
    from services.isabella_factual_claims import claim, ClaimDomain

    claim_id = await claim(
        domain=ClaimDomain.FINANCIAL,
        entity_type="subscriber",
        entity_id=subscriber["id"],
        checks=[
            {"name": "identification", "ok": True, "ext": "..."},
            {"name": "primary_count", "ok": True, "paid": 3, "open": 0},
            {"name": "sync_freshness", "ok": True, "stale_h": 6.8},
        ],
        warnings=[],
        evidence={...},  # dados que serão exibidos ao cliente
    )

Schema persistido em `isabella_factual_claims`:
    {
      id:          "claim-<dom>-<10hex>"   evidence_id
      domain:      financial|technical|cadastro|estoque
      entity_type: subscriber|onu|equipment|os
      entity_id:   ...
      company_id:  ...
      audited_at:  ISO
      checks:      [{name, ok, ...}]
      warnings:    [str]
      evidence:    {...}             # snapshot dos dados afirmados
      audit_passed: bool             # true sse todos checks ok + 0 warnings
      ttl_minutes:  N                # válido por N min (default 30)
      consumed_by:  null|"mid-..."   # link pra wa message que usou
    }
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from database import db

logger = logging.getLogger("isabella.factual_claims")


class ClaimDomain(str, Enum):
    FINANCIAL = "financial"
    TECHNICAL = "technical"
    CADASTRO = "cadastro"
    ESTOQUE = "estoque"
    OTHER = "other"


_DEFAULT_TTL_MIN = 30


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def evaluate_audit(checks: List[Dict[str, Any]],
                     warnings: List[str]) -> bool:
    """Regra dura: audit passa SSE todos os checks ok + zero warnings."""
    if warnings:
        return False
    return all(bool(c.get("ok")) for c in (checks or []))


async def claim(*, domain: ClaimDomain, entity_type: str,
                  entity_id: Optional[str],
                  company_id: Optional[str] = None,
                  checks: List[Dict[str, Any]],
                  warnings: Optional[List[str]] = None,
                  evidence: Optional[Dict[str, Any]] = None,
                  ttl_minutes: int = _DEFAULT_TTL_MIN
                  ) -> Dict[str, Any]:
    """Registra 1 claim factual auditável. Retorna o doc com `id` e
    `audit_passed`. Se `audit_passed=False`, o caller DEVE responder ao
    cliente apenas "vou verificar" — não pode afirmar."""
    cid = company_id or "co-demo"
    warnings = warnings or []
    audit_passed = evaluate_audit(checks, warnings)
    claim_id = f"claim-{domain.value}-{uuid.uuid4().hex[:10]}"
    doc: Dict[str, Any] = {
        "id": claim_id,
        "domain": domain.value,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "company_id": cid,
        "audited_at": _iso(datetime.now(timezone.utc)),
        "checks": checks,
        "warnings": warnings,
        "evidence": evidence or {},
        "audit_passed": audit_passed,
        "ttl_minutes": ttl_minutes,
        "consumed_by": None,
    }
    try:
        await db.isabella_factual_claims.insert_one(dict(doc))
    except Exception as e:  # noqa: BLE001
        logger.exception("[claim] persist exc: %s", e)
    logger.info("[claim] %s domain=%s entity=%s/%s passed=%s warns=%s",
                claim_id, domain.value, entity_type, entity_id,
                audit_passed, warnings)
    return doc


async def mark_consumed(claim_id: str, message_id: str) -> None:
    """Link 1 claim a 1 mensagem enviada (rastreabilidade end-to-end)."""
    try:
        await db.isabella_factual_claims.update_one(
            {"id": claim_id},
            {"$set": {"consumed_by": message_id,
                       "consumed_at": _iso(datetime.now(timezone.utc))}})
    except Exception:
        pass


# ── Helpers de listagem (admin) ───────────────────────────────


async def recent(*, company_id: str = "co-demo",
                   domain: Optional[str] = None,
                   limit: int = 50,
                   passed: Optional[bool] = None
                   ) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"company_id": company_id}
    if domain:
        q["domain"] = domain
    if passed is not None:
        q["audit_passed"] = passed
    return await (db.isabella_factual_claims
                  .find(q, {"_id": 0})
                  .sort("audited_at", -1).limit(limit).to_list(limit))


async def stats_24h(company_id: str = "co-demo") -> Dict[str, Any]:
    from datetime import timedelta
    since = _iso(datetime.now(timezone.utc) - timedelta(hours=24))
    base = {"company_id": company_id, "audited_at": {"$gte": since}}
    total = await db.isabella_factual_claims.count_documents(base)
    passed = await db.isabella_factual_claims.count_documents(
        {**base, "audit_passed": True})
    failed = await db.isabella_factual_claims.count_documents(
        {**base, "audit_passed": False})
    by_dom: Dict[str, int] = {}
    pipe = [
        {"$match": base},
        {"$group": {"_id": "$domain", "n": {"$sum": 1}}},
    ]
    async for r in db.isabella_factual_claims.aggregate(pipe):
        by_dom[r["_id"] or "?"] = r["n"]
    top_warns: List[Dict[str, Any]] = []
    pipe2 = [
        {"$match": base},
        {"$unwind": "$warnings"},
        {"$group": {"_id": "$warnings", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 10},
    ]
    async for r in db.isabella_factual_claims.aggregate(pipe2):
        top_warns.append({"warning": r["_id"], "count": r["n"]})
    return {
        "total_24h": total,
        "passed_24h": passed,
        "failed_24h": failed,
        "trust_rate_pct": round((passed / total * 100.0) if total else 0.0, 2),
        "by_domain": by_dom,
        "top_warnings": top_warns,
    }
