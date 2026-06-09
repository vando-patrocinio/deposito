"""olt_polling_scheduler.py — Polling periódico (5min) das OLTs ativas
via SNMP. Cacheia resultado em `db.olt_snmp_cache` para discovery
instantâneo (sem latência de walk).

Registrado no APScheduler do server.py via setup_olt_polling().
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict
from database import db
from services import secrets_vault as vault
from services.vsol_snmp import VsolSnmpPoller

logger = logging.getLogger("smartprov.olt_polling")

_POLL_INTERVAL_MIN = 5


def _k(profile: str, field: str) -> str:
    return f"integration:olt:profiles:{profile}:{field}"


async def _list_enabled_olts() -> list:
    names = set()
    async for d in db.secrets_vault.find(
            {"name": {"$regex": "^integration:olt:profiles:"}},
            {"name": 1}):
        parts = d["name"].split(":")
        if len(parts) >= 5:
            names.add(parts[3])
    enabled = []
    for n in sorted(names):
        en = await vault.get_secret(_k(n, "enabled"), scope="global")
        if en != "false":
            enabled.append(n)
    return enabled


async def _poll_one(profile: str) -> Dict[str, Any]:
    host = await vault.get_secret(_k(profile, "host"), scope="global")
    port = await vault.get_secret(_k(profile, "port"), scope="global")
    version = await vault.get_secret(_k(profile, "version"), scope="global")
    comm = await vault.get_secret(_k(profile, "community"), scope="global")
    vendor = await vault.get_secret(_k(profile, "vendor"), scope="global")
    if not host or not comm:
        return {"profile": profile, "error": "incomplete"}
    poller = VsolSnmpPoller(
        host=host, community=comm,
        port=int(port or 161),
        version=version or "v2c",
        vendor=vendor or "vsol",
    )
    try:
        return await poller.discover_onus()
    except Exception as e:
        return {"profile": profile, "error": repr(e)[:200]}


async def poll_all_and_cache() -> Dict[str, Any]:
    """Executa polling em todas OLTs habilitadas em paralelo e
    atualiza `db.olt_snmp_cache` com upsert por profile."""
    enabled = await _list_enabled_olts()
    if not enabled:
        return {"olts": 0, "polled": 0}
    started = datetime.now(timezone.utc)
    results = await asyncio.gather(
        *[_poll_one(n) for n in enabled],
        return_exceptions=True)
    polled_ok = 0
    for n, r in zip(enabled, results):
        if isinstance(r, Exception):
            r = {"profile": n, "error": repr(r)[:200]}
        ts = datetime.now(timezone.utc)
        doc = {
            "id": f"olt-cache-{n}",
            "profile": n,
            "polled_at": ts.isoformat(),
            "onu_count": r.get("onu_count", 0),
            "onus": r.get("onus", []) if "error" not in r else [],
            "errors": r.get("errors"),
            "error": r.get("error"),
        }
        await db.olt_snmp_cache.update_one(
            {"id": doc["id"]}, {"$set": doc}, upsert=True)
        if "error" not in r:
            polled_ok += 1
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    logger.info("[olt-polling] %d/%d OK em %.1fs",
                  polled_ok, len(enabled), elapsed)
    return {"olts": len(enabled), "polled_ok": polled_ok,
             "elapsed_s": round(elapsed, 1)}


def setup_olt_polling(scheduler) -> None:
    """Registra job APScheduler para rodar polling periódico.
    Chamado do server.py após instanciar o scheduler global."""
    try:
        scheduler.add_job(
            poll_all_and_cache,
            "interval",
            minutes=_POLL_INTERVAL_MIN,
            id="olt_snmp_polling",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        logger.info("[olt-polling] scheduler registrado "
                     "(intervalo=%dmin)", _POLL_INTERVAL_MIN)
    except Exception as e:
        logger.warning("[olt-polling] falha ao registrar job: %r", e)
