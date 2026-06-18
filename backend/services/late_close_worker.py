"""late_close_worker — Rede de segurança Onda B.

Para cada stok_services em status="ativo" cujo ticket associado já está
finalizado/encerrado há > N segundos, fecha o stok_service via
`auto_close_service_from_ticket`. Isso captura qualquer caso em que o
flow normal de finalize NÃO conseguiu fechar a OS (raro, mas
historicamente aconteceu).

Política CEO (18/06/2026):
  • NÃO usa try/except silencioso.
  • Cada execução grava relatório em `late_close_runs`.
  • Idempotente.

Uso CLI:
    # Dry-run
    python3 -m scripts.late_close_run --dry-run

    # Execução real
    python3 -m scripts.late_close_run

    # Para uma empresa específica
    python3 -m scripts.late_close_run --company-id co-demo
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db

logger = logging.getLogger("ponto.late_close_worker")

LATE_CLOSE_RUNS_COLL = "late_close_runs"
DEFAULT_LATE_GRACE_SECONDS = 60   # ticket fechado há > 60s já é late
MAX_BATCH = 500


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_to_dt(iso_str: Optional[str]) -> Optional[datetime]:
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        return None


async def find_late_close_candidates(
    *,
    company_id: Optional[str] = None,
    grace_seconds: int = DEFAULT_LATE_GRACE_SECONDS,
    limit: int = MAX_BATCH,
) -> List[Dict[str, Any]]:
    """Encontra stok_services em 'ativo' cujo ticket está finalizado
    há mais que `grace_seconds`."""
    q: Dict[str, Any] = {"status": "ativo",
                          "ticket_id": {"$exists": True, "$ne": None}}
    if company_id:
        q["company_id"] = company_id

    now = _now()
    candidates: List[Dict[str, Any]] = []

    cursor = db.stok_services.find(
        q,
        {"_id": 0, "id": 1, "ticket_id": 1, "company_id": 1,
         "type": 1, "technician_id": 1, "technician_name": 1,
         "created_at": 1},
    )

    async for svc in cursor:
        if len(candidates) >= limit:
            break
        t = await db.tickets.find_one(
            {"id": svc["ticket_id"], "company_id": svc["company_id"]},
            {"_id": 0, "status": 1, "finalized_at": 1, "closed_at": 1,
             "outcome": 1, "completion_data": 1,
             "assigned_collaborator_id": 1,
             "assigned_collaborator_name": 1},
        )
        if not t:
            # órfã — não é trabalho do late_close, é do reconcile
            continue
        if t.get("status") not in ("finalizada", "encerrada",
                                      "pendente_conciliacao"):
            continue
        # Verifica grace
        closed_ts = (t.get("finalized_at") or t.get("closed_at"))
        closed_dt = _iso_to_dt(closed_ts)
        if not closed_dt:
            continue
        if (now - closed_dt).total_seconds() < grace_seconds:
            continue
        candidates.append({"svc": svc, "ticket": t,
                            "closed_dt": closed_dt})
    return candidates


async def late_close_one(
    *, svc: Dict[str, Any], ticket: Dict[str, Any],
) -> Dict[str, Any]:
    """Fecha um stok_service via auto_close. NÃO swallow exceptions —
    propaga para o caller."""
    from routes.stok import auto_close_service_from_ticket
    completion_data = ticket.get("completion_data") or {}
    tech_id = (ticket.get("assigned_collaborator_id")
                or svc.get("technician_id"))
    tech_name = (ticket.get("assigned_collaborator_name")
                  or svc.get("technician_name") or "?")
    res = await auto_close_service_from_ticket(
        ticket_id=ticket["id"] if "id" in ticket else svc["ticket_id"],
        company_id=svc["company_id"],
        completion_data=completion_data,
        technician_id=tech_id,
        technician_name=tech_name,
        caller="late_close_worker",
    )
    return res or {}


async def run_late_close(
    *,
    company_id: Optional[str] = None,
    grace_seconds: int = DEFAULT_LATE_GRACE_SECONDS,
    dry_run: bool = False,
    limit: int = MAX_BATCH,
) -> Dict[str, Any]:
    """Executa 1 ciclo do worker. Retorna stats."""
    started_at = _now()
    candidates = await find_late_close_candidates(
        company_id=company_id, grace_seconds=grace_seconds, limit=limit,
    )
    stats = {
        "started_at": started_at,
        "company_filter": company_id,
        "grace_seconds": grace_seconds,
        "dry_run": dry_run,
        "candidates_found": len(candidates),
        "closed_ok": 0,
        "closed_failed": 0,
        "failures": [],
        "samples_closed": [],
    }

    for c in candidates:
        svc = c["svc"]
        ticket = c["ticket"]
        ticket["id"] = svc["ticket_id"]
        sample_entry = {
            "stok_service_id": svc["id"],
            "ticket_id": svc["ticket_id"],
            "type": svc.get("type"),
            "company_id": svc["company_id"],
            "closed_at": c["closed_dt"].isoformat(),
        }
        if dry_run:
            stats["samples_closed"].append({**sample_entry,
                                              "dry_run": True})
            continue
        try:
            res = await late_close_one(svc=svc, ticket=ticket)
            if res.get("ok"):
                stats["closed_ok"] += 1
                stats["samples_closed"].append({**sample_entry,
                                                  "used_items": res.get("used_items")})
                # Marca explicitamente que foi fechado por late_close
                await db.stok_services.update_one(
                    {"id": svc["id"], "company_id": svc["company_id"]},
                    {"$set": {"late_closed": True,
                              "late_closed_at": _now().isoformat(),
                              "late_closed_reason": "auto_close_inicial_falhou"}},
                )
            else:
                stats["closed_failed"] += 1
                stats["failures"].append({**sample_entry,
                                           "reason": res.get("reason"),
                                           "error_reason": res.get("error_reason")})
        except Exception as e:
            stats["closed_failed"] += 1
            stats["failures"].append({**sample_entry,
                                       "exception": f"{type(e).__name__}: {str(e)[:200]}"})
            logger.exception("[late_close] svc=%s ticket=%s exc: %s",
                             svc["id"], svc["ticket_id"], e)

    stats["finished_at"] = _now()
    stats["duration_ms"] = int(
        (stats["finished_at"] - stats["started_at"]).total_seconds() * 1000)

    # Grava relatório (sempre, mesmo em dry-run)
    try:
        await db[LATE_CLOSE_RUNS_COLL].insert_one(dict(stats))
    except Exception as e:
        logger.warning("[late_close] gravar run report falhou: %s", e)

    return stats


# ── Scheduler hook ──────────────────────────────────────────────


async def scheduled_late_close_tick() -> None:
    """Função para agendar via scheduler (1x a cada 5min)."""
    stats = await run_late_close(dry_run=False)
    if stats["candidates_found"] > 0:
        logger.info(
            "[late_close] tick · candidates=%d · closed_ok=%d · failed=%d",
            stats["candidates_found"], stats["closed_ok"],
            stats["closed_failed"],
        )
