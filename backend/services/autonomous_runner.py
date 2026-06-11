"""Autonomous Runner — ativa pipelines proativos que já existem.

Reutiliza:
  • services.autonomous_engine.drive_from_overdue
  • services.autonomous_engine.drive_from_isabella_churn
  • services.autonomous_engine.drive_from_isabella_retention
  • services.autonomous_engine.drive_from_isabella_referral
  • services.autonomous_engine.drive_from_isabella_collection
  • services.autonomous_engine.drive_from_onu_degraded
  • services.rede_ia_outage_detector.detect_now
  • services.isabella_scoring (já popula isabella_opportunities)

NÃO recria nenhuma lógica. Apenas chama o que existe, em loop.

API:
  await run_once_for(tenant_id) → dict com counters
  await run_once_all() → dict {tenant: counters}
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import logging
import os
from datetime import datetime, timezone

from database import db

logger = logging.getLogger("autonomous_runner")


def _now():
    return datetime.now(timezone.utc)


def _is_test_tenant(cid: str) -> bool:
    if not cid:
        return True
    cid_l = cid.lower()
    return (cid_l.startswith("test-") or cid_l.startswith("co-test-")
            or cid_l == "_orphan" or "homolog" in cid_l)


async def run_once_for(company_id: str) -> dict:
    """Roda 1 ciclo completo para 1 tenant."""
    from services import autonomous_engine as ae
    result = {"company_id": company_id, "ts": _now().isoformat(),
              "drivers": {}}
    drivers = [
        ("overdue", ae.drive_from_overdue),
        ("churn", ae.drive_from_isabella_churn),
        ("retention", ae.drive_from_isabella_retention),
        ("referral", ae.drive_from_isabella_referral),
        ("collection", ae.drive_from_isabella_collection),
        ("onu_degraded", ae.drive_from_onu_degraded),
    ]
    for name, fn in drivers:
        try:
            r = await fn(company_id)
            result["drivers"][name] = r if isinstance(r, dict) else {"ran": True}
        except Exception as e:  # noqa: BLE001
            result["drivers"][name] = {"error": repr(e)[:200]}

    # Outage detection (Álvaro proativo)
    try:
        from services.rede_ia_outage_detector import detect_now
        result["drivers"]["outage_detect"] = await detect_now(company_id)
    except Exception as e:  # noqa: BLE001
        result["drivers"]["outage_detect"] = {"error": repr(e)[:200]}

    return result


async def run_once_all(include_test: bool = False) -> dict:
    """Roda para todos os tenants com eventos. include_test=False ignora homolog."""
    tenants = await db.motor_ia_events.distinct("company_id")
    if not include_test:
        tenants = [t for t in tenants if not _is_test_tenant(t)]
    out = {}
    for cid in tenants:
        try:
            out[cid] = await run_once_for(cid)
        except Exception as e:  # noqa: BLE001
            out[cid] = {"error": repr(e)[:200]}
    return out


async def loop_forever(interval_s: int = 300) -> None:
    """Loop infinito para uso em scheduler standalone (não usado hoje;
    ativável via supervisor se desejado)."""
    while True:
        try:
            await run_once_all()
        except Exception as e:  # noqa: BLE001
            logger.exception("[autonomous_runner] erro: %s", e)
        await asyncio.sleep(interval_s)
