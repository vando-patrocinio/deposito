"""
self_healing.py — V6.2 FASE 1
Cada bloqueador identificado pelo `blockers_audit` recebe ação corretiva
EXECUTÁVEL com botão "APLICAR CORREÇÃO". Antes/Depois/ROI/Rollback registrados.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from database import db


def _now(): return datetime.now(timezone.utc)
def _iso(): return _now().isoformat()
def _uid(): return f"heal-{uuid.uuid4().hex[:12]}"


# ============ HEALERS por kind de bloqueador ============ #

async def _heal_orphan_records(company_id: str) -> Dict[str, Any]:
    from scripts import audit_multitenant
    before = await audit_multitenant.audit(db)
    fixed = await audit_multitenant.fix(db)
    after = await audit_multitenant.audit(db)
    diff = (before["summary"]["total_orphans"]
            - after["summary"]["total_orphans"])
    return {
        "before": {"orphans": before["summary"]["total_orphans"]},
        "after":  {"orphans": after["summary"]["total_orphans"]},
        "fixed":  diff,
        "rollback_supported": False,
        "rollback_hint": "Backfill é idempotente; órfãos novos serão "
                          "tratados em próxima execução",
    }


async def _heal_plan_price(company_id: str) -> Dict[str, Any]:
    from scripts.backfill_financial import backfill as bf
    before_no_price = await db.subscribers.count_documents({
        "company_id": company_id,
        "$or": [{"plan_price": {"$exists": False}},
                 {"plan_price": 0}, {"plan_price": None}]})
    stats = await bf(db, dry_run=False)
    after_no_price = await db.subscribers.count_documents({
        "company_id": company_id,
        "$or": [{"plan_price": {"$exists": False}},
                 {"plan_price": 0}, {"plan_price": None}]})
    fixed = before_no_price - after_no_price
    # ROI estimado: cada subscriber com plan_price habilita decisões financeiras
    # Estimamos R$ 0,18 × plan_price médio por ação Tier C aplicável
    avg_pipe = [{"$match": {"company_id": company_id,
                              "plan_price": {"$gt": 0}}},
                 {"$group": {"_id": None,
                              "avg": {"$avg": "$plan_price"}}}]
    avg_doc = await db.subscribers.aggregate(avg_pipe).to_list(1)
    avg = float(avg_doc[0]["avg"]) if avg_doc else 100.0
    roi_BRL = round(fixed * avg * 0.18, 2)
    return {
        "before": {"without_price": before_no_price},
        "after":  {"without_price": after_no_price},
        "fixed":  fixed,
        "roi_BRL_estimated": roi_BRL,
        "backfill_stats": stats,
        "rollback_supported": False,
        "rollback_hint": "Preços vieram da mediana real de invoices; "
                          "podem ser sobrescritos por sincronização",
    }


async def _heal_phone_missing(company_id: str) -> Dict[str, Any]:
    """Tenta enriquecer phone pegando de invoices/contracts."""
    before = await db.subscribers.count_documents({
        "company_id": company_id, "status": "ATIVO",
        "$or": [{"phone": {"$exists": False}}, {"phone": ""}, {"phone": None}]})

    # Heurística: invoices.phone → subscriber.phone
    pipe = [
        {"$match": {"company_id": company_id,
                     "phone": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$subscriber_document",
                     "phone": {"$first": "$phone"}}},
    ]
    fixed = 0
    async for inv in db.subscriber_invoices.aggregate(pipe):
        doc = inv["_id"]
        if not doc: continue
        r = await db.subscribers.update_one(
            {"company_id": company_id, "document": doc,
              "$or": [{"phone": {"$exists": False}}, {"phone": ""},
                       {"phone": None}]},
            {"$set": {"phone": inv["phone"],
                       "_phone_source": "invoice_enrich"}})
        fixed += r.modified_count
    after = await db.subscribers.count_documents({
        "company_id": company_id, "status": "ATIVO",
        "$or": [{"phone": {"$exists": False}}, {"phone": ""}, {"phone": None}]})
    return {
        "before": {"without_phone": before},
        "after":  {"without_phone": after},
        "fixed":  fixed,
        "roi_BRL_estimated": round(fixed * 18.0, 2),  # média Tier C recover
        "rollback_supported": True,
        "rollback_hint": "Reverter com _phone_source=invoice_enrich",
    }


async def _heal_onu_mapping(company_id: str) -> Dict[str, Any]:
    """Vincula subscribers a smartolt_onu_zone quando há match por
    document."""
    before = await db.subscribers.count_documents({
        "company_id": company_id, "status": "ATIVO",
        "$or": [{"smartolt_onu_zone": {"$exists": False}},
                 {"smartolt_onu_zone": ""},
                 {"smartolt_onu_zone": None}]})
    fixed = 0
    async for o in db.smartolt_onus.find(
            {"company_id": company_id, "zone": {"$nin": [None, ""]}}
    ).limit(5000):
        doc = o.get("subscriber_document") or o.get("document")
        if not doc: continue
        r = await db.subscribers.update_one(
            {"company_id": company_id, "document": doc,
              "$or": [{"smartolt_onu_zone": {"$exists": False}},
                       {"smartolt_onu_zone": ""},
                       {"smartolt_onu_zone": None}]},
            {"$set": {"smartolt_onu_zone": o["zone"],
                       "smartolt_onu_status": o.get("status") or "Online",
                       "_onu_mapping_source": "smartolt_enrich"}})
        fixed += r.modified_count
    after = await db.subscribers.count_documents({
        "company_id": company_id, "status": "ATIVO",
        "$or": [{"smartolt_onu_zone": {"$exists": False}},
                 {"smartolt_onu_zone": ""},
                 {"smartolt_onu_zone": None}]})
    return {
        "before": {"without_zone": before},
        "after":  {"without_zone": after},
        "fixed":  fixed,
        "roi_BRL_estimated": round(fixed * 5.0, 2),
        "rollback_supported": True,
        "rollback_hint": "Reverter via _onu_mapping_source",
    }


async def _heal_credential_block(company_id: str,
                                    blocker: str) -> Dict[str, Any]:
    """Credenciais WA não podem ser auto-fixadas — só documentamos."""
    return {
        "before": {"configured": False},
        "after":  {"configured": False},
        "fixed":  0,
        "roi_BRL_estimated": 0.0,
        "rollback_supported": False,
        "manual_step_required": True,
        "instructions": (
            f"Configurar {blocker} no backend/.env e fazer "
            "sudo supervisorctl restart backend"),
    }


# ============ Dispatcher ============ #

HEALERS = {
    "orphan_company_id":               _heal_orphan_records,
    "subscribers_without_plan_price":  _heal_plan_price,
    "active_subscribers_without_phone": _heal_phone_missing,
    "onu_mapping_gap":                 _heal_onu_mapping,
    "WA_SIDECAR_TOKEN":                 lambda co: _heal_credential_block(co, "WA_SIDECAR_TOKEN"),
    "BAILEYS_SIDECAR_URL":              lambda co: _heal_credential_block(co, "BAILEYS_SIDECAR_URL"),
    "PRESIDENTE_IA_GESTOR_PHONE":       lambda co: _heal_credential_block(co, "PRESIDENTE_IA_GESTOR_PHONE"),
    "session_status_open":              lambda co: _heal_credential_block(co, "Baileys session"),
    "sidecar_reachable":                lambda co: _heal_credential_block(co, "Baileys sidecar"),
}


async def apply_correction(company_id: str,
                            blocker_key: str) -> Dict[str, Any]:
    """Executa healer + persiste em motor_ia_self_healing."""
    if blocker_key not in HEALERS:
        raise ValueError(f"healer não disponível para '{blocker_key}'")
    healer = HEALERS[blocker_key]
    started = _now()
    heal_id = _uid()
    record = {
        "heal_id": heal_id, "company_id": company_id,
        "blocker_key": blocker_key,
        "started_at": started.isoformat(),
        "status": "running",
    }
    await db.motor_ia_self_healing.insert_one(dict(record))
    try:
        result = await healer(company_id)
        duration_ms = int((_now() - started).total_seconds() * 1000)
        await db.motor_ia_self_healing.update_one(
            {"heal_id": heal_id},
            {"$set": {**result,
                       "duration_ms": duration_ms,
                       "finished_at": _iso(),
                       "status": "complete"}})
        return {"heal_id": heal_id, "status": "complete",
                 "duration_ms": duration_ms, **result}
    except Exception as e:  # noqa: BLE001
        await db.motor_ia_self_healing.update_one(
            {"heal_id": heal_id},
            {"$set": {"status": "failed", "error": str(e)[:200],
                       "finished_at": _iso()}})
        raise


async def healing_score(company_id: str,
                          days: int = 7) -> Dict[str, Any]:
    """V6.2 FASE 2 — Self Healing Score."""
    from datetime import timedelta
    cutoff = (_now() - timedelta(days=days)).isoformat()
    cur = db.motor_ia_self_healing.find(
        {"company_id": company_id, "started_at": {"$gte": cutoff}})
    total = 0
    auto_fixed = 0
    manual = 0
    duration_total = 0
    roi_recovered = 0.0
    by_kind: Dict[str, Dict[str, Any]] = {}
    async for h in cur:
        total += 1
        if h.get("manual_step_required"):
            manual += 1
        elif h.get("status") == "complete" and (h.get("fixed") or 0) > 0:
            auto_fixed += 1
            duration_total += h.get("duration_ms", 0)
            roi_recovered += float(h.get("roi_BRL_estimated") or 0)
        kind = h.get("blocker_key", "unknown")
        b = by_kind.setdefault(kind, {"count": 0, "fixed": 0,
                                          "roi_BRL": 0.0})
        b["count"] += 1
        b["fixed"] += int(h.get("fixed") or 0)
        b["roi_BRL"] += float(h.get("roi_BRL_estimated") or 0)

    # Score = auto_fixed / (auto_fixed + manual). Sem heals = 0.
    effective = auto_fixed + manual
    score = round((auto_fixed / max(effective, 1)) * 100, 1) if effective else 0.0
    avg_ms = int(duration_total / max(auto_fixed, 1))

    if score >= 90: cls = "AUTO_HEAL"
    elif score >= 70: cls = "MOSTLY_AUTO"
    elif score >= 40: cls = "HYBRID"
    elif score > 0: cls = "MOSTLY_MANUAL"
    else: cls = "NO_DATA"

    return {
        "generated_at": _iso(),
        "company_id": company_id,
        "window_days": days,
        "score": score,
        "classification": cls,
        "total_healings": total,
        "auto_fixed": auto_fixed,
        "manual_required": manual,
        "avg_duration_ms": avg_ms,
        "roi_BRL_recovered": round(roi_recovered, 2),
        "by_kind": by_kind,
    }
