"""ISABELLA COMMANDERS WORKER — varredura agendada autônoma.

Executa em background:
  • A cada 30 min: scan dos 5 Commanders (Churn/Dunning/Revenue/Twin/Expansion)
  • Diariamente às 09h (UTC-3 ~ 12h UTC): reunião do Conselho Executivo IA
  • A cada 60 min: expira oportunidades antigas (status='expired')

Tolerante a falhas: catch global por loop, log e retoma na próxima iteração.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from database import db
from services import (isabella_churn, isabella_conselho, isabella_dunning,
                        isabella_expansion, isabella_revenue, isabella_twin)
from services.isabella_opportunities import (ensure_indexes as opp_indexes,
                                                expire_old)
from services import isabella_outcome_engine as outcome_eng
from services import isabella_learning as learning_eng
from services import isabella_executive_memory as memory_eng

log = logging.getLogger("ponto.isabella_commanders_worker")

SCAN_INTERVAL_SEC = 30 * 60
COUNCIL_HOUR_UTC = 12  # ~09h America/Sao_Paulo
EXPERIENCE_HOUR_UTC = 10  # ~07h America/Sao_Paulo


async def _active_companies() -> list[str]:
    cids = await db.companies.distinct("id")
    return [c for c in cids if c]


async def _run_scans_for(company_id: str) -> dict:
    out = {"company_id": company_id}
    for name, fn in (("churn", isabella_churn.scan_company),
                       ("dunning", isabella_dunning.scan_company),
                       ("revenue", isabella_revenue.scan_company),
                       ("twin", isabella_twin.scan_company),
                       ("expansion", isabella_expansion.scan_company)):
        try:
            out[name] = await fn(company_id)
        except Exception as e:
            log.warning("[commanders_worker] %s/%s falhou: %s",
                        company_id, name, e)
            out[name] = {"error": str(e)}
    return out


async def isabella_commanders_worker() -> None:
    """Loop autônomo dos Commanders."""
    await asyncio.sleep(75)  # boot
    try:
        await opp_indexes()
        await outcome_eng.ensure_indexes()
        await learning_eng.ensure_indexes()
        await memory_eng.ensure_indexes()
    except Exception:
        pass
    log.info("[commanders_worker] iniciado (a cada %ss)", SCAN_INTERVAL_SEC)
    last_council_day: str | None = None
    last_experience_day: str | None = None
    while True:
        try:
            companies = await _active_companies()
            for cid in companies:
                try:
                    await _run_scans_for(cid)
                except Exception as e:
                    log.warning("[commanders_worker] scan %s: %s", cid, e)
            now = datetime.now(timezone.utc)
            today = now.strftime("%Y-%m-%d")
            # Experience Commander — varredura diária de
            # aniversários / level-ups / indicações / incidentes resolvidos
            if now.hour >= EXPERIENCE_HOUR_UTC and last_experience_day != today:
                try:
                    from services import isabella_experience as exp_eng
                    for cid in companies:
                        try:
                            r = await exp_eng.scan_company(cid)
                            if (r.get("totals") or {}).get("total", 0):
                                log.info(
                                    "[commanders_worker] experience %s: %s",
                                    cid, r["totals"])
                        except Exception as e:
                            log.warning(
                                "[commanders_worker] experience %s: %s",
                                cid, e)
                    last_experience_day = today
                except Exception as e:
                    log.warning("[commanders_worker] experience scan: %s", e)
            # Resolução de outcomes (job diário)
            try:
                r = await outcome_eng.resolve_due()
                if r.get("resolved", 0):
                    log.info("[commanders_worker] outcomes resolvidos: %s",
                              {k: r[k] for k in ("resolved", "success",
                                                  "failure", "inconclusive")})
            except Exception as e:
                log.warning("[commanders_worker] resolve_due: %s", e)
            # Reunião do conselho 1x por dia
            if now.hour >= COUNCIL_HOUR_UTC and last_council_day != today:
                for cid in companies:
                    try:
                        await isabella_conselho.hold_meeting(cid)
                    except Exception as e:
                        log.warning("[commanders_worker] council %s: %s",
                                     cid, e)
                # Auditoria de precisão (mesma janela diária)
                try:
                    from services import isabella_audit as audit_eng
                    for cid in companies:
                        await audit_eng.precision_audit_run(cid, days=30)
                except Exception as e:
                    log.warning("[commanders_worker] precision_audit: %s", e)
                last_council_day = today
            # Expira oportunidades antigas
            try:
                await expire_old()
            except Exception:
                pass
        except Exception as e:
            log.exception("[commanders_worker] loop: %s", e)
        await asyncio.sleep(SCAN_INTERVAL_SEC)
