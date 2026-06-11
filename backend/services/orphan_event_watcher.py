"""ORPHAN EVENT WATCHER — proteção multi-tenant em tempo real.

A cada 10min escaneia motor_ia_events. Se acha evento sem company_id:
  1. Audita em audit_chain
  2. Coloca source em quarentena (nervous_quarantined_sources)
  3. Abre opp critical no Conselho IA
  4. Health Center sinaliza YELLOW/RED

Source em quarentena = bloqueio futuro via emit_event_guard.
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "shield",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": False,
    "notes": "Watcher de eventos órfãos. Persiste em audit_chain + "
              "nervous_quarantined_sources + isabella_commander_opportunities. "
              "Não emite eventos próprios (é leitor + reator).",
}

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from apscheduler.triggers.cron import CronTrigger

from database import db
from services import audit_chain

log = logging.getLogger("ponto.orphan_watcher")
QUAR_COLL = "nervous_quarantined_sources"


def _now():
    return datetime.now(timezone.utc)


async def ensure_indexes() -> None:
    try:
        await db[QUAR_COLL].create_index("source", unique=True)
        await db[QUAR_COLL].create_index([("status", 1), ("last_detected_at", -1)])
    except Exception as e:
        log.warning("[orphan_watcher] indexes: %s", e)


async def scan_orphans(window_minutes: int = 10) -> Dict[str, Any]:
    """Escaneia últimos N min. Retorna {detected, quarantined, audit_ids}."""
    cut = (_now() - timedelta(minutes=window_minutes)).isoformat()
    query = {
        "timestamp": {"$gte": cut},
        "$or": [{"company_id": None}, {"company_id": ""},
                  {"company_id": {"$exists": False}}],
    }
    detected: List[Dict] = []
    async for ev in db.motor_ia_events.find(query, {"_id": 0}).limit(500):
        detected.append(ev)
    if not detected:
        return {"detected": 0, "quarantined": 0, "audit_ids": []}

    # Agrega por source
    by_source: Dict[str, List[Dict]] = {}
    for ev in detected:
        src = ev.get("source") or "unknown"
        by_source.setdefault(src, []).append(ev)

    audit_ids: List[str] = []
    quarantined: List[str] = []
    for src, events in by_source.items():
        # Quarantine upsert
        await db[QUAR_COLL].update_one(
            {"source": src},
            {
                "$set": {
                    "source": src, "status": "ACTIVE",
                    "reason": f"emitiu {len(events)} evento(s) sem company_id",
                    "last_detected_at": _now().isoformat(),
                    "orphan_count_last_window": len(events),
                    "event_types_affected": list({
                        e.get("event_type") for e in events}),
                },
                "$setOnInsert": {
                    "first_detected_at": _now().isoformat(),
                    "id": f"quar-{uuid.uuid4().hex[:10]}",
                },
                "$inc": {"orphan_count_total": len(events)},
            }, upsert=True)
        quarantined.append(src)

        # Audit chain
        try:
            rec = await audit_chain.append(
                chain_key=f"shield-orphan-{src}",
                actor="orphan_watcher",
                action="ORPHAN_EVENT_DETECTED",
                payload={
                    "source": src, "count": len(events),
                    "event_types": list({e.get("event_type") for e in events}),
                    "risk": "multi_tenant_violation",
                    "sample_event_id": events[0].get("id"),
                })
            audit_ids.append(rec["audit_id"])
            await audit_chain.append(
                chain_key=f"shield-orphan-{src}",
                actor="orphan_watcher",
                action="SOURCE_QUARANTINED",
                payload={"source": src, "auto": True})
        except Exception as e:
            log.warning("[orphan_watcher] audit_chain: %s", e)

        # Conselho IA opp
        try:
            await db.isabella_commander_opportunities.insert_one({
                "id": f"opp-mt-{uuid.uuid4().hex[:10]}",
                "company_id": "co-demo",
                "kind": "multi_tenant_violation",
                "subkind": "orphan_event",
                "score": 100, "probability": 1.0, "status": "pending",
                "target_label": f"Source '{src}' emitiu {len(events)} evento(s) sem company_id",
                "evidence": {
                    "source": src, "orphan_count": len(events),
                    "event_types": list({e.get("event_type") for e in events}),
                    "first_event_id": events[0].get("id"),
                },
                "reason_codes": ["orphan_event", "multi_tenant_risk"],
                "recommended_action": {
                    "type": "quarantine_release",
                    "message": (f"Source {src} colocado em quarentena. "
                                 "Corrigir resolução de company_id no código "
                                 "e liberar via "
                                 f"POST /api/nervous/quarantine/{src}/release."),
                },
                "impact_brl": 0,
                "created_at": _now().isoformat(),
            })
        except Exception as e:
            log.warning("[orphan_watcher] opp create failed: %s", e)

    log.warning("[orphan_watcher] %d evento(s) órfão(s) em %d source(s): %s",
                  len(detected), len(by_source), list(by_source.keys()))
    return {
        "detected": len(detected), "quarantined": len(quarantined),
        "audit_ids": audit_ids, "sources": quarantined,
    }


async def is_quarantined(source: str) -> bool:
    """Usado por emit_event_guard antes de publicar."""
    doc = await db[QUAR_COLL].find_one(
        {"source": source, "status": "ACTIVE"}, {"_id": 0, "status": 1})
    return bool(doc)


async def release_source(*, source: str, justificativa: str,
                            released_by: str) -> Dict[str, Any]:
    """Libera source da quarentena. Requer audit + justificativa."""
    res = await db[QUAR_COLL].update_one(
        {"source": source, "status": "ACTIVE"},
        {"$set": {
            "status": "RELEASED",
            "released_at": _now().isoformat(),
            "released_by": released_by,
            "release_justification": justificativa[:500],
        }})
    if res.modified_count == 0:
        return {"ok": False, "reason": "source não está em quarentena"}
    try:
        await audit_chain.append(
            chain_key=f"shield-orphan-{source}",
            actor=released_by, action="SOURCE_RELEASED",
            payload={"justificativa": justificativa[:500]})
    except Exception:
        pass
    # Re-scan imediato pra reabilitar quarentena se ainda houver órfão
    await scan_orphans(window_minutes=10)
    return {"ok": True, "source": source}


async def quarantined_list() -> List[Dict[str, Any]]:
    items: List[Dict] = []
    async for d in db[QUAR_COLL].find(
            {"status": "ACTIVE"}, {"_id": 0}).sort("last_detected_at", -1):
        items.append(d)
    return items


async def orphan_status_24h() -> Dict[str, Any]:
    cut = (_now() - timedelta(hours=24)).isoformat()
    n_orph = await db.motor_ia_events.count_documents({
        "timestamp": {"$gte": cut},
        "$or": [{"company_id": None}, {"company_id": ""},
                  {"company_id": {"$exists": False}}]})
    n_quar = await db[QUAR_COLL].count_documents({"status": "ACTIVE"})
    if n_quar > 0 or n_orph > 5:
        status = "RED"
    elif n_orph > 0:
        status = "YELLOW"
    else:
        status = "GREEN"
    return {"status": status, "orphans_24h": n_orph,
              "active_quarantines": n_quar}


async def watcher_job():
    try:
        await scan_orphans(window_minutes=10)
    except Exception as e:
        log.error("[orphan_watcher] crashed: %r", e)


def register_scheduler(scheduler) -> None:
    scheduler.add_job(
        watcher_job,
        CronTrigger(minute="*/10"),  # a cada 10min
        id="orphan_event_watcher",
        replace_existing=True, max_instances=1,
        misfire_grace_time=600,
    )
    log.info("[startup] orphan_event_watcher registered (*/10min)")
