"""
briefing_dispatcher.py — Sprint final V5.0
Envia daily briefing automaticamente via WhatsApp (Baileys) ou,
quando WA estiver bloqueado, persiste como simulação com status correto.
NÃO mente. NÃO mascara.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict

from database import db
from services import autonomous_engine as eng
from services import transport_check as tx
from services import wa_dispatcher


def _fmt(v: float) -> str:
    return f"R$ {(v or 0):,.2f}"


def _build_message(b: Dict[str, Any], slot: str) -> str:
    q = b["questions"]
    s = b["autonomy_score"]
    head = {
        "07h": "📊 SmartProv · Briefing 07h",
        "12h": "⚡ SmartProv · Alerta Operacional 12h",
        "18h": "🌙 SmartProv · Fechamento Executivo 18h",
    }[slot]
    return (
        f"{head}\n\n"
        f"Autonomy: *{s['score']}%* ({s['classification'].replace('_', ' ')})\n"
        f"Gerado: {_fmt(q['1_generated_today_BRL'])}\n"
        f"Protegido: {_fmt(q['3_protected_today_BRL'])}\n"
        f"Perdido: {_fmt(q['4_lost_today_BRL'])}\n"
        f"Aprendizados: {q['5_learnings_today']}\n"
        f"Planejado p/ amanhã: {q['6_planned_for_tomorrow_actions']} ações · "
        f"{_fmt(q['6_planned_for_tomorrow_BRL'])}\n"
        f"Melhor que ontem? {'✓ SIM' if q['7_better_than_yesterday'] else '✗ NÃO'}\n"
        f"Prova: hoje {_fmt(q['8_proof']['today_BRL'])} vs "
        f"ontem {_fmt(q['8_proof']['yesterday_BRL'])} "
        f"(Δ {_fmt(q['8_proof']['diff_BRL'])})"
    )


async def dispatch(company_id: str, slot: str = "07h") -> Dict[str, Any]:
    """Gera briefing e envia. Se WA bloqueado, persiste status real."""
    briefing = await eng.daily_briefing(company_id)
    text = _build_message(briefing, slot)

    transport = await tx.wa_status(company_id)
    import os
    gestor = os.environ.get("PRESIDENTE_IA_GESTOR_PHONE", "")

    out = {
        "company_id": company_id, "slot": slot,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "text": text,
        "transport": transport["status"],
        "blockers": transport["blockers"],
        "delivery_status": "pending",
    }

    if not transport["can_send"] or not gestor:
        out["delivery_status"] = "blocked_transport"
        out["reason"] = "WA não OPEN ou PRESIDENTE_IA_GESTOR_PHONE ausente"
    else:
        send = await wa_dispatcher.send_text(
            company_id=company_id, to=gestor, text=text)
        if send.get("ok"):
            out["delivery_status"] = "delivered"
            out["wa_id"] = send.get("id")
        else:
            out["delivery_status"] = "blocked_transport"
            out["reason"] = send.get("reason")

    await db.motor_ia_briefings.insert_one(dict(out))
    return out
