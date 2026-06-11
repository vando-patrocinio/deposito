"""Business hours service — horário comercial dinâmico por empresa.

Persiste em `aihub_settings` (key=business_hours) usando a shape
compatível com `WaBusinessHoursCard` (legacy):

{
  "company_id": "co-demo",
  "key": "business_hours",
  "enabled": true,                              # toggle global on/off
  "timezone_offset_hours": -3,                  # BRT
  "weekly_schedule": {
    "0": {"enabled": false},                    # 0=domingo (legacy)
    "1": {"enabled": true, "open": "08:00", "close": "18:00"},
    ...
    "6": {"enabled": true, "open": "08:00", "close": "13:00"}
  },
  "holidays": ["2026-12-25", ...],
  "fora_de_hora_message": "..."
}

(IMPORTANTE: legacy usa 0=Domingo / 1..6=Seg..Sáb — SEM mapeamento
ISO. weekday() do Python tem 0=Mon, então convertemos.)

API:
- get_business_hours(company_id) → dict (com defaults)
- set_business_hours(company_id, payload, by) → dict salvo
- compute_status(cfg, now_local=None) → status atual
- format_for_prompt(company_id) → bloco de prompt para a IA
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

from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, Optional

from database import db


# Legacy: 0=Dom, 1=Seg, 2=Ter, 3=Qua, 4=Qui, 5=Sex, 6=Sáb
_LEGACY_NAMES = ["domingo", "segunda", "terça", "quarta", "quinta",
                  "sexta", "sábado"]

_DEFAULTS = {
    "enabled": True,
    "timezone_offset_hours": -3,
    "weekly_schedule": {
        "0": {"enabled": False, "open": "09:00", "close": "13:00"},
        "1": {"enabled": True, "open": "08:00", "close": "18:00"},
        "2": {"enabled": True, "open": "08:00", "close": "18:00"},
        "3": {"enabled": True, "open": "08:00", "close": "18:00"},
        "4": {"enabled": True, "open": "08:00", "close": "18:00"},
        "5": {"enabled": True, "open": "08:00", "close": "18:00"},
        "6": {"enabled": True, "open": "08:00", "close": "13:00"},
    },
    "holidays": [],
    "fora_de_hora_message": (
        "Olá! Nosso atendimento humano está fora do horário comercial "
        "agora 🙂 Mas eu já posso resolver várias coisas aqui pelo chat — "
        "me conta no que posso te ajudar?"
    ),
}


def _norm_cfg(raw: Optional[dict]) -> Dict[str, Any]:
    """Normaliza cfg aceitando shapes novo (schedule/active/tz_offset/
    after_hours_message) e legacy (weekly_schedule/enabled/
    timezone_offset_hours/fora_de_hora_message).
    """
    out: Dict[str, Any] = {
        "enabled": _DEFAULTS["enabled"],
        "timezone_offset_hours": _DEFAULTS["timezone_offset_hours"],
        "weekly_schedule": {**_DEFAULTS["weekly_schedule"]},
        "holidays": [],
        "fora_de_hora_message": _DEFAULTS["fora_de_hora_message"],
    }
    if not raw:
        return out

    if "enabled" in raw:
        out["enabled"] = bool(raw["enabled"])
    if "timezone_offset_hours" in raw:
        out["timezone_offset_hours"] = int(raw["timezone_offset_hours"])
    elif "tz_offset" in raw:
        out["timezone_offset_hours"] = int(raw["tz_offset"])

    sched = raw.get("weekly_schedule") or raw.get("schedule") or {}
    for k, v in sched.items():
        kk = str(k)
        if kk not in out["weekly_schedule"]:
            continue
        if not isinstance(v, dict):
            continue
        cur = dict(out["weekly_schedule"][kk])
        # aceita "active" como alias de "enabled"
        if "enabled" in v:
            cur["enabled"] = bool(v["enabled"])
        elif "active" in v:
            cur["enabled"] = bool(v["active"])
        if v.get("open"):
            cur["open"] = str(v["open"])
        if v.get("close"):
            cur["close"] = str(v["close"])
        out["weekly_schedule"][kk] = cur

    if isinstance(raw.get("holidays"), list):
        out["holidays"] = [str(h) for h in raw["holidays"]
                              if isinstance(h, str)]
    if raw.get("fora_de_hora_message"):
        out["fora_de_hora_message"] = str(raw["fora_de_hora_message"])
    elif raw.get("after_hours_message"):
        out["fora_de_hora_message"] = str(raw["after_hours_message"])

    return out


async def get_business_hours(company_id: str) -> Dict[str, Any]:
    raw = await db.aihub_settings.find_one(
        {"company_id": company_id, "key": "business_hours"},
        {"_id": 0},
    )
    return _norm_cfg(raw)


async def set_business_hours(company_id: str, cfg: Dict[str, Any],
                                  by: str = "system") -> Dict[str, Any]:
    norm = _norm_cfg(cfg)
    doc = {
        "company_id": company_id,
        "key": "business_hours",
        **norm,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": by,
    }
    await db.aihub_settings.update_one(
        {"company_id": company_id, "key": "business_hours"},
        {"$set": doc},
        upsert=True,
    )
    return norm


def _parse_hhmm(s: Optional[str]) -> Optional[time]:
    if not s:
        return None
    try:
        h, m = s.split(":")
        return time(int(h), int(m))
    except Exception:
        return None


def _legacy_key_for(now_local: datetime) -> str:
    """Legacy weekly_schedule é indexada com 0=Dom..6=Sáb.
    Python weekday() é 0=Seg..6=Dom. Convertemos: (wd+1)%7."""
    return str((now_local.weekday() + 1) % 7)


def compute_status(cfg: Dict[str, Any],
                       now_local: Optional[datetime] = None) -> Dict[str, Any]:
    """Calcula status atual. Retorna:
      is_open, status (open/before_open/after_close/closed_today/disabled/holiday),
      now_iso, open_today, close_today, today_active,
      next_open_iso, next_open_human, fora_de_hora_message
    """
    cfg = _norm_cfg(cfg)
    tz = timezone(timedelta(hours=cfg["timezone_offset_hours"]))
    if now_local is None:
        now_local = datetime.now(timezone.utc).astimezone(tz)

    # Toggle global desligado
    if not cfg["enabled"]:
        return {
            "is_open": False, "status": "disabled",
            "now_iso": now_local.isoformat(timespec="minutes"),
            "open_today": None, "close_today": None,
            "today_active": False,
            "next_open_iso": None, "next_open_human": None,
            "fora_de_hora_message": cfg["fora_de_hora_message"],
        }

    today_iso = now_local.strftime("%Y-%m-%d")
    is_holiday = today_iso in (cfg.get("holidays") or [])

    today_key = _legacy_key_for(now_local)
    today = cfg["weekly_schedule"].get(today_key) or {}
    today_active = bool(today.get("enabled")) and not is_holiday
    open_t = _parse_hhmm(today.get("open")) if today_active else None
    close_t = _parse_hhmm(today.get("close")) if today_active else None

    is_open = False
    status = "holiday" if is_holiday else "closed_today"
    if today_active and open_t and close_t:
        cur_t = now_local.time()
        if cur_t < open_t:
            status = "before_open"
        elif open_t <= cur_t < close_t:
            status = "open"
            is_open = True
        else:
            status = "after_close"

    next_open_iso = None
    next_open_human = None
    if status == "before_open" and open_t:
        nxt = now_local.replace(hour=open_t.hour, minute=open_t.minute,
                                  second=0, microsecond=0)
        next_open_iso = nxt.isoformat(timespec="minutes")
        next_open_human = f"hoje às {open_t.strftime('%H:%M')}"
    elif status in ("after_close", "closed_today", "holiday"):
        for offset in range(1, 8):
            d = now_local + timedelta(days=offset)
            d_iso = d.strftime("%Y-%m-%d")
            if d_iso in (cfg.get("holidays") or []):
                continue
            day_cfg = cfg["weekly_schedule"].get(_legacy_key_for(d)) or {}
            if day_cfg.get("enabled") and day_cfg.get("open"):
                op = _parse_hhmm(day_cfg["open"])
                if op:
                    nxt = d.replace(hour=op.hour, minute=op.minute,
                                      second=0, microsecond=0)
                    next_open_iso = nxt.isoformat(timespec="minutes")
                    if offset == 1:
                        prefix = "amanhã"
                    else:
                        prefix = _LEGACY_NAMES[(d.weekday() + 1) % 7]
                    next_open_human = (f"{prefix} ({d.strftime('%d/%m')}) "
                                          f"às {op.strftime('%H:%M')}")
                    break

    return {
        "is_open": is_open, "status": status,
        "now_iso": now_local.isoformat(timespec="minutes"),
        "open_today": today.get("open") if today_active else None,
        "close_today": today.get("close") if today_active else None,
        "today_active": today_active,
        "next_open_iso": next_open_iso,
        "next_open_human": next_open_human,
        "fora_de_hora_message": cfg["fora_de_hora_message"],
    }


async def format_for_prompt(company_id: str) -> str:
    cfg = await get_business_hours(company_id)
    st = compute_status(cfg)
    if st["is_open"]:
        return (
            "=== HORÁRIO COMERCIAL ===\n"
            f"Status: ABERTO (até {st['close_today']})\n"
            "Atendimento humano disponível agora pra escalar se você "
            "precisar transferir uma conversa complexa."
        )
    motivo_map = {
        "before_open": (
            f"FORA DE HORÁRIO (abre {st['next_open_human'] or 'em breve'})"
        ),
        "after_close": (
            f"FORA DE HORÁRIO — já fechamos às {st['close_today'] or '?'}. "
            f"Próxima abertura: {st['next_open_human'] or 'em breve'}"
        ),
        "closed_today": (
            f"FECHADO HOJE. Próxima abertura: "
            f"{st['next_open_human'] or 'em breve'}"
        ),
        "holiday": (
            f"FECHADO POR FERIADO HOJE. Próxima abertura: "
            f"{st['next_open_human'] or 'em breve'}"
        ),
        "disabled": (
            "ATENDIMENTO HUMANO DESATIVADO no momento (você é o único canal)"
        ),
    }
    motivo = motivo_map.get(st["status"], "FORA DE HORÁRIO")
    return (
        "=== HORÁRIO COMERCIAL ===\n"
        f"Status: {motivo}\n"
        f"Mensagem oficial pra cliente que pedir humano: "
        f"\"{st['fora_de_hora_message']}\"\n"
        "REGRA: você está sozinha agora — não há humano pra escalar nesta "
        "janela. Resolva o que conseguir, e se for caso inadiável, "
        "registre o pedido e prometa retorno na próxima abertura "
        f"({st['next_open_human'] or 'em breve'})."
    )
