"""Training Studio Scheduler — executa os 20 testes de validação automaticamente
em horário configurável (default 03:00 UTC ≈ 00:00 BRT).

Se a média < `alert_threshold`, dispara notificação in-app via `notifications`
collection (a NotificationsBell mostra automaticamente).

Idempotente: usa `last_run_date` (YYYY-MM-DD) pra rodar 1x/dia.

Config (Mongo): `ai_training_schedule` por company_id:
  {
    company_id, enabled, hour_utc (0-23), minute (0-59),
    alert_threshold (float, default 7.5),
    last_run_date, last_run_at, last_average, last_passed, last_failed,
    last_batch_id, last_alert_at,
    updated_at, updated_by
  }
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

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from core import now_iso
from database import db

logger = logging.getLogger("ai_training_scheduler")

CHECK_INTERVAL_SECONDS = 60  # checa a cada 1min
_worker_task: Optional[asyncio.Task] = None


# ---------------------------------------------------------------------------
# Execução do batch
# ---------------------------------------------------------------------------
async def _run_batch(company_id: str) -> Dict[str, Any]:
    """Roda todos os 20 testes de validação para a empresa."""
    # Importação lazy para evitar ciclo com routes/ai_training.py
    from routes.ai_training import _run_isabela, _run_avaliador

    tests = await db.ai_training_tests.find(
        {"company_id": company_id}, {"_id": 0}
    ).sort("number", 1).to_list(100)

    if not tests:
        logger.warning("[ai-training-scheduler] sem testes para %s", company_id)
        return {"total": 0, "passed": 0, "failed": 0, "average_score": 0.0}

    batch_id = f"batch-auto-{uuid.uuid4().hex[:10]}"
    started = now_iso()
    semaphore = asyncio.Semaphore(3)  # menos paralelismo no auto (overnight)

    async def _run_one(t):
        async with semaphore:
            try:
                isa = await _run_isabela(company_id, t["entrada_cliente"])
                response = (isa.get("content") or "").strip()
                evaluation = await _run_avaliador(company_id, t, response)
                score = float(evaluation.get("score_decimal", 0.0))
                passed = bool(evaluation.get("pass", False))
                return {
                    "test_number": t["number"], "test_name": t["name"],
                    "test_categoria": t.get("categoria"),
                    "entrada_cliente": t.get("entrada_cliente"),
                    "isabela_response": response, "evaluation": evaluation,
                    "score": score, "pass": passed, "status": "ok",
                }
            except Exception as e:
                logger.exception("[ai-training-scheduler] erro teste #%d %s",
                                  t["number"], company_id)
                return {
                    "test_number": t["number"], "test_name": t["name"],
                    "score": 0.0, "pass": False, "status": "error",
                    "error": str(e),
                }

    results = await asyncio.gather(*[_run_one(t) for t in tests])
    finished = now_iso()

    # Persiste cada run individualmente (kind=test, automated=True)
    for r in results:
        await db.ai_training_runs.insert_one({
            "id": f"run-{uuid.uuid4().hex[:12]}",
            "company_id": company_id,
            "kind": "test",
            "batch_id": batch_id,
            "automated": True,
            **r,
            "started_at": started,
            "finished_at": finished,
            "created_at": now_iso(),
            "user_id": "scheduler",
            "user_name": "Scheduler (auto)",
        })

    passed = sum(1 for r in results if r.get("pass"))
    total = len(results)
    avg = sum(r.get("score", 0) for r in results) / total if total else 0

    return {
        "batch_id": batch_id,
        "started_at": started,
        "finished_at": finished,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "average_score": round(avg, 2),
        "results": results,
    }


async def _emit_alert(company_id: str, batch: Dict[str, Any],
                       threshold: float) -> None:
    """Cria notificação in-app + log estruturado quando média < threshold."""
    avg = batch.get("average_score", 0)
    passed = batch.get("passed", 0)
    failed = batch.get("failed", 0)
    total = batch.get("total", 0)
    msg = (
        f"Training Studio: nota média {avg}/10 abaixo do limite "
        f"{threshold}/10. Aprovados {passed}/{total}, reprovados {failed}. "
        f"Verifique o histórico para identificar regressões."
    )
    try:
        await db.notifications.insert_one({
            "id": f"ntf-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "kind": "training_drift",
            "severity": "warning",
            "title": "Drift detectado no Training Studio",
            "message": msg,
            "data": {
                "batch_id": batch.get("batch_id"),
                "average_score": avg,
                "passed": passed,
                "failed": failed,
                "threshold": threshold,
            },
            "read": False,
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.warning("[ai-training-scheduler] notification insert falhou: %s", e)
    logger.warning("[ai-training-scheduler] DRIFT ALERT %s avg=%s threshold=%s",
                    company_id, avg, threshold)


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------
async def _process_schedule(cfg: Dict[str, Any]) -> None:
    cid = cfg.get("company_id")
    if not cid or not cfg.get("enabled"):
        return
    now = datetime.now(timezone.utc)
    target_hour = int(cfg.get("hour_utc", 3))
    target_min = int(cfg.get("minute", 0))
    today_iso = now.date().isoformat()
    if cfg.get("last_run_date") == today_iso:
        return
    if now.hour < target_hour or (now.hour == target_hour and now.minute < target_min):
        return

    threshold = float(cfg.get("alert_threshold", 7.5))
    logger.info("[ai-training-scheduler] disparando p/ %s (threshold %s)",
                  cid, threshold)
    batch = await _run_batch(cid)

    update = {
        "last_run_date": today_iso,
        "last_run_at": now_iso(),
        "last_batch_id": batch.get("batch_id"),
        "last_average": batch.get("average_score"),
        "last_passed": batch.get("passed"),
        "last_failed": batch.get("failed"),
        "last_total": batch.get("total"),
    }

    if batch.get("total", 0) > 0 and batch.get("average_score", 0) < threshold:
        await _emit_alert(cid, batch, threshold)
        update["last_alert_at"] = now_iso()
        update["last_alert_avg"] = batch.get("average_score")

    await db.ai_training_schedule.update_one(
        {"company_id": cid}, {"$set": update}
    )


async def _worker_loop():
    while True:
        try:
            cursor = db.ai_training_schedule.find(
                {"enabled": True}, {"_id": 0})
            async for cfg in cursor:
                try:
                    await _process_schedule(cfg)
                except Exception as e:
                    logger.exception(
                        "[ai-training-scheduler] erro %s: %s",
                        cfg.get("company_id"), e)
        except Exception as e:
            logger.exception("[ai-training-scheduler] loop err: %s", e)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def start_worker():
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(_worker_loop())
    logger.info("[ai-training-scheduler] worker iniciado (check %ds)",
                  CHECK_INTERVAL_SECONDS)


def stop_worker():
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()


# ---------------------------------------------------------------------------
# Helpers REST
# ---------------------------------------------------------------------------
async def get_schedule(company_id: str) -> Dict[str, Any]:
    doc = await db.ai_training_schedule.find_one(
        {"company_id": company_id}, {"_id": 0})
    if not doc:
        doc = {
            "company_id": company_id,
            "enabled": False,
            "hour_utc": 3,       # 00:00 BRT
            "minute": 0,
            "alert_threshold": 7.5,
            "last_run_date": None,
            "last_run_at": None,
            "last_average": None,
        }
    return doc


async def save_schedule(company_id: str, data: Dict[str, Any],
                          updated_by: Optional[str] = None) -> Dict[str, Any]:
    payload = {k: v for k, v in data.items() if v is not None}
    payload["updated_at"] = now_iso()
    payload["updated_by"] = updated_by or "system"
    await db.ai_training_schedule.update_one(
        {"company_id": company_id},
        {"$set": payload,
         "$setOnInsert": {"company_id": company_id, "created_at": now_iso()}},
        upsert=True,
    )
    return await get_schedule(company_id)


async def run_now(company_id: str) -> Dict[str, Any]:
    """Dispara manualmente (não altera last_run_date pra não bloquear next)."""
    return await _run_batch(company_id)
