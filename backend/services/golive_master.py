"""
golive_master.py — V8.0 PRIORIDADE 1
Verifica 8 dependências críticas continuamente.
VERDE só se TODAS estão saudáveis.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict

from database import db


def _now(): return datetime.now(timezone.utc).isoformat()


async def status(company_id: str) -> Dict[str, Any]:
    from services import transport_check
    wa = await transport_check.wa_status(company_id)

    checks: Dict[str, Any] = {}
    # 1-3: WA tokens (do wa_status)
    for k in ("WA_SIDECAR_TOKEN", "BAILEYS_SIDECAR_URL",
              "PRESIDENTE_IA_GESTOR_PHONE"):
        checks[k] = wa["checks"][k]
    # 4: WA session
    checks["WA_SESSION_OPEN"] = wa["checks"]["session_status_open"]
    # 5: Mongo
    try:
        await db.command("ping")
        checks["MONGODB"] = True
    except Exception:
        checks["MONGODB"] = False
    # 6: Scheduler
    try:
        from server import scheduler as gs
        checks["SCHEDULER"] = gs.running and any(
            j.id.startswith("autonomy_") for j in gs.get_jobs())
    except Exception:
        checks["SCHEDULER"] = False
    # 7: Event Bus = motor_ia_events na última hora
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=1)).isoformat()
    recent_events = await db.motor_ia_events.count_documents(
        {"company_id": company_id, "created_at": {"$gte": cutoff}})
    checks["EVENT_BUS"] = recent_events > 0
    # 8: Autonomous Engine = ciclos completos nas últimas 24h
    cutoff_24h = (datetime.now(timezone.utc)
                   - timedelta(hours=24)).isoformat()
    recent_cycles = await db.motor_ia_autonomous_cycles.count_documents({
        "company_id": company_id, "started_at": {"$gte": cutoff_24h}})
    checks["AUTONOMOUS_ENGINE"] = recent_cycles > 0

    blockers = [k for k, v in checks.items() if not v]
    state = "VERDE" if not blockers else "VERMELHO"
    return {
        "checked_at":  _now(),
        "state":       state,
        "checks":      checks,
        "blockers":    blockers,
        "blocker_count": len(blockers),
        "next_step": (
            "Operação 100% ativa" if state == "VERDE"
            else f"Resolver: {' · '.join(blockers)}"),
    }
