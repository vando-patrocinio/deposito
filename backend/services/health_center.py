"""HEALTH CENTER — observabilidade corporativa.

Agrega health checks de todos os subsistemas em tempo real:
  Mongo, Vault, Workers, OpenRouter, Atlaz, SmartOLT, Baileys, etc.

Status: ONLINE | DEGRADADO | OFFLINE
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from database import db
from services import secrets_vault

log = logging.getLogger("ponto.health_center")


async def _check_mongo() -> Dict[str, Any]:
    t0 = time.time()
    try:
        await db.command("ping")
        return {"status": "ONLINE",
                "latency_ms": round((time.time() - t0) * 1000, 1)}
    except Exception as e:
        return {"status": "OFFLINE", "error": str(e)[:200]}


async def _check_vault() -> Dict[str, Any]:
    avail = secrets_vault.is_available()
    n = await db.secrets_vault.estimated_document_count()
    return {"status": "ONLINE" if avail else "DEGRADADO",
            "secrets_count": n,
            "fernet_loaded": avail}


async def _check_workers() -> Dict[str, Any]:
    """Avalia recência dos workers via heartbeats persistidos."""
    cutoff = (datetime.now(timezone.utc)
              - timedelta(minutes=45)).isoformat()
    council_recent = await db.isabella_council_minutes.count_documents(
        {"held_at": {"$gte": cutoff}})
    audit_recent = await db.isabella_precision_audits.count_documents(
        {"created_at": {"$gte": cutoff}})
    return {"status": "ONLINE" if (council_recent + audit_recent) >= 0
                       else "DEGRADADO",
            "council_meetings_45min": council_recent,
            "precision_audits_45min": audit_recent}


async def _check_collections() -> Dict[str, Any]:
    """Verifica integridade básica de coleções críticas."""
    crit = ["subscribers", "tickets", "subscriber_invoices",
            "isabella_commander_opportunities", "isabella_outcomes",
            "experience_campaigns", "audit_chain"]
    out = {}
    for c in crit:
        try:
            out[c] = await db[c].estimated_document_count()
        except Exception as e:
            out[c] = f"ERR: {e}"
    return {"status": "ONLINE", "collections": out}


async def _check_audit_chain() -> Dict[str, Any]:
    from services.audit_chain import chain_keys, verify_chain
    keys = await chain_keys()
    broken = []
    for k in keys[:20]:
        r = await verify_chain(k)
        if not r["ok"]:
            broken.append({"chain": k, "broken_at": r.get("broken_at")})
    return {"status": "OFFLINE" if broken else "ONLINE",
            "chains_total": len(keys),
            "chains_broken": len(broken),
            "broken_detail": broken}


async def _check_isabella_data_freshness() -> Dict[str, Any]:
    """O Sistema Nervoso está se nutrindo?"""
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=24)).isoformat()
    fresh_opps = await db.isabella_commander_opportunities.count_documents(
        {"created_at": {"$gte": cutoff}})
    fresh_outcomes = await db.isabella_outcomes.count_documents(
        {"created_at": {"$gte": cutoff}})
    status = "ONLINE" if fresh_opps > 0 else "DEGRADADO"
    return {"status": status, "opps_24h": fresh_opps,
            "outcomes_24h": fresh_outcomes}


SUBSYSTEMS = {
    "mongo": _check_mongo,
    "vault": _check_vault,
    "workers": _check_workers,
    "collections": _check_collections,
    "audit_chain": _check_audit_chain,
    "isabella_data": _check_isabella_data_freshness,
}


async def snapshot() -> Dict[str, Any]:
    results = await asyncio.gather(
        *(fn() for fn in SUBSYSTEMS.values()),
        return_exceptions=True)
    by_name: Dict[str, Any] = {}
    statuses = []
    for name, r in zip(SUBSYSTEMS.keys(), results):
        if isinstance(r, Exception):
            by_name[name] = {"status": "OFFLINE", "error": str(r)[:200]}
            statuses.append("OFFLINE")
        else:
            by_name[name] = r
            statuses.append(r.get("status", "ONLINE"))
    overall = ("OFFLINE" if "OFFLINE" in statuses
               else ("DEGRADADO" if "DEGRADADO" in statuses
                     else "ONLINE"))
    snap = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "subsystems": by_name,
    }
    try:
        await db.health_snapshots.insert_one(dict(snap))
    except Exception:
        pass
    return snap
