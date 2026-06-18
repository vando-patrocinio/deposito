"""Watchtower IA endpoints — Painéis Executivos da Isabella.

Endpoints compostos (1 request → tudo que o dashboard precisa) para:
  • Watchtower IA Presidente: saúde geral da IA (índices, alarmes, claims,
    promessas, latência, falhas de envio).
  • Watchtower Relacionamento: visão por cliente (trust, memórias,
    promessas, VIPs, follow-ups).

Acesso: gestor/admin/auditor (mesmo padrão dos outros watchtowers).
"""

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

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from core import get_current_user, is_super_admin
from database import db
from services.rate_limit import get_limit, limiter

logger = logging.getLogger("ponto.isabella_watchtower")
router = APIRouter(prefix="/api/isabella/watchtower",
                    tags=["isabella_watchtower"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_priv(user: Dict[str, Any]) -> None:
    role = (user or {}).get("role") or ""
    if is_super_admin(user):
        return
    if role not in ("owner", "admin", "operator", "auditor",
                     "gestor", "administrador"):
        raise HTTPException(403, "acesso restrito (gestor/admin)")


def _company_or_param(user: Dict[str, Any], cid: Optional[str]) -> str:
    if cid and is_super_admin(user):
        return cid
    out = (user or {}).get("company_id")
    if not out:
        raise HTTPException(400, "company_id ausente")
    return out


# ── HELPERS ──────────────────────────────────────────────────────


async def _claims_no_evidence(company_id: str,
                                  hours: int) -> Dict[str, Any]:
    """Claims que NÃO encontraram evidência (audit_passed=False) ou
    expiraram sem consumo. Indicador chave de hallucination risk."""
    since = _now() - timedelta(hours=hours)
    q_failed = {"company_id": company_id, "audit_passed": False,
                 "created_at": {"$gte": since}}
    q_orphan = {"company_id": company_id, "audit_passed": True,
                 "consumed_by": None, "created_at": {"$gte": since}}
    failed_n = await db.isabella_factual_claims.count_documents(q_failed)
    orphan_n = await db.isabella_factual_claims.count_documents(q_orphan)
    samples = await db.isabella_factual_claims.find(
        q_failed,
        {"_id": 1, "claim_type": 1, "claim_text": 1, "created_at": 1,
         "audit_reason": 1},
    ).sort("created_at", -1).limit(5).to_list(5)
    for s in samples:
        s["id"] = s.pop("_id", None)
        if hasattr(s.get("created_at"), "isoformat"):
            s["created_at"] = s["created_at"].isoformat()
    return {"failed": failed_n, "orphan_no_consume": orphan_n,
              "samples": samples}


async def _promises_stats(company_id: str,
                              hours: int) -> Dict[str, Any]:
    """Promessas: abertas (pending), vencidas (pending + due_at<now),
    cumpridas no período."""
    since = _now() - timedelta(hours=hours)
    now = _now()
    coll = db.customer_promises
    open_n = await coll.count_documents(
        {"company_id": company_id, "status": "pending"})
    overdue_n = await coll.count_documents(
        {"company_id": company_id, "status": "pending",
         "due_at": {"$lt": now}})
    fulfilled_n = await coll.count_documents(
        {"company_id": company_id, "status": "resolved",
         "resolved_at": {"$gte": since}})
    # Sample de promessas em atraso
    overdue = await coll.find(
        {"company_id": company_id, "status": "pending",
         "due_at": {"$lt": now}},
        {"_id": 1, "phone": 1, "promise_text": 1, "created_at": 1,
         "due_at": 1},
    ).sort("due_at", 1).limit(5).to_list(5)
    for o in overdue:
        o["id"] = o.pop("_id", None)
        for k in ("created_at", "due_at"):
            v = o.get(k)
            if hasattr(v, "isoformat"):
                o[k] = v.isoformat()
    return {"open": open_n, "overdue": overdue_n,
              "fulfilled": fulfilled_n,
              "overdue_samples": overdue}


async def _wa_dispatch_stats(company_id: str,
                                  hours: int) -> Dict[str, Any]:
    """Latência média/p95 + falhas de envio recentes (wa_dispatch_metrics)."""
    since = _now() - timedelta(hours=hours)
    # avg + samples ordenados (para p95 simples)
    cursor = db.wa_dispatch_metrics.find(
        {"company_id": company_id, "ts": {"$gte": since}},
        {"_id": 0, "ok": 1, "latency_ms": 1, "reason": 1, "ts": 1},
    ).sort("ts", -1).limit(2000)
    rows = await cursor.to_list(2000)
    total = len(rows)
    fails = [r for r in rows if not r.get("ok")]
    fail_n = len(fails)
    lats = sorted(r.get("latency_ms") or 0 for r in rows if r.get("ok"))
    if lats:
        avg = sum(lats) / len(lats)
        p95_idx = max(0, int(len(lats) * 0.95) - 1)
        p95 = lats[p95_idx]
    else:
        avg = 0
        p95 = 0
    # últimas 5 falhas
    fail_samples = []
    for r in fails[:5]:
        ts = r.get("ts")
        if hasattr(ts, "isoformat"):
            ts = ts.isoformat()
        fail_samples.append({"reason": r.get("reason") or "—",
                              "latency_ms": r.get("latency_ms"),
                              "ts": ts})
    return {"window_hours": hours, "total": total,
              "failures": fail_n,
              "success_rate": round(
                  (1 - fail_n / total) * 100, 1) if total else None,
              "latency_ms_avg": round(avg, 1),
              "latency_ms_p95": p95,
              "fail_samples": fail_samples}


async def _memories_stats(company_id: str,
                              hours: int) -> Dict[str, Any]:
    """Memórias criadas no período, por tipo, + amostras recentes."""
    since = _now() - timedelta(hours=hours)
    coll = db.customer_memory
    pipeline = [
        {"$match": {"company_id": company_id, "created_at": {"$gte": since}}},
        {"$group": {"_id": "$memory_type", "n": {"$sum": 1}}},
    ]
    rows = await coll.aggregate(pipeline).to_list(50)
    by_type = {r["_id"]: r["n"] for r in rows if r.get("_id")}
    total = sum(by_type.values())
    samples = await coll.find(
        {"company_id": company_id, "created_at": {"$gte": since}},
        {"_id": 1, "phone": 1, "memory_type": 1, "title": 1,
         "description": 1, "confidence": 1, "created_at": 1},
    ).sort("created_at", -1).limit(8).to_list(8)
    for s in samples:
        s["id"] = s.pop("_id", None)
        v = s.get("created_at")
        if hasattr(v, "isoformat"):
            s["created_at"] = v.isoformat()
    return {"total": total, "by_type": by_type, "samples": samples}


async def _follow_ups_pending(company_id: str) -> Dict[str, Any]:
    """Memórias PESSOAIS com follow_up_required=True (não vencidas ainda)."""
    coll = db.customer_memory
    now = _now()
    q = {"company_id": company_id,
          "follow_up_required": True,
          "$or": [{"expires_at": {"$gt": now}}, {"expires_at": None}]}
    n = await coll.count_documents(q)
    samples = await coll.find(
        q, {"_id": 1, "phone": 1, "title": 1, "description": 1,
            "confidence": 1, "created_at": 1},
    ).sort("created_at", -1).limit(8).to_list(8)
    for s in samples:
        s["id"] = s.pop("_id", None)
        v = s.get("created_at")
        if hasattr(v, "isoformat"):
            s["created_at"] = v.isoformat()
    return {"count": n, "samples": samples}


async def _top_clients_by_memories(company_id: str,
                                          limit: int = 10
                                          ) -> List[Dict[str, Any]]:
    """Ranking de clientes com mais memórias acumuladas (proxy de
    Trust/Relacionamento por cliente). Limita aos top N."""
    pipeline = [
        {"$match": {"company_id": company_id}},
        {"$group": {"_id": "$phone",
                     "memory_count": {"$sum": 1},
                     "last_memory_at": {"$max": "$created_at"},
                     "avg_confidence": {"$avg": "$confidence"}}},
        {"$sort": {"memory_count": -1}},
        {"$limit": limit},
    ]
    rows = await db.customer_memory.aggregate(pipeline).to_list(limit)
    out: List[Dict[str, Any]] = []
    for r in rows:
        phone = r.get("_id") or ""
        # Trust score por cliente = confidence média normalizada para 0-100
        avg_conf = r.get("avg_confidence") or 0
        trust = round(float(avg_conf) * 100, 1)
        last = r.get("last_memory_at")
        if hasattr(last, "isoformat"):
            last = last.isoformat()
        out.append({"phone": phone,
                     "memory_count": r.get("memory_count"),
                     "last_memory_at": last,
                     "trust_score": trust})
    return out


async def _vip_clients(company_id: str,
                            limit: int = 10) -> List[Dict[str, Any]]:
    """Clientes marcados como VIP (memória PESSOAL com tag VIP no título
    ou na descrição). Heurística simples (substring case-insensitive)."""
    cursor = db.customer_memory.find(
        {"company_id": company_id, "memory_type": "PESSOAL",
         "$or": [{"title": {"$regex": "vip", "$options": "i"}},
                  {"description": {"$regex": "vip", "$options": "i"}},
                  {"tags": {"$in": ["VIP", "vip"]}}]},
        {"_id": 1, "phone": 1, "title": 1, "description": 1,
         "confidence": 1, "created_at": 1},
    ).sort("created_at", -1).limit(limit)
    items = await cursor.to_list(limit)
    for it in items:
        it["id"] = it.pop("_id", None)
        v = it.get("created_at")
        if hasattr(v, "isoformat"):
            it["created_at"] = v.isoformat()
    return items


# ── ENDPOINTS ────────────────────────────────────────────────────


@router.get("/ia-presidente")
@limiter.limit(get_limit("isabella_read"))
async def watchtower_ia_presidente(
    request: Request,
    hours: int = Query(24, ge=1, le=720),
    cid: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Painel composto da saúde da IA.

    Retorna ISABELLA INDEX + AUTONOMY alarms + claims (failed/orphan)
    + promessas (open/overdue/fulfilled) + latência WhatsApp + falhas.
    """
    _require_priv(user)
    company = _company_or_param(user, cid)

    from services.isabella_confidence import isabella_index, autonomy_alarms

    index = await isabella_index(company_id=company, hours=hours)
    alarms_doc = await autonomy_alarms(company_id=company, hours=168)
    claims = await _claims_no_evidence(company, hours)
    promises = await _promises_stats(company, hours)
    dispatch = await _wa_dispatch_stats(company, hours)

    return {
        "company_id": company,
        "window_hours": hours,
        "generated_at": _now().isoformat(),
        "isabella_index": index,
        "autonomy_alarms": alarms_doc,
        "claims": claims,
        "promises": promises,
        "wa_dispatch": dispatch,
    }


@router.get("/relacionamento")
@limiter.limit(get_limit("isabella_read"))
async def watchtower_relacionamento(
    request: Request,
    hours: int = Query(168, ge=1, le=720),
    cid: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Painel composto do relacionamento por cliente.

    Retorna ranking top clientes por memórias (proxy Trust Score),
    contagem de memórias criadas/por tipo, promessas, VIPs, últimas
    memórias relevantes e follow-ups pendentes.
    """
    _require_priv(user)
    company = _company_or_param(user, cid)

    memories = await _memories_stats(company, hours)
    promises = await _promises_stats(company, hours)
    follow_ups = await _follow_ups_pending(company)
    top_clients = await _top_clients_by_memories(company, limit=10)
    vips = await _vip_clients(company, limit=10)

    return {
        "company_id": company,
        "window_hours": hours,
        "generated_at": _now().isoformat(),
        "memories": memories,
        "promises": promises,
        "follow_ups_pending": follow_ups,
        "top_clients": top_clients,
        "vip_clients": vips,
    }
