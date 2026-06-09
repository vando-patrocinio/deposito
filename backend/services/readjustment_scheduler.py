"""Scheduler diário de Reajuste Anual.

REGRAS:
- Roda 1x ao dia (default 03:00 UTC).
- Lê `readjustment_schedule_config` por empresa:
    {
      company_id, enabled, auto_apply,
      notify_days_before (lista de ints, ex.: [30, 7, 1]),
      check_hour_utc (int 0-23)
    }
- Se `auto_apply=true` → aplica reajustes em cascata para clientes vencidos.
- Para cada cliente com virada dentro de X dias, cria notificação em
  `readjustment_notifications` (consumido pelo painel do gestor).

NÃO envia WhatsApp aqui — esse é responsabilidade do módulo Billing
(disparo_boleto ou módulo dedicado).
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from database import db
from services.readjustment import (
    _add_years, _parse_iso, apply_readjustment,
    compute_pending_anniversaries,
)
from services.readjustment_notifications import notify_upcoming_readjustments

logger = logging.getLogger("readjustment_scheduler")

CHECK_INTERVAL_SECONDS = 60 * 60  # checa a cada 1h (aplica 1x/dia por empresa)
_worker_task: Optional[asyncio.Task] = None


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


async def _get_company_config(company_id: str) -> Dict:
    cfg = await db.readjustment_schedule_config.find_one(
        {"company_id": company_id}, {"_id": 0},
    )
    if cfg:
        return cfg
    return {
        "company_id": company_id,
        "enabled": True,
        "auto_apply": False,                    # default: só notifica
        "notify_days_before": [30, 7, 1],
        "check_hour_utc": 3,                    # 03:00 UTC ~ 00:00 BRT
        "whatsapp_notify": True,                # avisa cliente via WhatsApp
        "whatsapp_days_ahead": 30,              # 30d antes da virada (Anatel)
        "last_run_date": None,
    }


async def _notify_pending(sub: Dict, days_before: int) -> None:
    """Cria entry em `readjustment_notifications` (gestor vê no painel).

    Idempotente por (subscriber_id, anniversary, days_before).
    """
    inst = _parse_iso(sub.get("installation_date"))
    last = _parse_iso(sub.get("last_readjustment_at"))
    base = last or inst
    if not base:
        return

    today = datetime.now(timezone.utc)
    # Próxima virada futura
    next_anniv = None
    for n in range(1, 30):
        a = _add_years(base, n)
        if a > today:
            next_anniv = a
            break
    if not next_anniv:
        return
    days_to = (next_anniv.date() - today.date()).days
    if days_to != days_before:
        return

    key = f"{sub['id']}-{next_anniv.date().isoformat()}-{days_before}"
    exists = await db.readjustment_notifications.find_one({"id": key})
    if exists:
        return

    await db.readjustment_notifications.insert_one({
        "id": key,
        "subscriber_id": sub["id"],
        "subscriber_name": sub.get("name"),
        "company_id": sub.get("company_id"),
        "anniversary_date": next_anniv.date().isoformat(),
        "days_before": days_before,
        "current_price": sub.get("plan_price"),
        "created_at": today.isoformat(),
        "read": False,
        "kind": "upcoming_readjustment",
    })
    logger.info("[readjustment-scheduler] notif criada %s (%dd antes)",
                sub.get("name"), days_before)


async def _process_company(cfg: Dict) -> None:
    cid = cfg["company_id"]
    if not cfg.get("enabled", True):
        return
    if cfg.get("last_run_date") == _today_iso():
        return  # já rodou hoje

    auto = bool(cfg.get("auto_apply"))
    notify_days = cfg.get("notify_days_before") or [30, 7, 1]
    whatsapp_enabled = bool(cfg.get("whatsapp_notify", True))
    whatsapp_days_ahead = int(cfg.get("whatsapp_days_ahead", 30))
    applied_count = 0
    notified_count = 0
    wa_sent = 0

    cursor = db.subscribers.find(
        {"company_id": cid,
         "installation_date": {"$exists": True, "$ne": None},
         "status": {"$in": ["ATIVO", "ativo"]}},
        {"_id": 0},
    )
    async for sub in cursor:
        pending = compute_pending_anniversaries(sub)

        # AUTO-APPLY: vencidos
        if pending and auto:
            try:
                r = await apply_readjustment(sub, actor="cron")
                if r.get("applied"):
                    applied_count += 1
            except Exception as e:
                logger.exception(
                    "[readjustment-scheduler] apply falhou %s: %s",
                    sub.get("name"), e)

        # NOTIFICAÇÕES INTERNAS (painel gestor): próximas viradas
        for d in notify_days:
            try:
                await _notify_pending(sub, int(d))
                notified_count += 1
            except Exception as e:
                logger.exception(
                    "[readjustment-scheduler] notify falhou %s: %s",
                    sub.get("name"), e)

    # NOTIFICAÇÃO WHATSAPP AO CLIENTE (cumpre Anatel: 30d antes da virada)
    # Idempotente — não envia 2x ao mesmo cliente pra mesma virada.
    if whatsapp_enabled:
        try:
            wa_result = await notify_upcoming_readjustments(
                cid, days_ahead=whatsapp_days_ahead)
            wa_sent = wa_result.get("sent", 0)
        except Exception as e:
            logger.exception(
                "[readjustment-scheduler] WhatsApp falhou %s: %s", cid, e)

    await db.readjustment_schedule_config.update_one(
        {"company_id": cid},
        {"$set": {
            "last_run_date": _today_iso(),
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_applied": applied_count,
            "last_notified": notified_count,
            "last_whatsapp_sent": wa_sent,
        }},
        upsert=True,
    )
    logger.info(
        "[readjustment-scheduler] %s: aplicados=%d notificados=%d wa=%d",
        cid, applied_count, notified_count, wa_sent)


async def _worker_loop():
    while True:
        try:
            now = datetime.now(timezone.utc)
            # Lista empresas com config OU usa todas as companies do banco
            companies = set()
            async for c in db.readjustment_schedule_config.find(
                    {"enabled": True}, {"_id": 0, "company_id": 1}):
                if c.get("company_id"):
                    companies.add(c["company_id"])
            # Sempre incluir companies que têm subscribers
            try:
                cids = await db.subscribers.distinct("company_id")
                for c in cids:
                    if c:
                        companies.add(c)
            except Exception:
                pass

            for cid in companies:
                cfg = await _get_company_config(cid)
                target_hour = int(cfg.get("check_hour_utc") or 3)
                if now.hour != target_hour:
                    continue  # só roda na hora configurada
                try:
                    await _process_company(cfg)
                except Exception as e:
                    logger.exception(
                        "[readjustment-scheduler] erro empresa %s: %s",
                        cid, e)
        except Exception as e:
            logger.exception("[readjustment-scheduler] loop err: %s", e)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def start_worker():
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(_worker_loop())
    logger.info("[readjustment-scheduler] worker iniciado (check %ds)",
                CHECK_INTERVAL_SECONDS)


def stop_worker():
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
