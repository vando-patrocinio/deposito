"""WhatsApp Baileys — configuracao de horario comercial / auto-reply.

Extraido de `routes/whatsapp_baileys.py` para reduzir o monolito (~5400 LOC).

Endpoints:
- GET    /api/whatsapp-baileys/auto-reply
- PUT    /api/whatsapp-baileys/auto-reply
- GET    /api/whatsapp-baileys/business-hours
- PUT    /api/whatsapp-baileys/business-hours
- GET    /api/whatsapp-baileys/after-hours-metrics
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "whatsapp",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.wa_baileys")
router = APIRouter(prefix="/api/whatsapp-baileys", tags=["whatsapp-baileys"])


# ---------------------------------------------------------------------------
# Auto-reply (toggle global de resposta automatica da IA)
# ---------------------------------------------------------------------------
class AutoReplySettingsIn(BaseModel):
    enabled: bool
    agent_name: Optional[str] = "Jerusa"


@router.get("/auto-reply")
async def get_auto_reply(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await db.aihub_settings.find_one(
        {"company_id": cid, "key": "whatsapp_auto_reply"}, {"_id": 0}
    ) or {"enabled": False, "agent_name": "Jerusa"}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "agent_name": cfg.get("agent_name", "Jerusa"),
        "updated_at": cfg.get("updated_at"),
        "updated_by": cfg.get("updated_by"),
    }


@router.put("/auto-reply")
async def set_auto_reply(payload: AutoReplySettingsIn,
                          user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    await db.aihub_settings.update_one(
        {"company_id": cid, "key": "whatsapp_auto_reply"},
        {"$set": {
            "company_id": cid,
            "key": "whatsapp_auto_reply",
            "enabled": payload.enabled,
            "agent_name": payload.agent_name or "Jerusa",
            "updated_at": now_iso(),
            "updated_by": user.get("email") or user.get("id"),
        }},
        upsert=True,
    )
    logger.info("[wa-baileys] auto-reply %s por %s",
                 "ATIVADO" if payload.enabled else "DESATIVADO",
                 user.get("email"))
    return {"ok": True, "enabled": payload.enabled,
            "agent_name": payload.agent_name or "Jerusa"}


# ---------------------------------------------------------------------------
# Business hours — horário comercial editável por empresa (afeta IA)
# ---------------------------------------------------------------------------
class BusinessHoursIn(BaseModel):
    enabled: Optional[bool] = True
    timezone_offset_hours: Optional[int] = -3
    weekly_schedule: Optional[Dict[str, Any]] = None
    holidays: Optional[List[str]] = None
    fora_de_hora_message: Optional[str] = None
    # Aliases novos (compat)
    schedule: Optional[Dict[str, Any]] = None
    tz_offset: Optional[int] = None
    after_hours_message: Optional[str] = None


@router.get("/business-hours")
async def get_business_hours_endpoint(
    user: dict = Depends(require_role("gestor")),
):
    """Retorna config + status atual (aberto/fechado + próxima abertura).
    Shape compatível com WaBusinessHoursCard (legacy) — campos `enabled`,
    `weekly_schedule`, `timezone_offset_hours`, `holidays`,
    `fora_de_hora_message`."""
    from services.business_hours import (
        get_business_hours, compute_status,
    )
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await get_business_hours(cid)
    st = compute_status(cfg)
    return {
        **cfg,
        "is_outside_now": not st["is_open"],
        "status": st,
    }


@router.put("/business-hours")
async def set_business_hours_endpoint(
    payload: BusinessHoursIn,
    user: dict = Depends(require_role("gestor")),
):
    """Atualiza horário comercial. Aceita campos legacy ou novos."""
    from services.business_hours import (
        set_business_hours, compute_status,
    )
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await set_business_hours(
        cid,
        payload.model_dump(exclude_none=True),
        by=user.get("email") or user.get("id"),
    )
    st = compute_status(cfg)
    logger.info("[wa-baileys] business_hours atualizado por %s",
                  user.get("email"))
    return {
        "ok": True, "config": cfg,
        "is_outside_now": not st["is_open"],
        "status": st,
    }


@router.get("/after-hours-metrics")
async def get_after_hours_metrics(
    days: int = 7,
    user: dict = Depends(require_role("gestor")),
):
    """Métricas de conversas atendidas pela IA FORA DO HORÁRIO comercial.

    Retorna: total, by_day (sparkline), top_agents, samples (últimas msgs).
    Usa `auto_reply=True` em `aihub_wa_messages` cruzado com a janela
    de business hours.
    """
    from services.business_hours import (
        get_business_hours, compute_status,
    )
    cid = user.get("company_id") or DEMO_COMPANY_ID
    days = max(1, min(int(days or 7), 90))
    since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since_dt.isoformat()

    bh_cfg = await get_business_hours(cid)
    tz_off = bh_cfg.get("timezone_offset_hours", -3)
    tz = timezone(timedelta(hours=tz_off))

    # Pull all auto_reply outbound da janela
    cursor = db.aihub_wa_messages.find(
        {
            "company_id": cid, "direction": "outbound", "auto_reply": True,
            "created_at": {"$gte": since_iso},
        },
        {"_id": 0, "phone": 1, "created_at": 1, "agent_name": 1,
         "text": 1},
    ).sort([("created_at", -1)]).limit(5000)

    # Agrega
    by_day: Dict[str, int] = {}
    by_agent: Dict[str, int] = {}
    after_hours_phones: set = set()
    in_hours_phones: set = set()
    samples: list = []
    after_hours_total = 0
    in_hours_total = 0

    async for m in cursor:
        ts = m.get("created_at")
        if not ts:
            continue
        try:
            dt_utc = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            continue
        dt_local = dt_utc.astimezone(tz)
        st = compute_status(bh_cfg, now_local=dt_local)
        is_after_hours = not st["is_open"]
        ph = m.get("phone")
        ag = m.get("agent_name") or "—"
        day_key = dt_local.strftime("%Y-%m-%d")
        if is_after_hours:
            after_hours_total += 1
            by_day[day_key] = by_day.get(day_key, 0) + 1
            by_agent[ag] = by_agent.get(ag, 0) + 1
            if ph:
                after_hours_phones.add(ph)
            if len(samples) < 8:
                samples.append({
                    "phone": ph,
                    "agent_name": ag,
                    "text": (m.get("text") or "")[:160],
                    "at": dt_local.isoformat(timespec="minutes"),
                })
        else:
            in_hours_total += 1
            if ph:
                in_hours_phones.add(ph)

    # Sparkline normalizada (últimos N dias, todos preenchidos)
    today_local = datetime.now(timezone.utc).astimezone(tz)
    sparkline = []
    for i in range(days - 1, -1, -1):
        d = today_local - timedelta(days=i)
        k = d.strftime("%Y-%m-%d")
        sparkline.append({"date": k, "label": d.strftime("%d/%m"),
                            "count": by_day.get(k, 0)})

    top_agents = sorted(by_agent.items(), key=lambda x: -x[1])[:5]
    cur_status = compute_status(bh_cfg)

    return {
        "window_days": days,
        "is_open_now": cur_status["is_open"],
        "next_open_human": cur_status.get("next_open_human"),
        "after_hours_total_messages": after_hours_total,
        "in_hours_total_messages": in_hours_total,
        "after_hours_unique_clients": len(after_hours_phones),
        "in_hours_unique_clients": len(in_hours_phones),
        "by_day": sparkline,
        "top_agents": [{"agent_name": a, "count": c}
                          for a, c in top_agents],
        "samples": samples,
    }
