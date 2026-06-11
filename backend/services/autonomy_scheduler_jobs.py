"""
autonomy_scheduler_jobs.py — Sprint final V5.0
Funções top-level que serão registradas no scheduler global do server.py.
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import os

log = logging.getLogger("autonomy_jobs")


def _co() -> str:
    return os.environ.get("AUTONOMY_DEFAULT_COMPANY", "co-demo")


async def drives():
    from services import autonomous_engine as eng
    co = _co()
    try:
        await eng.drive_from_overdue(co, limit=5)
        await eng.drive_from_isabella_churn(co, limit=5)
        await eng.drive_from_onu_degraded(co, limit=5)
        # V6.2 FASE 4 — Isabella full autônoma
        await eng.drive_from_isabella_retention(co, limit=5)
        await eng.drive_from_isabella_referral(co, limit=5)
        await eng.drive_from_isabella_collection(co, limit=5)
    except Exception as e:  # noqa: BLE001
        log.warning("[autonomy_jobs] drives fail: %s", e)


async def reconcile():
    from services import reconcile_worker as rec
    try:
        await rec.reconcile_all_recent(_co(), hours=168)
    except Exception as e:  # noqa: BLE001
        log.warning("[autonomy_jobs] reconcile fail: %s", e)


async def briefing_07h():
    from services import briefing_dispatcher as bd
    try:
        await bd.dispatch(_co(), slot="07h")
    except Exception as e:  # noqa: BLE001
        log.warning("[autonomy_jobs] briefing 07h fail: %s", e)


async def briefing_12h():
    from services import briefing_dispatcher as bd
    try:
        await bd.dispatch(_co(), slot="12h")
    except Exception as e:  # noqa: BLE001
        log.warning("[autonomy_jobs] briefing 12h fail: %s", e)


async def briefing_18h():
    from services import briefing_dispatcher as bd
    try:
        await bd.dispatch(_co(), slot="18h")
    except Exception as e:  # noqa: BLE001
        log.warning("[autonomy_jobs] briefing 18h fail: %s", e)


async def self_healing_auto():
    """V7.1 FASE 5 — Healing automático sem clique humano.
    Roda apenas healers idempotentes."""
    from services import self_healing as sh
    co = _co()
    auto_keys = [
        "orphan_company_id",
        "subscribers_without_plan_price",
        "active_subscribers_without_phone",
        "onu_mapping_gap",
    ]
    for key in auto_keys:
        try:
            await sh.apply_correction(co, key)
        except Exception as e:  # noqa: BLE001
            log.warning("[autonomy_jobs] auto_heal %s fail: %s", key, e)
