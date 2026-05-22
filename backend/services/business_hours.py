"""Business hours service — horário comercial dinâmico por empresa.

Configuração persistida em `aihub_settings` (key=business_hours):
{
  "company_id": "co-demo",
  "key": "business_hours",
  "tz_offset": -3,                      # BRT
  "schedule": {
    "0": {"open": "08:00", "close": "18:00", "active": true},   # seg (Mon=0)
    "1": {"open": "08:00", "close": "18:00", "active": true},   # ter
    "2": {"open": "08:00", "close": "18:00", "active": true},
    "3": {"open": "08:00", "close": "18:00", "active": true},
    "4": {"open": "08:00", "close": "18:00", "active": true},
    "5": {"open": "08:00", "close": "13:00", "active": true},   # sáb
    "6": {"active": false}                                      # dom
  },
  "after_hours_message": "Atendimento humano só amanhã às 8h, mas eu já posso resolver tudo aqui pelo chat 🙂"
}

API:
- get_business_hours(company_id) → dict (sempre retorna config, com defaults)
- compute_status(cfg, now_brt=None) → {is_open, status, next_open_iso, message}
- format_for_prompt(company_id) → string injetável no system prompt
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, Optional

from database import db


_DEFAULTS = {
    "tz_offset": -3,
    "schedule": {
        "0": {"open": "08:00", "close": "18:00", "active": True},
        "1": {"open": "08:00", "close": "18:00", "active": True},
        "2": {"open": "08:00", "close": "18:00", "active": True},
        "3": {"open": "08:00", "close": "18:00", "active": True},
        "4": {"open": "08:00", "close": "18:00", "active": True},
        "5": {"open": "08:00", "close": "13:00", "active": True},
        "6": {"active": False},
    },
    "after_hours_message": (
        "Nosso atendimento humano está fora do horário comercial agora. "
        "Mas eu já posso resolver várias coisas aqui pelo chat — me conta "
        "no que posso te ajudar? 🙂"
    ),
}

_WEEKDAYS_PT = ["segunda", "terça", "quarta", "quinta", "sexta",
                  "sábado", "domingo"]


def _norm_cfg(raw: Optional[dict]) -> Dict[str, Any]:
    """Garante que o cfg tem todos os campos com defaults."""
    out = {**_DEFAULTS}
    if not raw:
        return out
    out["tz_offset"] = raw.get("tz_offset", _DEFAULTS["tz_offset"])
    out["after_hours_message"] = raw.get("after_hours_message") or \
        _DEFAULTS["after_hours_message"]
    sched = raw.get("schedule") or {}
    merged = {**_DEFAULTS["schedule"]}
    for k, v in sched.items():
        if str(k) in merged and isinstance(v, dict):
            merged[str(k)] = {**merged[str(k)], **v}
    out["schedule"] = merged
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
        "tz_offset": norm["tz_offset"],
        "schedule": norm["schedule"],
        "after_hours_message": norm["after_hours_message"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": by,
    }
    await db.aihub_settings.update_one(
        {"company_id": company_id, "key": "business_hours"},
        {"$set": doc},
        upsert=True,
    )
    return norm


def _parse_hhmm(s: str) -> Optional[time]:
    try:
        h, m = s.split(":")
        return time(int(h), int(m))
    except Exception:
        return None


def compute_status(cfg: Dict[str, Any],
                       now_local: Optional[datetime] = None) -> Dict[str, Any]:
    """Calcula se está aberto AGORA. Retorna:
    {
      is_open: bool,
      status: "open" | "before_open" | "after_close" | "closed_today",
      now_iso: str,
      open_today: str|None,        # "08:00" se hoje é dia ativo
      close_today: str|None,
      next_open_iso: str|None,     # próximo horário de abertura
      next_open_human: str|None,   # "amanhã às 8h" / "segunda às 8h"
    }
    """
    cfg = _norm_cfg(cfg)
    tz = timezone(timedelta(hours=cfg["tz_offset"]))
    if now_local is None:
        now_local = datetime.now(timezone.utc).astimezone(tz)
    weekday = now_local.weekday()
    schedule = cfg["schedule"]
    today = schedule.get(str(weekday)) or {}
    today_active = bool(today.get("active"))
    open_t = _parse_hhmm(today.get("open") or "") if today_active else None
    close_t = _parse_hhmm(today.get("close") or "") if today_active else None

    is_open = False
    status = "closed_today"
    if today_active and open_t and close_t:
        cur_t = now_local.time()
        if cur_t < open_t:
            status = "before_open"
        elif open_t <= cur_t < close_t:
            status = "open"
            is_open = True
        else:
            status = "after_close"

    # Próximo horário de abertura
    next_open_iso = None
    next_open_human = None
    if status == "before_open" and open_t:
        nxt = now_local.replace(hour=open_t.hour, minute=open_t.minute,
                                  second=0, microsecond=0)
        next_open_iso = nxt.isoformat(timespec="minutes")
        next_open_human = f"hoje às {open_t.strftime('%H:%M')}"
    elif status in ("after_close", "closed_today"):
        for offset in range(1, 8):
            d = now_local + timedelta(days=offset)
            wd = d.weekday()
            day_cfg = schedule.get(str(wd)) or {}
            if day_cfg.get("active") and day_cfg.get("open"):
                op = _parse_hhmm(day_cfg["open"])
                if op:
                    nxt = d.replace(hour=op.hour, minute=op.minute,
                                      second=0, microsecond=0)
                    next_open_iso = nxt.isoformat(timespec="minutes")
                    if offset == 1:
                        prefix = "amanhã"
                    else:
                        prefix = _WEEKDAYS_PT[wd]
                    next_open_human = (f"{prefix} ({d.strftime('%d/%m')}) "
                                          f"às {op.strftime('%H:%M')}")
                    break

    return {
        "is_open": is_open,
        "status": status,
        "now_iso": now_local.isoformat(timespec="minutes"),
        "open_today": today.get("open") if today_active else None,
        "close_today": today.get("close") if today_active else None,
        "today_active": today_active,
        "next_open_iso": next_open_iso,
        "next_open_human": next_open_human,
        "after_hours_message": cfg["after_hours_message"],
    }


async def format_for_prompt(company_id: str) -> str:
    """Bloco pronto pra injetar no system prompt da IA."""
    cfg = await get_business_hours(company_id)
    st = compute_status(cfg)
    if st["is_open"]:
        return (
            "=== HORÁRIO COMERCIAL ===\n"
            f"Status: ABERTO (até {st['close_today']})\n"
            "Atendimento humano disponível agora pra escalar se você "
            "precisar transferir uma conversa complexa."
        )
    motivo = {
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
    }.get(st["status"], "FORA DE HORÁRIO")
    return (
        "=== HORÁRIO COMERCIAL ===\n"
        f"Status: {motivo}\n"
        f"Mensagem oficial pra cliente que pedir humano: "
        f"\"{st['after_hours_message']}\"\n"
        "REGRA: você está sozinha agora — não há humano pra escalar nesta "
        "janela. Resolva o que conseguir, e se for caso inadiável, "
        "registre o pedido e prometa retorno na próxima abertura "
        f"({st['next_open_human'] or 'em breve'})."
    )
