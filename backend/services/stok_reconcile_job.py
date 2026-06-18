"""stok_reconcile_job — Cron diário 03:00 UTC.

Roda a reconciliação de stok_services órfãs (ticket inexistente) em
TODAS as empresas. Grava relatório em `stok_reconcile_runs` e gera
alerta se órfãs detectadas exceder o limite.

Política CEO (18/06/2026):
  • Idempotente (rodar 2x não duplica)
  • Sem delete (apenas marca status)
  • Salva relatório por execução
  • Alerta se órfãs > ORPHAN_ALERT_THRESHOLD
"""
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

from database import db

logger = logging.getLogger("ponto.stok_reconcile_job")

ORPHAN_ALERT_THRESHOLD = int(os.environ.get(
    "STOK_ORPHAN_ALERT_THRESHOLD", "20"))
STOK_RECONCILE_RUNS_COLL = "stok_reconcile_runs"
NOTIFICATION_COLL = "ai_notifications"


async def daily_reconcile_orphans_job() -> None:
    """Job agendado: roda em TODAS as empresas, salva relatório, alerta."""
    from scripts.reconcile_orphan_stok_services import reconcile

    started_at = datetime.now(timezone.utc)
    logger.info(
        "[stok_reconcile_job] iniciando reconciliação diária (cron 03:00)")

    # Companies que têm stok_services ativos
    companies = await db.stok_services.distinct(
        "company_id", {"status": "ativo"})
    logger.info("[stok_reconcile_job] empresas com OS ativas: %d",
                 len(companies))

    total_stats: Dict[str, Any] = {
        "started_at": started_at,
        "companies": [],
        "total_scanned": 0,
        "total_orphan_marked": 0,
        "total_valid": 0,
        "alerts_raised": [],
    }

    for cid in companies:
        try:
            stats = await reconcile(company_id=cid, dry_run=False)
        except Exception as e:
            logger.exception(
                "[stok_reconcile_job] reconcile falhou em %s: %s", cid, e)
            total_stats["companies"].append({
                "company_id": cid, "error": str(e)[:200],
            })
            continue

        company_summary = {
            "company_id": cid,
            "scanned": stats["scanned"],
            "valid": stats["valid_ticket"],
            "orphan_marked": stats["orphan_marked"],
        }
        total_stats["companies"].append(company_summary)
        total_stats["total_scanned"] += stats["scanned"]
        total_stats["total_orphan_marked"] += stats["orphan_marked"]
        total_stats["total_valid"] += stats["valid_ticket"]

        # Alerta se passou do limite
        if stats["orphan_marked"] >= ORPHAN_ALERT_THRESHOLD:
            alert = {
                "company_id": cid,
                "orphan_count": stats["orphan_marked"],
                "threshold": ORPHAN_ALERT_THRESHOLD,
            }
            total_stats["alerts_raised"].append(alert)
            await _emit_alert(cid=cid,
                              orphan_count=stats["orphan_marked"])

    total_stats["finished_at"] = datetime.now(timezone.utc)
    total_stats["duration_ms"] = int(
        (total_stats["finished_at"] - started_at).total_seconds() * 1000)

    # Grava o relatório
    try:
        await db[STOK_RECONCILE_RUNS_COLL].insert_one(dict(total_stats))
    except Exception as e:
        logger.warning("[stok_reconcile_job] salvar relatório falhou: %s", e)

    logger.info(
        "[stok_reconcile_job] concluído · empresas=%d · órfãs marcadas=%d · "
        "alertas=%d · duração=%dms",
        len(companies),
        total_stats["total_orphan_marked"],
        len(total_stats["alerts_raised"]),
        total_stats["duration_ms"],
    )


async def _emit_alert(*, cid: str, orphan_count: int) -> None:
    """Insere notificação operacional pro gestor."""
    try:
        await db[NOTIFICATION_COLL].insert_one({
            "company_id": cid,
            "type": "stok_orphan_high",
            "severity": "warning",
            "title": "⚠️ OS órfãs detectadas no estoque",
            "message": (
                f"A reconciliação diária encontrou {orphan_count} OS de estoque "
                f"sem ticket associado (acima do limite {ORPHAN_ALERT_THRESHOLD}). "
                "Elas foram marcadas como 'orfa_sem_ticket' (não apagadas). "
                "Recomendado revisar o que está apagando os tickets."
            ),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "read": False,
            "metadata": {"orphan_count": orphan_count,
                          "threshold": ORPHAN_ALERT_THRESHOLD},
        })
    except Exception as e:
        logger.warning("[stok_reconcile_job] alerta insert falhou: %s", e)
