"""Onda C P1 V2.0 — Worker de SLA da Confirmação Patrimonial.

Aprovado CEO 18/06/2026. Runs a cada 30min e implementa:

  Nível 2 — Lembrete (4h sem resposta):
    sent_to_technician AND now - confirmation_sent_at >= 4h AND reminder_count = 0
      → reenvia WhatsApp 1 única vez
      → reminder_sent_at = now
      → reminder_count = 1

  Nível 3 — Escalonamento (24h sem resposta):
    sent_to_technician AND now - confirmation_sent_at >= 24h
      → status = overdue_confirmation
      → escalated_at = now
      → notifica gestor (notification + futuro alerta Watchtower)

Idempotente. Não toca estoque. Apenas auditoria + SLA.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx

from database import db
from services.wa.sidecar import SIDECAR_BASE, _sidecar_headers

logger = logging.getLogger("swap_confirmation.sla")

REMINDER_AFTER = timedelta(hours=4)
ESCALATE_AFTER = timedelta(hours=24)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


async def _send_reminder_whatsapp(evt: Dict[str, Any]) -> tuple[bool, str | None]:
    """Reenvio único. Retorna (ok, error_msg)."""
    phone = (evt.get("confirmation_phone") or "").strip()
    if not phone:
        return False, "no_phone_on_event"
    # Reutiliza os mesmos tokens HMAC do envio original (são determinísticos)
    from routes.swap_confirmation import _hmac_token
    import os as _os
    base_url = _os.environ.get("REACT_APP_BACKEND_URL", "")
    eid = evt["id"]
    links = {
        "confirmed":    f"{base_url}/api/swap-confirmation/respond/{eid}/{_hmac_token(eid, 'confirmed')}/confirmed",
        "disputed":     f"{base_url}/api/swap-confirmation/respond/{eid}/{_hmac_token(eid, 'disputed')}/disputed",
        "needs_review": f"{base_url}/api/swap-confirmation/respond/{eid}/{_hmac_token(eid, 'needs_review')}/needs_review",
    }
    text = (
        "⏰ *Lembrete · Confirmação Patrimonial Pendente*\n\n"
        f"Existe uma confirmação patrimonial pendente referente à OS "
        f"*{evt.get('ticket_id')}*.\n\n"
        f"• ONT anterior: `{evt.get('ont_anterior')}`\n"
        f"• ONT atual:    `{evt.get('ont_atual')}`\n\n"
        "Responda agora:\n\n"
        f"✅ *CONFIRMO*:           {links['confirmed']}\n"
        f"❌ *NÃO HOUVE TROCA*:    {links['disputed']}\n"
        f"🔍 *PRECISO REVISAR*:    {links['needs_review']}\n\n"
        "_Próximo lembrete não será enviado. Após 24h sem resposta o caso é "
        "escalado para o gestor._"
    )
    try:
        async with httpx.AsyncClient(
                headers=_sidecar_headers(), timeout=15.0) as cli:
            r = await cli.post(
                f"{SIDECAR_BASE}/send",
                json={"phone": phone, "text": text},
            )
            try:
                out = r.json()
            except Exception:
                out = {"raw": r.text}
            if r.status_code < 400 and out.get("ok"):
                return True, None
            return False, out.get("error") or f"HTTP {r.status_code}"
    except httpx.HTTPError as e:
        return False, str(e)


async def _process_reminders(now: datetime) -> Dict[str, int]:
    """Nível 2 — encontra eventos elegíveis para lembrete."""
    deadline_iso = (now - REMINDER_AFTER).isoformat()
    cur = db.auto_ont_swap_events.find({
        "status": "sent_to_technician",
        "confirmation_sent_at": {"$lte": deadline_iso, "$ne": None},
        "$or": [
            {"reminder_count": {"$exists": False}},
            {"reminder_count": 0},
            {"reminder_count": None},
        ],
    })
    sent = failed = 0
    async for evt in cur:
        # Não envia lembrete se já passou de 24h (vai pra escalonamento)
        sent_at = _parse_iso(evt.get("confirmation_sent_at"))
        if sent_at and (now - sent_at) >= ESCALATE_AFTER:
            continue
        ok, err = await _send_reminder_whatsapp(evt)
        update_set = {
            "reminder_sent_at": now.isoformat(),
            "reminder_count": 1,
            "reminder_last_error": err,
        }
        await db.auto_ont_swap_events.update_one(
            {"id": evt["id"]},
            {"$set": update_set},
        )
        if ok:
            sent += 1
            logger.info("[sla] reminder enviado evt=%s", evt["id"])
        else:
            failed += 1
            logger.warning("[sla] reminder falhou evt=%s err=%s", evt["id"], err)
    return {"reminders_sent": sent, "reminders_failed": failed}


async def _create_notification_for_managers(evt: Dict[str, Any]) -> int:
    """Cria notification para todos os gestores da empresa."""
    cid = evt.get("company_id")
    managers_cur = db.users.find(
        {"company_id": cid, "role": {"$in": ["gestor", "administrador"]}},
        {"_id": 0, "id": 1, "email": 1},
    )
    count = 0
    now_iso = _now().isoformat()
    async for m in managers_cur:
        from uuid import uuid4
        notif = {
            "id": f"notif-overdue-{uuid4().hex[:12]}",
            "company_id": cid,
            "user_id": m.get("id"),
            "type": "patrimonial_confirmation_overdue",
            "title": "Confirmação patrimonial em atraso",
            "message": (
                f"Técnico {evt.get('technician_id')} não confirmou "
                f"troca de ONT no ticket {evt.get('ticket_id')} em 24h. "
                f"ONT {evt.get('ont_anterior')} → {evt.get('ont_atual')}."
            ),
            "related_swap_event_id": evt["id"],
            "created_at": now_iso,
            "read": False,
            "severity": "warning",
        }
        await db.notifications.insert_one(notif)
        count += 1
    return count


async def _process_escalations(now: datetime) -> Dict[str, int]:
    """Nível 3 — sent_to_technician há ≥24h sem resposta vira overdue."""
    deadline_iso = (now - ESCALATE_AFTER).isoformat()
    cur = db.auto_ont_swap_events.find({
        "status": "sent_to_technician",
        "confirmation_sent_at": {"$lte": deadline_iso, "$ne": None},
    })
    escalated = 0
    notif_total = 0
    async for evt in cur:
        await db.auto_ont_swap_events.update_one(
            {"id": evt["id"], "status": "sent_to_technician"},
            {"$set": {
                "status": "overdue_confirmation",
                "escalated_at": now.isoformat(),
                "escalation_reason": "no_response_24h",
            }},
        )
        n = await _create_notification_for_managers(evt)
        notif_total += n
        escalated += 1
        logger.info("[sla] escalonado evt=%s notif_managers=%s",
                    evt["id"], n)
    return {"escalated": escalated, "notifications_created": notif_total}


# ─────────────────────── Public job entrypoint ───────────────────────────

async def patrimonial_sla_tick() -> Dict[str, Any]:
    """Chamado a cada 30 min pelo apscheduler."""
    now = _now()
    started = now.isoformat()
    r1 = await _process_reminders(now)
    r2 = await _process_escalations(now)
    finished = _now().isoformat()
    stats = {
        "started_at": started,
        "finished_at": finished,
        **r1, **r2,
    }
    try:
        await db.patrimonial_sla_runs.insert_one({**stats,
                                                   "id": f"sla-{started}"})
    except Exception as e:  # noqa: BLE001
        logger.warning("[sla] failed to insert run report: %s", e)
    logger.info("[sla] tick done: %s", stats)
    return stats


# ─────────────────────── Compliance Score ────────────────────────────────

# Pontuação:
#   Resposta no prazo (<4h)          → 100 pontos por evento
#   Resposta após lembrete (4-24h)   →  60 pontos
#   Sem resposta (overdue)           →   0 pontos
#   disputed/needs_review pontual    →  85 pontos (transparência conta)

async def compute_compliance_score(company_id: str,
                                    days: int = 30) -> Dict[str, Any]:
    """Score 0-100 por técnico nos últimos N dias. Inclui ranking."""
    since = _now() - timedelta(days=days)
    cur = db.auto_ont_swap_events.find({
        "company_id": company_id,
        "detected_at": {"$gte": since.isoformat()},
    }, {"_id": 0})

    by_tech: Dict[str, Dict[str, Any]] = {}
    overall_total = 0
    overall_score_sum = 0

    async for evt in cur:
        tid = evt.get("technician_id") or "(sem técnico)"
        b = by_tech.setdefault(tid, {
            "technician_id": tid,
            "events_total": 0,
            "events_confirmed": 0,
            "events_disputed": 0,
            "events_needs_review": 0,
            "events_overdue": 0,
            "events_pending": 0,
            "score_sum": 0,
        })
        b["events_total"] += 1
        status = evt.get("status") or "pending_confirmation"
        sent_at = _parse_iso(evt.get("confirmation_sent_at"))
        resp_at = _parse_iso(evt.get("confirmation_response_at"))
        # Categoriza
        if status == "confirmed":
            b["events_confirmed"] += 1
            pts = 100
            if sent_at and resp_at:
                lag = resp_at - sent_at
                if lag >= REMINDER_AFTER:
                    pts = 60
            b["score_sum"] += pts
        elif status == "disputed":
            b["events_disputed"] += 1
            b["score_sum"] += 85
        elif status == "needs_review":
            b["events_needs_review"] += 1
            b["score_sum"] += 85
        elif status == "overdue_confirmation":
            b["events_overdue"] += 1
            b["score_sum"] += 0
        else:
            # pending_confirmation, sent_to_technician → neutro (não pontua ainda)
            b["events_pending"] += 1
        overall_total += 1

    # Finaliza score por técnico (só conta eventos com decisão)
    out_techs: List[Dict[str, Any]] = []
    tech_ids = list(by_tech.keys())
    name_map: Dict[str, str] = {}
    if tech_ids:
        async for c in db.collaborators.find(
                {"id": {"$in": tech_ids}},
                {"_id": 0, "id": 1, "name": 1}):
            name_map[c["id"]] = c.get("name", c["id"])
    for tid, b in by_tech.items():
        decided = (b["events_confirmed"] + b["events_disputed"]
                   + b["events_needs_review"] + b["events_overdue"])
        score = round(b["score_sum"] / decided, 1) if decided else None
        b["score"] = score
        b["events_decided"] = decided
        b["technician_name"] = name_map.get(tid, tid)
        if score is not None:
            overall_score_sum += b["score_sum"]
        out_techs.append(b)
    # Ordena por score asc (piores primeiro — pra ação)
    out_techs.sort(key=lambda x: (x.get("score") if x.get("score") is not None
                                   else 999, -x["events_total"]))
    overall_decided = sum((t["events_decided"] for t in out_techs), 0)
    overall_score = (round(overall_score_sum / overall_decided, 1)
                     if overall_decided else None)
    return {
        "company_id": company_id,
        "window_days": days,
        "overall_score": overall_score,
        "events_total": overall_total,
        "events_decided": overall_decided,
        "ranking": out_techs,
    }
