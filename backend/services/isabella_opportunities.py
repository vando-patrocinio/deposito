"""ISABELLA OPPORTUNITIES — pipeline central dos Commanders (Churn, Dunning,
Revenue, Expansion, Twin).

Filosofia (ordem CTO 02/2026):
  • Isabella **DETECTA** padrões em dados REAIS (zero mock).
  • Isabella **PONTUA** com score + probabilidade + impacto financeiro.
  • Isabella **SUGERE** ação recomendada (não executa sozinha).
  • Painel mostra → gestor aprova em 1 clique → ação é executada.

Coleção única: `isabella_opportunities` com `kind` = churn|dunning|revenue|
expansion|twin. Dedup por `(company_id, kind, subkind, target_type,
target_id)` em janela TTL.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db
from services.event_bus import EventType, emit_event

log = logging.getLogger("ponto.isabella_opportunities")

VALID_KINDS = ("churn", "dunning", "revenue", "expansion", "twin")
VALID_STATUSES = ("pending", "approved", "dismissed", "executed", "expired")
DEFAULT_TTL_HOURS = 72


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


async def ensure_indexes() -> None:
    try:
        await db.isabella_commander_opportunities.create_index(
            [("company_id", 1), ("kind", 1), ("status", 1), ("score", -1)])
        await db.isabella_commander_opportunities.create_index(
            [("company_id", 1), ("kind", 1), ("subkind", 1),
             ("target_type", 1), ("target_id", 1)],
            name="opp_dedup_idx")
        await db.isabella_commander_opportunities.create_index([("expires_at", 1)])
        await db.isabella_commander_opportunities.create_index(
            [("company_id", 1), ("created_at", -1)])
    except Exception as e:  # noqa
        log.warning("[opportunities] ensure_indexes: %s", e)


async def get_arpu(company_id: str) -> float:
    """ARPU interno consolidado por empresa. Busca:
       1. companies.arpu (configurável pelo cliente)
       2. média real dos últimos 90d (sum invoices.amount_paid /
          contagem de assinantes ativos)
       3. fallback 109.90 (média Ligo histórica)
    """
    try:
        c = await db.companies.find_one({"id": company_id}, {"_id": 0, "arpu": 1})
        if c and c.get("arpu"):
            return float(c["arpu"])
    except Exception:
        pass
    # tenta da média real
    try:
        cutoff = (_now() - timedelta(days=90)).isoformat()
        pipe = [
            {"$match": {"company_id": company_id,
                          "status": {"$in": ["paid", "pago", "PAGO"]},
                          "paid_at": {"$gte": cutoff}}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"},
                          "n": {"$sum": 1}}},
        ]
        agg = await db.invoices.aggregate(pipe).to_list(1)
        if agg and agg[0].get("n"):
            avg = agg[0]["total"] / agg[0]["n"]
            if avg > 0:
                return float(avg)
    except Exception:
        pass
    return 109.90


async def upsert_opportunity(*,
                              company_id: str,
                              kind: str,
                              subkind: str,
                              target_type: str,
                              target_id: str,
                              target_label: str,
                              score: float,
                              probability: float,
                              impact_brl: float,
                              reason_codes: List[str],
                              evidence: Dict[str, Any],
                              recommended_action: Dict[str, Any],
                              ttl_hours: int = DEFAULT_TTL_HOURS,
                              source: str = "isabella") -> Dict[str, Any]:
    """Cria ou atualiza (dedup) uma oportunidade pendente."""
    if kind not in VALID_KINDS:
        raise ValueError(f"kind inválido: {kind}")
    now = _now()
    expires = now + timedelta(hours=ttl_hours)
    key = {
        "company_id": company_id,
        "kind": kind,
        "subkind": subkind,
        "target_type": target_type,
        "target_id": target_id,
        "status": {"$in": ["pending", "approved"]},
    }
    existing = await db.isabella_commander_opportunities.find_one(key, {"_id": 0})
    if existing:
        await db.isabella_commander_opportunities.update_one(
            {"id": existing["id"]},
            {"$set": {
                "score": round(float(score), 2),
                "probability": round(float(probability), 4),
                "impact_brl": round(float(impact_brl), 2),
                "reason_codes": reason_codes,
                "evidence": evidence,
                "recommended_action": recommended_action,
                "target_label": target_label,
                "updated_at": _iso(now),
                "expires_at": _iso(expires),
                "source": source,
            }})
        return {**existing,
                "score": round(float(score), 2),
                "probability": round(float(probability), 4),
                "updated": True}
    doc = {
        "id": f"opp-{uuid.uuid4().hex[:14]}",
        "company_id": company_id,
        "kind": kind,
        "subkind": subkind,
        "target_type": target_type,
        "target_id": target_id,
        "target_label": target_label,
        "score": round(float(score), 2),
        "probability": round(float(probability), 4),
        "impact_brl": round(float(impact_brl), 2),
        "reason_codes": reason_codes,
        "evidence": evidence,
        "recommended_action": recommended_action,
        "status": "pending",
        "source": source,
        "created_at": _iso(now),
        "updated_at": _iso(now),
        "expires_at": _iso(expires),
    }
    await db.isabella_commander_opportunities.insert_one(doc)
    await emit_event(
        EventType.OPPORTUNITY_CREATED,
        company_id=company_id,
        source=source,
        severity="alta" if score >= 75 else ("media" if score >= 40 else "baixa"),
        payload={"opp_id": doc["id"], "kind": kind, "subkind": subkind,
                  "target": f"{target_type}:{target_id}",
                  "score": doc["score"], "impact_brl": doc["impact_brl"]})
    doc.pop("_id", None)
    return doc


async def list_opportunities(*, company_id: str,
                              kind: Optional[str] = None,
                              subkind: Optional[str] = None,
                              status: Optional[str] = "pending",
                              limit: int = 100) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"company_id": company_id}
    if kind:
        q["kind"] = kind
    if subkind:
        q["subkind"] = subkind
    if status:
        q["status"] = status
    return await db.isabella_commander_opportunities.find(q, {"_id": 0}).sort(
        [("score", -1), ("created_at", -1)]).limit(limit).to_list(limit)


async def get_opportunity(opp_id: str, company_id: str) -> Optional[Dict[str, Any]]:
    return await db.isabella_commander_opportunities.find_one(
        {"id": opp_id, "company_id": company_id}, {"_id": 0})


async def update_status(opp_id: str, company_id: str, *,
                          status: str,
                          actor: Optional[str] = None,
                          result: Optional[Dict[str, Any]] = None,
                          notes: Optional[str] = None) -> Dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"status inválido: {status}")
    patch: Dict[str, Any] = {"status": status, "updated_at": _iso(_now())}
    if status == "approved":
        patch["approved_by"] = actor
        patch["approved_at"] = _iso(_now())
    if status == "dismissed":
        patch["dismissed_by"] = actor
        patch["dismissed_at"] = _iso(_now())
        patch["dismiss_notes"] = notes
    if status == "executed":
        patch["executed_at"] = _iso(_now())
        patch["execution_result"] = result or {}
    r = await db.isabella_commander_opportunities.update_one(
        {"id": opp_id, "company_id": company_id}, {"$set": patch})
    if not r.matched_count:
        raise ValueError(f"opportunity {opp_id} não encontrada")
    return await db.isabella_commander_opportunities.find_one(
        {"id": opp_id, "company_id": company_id}, {"_id": 0})


async def kpis(company_id: str) -> Dict[str, Any]:
    """KPIs agregados para o painel Isabella Console."""
    pipe = [
        {"$match": {"company_id": company_id}},
        {"$group": {
            "_id": {"kind": "$kind", "status": "$status"},
            "n": {"$sum": 1},
            "impact": {"$sum": "$impact_brl"},
        }},
    ]
    agg = await db.isabella_commander_opportunities.aggregate(pipe).to_list(200)
    out: Dict[str, Any] = {"by_kind": {}, "totals": {
        "pending": 0, "approved": 0, "executed": 0, "dismissed": 0,
        "impact_pending_brl": 0.0, "impact_executed_brl": 0.0}}
    for row in agg:
        k = (row["_id"] or {}).get("kind", "unknown")
        s = (row["_id"] or {}).get("status", "unknown")
        out["by_kind"].setdefault(k, {"pending": 0, "approved": 0,
                                         "executed": 0, "dismissed": 0,
                                         "impact_brl": 0.0})
        out["by_kind"][k][s] = out["by_kind"][k].get(s, 0) + row["n"]
        out["by_kind"][k]["impact_brl"] += float(row.get("impact") or 0)
        if s in out["totals"]:
            out["totals"][s] += row["n"]
        if s == "pending":
            out["totals"]["impact_pending_brl"] += float(row.get("impact") or 0)
        elif s == "executed":
            out["totals"]["impact_executed_brl"] += float(row.get("impact") or 0)
    return out


async def expire_old() -> int:
    """Marca como `expired` oportunidades pendentes cujo TTL passou."""
    now_iso = _iso(_now())
    r = await db.isabella_commander_opportunities.update_many(
        {"status": "pending", "expires_at": {"$lt": now_iso}},
        {"$set": {"status": "expired", "updated_at": now_iso}})
    return r.modified_count or 0
